"""Utilitários de teste compartilhados (sem dependência de banco ou rede)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from starlette.websockets import WebSocketState


class FakeWebSocket:
    """Substituto mínimo de `starlette.websockets.WebSocket`.

    Implementa apenas o que o código de produção usa: `query_params`,
    `headers`, `receive`, `send_text`, `send_bytes`, `close` e `client_state`.
    """

    def __init__(
        self,
        *,
        query_params: MutableMapping[str, str] | None = None,
        headers: MutableMapping[str, str] | None = None,
        incoming: list[dict[str, Any]] | None = None,
        block_on_receive: bool = False,
    ) -> None:
        self.query_params: MutableMapping[str, str] = dict(query_params or {})
        self.headers: MutableMapping[str, str] = {
            key.lower(): value for key, value in (headers or {}).items()
        }
        self.client_state = WebSocketState.CONNECTED

        self.sent_text: list[str] = []
        self.sent_bytes: list[bytes] = []
        self.close_calls: list[tuple[int, str]] = []

        self._incoming: list[dict[str, Any]] = list(incoming or [])
        self._block_on_receive = block_on_receive
        self._blocker = asyncio.Event()

    # ------------------------------------------------------------------ envio
    async def send_text(self, data: str) -> None:
        self.sent_text.append(data)

    async def send_bytes(self, data: bytes) -> None:
        self.sent_bytes.append(data)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.close_calls.append((code, reason))
        self.client_state = WebSocketState.DISCONNECTED

    # ------------------------------------------------------------------ recepção
    async def receive(self) -> dict[str, Any]:
        if self._incoming:
            return self._incoming.pop(0)
        if self._block_on_receive:
            # Simula cliente silencioso: só retorna no cancelamento/timeout.
            await self._blocker.wait()
        return {"type": "websocket.disconnect", "code": 1000}

    def disconnect_now(self) -> None:
        """Libera um `receive()` bloqueado (usado em teardown)."""
        self._blocker.set()


async def wait_until(
    predicate: Callable[[], bool],
    *,
    timeout: float = 2.0,
    interval: float = 0.005,
) -> None:
    """Aguarda até `predicate()` ser verdadeiro, ou falha por timeout."""

    async def _poll() -> None:
        while not predicate():
            await asyncio.sleep(interval)

    await asyncio.wait_for(_poll(), timeout=timeout)


def run(coro: Awaitable[Any]) -> Any:  # pragma: no cover - conveniência
    return asyncio.get_event_loop().run_until_complete(coro)
