"""Modelos de Push-To-Talk: canais, membros e auditoria de fala."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PttChannel(Base):
    __tablename__ = "ptt_channels"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    circle_id: Mapped[UUID] = mapped_column(
        ForeignKey("circles.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (UniqueConstraint("circle_id", "name", name="ux_ptt_channels_circle_name"),)


class PttChannelMember(Base):
    __tablename__ = "ptt_channel_members"

    channel_id: Mapped[UUID] = mapped_column(
        ForeignKey("ptt_channels.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    can_speak: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_ptt_members_user", "user_id"),)


class PttSession(Base):
    """Auditoria de cada aperto de botão. Nunca armazena áudio."""

    __tablename__ = "ptt_sessions"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    channel_id: Mapped[UUID] = mapped_column(
        ForeignKey("ptt_channels.id", ondelete="CASCADE"), nullable=False
    )
    speaker_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    frames_sent: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    bytes_sent: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))

    __table_args__ = (Index("ix_ptt_sessions_channel_time", "channel_id", text("started_at DESC")),)
