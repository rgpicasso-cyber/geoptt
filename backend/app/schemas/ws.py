"""Protocolo de tempo real do GeoPTT (envelope JSON v1).

Frames **textuais** usam o envelope abaixo; frames **binários** são exclusivamente
áudio Opus e não passam por Pydantic (custo desnecessário por chunk).
"""

from __future__ import annotations

import time
from enum import StrEnum
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, field_validator

PROTOCOL_VERSION: Final = 1

# Códigos de fechamento do WebSocket (faixa privada 4000-4999).
CLOSE_UNAUTHORIZED: Final = 4401
CLOSE_AUTH_TIMEOUT: Final = 4402
CLOSE_HEARTBEAT_TIMEOUT: Final = 4408
CLOSE_MESSAGE_TOO_BIG: Final = 4409
CLOSE_INTERNAL_ERROR: Final = 4500


class WsMessageType(StrEnum):
    """Tipos de mensagem do contrato — espelha `docs/ARCHITECTURE.md` §7."""

    AUTH = "AUTH"
    AUTH_OK = "AUTH_OK"
    PING = "PING"
    PONG = "PONG"
    LOCATION_BATCH = "LOCATION_BATCH"
    LOCATION_UPDATE = "LOCATION_UPDATE"
    PTT_DOWN = "PTT_DOWN"
    PTT_UP = "PTT_UP"
    PTT_BUSY = "PTT_BUSY"
    PTT_SPEAKER_START = "PTT_SPEAKER_START"
    PTT_SPEAKER_STOP = "PTT_SPEAKER_STOP"
    PTT_WAKEUP = "PTT_WAKEUP"
    ERROR = "ERROR"


class WsErrorCode(StrEnum):
    BAD_ENVELOPE = "BAD_ENVELOPE"
    UNAUTHORIZED = "UNAUTHORIZED"
    UNSUPPORTED_TYPE = "UNSUPPORTED_TYPE"
    NOT_A_MEMBER = "NOT_A_MEMBER"
    CANNOT_SPEAK = "CANNOT_SPEAK"
    CHANNEL_NOT_FOUND = "CHANNEL_NOT_FOUND"
    CHANNEL_INACTIVE = "CHANNEL_INACTIVE"
    NOT_SPEAKING = "NOT_SPEAKING"
    NO_ACTIVE_CHANNEL = "NO_ACTIVE_CHANNEL"
    MESSAGE_TOO_BIG = "MESSAGE_TOO_BIG"
    INTERNAL = "INTERNAL"


class WsEnvelope(BaseModel):
    """Envelope de entrada (cliente → servidor)."""

    model_config = ConfigDict(extra="forbid")

    v: int = Field(default=PROTOCOL_VERSION, ge=1, le=PROTOCOL_VERSION)
    type: WsMessageType
    id: str | None = None
    ts: int | None = None
    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("v")
    @classmethod
    def _check_version(cls, value: int) -> int:
        if value != PROTOCOL_VERSION:
            msg = f"versão de protocolo não suportada: {value}"
            raise ValueError(msg)
        return value


class AuthPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=10, max_length=4096)


class PttControlPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel_id: str = Field(min_length=1, max_length=64)


def envelope(
    message_type: WsMessageType | str,
    *,
    data: dict[str, Any] | None = None,
    message_id: str | None = None,
) -> dict[str, Any]:
    """Constrói um envelope de saída (servidor → cliente)."""
    payload: dict[str, Any] = {
        "v": PROTOCOL_VERSION,
        "type": str(message_type),
        "ts": int(time.time()),
        "data": data or {},
    }
    if message_id is not None:
        payload["id"] = message_id
    return payload


def error_envelope(code: WsErrorCode | str, message: str) -> dict[str, Any]:
    return envelope(WsMessageType.ERROR, data={"code": str(code), "message": message})
