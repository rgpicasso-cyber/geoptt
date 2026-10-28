"""Erros de aplicação e handlers HTTP.

Contrato de erro (`docs/ARCHITECTURE.md` §7.1):

```json
{ "error": { "code": "EMAIL_TAKEN", "message": "e-mail já cadastrado" } }
```

Regra de segurança: a resposta de validação **nunca** ecoa o valor recebido —
payloads de `/auth/*` contêm senhas em claro.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

# Mapeia status HTTP → código de erro estável do contrato.
_STATUS_CODES: Final[dict[int, str]] = {
    status.HTTP_400_BAD_REQUEST: "BAD_REQUEST",
    status.HTTP_401_UNAUTHORIZED: "UNAUTHORIZED",
    status.HTTP_403_FORBIDDEN: "FORBIDDEN",
    status.HTTP_404_NOT_FOUND: "NOT_FOUND",
    status.HTTP_405_METHOD_NOT_ALLOWED: "METHOD_NOT_ALLOWED",
    status.HTTP_409_CONFLICT: "CONFLICT",
    status.HTTP_422_UNPROCESSABLE_CONTENT: "VALIDATION_ERROR",
    status.HTTP_429_TOO_MANY_REQUESTS: "RATE_LIMITED",
    status.HTTP_500_INTERNAL_SERVER_ERROR: "INTERNAL",
    status.HTTP_503_SERVICE_UNAVAILABLE: "UNAVAILABLE",
}


class AppError(Exception):
    """Erro de negócio com status HTTP e código estável."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "BAD_REQUEST"
    message: str = "requisição inválida"

    def __init__(self, message: str | None = None, *, code: str | None = None) -> None:
        super().__init__(message or self.message)
        if message:
            self.message = message
        if code:
            self.code = code

    def to_response(self) -> JSONResponse:
        return JSONResponse(
            status_code=self.status_code,
            content=error_body(self.code, self.message),
        )


class UnauthorizedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "UNAUTHORIZED"
    message = "não autenticado"


class BadRequestError(AppError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "BAD_REQUEST"
    message = "requisição inválida"


class UnprocessableError(AppError):
    """Regra de negócio que invalida o payload (ex.: senha fraca)."""

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "VALIDATION_ERROR"
    message = "payload inválido"


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "FORBIDDEN"
    message = "acesso negado"


class NotAMemberError(ForbiddenError):
    code = "NOT_A_MEMBER"
    message = "usuário não é membro deste círculo"


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"
    message = "recurso não encontrado"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "CONFLICT"
    message = "conflito de estado"


class RateLimitedError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "RATE_LIMITED"
    message = "muitas requisições; tente novamente em instantes"

    def __init__(self, message: str | None = None, *, retry_after: int = 60) -> None:
        super().__init__(message)
        self.retry_after = retry_after

    def to_response(self) -> JSONResponse:
        response = super().to_response()
        response.headers["Retry-After"] = str(self.retry_after)
        return response


def error_body(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


# --------------------------------------------------------------------------- handlers
async def app_error_handler(_: Request, exc: Exception) -> JSONResponse:
    """Handler de `AppError` (o parâmetro é `Exception` por compatibilidade)."""
    if not isinstance(exc, AppError):  # pragma: no cover - defensivo
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_body("INTERNAL", "erro interno"),
        )
    if exc.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        logger.error("erro de aplicação", exc_info=exc, extra={"event": "app_error"})
    return exc.to_response()


async def http_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    """Normaliza `HTTPException` (inclui 401 do `HTTPBearer`) no envelope do contrato."""
    if not isinstance(exc, StarletteHTTPException):  # pragma: no cover - defensivo
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_body("INTERNAL", "erro interno"),
        )

    code = _STATUS_CODES.get(exc.status_code, "ERROR")
    detail = exc.detail if isinstance(exc.detail, str) else code
    headers = getattr(exc, "headers", None)
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(code, detail),
        headers=headers,
    )


async def validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    """422 sem ecoar o valor recebido (payloads de auth contêm senha)."""
    details: list[dict[str, Any]] = []
    if isinstance(exc, RequestValidationError):
        for error in exc.errors():
            location = ".".join(str(part) for part in error.get("loc", ()))
            details.append(
                {
                    "loc": location,
                    "msg": str(error.get("msg", "valor inválido")),
                    "type": str(error.get("type", "value_error")),
                }
            )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "payload inválido",
                "details": details,
            }
        },
    )


async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    """Rede de segurança: nunca vazar stack trace para o cliente."""
    logger.error("erro não tratado", exc_info=exc, extra={"event": "unhandled_error"})
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_body("INTERNAL", "erro interno"),
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
