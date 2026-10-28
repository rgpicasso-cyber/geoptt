"""Testes de segurança: hash de senha, JWT e redação de logs."""

from __future__ import annotations

import logging
from datetime import timedelta
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.core.logging import RedactionFilter, redact
from app.core.security import (
    BCRYPT_MAX_PASSWORD_BYTES,
    TokenError,
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_opaque_token,
    hash_password,
    hash_token,
    verify_password,
)


# --------------------------------------------------------------------------- senha
def test_password_roundtrip() -> None:
    password = "S3nh@-forte-com-acentuação"
    hashed = hash_password(password)

    assert hashed != password
    assert hashed.startswith("$2")
    assert verify_password(password, hashed) is True
    assert verify_password("senha-errada", hashed) is False


def test_password_hash_is_salted() -> None:
    password = "mesma-senha"
    assert hash_password(password) != hash_password(password)


def test_password_rejects_more_than_72_bytes() -> None:
    too_long = "a" * (BCRYPT_MAX_PASSWORD_BYTES + 1)
    with pytest.raises(ValueError, match="72"):
        hash_password(too_long)


def test_password_at_exact_limit_is_accepted() -> None:
    assert verify_password(
        "a" * BCRYPT_MAX_PASSWORD_BYTES,
        hash_password("a" * BCRYPT_MAX_PASSWORD_BYTES),
    )


def test_verify_password_with_corrupt_hash_returns_false() -> None:
    assert verify_password("qualquer", "nao-e-um-hash-bcrypt") is False


# --------------------------------------------------------------------------- token hash
def test_hash_token_is_sha256_hex() -> None:
    digest = hash_token("token-em-claro")
    assert len(digest) == 64
    assert digest == hash_token("token-em-claro")
    assert digest != hash_token("outro-token")
    assert all(char in "0123456789abcdef" for char in digest)


def test_generate_opaque_token_is_urlsafe_and_unique() -> None:
    first, second = generate_opaque_token(), generate_opaque_token()
    assert first != second
    assert len(first) >= 40
    assert "+" not in first and "/" not in first


# --------------------------------------------------------------------------- JWT
def test_access_token_roundtrip(settings: Settings) -> None:
    user_id = uuid4()
    token = create_access_token(subject=user_id, settings=settings)

    claims = decode_token(token, settings=settings, expected_type=TokenType.ACCESS)

    assert claims["user_id"] == user_id
    assert claims["sub"] == str(user_id)
    assert claims["typ"] == TokenType.ACCESS.value
    assert claims["iss"] == settings.jwt_issuer
    assert claims["aud"] == settings.jwt_audience
    assert "jti" in claims


def test_refresh_token_has_different_type(settings: Settings) -> None:
    token = create_refresh_token(subject=uuid4(), settings=settings)
    claims = decode_token(token, settings=settings, expected_type=TokenType.REFRESH)
    assert claims["typ"] == TokenType.REFRESH.value


def test_access_token_rejected_when_refresh_expected(settings: Settings) -> None:
    token = create_access_token(subject=uuid4(), settings=settings)
    with pytest.raises(TokenError, match="tipo de token"):
        decode_token(token, settings=settings, expected_type=TokenType.REFRESH)


def test_expired_token_is_rejected(settings: Settings) -> None:
    token = create_access_token(subject=uuid4(), settings=settings, extra_claims=None)
    # Recria com TTL negativo para simular expiração.
    from app.core.security import create_token

    expired = create_token(
        subject=uuid4(),
        token_type=TokenType.ACCESS,
        settings=settings,
        ttl=timedelta(seconds=-10),
    )
    assert token  # sanity

    with pytest.raises(TokenError, match="expirado"):
        decode_token(expired, settings=settings)


def test_tampered_token_is_rejected(settings: Settings) -> None:
    token = create_access_token(subject=uuid4(), settings=settings)
    header, payload, signature = token.split(".")
    tampered = f"{header}.{payload}.{signature[:-4]}AAAA"

    with pytest.raises(TokenError):
        decode_token(tampered, settings=settings)


def test_token_signed_with_other_secret_is_rejected(settings: Settings, settings_factory) -> None:
    other = settings_factory(jwt_secret="outro-segredo-com-32-caracteres-ou-mais-ok")
    token = create_access_token(subject=uuid4(), settings=other)

    with pytest.raises(TokenError):
        decode_token(token, settings=settings)


