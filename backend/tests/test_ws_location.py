"""Testes do `LOCATION_BATCH` via WebSocket.

Diferente do REST, aqui não existe sessão de requisição: o handler abre uma
sessão curta própria e faz `commit()` explícito. Estes testes cobrem o contrato
(sucesso silencioso, erro em envelope) sem tocar em PostgreSQL.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, cast
from uuid import UUID, uuid4

from app.api.ws.ptt import _handle_text
from app.core.config import Settings
from app.core.container import Services
from app.schemas.location import LocationPoint
from app.services.connection_manager import Connection
from tests.helpers import FakeWebSocket, wait_until


class FakeSession:
    """Sessão mínima: só registra `commit()`/`rollback()`."""

    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class FakeSessionFactory:
    """Assíncrono como `async_sessionmaker`: `async with factory() as session`."""

    def __init__(self, session: FakeSession) -> None:
        self.session = session

    def __call__(self) -> FakeSessionFactory:
        return self

    async def __aenter__(self) -> FakeSession:
        return self.session

    async def __aexit__(self, *exc: object) -> bool:
        return False


class FakeLocationService:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[UUID, list[LocationPoint]]] = []

    async def ingest_batch(self, *, user_id: UUID, points: list[LocationPoint]) -> Any:
        if self.fail:
            raise RuntimeError("banco indisponível")
        self.calls.append((user_id, list(points)))
        return None


def build_services(
    settings: Settings, *, service: FakeLocationService, session: FakeSession
) -> Services:
    db = type("FakeDb", (), {"session_factory": FakeSessionFactory(session)})()
    return Services(
        settings=settings,
        db=cast(Any, db),
        connections=cast(Any, None),
        fcm=cast(Any, None),
        apns=cast(Any, None),
        ptt=cast(Any, None),
        auth_limiter=cast(Any, None),
        location_factory=cast(Any, lambda _session: service),
    )


def frame(points: list[dict[str, Any]]) -> str:
    return json.dumps({"v": 1, "type": "LOCATION_BATCH", "data": {"points": points}})


def point_payload(seq: int = 1) -> dict[str, Any]:
    return {
        "lat": -23.5505,
        "lng": -46.6333,
        "client_seq": seq,
        "recorded_at": "2026-10-28T12:00:00+00:00",
    }


def connection(user_id: UUID) -> Connection:
    """Conexão com o writer task ativo — é ele que esvazia as filas."""
    conn = Connection(user_id=user_id, websocket=cast(Any, FakeWebSocket()))
    conn.start()
    return conn


def sent(conn: Connection) -> list[str]:
    return cast(FakeWebSocket, conn.websocket).sent_text


async def next_frame(conn: Connection) -> dict[str, Any]:
    await wait_until(lambda: bool(sent(conn)))
    return cast(dict[str, Any], json.loads(sent(conn)[-1]))


# --------------------------------------------------------------------------- sucesso
async def test_location_batch_is_ingested_and_committed(settings: Settings) -> None:
    user_id = uuid4()
    service, session = FakeLocationService(), FakeSession()
    conn = connection(user_id)
    services = build_services(settings, service=service, session=session)

    try:
        await _handle_text(conn, services, frame([point_payload(1), point_payload(2)]))

        assert session.committed is True
        assert len(service.calls) == 1
        called_user, points = service.calls[0]
        assert called_user == user_id
        assert [point.client_seq for point in points] == [1, 2]

        # Sucesso não gera ACK: silêncio é o contrato. Damos tempo ao writer
        # para provar que nada foi enfileirado, em vez de afirmar no vazio.
        await asyncio.sleep(0.02)
        assert sent(conn) == []
    finally:
        await conn.stop()


# --------------------------------------------------------------------------- falhas
async def test_location_batch_with_invalid_payload_returns_error(settings: Settings) -> None:
    service, session = FakeLocationService(), FakeSession()
    conn = connection(uuid4())
    services = build_services(settings, service=service, session=session)

    try:
        await _handle_text(conn, services, frame([{"lat": 999, "lng": 0}]))

        assert service.calls == []
        assert session.committed is False
        payload = await next_frame(conn)
        assert payload["data"]["code"] == "BAD_ENVELOPE"
    finally:
        await conn.stop()


async def test_location_batch_without_points_returns_error(settings: Settings) -> None:
    service, session = FakeLocationService(), FakeSession()
    conn = connection(uuid4())
    services = build_services(settings, service=service, session=session)

    try:
        await _handle_text(conn, services, json.dumps({"v": 1, "type": "LOCATION_BATCH"}))

        payload = await next_frame(conn)
        assert payload["data"]["code"] == "BAD_ENVELOPE"
    finally:
        await conn.stop()


async def test_location_batch_failure_returns_internal_error(settings: Settings) -> None:
    """O cliente reenfileira o lote; o socket não pode cair por erro de banco."""
    service, session = FakeLocationService(fail=True), FakeSession()
    conn = connection(uuid4())
    services = build_services(settings, service=service, session=session)

    try:
        await _handle_text(conn, services, frame([point_payload()]))

        assert session.committed is False
        payload = await next_frame(conn)
        assert payload["data"]["code"] == "INTERNAL"
    finally:
        await conn.stop()
