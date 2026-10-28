"""Modelo `users` — conta do usuário e estado de presença.

`fcm_token` e `battery_level` vivem aqui (não em tabela separada) conforme
`docs/DATA_MODEL.md` §2.1. Multi-dispositivo é limitação conhecida do MVP.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import Platform, str_enum


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )

    email: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(String(60), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Push (FCM) ---------------------------------------------------------
    fcm_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    platform: Mapped[Platform | None] = mapped_column(
        str_enum(Platform, "user_platform"), nullable=True
    )

    # --- Presença -----------------------------------------------------------
    battery_level: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    is_sharing_location: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "battery_level IS NULL OR (battery_level BETWEEN 0 AND 100)",
            name="battery_level_range",
        ),
        Index("ux_users_email_lower", text("lower(email)"), unique=True),
    )

    def __repr__(self) -> str:  # pragma: no cover - diagnóstico
        # Nunca expor e-mail ou token em repr.
        return f"<User id={self.id} display_name={self.display_name!r}>"
