"""Rotas de perfil do usuário autenticado e registro de push."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUserDep, UserServiceDep
from app.schemas.errors import NOT_FOUND, UNAUTHORIZED, VALIDATION
from app.schemas.users import FcmTokenRequest, UserPublic, UserUpdate

router = APIRouter(
    prefix="/users",
    tags=["users"],
    responses={401: UNAUTHORIZED, 404: NOT_FOUND, 422: VALIDATION},
)


@router.get("/me", response_model=UserPublic, summary="Perfil do usuário autenticado")
async def read_me(user: CurrentUserDep) -> UserPublic:
    return UserPublic.model_validate(user)


@router.patch("/me", response_model=UserPublic, summary="Atualiza perfil (parcial)")
async def update_me(
    payload: UserUpdate,
    user: CurrentUserDep,
    service: UserServiceDep,
) -> UserPublic:
    updated = await service.update(
        user.id,
        display_name=payload.display_name,
        is_sharing_location=payload.is_sharing_location,
    )
    return UserPublic.model_validate(updated)


@router.post(
    "/me/fcm-token",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Registra o token FCM do dispositivo (idempotente)",
)
async def register_fcm_token(
    payload: FcmTokenRequest,
    user: CurrentUserDep,
    service: UserServiceDep,
) -> Response:
    await service.register_fcm_token(
        user.id, fcm_token=payload.fcm_token, platform=payload.platform
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/me/fcm-token",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove o token FCM (logout)",
)
async def delete_fcm_token(user: CurrentUserDep, service: UserServiceDep) -> Response:
    await service.remove_fcm_token(user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
