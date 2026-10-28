"""Rotas de círculos.

Nota de contrato: para círculos dos quais o solicitante **não** é membro
devolvemos `404` (nunca `403`), evitando um oráculo de existência de IDs.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Response, status

from app.api.deps import CircleServiceDep, CurrentUserDep
from app.repositories.protocols import CircleSummary, MemberView
from app.schemas.circles import (
    CircleCreate,
    CircleJoinRequest,
    CircleListResponse,
    CircleMemberPublic,
    CircleMembersResponse,
    CirclePublic,
)
from app.schemas.errors import CONFLICT, FORBIDDEN, NOT_FOUND, UNAUTHORIZED, VALIDATION

router = APIRouter(
    prefix="/circles",
    tags=["circles"],
    responses={
        401: UNAUTHORIZED,
        403: FORBIDDEN,
        404: NOT_FOUND,
        409: CONFLICT,
        422: VALIDATION,
    },
)


def _to_public(summary: CircleSummary) -> CirclePublic:
    return CirclePublic(
        id=summary.id,
        name=summary.name,
        owner_id=summary.owner_id,
        invite_code=summary.invite_code,
        role=summary.role,
        member_count=summary.member_count,
        created_at=summary.created_at,
    )


def _to_member(view: MemberView) -> CircleMemberPublic:
    return CircleMemberPublic(
        user_id=view.user_id,
        display_name=view.display_name,
        role=view.role,
        battery_level=view.battery_level,
        is_sharing_location=view.is_sharing_location,
        last_seen_at=view.last_seen_at,
        lat=view.lat,
        lng=view.lng,
        accuracy_m=view.accuracy_m,
        speed_mps=view.speed_mps,
        heading_deg=view.heading_deg,
        recorded_at=view.recorded_at,
    )


@router.post(
    "",
    response_model=CirclePublic,
    status_code=status.HTTP_201_CREATED,
    summary="Cria círculo (owner + canal PTT 'Geral')",
)
async def create_circle(
    payload: CircleCreate,
    user: CurrentUserDep,
    service: CircleServiceDep,
) -> CirclePublic:
    summary = await service.create(name=payload.name, owner_id=user.id)
    return _to_public(summary)


@router.post("/join", response_model=CirclePublic, summary="Entra por código de convite")
async def join_circle(
    payload: CircleJoinRequest,
    user: CurrentUserDep,
    service: CircleServiceDep,
) -> CirclePublic:
    summary = await service.join(invite_code=payload.invite_code, user_id=user.id)
    return _to_public(summary)


@router.get("", response_model=CircleListResponse, summary="Círculos do usuário")
async def list_circles(
    user: CurrentUserDep,
    service: CircleServiceDep,
) -> CircleListResponse:
    summaries = await service.list_for_user(user.id)
    return CircleListResponse(items=[_to_public(summary) for summary in summaries])


@router.get(
    "/{circle_id}/members",
    response_model=CircleMembersResponse,
    summary="Membros com última posição conhecida",
)
async def list_members(
    circle_id: UUID,
    user: CurrentUserDep,
    service: CircleServiceDep,
) -> CircleMembersResponse:
    members = await service.list_members(circle_id=circle_id, requester_id=user.id)
    return CircleMembersResponse(
        circle_id=circle_id,
        items=[_to_member(member) for member in members],
    )


@router.delete(
    "/{circle_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove membro (ou sai do círculo, se for você)",
)
async def remove_member(
    circle_id: UUID,
    user_id: UUID,
    user: CurrentUserDep,
    service: CircleServiceDep,
) -> Response:
    await service.remove_member(
        circle_id=circle_id,
        requester_id=user.id,
        target_id=user_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
