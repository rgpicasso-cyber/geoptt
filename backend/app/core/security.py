"""Primitivas de segurança: hash de senha (bcrypt) e tokens JWT.

Não há rotas de autenticação aqui — apenas as funções usadas pelo handshake do
WebSocket e, na próxima entrega da Fase 2, pelos routers `/auth/*`.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Final
from uuid import UUID, uuid4

import jwt
from passlib.context import CryptContext

from app.core.config import Settings

# bcrypt ignora bytes além do 72º; rejeitar explicitamente evita truncamento silencioso.
BCRYPT_MAX_PASSWORD_BYTES: Final = 72

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class TokenType(StrEnum):
    """Tipo do token, gravado na claim `typ`."""

    ACCESS = "access"
    REFRESH = "refresh"


class TokenError(Exception):
    """Token ausente, malformado, expirado ou de tipo inesperado."""


def hash_password(password: str) -> str:
    """Gera o hash bcrypt da senha.

    Levanta `ValueError` se a senha exceder 72 bytes em UTF-8.
    """
    if len(password.encode("utf-8")) > BCRYPT_MAX_PASSWORD_BYTES:
        msg = f"Senha excede {BCRYPT_MAX_PASSWORD_BYTES} bytes (limite do bcrypt)."
        raise ValueError(msg)
    return _pwd_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Compara senha e hash em tempo constante. Nunca levanta por hash inválido."""
    try:
        return _pwd_context.verify(plain_password, password_hash)
    except (ValueError, TypeError):
        return False


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
