"""Guarda de deriva do contrato OpenAPI.

O arquivo `docs/openapi.yaml` é versionado e é a fonte de verdade consumida pelo
app Flutter. Se o código mudar e o arquivo não, este teste falha — evitando que
o cliente e o servidor divirjam silenciosamente.

Regenerar:

    python tools/export_openapi.py
"""

from __future__ import annotations

from pathlib import Path

from tools.export_openapi import build_schema, render

DOCS = Path(__file__).resolve().parents[2] / "docs" / "openapi.yaml"


def test_committed_schema_matches_the_application() -> None:
    committed = DOCS.read_text(encoding="utf-8")
    generated = render(build_schema())

    assert generated == committed, (
        "docs/openapi.yaml está desatualizado; rode `python tools/export_openapi.py`"
    )


def test_rest_routes_live_under_the_api_prefix() -> None:
    paths = set(build_schema()["paths"])

    rest = {path for path in paths if path not in {"/health", "/health/ready"}}
    assert rest, "nenhuma rota REST exposta"
    assert all(path.startswith("/api/v1/") for path in rest)


def test_protected_routes_document_401() -> None:
    paths = build_schema()["paths"]

    assert "401" in paths["/api/v1/users/me"]["get"]["responses"]
    assert "401" in paths["/api/v1/circles"]["get"]["responses"]
    assert "401" in paths["/api/v1/location/batch"]["post"]["responses"]


def test_token_pair_schema_is_documented() -> None:
    schemas = build_schema()["components"]["schemas"]

    assert {"access_token", "refresh_token", "token_type", "expires_in"} <= set(
        schemas["TokenPair"]["properties"]
    )


def test_no_password_field_leaks_into_responses() -> None:
    """`UserPublic` nunca pode expor hash de senha nem token FCM."""
    schemas = build_schema()["components"]["schemas"]
    public = schemas["UserPublic"]["properties"]

    assert "password_hash" not in public
    assert "fcm_token" not in public
