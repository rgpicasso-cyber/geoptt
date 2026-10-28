"""Rotas de localização: ingestão de lote (fila offline) e snapshot do mapa."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import CurrentUserDep, LocationServiceDep
from app.repositories.protocols import PositionView
from app.schemas.errors import NOT_FOUND, UNAUTHORIZED, VALIDATION
from app.schemas.location import (
    CirclePositionsResponse,
    LocationBatchRequest,
    LocationBatchResponse,
    PositionPublic,
)

router = APIRouter(
    prefix="/location",
    tags=["location"],
    responses={401: UNAUTHORIZED, 404: NOT_FOUND, 422: VALIDATION},
)


def _to_public(view: PositionView) -> PositionPublic:
    return PositionPublic(
        user_id=view.user_id,
        display_name=view.display_name,
        lat=view.lat,
        lng=view.lng,
        accuracy_m=view.accuracy_m,
        speed_mps=view.speed_mps,
        heading_deg=view.heading_deg,
        battery_level=view.battery_level,
        recorded_at=view.recorded_at,
    )


@router.post(
    "/batch",
    response_model=LocationBatchResponse,
    summary="Ingere até 50 pontos (idempotente por client_seq)",
)
async def ingest_batch(
    payload: LocationBatchRequest,
    user: CurrentUserDep,
    service: LocationServiceDep,
) -> LocationBatchResponse:
    result = await service.ingest_batch(user_id=user.id, points=payload.points)
    return LocationBatchResponse(
        accepted=result.accepted,
        duplicated=result.duplicated,
        server_ts=result.server_ts,
    )


@router.get(
    "/circle/{circle_id}",
    response_model=CirclePositionsResponse,
    summary="Snapshot de posições do círculo (para o mapa)",
)
async def circle_positions(
    circle_id: UUID,
    user: CurrentUserDep,
    service: LocationServiceDep,
) -> CirclePositionsResponse:
    positions = await service.circle_positions(circle_id=circle_id, requester_id=user.id)
    return CirclePositionsResponse(
        circle_id=circle_id,
        items=[_to_public(position) for position in positions],
    )
