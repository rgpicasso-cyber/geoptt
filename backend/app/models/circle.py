"""Modelos `circles` e `circle_members` — agrupamento social."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import CircleRole, str_enum


class Circle(Base):
    __tablename__ = "circles"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    invite_code: Mapped[str] = mapped_column(String(12), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CircleMember(Base):
    __tablename__ = "circle_members"

    circle_id: Mapped[UUID] = mapped_column(
        ForeignKey("circles.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[CircleRole] = mapped_column(
        str_enum(CircleRole, "circle_role"), nullable=False, server_default=text("'member'")
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_circle_members_user", "user_id"),
        # Um único owner por círculo (índice parcial único).
        # Nota: NÃO existe UniqueConstraint(circle_id, user_id) — a PK composta
        # já garante unicidade e uma constraint extra seria redundante.
        Index(
            "ux_circle_single_owner",
            "circle_id",
            unique=True,
            postgresql_where=text("role = 'owner'"),
        ),
    )
