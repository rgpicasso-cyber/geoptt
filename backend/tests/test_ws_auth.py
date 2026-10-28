"""Testes do handshake WebSocket e da extração de `channel_id`.

Não há servidor HTTP: o handler é exercitado com um `FakeWebSocket`.
"""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest
from fastapi import WebSocketDisconnect

from app.api.ws import ptt as ws_module
from app.api.ws.ptt import (
    _authenticate,
    _AuthHandshakeError,
    _extract_channel_id,
)
from app.core.config import Settings
from app.core.security import create_access_token
from app.schemas.ws import (
    CLOSE_AUTH_TIMEOUT,
    CLOSE_UNAUTHORIZED,
    WsEnvelope,
    WsErrorCode,
)
from app.services.connection_manager import Connection
from tests.helpers import FakeWebSocket


def _auth_frame(token: str) -> str:
    return json.dumps({"v": 1, "type": "AUTH", "data": {"token": token}})


# --------------------------------------------------------------------------- sucesso
async def test_authenticate_with_query_token(settings: Settings) -> None:
    user_id = uuid4()
    token = create_access_token(subject=user_id, settings=settings)
    ws = FakeWebSocket(query_params={"token": token})

    assert await _authenticate(ws, settings) == user_id  # type: ignore[arg-type]


async def test_authenticate_with_auth_frame(settings: Settings) -> None:
    user_id = uuid4()
    token = create_access_token(subject=user_id, settings=settings)
    ws = FakeWebSocket(incoming=[{"type": "websocket.receive", "text": _auth_frame(token)}])

    assert await _authenticate(ws, settings) == user_id  # type: ignore[arg-type]


async def test_query_token_takes_precedence_over_frame(settings: Settings) -> None:
    user_id = uuid4()
    token = create_access_token(subject=user_id, settings=settings)
    other_user = uuid4()
    other_token = create_access_token(subject=other_user, settings=settings)

    ws = FakeWebSocket(
        query_params={"token": token},
        incoming=[{"type": "websocket.receive", "text": _auth_frame(other_token)}],
    )

    assert await _authenticate(ws, settings) == user_id  # type: ignore[arg-type]


# --------------------------------------------------------------------------- falhas
async def test_authenticate_times_out_without_auth(settings: Settings) -> None:
    ws = FakeWebSocket(block_on_receive=True)

    with pytest.raises(_AuthHandshakeError) as excinfo:
        await _authenticate(ws, settings)  # type: ignore[arg-type]

    assert excinfo.value.code == CLOSE_AUTH_TIMEOUT


async def test_authenticate_rejects_invalid_query_token(settings: Settings) -> None:
    ws = FakeWebSocket(query_params={"token": "token-invalido-mas-longo"})

    with pytest.raises(_AuthHandshakeError) as excinfo:
        await _authenticate(ws, settings)  # type: ignore[arg-type]

    assert excinfo.value.code == CLOSE_UNAUTHORIZED


async def test_authenticate_rejects_refresh_token(settings: Settings) -> None:
    from app.core.security import create_refresh_token

    refresh = create_refresh_token(subject=uuid4(), settings=settings)
    ws = FakeWebSocket(query_params={"token": refresh})

    with pytest.raises(_AuthHandshakeError) as excinfo:
        await _authenticate(ws, settings)  # type: ignore[arg-type]

    assert excinfo.value.code == CLOSE_UNAUTHORIZED


async def test_authenticate_requires_auth_as_first_frame(settings: Settings) -> None:
    ws = FakeWebSocket(
        incoming=[{"type": "websocket.receive", "text": json.dumps({"v": 1, "type": "PING"})}]
    )

    with pytest.raises(_AuthHandshakeError) as excinfo:
        await _authenticate(ws, settings)  # type: ignore[arg-type]

    assert excinfo.value.code == CLOSE_UNAUTHORIZED
    assert "AUTH" in excinfo.value.reason


