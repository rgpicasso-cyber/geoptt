"""Repositório de usuários: conta, perfil e token FCM.

O e-mail é único **case-insensitive** (índice funcional `ux_users_email_lower`),
por isso toda busca normaliza com `lower(email)`.

Sem `commit()` aqui: quem controla a transação é `app.api.deps.get_session`
(requisição) ou `PttService` (sessão própria). Ver `protocols.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import Platform
from app.models.user import User
from app.repositories.results import affected_rows


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(func.lower(User.email) == email.strip().lower())
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create(self, *, email: str, password_hash: str, display_name: str) -> User:
        user = User(
            email=email.strip().lower(),
            password_hash=password_hash,
            display_name=display_name.strip(),
        )
        self._session.add(user)
        # `flush` (não commit): o ID vem do `server_default gen_random_uuid()`.
        await self._session.flush()
        await self._session.refresh(user)
        return user

    async def update_profile(
        self,
        user_id: UUID,
        *,
        display_name: str | None = None,
        is_sharing_location: bool | None = None,
    ) -> User | None:
        user = await self._session.get(User, user_id)
        if user is None:
            return None
        if display_name is not None:
            user.display_name = display_name.strip()
        if is_sharing_location is not None:
            user.is_sharing_location = is_sharing_location
        await self._session.flush()
        await self._session.refresh(user)
        return user

    async def update_password_hash(self, user_id: UUID, password_hash: str) -> None:
        """Persiste um re-hash (custo do Argon2 atualizado) após login válido."""
        await self._session.execute(
            update(User)
            .where(User.id == user_id)
            .values(password_hash=password_hash, updated_at=datetime.now(UTC))
        )

    async def set_fcm_token(
        self, user_id: UUID, *, fcm_token: str, platform: Platform
    ) -> User | None:
        user = await self._session.get(User, user_id)
        if user is None:
            return None
        user.fcm_token = fcm_token
        user.platform = platform
        await self._session.flush()
        await self._session.refresh(user)
        return user

    async def clear_fcm_token(self, user_id: UUID) -> bool:
        user = await self._session.get(User, user_id)
        if user is None or user.fcm_token is None:
            return False
        user.fcm_token = None
        user.platform = None
        await self._session.flush()
        return True

    async def clear_fcm_token_by_value(self, fcm_token: str) -> bool:
        """Limpa o token quando o FCM responde `UNREGISTERED`."""
        result = await self._session.execute(
            update(User)
            .where(User.fcm_token == fcm_token)
            .values(fcm_token=None, platform=None, updated_at=datetime.now(UTC))
        )
        return affected_rows(result) > 0

    async def touch_presence(
        self, user_id: UUID, *, battery_level: int | None, seen_at: datetime
    ) -> None:
        """Atualiza presença agregada (`last_seen_at` + bateria) após um lote de posições."""
        values: dict[str, object] = {"last_seen_at": seen_at}
        if battery_level is not None:
            values["battery_level"] = battery_level
        await self._session.execute(update(User).where(User.id == user_id).values(**values))