def test_token_with_wrong_audience_is_rejected(settings: Settings, settings_factory) -> None:
    other = settings_factory(jwt_audience="outro-app")
    token = create_access_token(subject=uuid4(), settings=other)

    with pytest.raises(TokenError):
        decode_token(token, settings=settings)


def test_empty_token_is_rejected(settings: Settings) -> None:
    with pytest.raises(TokenError, match="vazio"):
        decode_token("   ", settings=settings)


def test_token_with_non_uuid_subject_is_rejected(settings: Settings, settings_factory) -> None:
    from app.core.security import create_token

    token = create_token(
        subject="nao-e-uuid",
        token_type=TokenType.ACCESS,
        settings=settings,
    )
    with pytest.raises(TokenError, match="UUID"):
        decode_token(token, settings=settings)


# --------------------------------------------------------------------------- redação
@pytest.mark.parametrize(
    "raw, secret",
    [
        ("token=abc123", "abc123"),
        ("Authorization: Bearer xyz", "xyz"),
        ("password=hunter2", "hunter2"),
        ("fcm_token: muito-secreto", "muito-secreto"),
    ],
)
def test_redact_removes_secrets(raw: str, secret: str) -> None:
    assert secret not in redact(raw)


def test_redact_masks_jwt() -> None:
    jwt_like = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3OCJ9.abcdefghijklmnop"
    assert jwt_like not in redact(f"falhou com {jwt_like}")


def test_redact_masks_precise_coordinates() -> None:
    assert "-23.55052" not in redact("posição -23.55052, -46.63331")
    assert "-23.5505" in redact("posição -23.5505")  # 4 casas: preservado


def test_redact_keeps_harmless_text() -> None:
    assert redact("usuário conectado ao canal") == "usuário conectado ao canal"


def test_redaction_filter_mutates_record() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="token=%s",
        args=("super-secreto",),
        exc_info=None,
    )
    assert RedactionFilter().filter(record) is True
    assert "super-secreto" not in record.getMessage()


# --------------------------------------------------------------------------- Settings
def test_production_rejects_dev_jwt_secret(settings_factory) -> None:
    with pytest.raises(ValueError, match="JWT_SECRET"):
        settings_factory(
            env="production", jwt_secret="dev-insecure-secret-do-not-use-in-production-32chars"
        )


def test_production_rejects_debug(settings_factory) -> None:
    with pytest.raises(ValueError, match="DEBUG"):
        settings_factory(env="production", debug=True)


def test_production_requires_fcm_credentials(settings_factory) -> None:
    with pytest.raises(ValueError, match="FCM_CREDENTIALS_PATH"):
        settings_factory(env="production", fcm_enabled=True, fcm_credentials_path=None)


def test_production_accepts_hardened_config(settings_factory) -> None:
    settings = settings_factory(
        env="production",
        debug=False,
        fcm_enabled=True,
        fcm_credentials_path="/opt/geoptt/secrets/serviceAccountKey.json",
    )
    assert settings.is_production is True


def test_short_jwt_secret_is_rejected(settings_factory) -> None:
    with pytest.raises(ValueError, match="32"):
        settings_factory(jwt_secret="curto")


@pytest.mark.parametrize(
    "given, expected_prefix",
    [
        ("postgres://u:p@h:5432/db", "postgresql+asyncpg://"),
        ("postgresql://u:p@h:5432/db", "postgresql+asyncpg://"),
        ("postgresql+asyncpg://u:p@h:5432/db", "postgresql+asyncpg://"),
    ],
)
def test_database_url_is_normalized(settings_factory, given: str, expected_prefix: str) -> None:
    settings = settings_factory(database_url=given)
    assert settings.database_url.startswith(expected_prefix)


def test_masked_database_url_hides_credentials(settings_factory) -> None:
    settings = settings_factory(database_url="postgresql+asyncpg://user:senha@db:5432/geoptt")
    masked = settings.masked_database_url
    assert "senha" not in masked
    assert "user" not in masked
    assert "db:5432" in masked


def test_cors_origins_parsing(settings_factory) -> None:
    settings = settings_factory(cors_origins="https://a.com, https://b.com ,")
    assert settings.cors_origin_list == ("https://a.com", "https://b.com")


def test_jwt_secret_never_leaks_in_repr(settings_factory) -> None:
    settings = settings_factory()
    assert "test-secret-key" not in repr(settings)
