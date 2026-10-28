"""Registro central dos modelos ORM.

Importar este pacote garante que `Base.metadata` conheça todas as tabelas —
requisito para o autogenerate do Alembic e para os testes de metadata.
"""

from __future__ import annotations

from app.models.circle import Circle, CircleMember
from app.models.enums import CircleRole, Platform
from app.models.location import Location, LocationHistory
from app.models.ptt import PttChannel, PttChannelMember, PttSession
from app.models.token import RefreshToken
from app.models.user import User

__all__ = [
    "Circle",
    "CircleMember",
    "CircleRole",
    "Location",
    "LocationHistory",
    "Platform",
    "PttChannel",
    "PttChannelMember",
    "PttSession",
    "RefreshToken",
    "User",
]
