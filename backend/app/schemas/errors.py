"""Envelope de erro do contrato REST (`docs/ARCHITECTURE.md` §7.1).

Estes modelos existem para o OpenAPI: sem eles, o cliente Flutter não teria como
gerar tipos para as respostas de erro — e o contrato ficaria só na documentação
em prosa.

Formato:

```json
{ "error": { "code": "EMAIL_TAKEN", "message": "e-mail já cadastrado" } }
```
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """Código estável (para o cliente decidir o que fazer) + mensagem humana."""

    code: str = Field(description="Código estável do erro, ex.: EMAIL_TAKEN")
    message: str = Field(description="Mensagem legível, em português")


class ValidationDetail(BaseModel):
    """Item de `details` — **nunca** inclui o valor recebido (pode ser senha)."""

    loc: str
    msg: str
    type: str


class ErrorEnvelope(BaseModel):
    error: ErrorDetail
    details: list[ValidationDetail] | None = None


def error_response(description: str) -> dict[str, Any]:
    """Resposta reutilizável para o parâmetro `responses=` do FastAPI."""
    return {"model": ErrorEnvelope, "description": description}


UNAUTHORIZED = error_response("Token ausente, inválido ou expirado")
FORBIDDEN = error_response("Autenticado, mas sem permissão para a operação")
NOT_FOUND = error_response("Recurso inexistente **ou** fora do alcance do usuário")
CONFLICT = error_response("Conflito de estado (e-mail, convite, associação)")
VALIDATION = error_response("Payload inválido")
RATE_LIMITED = error_response("Limite de requisições por IP excedido")
