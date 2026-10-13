"""Запись события в журнал (plan §4.4, D-7, FR-57).

``record_event`` выполняет INSERT в текущей транзакции вызывающего: откат изменения
откатывает и событие (AC-67). Сама функция не фиксирует и не откатывает транзакцию.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, TypedDict
from uuid import UUID

from sqlalchemy import insert

from app.core.clock import utcnow
from app.domain.events.catalog import EVENT_CATALOG, EntityType, EventAction
from app.domain.events.models import DomainEvent

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]


class FieldChange(TypedDict):
    field: str
    old: JsonValue
    new: JsonValue


class UserEventDetails(TypedDict, total=False):
    """Единственный допустимый ``details``; паролей и хешей по типу нет (FR-57)."""

    role_from: str | None
    role_to: str | None


_ALLOWED_DETAILS_KEYS = frozenset(UserEventDetails.__annotations__)


def _validate_details(
    details: Mapping[str, object], entity_type: EntityType
) -> dict[str, str | None]:
    if entity_type is not EntityType.USER:
        raise ValueError(f"details допустим только для entity_type=user, не для {entity_type}")
    unknown = set(details) - _ALLOWED_DETAILS_KEYS
    if unknown:
        raise ValueError(
            f"details допускает только ключи {sorted(_ALLOWED_DETAILS_KEYS)}; "
            f"недопустимые: {sorted(unknown)}"
        )
    checked: dict[str, str | None] = {}
    for key, value in details.items():
        if value is not None and not isinstance(value, str):
            raise ValueError(f"details[{key!r}] должно быть строкой или None")
        checked[key] = value
    return checked


async def record_event(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    actor_id: UUID | None,
    action: EventAction,
    entity_id: UUID,
    changed_fields: Sequence[str] = (),
    project_id: UUID | None = None,
    deal_id: UUID | None = None,
    changes: Sequence[FieldChange] | None = None,
    details: UserEventDetails | None = None,
) -> int:
    """Добавляет строку ``domain_event`` в текущую транзакцию и возвращает её ``id``.

    ``entity_type`` и ``in_audit`` берутся из ``EVENT_CATALOG``; ``actor_id=None`` — «система».
    Неизвестное действие, отсутствие его в каталоге, ``details`` не для ``user`` или с
    ключами кроме ``role_from``/``role_to`` — ``ValueError``, строка не пишется.
    """
    resolved = EventAction(action)  # неизвестное значение → ValueError
    spec = EVENT_CATALOG.get(resolved)
    if spec is None:
        raise ValueError(f"действие {resolved.value!r} отсутствует в каталоге событий")
    checked_details = None if details is None else _validate_details(details, spec.entity_type)

    result = await db.execute(
        insert(DomainEvent)
        .values(
            workspace_id=workspace_id,
            occurred_at=utcnow(),
            actor_id=actor_id,
            entity_type=spec.entity_type.value,
            entity_id=entity_id,
            action=resolved.value,
            changed_fields=list(changed_fields),
            project_id=project_id,
            deal_id=deal_id,
            in_audit=spec.audit,
            changes=None if changes is None else [dict(c) for c in changes],
            details=checked_details,
        )
        .returning(DomainEvent.id)
    )
    return int(result.scalar_one())
