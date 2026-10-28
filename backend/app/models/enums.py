"""Enumerações persistidas no banco.

`values_callable` garante que o PostgreSQL armazene o **valor** (`android`) e não
o **nome** do membro Python (`ANDROID`) — evita divergência com o DDL documentado.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from sqlalchemy import Enum as SAEnum


class Platform(StrEnum):
    ANDROID = "android"
    IOS = "ios"


class CircleRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


def enum_values(enum_cls: type[StrEnum]) -> list[str]:
    """Valores na ordem de declaração (usado como `values_callable`)."""
    return [member.value for member in enum_cls]


def str_enum(enum_cls: type[StrEnum], name: str) -> SAEnum:
    """Cria um tipo ENUM nativo do PostgreSQL a partir de um `StrEnum`."""
    kwargs: dict[str, Any] = {
        "name": name,
        "native_enum": True,
        "values_callable": enum_values,
        "validate_strings": True,
    }
    return SAEnum(enum_cls, **kwargs)
