"""Журнал аудита: ``/api/v1/admin/audit*`` (plan §4.4, §4.6, D-7, D-8, FR-41, FR-45a, AC-66).

Гейт раздела — router-level ``require_capability(VIEW_AUDIT)``: зависимости выполняются раньше
разбора пути и параметров, поэтому БА, Пользователь и «без роли» получают 403 для любого
запроса. Только ``GET``: для прочих методов роутер отвечает 405 ``method_not_allowed``,
запись через API не меняется и не удаляется. Чужая, несуществующая и не аудитная запись —
одинаковый 404 ``not_found``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_active_actor, require_capability
from app.api.openapi import error_responses
from app.api.v1.schemas.audit import AuditActor, AuditEntry, AuditListQuery
from app.core.db import DbSession
from app.core.pagination import Page
from app.domain.access.roles import Actor, Capability
from app.domain.events import queries
from app.domain.events.catalog import EntityType
from app.domain.events.queries import AuditRecord

router = APIRouter(
    prefix="/admin/audit",
    tags=["admin-audit"],
    dependencies=[Depends(require_capability(Capability.VIEW_AUDIT))],
    responses=error_responses(401, 403),
)

# ``get_active_actor`` общий с гейтом раздела (кэш зависимостей запроса): ``get_actor`` один.
CurrentActor = Annotated[Actor, Depends(get_active_actor)]


def _to_entry(record: AuditRecord) -> AuditEntry:
    return AuditEntry(
        id=record.id,
        occurred_at=record.occurred_at,
        actor=AuditActor(
            kind="system" if record.actor_id is None else "user",
            id=record.actor_id,
            login=record.actor_login,
        ),
        action=record.action,
        entity_type=EntityType(record.entity_type),
        entity_id=record.entity_id,
        entity_deleted=record.entity_deleted,
        changed_fields=record.changed_fields,
        details=record.details,
    )


@router.get("", response_model=Page[AuditEntry], responses=error_responses(422))
async def list_audit(
    db: DbSession, actor: CurrentActor, params: Annotated[AuditListQuery, Query()]
) -> Page[AuditEntry]:
    """Страница журнала пространства: ``id DESC``, фильтры ``entity_type`` и ``actor_id``."""
    records, has_next = await queries.list_audit(
        db, actor, params, entity_type=params.entity_type, actor_id=params.actor_id
    )
    return Page[AuditEntry](
        items=[_to_entry(record) for record in records],
        page=params.page,
        page_size=params.page_size,
        has_next=has_next,
    )


@router.get("/{entry_id}", response_model=AuditEntry, responses=error_responses(404, 422))
async def get_audit_entry(entry_id: int, db: DbSession, actor: CurrentActor) -> AuditEntry:
    """Запись журнала; чужое пространство, неизвестный и не аудитный ``id`` — 404."""
    return _to_entry(await queries.get_audit_entry(db, actor, entry_id))
