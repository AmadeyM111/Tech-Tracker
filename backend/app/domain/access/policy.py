"""Объектные права MVP: чистые функции без БД (plan §11.5, D-45, D-54, BR-1, BR-11, SC-20).

ТА и пользователь без роли — везде ``False``. Роль берётся из ``Actor.role``; доступ к
разделу и общие возможности — из матрицы ``roles.ROLE_CAPABILITIES`` через ``Actor.can``.

Решение по OI-127 (вариант «а»): БА-участник, не владелец, правит и удаляет СВОЮ задачу
(автор и исполнитель — он); чужие задачи — только владелец-БА, СМ — любые. Правило живёт
в одной функции ``can_edit_task_fully``; ``can_delete_task`` считается через неё.
Исполнителя меняет только владелец-БА или СМ-участник (FR-19a).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.domain.access.roles import Actor, Capability, Role


@dataclass(frozen=True, slots=True)
class ProjectFacts:
    project_id: UUID
    owner_id: UUID
    actor_is_member: bool


@dataclass(frozen=True, slots=True)
class TaskFacts:
    created_by: UUID
    assignee_id: UUID | None
    parent_id: UUID | None


def _is_owner(a: Actor, p: ProjectFacts) -> bool:
    return p.owner_id == a.user_id


def is_own_project(a: Actor, p: ProjectFacts) -> bool:
    """БА — владелец проекта (D-54); СМ — участник; остальные — нет."""
    if a.role == Role.BUSINESS_ADMIN:
        return _is_owner(a, p)
    if a.role == Role.MIXED:
        return p.actor_is_member
    return False


def can_view_project(a: Actor, p: ProjectFacts) -> bool:
    """Карточка проекта: БА и СМ — любой проект пространства, «Пользователь» — свой."""
    if a.role in (Role.BUSINESS_ADMIN, Role.MIXED):
        return True
    return a.role == Role.USER and p.actor_is_member


def can_read_project_content(a: Actor, p: ProjectFacts) -> bool:
    return a.can(Capability.BUSINESS_ACCESS) and p.actor_is_member


def can_edit_task_fully(a: Actor, p: ProjectFacts, t: TaskFacts) -> bool:
    """Полная правка (FR-19): правило БА по OI-127 (а) — только здесь."""
    if a.role == Role.USER:
        return p.actor_is_member and t.created_by == a.user_id and t.assignee_id == a.user_id
    if a.role == Role.BUSINESS_ADMIN:
        return is_own_project(a, p) or (
            p.actor_is_member and t.created_by == a.user_id and t.assignee_id == a.user_id
        )
    if a.role == Role.MIXED:
        return p.actor_is_member
    return False


def can_change_task_status(a: Actor, p: ProjectFacts, t: TaskFacts) -> bool:
    """Статус (FR-19b): полная правка либо участник-исполнитель."""
    if can_edit_task_fully(a, p, t):
        return True
    return a.can(Capability.BUSINESS_ACCESS) and p.actor_is_member and t.assignee_id == a.user_id


def can_create_task(a: Actor, p: ProjectFacts, assignee_id: UUID | None) -> bool:
    """Создание задачи (BR-1): себе — любой участник, другому/без исполнителя — БА и СМ."""
    if not (a.can(Capability.BUSINESS_ACCESS) and p.actor_is_member):
        return False
    return assignee_id == a.user_id or a.can(Capability.TASK_ASSIGN_OTHERS)


def can_create_subtask(
    a: Actor, p: ProjectFacts, parent: TaskFacts, assignee_id: UUID | None
) -> bool:
    """Подзадача (SC-20): подчиняется правилам создания задачи плюс доступ к родителю."""
    return can_create_task(a, p, assignee_id) and (
        can_edit_task_fully(a, p, parent) or parent.assignee_id == a.user_id
    )


def can_change_assignee(a: Actor, p: ProjectFacts, t: TaskFacts) -> bool:
    """FR-19a: БА — только владелец проекта, СМ — участник; ``t`` в правиле не участвует."""
    del t  # сигнатура по plan §11.5
    return a.can(Capability.TASK_ASSIGN_OTHERS) and is_own_project(a, p)


def can_delete_task(a: Actor, p: ProjectFacts, t: TaskFacts) -> bool:
    return can_edit_task_fully(a, p, t)


def can_edit_comment(a: Actor, author_id: UUID) -> bool:
    """Свой комментарий (FR-23); участие проверяет сервис."""
    return a.can(Capability.BUSINESS_ACCESS) and author_id == a.user_id


def can_delete_comment(a: Actor, p: ProjectFacts, author_id: UUID) -> bool:
    if not (a.can(Capability.BUSINESS_ACCESS) and p.actor_is_member):
        return False
    return (
        author_id == a.user_id
        or (a.role == Role.BUSINESS_ADMIN and _is_owner(a, p))
        or a.role == Role.MIXED
    )


def can_manage_project(a: Actor, p: ProjectFacts) -> bool:
    """Правка, передача владения, удаление, архив: БА в любом проекте (002/FR-8, D-1).

    Участие и владение не требуются; ``p`` в правиле не участвует.
    """
    del p  # сигнатура по plan §4.2
    return a.can(Capability.PROJECT_MANAGE_ANY)


def can_manage_members(a: Actor, p: ProjectFacts) -> bool:
    return can_manage_project(a, p)


def can_add_member(a: Actor, p: ProjectFacts, user_id: UUID) -> bool:
    """Участники (002/FR-8): БА добавляет любого, в том числе себя; ``user_id`` не участвует."""
    del user_id  # сигнатура по plan §4.2
    return can_manage_members(a, p)


def can_remove_self(a: Actor, p: ProjectFacts) -> bool:
    """Выход из проекта (FR-15a): участник, кроме владельца."""
    return a.can(Capability.BUSINESS_ACCESS) and p.actor_is_member and not _is_owner(a, p)
