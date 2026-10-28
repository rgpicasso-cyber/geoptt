"""Ponto de entrada da API GeoPTT.

Execução local:
    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import health
from app.api.ws import ptt as ws_ptt
from app.core.config import Settings, get_settings
from app.core.container import Services
from app.core.logging import configure_logging
from app.db.session import Database
from app.services.connection_manager import ConnectionManager
from app.services.fcm_service import FcmService
from app.services.ptt_service import PttService

logger = logging.getLogger(__name__)

_DESCRIPTION = """
API de rastreamento em tempo real e Push-To-Talk do GeoPTT.

* **REST** — autenticação, círculos, localização em lote e canais PTT.
* **WebSocket** `/ws` — presença, áudio Opus (binário) e controle (JSON).
* **Resiliência** — quando o destinatário não tem socket ativo, o servidor dispara
  uma Data Message de alta prioridade via FCM para acordar o app.
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    """Application factory — permite injetar `Settings` em testes."""
    settings = settings or get_settings()
    configure_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = Database(settings)
        connections = ConnectionManager(
            control_queue_size=settings.ws_control_queue_size,
            audio_queue_size=settings.ws_audio_queue_size,
        )
        fcm = FcmService(settings)
        ptt = PttService(
            manager=connections,
            fcm=fcm,
            session_factory=db.session_factory,
            settings=settings,
        )

        app.state.services = Services(
            settings=settings,
            db=db,
            connections=connections,
            fcm=fcm,
            ptt=ptt,
        )

        await fcm.start()
        logger.info(
            "aplicação iniciada",
            extra={"event": "startup", "platform": settings.env},
        )

        try:
            yield
        finally:
            # Ordem importa: parar tráfego → parar áudio → fechar banco.
            await ptt.shutdown()
            await connections.close_all()
            await fcm.stop()
            await db.dispose()
            logger.info("aplicação encerrada", extra={"event": "shutdown"})

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=_DESCRIPTION,
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origin_list),
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Device-Id"],
        )

    app.include_router(health.router)
    app.include_router(ws_ptt.router)

    return app


app = create_app()
