"""Объектные права MVP: чистые функции без БД (plan §11.5, D-45, D-54, BR-1, BR-11, SC-20).

ТА и пользователь без роли — везде ``False``. Роль берётся из ``Actor.role``; доступ к
разделу и общие возможности — из матрицы ``roles.ROLE_CAPABILITIES`` через ``Actor.can``.

Права БА определяются участием в проекте, а не владением (002 §5.3 п.3, FR-9, D-2):
БА-участник правит, переназначает и удаляет любые задачи проекта. Правило OI-127 (а) и
D-54 («свой проект» БА = владелец) отменены. Исполнителя меняет БА-участник или СМ-участник
(FR-19a). Правило полной правки живёт в одной функции ``can_edit_task_fully``;
``can_delete_task`` считается через неё.
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
    """БА — участник проекта (002/FR-9, D-2); СМ — участник; остальные — нет.

    Переходная форма: ``MIXED`` убирается в R3-T11.
    """
    if a.role in (Role.BUSINESS_ADMIN, Role.MIXED):
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
    """Полная правка (FR-19): П — только свою задачу, БА-участник — любую (002/FR-9).

    Переходная форма: ``MIXED`` убирается в R3-T11.
    """
    if a.role == Role.USER:
        return p.actor_is_member and t.created_by == a.user_id and t.assignee_id == a.user_id
    if a.role in (Role.BUSINESS_ADMIN, Role.MIXED):
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
    """FR-19a: БА и СМ — участник проекта; ``t`` в правиле не участвует."""
    del t  # сигнатура по plan §11.5
    return a.can(Capability.TASK_ASSIGN_OTHERS) and is_own_project(a, p)


def can_delete_task(a: Actor, p: ProjectFacts, t: TaskFacts) -> bool:
    return can_edit_task_fully(a, p, t)


def can_edit_comment(a: Actor, author_id: UUID) -> bool:
    """Свой комментарий (FR-23); участие проверяет сервис."""
    return a.can(Capability.BUSINESS_ACCESS) and author_id == a.user_id


def can_delete_comment(a: Actor, p: ProjectFacts, author_id: UUID) -> bool:
    """Свой или любой комментарий проекта для БА-участника (002/FR-9, AC-13).

    Переходная форма: ``MIXED`` убирается в R3-T11.
    """
    if not (a.can(Capability.BUSINESS_ACCESS) and p.actor_is_member):
        return False
    return author_id == a.user_id or a.role in (Role.BUSINESS_ADMIN, Role.MIXED)


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
