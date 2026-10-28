"""Engine e fábrica de sessões assíncronas.

Uma única `Database` por processo, criada no `lifespan` e descartada no shutdown.
Sessões são curtas e nunca atravessam I/O de rede (WebSocket) — ver `PttService`.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import Settings

logger = logging.getLogger(__name__)


class Database:
    """Wrapper fino em volta do engine assíncrono."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine: AsyncEngine = create_async_engine(
            settings.database_url,
            echo=settings.db_echo,
            pool_pre_ping=True,
            future=True,
            **_pool_kwargs(settings),
        )
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return self._session_factory

    async def ping(self) -> bool:
        """`SELECT 1` — usado pelo readiness probe."""
        try:
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:
            logger.warning("database ping failed", exc_info=True, extra={"event": "db_ping"})
            return False
        return True

    async def dispose(self) -> None:
        await self._engine.dispose()


def _pool_kwargs(settings: Settings) -> dict[str, Any]:
    """SQLite (dev/testes) não suporta pool dimensionado; usa NullPool."""
    if settings.database_url.startswith("sqlite"):
        return {"poolclass": NullPool}
    return {
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_recycle": settings.db_pool_recycle_seconds,
    }
