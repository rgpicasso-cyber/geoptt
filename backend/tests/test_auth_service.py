"""Testes de `AuthService` — registro, login, rotação e revogação de tokens."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.core.errors import ConflictError, UnauthorizedError, UnprocessableError
from app.core.security import TokenType, create_token, hash_password, hash_token
from app.services.auth_service import AuthService
from tests.fakes import FakeTokenRepository, FakeUserRepository, make_user

PASSWORD = "Senha-forte-123"
DEVICE = "device-abc"


def build_service(
    settings: Settings, users: FakeUserRepository, tokens: FakeTokenRepository
) -> AuthService:
    return AuthService(users=users, tokens=tokens, settings=settings)


# --------------------------------------------------------------------------- registro
async def test_register_creates_user_and_issues_tokens(settings: Settings) -> None:
    users, tokens = FakeUserRepository(), FakeTokenRepository()
    service = build_service(settings, users, tokens)

    issued = await service.register(
        email="Ana@Example.com",
        password=PASSWORD,
        display_name="Ana",
        device_id=DEVICE,
    )

    assert issued.access_token and issued.refresh_token
    assert issued.expires_in == settings.access_token_ttl_minutes * 60

    stored = await users.get_by_email("ana@example.com")
    assert stored is not None
    assert stored.email == "ana@example.com"  # normalizado
    assert stored.password_hash.startswith("$argon2id$")

    # O banco guarda apenas o SHA-256 do refresh token.
    assert await tokens.get_by_hash(hash_token(issued.refresh_token)) is not None
    assert await tokens.get_by_hash(issued.refresh_token) is None


async def test_register_rejects_duplicate_email(settings: Settings) -> None:
    users, tokens = FakeUserRepository(), FakeTokenRepository()
    users.seed(make_user(email="ana@example.com"))
    service = build_service(settings, users, tokens)

    with pytest.raises(ConflictError) as excinfo:
        await service.register(
            email="ANA@example.com", password=PASSWORD, display_name="Ana", device_id=DEVICE
        )

    assert excinfo.value.code == "EMAIL_TAKEN"
    assert excinfo.value.status_code == 409


@pytest.mark.parametrize("weak", ["curta1", "semnumero", "12345678"])
async def test_register_rejects_weak_password(settings: Settings, weak: str) -> None:
    service = build_service(settings, FakeUserRepository(), FakeTokenRepository())

    with pytest.raises(UnprocessableError):
        await service.register(
            email="ana@example.com", password=weak, display_name="Ana", device_id=DEVICE
        )


# --------------------------------------------------------------------------- login
async def test_login_succeeds_with_correct_password(settings: Settings) -> None:
    users, tokens = FakeUserRepository(), FakeTokenRepository()
    user = users.seed(make_user(email="ana@example.com", password_hash=hash_password(PASSWORD)))
    service = build_service(settings, users, tokens)

    issued = await service.login(email="ANA@example.com", password=PASSWORD, device_id=DEVICE)

    assert issued.access_token
    assert len(tokens.active_for(user.id)) == 1


async def test_login_rejects_wrong_password(settings: Settings) -> None:
    users = FakeUserRepository()
    users.seed(make_user(email="ana@example.com", password_hash=hash_password(PASSWORD)))
    service = build_service(settings, users, FakeTokenRepository())

    with pytest.raises(UnauthorizedError):
        await service.login(email="ana@example.com", password="errada-123", device_id=DEVICE)


async def test_login_of_unknown_email_is_indistinguishable(settings: Settings) -> None:
    """Mesmo status e mesma mensagem — evita enumeração de contas."""
    service = build_service(settings, FakeUserRepository(), FakeTokenRepository())

    with pytest.raises(UnauthorizedError) as excinfo:
        await service.login(email="ninguem@example.com", password=PASSWORD, device_id=DEVICE)

    assert excinfo.value.message == "credenciais inválidas"


# --------------------------------------------------------------------------- refresh
async def test_refresh_rotates_token(settings: Settings) -> None:
    users, tokens = FakeUserRepository(), FakeTokenRepository()
    user = users.seed(make_user(email="ana@example.com", password_hash=hash_password(PASSWORD)))
    service = build_service(settings, users, tokens)

    first = await service.login(email="ana@example.com", password=PASSWORD, device_id=DEVICE)
    second = await service.refresh(refresh_token=first.refresh_token, device_id=DEVICE)

    assert second.refresh_token != first.refresh_token
    # O token usado foi revogado; o novo está ativo.
    old = await tokens.get_by_hash(hash_token(first.refresh_token))
    assert old is not None and old.revoked_at is not None
    assert len(tokens.active_for(user.id)) == 1


async def test_refresh_reuse_revokes_every_session(settings: Settings) -> None:
    """Cenário de roubo de token: reutilizar um refresh já rotacionado derruba tudo."""
    users, tokens = FakeUserRepository(), FakeTokenRepository()
    user = users.seed(make_user(email="ana@example.com", password_hash=hash_password(PASSWORD)))
    service = build_service(settings, users, tokens)

    first = await service.login(email="ana@example.com", password=PASSWORD, device_id=DEVICE)
    await service.login(email="ana@example.com", password=PASSWORD, device_id="outro-device")
    await service.refresh(refresh_token=first.refresh_token, device_id=DEVICE)

    # Sess?o do outro device + o token rec?m-rotacionado (o antigo morreu).
    assert len(tokens.active_for(user.id)) == 2

    with pytest.raises(UnauthorizedError) as excinfo:
        await service.refresh(refresh_token=first.refresh_token, device_id=DEVICE)

    assert excinfo.value.code == "TOKEN_REUSED"
    assert tokens.active_for(user.id) == []


async def test_refresh_from_other_device_revokes_only_that_token(settings: Settings) -> None:
    users, tokens = FakeUserRepository(), FakeTokenRepository()
    user = users.seed(make_user(email="ana@example.com", password_hash=hash_password(PASSWORD)))
    service = build_service(settings, users, tokens)

    first = await service.login(email="ana@example.com", password=PASSWORD, device_id=DEVICE)
    other = await service.login(email="ana@example.com", password=PASSWORD, device_id="tablet")

    with pytest.raises(UnauthorizedError):
        await service.refresh(refresh_token=first.refresh_token, device_id="tablet")

    # A sessão do tablet continua válida; só o token usado foi revogado.
    active = tokens.active_for(user.id)
    assert [token.token_hash for token in active] == [hash_token(other.refresh_token)]


async def test_refresh_of_expired_token_is_rejected(settings: Settings) -> None:
    users, tokens = FakeUserRepository(), FakeTokenRepository()
    user = users.seed(make_user(email="ana@example.com", password_hash=hash_password(PASSWORD)))
    service = build_service(settings, users, tokens)

    # JWT ainda v?lido, mas a linha no banco j? venceu: cobre o caminho de
    # expira??o *de sess?o* (o de JWT expirado ? outro teste).
    stale_raw = create_token(subject=user.id, token_type=TokenType.REFRESH, settings=settings)
    await tokens.create(
        user_id=user.id,
        token_hash=hash_token(stale_raw),
        device_id=DEVICE,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    with pytest.raises(UnauthorizedError) as excinfo:
        await service.refresh(refresh_token=stale_raw, device_id=DEVICE)

    assert excinfo.value.code == "TOKEN_EXPIRED"


async def test_refresh_with_garbage_token_is_rejected(settings: Settings) -> None:
    service = build_service(settings, FakeUserRepository(), FakeTokenRepository())

    with pytest.raises(UnauthorizedError):
        await service.refresh(refresh_token="nao-e-um-jwt-valido", device_id=DEVICE)


async def test_refresh_of_unknown_but_valid_token_is_rejected(settings: Settings) -> None:
    users = FakeUserRepository()
    user = users.seed(make_user())
    service = build_service(settings, users, FakeTokenRepository())

    orphan = create_token(subject=user.id, token_type=TokenType.REFRESH, settings=settings)

    with pytest.raises(UnauthorizedError):
        await service.refresh(refresh_token=orphan, device_id=DEVICE)


async def test_refresh_token_from_another_user_revokes_sessions(settings: Settings) -> None:
    """Token válido cujo `sub` não bate com o dono no banco: possível forja."""
    users, tokens = FakeUserRepository(), FakeTokenRepository()
    owner = users.seed(make_user(email="ana@example.com", password_hash=hash_password(PASSWORD)))
    intruder_id = uuid4()
    service = build_service(settings, users, tokens)

    issued = await service.login(email="ana@example.com", password=PASSWORD, device_id=DEVICE)
    forged = create_token(subject=intruder_id, token_type=TokenType.REFRESH, settings=settings)
    await tokens.create(
        user_id=owner.id,
        token_hash=hash_token(forged),
        device_id=DEVICE,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )

    with pytest.raises(UnauthorizedError):
        await service.refresh(refresh_token=forged, device_id=DEVICE)

    # O dono do registro perde todas as sessões — inclusive a legítima.
    assert await tokens.get_by_hash(hash_token(issued.refresh_token)) is not None
    assert tokens.active_for(owner.id) == []


# --------------------------------------------------------------------------- logout
async def test_logout_revokes_only_the_device(settings: Settings) -> None:
    users, tokens = FakeUserRepository(), FakeTokenRepository()
    user = users.seed(make_user(email="ana@example.com", password_hash=hash_password(PASSWORD)))
    service = build_service(settings, users, tokens)

    await service.login(email="ana@example.com", password=PASSWORD, device_id=DEVICE)
    await service.login(email="ana@example.com", password=PASSWORD, device_id="tablet")

    revoked = await service.logout(user_id=user.id, device_id=DEVICE)

    assert revoked == 1
    assert len(tokens.active_for(user.id)) == 1


async def test_logout_without_device_revokes_all(settings: Settings) -> None:
    users, tokens = FakeUserRepository(), FakeTokenRepository()
    user = users.seed(make_user(email="ana@example.com", password_hash=hash_password(PASSWORD)))
    service = build_service(settings, users, tokens)

    await service.login(email="ana@example.com", password=PASSWORD, device_id=DEVICE)
    await service.login(email="ana@example.com", password=PASSWORD, device_id="tablet")

    revoked = await service.logout(user_id=user.id, device_id=None)

    assert revoked == 2
    assert tokens.active_for(user.id) == []
