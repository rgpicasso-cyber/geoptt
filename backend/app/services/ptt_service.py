"""Regras de negócio do Push-To-Talk (half-duplex).

Invariantes:
  * **um locutor por canal** — garantido no servidor, nunca no cliente;
  * o estado de fala é **efêmero** (memória). Reiniciar o processo libera os canais;
  * áudio nunca toca o banco: `relay_audio` só usa dados já em cache no estado;
  * FCM é disparado **uma vez por pressão** (no `PTT_DOWN`), jamais por chunk.

Concorrência: o event loop é single-threaded e todas as mutações de estado abaixo
ocorrem em trechos **sem `await`** entre checagem e escrita — logo são atômicas.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.repositories.ptt_channel_repository import ChannelInfo, PttChannelRepository
from app.schemas.ws import WsErrorCode, WsMessageType, envelope
from app.services.connection_manager import ConnectionManager
from app.services.fcm_service import FcmService

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- erros
class PttError(Exception):
    """Erro de regra de negócio traduzível em envelope `ERROR`."""

    code: WsErrorCode = WsErrorCode.INTERNAL
    message: str = "erro interno"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)
        if message:
            self.message = message


class PttChannelNotFoundError(PttError):
    code = WsErrorCode.CHANNEL_NOT_FOUND
    message = "canal não encontrado"


class PttChannelInactiveError(PttError):
    code = WsErrorCode.CHANNEL_INACTIVE
    message = "canal inativo"


class PttNotMemberError(PttError):
    code = WsErrorCode.NOT_A_MEMBER
    message = "usuário não é membro do canal"


class PttCannotSpeakError(PttError):
    code = WsErrorCode.CANNOT_SPEAK
    message = "usuário sem permissão de fala neste canal"


class PttBusyError(PttError):
    code = WsErrorCode.INTERNAL  # substituído no envelope por PTT_BUSY
    message = "canal ocupado"

    def __init__(self, speaker_id: UUID | None) -> None:
        super().__init__()
        self.speaker_id = speaker_id


class PttNotSpeakingError(PttError):
    code = WsErrorCode.NOT_SPEAKING
    message = "usuário não é o locutor atual"


# --------------------------------------------------------------------------- estado
@dataclass(slots=True)
class _ChannelState:
    """Estado efêmero de um canal ocupado."""

    call_id: UUID
    speaker_id: UUID
    recipients: tuple[UUID, ...]
    started_at: datetime
    session_id: UUID | None = None
    frames: int = 0
    bytes_sent: int = 0
    watchdog: asyncio.Task[None] | None = field(default=None, repr=False)


class PttService:
    def __init__(
        self,
        *,
        manager: ConnectionManager,
        fcm: FcmService,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._manager = manager
        self._fcm = fcm
        self._session_factory = session_factory
        self._settings = settings
        self._states: dict[UUID, _ChannelState] = {}
        self._background: set[asyncio.Task[Any]] = set()

    # ------------------------------------------------------------------ consulta
    @property
    def busy_channels(self) -> dict[str, str]:
        """Mapa `channel_id -> speaker_id` (diagnóstico)."""
        return {
            str(channel_id): str(state.speaker_id) for channel_id, state in self._states.items()
        }

    def current_speaker(self, channel_id: UUID) -> UUID | None:
        state = self._states.get(channel_id)
        return state.speaker_id if state is not None else None

    # ------------------------------------------------------------------ PTT_DOWN
    async def start_talking(self, *, channel_id: UUID, user_id: UUID) -> UUID:
        """Assume o canal. Retorna o `call_id` da fala.

        Levanta `PttBusyError` se outro usuário estiver falando.
        """
        info = await self._load_channel(channel_id)
        member = info.member(user_id)

        # --- validações (ordem importa para mensagens de erro precisas) ---
        if not info.is_active:
            raise PttChannelInactiveError
        if member is None:
            raise PttNotMemberError
        if not member.can_speak:
            raise PttCannotSpeakError

        existing = self._states.get(channel_id)
        if existing is not None:
            raise PttBusyError(existing.speaker_id)

        # --- trecho atômico: nenhum await até o estado estar consistente ---
        call_id = uuid4()
        state = _ChannelState(
            call_id=call_id,
            speaker_id=user_id,
            recipients=info.member_ids,
            started_at=datetime.now(UTC),
        )
        self._states[channel_id] = state

        # --- efeitos (a partir daqui pode haver await) ---
        self._manager.broadcast(
            info.member_ids,
            envelope(
                WsMessageType.PTT_SPEAKER_START,
                data={
                    "channel_id": str(channel_id),
                    "user_id": str(user_id),
                    "call_id": str(call_id),
                },
            ),
        )

        self._spawn(self._record_session_start(channel_id, call_id, user_id, state))
        self._spawn(self._wake_offline_members(info, sender_id=user_id, call_id=call_id))
        state.watchdog = asyncio.create_task(
            self._watchdog(channel_id, call_id), name=f"ptt-watchdog-{channel_id}"
        )

        logger.info(
            "ptt start",
            extra={
                "event": "ptt_start",
                "user_id": str(user_id),
                "channel_id": str(channel_id),
            },
        )
        return call_id

    # ------------------------------------------------------------------ PTT_UP
    async def stop_talking(self, *, channel_id: UUID, user_id: UUID) -> None:
        state = self._states.get(channel_id)
        if state is None or state.speaker_id != user_id:
            raise PttNotSpeakingError
        await self._release(channel_id, state, reason="user_released")

    # ------------------------------------------------------------------ áudio
    async def relay_audio(self, *, channel_id: UUID, sender_id: UUID, payload: bytes) -> int:
        """Repassa um chunk Opus para os membros online. Zero I/O de banco."""
        state = self._states.get(channel_id)
        if state is None or state.speaker_id != sender_id:
            # Áudio de quem não é o locutor é descartado silenciosamente.
            return 0

        state.frames += 1
        state.bytes_sent += len(payload)

        recipients = tuple(uid for uid in state.recipients if uid != sender_id)
        return self._manager.broadcast_audio(recipients, payload)

    # ------------------------------------------------------------------ interno
    async def _load_channel(self, channel_id: UUID) -> ChannelInfo:
        async with self._session_factory() as session:
            info = await PttChannelRepository(session).get_channel_info(channel_id)
        if info is None:
            raise PttChannelNotFoundError
        return info

    async def _release(self, channel_id: UUID, state: _ChannelState, *, reason: str) -> None:
        # Trecho atômico: remove o estado antes de qualquer await.
        if self._states.get(channel_id) is state:
            del self._states[channel_id]

        watchdog = state.watchdog
        state.watchdog = None
        if watchdog is not None and watchdog is not asyncio.current_task():
            watchdog.cancel()

        self._manager.broadcast(
            state.recipients,
            envelope(
                WsMessageType.PTT_SPEAKER_STOP,
                data={
                    "channel_id": str(channel_id),
                    "user_id": str(state.speaker_id),
                    "call_id": str(state.call_id),
                    "reason": reason,
                },
            ),
        )

        logger.info(
            "ptt stop",
            extra={
                "event": "ptt_stop",
                "user_id": str(state.speaker_id),
                "channel_id": str(channel_id),
            },
        )

        if state.session_id is not None:
            self._spawn(self._record_session_end(state))

    async def _watchdog(self, channel_id: UUID, call_id: UUID) -> None:
        """Libera o canal se o locutor esquecer o `PTT_UP`."""
        try:
            await asyncio.sleep(self._settings.ptt_speaker_timeout_seconds)
        except asyncio.CancelledError:
            return

        state = self._states.get(channel_id)
        if state is None or state.call_id != call_id:
            return

        logger.warning(
            "ptt speaker timeout — liberando canal",
            extra={
                "event": "ptt_timeout",
                "user_id": str(state.speaker_id),
                "channel_id": str(channel_id),
            },
        )
        await self._release(channel_id, state, reason="timeout")

    async def _wake_offline_members(
        self, info: ChannelInfo, *, sender_id: UUID, call_id: UUID
    ) -> None:
        """Dispara FCM para membros sem socket ativo — uma vez por pressão."""
        offline = [
            member
            for member in info.members
            if member.user_id != sender_id and not self._manager.is_online(member.user_id)
        ]
        if not offline:
            return

        results = await asyncio.gather(
            *(
                self._fcm.send_wakeup(
                    user_id=member.user_id,
                    fcm_token=member.fcm_token,
                    platform=member.platform,
                    channel_id=info.id,
                    sender_id=sender_id,
                    call_id=call_id,
                )
                for member in offline
            ),
            return_exceptions=True,
        )

        for member, result in zip(offline, results, strict=True):
            if isinstance(result, BaseException):
                logger.warning(
                    "erro inesperado ao acordar membro",
                    extra={"event": "fcm_wakeup_error", "user_id": str(member.user_id)},
                    exc_info=result,
                )
            elif result.invalid_token:
                # O chamador (camada HTTP) limpa users.fcm_token; aqui só sinalizamos.
                logger.info(
                    "token FCM inválido detectado no fan-out",
                    extra={"event": "fcm_invalid_token", "user_id": str(member.user_id)},
                )

    async def _record_session_start(
        self, channel_id: UUID, call_id: UUID, speaker_id: UUID, state: _ChannelState
    ) -> None:
        """Auditoria best-effort: falha de banco não pode derrubar o áudio."""
        try:
            async with self._session_factory() as session:
                session_id = await PttChannelRepository(session).start_session(
                    channel_id=channel_id, speaker_id=speaker_id, started_at=state.started_at
                )
                await session.commit()
        except Exception:
            logger.warning(
                "falha ao registrar início de sessão PTT",
                extra={"event": "ptt_session_write_failed", "channel_id": str(channel_id)},
                exc_info=True,
            )
            return
        # Só associa se a mesma fala ainda estiver ativa.
        if self._states.get(channel_id) is state and state.call_id == call_id:
            state.session_id = session_id

    async def _record_session_end(self, state: _ChannelState) -> None:
        if state.session_id is None:
            return
        try:
            async with self._session_factory() as session:
                await PttChannelRepository(session).end_session(
                    state.session_id,
                    ended_at=datetime.now(UTC),
                    frames_sent=state.frames,
                    bytes_sent=state.bytes_sent,
                )
                await session.commit()
        except Exception:
            logger.warning(
                "falha ao registrar fim de sessão PTT",
                extra={"event": "ptt_session_write_failed", "session_id": str(state.session_id)},
                exc_info=True,
            )

    def _spawn(self, coro: Any) -> None:
        """Executa em background sem perder exceções (logadas no callback)."""
        task: asyncio.Task[Any] = asyncio.create_task(coro)
        self._background.add(task)
        task.add_done_callback(self._on_background_done)

    def _on_background_done(self, task: asyncio.Task[Any]) -> None:
        self._background.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:  # pragma: no cover - já logado no ponto de origem
            logger.warning("tarefa de background falhou", exc_info=exc)

    async def shutdown(self) -> None:
        """Cancela watchdogs e tarefas pendentes no shutdown da aplicação."""
        for state in list(self._states.values()):
            if state.watchdog is not None:
                state.watchdog.cancel()
        self._states.clear()

        pending = [task for task in self._background if not task.done()]
        for task in pending:
            task.cancel()
        for task in pending:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
