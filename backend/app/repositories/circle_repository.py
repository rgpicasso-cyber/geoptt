"""Repositório de círculos, membros e agregações para o mapa.

Consultas pensadas para o cliente móvel: `list_members` já devolve a última
posição conhecida (um único round-trip), e `list_broadcast_recipients` resolve o
fan-out de `LOCATION_UPDATE` em **uma** query.

Sem `commit()`: ver `protocols.py`.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.circle import Circle, CircleMember
from app.models.enums import CircleRole
from app.models.location import Location
from app.models.user import User
from app.repositories.protocols import CircleSummary, MemberView
from app.repositories.results import affected_rows


class CircleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------ círculo
    async def create(self, *, name: str, owner_id: UUID, invite_code: str) -> Circle:
        circle = Circle(name=name.strip(), owner_id=owner_id, invite_code=invite_code)
        self._session.add(circle)
        await self._session.flush()
        await self._session.refresh(circle)
        return circle

    async def get_by_id(self, circle_id: UUID) -> Circle | None:
        return await self._session.get(Circle, circle_id)

    async def get_by_invite_code(self, invite_code: str) -> Circle | None:
        stmt = select(Circle).where(Circle.invite_code == invite_code.strip().upper())
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def invite_code_exists(self, invite_code: str) -> bool:
        stmt = (
            select(func.count())
            .select_from(Circle)
            .where(Circle.invite_code == invite_code.strip().upper())
        )
        return bool((await self._session.execute(stmt)).scalar_one())

    # ------------------------------------------------------------------ membros
    async def get_member(self, circle_id: UUID, user_id: UUID) -> CircleMember | None:
        return await self._session.get(CircleMember, (circle_id, user_id))

    async def add_member(self, *, circle_id: UUID, user_id: UUID, role: CircleRole) -> CircleMember:
        member = CircleMember(circle_id=circle_id, user_id=user_id, role=role)
        self._session.add(member)
        await self._session.flush()
        await self._session.refresh(member)
        return member

    async def remove_member(self, circle_id: UUID, user_id: UUID) -> bool:
        result = await self._session.execute(
            delete(CircleMember).where(
                CircleMember.circle_id == circle_id,
                CircleMember.user_id == user_id,
            )
        )
        return affected_rows(result) > 0

    async def list_member_ids(self, circle_id: UUID) -> list[UUID]:
        stmt = select(CircleMember.user_id).where(CircleMember.circle_id == circle_id)
        return list((await self._session.execute(stmt)).scalars())

    async def list_broadcast_recipients(self, user_id: UUID) -> list[UUID]:
        """Todos os membros dos círculos do usuário, exceto ele mesmo (distintos)."""
        peer = aliased(CircleMember)
        stmt = (
            select(peer.user_id)
            .distinct()
            .join(CircleMember, CircleMember.circle_id == peer.circle_id)
            .where(CircleMember.user_id == user_id, peer.user_id != user_id)
        )
        return list((await self._session.execute(stmt)).scalars())

    # ------------------------------------------------------------------ listagens
    async def list_for_user(self, user_id: UUID) -> list[CircleSummary]:
        stmt = (
            select(Circle, CircleMember.role)
            .join(CircleMember, CircleMember.circle_id == Circle.id)
            .where(CircleMember.user_id == user_id)
            .order_by(Circle.created_at)
        )
        rows = (await self._session.execute(stmt)).all()
        if not rows:
            return []

        circle_ids = [row[0].id for row in rows]
        counts_stmt = (
            select(CircleMember.circle_id, func.count())
            .where(CircleMember.circle_id.in_(circle_ids))
            .group_by(CircleMember.circle_id)
        )
        counts = {
            circle_id: int(total)
            for circle_id, total in (await self._session.execute(counts_stmt)).all()
        }

        return [
            CircleSummary(
                id=circle.id,
                name=circle.name,
                owner_id=circle.owner_id,
                invite_code=circle.invite_code,
                role=role,
                member_count=counts.get(circle.id, 0),
                created_at=circle.created_at,
            )
            for circle, role in rows
        ]

    async def list_members(self, circle_id: UUID) -> list[MemberView]:
        """Membros + última posição (LEFT JOIN: membro sem ping ainda aparece)."""
        stmt = (
            select(
                User.id,
                User.display_name,
                CircleMember.role,
                func.coalesce(Location.battery_level, User.battery_level),
                User.is_sharing_location,
                User.last_seen_at,
                Location.lat,
                Location.lng,
                Location.accuracy_m,
                Location.speed_mps,
                Location.heading_deg,
                Location.recorded_at,
            )
            .join(CircleMember, CircleMember.user_id == User.id)
            .outerjoin(Location, Location.user_id == User.id)
            .where(CircleMember.circle_id == circle_id)
            .order_by(CircleMember.role, User.display_name)
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            MemberView(
                user_id=row[0],
                display_name=row[1],
                role=row[2],
                battery_level=row[3],
                is_sharing_location=row[4],
                last_seen_at=row[5],
                lat=row[6],
                lng=row[7],
                accuracy_m=row[8],
                speed_mps=row[9],
                heading_deg=row[10],
                recorded_at=row[11],
            )
            for row in rows
        ]

    # ------------------------------------------------------------------ auxiliares
    async def touch_circle(self, circle_id: UUID, *, at: datetime) -> None:
        """Marca o círculo como alterado (usado ao entrar/sair de membros)."""
        circle = await self._session.get(Circle, circle_id)
        if circle is not None:
            circle.updated_at = at
            await self._session.flush()
