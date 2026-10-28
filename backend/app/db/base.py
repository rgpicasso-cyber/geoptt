"""Base declarativa do SQLAlchemy com convenção de nomes determinística.

A convenção garante que constraints e índices gerados por `create_all`/Alembic
tenham nomes previsíveis entre ambientes — requisito para migrations reversíveis.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION: Final = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "ux_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Classe base de todos os modelos ORM."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
