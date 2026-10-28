"""Testes de `LocationService` — ingestão idempotente, snapshot e broadcast."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.core.errors import NotFoundError
from app.models.enums import CircleRole
from app.repositories.protocols import PositionView
from app.schemas.location import LocationPoint
from app.services.connection_manager import ConnectionManager
from app.services.location_service import BROADCAST_MAX_AGE, LocationService
from tests.fakes import (
    FakeCircleRepository,
    FakeLocationRepository,
    FakeUserRepository,
    make_circle,
    make_user,
)
from tests.helpers import FakeWebSocket, wait_until


def point(
    *,
    seq: int = 1,
    recorded_at: datetime | None = None,
    lat: float = -23.5505,
    lng: float = -46.6333,
    battery: int | None = 80,
) -> LocationPoint:
    return LocationPoint(
        lat=lat,
        lng=lng,
        accuracy_m=12.5,
        speed_mps=1.2,
        heading_deg=90.0,
        battery_level=battery,
        client_seq=seq,
        recorded_at=recorded_at or datetime.now(UTC),
    )


def build_service(
    *,
    users: FakeUserRepository,
    circles: FakeCircleRepository,
    locations: FakeLocationRepository,
    manager: ConnectionManager | None = None,
) -> LocationService:
    return LocationService(
        locations=locations,
        circles=circles,
        users=users,
        manager=manager or ConnectionManager(),
    )


# --------------------------------------------------------------------------- ingestão
async def test_ingest_persists_history_current_and_presence() -> None:
    user = make_user()
    users = FakeUserRepository()
    users.seed(user)
    locations = FakeLocationRepository()
    service = build_service(users=users, circles=FakeCircleRepository(), locations=locations)

    now = datetime.now(UTC)
    result = await service.ingest_batch(
        user_id=user.id,
        points=[
            point(seq=1, recorded_at=now - timedelta(seconds=30)),
            point(seq=2, recorded_at=now),
        ],
    )

    assert (result.accepted, result.duplicated) == (2, 0)
    assert len(locations.history) == 2
    assert locations.current[user.id].client_seq == 2
    assert user.last_seen_at is not None
    assert user.battery_level == 80


async def test_ingest_is_idempotent_by_client_seq() -> None:
    user = make_user()
    users = FakeUserRepository()
    users.seed(user)
    locations = FakeLocationRepository()
    service = build_service(users=users, circles=FakeCircleRepository(), locations=locations)
    batch = [point(seq=1), point(seq=2)]

    first = await service.ingest_batch(user_id=user.id, points=batch)
    second = await service.ingest_batch(user_id=user.id, points=batch)

    assert (first.accepted, first.duplicated) == (2, 0)
    assert (second.accepted, second.duplicated) == (0, 2)
    assert len(locations.history) == 2


async def test_ingest_picks_current_by_recorded_at_not_array_order() -> None:
    """A fila offline pode ser drenada fora de ordem."""
    user = make_user()
    users = FakeUserRepository()
    users.seed(user)
    locations = FakeLocationRepository()
    service = build_service(users=users, circles=FakeCircleRepository(), locations=locations)

    now = datetime.now(UTC)
    older = point(seq=1, recorded_at=now - timedelta(minutes=1), lat=-23.0)
    newer = point(seq=2, recorded_at=now, lat=-24.0)

    await service.ingest_batch(user_id=user.id, points=[newer, older])

    assert locations.current[user.id].lat == pytest.approx(-24.0)


async def test_ingest_accepts_only_stale_points() -> None:
    """Histórico antigo é gravado normalmente, apenas não vira broadcast."""
    user = make_user()
    users = FakeUserRepository()
    users.seed(user)
    locations = FakeLocationRepository()
    service = build_service(users=users, circles=FakeCircleRepository(), locations=locations)

    stale = point(recorded_at=datetime.now(UTC) - BROADCAST_MAX_AGE - timedelta(minutes=1))
    result = await service.ingest_batch(user_id=user.id, points=[stale])

    assert result.accepted == 1
    assert locations.current[user.id].client_seq == stale.client_seq


# --------------------------------------------------------------------------- broadcast
async def test_fresh_point_is_broadcast_to_circle_peers() -> None:
    user, peer = make_user(display_name="Ana"), make_user(email="bia@example.com")
    users = FakeUserRepository()
    users.seed(user)
    users.seed(peer)

    circles = FakeCircleRepository()
    circle = circles.seed_circle(make_circle(owner_id=user.id))
    circles.seed_member(circle.id, user, CircleRole.OWNER)
    circles.seed_member(circle.id, peer, CircleRole.MEMBER)

    manager = ConnectionManager()
    ws = FakeWebSocket()
    connection = await manager.register(ws, peer.id)  # type: ignore[arg-type]

    try:
        service = build_service(
            users=users, circles=circles, locations=FakeLocationRepository(), manager=manager
        )
        await service.ingest_batch(user_id=user.id, points=[point()])

        await wait_until(lambda: bool(ws.sent_text))
        payload = json.loads(ws.sent_text[0])
        assert payload["type"] == "LOCATION_UPDATE"
        assert payload["data"]["user_id"] == str(user.id)
        assert payload["data"]["lat"] == pytest.approx(-23.5505)
    finally:
        await manager.unregister(connection)


async def test_stale_point_is_not_broadcast() -> None:
    user, peer = make_user(), make_user(email="bia@example.com")
    users = FakeUserRepository()
    users.seed(user)
    users.seed(peer)

    circles = FakeCircleRepository()
    circle = circles.seed_circle(make_circle(owner_id=user.id))
    circles.seed_member(circle.id, user, CircleRole.OWNER)
    circles.seed_member(circle.id, peer, CircleRole.MEMBER)

    manager = ConnectionManager()
    ws = FakeWebSocket()
    connection = await manager.register(ws, peer.id)  # type: ignore[arg-type]

    try:
        service = build_service(
            users=users, circles=circles, locations=FakeLocationRepository(), manager=manager
        )
        await service.ingest_batch(
            user_id=user.id,
            points=[
                point(recorded_at=datetime.now(UTC) - BROADCAST_MAX_AGE - timedelta(seconds=1))
            ],
        )

        # Dá tempo ao writer task antes de afirmar ausência.
        await wait_until(lambda: True)
        assert ws.sent_text == []
    finally:
        await manager.unregister(connection)


async def test_broadcast_failure_does_not_break_ingest() -> None:
    class ExplodingCircleRepository(FakeCircleRepository):
        async def list_broadcast_recipients(self, user_id: UUID) -> list[UUID]:  # type: ignore[override]
            raise RuntimeError("presença indisponível")

    user = make_user()
    users = FakeUserRepository()
    users.seed(user)
    locations = FakeLocationRepository()
    service = build_service(users=users, circles=ExplodingCircleRepository(), locations=locations)

    result = await service.ingest_batch(user_id=user.id, points=[point()])

    assert result.accepted == 1
    assert locations.current[user.id] is not None


# --------------------------------------------------------------------------- mapa
async def test_circle_positions_requires_membership() -> None:
    user = make_user()
    circles = FakeCircleRepository()
    circle = circles.seed_circle(make_circle(owner_id=user.id))
    service = build_service(
        users=FakeUserRepository(), circles=circles, locations=FakeLocationRepository()
    )

    with pytest.raises(NotFoundError):
        await service.circle_positions(circle_id=circle.id, requester_id=uuid4())


async def test_circle_positions_of_missing_circle_is_404() -> None:
    service = build_service(
        users=FakeUserRepository(),
        circles=FakeCircleRepository(),
        locations=FakeLocationRepository(),
    )

    with pytest.raises(NotFoundError):
        await service.circle_positions(circle_id=uuid4(), requester_id=uuid4())


async def test_circle_positions_returns_snapshot_for_member() -> None:
    user = make_user()
    circles = FakeCircleRepository()
    circle = circles.seed_circle(make_circle(owner_id=user.id))
    circles.seed_member(circle.id, user, CircleRole.OWNER)

    locations = FakeLocationRepository()
    locations.seed_positions(
        circle.id,
        [
            PositionView(
                user_id=user.id,
                display_name="Ana",
                lat=-23.55,
                lng=-46.63,
                accuracy_m=8.0,
                speed_mps=0.0,
                heading_deg=None,
                battery_level=75,
                recorded_at=datetime.now(UTC),
            )
        ],
    )
    service = build_service(users=FakeUserRepository(), circles=circles, locations=locations)

    positions = await service.circle_positions(circle_id=circle.id, requester_id=user.id)

    assert [position.user_id for position in positions] == [user.id]
