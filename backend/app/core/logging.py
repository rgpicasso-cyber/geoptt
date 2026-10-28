"""Logging estruturado com redação de dados sensíveis.

Regras do projeto (`.opencode/rules.md` §4 e §9):
  * nunca logar token, senha, coordenada exata ou `fcm_token` completo;
  * logs em JSON em produção (parseáveis por Loki/CloudWatch);
  * logs legíveis (texto) em desenvolvimento.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any, Final

from app.core.config import Settings

# Campos de `extra` que propagamos para o JSON quando presentes.
_CONTEXT_FIELDS: Final = (
    "event",
    "user_id",
    "channel_id",
    "connection_id",
    "device_id",
    "platform",
    "path",
    "method",
    "status_code",
    "duration_ms",
    "code",
)

_JWT_RE: Final = re.compile(r"eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")
_KV_SECRET_RE: Final = re.compile(
    r"(?i)\b(token|password|passwd|secret|authorization|api[_-]?key|fcm_token)\b"
    r"\s*[=:]\s*(?:bearer\s+)?\S+"
)
# Coordenada com 5+ casas decimais (~1 m de precisão) — nunca vai para o log.
_COORD_RE: Final = re.compile(r"-?\d{1,3}\.\d{5,}")


def redact(text: str) -> str:
    """Remove segredos e coordenadas de uma string de log."""
    text = _JWT_RE.sub("***JWT***", text)
    text = _KV_SECRET_RE.sub(lambda m: f"{m.group(1)}=***", text)
    return _COORD_RE.sub("***COORD***", text)


class RedactionFilter(logging.Filter):
    """Aplica `redact()` na mensagem já formatada, antes de qualquer handler."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - formatação defensiva
            return True
        record.msg = redact(message)
        record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    """Serializa cada registro como uma linha JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for field in _CONTEXT_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(settings: Settings) -> None:
    """Configura o root logger de forma idempotente."""
    handler: logging.Handler = logging.StreamHandler(stream=sys.stdout)
    handler.addFilter(RedactionFilter())

    if settings.log_json:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(settings.log_level)

    # Bibliotecas verbosas: reduzir ruído.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("firebase_admin").setLevel(logging.WARNING)
