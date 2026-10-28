"""Regras de círculos: criação, convite, listagem e remoção de membros.

Regras de autorização (espelham `docs/ARCHITECTURE.md` §7.1):

* **404** quando o solicitante não é membro — nunca **403** para círculo alheio,
  senão a resposta vira um oráculo de existência;
* **403** apenas em operação *dentro* de um círculo do qual o usuário participa
  (ex.: membro comum tentando remover outro membro);
* o **owner nunca é removível** — transferência de propriedade é uma feature
  separada (não faz parte do MVP).
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from app.core.errors import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.models.enums import CircleRole
from app.repositories.protocols import (
    CircleRepositoryProtocol,
    CircleSummary,
    MemberView,
    PttChannelWriterProtocol,
)

logger = logging.getLogger(__name__)

# Canal criado automaticamente em todo círculo novo.
DEFAULT_CHANNEL_NAME: Final = "Geral"

# Sem caracteres ambíguos (0/O, 1/I/L): o código é digitado à mão pelo usuário.
_INVITE_ALPHABET: Final = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_INVITE_LENGTH: Final = 8
_INVITE_MAX_ATTEMPTS: Final = 5

_MANAGER_ROLES: Final = frozenset({CircleRole.OWNER, CircleRole.ADMIN})


class CircleService:
    def __init__(
        self,
        *,
        circles: CircleRepositoryProtocol,
        channels: PttChannelWriterProtocol,
    ) -> None:
        self._circles = circles
        self._channels = channels

    # ------------------------------------------------------------------ criação
    async def create(self, *, name: str, owner_id: UUID) -> CircleSummary:
        invite_code = await self._generate_invite_code()
        circle = await self._circles.create(name=name, owner_id=owner_id, invite_code=invite_code)
        await self._circles.add_member(circle_id=circle.id, user_id=owner_id, role=CircleRole.OWNER)

        # Todo círculo nasce com o canal padrão e o owner já habilitado a falar.
        channel = await self._channels.create_channel(
            circle_id=circle.id, name=DEFAULT_CHANNEL_NAME, created_by=owner_id
        )
        await self._channels.add_member(channel_id=channel.id, user_id=owner_id, can_speak=True)

        logger.info(
            "círculo criado",
            extra={
                "event": "circle_created",
                "circle_id": str(circle.id),
                "owner_id": str(owner_id),
            },
        )
        return CircleSummary(
            id=circle.id,
            name=circle.name,
            owner_id=circle.owner_id,
            invite_code=circle.invite_code,
            role=CircleRole.OWNER,
            member_count=1,
            created_at=circle.created_at,
        )

    # ------------------------------------------------------------------ convite
    async def join(self, *, invite_code: str, user_id: UUID) -> CircleSummary:
        circle = await self._circles.get_by_invite_code(invite_code)
        if circle is None:
            # 404 e não 403: não confirmamos a existência de códigos válidos.
            raise NotFoundError("convite inválido")

        if await self._circles.get_member(circle.id, user_id) is not None:
            raise ConflictError("usuário já é membro deste círculo", code="ALREADY_MEMBER")

        await self._circles.add_member(circle_id=circle.id, user_id=user_id, role=CircleRole.MEMBER)
        await self._channels.add_member_to_circle_channels(circle.id, user_id)
        await self._circles.touch_circle(circle.id, at=datetime.now(UTC))

        member_ids = await self._circles.list_member_ids(circle.id)
        logger.info(
            "membro entrou no círculo",
            extra={
                "event": "circle_member_joined",
                "circle_id": str(circle.id),
                "user_id": str(user_id),
            },
        )
        return CircleSummary(
            id=circle.id,
            name=circle.name,
            owner_id=circle.owner_id,
            invite_code=circle.invite_code,
            role=CircleRole.MEMBER,
            member_count=len(member_ids),
            created_at=circle.created_at,
        )

    # ------------------------------------------------------------------ leitura
    async def list_for_user(self, user_id: UUID) -> list[CircleSummary]:
        return await self._circles.list_for_user(user_id)

    async def list_members(self, *, circle_id: UUID, requester_id: UUID) -> list[MemberView]:
        await self._require_membership(circle_id, requester_id)
        return await self._circles.list_members(circle_id)

    # ------------------------------------------------------------------ remoção
    async def remove_member(self, *, circle_id: UUID, requester_id: UUID, target_id: UUID) -> None:
        circle = await self._circles.get_by_id(circle_id)
        if circle is None:
            raise NotFoundError("círculo não encontrado")

        requester = await self._circles.get_member(circle_id, requester_id)
        if requester is None:
            raise NotFoundError("círculo não encontrado")

        if target_id == circle.owner_id:
            raise BadRequestError(
                "o owner não pode ser removido; transfira a propriedade antes",
                code="CANNOT_REMOVE_OWNER",
            )

        # Sair do próprio círculo é sempre permitido; remover terceiros exige papel.
        if target_id != requester_id and requester.role not in _MANAGER_ROLES:
            raise ForbiddenError("somente owner ou admin podem remover outros membros")

        target = await self._circles.get_member(circle_id, target_id)
        if target is None:
            raise NotFoundError("membro não encontrado")

        await self._circles.remove_member(circle_id, target_id)
        await self._channels.remove_member_from_circle_channels(circle_id, target_id)
        await self._circles.touch_circle(circle_id, at=datetime.now(UTC))

        logger.info(
            "membro removido do círculo",
            extra={
                "event": "circle_member_removed",
                "circle_id": str(circle_id),
                "user_id": str(target_id),
                "by": str(requester_id),
            },
        )

    # ------------------------------------------------------------------ interno
    async def _require_membership(self, circle_id: UUID, requester_id: UUID) -> None:
        circle = await self._circles.get_by_id(circle_id)
        if circle is None:
            raise NotFoundError("círculo não encontrado")
        if await self._circles.get_member(circle_id, requester_id) is None:
            raise NotFoundError("círculo não encontrado")

    async def _generate_invite_code(self) -> str:
        for _ in range(_INVITE_MAX_ATTEMPTS):
            code = "".join(secrets.choice(_INVITE_ALPHABET) for _ in range(_INVITE_LENGTH))
            if not await self._circles.invite_code_exists(code):
                return code
        # 32^8 combinações: chegar aqui indica colisão patológica ou bug.
        raise ConflictError(
            "não foi possível gerar um código de convite", code="INVITE_CODE_UNAVAILABLE"
        )
