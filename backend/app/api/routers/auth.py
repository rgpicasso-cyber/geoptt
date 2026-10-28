"""Rotas de autenticação.

`login` usa `application/x-www-form-urlencoded` (OAuth2 password flow) para
funcionar com o botão *Authorize* do Swagger; `username` recebe o e-mail.
`register`, `refresh` e `logout` usam JSON.

Todo endpoint que emite token exige o header `X-Device-Id` — é a chave de
rotação/revogação por dispositivo (`refresh_tokens.device_id`).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import (
    AuthServiceDep,
    CurrentUserDep,
    auth_rate_limit,
)
from app.schemas.auth import LogoutRequest, RefreshRequest, RegisterRequest, TokenPair
from app.schemas.errors import CONFLICT, RATE_LIMITED, UNAUTHORIZED, VALIDATION
from app.services.auth_service import IssuedTokens

router = APIRouter(prefix="/auth", tags=["auth"], responses={422: VALIDATION})

DeviceId = Annotated[
    str,
    Header(
        alias="X-Device-Id",
        min_length=1,
        max_length=120,
        description="Identificador estável do dispositivo (ex.: installation id).",
    ),
]


def _to_pair(issued: IssuedTokens) -> TokenPair:
    return TokenPair(
        access_token=issued.access_token,
        refresh_token=issued.refresh_token,
        expires_in=issued.expires_in,
        refresh_expires_in=issued.refresh_expires_in,
    )


@router.post(
    "/register",
    response_model=TokenPair,
    status_code=status.HTTP_201_CREATED,
    summary="Cria conta e devolve o par de tokens",
    dependencies=[Depends(auth_rate_limit)],
    responses={409: CONFLICT, 429: RATE_LIMITED},
)
async def register(
    payload: RegisterRequest,
    device_id: DeviceId,
    service: AuthServiceDep,
) -> TokenPair:
    issued = await service.register(
        email=str(payload.email),
        password=payload.password,
        display_name=payload.display_name,
        device_id=device_id,
    )
    return _to_pair(issued)


@router.post(
    "/login",
    response_model=TokenPair,
    summary="OAuth2 password flow (username = e-mail)",
    dependencies=[Depends(auth_rate_limit)],
    responses={401: UNAUTHORIZED, 429: RATE_LIMITED},
)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    device_id: DeviceId,
    service: AuthServiceDep,
) -> TokenPair:
    issued = await service.login(
        email=form.username,
        password=form.password,
        device_id=device_id,
    )
    return _to_pair(issued)


@router.post(
    "/refresh",
    response_model=TokenPair,
    summary="Rotaciona o par de tokens (o refresh usado é revogado)",
)
async def refresh(
    payload: RefreshRequest,
    device_id: DeviceId,
    service: AuthServiceDep,
) -> TokenPair:
    issued = await service.refresh(refresh_token=payload.refresh_token, device_id=device_id)
    return _to_pair(issued)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoga o refresh do dispositivo (ou todas as sessões)",
)
async def logout(
    payload: LogoutRequest,
    user: CurrentUserDep,
    service: AuthServiceDep,
) -> Response:
    await service.logout(user_id=user.id, device_id=payload.device_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
