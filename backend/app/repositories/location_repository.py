"""Repositório geoespacial (PostGIS).

`geom` é derivado de `(lat, lng)` no próprio SQL — o cliente nunca envia WKT.
Isso evita divergência entre as colunas escalares (usadas nas respostas REST) e a
geometria (usada em consultas espaciais futuras).

**PostgreSQL/PostGIS obrigatório.** As tabelas `locations`/`location_history`
não existem no SQLite de desenvolvimento (ver `docs/DATA_MODEL.md` e risco R7).

Sem `commit()`: ver `protocols.py`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from geoalchemy2 import Geography
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.circle import CircleMember
from app.models.location import Location, LocationHistory
from app.models.user import User
from app.repositories.protocols import LocationPointInput, PositionView
from app.repositories.results import affected_rows


def _point_geography(lat: float, lng: float) -> Any:
    """`ST_SetSRID(ST_MakePoint(lng, lat), 4326)::geography`.

    Atenção à ordem: PostGIS usa **(x=lng, y=lat)**. Inverter aqui produziria
    coordenadas plausíveis porém erradas (falha silenciosa).
    """
    return func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326).cast(Geography)


class LocationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_current(self, *, user_id: UUID, point: LocationPointInput) -> None:
        """Sobrescreve a posição atual (1:1 com `users`)."""
        stmt = insert(Location).values(
            user_id=user_id,
            lat=point.lat,
            lng=point.lng,
            geom=_point_geography(point.lat, point.lng),
            accuracy_m=point.accuracy_m,
            speed_mps=point.speed_mps,
            heading_deg=point.heading_deg,
            battery_level=point.battery_level,
            recorded_at=point.recorded_at,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id"],
            set_={
                "lat": stmt.excluded.lat,
                "lng": stmt.excluded.lng,
                "geom": stmt.excluded.geom,
                "accuracy_m": stmt.excluded.accuracy_m,
                "speed_mps": stmt.excluded.speed_mps,
                "heading_deg": stmt.excluded.heading_deg,
                "battery_level": stmt.excluded.battery_level,
                "recorded_at": stmt.excluded.recorded_at,
                "updated_at": func.now(),
            },
        )
        await self._session.execute(stmt)

    async def insert_history(self, *, user_id: UUID, points: Sequence[LocationPointInput]) -> int:
        """Insere o lote ignorando duplicatas — idempotência do reenvio offline."""
        if not points:
            return 0

        rows = [
            {
                "user_id": user_id,
                "lat": point.lat,
                "lng": point.lng,
                "geom": _point_geography(point.lat, point.lng),
                "accuracy_m": point.accuracy_m,
                "speed_mps": point.speed_mps,
                "heading_deg": point.heading_deg,
                "battery_level": point.battery_level,
                "client_seq": point.client_seq,
                "recorded_at": point.recorded_at,
            }
            for point in points
        ]
        stmt = (
            insert(LocationHistory)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["user_id", "client_seq"])
        )
        result = await self._session.execute(stmt)
        return affected_rows(result)

    async def list_circle_positions(self, circle_id: UUID) -> list[PositionView]:
        """Snapshot do mapa: apenas membros que compartilham localização."""
        stmt = (
            select(
                User.id,
                User.display_name,
                Location.lat,
                Location.lng,
                Location.accuracy_m,
                Location.speed_mps,
                Location.heading_deg,
                func.coalesce(Location.battery_level, User.battery_level),
                Location.recorded_at,
            )
            .join(CircleMember, CircleMember.user_id == User.id)
            .join(Location, Location.user_id == User.id)
            .where(
                CircleMember.circle_id == circle_id,
                User.is_sharing_location.is_(True),
            )
            .order_by(User.display_name)
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            PositionView(
                user_id=row[0],
                display_name=row[1],
                lat=row[2],
                lng=row[3],
                accuracy_m=row[4],
                speed_mps=row[5],
                heading_deg=row[6],
                battery_level=row[7],
                recorded_at=row[8],
            )
            for row in rows
        ]
