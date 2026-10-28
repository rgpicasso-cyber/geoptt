"""Configuração central da aplicação (fonte única de verdade para runtime).

Todos os valores vêm de variáveis de ambiente ou de `backend/.env`.
Segredos são tipados como `SecretStr` para nunca aparecerem em `repr()`/logs.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "staging", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

# Valor usado apenas em desenvolvimento/testes. `model_validator` impede que ele
# sobreviva em produção.
_DEV_JWT_SECRET = "dev-insecure-secret-do-not-use-in-production-32chars"

# Menor tamanho aceitável para um segredo HMAC-SHA256.
_MIN_SECRET_LENGTH = 32


class Settings(BaseSettings):
    """Configuração imutável carregada do ambiente."""

    model_config = SettingsConfigDict(
        env_file=(".env",),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Aplicação -----------------------------------------------------------
    env: Environment = "local"
    app_name: str = "GeoPTT API"
    app_version: str = "0.1.0"
    debug: bool = False
    api_prefix: str = "/api/v1"

    # --- Banco de dados ------------------------------------------------------
    database_url: str = "postgresql+asyncpg://geoptt:geoptt@127.0.0.1:5432/geoptt"
    db_echo: bool = False
    db_pool_size: int = Field(default=10, ge=1, le=50)
    db_max_overflow: int = Field(default=20, ge=0, le=100)
    db_pool_recycle_seconds: int = Field(default=1800, ge=60)

    # --- JWT -----------------------------------------------------------------
    jwt_secret: SecretStr = SecretStr(_DEV_JWT_SECRET)
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    jwt_issuer: str = "geoptt"
    jwt_audience: str = "geoptt-app"
    access_token_ttl_minutes: int = Field(default=15, ge=1, le=1440)
    refresh_token_ttl_days: int = Field(default=30, ge=1, le=365)

    # --- WebSocket / PTT -----------------------------------------------------
    ws_auth_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    ws_heartbeat_timeout_seconds: float = Field(default=60.0, gt=5, le=600)
    ws_max_message_bytes: int = Field(default=64 * 1024, ge=1024, le=1024 * 1024)
    ws_control_queue_size: int = Field(default=256, ge=16, le=4096)
    ws_audio_queue_size: int = Field(default=16, ge=2, le=128)
    ptt_speaker_timeout_seconds: float = Field(default=60.0, gt=5, le=600)

    # --- FCM -----------------------------------------------------------------
    fcm_enabled: bool = True
    fcm_credentials_path: str | None = None
    fcm_project_id: str | None = None
    fcm_wakeup_rate_limit_per_minute: int = Field(default=10, ge=1, le=120)

    # --- APNs (iOS PushToTalk) ----------------------------------------------
    apns_enabled: bool = True
    apns_use_sandbox: bool = True
    apns_auth_key_path: str | None = None
    apns_key_id: str | None = None
    apns_team_id: str | None = None
    apns_bundle_id: str | None = None

    # --- HTTP ----------------------------------------------------------------
    cors_origins: str = ""
    # Confiar em `X-Forwarded-For` só quando existe proxy reverso conhecido
    # (Nginx na VPS). Caso contrário o cliente forjaria o IP e escaparia do
    # rate limit de /auth/*.
    trust_proxy_headers: bool = False

    # --- Logs ----------------------------------------------------------------
    log_level: LogLevel = "INFO"
    log_json: bool = True

    # ------------------------------------------------------------------ validadores
    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        """Força o driver assíncrono do PostgreSQL.

        Aceita `postgres://` e `postgresql://` (formatos comuns em provedores) e
        converte para `postgresql+asyncpg://`, evitando erro silencioso de driver
        síncrono em engine assíncrona.
        """
        value = value.strip()
        if value.startswith("postgres://"):
            return "postgresql+asyncpg://" + value.removeprefix("postgres://")
        if value.startswith("postgresql://"):
            return "postgresql+asyncpg://" + value.removeprefix("postgresql://")
        return value

    @field_validator("jwt_secret")
    @classmethod
    def _validate_secret_strength(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if len(raw) < _MIN_SECRET_LENGTH:
            msg = (
                f"JWT_SECRET deve ter ao menos {_MIN_SECRET_LENGTH} caracteres. "
                'Gere com: python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _validate_production_hardening(self) -> Settings:
        """Impede subir produção com defaults de desenvolvimento."""
        if self.env != "production":
            return self

        if self.jwt_secret.get_secret_value() == _DEV_JWT_SECRET:
            msg = "JWT_SECRET padrão de desenvolvimento é proibido em ENV=production."
            raise ValueError(msg)

        if self.debug:
            msg = "DEBUG=true é proibido em ENV=production."
            raise ValueError(msg)

        if self.fcm_enabled and not self.fcm_credentials_path:
            msg = (
                "Em ENV=production com FCM_ENABLED=true, FCM_CREDENTIALS_PATH é "
                "obrigatório (arquivo fora do repositório, ex.: "
                "/opt/geoptt/secrets/serviceAccountKey.json)."
            )
            raise ValueError(msg)

        if self.apns_enabled and not self.apns_auth_key_path:
            msg = (
                "Em ENV=production com APNS_ENABLED=true, APNS_AUTH_KEY_PATH é "
                "obrigatório (arquivo .p8 fora do repositório, ex.: "
                "/opt/geoptt/secrets/AuthKey_XXXXXXXX.p8)."
            )
            raise ValueError(msg)

        if self.apns_enabled and not all(
            [self.apns_key_id, self.apns_team_id, self.apns_bundle_id]
        ):
            msg = (
                "Em ENV=production com APNS_ENABLED=true, APNS_KEY_ID, APNS_TEAM_ID e "
                "APNS_BUNDLE_ID são obrigatórios."
            )
            raise ValueError(msg)

        return self

    # ------------------------------------------------------------------ helpers
    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def cors_origin_list(self) -> tuple[str, ...]:
        """`CORS_ORIGINS` como tupla, aceitando lista separada por vírgula."""
        return tuple(item.strip() for item in self.cors_origins.split(",") if item.strip())

    @property
    def masked_database_url(self) -> str:
        """DSN seguro para log (sem credenciais)."""
        _, _, tail = self.database_url.partition("://")
        _, _, host_part = tail.partition("@")
        return f"postgresql://***@{host_part}" if host_part else "***"

    def new_dev_secret(self) -> str:
        """Utilidade para scripts locais (não usada em runtime)."""
        return secrets.token_urlsafe(48)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Instância única (cacheada) — permite `override` em testes via `cache_clear()`."""
    return Settings()
