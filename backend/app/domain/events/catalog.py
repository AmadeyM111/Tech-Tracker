"""Каталог событий (plan §4.4, D-7): сущность, попадание в аудит, ленту и историю сделки.

Действия ``user.*`` (R1.0) и действия R1.1 по таблице plan §10.5 (D-41). Белые списки полей:
``fields`` — допустимые имена в ``changed_fields``, ``value_fields`` — допустимые
``changes[].field`` (значения пишутся только для них, BR-2).
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
    PROJECT_UPDATED = "project.updated"
    PROJECT_OWNERSHIP_TRANSFERRED = "project.ownership_transferred"
    PROJECT_ARCHIVED = "project.archived"
    PROJECT_UNARCHIVED = "project.unarchived"
    MEMBER_ADDED = "member.added"
    MEMBER_REMOVED = "member.removed"
    TASK_CREATED = "task.created"
    TASK_DELETED = "task.deleted"
    TASK_RESTORED = "task.restored"
    TASK_UPDATED = "task.updated"
    TASK_UNASSIGNED_MEMBER_REMOVED = "task.unassigned_member_removed"
    COMMENT_CREATED = "comment.created"
    COMMENT_DELETED = "comment.deleted"
    ATTACHMENT_CREATED = "attachment.created"
    ATTACHMENT_DELETED = "attachment.deleted"


@dataclass(frozen=True)
class EventSpec:
    entity_type: EntityType
    audit: bool
    feed: Literal["project", "deal"] | None
    deal_history: bool
    fields: frozenset[str] = frozenset()
    value_fields: frozenset[str] = frozenset()


_USER_AUDITED: Final = EventSpec(
    entity_type=EntityType.USER, audit=True, feed=None, deal_history=False
)


def _feed(entity_type: EntityType, *, audit: bool = False, **kw: frozenset[str]) -> EventSpec:
    return EventSpec(entity_type=entity_type, audit=audit, feed="project", deal_history=False, **kw)


EVENT_CATALOG: Final[Mapping[EventAction, EventSpec]] = {
    EventAction.USER_CREATED: _USER_AUDITED,
    EventAction.USER_BLOCKED: _USER_AUDITED,
    EventAction.USER_UNBLOCKED: _USER_AUDITED,
    EventAction.USER_PASSWORD_RESET: _USER_AUDITED,
    EventAction.USER_SESSIONS_REVOKED: _USER_AUDITED,
    EventAction.USER_ROLE_ASSIGNED: _USER_AUDITED,
    EventAction.USER_ROLE_CHANGED: _USER_AUDITED,
    EventAction.USER_ROLE_REMOVED: _USER_AUDITED,
    EventAction.PROJECT_UPDATED: _feed(
        EntityType.PROJECT, fields=frozenset({"name", "description"})
    ),
    EventAction.PROJECT_OWNERSHIP_TRANSFERRED: _feed(
        EntityType.PROJECT,
        audit=True,
        fields=frozenset({"owner_id"}),
        value_fields=frozenset({"owner_id"}),
    ),
    EventAction.PROJECT_ARCHIVED: _feed(
        EntityType.PROJECT, audit=True, fields=frozenset({"status"})
    ),
    EventAction.PROJECT_UNARCHIVED: _feed(
        EntityType.PROJECT, audit=True, fields=frozenset({"status"})
    ),
    EventAction.MEMBER_ADDED: _feed(EntityType.USER),
    EventAction.MEMBER_REMOVED: _feed(EntityType.USER),
    EventAction.TASK_CREATED: _feed(EntityType.TASK),
    EventAction.TASK_DELETED: _feed(EntityType.TASK),
    EventAction.TASK_RESTORED: _feed(EntityType.TASK),
    EventAction.TASK_UPDATED: _feed(
        EntityType.TASK,
        fields=frozenset({"status", "assignee_id", "due_date", "title", "description"}),
        value_fields=frozenset({"status", "assignee_id", "due_date"}),
    ),
    EventAction.TASK_UNASSIGNED_MEMBER_REMOVED: _feed(
        EntityType.TASK,
        fields=frozenset({"assignee_id"}),
        value_fields=frozenset({"assignee_id"}),
    ),
    EventAction.COMMENT_CREATED: _feed(EntityType.COMMENT),
    EventAction.COMMENT_DELETED: _feed(EntityType.COMMENT),
    EventAction.ATTACHMENT_CREATED: _feed(EntityType.ATTACHMENT),
    EventAction.ATTACHMENT_DELETED: _feed(EntityType.ATTACHMENT),
}
