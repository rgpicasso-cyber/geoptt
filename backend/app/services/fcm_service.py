"""Serviço de Push (FCM) — Data Message de alta prioridade para wake-up.

Princípios (`docs/ARCHITECTURE.md` §4 e `.opencode/skills/mobile-background-resilience`):

  * **data-only** (nunca `notification`): o objetivo é acordar o app, não mostrar UI;
  * `android.priority = high` e `ttl = 0`: entregar agora ou descartar (áudio é perecível);
  * payload **< 4 KB** e **sem áudio** — apenas o ponteiro do canal/locutor;
  * `messaging.send` é síncrono → sempre via `asyncio.to_thread` para não bloquear o loop;
  * token inválido → sinaliza `invalid_token` para o chamador limpar `users.fcm_token`.

No iOS o FCM entrega *background push* (`content-available`), que o sistema pode
atrasar ou suprimir. O despertar garantido em iOS exige PushKit/VoIP (Fase 3).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Final
from uuid import UUID

import firebase_admin
from firebase_admin import credentials, messaging

from app.core.config import Settings
from app.models.enums import Platform
from app.schemas.ws import PROTOCOL_VERSION, WsMessageType

logger = logging.getLogger(__name__)

# Tamanho máximo aceito pelo FCM para o payload de dados.
FCM_MAX_DATA_BYTES: Final = 4096

_UNREGISTERED_ERROR = getattr(messaging, "UnregisteredError", None)


@dataclass(frozen=True, slots=True)
class WakeupResult:
    """Resultado de uma tentativa de wake-up."""

    delivered: bool
    invalid_token: bool = False
    reason: str | None = None


def mask_token(token: str | None) -> str:
    """Representação segura de um token para log (nunca o token completo)."""
    if not token:
        return "<none>"
    return f"{token[:6]}…({len(token)}b)"


class SlidingWindowLimiter:
    """Rate limit em memória por chave (janela deslizante).

    Evita *push bombing*: um cliente malicioso não deve conseguir forçar o servidor
    a disparar milhares de pushes para a mesma vítima.
    """

    def __init__(
        self,
        limit: int,
        *,
        window_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 10_000,
    ) -> None:
        if limit < 1:
            msg = "limit deve ser >= 1"
            raise ValueError(msg)
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._max_keys = max_keys
        self._buckets: dict[Hashable, deque[float]] = {}

    def allow(self, key: Hashable) -> bool:
        now = self._clock()
        bucket = self._buckets.get(key)
        if bucket is None:
            if len(self._buckets) >= self._max_keys:
                self._prune(now)
            bucket = deque()
            self._buckets[key] = bucket

        while bucket and now - bucket[0] >= self._window:
            bucket.popleft()

        if len(bucket) >= self._limit:
            return False

        bucket.append(now)
        return True

    def _prune(self, now: float) -> None:
        expired = [
            key
            for key, bucket in self._buckets.items()
            if not bucket or now - bucket[-1] >= self._window
        ]
        for key in expired:
            self._buckets.pop(key, None)


class FcmService:
    """Fachada assíncrona sobre o Firebase Admin SDK."""

    def __init__(self, settings: Settings, *, limiter: SlidingWindowLimiter | None = None) -> None:
        self._settings = settings
        self._app: firebase_admin.App | None = None
        self._ready = False
        self._limiter = limiter or SlidingWindowLimiter(settings.fcm_wakeup_rate_limit_per_minute)

    # ------------------------------------------------------------------ propriedades
    @property
    def enabled(self) -> bool:
        return self._settings.fcm_enabled

    @property
    def ready(self) -> bool:
        return self._ready

    # ------------------------------------------------------------------ ciclo de vida
    async def start(self) -> None:
        """Inicializa o SDK. Em produção, falha aqui aborta o startup."""
        if not self.enabled:
            logger.info(
                "FCM desabilitado — wake-up será simulado (ambiente local)",
                extra={"event": "fcm_disabled"},
            )
            return

        try:
            self._app = await asyncio.to_thread(self._initialize_sync)
        except Exception:
            logger.exception(
                "falha ao inicializar Firebase Admin SDK", extra={"event": "fcm_init_failed"}
            )
            if self._settings.is_production:
                raise
            return

        self._ready = True
        logger.info("FCM pronto", extra={"event": "fcm_ready"})

    async def stop(self) -> None:
        """Libera a app do Firebase (idempotente)."""
        app, self._app = self._app, None
        self._ready = False
        if app is None:
            return
        try:
            await asyncio.to_thread(firebase_admin.delete_app, app)
        except Exception:  # pragma: no cover - shutdown defensivo
            logger.warning("falha ao encerrar app Firebase", exc_info=True)

    def _initialize_sync(self) -> firebase_admin.App:
        try:
            return firebase_admin.get_app()
        except ValueError:
            pass

        options: dict[str, Any] | None = (
            {"projectId": self._settings.fcm_project_id} if self._settings.fcm_project_id else None
        )

        path = self._settings.fcm_credentials_path
        # O arquivo deve viver FORA do repositório (ex.: /opt/geoptt/secrets).
        cred = credentials.Certificate(path) if path else credentials.ApplicationDefault()

        return firebase_admin.initialize_app(cred, options)

    # ------------------------------------------------------------------ envio
    async def send_wakeup(
        self,
        *,
        user_id: UUID,
        fcm_token: str | None,
        platform: Platform | None,
        channel_id: UUID,
        sender_id: UUID,
        call_id: UUID | None = None,
        ttl_seconds: int = 0,
    ) -> WakeupResult:
        """Dispara `PTT_WAKEUP` para um usuário offline.

        Chamado **uma vez por pressão de PTT** (não por chunk de áudio): disparar
        por frame inundaria o FCM e estouraria o rate limit em segundos.
        """
        if not fcm_token:
            return WakeupResult(delivered=False, reason="missing_token")

        if not self.enabled:
            logger.info(
                "wake-up simulado (FCM desabilitado)",
                extra={
                    "event": "fcm_wakeup_simulated",
                    "user_id": str(user_id),
                    "channel_id": str(channel_id),
                },
            )
            return WakeupResult(delivered=False, reason="fcm_disabled")

        if self._app is None:
            return WakeupResult(delivered=False, reason="not_ready")

        if not self._limiter.allow(user_id):
            logger.warning(
                "wake-up bloqueado por rate limit",
                extra={"event": "fcm_rate_limited", "user_id": str(user_id)},
            )
            return WakeupResult(delivered=False, reason="rate_limited")

        message = self.build_message(
            fcm_token=fcm_token,
            channel_id=channel_id,
            sender_id=sender_id,
            call_id=call_id,
            ttl_seconds=ttl_seconds,
        )

        try:
            await asyncio.to_thread(messaging.send, message, app=self._app)
        except Exception as exc:
            if self._is_unregistered(exc):
                logger.info(
                    "token FCM inválido/expirado",
                    extra={"event": "fcm_invalid_token", "user_id": str(user_id)},
                )
                return WakeupResult(delivered=False, invalid_token=True, reason="unregistered")

            logger.warning(
                "falha ao enviar wake-up",
                extra={"event": "fcm_send_failed", "user_id": str(user_id)},
                exc_info=True,
            )
            return WakeupResult(delivered=False, reason="send_failed")

        logger.info(
            "wake-up enviado",
            extra={
                "event": "fcm_wakeup_sent",
                "user_id": str(user_id),
                "channel_id": str(channel_id),
                "platform": platform.value if platform is not None else None,
            },
        )
        return WakeupResult(delivered=True)

    def build_message(
        self,
        *,
        fcm_token: str,
        channel_id: UUID,
        sender_id: UUID,
        call_id: UUID | None = None,
        ttl_seconds: int = 0,
    ) -> messaging.Message:
        """Monta a Data Message. Todos os valores de `data` devem ser strings."""
        data: dict[str, str] = {
            "type": str(WsMessageType.PTT_WAKEUP),
            "v": str(PROTOCOL_VERSION),
            "channel_id": str(channel_id),
            "sender_id": str(sender_id),
            "ts": str(int(time.time())),
        }
        if call_id is not None:
            data["call_id"] = str(call_id)

        size = sum(len(key) + len(value) for key, value in data.items())
        if size > FCM_MAX_DATA_BYTES:  # pragma: no cover - payload fixo e pequeno
            msg = f"payload FCM excede {FCM_MAX_DATA_BYTES} bytes"
            raise ValueError(msg)

        return messaging.Message(
            token=fcm_token,
            data=data,
            android=messaging.AndroidConfig(
                priority="high",
                ttl=timedelta(seconds=ttl_seconds),
            ),
            apns=messaging.APNSConfig(
                headers={
                    # Background push: prioridade 5 (obrigatório para content-available).
                    "apns-priority": "5",
                    "apns-push-type": "background",
                },
                payload={"aps": {"content-available": 1}},
            ),
        )

    @staticmethod
    def _is_unregistered(exc: Exception) -> bool:
        """Detecta token morto.

        `registration-token-not-registered` é o caso canônico. `invalid-argument`
        também indica token malformado e deve limpar o registro do usuário.
        """
        if _UNREGISTERED_ERROR is not None and isinstance(exc, _UNREGISTERED_ERROR):
            return True
        text = str(exc).lower()
        return "not-registered" in text or "not registered" in text or "invalid-argument" in text
