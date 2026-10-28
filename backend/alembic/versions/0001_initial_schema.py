"""schema inicial do GeoPTT

Cria as entidades de `docs/DATA_MODEL.md` §3:
users, circles, circle_members, locations, location_history,
ptt_channels, ptt_channel_members, ptt_sessions, refresh_tokens.

Requer PostgreSQL 13+ com a extensão PostGIS disponível no servidor.
A extensão é criada com `CREATE EXTENSION IF NOT EXISTS postgis`.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-28 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geography
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid() -> postgresql.UUID:
    return postgresql.UUID(as_uuid=True)


def _timestamptz() -> sa.DateTime:
    return sa.DateTime(timezone=True)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        msg = (
            "As migrations do GeoPTT exigem PostgreSQL com PostGIS "
            f"(dialeto detectado: {bind.dialect.name})."
        )
        raise RuntimeError(msg)

    # --- extensões (idempotente) -------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # --- tipos enumerados ---------------------------------------------------
    op.execute("CREATE TYPE user_platform AS ENUM ('android', 'ios')")
    op.execute("CREATE TYPE circle_role AS ENUM ('owner', 'admin', 'member')")

    # --- users --------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("display_name", sa.String(length=60), nullable=False),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("fcm_token", sa.String(length=255), nullable=True),
        sa.Column(
            "platform",
            postgresql.ENUM(name="user_platform", create_type=False),
            nullable=True,
        ),
        sa.Column("battery_level", sa.SmallInteger(), nullable=True),
        sa.Column(
            "is_sharing_location", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("last_seen_at", _timestamptz(), nullable=True),
        sa.Column("created_at", _timestamptz(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", _timestamptz(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.CheckConstraint(
            "battery_level IS NULL OR (battery_level BETWEEN 0 AND 100)",
            name="battery_level_range",
        ),
    )
    op.create_index("ux_users_email_lower", "users", [sa.text("lower(email)")], unique=True)

    # --- circles ------------------------------------------------------------
    op.create_table(
        "circles",
        sa.Column("id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("owner_id", _uuid(), nullable=False),
        sa.Column("invite_code", sa.String(length=12), nullable=False),
        sa.Column("created_at", _timestamptz(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", _timestamptz(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_circles"),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name="fk_circles_owner_id_users",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("invite_code", name="ux_circles_invite_code"),
    )

    # --- circle_members -----------------------------------------------------
    op.create_table(
        "circle_members",
        sa.Column("circle_id", _uuid(), nullable=False),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM(name="circle_role", create_type=False),
            server_default=sa.text("'member'"),
            nullable=False,
        ),
        sa.Column("joined_at", _timestamptz(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("circle_id", "user_id", name="pk_circle_members"),
        sa.ForeignKeyConstraint(
            ["circle_id"],
            ["circles.id"],
            name="fk_circle_members_circle_id_circles",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_circle_members_user_id_users",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_circle_members_user", "circle_members", ["user_id"])
    op.create_index(
        "ux_circle_single_owner",
        "circle_members",
        ["circle_id"],
        unique=True,
        postgresql_where=sa.text("role = 'owner'"),
    )

    # --- locations (posição atual) -----------------------------------------
    op.create_table(
        "locations",
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("lat", sa.Double(), nullable=False),
        sa.Column("lng", sa.Double(), nullable=False),
        sa.Column(
            "geom",
            Geography(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("accuracy_m", sa.Double(), nullable=True),
        sa.Column("speed_mps", sa.Double(), nullable=True),
        sa.Column("heading_deg", sa.Double(), nullable=True),
        sa.Column("battery_level", sa.SmallInteger(), nullable=True),
        sa.Column("recorded_at", _timestamptz(), nullable=False),
        sa.Column("updated_at", _timestamptz(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("user_id", name="pk_locations"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_locations_user_id_users",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("lat BETWEEN -90 AND 90", name="lat_range"),
        sa.CheckConstraint("lng BETWEEN -180 AND 180", name="lng_range"),
        sa.CheckConstraint(
            "heading_deg IS NULL OR (heading_deg >= 0 AND heading_deg <= 360)",
            name="heading_range",
        ),
        sa.CheckConstraint(
            "battery_level IS NULL OR (battery_level BETWEEN 0 AND 100)",
            name="battery_level_range",
        ),
    )
    op.create_index("ix_locations_geom", "locations", ["geom"], postgresql_using="gist")

    # --- location_history ---------------------------------------------------
    op.create_table(
        "location_history",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("lat", sa.Double(), nullable=False),
        sa.Column("lng", sa.Double(), nullable=False),
        sa.Column(
            "geom",
            Geography(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("accuracy_m", sa.Double(), nullable=True),
        sa.Column("speed_mps", sa.Double(), nullable=True),
        sa.Column("heading_deg", sa.Double(), nullable=True),
        sa.Column("battery_level", sa.SmallInteger(), nullable=True),
        sa.Column("client_seq", sa.BigInteger(), nullable=False),
        sa.Column("recorded_at", _timestamptz(), nullable=False),
        sa.Column("created_at", _timestamptz(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_location_history"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_location_history_user_id_users",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("lat BETWEEN -90 AND 90", name="lat_range"),
        sa.CheckConstraint("lng BETWEEN -180 AND 180", name="lng_range"),
        sa.UniqueConstraint("user_id", "client_seq", name="ux_history_user_seq"),
    )
    op.create_index(
        "ix_history_user_time", "location_history", ["user_id", sa.text("recorded_at DESC")]
    )
    op.create_index("ix_history_geom", "location_history", ["geom"], postgresql_using="gist")

    # --- ptt_channels -------------------------------------------------------
    op.create_table(
        "ptt_channels",
        sa.Column("id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("circle_id", _uuid(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("created_by", _uuid(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", _timestamptz(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_ptt_channels"),
        sa.ForeignKeyConstraint(
            ["circle_id"],
            ["circles.id"],
            name="fk_ptt_channels_circle_id_circles",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_ptt_channels_created_by_users",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("circle_id", "name", name="ux_ptt_channels_circle_name"),
    )

    # --- ptt_channel_members ------------------------------------------------
    op.create_table(
        "ptt_channel_members",
        sa.Column("channel_id", _uuid(), nullable=False),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("can_speak", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("joined_at", _timestamptz(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("channel_id", "user_id", name="pk_ptt_channel_members"),
        sa.ForeignKeyConstraint(
            ["channel_id"],
            ["ptt_channels.id"],
            name="fk_ptt_channel_members_channel_id_ptt_channels",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_ptt_channel_members_user_id_users",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_ptt_members_user", "ptt_channel_members", ["user_id"])

    # --- ptt_sessions -------------------------------------------------------
    op.create_table(
        "ptt_sessions",
        sa.Column("id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("channel_id", _uuid(), nullable=False),
        sa.Column("speaker_id", _uuid(), nullable=False),
        sa.Column("started_at", _timestamptz(), nullable=False),
        sa.Column("ended_at", _timestamptz(), nullable=True),
        sa.Column("frames_sent", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("bytes_sent", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_ptt_sessions"),
        sa.ForeignKeyConstraint(
            ["channel_id"],
            ["ptt_channels.id"],
            name="fk_ptt_sessions_channel_id_ptt_channels",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["speaker_id"],
            ["users.id"],
            name="fk_ptt_sessions_speaker_id_users",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_ptt_sessions_channel_time", "ptt_sessions", ["channel_id", sa.text("started_at DESC")]
    )

    # --- refresh_tokens -----------------------------------------------------
    op.create_table(
        "refresh_tokens",
        sa.Column("id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("device_id", sa.String(length=120), nullable=False),
        sa.Column("expires_at", _timestamptz(), nullable=False),
        sa.Column("revoked_at", _timestamptz(), nullable=True),
        sa.Column("created_at", _timestamptz(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_tokens"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_refresh_tokens_user_id_users",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("token_hash", name="ux_refresh_tokens_token_hash"),
    )
    op.create_index(
        "ix_refresh_user",
        "refresh_tokens",
        ["user_id"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("refresh_tokens")
    op.drop_table("ptt_sessions")
    op.drop_table("ptt_channel_members")
    op.drop_table("ptt_channels")
    op.drop_table("location_history")
    op.drop_table("locations")
    op.drop_table("circle_members")
    op.drop_table("circles")
    op.drop_table("users")

    op.execute("DROP TYPE IF EXISTS circle_role")
    op.execute("DROP TYPE IF EXISTS user_platform")
    # As extensões NÃO são removidas: outros bancos/schemas podem depender delas.
