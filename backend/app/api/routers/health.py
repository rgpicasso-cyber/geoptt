"""Probes de saúde — usados por Nginx, systemd e monitoramento externo."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.deps import get_services
from app.core.container import Services

router = APIRouter(tags=["health"])

ServicesDep = Annotated[Services, Depends(get_services)]


@router.get("/health", summary="Liveness probe")
async def liveness(services: ServicesDep) -> dict[str, str]:
    """Responde 200 se o processo está vivo. Não toca no banco."""
    return {
        "status": "ok",
        "service": services.settings.app_name,
        "version": services.settings.app_version,
        "env": services.settings.env,
    }


@router.get("/health/ready", summary="Readiness probe")
async def readiness(services: ServicesDep) -> JSONResponse:
    """Verifica banco e FCM. Retorna 503 se algo essencial estiver indisponível."""
    db_ok = await services.db.ping()
    fcm_ok = (not services.settings.fcm_enabled) or services.fcm.ready
    ready = db_ok and fcm_ok

    body: dict[str, Any] = {
        "status": "ready" if ready else "degraded",
        "database": db_ok,
        "fcm": fcm_ok,
        "websockets": services.connections.stats,
        "busy_channels": len(services.ptt.busy_channels),
    }
    return JSONResponse(status_code=200 if ready else 503, content=body)
