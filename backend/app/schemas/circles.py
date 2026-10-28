"""Schemas de círculos e membros."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import CircleRole


class CircleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=80)


class CircleJoinRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    invite_code: str = Field(min_length=6, max_length=12)


class CirclePublic(BaseModel):
    """Círculo visto por quem é membro (o `invite_code` permite convidar)."""

    id: UUID
    name: str
    owner_id: UUID
    invite_code: str
    role: CircleRole
    member_count: int
    created_at: datetime


class CircleMemberPublic(BaseModel):
    """Membro + última posição conhecida (para o mapa).

    `lat`/`lng` são `null` quando o membro ainda não enviou ping ou quando
    desligou o compartilhamento (`is_sharing_location = false`).
    """

    user_id: UUID
    display_name: str
    role: CircleRole
    battery_level: int | None = None
    is_sharing_location: bool
    last_seen_at: datetime | None = None
    lat: float | None = None
    lng: float | None = None
    accuracy_m: float | None = None
    speed_mps: float | None = None
    heading_deg: float | None = None
    recorded_at: datetime | None = None


class CircleListResponse(BaseModel):
    items: list[CirclePublic]


class CircleMembersResponse(BaseModel):
    circle_id: UUID
    items: list[CircleMemberPublic]
