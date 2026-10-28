"""Utilitário de leitura de `rowcount` para comandos DML.

Motivo: `AsyncSession.execute()` é tipado como `Result[Any]`, mas comandos
`INSERT`/`UPDATE`/`DELETE` devolvem `CursorResult`, que expõe `rowcount`. Em vez
de espalhar `# type: ignore` pelos repositórios, centralizamos o cast aqui.
"""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import Result


def affected_rows(result: Result[Any]) -> int:
    """Número de linhas afetadas por um `INSERT`/`UPDATE`/`DELETE`."""
    return int(cast(Any, result).rowcount or 0)
