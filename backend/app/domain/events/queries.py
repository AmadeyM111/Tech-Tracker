"""Выборки журнала для раздела «Журнал аудита» (plan §4.4, D-7, D-8, FR-41, ADR-0006).

Каждая выборка фильтруется ``workspace_id = actor.workspace_id`` и ``in_audit``; порядок —
``id DESC`` (``id`` уникален, страницы не пересекаются и не теряют строки). Строки отдаются как
``AuditRecord``: полей ``changes`` здесь нет (BR-2), ``details`` — только для
``entity_type = user`` и только ключи ``UserEventDetails`` (FR-57).

Логины авторов и существование пользователей-сущностей читаются ОДНИМ запросом на страницу
(``IN`` по идентификаторам страницы): число SQL не зависит от размера страницы.

``entity_deleted`` — «объекта больше нет» (FR-25b):

* ``entity_type = user`` — нет членства пользователя в пространстве актора;
* остальные типы (project/task/comment/attachment/stage/deal) таблиц в R1.0 не имеют, объекта
  нет по определению хранения, но и «удалённым» его признать нельзя: возвращается ``False``.
  TODO(R1.1+): проверять существование по таблицам проектов, задач, комментариев, вложений,
  стадий и сделок вместе с их появлением (одним батчем на тип).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.core.errors import Forbidden, NotFound
from app.core.pagination import PageParams, paginate
from app.domain.access.roles import Actor, Capability
from app.domain.events.catalog import EntityType
from app.domain.events.models import DomainEvent
from app.domain.events.writer import UserEventDetails
from app.domain.users.models import AppUser
from app.domain.workspaces.models import WorkspaceMember

logger = logging.getLogger(__name__)

_ENTITY_TYPES: Final = frozenset(t.value for t in EntityType)
_DETAILS_KEYS: Final = frozenset(UserEventDetails.__annotations__)
_MAX_ENTRY_ID: Final = 2**63 - 1  # bigint: больше такого идентификатора не существует


@dataclass(frozen=True)
class AuditRecord:
    """Запись журнала для представления «аудит»; без значений бизнес-сущностей (BR-2)."""

    id: int
    occurred_at: datetime
    actor_id: UUID | None
    actor_login: str | None
    action: str
    entity_type: str
    entity_id: UUID
    entity_deleted: bool
    changed_fields: list[str]
    details: dict[str, str | None] | None


def _audit_select() -> Select[DomainEvent]:
    """Выборка записей аудита пространства: только колонки представления (BR-2).

    ``changes`` (значения бизнес-сущностей), ``project_id``, ``deal_id``, ``in_audit`` и
    ``workspace_id`` из БД не читаются; обращение к ним — ``InvalidRequestError`` (raiseload).
    Предикат ``in_audit`` без ``IS true``: совпадает с предикатом частичного индекса
    ``ix_domain_event_workspace_id_id_audit``.
    """
    return select(DomainEvent).options(
        load_only(
            DomainEvent.id,
            DomainEvent.occurred_at,
            DomainEvent.actor_id,
            DomainEvent.action,
            DomainEvent.entity_type,
            DomainEvent.entity_id,
            DomainEvent.changed_fields,
            DomainEvent.details,
            raiseload=True,
        )
    )


def _require_view(actor: Actor) -> None:
    if not actor.can(Capability.VIEW_AUDIT):
        raise Forbidden()


def _user_details(raw: dict[str, object] | None) -> dict[str, str | None] | None:
    """Только допустимые ключи и строковые значения; ``None`` остаётся ``None``."""
    if raw is None:
        return None
    return {
        key: value
        for key, value in raw.items()
        if key in _DETAILS_KEYS and (value is None or isinstance(value, str))
    }


async def _to_records(
    db: AsyncSession, workspace_id: UUID, events: Iterable[DomainEvent]
) -> list[AuditRecord]:
    """Один батч: логины авторов и существование пользователей-сущностей пространства."""
    rows: list[DomainEvent] = []
    for event in events:
        if event.entity_type not in _ENTITY_TYPES:
            # откат кода к версии без нового типа (D-41): строку пропускаем, значения не логируем
            logger.warning(
                "domain_event id=%s: неизвестный entity_type=%r, запись пропущена",
                event.id,
                event.entity_type,
            )
            continue
        rows.append(event)
    wanted: set[UUID] = set()
    for event in rows:
        if event.actor_id is not None:
            wanted.add(event.actor_id)
        if event.entity_type == EntityType.USER.value:
            wanted.add(event.entity_id)
    logins: dict[UUID, str] = {}
    if wanted:
        found = await db.execute(
            select(AppUser.id, AppUser.login_display)
            .join(WorkspaceMember, WorkspaceMember.user_id == AppUser.id)
            .where(
                WorkspaceMember.workspace_id == workspace_id,
                AppUser.id.in_(wanted),
            )
        )
        logins = {row.id: row.login_display for row in found}

    records: list[AuditRecord] = []
    for event in rows:
        is_user = event.entity_type == EntityType.USER.value
        records.append(
            AuditRecord(
                id=event.id,
                occurred_at=event.occurred_at,
                actor_id=event.actor_id,
                actor_login=None if event.actor_id is None else logins.get(event.actor_id),
                action=event.action,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                entity_deleted=is_user and event.entity_id not in logins,
                changed_fields=list(event.changed_fields),
                details=_user_details(event.details) if is_user else None,
            )
        )
    return records


async def list_audit(
    db: AsyncSession,
    actor: Actor,
    params: PageParams,
    *,
    entity_type: EntityType | None = None,
    actor_id: UUID | None = None,
) -> tuple[list[AuditRecord], bool]:
    """Страница журнала аудита пространства актора, ``id DESC``; второй элемент — ``has_next``.

    Строки с неизвестным ``entity_type`` пропускаются: страница может быть короче
    ``page_size``; ``has_next`` считается по «сырой» выборке, поэтому соседние строки
    не теряются и не дублируются.
    """
    _require_view(actor)
    stmt = _audit_select().where(
        DomainEvent.workspace_id == actor.workspace_id,
        DomainEvent.in_audit,
    )
    if entity_type is not None:
        stmt = stmt.where(DomainEvent.entity_type == entity_type.value)
    if actor_id is not None:
        stmt = stmt.where(DomainEvent.actor_id == actor_id)
    events, has_next = await paginate(db, stmt.order_by(DomainEvent.id.desc()), params)
    return await _to_records(db, actor.workspace_id, events), has_next


async def get_audit_entry(db: AsyncSession, actor: Actor, entry_id: int) -> AuditRecord:
    """Запись по ``id``; чужая, несуществующая, не аудитная и с типом вне ``EntityType`` — 404."""
    _require_view(actor)
    if not 0 < entry_id <= _MAX_ENTRY_ID:
        raise NotFound()
    event = (
        await db.scalars(
            _audit_select().where(
                DomainEvent.id == entry_id,
                DomainEvent.workspace_id == actor.workspace_id,
                DomainEvent.in_audit,
            )
        )
    ).one_or_none()
    if event is None:
        raise NotFound()
    records = await _to_records(db, actor.workspace_id, [event])
    if not records:  # entity_type вне EntityType: запись нечитаема этой версией (D-41)
        raise NotFound()
    return records[0]
