"""Modelos geoespaciais: posição atual (`locations`) e série temporal.

`geom` usa `GEOGRAPHY(POINT, 4326)` no PostgreSQL/PostGIS. Em SQLite (dev/testes)
essas duas tabelas não são criadas — ver README.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from geoalchemy2 import Geography
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Index,
    SmallInteger,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Location(Base):
    """Posição atual — 1:1 com `users`, sobrescrita a cada ping."""

    __tablename__ = "locations"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    lat: Mapped[float] = mapped_column(Double, nullable=False)
    lng: Mapped[float] = mapped_column(Double, nullable=False)
    geom: Mapped[Any] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False), nullable=False
    )
    accuracy_m: Mapped[float | None] = mapped_column(Double, nullable=True)
    speed_mps: Mapped[float | None] = mapped_column(Double, nullable=True)
    heading_deg: Mapped[float | None] = mapped_column(Double, nullable=True)
    battery_level: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("lat BETWEEN -90 AND 90", name="lat_range"),
        CheckConstraint("lng BETWEEN -180 AND 180", name="lng_range"),
        CheckConstraint(
            "heading_deg IS NULL OR (heading_deg >= 0 AND heading_deg <= 360)",
            name="heading_range",
        ),
        CheckConstraint(
            "battery_level IS NULL OR (battery_level BETWEEN 0 AND 100)",
            name="battery_level_range",
        ),
        Index("ix_locations_geom", "geom", postgresql_using="gist"),
    )


class LocationHistory(Base):
    """Série temporal imutável de posições (retenção de 30 dias)."""

    __tablename__ = "location_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    lat: Mapped[float] = mapped_column(Double, nullable=False)
    lng: Mapped[float] = mapped_column(Double, nullable=False)
    geom: Mapped[Any] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False), nullable=False
    )
    accuracy_m: Mapped[float | None] = mapped_column(Double, nullable=True)
    speed_mps: Mapped[float | None] = mapped_column(Double, nullable=True)
    heading_deg: Mapped[float | None] = mapped_column(Double, nullable=True)
    battery_level: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    client_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("lat BETWEEN -90 AND 90", name="lat_range"),
        CheckConstraint("lng BETWEEN -180 AND 180", name="lng_range"),
        # Idempotência do reenvio da fila offline.
        UniqueConstraint("user_id", "client_seq", name="ux_history_user_seq"),
        Index("ix_history_user_time", "user_id", text("recorded_at DESC")),
        Index("ix_history_geom", "geom", postgresql_using="gist"),
    )
