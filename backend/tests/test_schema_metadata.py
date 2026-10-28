"""Guarda de drift entre o ORM (`Base.metadata`) e a migration inicial.

Não conecta em banco: renderiza o SQL da migration em modo *offline*
(`alembic upgrade head --sql`) e compara os nomes de constraints/índices com os
que o SQLAlchemy gera a partir dos modelos.

Se este teste falhar, o schema do código e o schema aplicado divergiram — e a
correção é ajustar a migration (nunca "consertar" o teste).
"""

from __future__ import annotations

import io
import re
from contextlib import redirect_stdout
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

import app.models  # noqa: F401  # registra os modelos em Base.metadata
from app.db.base import Base

BACKEND_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_TABLES = {
    "users",
    "circles",
    "circle_members",
    "locations",
    "location_history",
    "ptt_channels",
    "ptt_channel_members",
    "ptt_sessions",
    "refresh_tokens",
}

# Tabela interna do Alembic — não faz parte do domínio.
ALEMBIC_ONLY = {"alembic_version_pkc"}


@pytest.fixture(scope="module")
def migration_sql() -> str:
    """SQL completo da migration inicial, sem tocar no PostgreSQL."""
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        command.upgrade(config, "head", sql=True)
    return buffer.getvalue()


def _orm_constraints() -> set[str]:
    return {
        constraint.name
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if constraint.name is not None
    }


def _orm_indexes() -> set[str]:
    return {
        index.name
        for table in Base.metadata.tables.values()
        for index in table.indexes
        if index.name is not None
    }


def test_all_expected_tables_are_mapped() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_migration_creates_every_mapped_table(migration_sql: str) -> None:
    for table in EXPECTED_TABLES:
        assert f"CREATE TABLE {table} " in migration_sql, f"tabela ausente: {table}"


def test_migration_enables_postgis(migration_sql: str) -> None:
    assert "CREATE EXTENSION IF NOT EXISTS postgis;" in migration_sql


def test_geo_columns_are_postgis_geography(migration_sql: str) -> None:
    # `locations.geom` e `location_history.geom`, ambos SRID 4326.
    assert migration_sql.count("geography(POINT,4326)") == 2
    assert migration_sql.count("USING gist (geom)") == 2


def test_constraint_names_match_between_orm_and_migration(migration_sql: str) -> None:
    sql_names = set(re.findall(r"CONSTRAINT (\w+) ", migration_sql)) - ALEMBIC_ONLY
    assert sql_names == _orm_constraints()


def test_index_names_match_between_orm_and_migration(migration_sql: str) -> None:
    sql_names = set(re.findall(r"CREATE (?:UNIQUE )?INDEX (\w+) ", migration_sql))
    assert sql_names == _orm_indexes()


def test_uuid_primary_keys_have_server_default() -> None:
    """`gen_random_uuid()` deve existir no ORM, senão o autogenerate proporá drop."""
    for name in ("users", "circles", "ptt_channels", "ptt_sessions", "refresh_tokens"):
        column = Base.metadata.tables[name].c["id"]
        assert column.server_default is not None, f"{name}.id sem server_default"


def test_circle_members_has_no_redundant_unique_constraint() -> None:
    """A PK composta já garante unicidade; constraint extra só geraria índice inútil."""
    names = {constraint.name for constraint in Base.metadata.tables["circle_members"].constraints}
    assert "ux_circle_members_circle_user" not in names


def test_only_one_owner_per_circle_is_enforced_by_partial_index() -> None:
    index = next(
        i
        for i in Base.metadata.tables["circle_members"].indexes
        if i.name == "ux_circle_single_owner"
    )
    assert index.unique is True
    assert "role = 'owner'" in str(index.dialect_options["postgresql"]["where"])


def test_history_idempotency_key_exists() -> None:
    names = {constraint.name for constraint in Base.metadata.tables["location_history"].constraints}
    assert "ux_history_user_seq" in names
