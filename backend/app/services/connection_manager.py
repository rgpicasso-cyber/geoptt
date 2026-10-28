"""Gerenciador de conexões WebSocket — fonte de verdade da presença.

Responsabilidades:
  * mapear `user_id -> conexões` (um usuário pode ter mais de um dispositivo vivo);
  * garantir **uma única escrita concorrente** por socket (Starlette não permite
    `send` simultâneo), usando um writer task dedicado por conexão;
  * aplicar *backpressure* correto para áudio: fila curta com descarte do frame
    mais antigo (áudio é perecível) enquanto mensagens de controle têm prioridade
    e nunca são descartadas silenciosamente.

Não conhece banco de dados nem FCM — apenas transporte.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final, cast
from uuid import UUID

from starlette.websockets import WebSocket, WebSocketState

logger = logging.getLogger(__name__)

DEFAULT_CONTROL_QUEUE_SIZE: Final = 256
DEFAULT_AUDIO_QUEUE_SIZE: Final = 16


class FrameKind(StrEnum):
    TEXT = "text"
    BYTES = "bytes"


Frame = tuple[FrameKind, str | bytes]


@dataclass(eq=False, slots=True)
class Connection:
    """Uma conexão WebSocket autenticada."""

    user_id: UUID
    websocket: WebSocket
    device_id: str | None = None
    connected_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    # Canal em que este cliente está falando (half-duplex: no máximo um por vez).
    active_channel_id: UUID | None = None

    closed: bool = False
    dropped_audio_frames: int = 0
    control_queue_size: int = DEFAULT_CONTROL_QUEUE_SIZE
    audio_queue_size: int = DEFAULT_AUDIO_QUEUE_SIZE

    _control: asyncio.Queue[Frame] = field(init=False, repr=False)
    _audio: asyncio.Queue[Frame] = field(init=False, repr=False)
    _writer: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _send_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        self._control = asyncio.Queue(maxsize=self.control_queue_size)
        self._audio = asyncio.Queue(maxsize=self.audio_queue_size)

    # ------------------------------------------------------------------ ciclo de vida
    def start(self) -> None:
        """Inicia o writer task. Deve ser chamado de dentro do event loop."""
        if self._writer is None or self._writer.done():
            self._writer = asyncio.create_task(
                self._writer_loop(), name=f"ws-writer-{self.user_id}"
            )

    async def stop(self) -> None:
        """Encerra o writer e fecha o socket de forma idempotente."""
        self.closed = True
        writer, self._writer = self._writer, None
        if writer is not None and not writer.done():
            writer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await writer
        await self._close_socket()

    async def _close_socket(self) -> None:
        if self.websocket.client_state is WebSocketState.CONNECTED:
            with contextlib.suppress(Exception):
                async with self._send_lock:
                    await self.websocket.close()

    # ------------------------------------------------------------------ enfileiramento
    def enqueue_json(self, payload: Mapping[str, Any]) -> bool:
        """Enfileira mensagem de controle (nunca descartada). Retorna False se morto."""
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        return self._enqueue(self._control, (FrameKind.TEXT, raw), drop_oldest=False)

    def enqueue_audio(self, payload: bytes) -> bool:
        """Enfileira frame Opus, descartando o mais antigo se a fila encher."""
        return self._enqueue(self._audio, (FrameKind.BYTES, payload), drop_oldest=True)

    def _enqueue(self, queue: asyncio.Queue[Frame], frame: Frame, *, drop_oldest: bool) -> bool:
        if self.closed:
            return False
        try:
            queue.put_nowait(frame)
        except asyncio.QueueFull:
            if not drop_oldest:
                # Cliente não consome controle: conexão inutilizável, encerra.
                logger.warning(
                    "control queue full; closing connection",
                    extra={"event": "ws_backpressure_close", "user_id": str(self.user_id)},
                )
                self.closed = True
                return False
            with contextlib.suppress(asyncio.QueueEmpty):
                queue.get_nowait()
                self.dropped_audio_frames += 1
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(frame)
        return True

    # ------------------------------------------------------------------ writer
    async def _writer_loop(self) -> None:
        try:
            while not self.closed:
                frame = await self._next_frame()
                if frame is None:
                    return
                kind, payload = frame
                try:
                    async with self._send_lock:
                        if kind is FrameKind.TEXT:
                            await self.websocket.send_text(cast(str, payload))
                        else:
                            await self.websocket.send_bytes(cast(bytes, payload))
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.info(
                        "websocket send failed; dropping connection",
                        extra={"event": "ws_send_failed", "user_id": str(self.user_id)},
                    )
                    self.closed = True
                    return
        except asyncio.CancelledError:
            raise
        finally:
            self.closed = True

    async def _next_frame(self) -> Frame | None:
        """Próximo frame, com prioridade para o canal de controle."""
        while not self.closed:
            with contextlib.suppress(asyncio.QueueEmpty):
                return self._control.get_nowait()

            control_task = asyncio.create_task(self._control.get())
            audio_task = asyncio.create_task(self._audio.get())
            try:
                done, _ = await asyncio.wait(
                    {control_task, audio_task}, return_when=asyncio.FIRST_COMPLETED
                )
            finally:
                for task in (control_task, audio_task):
                    if not task.done():
                        task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await task

            if control_task in done:
                # Se o áudio também saiu, devolve o frame para não perdê-lo.
                if audio_task in done and not audio_task.cancelled():
                    with contextlib.suppress(asyncio.QueueFull):
                        self._audio.put_nowait(audio_task.result())
                return control_task.result()
            return audio_task.result()
        return None


class ConnectionManager:
    """Registro de conexões ativas por usuário."""

    def __init__(
        self,
        *,
        control_queue_size: int = DEFAULT_CONTROL_QUEUE_SIZE,
        audio_queue_size: int = DEFAULT_AUDIO_QUEUE_SIZE,
    ) -> None:
        self._connections: dict[UUID, set[Connection]] = {}
        self._lock = asyncio.Lock()
        self._control_queue_size = control_queue_size
        self._audio_queue_size = audio_queue_size
        self._total_registered = 0
        self._total_dropped_audio = 0

    # ------------------------------------------------------------------ registro
    async def register(
        self, websocket: WebSocket, user_id: UUID, *, device_id: str | None = None
    ) -> Connection:
        connection = Connection(
            user_id=user_id,
            websocket=websocket,
            device_id=device_id,
            control_queue_size=self._control_queue_size,
            audio_queue_size=self._audio_queue_size,
        )
        async with self._lock:
            self._connections.setdefault(user_id, set()).add(connection)
            self._total_registered += 1
        connection.start()
        logger.info(
            "ws connected",
            extra={"event": "ws_connect", "user_id": str(user_id), "device_id": device_id},
        )
        return connection

    async def unregister(self, connection: Connection) -> None:
        async with self._lock:
            bucket = self._connections.get(connection.user_id)
            if bucket is not None:
                bucket.discard(connection)
                if not bucket:
                    self._connections.pop(connection.user_id, None)
        self._total_dropped_audio += connection.dropped_audio_frames
        await connection.stop()
        logger.info(
            "ws disconnected",
            extra={"event": "ws_disconnect", "user_id": str(connection.user_id)},
        )

    # ------------------------------------------------------------------ consultas
    def is_online(self, user_id: UUID) -> bool:
        return any(not conn.closed for conn in self._connections.get(user_id, ()))

    def connections_of(self, user_id: UUID) -> tuple[Connection, ...]:
        return tuple(conn for conn in self._connections.get(user_id, ()) if not conn.closed)

    def online_user_ids(self) -> frozenset[UUID]:
        return frozenset(
            user_id
            for user_id, bucket in self._connections.items()
            if any(not conn.closed for conn in bucket)
        )

    @property
    def stats(self) -> dict[str, int]:
        return {
            "online_users": len(self.online_user_ids()),
            "connections": sum(len(bucket) for bucket in self._connections.values()),
            "total_registered": self._total_registered,
            "dropped_audio_frames": self._total_dropped_audio,
        }

    # ------------------------------------------------------------------ envio
    def send_to_user(self, user_id: UUID, payload: Mapping[str, Any]) -> int:
        """Enfileira mensagem de controle para todos os dispositivos do usuário."""
        return sum(1 for conn in self.connections_of(user_id) if conn.enqueue_json(payload))

    def send_audio_to_user(self, user_id: UUID, payload: bytes) -> int:
        return sum(1 for conn in self.connections_of(user_id) if conn.enqueue_audio(payload))

    def broadcast(self, user_ids: Iterable[UUID], payload: Mapping[str, Any]) -> int:
        """Enfileira mensagem de controle para vários usuários. Retorna nº de sockets."""
        delivered = 0
        for user_id in user_ids:
            delivered += self.send_to_user(user_id, payload)
        return delivered

    def broadcast_audio(self, user_ids: Iterable[UUID], payload: bytes) -> int:
        delivered = 0
        for user_id in user_ids:
            delivered += self.send_audio_to_user(user_id, payload)
        return delivered

    # ------------------------------------------------------------------ shutdown
    async def close_all(self) -> None:
        async with self._lock:
            connections = [conn for bucket in self._connections.values() for conn in bucket]
            self._connections.clear()
        if connections:
            await asyncio.gather(*(conn.stop() for conn in connections), return_exceptions=True)
        logger.info("all websocket connections closed", extra={"event": "ws_shutdown"})
