"""Regras de autenticação: registro, login, rotação de refresh e logout.

Decisões de segurança (ver `docs/ARCHITECTURE.md` §7.1 e ADR-006):

* hash **Argon2id** com re-hash transparente no login (`verify_and_upgrade`);
* e-mail inexistente e senha errada devolvem a **mesma** resposta e o mesmo custo
  de CPU (verificação contra hash descartável) — evita enumeração de contas;
* refresh token é opaco para o banco (só o SHA-256 é persistido);
* **reutilização de refresh já rotacionado revoga todas as sessões** do usuário
  (detecção de roubo de token);
* `device_id` divergente revoga apenas aquele token (sessão clonada).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.errors import ConflictError, UnauthorizedError, UnprocessableError
from app.core.security import (
    TokenError,
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    validate_password_policy,
    verify_and_upgrade,
    verify_password,
)
from app.repositories.protocols import TokenRepositoryProtocol, UserRepositoryProtocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    """Par de tokens pronto para serialização (`TokenPair`)."""

    access_token: str
    refresh_token: str
    expires_in: int
    refresh_expires_in: int


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    """Hash descartável (calculado uma vez) para equalizar o tempo do login."""
    return hash_password("geoptt-dummy-password-for-timing-equalization-0")


class AuthService:
    def __init__(
        self,
        *,
        users: UserRepositoryProtocol,
        tokens: TokenRepositoryProtocol,
        settings: Settings,
    ) -> None:
        self._users = users
        self._tokens = tokens
        self._settings = settings

    # ------------------------------------------------------------------ registro
    async def register(
        self,
        *,
        email: str,
        password: str,
        display_name: str,
        device_id: str,
    ) -> IssuedTokens:
        try:
            validate_password_policy(password)
        except ValueError as exc:
            raise UnprocessableError(str(exc)) from exc

        if await self._users.get_by_email(email) is not None:
            raise ConflictError("e-mail já cadastrado", code="EMAIL_TAKEN")

        try:
            user = await self._users.create(
                email=email,
                password_hash=hash_password(password),
                display_name=display_name,
            )
        except IntegrityError as exc:
            # Corrida entre duas requisições com o mesmo e-mail: o índice
            # funcional `ux_users_email_lower` é a última linha de defesa.
            raise ConflictError("e-mail já cadastrado", code="EMAIL_TAKEN") from exc

        logger.info(
            "usuário registrado", extra={"event": "user_registered", "user_id": str(user.id)}
        )
        return await self._issue(user_id=user.id, device_id=device_id)

    # ------------------------------------------------------------------ login
    async def login(self, *, email: str, password: str, device_id: str) -> IssuedTokens:
        user = await self._users.get_by_email(email)
        if user is None:
            # Custo de CPU equivalente ao caminho feliz.
            verify_password(password, _dummy_hash())
            raise UnauthorizedError("credenciais inválidas")

        valid, new_hash = verify_and_upgrade(password, user.password_hash)
        if not valid:
            raise UnauthorizedError("credenciais inválidas")

        if new_hash is not None:
            # Parâmetros de custo do Argon2 mudaram: atualiza sem pedir nada ao usuário.
            await self._users.update_password_hash(user.id, new_hash)

        return await self._issue(user_id=user.id, device_id=device_id)

    # ------------------------------------------------------------------ refresh
    async def refresh(self, *, refresh_token: str, device_id: str) -> IssuedTokens:
        try:
            claims = decode_token(
                refresh_token, settings=self._settings, expected_type=TokenType.REFRESH
            )
        except TokenError as exc:
            raise UnauthorizedError("refresh token inválido") from exc

        user_id: UUID = claims["user_id"]
        now = datetime.now(UTC)
        stored = await self._tokens.get_by_hash(hash_token(refresh_token))

        if stored is None:
            raise UnauthorizedError("refresh token desconhecido")

        if stored.user_id != user_id:
            # O hash existe no banco, mas o `sub` do JWT aponta para outro usuário:
            # indício de forja/segredo comprometido. Derruba as sessões do **dono
            # do registro** (quem de fato pode estar sendo atacado).
            await self._tokens.revoke_all(stored.user_id, revoked_at=now)
            logger.error(
                "refresh token com subject inconsistente",
                extra={
                    "event": "refresh_token_subject_mismatch",
                    "owner_id": str(stored.user_id),
                    "claimed_id": str(user_id),
                },
            )
            raise UnauthorizedError("refresh token inconsistente", code="TOKEN_REUSED")

        if stored.revoked_at is not None:
            # Token já rotacionado voltou a ser usado: cenário clássico de roubo.
            revoked = await self._tokens.revoke_all(user_id, revoked_at=now)
            logger.warning(
                "refresh token reutilizado — todas as sessões revogadas",
                extra={
                    "event": "refresh_token_reuse",
                    "user_id": str(user_id),
                    "revoked_sessions": revoked,
                },
            )
            raise UnauthorizedError(
                "refresh token reutilizado; todas as sessões foram revogadas",
                code="TOKEN_REUSED",
            )

        if stored.expires_at <= now:
            await self._tokens.revoke(stored.id, revoked_at=now)
            raise UnauthorizedError("refresh token expirado", code="TOKEN_EXPIRED")

        if stored.device_id != device_id:
            await self._tokens.revoke(stored.id, revoked_at=now)
            logger.warning(
                "refresh token usado por outro dispositivo",
                extra={"event": "refresh_token_device_mismatch", "user_id": str(user_id)},
            )
            raise UnauthorizedError("refresh token de outro dispositivo", code="TOKEN_REUSED")

        # Rotação: o token usado morre aqui, sempre.
        await self._tokens.revoke(stored.id, revoked_at=now)
        return await self._issue(user_id=user_id, device_id=device_id)

    # ------------------------------------------------------------------ logout
    async def logout(self, *, user_id: UUID, device_id: str | None) -> int:
        """Revoga o refresh do dispositivo (ou todas as sessões se `device_id` for nulo)."""
        now = datetime.now(UTC)
        if device_id is None:
            return await self._tokens.revoke_all(user_id, revoked_at=now)
        return await self._tokens.revoke_device(user_id, device_id, revoked_at=now)

    # ------------------------------------------------------------------ interno
    async def _issue(self, *, user_id: UUID, device_id: str) -> IssuedTokens:
        access_token = create_access_token(subject=user_id, settings=self._settings)
        refresh_token = create_refresh_token(subject=user_id, settings=self._settings)
        refresh_ttl = timedelta(days=self._settings.refresh_token_ttl_days)

        await self._tokens.create(
            user_id=user_id,
            token_hash=hash_token(refresh_token),
            device_id=device_id,
            expires_at=datetime.now(UTC) + refresh_ttl,
        )

        return IssuedTokens(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=self._settings.access_token_ttl_minutes * 60,
            refresh_expires_in=int(refresh_ttl.total_seconds()),
        )
