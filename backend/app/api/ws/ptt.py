"""Endpoint WebSocket `/ws` — autenticação, presença e áudio PTT.

Contrato (`docs/ARCHITECTURE.md` §7):
  * autenticação por `?token=<JWT>` **ou** primeiro frame `{"type": "AUTH"}`
    em até `WS_AUTH_TIMEOUT_SECONDS` (padrão 3 s);
  * falha de auth → close `4401` (após `accept`, para o cliente ler o código);
  * frames de texto = envelope JSON; frames binários = áudio Opus do locutor;
  * heartbeat: sem nenhuma mensagem em `WS_HEARTBEAT_TIMEOUT_SECONDS` → close `4408`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import cast
from uuid import UUID

from fastapi import APIRouter, FastAPI, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.core.config import Settings
from app.core.container import Services
from app.core.security import TokenError, TokenType, decode_token
from app.schemas.ws import (
    CLOSE_AUTH_TIMEOUT,
    CLOSE_HEARTBEAT_TIMEOUT,
    CLOSE_MESSAGE_TOO_BIG,
    CLOSE_UNAUTHORIZED,
    AuthPayload,
    PttControlPayload,
    WsEnvelope,
    WsErrorCode,
    WsMessageType,
    envelope,
    error_envelope,
)
from app.services.connection_manager import Connection
from app.services.ptt_service import PttBusyError, PttError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


class _AuthHandshakeError(Exception):
    """Falha de autenticação traduzida em código de fechamento."""

    def __init__(self, code: int, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


def _services(websocket: WebSocket) -> Services:
    app = cast(FastAPI, websocket.scope["app"])
    return cast(Services, app.state.services)


async def _safe_close(websocket: WebSocket, code: int, reason: str) -> None:
    # O protocolo limita `reason` a 123 bytes.
    with contextlib.suppress(Exception):
        await websocket.close(code=code, reason=reason[:120])


# --------------------------------------------------------------------------- auth
def _subject_from_token(token: str, settings: Settings) -> UUID:
    try:
        claims = decode_token(token, settings=settings, expected_type=TokenType.ACCESS)
    except TokenError as exc:
        raise _AuthHandshakeError(CLOSE_UNAUTHORIZED, str(exc)) from exc
    return cast(UUID, claims["user_id"])


async def _authenticate(websocket: WebSocket, settings: Settings) -> UUID:
    """Resolve o `user_id` via query string ou primeiro frame `AUTH`."""
    token = websocket.query_params.get("token")
    if token:
        return _subject_from_token(token, settings)

    try:
        message = await asyncio.wait_for(
            websocket.receive(), timeout=settings.ws_auth_timeout_seconds
        )
    except TimeoutError as exc:
        raise _AuthHandshakeError(CLOSE_AUTH_TIMEOUT, "timeout aguardando AUTH") from exc

    if message["type"] == "websocket.disconnect":
        raise WebSocketDisconnect

    raw = message.get("text")
    if raw is None:
        raise _AuthHandshakeError(CLOSE_UNAUTHORIZED, "frame binário antes do AUTH")

    try:
        inbound = WsEnvelope.model_validate_json(raw)
    except ValidationError as exc:
        raise _AuthHandshakeError(CLOSE_UNAUTHORIZED, "envelope inválido") from exc

    if inbound.type is not WsMessageType.AUTH:
        raise _AuthHandshakeError(CLOSE_UNAUTHORIZED, "primeiro frame deve ser AUTH")

    try:
        payload = AuthPayload.model_validate(inbound.data)
    except ValidationError as exc:
        raise _AuthHandshakeError(CLOSE_UNAUTHORIZED, "payload de AUTH inválido") from exc

    return _subject_from_token(payload.token, settings)


# --------------------------------------------------------------------------- handler
@router.websocket("/ws")
async def ptt_socket(websocket: WebSocket) -> None:
    """Conexão principal do app (presença + PTT + localização, a partir da Fase 4)."""
    services = _services(websocket)
    settings = services.settings

    await websocket.accept()

    try:
        user_id = await _authenticate(websocket, settings)
    except _AuthHandshakeError as failure:
        logger.info(
            "ws auth rejeitada",
            extra={"event": "ws_auth_rejected", "code": failure.code, "path": "/ws"},
        )
        await _safe_close(websocket, failure.code, failure.reason)
        return
    except WebSocketDisconnect:
        return
    except Exception:
        logger.exception("erro inesperado no handshake WS", extra={"event": "ws_auth_error"})
        await _safe_close(websocket, CLOSE_UNAUTHORIZED, "falha de autenticação")
        return

    device_id = websocket.query_params.get("device_id") or websocket.headers.get("x-device-id")
    connection = await services.connections.register(websocket, user_id, device_id=device_id)
    connection.enqueue_json(
        envelope(
            WsMessageType.AUTH_OK,
            data={"user_id": str(user_id), "server_ts": int(time.time())},
        )
    )

    try:
        await _receive_loop(connection, services)
    except WebSocketDisconnect:
        logger.info(
            "cliente desconectou", extra={"event": "ws_client_disconnect", "user_id": str(user_id)}
        )
    except Exception:
        logger.exception("erro no loop do WebSocket", extra={"event": "ws_loop_error"})
        await _safe_close(websocket, 4500, "erro interno")
    finally:
        await services.connections.unregister(connection)


async def _receive_loop(connection: Connection, services: Services) -> None:
    settings = services.settings
    websocket = connection.websocket

    while not connection.closed:
        try:
            message = await asyncio.wait_for(
                websocket.receive(), timeout=settings.ws_heartbeat_timeout_seconds
            )
        except TimeoutError:
            logger.info(
                "heartbeat timeout",
                extra={"event": "ws_heartbeat_timeout", "user_id": str(connection.user_id)},
            )
            await _safe_close(websocket, CLOSE_HEARTBEAT_TIMEOUT, "heartbeat timeout")
            return

        if message["type"] == "websocket.disconnect":
            return

        binary = message.get("bytes")
        if binary is not None:
            await _handle_binary(connection, services, binary)
            continue

        text = message.get("text")
        if text is not None:
            await _handle_text(connection, services, text)


# --------------------------------------------------------------------------- dispatch
async def _handle_text(connection: Connection, services: Services, raw: str) -> None:
    settings = services.settings
    if len(raw.encode("utf-8")) > settings.ws_max_message_bytes:
        connection.enqueue_json(
            error_envelope(WsErrorCode.MESSAGE_TOO_BIG, "mensagem excede o limite")
        )
        return

    try:
        inbound = WsEnvelope.model_validate_json(raw)
    except ValidationError:
        connection.enqueue_json(error_envelope(WsErrorCode.BAD_ENVELOPE, "envelope inválido"))
        return

    match inbound.type:
        case WsMessageType.PING:
            connection.enqueue_json(envelope(WsMessageType.PONG))

        case WsMessageType.PTT_DOWN:
            await _handle_ptt_down(connection, services, inbound)

        case WsMessageType.PTT_UP:
            await _handle_ptt_up(connection, services, inbound)

        case WsMessageType.AUTH:
            connection.enqueue_json(
                error_envelope(WsErrorCode.UNAUTHORIZED, "sessão já autenticada")
            )

        case _:
            connection.enqueue_json(
                error_envelope(
                    WsErrorCode.UNSUPPORTED_TYPE,
                    f"tipo '{inbound.type}' ainda não suportado nesta versão",
                )
            )


async def _handle_ptt_down(connection: Connection, services: Services, inbound: WsEnvelope) -> None:
    channel_id = _extract_channel_id(connection, inbound)
    if channel_id is None:
        return

    try:
        await services.ptt.start_talking(channel_id=channel_id, user_id=connection.user_id)
    except PttBusyError as busy:
        connection.enqueue_json(
            envelope(
                WsMessageType.PTT_BUSY,
                data={
                    "channel_id": str(channel_id),
                    "speaker_id": str(busy.speaker_id) if busy.speaker_id else None,
                },
            )
        )
        return
    except PttError as err:
        connection.enqueue_json(error_envelope(err.code, err.message))
        return

    connection.active_channel_id = channel_id


async def _handle_ptt_up(connection: Connection, services: Services, inbound: WsEnvelope) -> None:
    channel_id = _extract_channel_id(connection, inbound, fallback=connection.active_channel_id)
    if channel_id is None:
        return

    try:
        await services.ptt.stop_talking(channel_id=channel_id, user_id=connection.user_id)
    except PttError as err:
        connection.enqueue_json(error_envelope(err.code, err.message))
    finally:
        if connection.active_channel_id == channel_id:
            connection.active_channel_id = None


async def _handle_binary(connection: Connection, services: Services, payload: bytes) -> None:
    settings = services.settings
    if len(payload) > settings.ws_max_message_bytes:
        connection.enqueue_json(
            error_envelope(WsErrorCode.MESSAGE_TOO_BIG, "frame de áudio excede o limite")
        )
        await _safe_close(connection.websocket, CLOSE_MESSAGE_TOO_BIG, "frame muito grande")
        return

    channel_id = connection.active_channel_id
    if channel_id is None:
        connection.enqueue_json(
            error_envelope(WsErrorCode.NO_ACTIVE_CHANNEL, "envie PTT_DOWN antes do áudio")
        )
        return

    await services.ptt.relay_audio(
        channel_id=channel_id, sender_id=connection.user_id, payload=payload
    )


def _extract_channel_id(
    connection: Connection,
    inbound: WsEnvelope,
    *,
    fallback: UUID | None = None,
) -> UUID | None:
    """Valida `data.channel_id`. Em falha, enfileira erro e retorna None."""
    try:
        payload = PttControlPayload.model_validate(inbound.data)
        return UUID(payload.channel_id)
    except (ValidationError, ValueError):
        if fallback is not None:
            return fallback
        connection.enqueue_json(
            error_envelope(WsErrorCode.BAD_ENVELOPE, "channel_id ausente ou inválido")
        )
        return None
