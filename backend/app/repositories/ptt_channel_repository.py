"""Repositório de canais PTT (leitura de membros + provisionamento + auditoria).

Sessões são curtas: abrir, consultar, fechar. Nunca manter `AsyncSession` aberta
durante envio de áudio (ver `PttService`).

**Sem `commit()`**: `PttService` abre a sessão e faz o commit explicitamente
(`_record_session_start` / `_record_session_end`), e a criação de canais acontece
dentro da transação da requisição HTTP (`get_session`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import Platform
from app.models.ptt import PttChannel, PttChannelMember, PttSession
from app.models.user import User
from app.repositories.results import affected_rows


@dataclass(frozen=True, slots=True)
class ChannelMember:
    user_id: UUID
    can_speak: bool
    fcm_token: str | None
    platform: Platform | None


@dataclass(frozen=True, slots=True)
class ChannelInfo:
    id: UUID
    is_active: bool
    members: tuple[ChannelMember, ...]

    @property
    def member_ids(self) -> tuple[UUID, ...]:
        return tuple(member.user_id for member in self.members)

    def member(self, user_id: UUID) -> ChannelMember | None:
        return next((m for m in self.members if m.user_id == user_id), None)


class PttChannelRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------ leitura
    async def get_channel_info(self, channel_id: UUID) -> ChannelInfo | None:
        """Canal + membros (com token FCM) em duas queries."""
        channel = await self._session.get(PttChannel, channel_id)
        if channel is None:
            return None

        stmt = (
            select(
                PttChannelMember.user_id,
                PttChannelMember.can_speak,
                User.fcm_token,
                User.platform,
            )
            .join(User, User.id == PttChannelMember.user_id)
            .where(PttChannelMember.channel_id == channel_id)
        )
        rows = (await self._session.execute(stmt)).all()

        members = tuple(
            ChannelMember(
                user_id=row[0],
                can_speak=row[1],
                fcm_token=row[2],
                platform=row[3],
            )
            for row in rows
        )
        return ChannelInfo(id=channel.id, is_active=channel.is_active, members=members)

    # ------------------------------------------------------------------ provisionamento
    async def create_channel(self, *, circle_id: UUID, name: str, created_by: UUID) -> PttChannel:
        """Cria o canal ou devolve o existente (idempotente por `(circle_id, name)`)."""
        stmt = select(PttChannel).where(PttChannel.circle_id == circle_id, PttChannel.name == name)
        found = (await self._session.execute(stmt)).scalar_one_or_none()
        if found is not None:
            return found

        channel = PttChannel(circle_id=circle_id, name=name, created_by=created_by)
        self._session.add(channel)
        await self._session.flush()
        await self._session.refresh(channel)
        return channel

    async def add_member(self, *, channel_id: UUID, user_id: UUID, can_speak: bool = True) -> None:
        stmt = (
            insert(PttChannelMember)
            .values(channel_id=channel_id, user_id=user_id, can_speak=can_speak)
            .on_conflict_do_nothing(index_elements=["channel_id", "user_id"])
        )
        await self._session.execute(stmt)

    async def add_member_to_circle_channels(self, circle_id: UUID, user_id: UUID) -> int:
        """Adiciona o usuário a todos os canais ativos do círculo."""
        channel_ids = list(
            (
                await self._session.execute(
                    select(PttChannel.id).where(
                        PttChannel.circle_id == circle_id,
                        PttChannel.is_active.is_(True),
                    )
                )
            ).scalars()
        )
        if not channel_ids:
            return 0

        stmt = (
            insert(PttChannelMember)
            .values(
                [
                    {"channel_id": channel_id, "user_id": user_id, "can_speak": True}
                    for channel_id in channel_ids
                ]
            )
            .on_conflict_do_nothing(index_elements=["channel_id", "user_id"])
        )
        result = await self._session.execute(stmt)
        return affected_rows(result)

    async def remove_member_from_circle_channels(self, circle_id: UUID, user_id: UUID) -> int:
        channel_ids = select(PttChannel.id).where(PttChannel.circle_id == circle_id)
        result = await self._session.execute(
            delete(PttChannelMember).where(
                PttChannelMember.user_id == user_id,
                PttChannelMember.channel_id.in_(channel_ids),
            )
        )
        return affected_rows(result)

    # ------------------------------------------------------------------ auditoria
    async def start_session(
        self, *, channel_id: UUID, speaker_id: UUID, started_at: datetime
    ) -> UUID | None:
        """Registra o início da fala. Retorna o id da sessão ou None em falha."""
        session_row = PttSession(
            channel_id=channel_id,
            speaker_id=speaker_id,
            started_at=started_at,
        )
        self._session.add(session_row)
        await self._session.flush()
        return session_row.id

    async def end_session(
        self,
        session_id: UUID,
        *,
        ended_at: datetime,
        frames_sent: int,
        bytes_sent: int,
    ) -> None:
        session_row = await self._session.get(PttSession, session_id)
        if session_row is None:
            return
        session_row.ended_at = ended_at
        session_row.frames_sent = frames_sent
        session_row.bytes_sent = bytes_sent
        await self._session.flush()
