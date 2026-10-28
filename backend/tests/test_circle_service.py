"""Testes de `CircleService` — criação, convite e regras de remoção de membro."""

from __future__ import annotations

import pytest

from app.core.errors import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.models.enums import CircleRole
from app.services.circle_service import DEFAULT_CHANNEL_NAME, CircleService
from tests.fakes import (
    FakeCircleRepository,
    FakePttChannelWriter,
    make_circle,
    make_user,
)


def build_service(circles: FakeCircleRepository, channels: FakePttChannelWriter) -> CircleService:
    return CircleService(circles=circles, channels=channels)


async def test_create_makes_owner_member_and_default_channel() -> None:
    circles, channels = FakeCircleRepository(), FakePttChannelWriter()
    owner = make_user(display_name="Ana")
    service = build_service(circles, channels)

    summary = await service.create(name="Família", owner_id=owner.id)

    assert summary.role is CircleRole.OWNER
    assert summary.member_count == 1
    assert len(summary.invite_code) == 8
    assert summary.invite_code.isalnum()

    member = await circles.get_member(summary.id, owner.id)
    assert member is not None and member.role is CircleRole.OWNER

    channel = next(iter(channels.channels.values()))
    assert channel.name == DEFAULT_CHANNEL_NAME
    assert (channel.id, owner.id) in channels.memberships


async def test_invite_code_avoids_ambiguous_characters() -> None:
    """O código é digitado à mão: 0/O e 1/I/L não podem aparecer."""
    circles, channels = FakeCircleRepository(), FakePttChannelWriter()
    service = build_service(circles, channels)

    for index in range(20):
        summary = await service.create(name=f"Círculo {index}", owner_id=make_user().id)
        assert not set(summary.invite_code) & set("O0I1L")


async def test_join_adds_member_and_ptt_channels() -> None:
    circles, channels = FakeCircleRepository(), FakePttChannelWriter()
    owner, guest = make_user(display_name="Ana"), make_user(email="bia@example.com")
    service = build_service(circles, channels)

    created = await service.create(name="Família", owner_id=owner.id)
    joined = await service.join(invite_code=created.invite_code, user_id=guest.id)

    assert joined.role is CircleRole.MEMBER
    assert joined.member_count == 2
    assert (created.id, guest.id) in circles.members

    channel = next(iter(channels.channels.values()))
    assert (channel.id, guest.id) in channels.memberships


async def test_join_is_case_insensitive() -> None:
    circles, channels = FakeCircleRepository(), FakePttChannelWriter()
    owner, guest = make_user(), make_user(email="bia@example.com")
    service = build_service(circles, channels)
    created = await service.create(name="Família", owner_id=owner.id)

    joined = await service.join(invite_code=created.invite_code.lower(), user_id=guest.id)

    assert joined.id == created.id


async def test_join_with_unknown_code_is_404() -> None:
    service = build_service(FakeCircleRepository(), FakePttChannelWriter())

    with pytest.raises(NotFoundError):
        await service.join(invite_code="ZZZZ9999", user_id=make_user().id)


async def test_join_twice_is_conflict() -> None:
    circles, channels = FakeCircleRepository(), FakePttChannelWriter()
    owner, guest = make_user(), make_user(email="bia@example.com")
    service = build_service(circles, channels)
    created = await service.create(name="Família", owner_id=owner.id)
    await service.join(invite_code=created.invite_code, user_id=guest.id)

    with pytest.raises(ConflictError) as excinfo:
        await service.join(invite_code=created.invite_code, user_id=guest.id)

    assert excinfo.value.code == "ALREADY_MEMBER"


# --------------------------------------------------------------------------- leitura
async def test_list_members_returns_last_position() -> None:
    circles, channels = FakeCircleRepository(), FakePttChannelWriter()
    owner = make_user(display_name="Ana")
    circles.seed_user(owner)
    service = build_service(circles, channels)
    created = await service.create(name="Família", owner_id=owner.id)

    members = await service.list_members(circle_id=created.id, requester_id=owner.id)
    assert [member.user_id for member in members] == [owner.id]
    assert members[0].display_name == "Ana"


async def test_list_members_of_foreign_circle_is_404() -> None:
    """Nunca 403: confirmar existência do círculo já seria vazamento."""
    circles, channels = FakeCircleRepository(), FakePttChannelWriter()
    owner = make_user()
    circles.seed_circle(make_circle(owner_id=owner.id))
    service = build_service(circles, channels)

    with pytest.raises(NotFoundError):
        await service.list_members(
            circle_id=next(iter(circles.circles)), requester_id=make_user().id
        )


async def test_list_members_of_missing_circle_is_404() -> None:
    service = build_service(FakeCircleRepository(), FakePttChannelWriter())

    with pytest.raises(NotFoundError):
        await service.list_members(circle_id=make_user().id, requester_id=make_user().id)


