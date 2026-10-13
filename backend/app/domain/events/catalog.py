"""Каталог событий (plan §4.4, D-7): сущность, попадание в аудит, ленту и историю сделки.

В R1.0 — только действия ``user.*``; структура готова к остальным действиям из plan §4.4
(добавляются членами ``EventAction`` и записями ``EVENT_CATALOG`` в своих задачах).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal


class EntityType(StrEnum):
    USER = "user"
    PROJECT = "project"
    TASK = "task"
    COMMENT = "comment"
    ATTACHMENT = "attachment"
    STAGE = "stage"
    DEAL = "deal"


class EventAction(StrEnum):
    USER_CREATED = "user.created"
    USER_BLOCKED = "user.blocked"
    USER_UNBLOCKED = "user.unblocked"
    USER_PASSWORD_RESET = "user.password_reset"
    USER_SESSIONS_REVOKED = "user.sessions_revoked"
    USER_ROLE_ASSIGNED = "user.role_assigned"
    USER_ROLE_CHANGED = "user.role_changed"
    USER_ROLE_REMOVED = "user.role_removed"


@dataclass(frozen=True)
class EventSpec:
    entity_type: EntityType
    audit: bool
    feed: Literal["project", "deal"] | None
    deal_history: bool


_USER_AUDITED: Final = EventSpec(
    entity_type=EntityType.USER, audit=True, feed=None, deal_history=False
)

EVENT_CATALOG: Final[Mapping[EventAction, EventSpec]] = {
    EventAction.USER_CREATED: _USER_AUDITED,
    EventAction.USER_BLOCKED: _USER_AUDITED,
    EventAction.USER_UNBLOCKED: _USER_AUDITED,
    EventAction.USER_PASSWORD_RESET: _USER_AUDITED,
    EventAction.USER_SESSIONS_REVOKED: _USER_AUDITED,
    EventAction.USER_ROLE_ASSIGNED: _USER_AUDITED,
    EventAction.USER_ROLE_CHANGED: _USER_AUDITED,
    EventAction.USER_ROLE_REMOVED: _USER_AUDITED,
}
