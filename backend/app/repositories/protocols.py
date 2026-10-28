"""Interfaces (Protocols) da camada de dados.

Motivo: as regras de negócio vivem em `app/services/` e precisam ser testáveis
**sem PostgreSQL**. Como as tabelas geoespaciais usam `GEOGRAPHY(POINT,4326)` e
não existem em SQLite, os testes injetam implementações falsas que satisfazem
estes Protocols.

Os repositórios reais (`*_repository.py`) satisfazem as interfaces por tipagem
estrutural — não há herança nem registro.

**Regra de transação:** repositórios **nunca** fazem `commit()`. Eles apenas
`flush()` para obter IDs/defaults. Quem é dono da sessão decide o commit:

* requisição HTTP → `app.api.deps.get_session` (commit no fim, rollback em erro);
* `PttService` → abre sessão própria e faz `commit()` explicitamente.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.models.circle import Circle, CircleMember
from app.models.enums import CircleRole, Platform
from app.models.ptt import PttChannel
from app.models.token import RefreshToken
from app.models.user import User


# --------------------------------------------------------------------------- views
@dataclass(frozen=True, slots=True)
class MemberView:
    """Membro de círculo + última posição conhecida (para o mapa)."""

    user_id: UUID
    display_name: str
    role: CircleRole
    battery_level: int | None
    is_sharing_location: bool
    last_seen_at: datetime | None
    lat: float | None
    lng: float | None
    accuracy_m: float | None
    speed_mps: float | None
    heading_deg: float | None
    recorded_at: datetime | None


@dataclass(frozen=True, slots=True)
class PositionView:
    """Posição atual de um membro (snapshot do mapa)."""

    user_id: UUID
    display_name: str
    lat: float
    lng: float
    accuracy_m: float | None
    speed_mps: float | None
    heading_deg: float | None
    battery_level: int | None
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class CircleSummary:
    """Círculo visto pelo usuário autenticado (inclui o papel dele)."""

    id: UUID
    name: str
    owner_id: UUID
    invite_code: str
    role: CircleRole
    member_count: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class LocationPointInput:
    """Ponto já validado por Pydantic, pronto para persistência."""

    lat: float
    lng: float
    accuracy_m: float | None
    speed_mps: float | None
    heading_deg: float | None
    battery_level: int | None
    client_seq: int
    recorded_at: datetime


# --------------------------------------------------------------------------- protocols
class UserRepositoryProtocol(Protocol):
    async def get_by_id(self, user_id: UUID) -> User | None: ...

    async def get_by_email(self, email: str) -> User | None: ...

    async def create(self, *, email: str, password_hash: str, display_name: str) -> User: ...

    async def update_profile(
        self,
        user_id: UUID,
        *,
        display_name: str | None = None,
        is_sharing_location: bool | None = None,
    ) -> User | None: ...

    async def update_password_hash(self, user_id: UUID, password_hash: str) -> None: ...

    async def set_fcm_token(
        self, user_id: UUID, *, fcm_token: str, platform: Platform
    ) -> User | None: ...

    async def clear_fcm_token(self, user_id: UUID) -> bool: ...

    async def clear_fcm_token_by_value(self, fcm_token: str) -> bool: ...

    async def touch_presence(
        self, user_id: UUID, *, battery_level: int | None, seen_at: datetime
    ) -> None: ...


class TokenRepositoryProtocol(Protocol):
    async def create(
        self,
        *,
        user_id: UUID,
        token_hash: str,
        device_id: str,
        expires_at: datetime,
    ) -> RefreshToken: ...

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None: ...

    async def revoke(self, token_id: UUID, *, revoked_at: datetime) -> None: ...

    async def revoke_device(
        self, user_id: UUID, device_id: str, *, revoked_at: datetime
    ) -> int: ...

    async def revoke_all(self, user_id: UUID, *, revoked_at: datetime) -> int: ...


class CircleRepositoryProtocol(Protocol):
    async def create(self, *, name: str, owner_id: UUID, invite_code: str) -> Circle: ...

    async def get_by_id(self, circle_id: UUID) -> Circle | None: ...

    async def get_by_invite_code(self, invite_code: str) -> Circle | None: ...

    async def invite_code_exists(self, invite_code: str) -> bool: ...

    async def get_member(self, circle_id: UUID, user_id: UUID) -> CircleMember | None: ...

    async def add_member(
        self, *, circle_id: UUID, user_id: UUID, role: CircleRole
    ) -> CircleMember: ...

    async def list_for_user(self, user_id: UUID) -> list[CircleSummary]: ...

    async def list_members(self, circle_id: UUID) -> list[MemberView]: ...

    async def list_member_ids(self, circle_id: UUID) -> list[UUID]: ...

    async def list_broadcast_recipients(self, user_id: UUID) -> list[UUID]: ...

    async def remove_member(self, circle_id: UUID, user_id: UUID) -> bool: ...

    async def touch_circle(self, circle_id: UUID, *, at: datetime) -> None: ...


class LocationRepositoryProtocol(Protocol):
    async def upsert_current(
        self,
        *,
        user_id: UUID,
        point: LocationPointInput,
    ) -> None: ...

    async def insert_history(
        self,
        *,
        user_id: UUID,
        points: Sequence[LocationPointInput],
    ) -> int:
        """Insere ignorando duplicatas de `(user_id, client_seq)`. Retorna nº inserido."""
        ...

    async def list_circle_positions(self, circle_id: UUID) -> list[PositionView]: ...


class PttChannelWriterProtocol(Protocol):
    async def create_channel(
        self, *, circle_id: UUID, name: str, created_by: UUID
    ) -> PttChannel: ...

    async def add_member(
        self, *, channel_id: UUID, user_id: UUID, can_speak: bool = True
    ) -> None: ...

    async def add_member_to_circle_channels(self, circle_id: UUID, user_id: UUID) -> int: ...

    async def remove_member_from_circle_channels(self, circle_id: UUID, user_id: UUID) -> int: ...
