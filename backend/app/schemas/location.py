"""Schemas de localização (lote offline e snapshot do mapa).

Limites escolhidos para não transformar um único POST em um ataque de amplificação:

* **50 pontos** por lote — cobre ~50 min de ping a 1/min (fila offline típica);
* `recorded_at` no futuro além de **5 min** é rejeitado (relógio do celular errado);
* `recorded_at` mais antigo que **30 dias** é rejeitado (retenção do histórico).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_BATCH_POINTS: Final = 50
MAX_CLOCK_SKEW_MINUTES: Final = 5
MAX_POINT_AGE_DAYS: Final = 30


class LocationPoint(BaseModel):
    """Um ping de localização já normalizado."""

    model_config = ConfigDict(extra="forbid")

    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0, le=100_000)
    speed_mps: float | None = Field(default=None, ge=0, le=250)
    heading_deg: float | None = Field(default=None, ge=0, le=360)
    battery_level: int | None = Field(default=None, ge=0, le=100)
    client_seq: int = Field(ge=0, description="Sequência monotônica por dispositivo")
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def _normalize_and_bound(cls, value: datetime) -> datetime:
        """Assume UTC quando o cliente omite o fuso e rejeita datas implausíveis."""
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)

        now = datetime.now(UTC)
        if value > now + timedelta(minutes=MAX_CLOCK_SKEW_MINUTES):
            msg = "recorded_at no futuro"
            raise ValueError(msg)
        if value < now - timedelta(days=MAX_POINT_AGE_DAYS):
            msg = f"recorded_at mais antigo que {MAX_POINT_AGE_DAYS} dias"
            raise ValueError(msg)
        return value


class LocationBatchRequest(BaseModel):
    """Lote enviado por REST (fila offline) **ou** por WebSocket (`LOCATION_BATCH`)."""

    model_config = ConfigDict(extra="forbid")

    points: list[LocationPoint] = Field(min_length=1, max_length=MAX_BATCH_POINTS)


class LocationBatchResponse(BaseModel):
    accepted: int = Field(description="Pontos gravados no histórico")
    duplicated: int = Field(description="Pontos ignorados por `client_seq` já visto")
    server_ts: int


class PositionPublic(BaseModel):
    """Posição atual de um membro do círculo."""

    user_id: UUID
    display_name: str
    lat: float
    lng: float
    accuracy_m: float | None = None
    speed_mps: float | None = None
    heading_deg: float | None = None
    battery_level: int | None = None
    recorded_at: datetime


class CirclePositionsResponse(BaseModel):
    circle_id: UUID
    items: list[PositionPublic]
