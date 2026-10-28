"""Fixtures globais.

Regras:
  * nenhum teste toca PostgreSQL/PostGIS (o schema geoespacial não roda em SQLite);
  * `Settings` é construído explicitamente com `_env_file=None` para que um `.env`
    de desenvolvimento não vaze para a suíte.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from app.core.config import Settings

# Segredo forte o suficiente para passar no validador (>= 32 chars).
TEST_JWT_SECRET = "test-secret-key-with-at-least-32-characters-ok"

_BASE_OVERRIDES: dict[str, Any] = {
    "_env_file": None,
    "env": "local",
    "debug": False,
    "database_url": "postgresql+asyncpg://test:test@127.0.0.1:5432/test",
    "jwt_secret": TEST_JWT_SECRET,
    "fcm_enabled": False,
    "log_json": False,
    "log_level": "WARNING",
    "ws_auth_timeout_seconds": 0.2,
    "ws_heartbeat_timeout_seconds": 6.0,
    "ptt_speaker_timeout_seconds": 10.0,
}


def build_settings(**overrides: Any) -> Settings:
    """Cria `Settings` de teste, sobrescrevendo apenas o necessário."""
    values: dict[str, Any] = {**_BASE_OVERRIDES, **overrides}
    return Settings(**values)


@pytest.fixture
def settings() -> Settings:
    """Configuração isolada de teste (FCM desligado, sem `.env`)."""
    return build_settings()


@pytest.fixture
def settings_factory() -> Callable[..., Settings]:
    """Fábrica de variações de `Settings` preservando os defaults de teste."""
    return build_settings
