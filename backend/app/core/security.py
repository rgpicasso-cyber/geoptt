"""Primitivas de segurança: hash de senha (Argon2id) e tokens JWT.

Decisão de algoritmo: **ADR-006** (`docs/adr/ADR-006-pwdlib-argon2id.md`).
`passlib` foi removido por estar sem manutenção e quebrar com `bcrypt` 5.x.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Final
from uuid import UUID, uuid4

import jwt
from pwdlib import PasswordHash
from pwdlib.exceptions import PwdlibError

from app.core.config import Settings

# Limite de POLÍTICA (não do algoritmo): evita DoS de hashing com senhas enormes.
MAX_PASSWORD_BYTES: Final = 128
MIN_PASSWORD_LENGTH: Final = 8

# Argon2id com os parâmetros recomendados pela biblioteca.
_password_hash = PasswordHash.recommended()


class TokenType(StrEnum):
    """Tipo do token, gravado na claim `typ`."""

    ACCESS = "access"
    REFRESH = "refresh"


class TokenError(Exception):
    """Token ausente, malformado, expirado ou de tipo inesperado."""


def validate_password_policy(password: str) -> None:
    """Aplica a política de senha. Levanta `ValueError` com mensagem acionável.

    Regras: 8 a 128 bytes, ao menos uma letra e um dígito.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        msg = f"Senha deve ter ao menos {MIN_PASSWORD_LENGTH} caracteres."
        raise ValueError(msg)
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        msg = f"Senha excede {MAX_PASSWORD_BYTES} bytes."
        raise ValueError(msg)
    if not any(char.isalpha() for char in password):
        msg = "Senha deve conter ao menos uma letra."
        raise ValueError(msg)
    if not any(char.isdigit() for char in password):
        msg = "Senha deve conter ao menos um dígito."
        raise ValueError(msg)


def hash_password(password: str) -> str:
    """Gera o hash Argon2id da senha."""
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        msg = f"Senha excede {MAX_PASSWORD_BYTES} bytes."
        raise ValueError(msg)
    return _password_hash.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Compara senha e hash. Nunca levanta por hash inválido ou corrompido."""
    try:
        return _password_hash.verify(plain_password, password_hash)
    except (PwdlibError, ValueError, TypeError):
        # Hash de outro algoritmo (bcrypt legado), truncado ou vazio: nunca
        # propagamos isso como 500 ? o resultado de seguran?a ? "n?o confere".
        return False


def verify_and_upgrade(plain_password: str, password_hash: str) -> tuple[bool, str | None]:
    """Verifica e, se o custo do hash estiver desatualizado, devolve um novo.

    Retorna `(válido, novo_hash_ou_None)`. O chamador persiste o novo hash quando
    não for `None` — re-hash transparente no login.
    """
    try:
        return _password_hash.verify_and_update(plain_password, password_hash)
    except (PwdlibError, ValueError, TypeError):
        return False, None


def hash_token(raw_token: str) -> str:
    """SHA-256 do refresh token — é isso que vai para o banco, nunca o token."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_token(
    *,
    subject: str | UUID,
    token_type: TokenType,
    settings: Settings,
    ttl: timedelta | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Emite um JWT assinado (HS256 por padrão).

    Claims sempre presentes: `sub`, `typ`, `iat`, `exp`, `iss`, `aud`, `jti`.
    """
    now = datetime.now(UTC)
    if ttl is None:
        ttl = (
            timedelta(minutes=settings.access_token_ttl_minutes)
            if token_type is TokenType.ACCESS
            else timedelta(days=settings.refresh_token_ttl_days)
        )

    claims: dict[str, Any] = {
        "sub": str(subject),
        "typ": token_type.value,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "jti": str(uuid4()),
    }
    if extra_claims:
        claims.update(extra_claims)

    return jwt.encode(
        claims,
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def create_access_token(
    *, subject: str | UUID, settings: Settings, extra_claims: dict[str, Any] | None = None
) -> str:
    return create_token(
        subject=subject,
        token_type=TokenType.ACCESS,
        settings=settings,
        extra_claims=extra_claims,
    )


def create_refresh_token(*, subject: str | UUID, settings: Settings) -> str:
    return create_token(subject=subject, token_type=TokenType.REFRESH, settings=settings)


def decode_token(
    token: str,
    *,
    settings: Settings,
    expected_type: TokenType | None = None,
) -> dict[str, Any]:
    """Valida assinatura, expiração, emissor e audiência.

    Levanta `TokenError` em qualquer falha — o chamador decide o código de fechamento.
    """
    if not token or not token.strip():
        raise TokenError("token vazio")

    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "sub", "typ", "jti"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token expirado") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("token inválido") from exc

    if expected_type is not None and claims.get("typ") != expected_type.value:
        raise TokenError(f"tipo de token inesperado: esperado {expected_type.value}")

    subject = claims.get("sub")
    if not isinstance(subject, str):
        raise TokenError("claim 'sub' inválida")

    try:
        claims["user_id"] = UUID(subject)
    except ValueError as exc:
        raise TokenError("claim 'sub' não é um UUID") from exc

    return claims


def generate_opaque_token(n_bytes: int = 32) -> str:
    """Token opaco (para convites de círculo ou refresh alternativo)."""
    return secrets.token_urlsafe(n_bytes)
