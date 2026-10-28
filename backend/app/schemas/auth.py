"""Schemas de autenticação.

`POST /auth/login` usa o **OAuth2 password flow** (`application/x-www-form-urlencoded`)
para que o botão *Authorize* do Swagger funcione. O campo `username` recebe o e-mail.
Os demais endpoints usam JSON.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    """Criação de conta. A política de senha é validada em `security.validate_password_policy`."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: EmailStr
    password: str = Field(min_length=8, max_length=128, repr=False)
    display_name: str = Field(min_length=1, max_length=60)


class RefreshRequest(BaseModel):
    """Rotação de refresh token. O `device_id` vem do header `X-Device-Id`."""

    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=20, max_length=4096, repr=False)


class LogoutRequest(BaseModel):
    """Logout. Sem `device_id`, revoga **todas** as sessões do usuário."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    device_id: str | None = Field(default=None, min_length=1, max_length=120)


class TokenPair(BaseModel):
    """Par de tokens emitido por register/login/refresh."""

    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105
    expires_in: int = Field(description="TTL do access token em segundos")
    refresh_expires_in: int = Field(description="TTL do refresh token em segundos")
