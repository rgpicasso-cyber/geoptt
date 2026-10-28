"""Repositório de canais PTT (leitura de membros + auditoria de fala).

Sessões são curtas: abrir, consultar, fechar. Nunca manter `AsyncSession` aberta
durante envio de áudio (ver `PttService`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import Platform
from app.models.ptt import PttChannel, PttChannelMember, PttSession
from app.models.user import User


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
        await self._session.commit()
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
        await self._session.commit()
