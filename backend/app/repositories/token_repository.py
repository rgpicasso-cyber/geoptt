"""Repositório de refresh tokens (rotação e revogação por dispositivo).

O banco guarda apenas `sha256(token)` — ver `app.core.security.hash_token`.
Sem `commit()`: ver `protocols.py`.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.token import RefreshToken
from app.repositories.results import affected_rows


class TokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        user_id: UUID,
        token_hash: str,
        device_id: str,
        expires_at: datetime,
    ) -> RefreshToken:
        token = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            device_id=device_id,
            expires_at=expires_at,
        )
        self._session.add(token)
        await self._session.flush()
        await self._session.refresh(token)
        return token

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        """Busca **inclusive revogado** — necessário para detectar reutilização."""
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def revoke(self, token_id: UUID, *, revoked_at: datetime) -> None:
        await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.id == token_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=revoked_at)
        )

    async def revoke_device(self, user_id: UUID, device_id: str, *, revoked_at: datetime) -> int:
        """Revoga as sessões ativas de um dispositivo (logout)."""
        result = await self._session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.device_id == device_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
        )
        return affected_rows(result)

    async def revoke_all(self, user_id: UUID, *, revoked_at: datetime) -> int:
        """Revoga **todas** as sessões — usado quando há suspeita de roubo de token."""
        result = await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=revoked_at)
        )
        return affected_rows(result)
