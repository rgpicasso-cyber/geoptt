"""Serviço APNs para PushToTalk Framework (iOS 16+).

Princípios (`docs/ARCHITECTURE.md` §4, ADR-002):

  * **Push tipo `pushtotalk`** — acordar o app em background para entregar áudio PTT;
  * **Topic**: `{bundle_id}.voip-ptt` (ex.: `com.geoptt.voip-ptt`);
  * **Headers obrigatórios**:
      - `apns-push-type: pushtotalk`
      - `apns-priority: 10` (entrega imediata)
      - `apns-expiration: 0` (não armazenar pushes obsoletos)
  * **Payload**: `aps` vazio + chaves custom (channel_id, sender_id, call_id, etc.);
  * **Token efêmero**: recebido do `PTChannelManagerDelegate.channelManager(_:didActivate:withToken:)`;
    válido apenas enquanto o canal estiver ativo.
  * **Autenticação**: JWT com APNs Auth Key (p8) — token-based, não certificado;
  * **HTTP/2** via `httpx` com connection pooling.

Referências:
  - WWDC22 "Enhance voice communication with Push to Talk"
  - Apple Developer: "Sending notification requests to APNs"
  - `apns2` / `httpx` para HTTP/2 assíncrono.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import httpx
import jwt

from app.core.config import Settings
from app.models.enums import Platform
from app.schemas.ws import PROTOCOL_VERSION, WsMessageType

logger = logging.getLogger(__name__)

# APNs endpoints
APNS_PRODUCTION_URL: Final = "https://api.push.apple.com/3/device"
APNS_SANDBOX_URL: Final = "https://api.sandbox.push.apple.com/3/device"

# Tamanho máximo do payload APNs (4 KB para pushes de dados)
APNS_MAX_PAYLOAD_BYTES: Final = 4096

# Tempo de vida do JWT APNs (máximo 1 hora conforme especificação)
APNS_JWT_TTL_SECONDS: Final = 3600


@dataclass(frozen=True, slots=True)
class ApnsWakeupResult:
    """Resultado de uma tentativa de envio de push PTT via APNs."""

    delivered: bool
    invalid_token: bool = False
    reason: str | None = None
    apns_id: str | None = None


@dataclass(frozen=True, slots=True)
class ApnsCredentials:
    """Credenciais APNs carregadas do arquivo .p8."""

    key_id: str
    team_id: str
    bundle_id: str
    private_key: str


class ApnsPttService:
    """Serviço assíncrono para envio de pushes `pushtotalk` ao APNs.

    Uso:
        service = ApnsPttService(settings)
        await service.start()
        result = await service.send_ephemeral_push(
            ephemeral_token="...",  # token base64 do PTChannelManager
            channel_id=...,
            sender_id=...,
        )
        await service.stop()
    """

    def __init__(
        self,
        settings: Settings,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._http_client = http_client
        self._credentials: ApnsCredentials | None = None
        self._jwt_token: str | None = None
        self._jwt_expires_at: float = 0
        self._ready = False
        self._url = APNS_SANDBOX_URL if settings.apns_use_sandbox else APNS_PRODUCTION_URL

    # ------------------------------------------------------------------ propriedades

    @property
    def enabled(self) -> bool:
        return self._settings.apns_enabled

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def url(self) -> str:
        return self._url

    # ------------------------------------------------------------------ ciclo de vida

    async def start(self) -> None:
        """Carrega credenciais e prepara cliente HTTP/2."""
        if not self.enabled:
            logger.info(
                "APNs PTT desabilitado — wake-up iOS não será enviado",
                extra={"event": "apns_disabled"},
            )
            return

        try:
            self._credentials = self._load_credentials()
        except Exception:
            logger.exception(
                "falha ao carregar credenciais APNs", extra={"event": "apns_credentials_failed"}
            )
            if self._settings.is_production:
                raise
            return

        # Cliente HTTP/2 com connection pooling
        if self._http_client is None:
            limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)
            self._http_client = httpx.AsyncClient(
                http2=True,
                limits=limits,
                timeout=httpx.Timeout(10.0, connect=5.0),
            )

        self._ready = True
        logger.info(
            "APNs PTT pronto",
            extra={
                "event": "apns_ready",
                "endpoint": self._url,
                "bundle_id": self._credentials.bundle_id,
            },
        )

    async def stop(self) -> None:
        """Fecha conexões HTTP/2."""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None
        self._ready = False
        logger.info("APNs PTT encerrado", extra={"event": "apns_stopped"})

    # ------------------------------------------------------------------ credenciais / JWT

    def _load_credentials(self) -> ApnsCredentials:
        """Lê o arquivo .p8 e extrai as credenciais necessárias.

        Espera-se que o arquivo .p8 contenha a chave privada EC (P-256) em formato PKCS#8.
        O `key_id` e `team_id` devem vir do Settings (configurados via variáveis de ambiente).
        """
        path = self._settings.apns_auth_key_path
        if not path:
            raise ValueError("apns_auth_key_path não configurado")

        private_key_pem = Path(path).read_text(encoding="utf-8").strip()

        key_id = self._settings.apns_key_id
        team_id = self._settings.apns_team_id
        bundle_id = self._settings.apns_bundle_id

        if not all([key_id, team_id, bundle_id]):
            raise ValueError("apns_key_id, apns_team_id e apns_bundle_id são obrigatórios")

        return ApnsCredentials(
            key_id=key_id,  # type: ignore[arg-type]
            team_id=team_id,  # type: ignore[arg-type]
            bundle_id=bundle_id,  # type: ignore[arg-type]
            private_key=private_key_pem,
        )

    def _get_jwt(self) -> str:
        """Gera (ou reutiliza) o JWT de autenticação APNs.

        O JWT é válido por até 1 hora; renovamos automaticamente próximo ao vencimento.
        """
        now = time.time()
        if self._jwt_token and now < self._jwt_expires_at - 60:  # margem de 60s
            return self._jwt_token

        assert self._credentials is not None
        payload = {
            "iss": self._credentials.team_id,
            "iat": int(now),
        }
        headers = {
            "alg": "ES256",
            "kid": self._credentials.key_id,
        }

        self._jwt_token = jwt.encode(
            payload,
            self._credentials.private_key,
            algorithm="ES256",
            headers=headers,
        )
        self._jwt_expires_at = now + APNS_JWT_TTL_SECONDS
        logger.debug("JWT APNs renovado", extra={"event": "apns_jwt_renewed"})
        return self._jwt_token

    # ------------------------------------------------------------------ envio

    async def send_ephemeral_push(
        self,
        *,
        ephemeral_token: str,
        channel_id: UUID,
        sender_id: UUID,
        call_id: UUID | None = None,
        speaker_name: str | None = None,
        session_ended: bool = False,
    ) -> ApnsWakeupResult:
        """Envia push `pushtotalk` para um token efêmero de canal.

        Args:
            ephemeral_token: Token base64 recebido via `channelManager(_:didActivate:withToken:)`.
            channel_id: ID do canal PTT.
            sender_id: ID do usuário que iniciou a transmissão.
            call_id: ID da chamada/sessão (opcional).
            speaker_name: Nome do locutor ativo (opcional, para UI).
            session_ended: Se True, indica fim de sessão (app deve sair do canal).

        Returns:
            ApnsWakeupResult com status de entrega.
        """
        if not self.enabled:
            return ApnsWakeupResult(delivered=False, reason="apns_disabled")

        if not self._ready or self._credentials is None:
            return ApnsWakeupResult(delivered=False, reason="not_ready")

        if not ephemeral_token:
            return ApnsWakeupResult(delivered=False, reason="missing_ephemeral_token")

        # Monta payload
        payload = self._build_payload(
            channel_id=channel_id,
            sender_id=sender_id,
            call_id=call_id,
            speaker_name=speaker_name,
            session_ended=session_ended,
        )

        # Headers APNs
        headers = {
            "authorization": f"bearer {self._get_jwt()}",
            "apns-push-type": "pushtotalk",
            "apns-priority": "10",
            "apns-expiration": "0",
            "apns-topic": f"{self._credentials.bundle_id}.voip-ptt",
            "content-type": "application/json",
        }

        url = f"{self._url}/{ephemeral_token}"

        assert self._http_client is not None
        try:
            response = await self._http_client.post(
                url,
                json=payload,
                headers=headers,
            )
        except httpx.RequestError as exc:
            logger.warning(
                "erro de rede ao enviar push APNs",
                extra={"event": "apns_network_error", "channel_id": str(channel_id)},
                exc_info=True,
            )
            return ApnsWakeupResult(delivered=False, reason="network_error")

        # APNs retorna 200 com `apns-id` no header em caso de sucesso
        if response.status_code == 200:
            apns_id = response.headers.get("apns-id")
            logger.info(
                "push PTT enviado ao APNs",
                extra={
                    "event": "apns_push_sent",
                    "channel_id": str(channel_id),
                    "apns_id": apns_id,
                },
            )
            return ApnsWakeupResult(delivered=True, apns_id=apns_id)

        # Tratar erros conhecidos
        return self._handle_apns_error(response, channel_id)

    def _build_payload(
        self,
        *,
        channel_id: UUID,
        sender_id: UUID,
        call_id: UUID | None,
        speaker_name: str | None,
        session_ended: bool,
    ) -> dict[str, Any]:
        """Constrói o payload JSON para push `pushtotalk`.

        O corpo `aps` pode ficar vazio; chaves custom vão no nível superior.
        """
        custom: dict[str, Any] = {
            "channel_id": str(channel_id),
            "sender_id": str(sender_id),
            "ts": int(time.time()),
            "v": PROTOCOL_VERSION,
            "type": str(WsMessageType.PTT_WAKEUP),
        }
        if call_id is not None:
            custom["call_id"] = str(call_id)
        if speaker_name:
            custom["speaker_name"] = speaker_name
        if session_ended:
            custom["session_ended"] = True

        # Validação de tamanho
        payload_bytes = json.dumps({"aps": {}, **custom}, separators=(",", ":")).encode()
        if len(payload_bytes) > APNS_MAX_PAYLOAD_BYTES:
            raise ValueError(f"payload APNs excede {APNS_MAX_PAYLOAD_BYTES} bytes")

        return {"aps": {}, **custom}

    def _handle_apns_error(self, response: httpx.Response, channel_id: UUID) -> ApnsWakeupResult:
        """Interpreta códigos de erro APNs e decide se o token é inválido."""
        status = response.status_code
        reason = response.headers.get("apns-id", "unknown")

        # Códigos que indicam token inválido/expirado → devem limpar registro
        if status in (400, 404, 410):
            # 400: BadRequest (token malformado ou expirou)
            # 404: Device token não encontrado
            # 410: Gone (token revogado permanentemente)
            logger.info(
                "token efêmero APNs inválido/expirado",
                extra={
                    "event": "apns_invalid_token",
                    "channel_id": str(channel_id),
                    "status": status,
                },
            )
            return ApnsWakeupResult(delivered=False, invalid_token=True, reason=f"apns_{status}")

        # 429: Too Many Requests (rate limit) — backoff
        if status == 429:
            retry_after = response.headers.get("retry-after", "60")
            logger.warning(
                "rate limit APNs",
                extra={
                    "event": "apns_rate_limited",
                    "channel_id": str(channel_id),
                    "retry_after": retry_after,
                },
            )
            return ApnsWakeupResult(delivered=False, reason="rate_limited")

        # Outros erros
        logger.warning(
            "erro APNs ao enviar push",
            extra={
                "event": "apns_send_failed",
                "channel_id": str(channel_id),
                "status": status,
                "body": response.text[:500],
            },
        )
        return ApnsWakeupResult(delivered=False, reason=f"apns_{status}")


# ------------------------------------------------------------------ factory para injeção de dependência


def create_apns_ptt_service(settings: Settings) -> ApnsPttService:
    """Factory para criar ApnsPttService com configuração do Settings."""
    return ApnsPttService(settings)
