"""Testes de contrato REST: autenticação, autorização e códigos de erro.

Nenhum teste toca PostgreSQL: os `Depends` de repositório são sobrescritos por
dublês em memória (`tests/fakes.py`). O que se valida aqui é o **contrato**
descrito em `docs/ARCHITECTURE.md` §7.1 — status, envelope de erro e isolamento
entre círculos.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.deps import (
    get_circle_repo,
    get_location_repo,
    get_ptt_channel_repo,
    get_token_repo,
    get_user_repo,
)
from app.core.config import Settings
from app.core.security import create_access_token, hash_password
from app.main import create_app
from app.models.enums import CircleRole
from tests.fakes import (
    FakeCircleRepository,
    FakeLocationRepository,
    FakePttChannelWriter,
    FakeTokenRepository,
    FakeUserRepository,
    make_circle,
    make_user,
)

PREFIX = "/api/v1"
DEVICE = "device-test"


@dataclass
class Api:
    client: TestClient
    users: FakeUserRepository
    tokens: FakeTokenRepository
    circles: FakeCircleRepository
    locations: FakeLocationRepository
    channels: FakePttChannelWriter
    settings: Settings

    def auth(self, user_id: Any) -> dict[str, str]:
        token = create_access_token(subject=user_id, settings=self.settings)
        return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def api(settings: Settings) -> Iterator[Api]:
    app = create_app(settings)
    users, tokens = FakeUserRepository(), FakeTokenRepository()
    circles, locations, channels = (
        FakeCircleRepository(),
        FakeLocationRepository(),
        FakePttChannelWriter(),
    )

    app.dependency_overrides[get_user_repo] = lambda: users
    app.dependency_overrides[get_token_repo] = lambda: tokens
    app.dependency_overrides[get_circle_repo] = lambda: circles
    app.dependency_overrides[get_location_repo] = lambda: locations
    app.dependency_overrides[get_ptt_channel_repo] = lambda: channels

    with TestClient(app) as client:
        yield Api(
            client=client,
            users=users,
            tokens=tokens,
            circles=circles,
            locations=locations,
            channels=channels,
            settings=settings,
        )


def seed_user(api: Api, *, email: str = "ana@example.com", display_name: str = "Ana"):
    user = make_user(
        email=email, display_name=display_name, password_hash=hash_password("Senha-forte-123")
    )
    api.users.seed(user)
    return user


def seed_circle(api: Api, owner) -> Any:
    circle = api.circles.seed_circle(make_circle(owner_id=owner.id))
    api.circles.seed_member(circle.id, owner, CircleRole.OWNER)
    return circle


# --------------------------------------------------------------------------- 401
@pytest.mark.parametrize(
    "method, path",
    [
        ("get", f"{PREFIX}/users/me"),
        ("get", f"{PREFIX}/circles"),
        ("post", f"{PREFIX}/location/batch"),
    ],
)
def test_protected_routes_require_token(api: Api, method: str, path: str) -> None:
    response = getattr(api.client, method)(path)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_malformed_token_is_401_not_403(api: Api) -> None:
    response = api.client.get(
        f"{PREFIX}/users/me", headers={"Authorization": "Bearer nao-e-um-jwt"}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_token_of_deleted_user_is_401(api: Api) -> None:
    ghost = make_user(email="ghost@example.com")

    response = api.client.get(f"{PREFIX}/users/me", headers=api.auth(ghost.id))

    assert response.status_code == 401


# --------------------------------------------------------------------------- perfil
def test_me_returns_own_profile(api: Api) -> None:
    user = seed_user(api)

    response = api.client.get(f"{PREFIX}/users/me", headers=api.auth(user.id))

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "ana@example.com"
    assert "password_hash" not in body
    assert "fcm_token" not in body


def test_patch_me_rejects_empty_payload(api: Api) -> None:
    user = seed_user(api)

    response = api.client.patch(f"{PREFIX}/users/me", headers=api.auth(user.id), json={})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


# --------------------------------------------------------------------------- círculos
def test_list_circles_returns_membership_role(api: Api) -> None:
    user = seed_user(api)
    seed_circle(api, user)

    response = api.client.get(f"{PREFIX}/circles", headers=api.auth(user.id))

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["role"] == CircleRole.OWNER.value


def test_members_of_foreign_circle_is_404(api: Api) -> None:
    owner = seed_user(api)
    intruder = seed_user(api, email="bia@example.com", display_name="Bia")
    circle = seed_circle(api, owner)

    response = api.client.get(
        f"{PREFIX}/circles/{circle.id}/members", headers=api.auth(intruder.id)
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_members_of_missing_circle_is_404(api: Api) -> None:
    user = seed_user(api)

    response = api.client.get(
        f"{PREFIX}/circles/00000000-0000-0000-0000-000000000000/members",
        headers=api.auth(user.id),
    )

    assert response.status_code == 404


def test_plain_member_cannot_remove_peer_403(api: Api) -> None:
    owner = seed_user(api)
    guest = seed_user(api, email="bia@example.com", display_name="Bia")
    other = seed_user(api, email="caio@example.com", display_name="Caio")
    circle = seed_circle(api, owner)
    api.circles.seed_member(circle.id, guest, CircleRole.MEMBER)
    api.circles.seed_member(circle.id, other, CircleRole.MEMBER)

    response = api.client.delete(
        f"{PREFIX}/circles/{circle.id}/members/{other.id}", headers=api.auth(guest.id)
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert api.circles.members.get((circle.id, other.id)) is not None


def test_owner_can_remove_member_204(api: Api) -> None:
    owner = seed_user(api)
    guest = seed_user(api, email="bia@example.com", display_name="Bia")
    circle = seed_circle(api, owner)
    api.circles.seed_member(circle.id, guest, CircleRole.MEMBER)

    response = api.client.delete(
        f"{PREFIX}/circles/{circle.id}/members/{guest.id}", headers=api.auth(owner.id)
    )

    assert response.status_code == 204
    assert api.circles.members.get((circle.id, guest.id)) is None


def test_owner_cannot_be_removed_400(api: Api) -> None:
    owner = seed_user(api)
    circle = seed_circle(api, owner)

    response = api.client.delete(
        f"{PREFIX}/circles/{circle.id}/members/{owner.id}", headers=api.auth(owner.id)
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CANNOT_REMOVE_OWNER"


def test_join_with_invalid_code_is_404(api: Api) -> None:
    user = seed_user(api)

    response = api.client.post(
        f"{PREFIX}/circles/join", headers=api.auth(user.id), json={"invite_code": "ZZZZ9999"}
    )

    assert response.status_code == 404


def test_join_twice_is_409_already_member(api: Api) -> None:
    owner = seed_user(api)
    guest = seed_user(api, email="bia@example.com", display_name="Bia")
    circle = seed_circle(api, owner)
    api.circles.seed_member(circle.id, guest, CircleRole.MEMBER)

    response = api.client.post(
        f"{PREFIX}/circles/join",
        headers=api.auth(guest.id),
        json={"invite_code": circle.invite_code},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ALREADY_MEMBER"


# --------------------------------------------------------------------------- localização
def _point(seq: int, *, seconds_ago: float = 0.0) -> dict[str, Any]:
    return {
        "lat": -23.5505,
        "lng": -46.6333,
        "accuracy_m": 10.0,
        "speed_mps": 1.0,
        "heading_deg": 45.0,
        "battery_level": 70,
        "client_seq": seq,
        "recorded_at": (datetime.now(UTC) - timedelta(seconds=seconds_ago)).isoformat(),
    }


def test_batch_ingest_returns_counts(api: Api) -> None:
    user = seed_user(api)

    response = api.client.post(
        f"{PREFIX}/location/batch",
        headers=api.auth(user.id),
        json={"points": [_point(1, seconds_ago=30), _point(2)]},
    )

    assert response.status_code == 200
    assert response.json()["accepted"] == 2
    assert api.locations.current[user.id].client_seq == 2


def test_batch_over_limit_is_422(api: Api) -> None:
    user = seed_user(api)

    response = api.client.post(
        f"{PREFIX}/location/batch",
        headers=api.auth(user.id),
        json={"points": [_point(index) for index in range(51)]},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_validation_error_never_echoes_the_payload(api: Api) -> None:
    """Payloads de `/auth/*` carregam senha em claro: o 422 não pode devolvê-la."""
    sentinel = "Z" * 200

    response = api.client.post(
        f"{PREFIX}/auth/register",
        headers={"X-Device-Id": DEVICE},
        json={
            "email": "ana@example.com",
            "password": f"Senha1{sentinel}",
            "display_name": "Ana",
        },
    )

    assert response.status_code == 422
    assert sentinel not in response.text


def test_positions_of_foreign_circle_is_404(api: Api) -> None:
    owner = seed_user(api)
    intruder = seed_user(api, email="bia@example.com", display_name="Bia")
    circle = seed_circle(api, owner)

    response = api.client.get(
        f"{PREFIX}/location/circle/{circle.id}", headers=api.auth(intruder.id)
    )

    assert response.status_code == 404


# --------------------------------------------------------------------------- auth
def test_register_requires_device_header(api: Api) -> None:
    response = api.client.post(
        f"{PREFIX}/auth/register",
        json={"email": "ana@example.com", "password": "Senha-forte-123", "display_name": "Ana"},
    )

    assert response.status_code == 422


def test_register_then_duplicate_is_409(api: Api) -> None:
    payload = {
        "email": "ana@example.com",
        "password": "Senha-forte-123",
        "display_name": "Ana",
    }

    first = api.client.post(
        f"{PREFIX}/auth/register", headers={"X-Device-Id": DEVICE}, json=payload
    )
    second = api.client.post(
        f"{PREFIX}/auth/register", headers={"X-Device-Id": DEVICE}, json=payload
    )

    assert first.status_code == 201
    assert first.json()["token_type"] == "bearer"
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "EMAIL_TAKEN"


def test_login_returns_tokens(api: Api) -> None:
    seed_user(api)

    response = api.client.post(
        f"{PREFIX}/auth/login",
        headers={"X-Device-Id": DEVICE},
        data={"username": "ana@example.com", "password": "Senha-forte-123"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["expires_in"] > 0


def test_login_with_wrong_password_is_401(api: Api) -> None:
    seed_user(api)

    response = api.client.post(
        f"{PREFIX}/auth/login",
        headers={"X-Device-Id": DEVICE},
        data={"username": "ana@example.com", "password": "errada-123"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_login_is_rate_limited_per_ip(api: Api) -> None:
    seed_user(api)

    statuses = [
        api.client.post(
            f"{PREFIX}/auth/login",
            headers={"X-Device-Id": DEVICE},
            data={"username": "ana@example.com", "password": "errada-123"},
        ).status_code
        for _ in range(6)
    ]

    assert statuses[:5] == [401] * 5
    assert statuses[5] == 429

    limited = api.client.post(
        f"{PREFIX}/auth/login",
        headers={"X-Device-Id": DEVICE},
        data={"username": "ana@example.com", "password": "errada-123"},
    )
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"
    assert int(limited.headers["Retry-After"]) >= 1


def test_refresh_reuse_revokes_all_sessions(api: Api) -> None:
    seed_user(api)
    login = api.client.post(
        f"{PREFIX}/auth/login",
        headers={"X-Device-Id": DEVICE},
        data={"username": "ana@example.com", "password": "Senha-forte-123"},
    ).json()

    rotated = api.client.post(
        f"{PREFIX}/auth/refresh",
        headers={"X-Device-Id": DEVICE},
        json={"refresh_token": login["refresh_token"]},
    )
    assert rotated.status_code == 200

    reused = api.client.post(
        f"{PREFIX}/auth/refresh",
        headers={"X-Device-Id": DEVICE},
        json={"refresh_token": login["refresh_token"]},
    )

    assert reused.status_code == 401
    assert reused.json()["error"]["code"] == "TOKEN_REUSED"

    # A sessão rotacionada também caiu.
    after = api.client.post(
        f"{PREFIX}/auth/refresh",
        headers={"X-Device-Id": DEVICE},
        json={"refresh_token": rotated.json()["refresh_token"]},
    )
    assert after.status_code == 401


def test_logout_requires_authentication(api: Api) -> None:
    response = api.client.post(f"{PREFIX}/auth/logout", json={})

    assert response.status_code == 401


def test_logout_revokes_the_device(api: Api) -> None:
    user = seed_user(api)
    login = api.client.post(
        f"{PREFIX}/auth/login",
        headers={"X-Device-Id": DEVICE},
        data={"username": "ana@example.com", "password": "Senha-forte-123"},
    ).json()

    response = api.client.post(
        f"{PREFIX}/auth/logout",
        headers={**api.auth(user.id), "X-Device-Id": DEVICE},
        json={"device_id": DEVICE},
    )

    assert response.status_code == 204
    assert api.tokens.active_for(user.id) == []

    refresh = api.client.post(
        f"{PREFIX}/auth/refresh",
        headers={"X-Device-Id": DEVICE},
        json={"refresh_token": login["refresh_token"]},
    )
    assert refresh.status_code == 401
