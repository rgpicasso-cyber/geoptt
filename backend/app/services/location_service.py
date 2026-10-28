"""Regras de localização: ingestão de lote, snapshot do mapa e broadcast ao vivo.

Estratégia anti-dreno de bateria (o cliente decide *quando* enviar; o servidor
apenas garante que o custo por envio seja baixo):

* **lote** de até 50 pontos por requisição — a fila offline é drenada de uma vez;
* `upsert` da posição atual + `insert` do histórico em 2 statements, não 2xN;
* `ON CONFLICT DO NOTHING` em `(user_id, client_seq)` torna o reenvio idempotente;
* broadcast apenas do **ponto mais recente** e só se ele for fresco — reenviar
  histórico não deve animar o mapa dos outros membros.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.repositories.circle_repository import CircleRepository
from app.repositories.location_repository import LocationRepository
from app.repositories.protocols import (
    CircleRepositoryProtocol,
    LocationPointInput,
    LocationRepositoryProtocol,
    PositionView,
    UserRepositoryProtocol,
)
from app.repositories.user_repository import UserRepository
from app.schemas.location import LocationPoint
from app.schemas.ws import WsMessageType, envelope
from app.services.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)

# Acima disso o ponto é histórico (fila offline antiga) e não vira broadcast.
BROADCAST_MAX_AGE: Final = timedelta(minutes=2)


@dataclass(frozen=True, slots=True)
class IngestResult:
    accepted: int
    duplicated: int
    server_ts: int


class LocationService:
    def __init__(
        self,
        *,
        locations: LocationRepositoryProtocol,
        circles: CircleRepositoryProtocol,
        users: UserRepositoryProtocol,
        manager: ConnectionManager,
    ) -> None:
        self._locations = locations
        self._circles = circles
        self._users = users
        self._manager = manager

    # ------------------------------------------------------------------ ingestão
    async def ingest_batch(self, *, user_id: UUID, points: Sequence[LocationPoint]) -> IngestResult:
        """Persiste o lote e propaga o ponto mais recente aos membros dos círculos."""
        inputs = [
            LocationPointInput(
                lat=point.lat,
                lng=point.lng,
                accuracy_m=point.accuracy_m,
                speed_mps=point.speed_mps,
                heading_deg=point.heading_deg,
                battery_level=point.battery_level,
                client_seq=point.client_seq,
                recorded_at=point.recorded_at,
            )
            for point in points
        ]

        inserted = await self._locations.insert_history(user_id=user_id, points=inputs)

        # A posição "atual" é a de maior `recorded_at`, não a última do array:
        # a fila offline pode ser drenada fora de ordem.
        latest = max(inputs, key=lambda item: item.recorded_at)
        await self._locations.upsert_current(user_id=user_id, point=latest)
        await self._users.touch_presence(
            user_id,
            battery_level=latest.battery_level,
            seen_at=datetime.now(UTC),
        )

        await self._broadcast(user_id=user_id, point=latest)

        return IngestResult(
            accepted=inserted,
            duplicated=len(inputs) - inserted,
            server_ts=int(time.time()),
        )

    # ------------------------------------------------------------------ mapa
    async def circle_positions(self, *, circle_id: UUID, requester_id: UUID) -> list[PositionView]:
        circle = await self._circles.get_by_id(circle_id)
        if circle is None:
            raise NotFoundError("círculo não encontrado")
        if await self._circles.get_member(circle_id, requester_id) is None:
            raise NotFoundError("círculo não encontrado")
        return await self._locations.list_circle_positions(circle_id)

    # ------------------------------------------------------------------ interno
    async def _broadcast(self, *, user_id: UUID, point: LocationPointInput) -> None:
        """Fan-out best-effort: falha de presença nunca derruba o ingest."""
        if datetime.now(UTC) - point.recorded_at > BROADCAST_MAX_AGE:
            return

        try:
            recipients = await self._circles.list_broadcast_recipients(user_id)
        except Exception:  # pragma: no cover - defensivo
            logger.warning(
                "falha ao resolver destinatários do LOCATION_UPDATE",
                extra={"event": "location_broadcast_recipients_failed", "user_id": str(user_id)},
                exc_info=True,
            )
            return

        if not recipients:
            return

        self._manager.broadcast(
            recipients,
            envelope(
                WsMessageType.LOCATION_UPDATE,
                data={
                    "user_id": str(user_id),
                    "lat": point.lat,
                    "lng": point.lng,
                    "speed": point.speed_mps,
                    "heading": point.heading_deg,
                    "battery_level": point.battery_level,
                    "ts": int(point.recorded_at.timestamp()),
                },
            ),
        )


def build_location_service(session: AsyncSession, *, manager: ConnectionManager) -> LocationService:
    """Monta o serviço com repositórios presos a uma sessão.

    Usado por dois caminhos distintos:

    * **REST** — `app.api.deps.get_location_service` (sessão da requisição,
      commit feito por `get_session`);
    * **WebSocket** — `LOCATION_BATCH` abre sessão curta própria e faz `commit()`
      explicitamente, porque o socket vive muito além de qualquer transação.
    """
    return LocationService(
        locations=LocationRepository(session),
        circles=CircleRepository(session),
        users=UserRepository(session),
        manager=manager,
    )
