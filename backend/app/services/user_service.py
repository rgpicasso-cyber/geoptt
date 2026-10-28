"""Regras de perfil do usuário e registro de push (FCM)."""

from __future__ import annotations

from uuid import UUID

from app.core.errors import NotFoundError
from app.models.enums import Platform
from app.models.user import User
from app.repositories.protocols import UserRepositoryProtocol


class UserService:
    def __init__(self, *, users: UserRepositoryProtocol) -> None:
        self._users = users

    async def get(self, user_id: UUID) -> User:
        user = await self._users.get_by_id(user_id)
        if user is None:
            # Token válido para um usuário que não existe mais (conta excluída).
            raise NotFoundError("usuário não encontrado")
        return user

    async def update(
        self,
        user_id: UUID,
        *,
        display_name: str | None,
        is_sharing_location: bool | None,
    ) -> User:
        user = await self._users.update_profile(
            user_id,
            display_name=display_name,
            is_sharing_location=is_sharing_location,
        )
        if user is None:
            raise NotFoundError("usuário não encontrado")
        return user

    async def register_fcm_token(
        self, user_id: UUID, *, fcm_token: str, platform: Platform
    ) -> User:
        """Idempotente: o mesmo token pode ser reenviado a cada abertura do app."""
        user = await self._users.set_fcm_token(user_id, fcm_token=fcm_token, platform=platform)
        if user is None:
            raise NotFoundError("usuário não encontrado")
        return user

    async def remove_fcm_token(self, user_id: UUID) -> bool:
        """Remove o token do dispositivo (logout). `False` se não havia token."""
        return await self._users.clear_fcm_token(user_id)