# --------------------------------------------------------------------------- remoção
async def test_member_can_leave_the_circle() -> None:
    circles, channels = FakeCircleRepository(), FakePttChannelWriter()
    owner, guest = make_user(), make_user(email="bia@example.com")
    service = build_service(circles, channels)
    created = await service.create(name="Família", owner_id=owner.id)
    await service.join(invite_code=created.invite_code, user_id=guest.id)

    await service.remove_member(circle_id=created.id, requester_id=guest.id, target_id=guest.id)

    assert await circles.get_member(created.id, guest.id) is None
    channel = next(iter(channels.channels.values()))
    assert (channel.id, guest.id) not in channels.memberships


async def test_plain_member_cannot_remove_another_member() -> None:
    circles, channels = FakeCircleRepository(), FakePttChannelWriter()
    owner, guest, other = (
        make_user(),
        make_user(email="bia@example.com"),
        make_user(email="caio@example.com"),
    )
    service = build_service(circles, channels)
    created = await service.create(name="Família", owner_id=owner.id)
    await service.join(invite_code=created.invite_code, user_id=guest.id)
    await service.join(invite_code=created.invite_code, user_id=other.id)

    with pytest.raises(ForbiddenError) as excinfo:
        await service.remove_member(circle_id=created.id, requester_id=guest.id, target_id=other.id)

    assert excinfo.value.status_code == 403
    assert await circles.get_member(created.id, other.id) is not None


async def test_admin_can_remove_a_member() -> None:
    circles, channels = FakeCircleRepository(), FakePttChannelWriter()
    owner, admin, guest = (
        make_user(),
        make_user(email="admin@example.com"),
        make_user(email="bia@example.com"),
    )
    service = build_service(circles, channels)
    created = await service.create(name="Família", owner_id=owner.id)
    circles.seed_member(created.id, admin, CircleRole.ADMIN)
    await service.join(invite_code=created.invite_code, user_id=guest.id)

    await service.remove_member(circle_id=created.id, requester_id=admin.id, target_id=guest.id)

    assert await circles.get_member(created.id, guest.id) is None


async def test_owner_cannot_be_removed() -> None:
    circles, channels = FakeCircleRepository(), FakePttChannelWriter()
    owner, admin = make_user(), make_user(email="admin@example.com")
    service = build_service(circles, channels)
    created = await service.create(name="Família", owner_id=owner.id)
    circles.seed_member(created.id, admin, CircleRole.ADMIN)

    with pytest.raises(BadRequestError) as excinfo:
        await service.remove_member(circle_id=created.id, requester_id=admin.id, target_id=owner.id)

    assert excinfo.value.code == "CANNOT_REMOVE_OWNER"


async def test_remover_must_be_a_member() -> None:
    circles, channels = FakeCircleRepository(), FakePttChannelWriter()
    owner = make_user()
    service = build_service(circles, channels)
    created = await service.create(name="Família", owner_id=owner.id)

    with pytest.raises(NotFoundError):
        await service.remove_member(
            circle_id=created.id, requester_id=make_user().id, target_id=owner.id
        )


async def test_remove_unknown_member_is_404() -> None:
    circles, channels = FakeCircleRepository(), FakePttChannelWriter()
    owner = make_user()
    service = build_service(circles, channels)
    created = await service.create(name="Família", owner_id=owner.id)

    with pytest.raises(NotFoundError):
        await service.remove_member(
            circle_id=created.id, requester_id=owner.id, target_id=make_user().id
        )


async def test_remove_from_missing_circle_is_404() -> None:
    service = build_service(FakeCircleRepository(), FakePttChannelWriter())

    with pytest.raises(NotFoundError):
        await service.remove_member(
            circle_id=make_user().id, requester_id=make_user().id, target_id=make_user().id
        )


# --------------------------------------------------------------------------- listagem
async def test_list_for_user_returns_role_and_count() -> None:
    circles, channels = FakeCircleRepository(), FakePttChannelWriter()
    owner, guest = make_user(), make_user(email="bia@example.com")
    service = build_service(circles, channels)
    created = await service.create(name="Família", owner_id=owner.id)
    await service.join(invite_code=created.invite_code, user_id=guest.id)

    owner_circles = await service.list_for_user(owner.id)
    guest_circles = await service.list_for_user(guest.id)

    assert [circle.role for circle in owner_circles] == [CircleRole.OWNER]
    assert [circle.role for circle in guest_circles] == [CircleRole.MEMBER]
    assert guest_circles[0].member_count == 2


async def test_list_for_user_is_empty_without_membership() -> None:
    service = build_service(FakeCircleRepository(), FakePttChannelWriter())
    assert await service.list_for_user(make_user().id) == []
