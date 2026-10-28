"""Implementações em memória dos Protocols de `app.repositories.protocols`.

Por que existem: as tabelas geoespaciais usam `GEOGRAPHY(POINT,4326)` e não
rodam em SQLite. Para testar as regras de negócio sem PostgreSQL, injetamos
estes dublês — que satisfazem as interfaces por tipagem estrutural.

Regra de transação preservada: nenhum fake faz commit; apenas registra o que
recebeu, para que o teste possa inspecionar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.models.circle import Circle, CircleMember
from app.models.enums import CircleRole, Platform
from app.models.ptt import PttChannel
from app.models.token import RefreshToken
from app.models.user import User
from app.repositories.protocols import (
    CircleSummary,
    LocationPointInput,
    MemberView,
    PositionView,
)


def make_user(
    *,
    user_id: UUID | None = None,
    email: str = "user@example.com",
    display_name: str = "Usuário",
    password_hash: str = "$argon2id$fake",  # noqa: S107 - hash descart?vel de teste
) -> User:
    """Cria um `User` destacado da sessão, com `id`/`created_at` já preenchidos."""
    now = datetime.now(UTC)
    user = User(
        id=user_id or uuid4(),
        email=email,
        password_hash=password_hash,
        display_name=display_name,
    )
    user.created_at = now
    user.updated_at = now
    user.is_sharing_location = True
    return user


def make_circle(
    *,
    owner_id: UUID,
    name: str = "Família",
    invite_code: str = "ABCD2345",
    circle_id: UUID | None = None,
) -> Circle:
    now = datetime.now(UTC)
    circle = Circle(
        id=circle_id or uuid4(),
        name=name,
        owner_id=owner_id,
        invite_code=invite_code,
    )
    circle.created_at = now
    circle.updated_at = now
    return circle


# --------------------------------------------------------------------------- users
@dataclass
class FakeUserRepository:
    users: dict[UUID, User] = field(default_factory=dict)

    def seed(self, user: User) -> User:
        self.users[user.id] = user
        return user

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self.users.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        target = email.strip().lower()
        return next((u for u in self.users.values() if u.email.lower() == target), None)

    async def create(self, *, email: str, password_hash: str, display_name: str) -> User:
        user = make_user(
            email=email.strip().lower(),
            password_hash=password_hash,
            display_name=display_name.strip(),
        )
        return self.seed(user)

    async def update_profile(
        self,
        user_id: UUID,
        *,
        display_name: str | None = None,
        is_sharing_location: bool | None = None,
    ) -> User | None:
        user = self.users.get(user_id)
        if user is None:
            return None
        if display_name is not None:
            user.display_name = display_name.strip()
        if is_sharing_location is not None:
            user.is_sharing_location = is_sharing_location
        return user

    async def update_password_hash(self, user_id: UUID, password_hash: str) -> None:
        user = self.users.get(user_id)
        if user is not None:
            user.password_hash = password_hash

    async def set_fcm_token(
        self, user_id: UUID, *, fcm_token: str, platform: Platform
    ) -> User | None:
        user = self.users.get(user_id)
        if user is None:
            return None
        user.fcm_token = fcm_token
        user.platform = platform
        return user

    async def clear_fcm_token(self, user_id: UUID) -> bool:
        user = self.users.get(user_id)
        if user is None or user.fcm_token is None:
            return False
        user.fcm_token = None
        user.platform = None
        return True

    async def clear_fcm_token_by_value(self, fcm_token: str) -> bool:
        for user in self.users.values():
            if user.fcm_token == fcm_token:
                user.fcm_token = None
                user.platform = None
                return True
        return False

    async def touch_presence(
        self, user_id: UUID, *, battery_level: int | None, seen_at: datetime
    ) -> None:
        user = self.users.get(user_id)
        if user is None:
            return
        user.last_seen_at = seen_at
        if battery_level is not None:
            user.battery_level = battery_level


# --------------------------------------------------------------------------- tokens
@dataclass
class FakeTokenRepository:
    tokens: dict[str, RefreshToken] = field(default_factory=dict)

    async def create(
        self,
        *,
        user_id: UUID,
        token_hash: str,
        device_id: str,
        expires_at: datetime,
    ) -> RefreshToken:
        token = RefreshToken(
            id=uuid4(),
            user_id=user_id,
            token_hash=token_hash,
            device_id=device_id,
            expires_at=expires_at,
        )
        token.created_at = datetime.now(UTC)
        token.revoked_at = None
        self.tokens[token_hash] = token
        return token

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        return self.tokens.get(token_hash)

    async def revoke(self, token_id: UUID, *, revoked_at: datetime) -> None:
        for token in self.tokens.values():
            if token.id == token_id and token.revoked_at is None:
                token.revoked_at = revoked_at

    async def revoke_device(self, user_id: UUID, device_id: str, *, revoked_at: datetime) -> int:
        count = 0
        for token in self.tokens.values():
            if (
                token.user_id == user_id
                and token.device_id == device_id
                and token.revoked_at is None
            ):
                token.revoked_at = revoked_at
                count += 1
        return count

    async def revoke_all(self, user_id: UUID, *, revoked_at: datetime) -> int:
        count = 0
        for token in self.tokens.values():
            if token.user_id == user_id and token.revoked_at is None:
                token.revoked_at = revoked_at
                count += 1
        return count

    # ------------------------------------------------------------------ auxiliares
    def active_for(self, user_id: UUID) -> list[RefreshToken]:
        return [
            token
            for token in self.tokens.values()
            if token.user_id == user_id and token.revoked_at is None
        ]


# --------------------------------------------------------------------------- círculos
@dataclass
class FakeCircleRepository:
    circles: dict[UUID, Circle] = field(default_factory=dict)
    members: dict[tuple[UUID, UUID], CircleMember] = field(default_factory=dict)
    users: dict[UUID, User] = field(default_factory=dict)
    positions: dict[UUID, PositionView] = field(default_factory=dict)

    # ------------------------------------------------------------------ seed
    def seed_circle(self, circle: Circle) -> Circle:
        self.circles[circle.id] = circle
        return circle

    def seed_member(self, circle_id: UUID, user: User, role: CircleRole) -> CircleMember:
        self.users[user.id] = user
        member = CircleMember(circle_id=circle_id, user_id=user.id, role=role)
        member.joined_at = datetime.now(UTC)
        self.members[(circle_id, user.id)] = member
        return member

    def seed_position(self, position: PositionView) -> None:
        self.positions[position.user_id] = position

    def seed_user(self, user: User) -> None:
        """Registra o `User` para que `list_members` resolva o `display_name`."""
        self.users[user.id] = user

    # ------------------------------------------------------------------ círculo
    async def create(self, *, name: str, owner_id: UUID, invite_code: str) -> Circle:
        circle = make_circle(owner_id=owner_id, name=name, invite_code=invite_code)
        return self.seed_circle(circle)

    async def get_by_id(self, circle_id: UUID) -> Circle | None:
        return self.circles.get(circle_id)

    async def get_by_invite_code(self, invite_code: str) -> Circle | None:
        target = invite_code.strip().upper()
        return next((c for c in self.circles.values() if c.invite_code == target), None)

    async def invite_code_exists(self, invite_code: str) -> bool:
        return await self.get_by_invite_code(invite_code) is not None

    async def touch_circle(self, circle_id: UUID, *, at: datetime) -> None:
        circle = self.circles.get(circle_id)
        if circle is not None:
            circle.updated_at = at

    # ------------------------------------------------------------------ membros
    async def get_member(self, circle_id: UUID, user_id: UUID) -> CircleMember | None:
        return self.members.get((circle_id, user_id))

    async def add_member(self, *, circle_id: UUID, user_id: UUID, role: CircleRole) -> CircleMember:
        member = CircleMember(circle_id=circle_id, user_id=user_id, role=role)
        member.joined_at = datetime.now(UTC)
        self.members[(circle_id, user_id)] = member
        return member

    async def remove_member(self, circle_id: UUID, user_id: UUID) -> bool:
        return self.members.pop((circle_id, user_id), None) is not None

    async def list_member_ids(self, circle_id: UUID) -> list[UUID]:
        return [user_id for (cid, user_id) in self.members if cid == circle_id]

    async def list_broadcast_recipients(self, user_id: UUID) -> list[UUID]:
        own_circles = {cid for (cid, uid) in self.members if uid == user_id}
        peers = {uid for (cid, uid) in self.members if cid in own_circles and uid != user_id}
        return sorted(peers, key=str)

    # ------------------------------------------------------------------ listagens
    async def list_for_user(self, user_id: UUID) -> list[CircleSummary]:
        summaries: list[CircleSummary] = []
        for (circle_id, member_id), member in self.members.items():
            if member_id != user_id:
                continue
            circle = self.circles.get(circle_id)
            if circle is None:
                continue
            total = len(await self.list_member_ids(circle_id))
            summaries.append(
                CircleSummary(
                    id=circle.id,
                    name=circle.name,
                    owner_id=circle.owner_id,
                    invite_code=circle.invite_code,
                    role=member.role,
                    member_count=total,
                    created_at=circle.created_at,
                )
            )
        return sorted(summaries, key=lambda item: item.created_at)

    async def list_members(self, circle_id: UUID) -> list[MemberView]:
        views: list[MemberView] = []
        for (cid, user_id), member in self.members.items():
            if cid != circle_id:
                continue
            user = self.users.get(user_id)
            position = self.positions.get(user_id)
            views.append(
                MemberView(
                    user_id=user_id,
                    display_name=user.display_name if user else str(user_id),
                    role=member.role,
                    battery_level=user.battery_level if user else None,
                    is_sharing_location=user.is_sharing_location if user else True,
                    last_seen_at=user.last_seen_at if user else None,
                    lat=position.lat if position else None,
                    lng=position.lng if position else None,
                    accuracy_m=position.accuracy_m if position else None,
                    speed_mps=position.speed_mps if position else None,
                    heading_deg=position.heading_deg if position else None,
                    recorded_at=position.recorded_at if position else None,
                )
            )
        return sorted(views, key=lambda item: (item.role, item.display_name))


# --------------------------------------------------------------------------- localização
@dataclass
class FakeLocationRepository:
    history: dict[tuple[UUID, int], LocationPointInput] = field(default_factory=dict)
    current: dict[UUID, LocationPointInput] = field(default_factory=dict)
    positions: dict[UUID, list[PositionView]] = field(default_factory=dict)

    def seed_positions(self, circle_id: UUID, positions: list[PositionView]) -> None:
        self.positions[circle_id] = positions

    async def upsert_current(self, *, user_id: UUID, point: LocationPointInput) -> None:
        self.current[user_id] = point

    async def insert_history(self, *, user_id: UUID, points: list[LocationPointInput]) -> int:
        inserted = 0
        for point in points:
            key = (user_id, point.client_seq)
            if key in self.history:
                continue
            self.history[key] = point
            inserted += 1
        return inserted

    async def list_circle_positions(self, circle_id: UUID) -> list[PositionView]:
        return list(self.positions.get(circle_id, []))


# --------------------------------------------------------------------------- PTT (escrita)
@dataclass
class FakePttChannelWriter:
    channels: dict[UUID, PttChannel] = field(default_factory=dict)
    memberships: set[tuple[UUID, UUID]] = field(default_factory=set)

    async def create_channel(self, *, circle_id: UUID, name: str, created_by: UUID) -> PttChannel:
        existing = next(
            (c for c in self.channels.values() if c.circle_id == circle_id and c.name == name),
            None,
        )
        if existing is not None:
            return existing
        channel = PttChannel(id=uuid4(), circle_id=circle_id, name=name, created_by=created_by)
        channel.is_active = True
        channel.created_at = datetime.now(UTC)
        self.channels[channel.id] = channel
        return channel

    async def add_member(self, *, channel_id: UUID, user_id: UUID, can_speak: bool = True) -> None:
        self.memberships.add((channel_id, user_id))

    async def add_member_to_circle_channels(self, circle_id: UUID, user_id: UUID) -> int:
        added = 0
        for channel in self.channels.values():
            if (
                channel.circle_id == circle_id
                and channel.is_active
                and (channel.id, user_id) not in self.memberships
            ):
                self.memberships.add((channel.id, user_id))
                added += 1
        return added

    async def remove_member_from_circle_channels(self, circle_id: UUID, user_id: UUID) -> int:
        channel_ids = {c.id for c in self.channels.values() if c.circle_id == circle_id}
        removed = [key for key in self.memberships if key[1] == user_id and key[0] in channel_ids]
        for key in removed:
            self.memberships.discard(key)
        return len(removed)
