"""Gera `docs/openapi.yaml` a partir do app FastAPI.

Uso (de `backend/`):

    .\\.venv\\Scripts\\python.exe tools\\export_openapi.py

Por que existe: o schema OpenAPI é o **contrato** entre app Flutter e servidor
(`docs/ARCHITECTURE.md` §7.1). Mantê-lo versionado permite revisar mudanças de
contrato em code review — e o teste `tests/test_openapi_contract.py` falha se o
arquivo commitado divergir do código.

`Settings(_env_file=None)` garante determinismo: um `.env` de desenvolvimento
com `APP_NAME`/`APP_VERSION` customizados não deve alterar o contrato.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

# Permite rodar como script (`python tools/export_openapi.py`).
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

OUTPUT = BACKEND_ROOT.parent / "docs" / "openapi.yaml"


def build_schema() -> dict[str, Any]:
    """Schema OpenAPI determinístico (sem ler `.env`)."""
    settings = Settings(_env_file=None)
    return create_app(settings).openapi()


def render(schema: dict[str, Any]) -> str:
    return yaml.safe_dump(
        schema,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        # Sem dobra de linha: descrições longas ficam em uma linha só, o que
        # torna o diff do contrato legível em code review.
        width=4096,
    )


def main() -> int:
    schema = build_schema()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render(schema), encoding="utf-8", newline="\n")
    paths = len(schema.get("paths", {}))
    print(f"ok: {OUTPUT} ({paths} rotas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
