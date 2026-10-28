"""Container de serviços anexado a `app.state.services`.

Centraliza as dependências de runtime com tipagem explícita, evitando
`getattr(app.state, ...)` espalhado pelo código (e mantendo o mypy feliz).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.core.config import Settings

if TYPE_CHECKING:  # pragma: no cover - apenas para tipagem
    from app.db.session import Database
    from app.services.connection_manager import ConnectionManager
    from app.services.fcm_service import FcmService
    from app.services.ptt_service import PttService


@dataclass(slots=True)
class Services:
    """Dependências vivas durante o ciclo de vida da aplicação."""

    settings: Settings
    db: Database
    connections: ConnectionManager
    fcm: FcmService
    ptt: PttService
