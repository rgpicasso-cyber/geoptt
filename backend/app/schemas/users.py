"""Schemas de perfil e registro de push."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.models.enums import Platform


class UserPublic(BaseModel):
    """Perfil exposto ao próprio usuário. Nunca inclui `password_hash` nem `fcm_token`."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    display_name: str
    avatar_url: str | None = None
    platform: Platform | None = None
    is_sharing_location: bool
    battery_level: int | None = None
    last_seen_at: datetime | None = None
    created_at: datetime


class UserUpdate(BaseModel):
    """Atualização parcial — exige ao menos um campo."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    display_name: str | None = Field(default=None, min_length=1, max_length=60)
    is_sharing_location: bool | None = None

    @model_validator(mode="after")
    def _require_at_least_one(self) -> UserUpdate:
        if self.display_name is None and self.is_sharing_location is None:
            msg = "informe ao menos um campo para atualizar"
            raise ValueError(msg)
        return self


class FcmTokenRequest(BaseModel):
    """Registro idempotente do token FCM do dispositivo."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    fcm_token: str = Field(min_length=10, max_length=255, repr=False)
    platform: Platform
