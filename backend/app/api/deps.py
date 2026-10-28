"""Dependências compartilhadas dos routers HTTP.

Duas regras:

* **transação por requisição** — `get_session` faz `commit()` no fim e `rollback()`
  em qualquer exceção; os repositórios só fazem `flush()` (ver `protocols.py`);
* **401 sempre explícito** — `HTTPBearer(auto_error=False)` porque o default do
  FastAPI responde **403** quando o header `Authorization` está ausente, o que
  quebraria o contrato (`docs/ARCHITECTURE.md` §7.1).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated, cast
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.container import Services
from app.core.errors import RateLimitedError, UnauthorizedError
from app.core.security import TokenError, TokenType, decode_token
from app.models.user import User
from app.repositories.circle_repository import CircleRepository
from app.repositories.location_repository import LocationRepository
from app.repositories.protocols import (
    CircleRepositoryProtocol,
    LocationRepositoryProtocol,
    PttChannelWriterProtocol,
    TokenRepositoryProtocol,
    UserRepositoryProtocol,
)
from app.repositories.ptt_channel_repository import PttChannelRepository
from app.repositories.token_repository import TokenRepository
from app.repositories.user_repository import UserRepository
from app.services.auth_service import AuthService
from app.services.circle_service import CircleService
from app.services.location_service import LocationService
from app.services.user_service import UserService

bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="AccessToken",
    description="JWT de acesso emitido por `/auth/login` (TTL de 15 min).",
)


# --------------------------------------------------------------------------- infra
def get_services(request: Request) -> Services:
    """Container de serviços criado no `lifespan`."""
    return cast(Services, request.app.state.services)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Sessão de banco por requisição — commit no sucesso, rollback em erro."""
    services = get_services(request)
    async with services.db.session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()


def client_ip(request: Request, settings: Settings) -> str:
    """IP do cliente para rate limit.

    `X-Forwarded-For` só é confiável atrás de um proxy conhecido — por isso exige
    `TRUST_PROXY_HEADERS=true` (default `false`). Caso contrário, um cliente
    malicioso forjaria o header e escaparia do limite.
    """
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# --------------------------------------------------------------------------- tipos
ServicesDep = Annotated[Services, Depends(get_services)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


# --------------------------------------------------------------------------- repos
def get_user_repo(session: SessionDep) -> UserRepositoryProtocol:
    return UserRepository(session)


def get_token_repo(session: SessionDep) -> TokenRepositoryProtocol:
    return TokenRepository(session)


def get_circle_repo(session: SessionDep) -> CircleRepositoryProtocol:
    return CircleRepository(session)


def get_location_repo(session: SessionDep) -> LocationRepositoryProtocol:
    return LocationRepository(session)


def get_ptt_channel_repo(session: SessionDep) -> PttChannelWriterProtocol:
    return PttChannelRepository(session)


UserRepoDep = Annotated[UserRepositoryProtocol, Depends(get_user_repo)]
TokenRepoDep = Annotated[TokenRepositoryProtocol, Depends(get_token_repo)]
CircleRepoDep = Annotated[CircleRepositoryProtocol, Depends(get_circle_repo)]
LocationRepoDep = Annotated[LocationRepositoryProtocol, Depends(get_location_repo)]
ChannelRepoDep = Annotated[PttChannelWriterProtocol, Depends(get_ptt_channel_repo)]


# --------------------------------------------------------------------------- services
def get_auth_service(
    users: UserRepoDep,
    tokens: TokenRepoDep,
    services: ServicesDep,
) -> AuthService:
    return AuthService(users=users, tokens=tokens, settings=services.settings)


def get_user_service(users: UserRepoDep) -> UserService:
    return UserService(users=users)


def get_circle_service(circles: CircleRepoDep, channels: ChannelRepoDep) -> CircleService:
    return CircleService(circles=circles, channels=channels)


def get_location_service(
    locations: LocationRepoDep,
    circles: CircleRepoDep,
    users: UserRepoDep,
    services: ServicesDep,
) -> LocationService:
    return LocationService(
        locations=locations,
        circles=circles,
        users=users,
        manager=services.connections,
    )


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
UserServiceDep = Annotated[UserService, Depends(get_user_service)]
CircleServiceDep = Annotated[CircleService, Depends(get_circle_service)]
LocationServiceDep = Annotated[LocationService, Depends(get_location_service)]


# --------------------------------------------------------------------------- auth
async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    services: ServicesDep,
    users: UserRepoDep,
) -> User:
    """Valida o Bearer token e carrega o usuário.

    Qualquer falha vira **401** com o mesmo envelope — nunca distinguimos
    "token expirado" de "usuário removido" para o cliente.
    """
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError("token de acesso ausente")

    try:
        claims = decode_token(
            credentials.credentials,
            settings=services.settings,
            expected_type=TokenType.ACCESS,
        )
    except TokenError as exc:
        raise UnauthorizedError(str(exc)) from exc

    user = await users.get_by_id(cast(UUID, claims["user_id"]))
    if user is None:
        raise UnauthorizedError("usuário não encontrado")
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


# --------------------------------------------------------------------------- limites
def auth_rate_limit(request: Request, services: ServicesDep) -> None:
    """5 req/min/IP em `/auth/register` e `/auth/login` (anti credential stuffing)."""
    key = client_ip(request, services.settings)
    if not services.auth_limiter.allow(key):
        raise RateLimitedError(retry_after=services.auth_limiter.retry_after_seconds(key))