async def test_authenticate_rejects_binary_first_frame(settings: Settings) -> None:
    ws = FakeWebSocket(incoming=[{"type": "websocket.receive", "bytes": b"\x00opus"}])

    with pytest.raises(_AuthHandshakeError) as excinfo:
        await _authenticate(ws, settings)  # type: ignore[arg-type]

    assert excinfo.value.code == CLOSE_UNAUTHORIZED


async def test_authenticate_rejects_malformed_envelope(settings: Settings) -> None:
    ws = FakeWebSocket(incoming=[{"type": "websocket.receive", "text": "{nao-e-json"}])

    with pytest.raises(_AuthHandshakeError) as excinfo:
        await _authenticate(ws, settings)  # type: ignore[arg-type]

    assert excinfo.value.code == CLOSE_UNAUTHORIZED


async def test_authenticate_rejects_short_token_payload(settings: Settings) -> None:
    ws = FakeWebSocket(
        incoming=[
            {
                "type": "websocket.receive",
                "text": json.dumps({"v": 1, "type": "AUTH", "data": {"token": "abc"}}),
            }
        ]
    )

    with pytest.raises(_AuthHandshakeError) as excinfo:
        await _authenticate(ws, settings)  # type: ignore[arg-type]

    assert excinfo.value.code == CLOSE_UNAUTHORIZED


async def test_authenticate_propagates_disconnect(settings: Settings) -> None:
    ws = FakeWebSocket(incoming=[{"type": "websocket.disconnect", "code": 1000}])

    with pytest.raises(WebSocketDisconnect):
        await _authenticate(ws, settings)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- channel_id
def _connection(user_id: UUID) -> Connection:
    return Connection(user_id=user_id, websocket=FakeWebSocket())  # type: ignore[arg-type]


def test_extract_channel_id_from_envelope() -> None:
    channel_id = uuid4()
    conn = _connection(uuid4())
    envelope = WsEnvelope.model_validate(
        {"v": 1, "type": "PTT_DOWN", "data": {"channel_id": str(channel_id)}}
    )

    assert _extract_channel_id(conn, envelope) == channel_id


def test_extract_channel_id_uses_fallback_for_ptt_up() -> None:
    fallback = uuid4()
    conn = _connection(uuid4())
    envelope = WsEnvelope.model_validate({"v": 1, "type": "PTT_UP", "data": {}})

    assert _extract_channel_id(conn, envelope, fallback=fallback) == fallback


def test_extract_channel_id_reports_error_when_missing() -> None:
    conn = _connection(uuid4())
    envelope = WsEnvelope.model_validate({"v": 1, "type": "PTT_DOWN", "data": {}})

    assert _extract_channel_id(conn, envelope) is None


def test_extract_channel_id_rejects_non_uuid() -> None:
    conn = _connection(uuid4())
    envelope = WsEnvelope.model_validate(
        {"v": 1, "type": "PTT_DOWN", "data": {"channel_id": "nao-e-uuid"}}
    )

    assert _extract_channel_id(conn, envelope) is None


# --------------------------------------------------------------------------- protocolo
def test_envelope_rejects_unknown_version() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        WsEnvelope.model_validate({"v": 99, "type": "PING"})


def test_envelope_rejects_extra_fields() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        WsEnvelope.model_validate({"v": 1, "type": "PING", "campo_extra": True})


def test_error_envelope_shape() -> None:
    from app.schemas.ws import error_envelope

    payload = error_envelope(WsErrorCode.NOT_A_MEMBER, "usuário não é membro")
    assert payload["v"] == 1
    assert payload["type"] == "ERROR"
    assert payload["data"]["code"] == "NOT_A_MEMBER"
    assert isinstance(payload["ts"], int)


def test_module_exposes_close_codes() -> None:
    assert ws_module.CLOSE_UNAUTHORIZED == 4401
    assert ws_module.CLOSE_AUTH_TIMEOUT == 4402
