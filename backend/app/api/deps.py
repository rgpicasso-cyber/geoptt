"""Dependências compartilhadas dos routers HTTP."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import cast

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.container import Services


def get_services(request: Request) -> Services:
    """Container de serviços criado no `lifespan`."""
    return cast(Services, request.app.state.services)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Sessão de banco por requisição (commit é responsabilidade do service)."""
    services = get_services(request)
    async with services.db.session_factory() as session:
        yield session
