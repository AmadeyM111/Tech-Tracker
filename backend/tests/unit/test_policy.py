"""T70: объектные права MVP, чистые функции (plan §11.5, D-45, D-54, BR-1, BR-11, SC-20).

AC-9, AC-46, AC-47, AC-48, AC-52, AC-54, AC-73, AC-74, AC-99, AC-103, AC-109, AC-110;
FR-9, FR-10, FR-11, FR-14a, FR-14c, FR-15, FR-15a, FR-16, FR-19/19a/19b, FR-20, FR-23, FR-68.

Решение оркестратора по OI-127, вариант (а): БА-участник (не владелец) правит и удаляет
СВОЮ задачу (created_by == assignee_id == actor, как у «Пользователя»); исполнителя
меняет только владелец-БА (FR-19a: TASK_ASSIGN_OTHERS and is_own_project), СМ - участник;
чужие задачи и чужие комментарии - только владелец-БА (СМ - любые).
При выборе (б) правится ТОЛЬКО блок
``test_oi127_*`` и таблицы с пометкой OI-127.

Имена функций - по plan §11.5 (``can_change_task_status``, ``can_change_assignee``,
``can_manage_project``, ``can_read_project_content``). Права на создание проекта - это
``Actor.can(PROJECT_CREATE)`` (отдельной функции в plan нет).
"""

from __future__ import annotations

import ast
import importlib
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROLES = ("TECH_ADMIN", "BUSINESS_ADMIN", "USER", None)
WS = uuid.UUID(int=1)
ME = uuid.UUID(int=100)
OTHER = uuid.UUID(int=200)
OWNER = uuid.UUID(int=300)
PID = uuid.UUID(int=400)
T_ME, T_OTH, T_NONE = "me", "other", "none"


@pytest.fixture(scope="module")
def pol() -> ModuleType:
    return importlib.import_module("app.domain.access.policy")


@pytest.fixture(scope="module")
def roles() -> ModuleType:
    return importlib.import_module("app.domain.access.roles")


def _actor(roles: ModuleType, role: str | None, user_id: uuid.UUID = ME) -> Any:
    return roles.Actor(
        user_id=user_id,
        workspace_id=WS,
        login="u",
        role=None if role is None else roles.Role[role],
        must_change_password=False,
        session_id=b"s",
    )


def _proj(pol: ModuleType, *, owner: uuid.UUID = OWNER, member: bool = True) -> Any:
    return pol.ProjectFacts(project_id=PID, owner_id=owner, actor_is_member=member)


def _uid(tok: str) -> uuid.UUID | None:
    return {T_ME: ME, T_OTH: OTHER, T_NONE: None}[tok]


def _task(
    pol: ModuleType,
    *,
    created_by: uuid.UUID = OTHER,
    assignee: uuid.UUID | None = OTHER,
    parent: uuid.UUID | None = None,
) -> Any:
    return pol.TaskFacts(created_by=created_by, assignee_id=assignee, parent_id=parent)


# --- can_view_project (D-45)
VIEW = [
    ("TECH_ADMIN", True, False),
    ("TECH_ADMIN", False, False),
    (None, True, False),
    (None, False, False),
    ("BUSINESS_ADMIN", True, True),
    ("BUSINESS_ADMIN", False, True),
    ("USER", True, True),
    ("USER", False, False),
]


@pytest.mark.parametrize(
    ("role", "member", "expected"),
    [pytest.param(*r, id=f"{r[0]}-member={r[1]}") for r in VIEW],
)
def test_d45_fr17_can_view_project(pol, roles, role, member, expected) -> None:
    a, p = _actor(roles, role), _proj(pol, member=member)
    assert pol.can_view_project(a, p) is expected


READ = [
    ("TECH_ADMIN", True, False),
    (None, True, False),
    ("BUSINESS_ADMIN", True, True),
    ("BUSINESS_ADMIN", False, False),
    ("USER", True, True),
    ("USER", False, False),
]


@pytest.mark.parametrize(
    ("role", "member", "expected"),
    [pytest.param(*r, id=f"{r[0]}-member={r[1]}") for r in READ],
)
def test_fr17_ac55_can_read_project_content(pol, roles, role, member, expected) -> None:
    a, p = _actor(roles, role), _proj(pol, member=member)
    assert pol.can_read_project_content(a, p) is expected


# --- создание проекта
@pytest.mark.parametrize(
    ("role", "expected"),
    [
        ("TECH_ADMIN", False),
        (None, False),
        ("BUSINESS_ADMIN", True),
        ("USER", False),
    ],
    ids=lambda v: str(v),
)
def test_br1_create_project_capability(roles, role, expected) -> None:
    assert _actor(roles, role).can(roles.Capability.PROJECT_CREATE) is expected


# --- is_own_project (D-54, Q-6)
OWN = [
    ("BUSINESS_ADMIN", True, True, True),
    # 002/AC-13 (FR-9, 002 §5.3 п.3): правило D-54 отменено, БА действует по участию
    ("BUSINESS_ADMIN", False, True, True),
    ("BUSINESS_ADMIN", False, False, False),
    ("USER", True, True, False),
    ("USER", False, True, False),
    ("TECH_ADMIN", True, True, False),
    (None, True, True, False),
]


@pytest.mark.parametrize(
    ("role", "is_owner", "member", "expected"),
    [pytest.param(*r, id=f"{r[0]}-owner={r[1]}-member={r[2]}") for r in OWN],
)
def test_ac48_is_own_project(pol, roles, role, is_owner, member, expected) -> None:
    a = _actor(roles, role)
    p = _proj(pol, owner=ME if is_owner else OWNER, member=member)
    assert pol.is_own_project(a, p) is expected


# --- can_edit_task_fully / can_delete_task
# (роль, я_владелец, участник, created_by_me, assignee_me, ожидание)
FULLY = [
    # ТА и без роли
    ("TECH_ADMIN", True, True, T_ME, T_ME, False),
    (None, True, True, T_ME, T_ME, False),
    # БА-владелец: любые задачи
    ("BUSINESS_ADMIN", True, True, T_OTH, T_OTH, True),
    ("BUSINESS_ADMIN", True, True, T_ME, T_OTH, True),
    ("BUSINESS_ADMIN", True, True, T_OTH, T_NONE, True),
    # БА-участник, не владелец: любые задачи проекта (002/AC-13, FR-9; OI-127 (а) и D-54 отменены)
    ("BUSINESS_ADMIN", False, True, T_OTH, T_OTH, True),  # чужая: можно
    ("BUSINESS_ADMIN", False, True, T_OTH, T_ME, True),
    ("BUSINESS_ADMIN", False, True, T_ME, T_ME, True),
    ("BUSINESS_ADMIN", False, True, T_ME, T_OTH, True),
    ("BUSINESS_ADMIN", False, True, T_ME, T_NONE, True),
    ("BUSINESS_ADMIN", False, True, T_OTH, T_NONE, True),
    ("BUSINESS_ADMIN", False, False, T_ME, T_ME, False),  # не участник: нельзя
    ("BUSINESS_ADMIN", False, False, T_OTH, T_NONE, False),  # не участник (прежде строка СМ)
    # СМ: любые задачи, где участник
    # Пользователь: только своя (автор == исполнитель == я) и участник
    ("USER", False, True, T_ME, T_ME, True),
    ("USER", False, True, T_OTH, T_ME, False),  # назначили мне: только статус
    ("USER", False, True, T_ME, T_OTH, False),  # создал я, исполнитель другой
    ("USER", False, False, T_ME, T_ME, False),
    ("USER", False, True, T_OTH, T_OTH, False),
    ("USER", False, True, T_ME, T_NONE, False),
]


def _fully_id(r: tuple[Any, ...]) -> str:
    return f"{r[0]}-owner={r[1]}-member={r[2]}-created_by={r[3]}-assignee={r[4]}"


@pytest.mark.parametrize(
    ("role", "is_owner", "member", "cb", "asg", "expected"),
    [pytest.param(*r, id=_fully_id(r)) for r in FULLY],
)
def test_ac46_can_edit_task_fully_and_delete(
    pol, roles, role, is_owner, member, cb, asg, expected
) -> None:
    a = _actor(roles, role)
    p = _proj(pol, owner=ME if is_owner else OWNER, member=member)
    t = _task(pol, created_by=ME if cb == T_ME else OTHER, assignee=_uid(asg))
    assert pol.can_edit_task_fully(a, p, t) is expected
    # AC-99: права удаления == права полной правки (FR-19)
    assert pol.can_delete_task(a, p, t) is expected


def test_fully_unassigned_task_user_cannot(pol, roles) -> None:
    a = _actor(roles, "USER")
    t = _task(pol, created_by=ME, assignee=None)
    assert pol.can_edit_task_fully(a, _proj(pol), t) is False


def test_fully_unassigned_task_owner_ba_can(pol, roles) -> None:
    a = _actor(roles, "BUSINESS_ADMIN")
    t = _task(pol, created_by=OTHER, assignee=None)
    assert pol.can_edit_task_fully(a, _proj(pol, owner=ME), t) is True


# --- can_change_task_status (FR-19b)
STATUS = [
    ("TECH_ADMIN", False, True, T_OTH, T_ME, False),
    (None, False, True, T_OTH, T_ME, False),
    ("USER", False, True, T_OTH, T_ME, True),  # назначена мне
    ("USER", False, True, T_OTH, T_OTH, False),
    ("USER", False, False, T_OTH, T_ME, False),  # не участник
    ("USER", False, True, T_ME, T_ME, True),
    ("BUSINESS_ADMIN", False, True, T_OTH, T_ME, True),  # исполнитель: статус можно
    ("BUSINESS_ADMIN", False, True, T_OTH, T_OTH, True),  # 002/AC-13: чужая - можно
    ("BUSINESS_ADMIN", False, True, T_ME, T_OTH, True),  # 002/AC-13
    ("BUSINESS_ADMIN", False, False, T_OTH, T_ME, False),
    ("BUSINESS_ADMIN", True, True, T_OTH, T_OTH, True),  # владелец
    (
        "BUSINESS_ADMIN",
        False,
        False,
        T_OTH,
        T_OTH,
        False,
    ),  # не участник (прежде строка СМ, 002/AC-15)
]


@pytest.mark.parametrize(
    ("role", "is_owner", "member", "cb", "asg", "expected"),
    [pytest.param(*r, id=_fully_id(r)) for r in STATUS],
)
def test_ac47_can_change_task_status(pol, roles, role, is_owner, member, cb, asg, expected) -> None:
    a = _actor(roles, role)
    p = _proj(pol, owner=ME if is_owner else OWNER, member=member)
    t = _task(pol, created_by=ME if cb == T_ME else OTHER, assignee=_uid(asg))
    assert pol.can_change_task_status(a, p, t) is expected


# --- can_change_assignee (FR-19a)
ASSIGNEE = [
    ("TECH_ADMIN", True, True, T_ME, T_ME, False),
    (None, True, True, T_ME, T_ME, False),
    ("USER", False, True, T_ME, T_ME, False),  # BR-1: пользователь не меняет исполнителя
    ("BUSINESS_ADMIN", True, True, T_OTH, T_OTH, True),
    # 002/AC-13, AC-14 (FR-9): БА-участник меняет исполнителя любой задачи проекта
    ("BUSINESS_ADMIN", False, True, T_OTH, T_OTH, True),
    ("BUSINESS_ADMIN", False, True, T_OTH, T_ME, True),
    ("BUSINESS_ADMIN", False, True, T_ME, T_ME, True),
    ("BUSINESS_ADMIN", False, True, T_ME, T_OTH, True),
    ("BUSINESS_ADMIN", False, True, T_ME, T_NONE, True),
    ("BUSINESS_ADMIN", False, False, T_OTH, T_OTH, False),  # 002/AC-15: не участник
    ("BUSINESS_ADMIN", True, True, T_OTH, T_NONE, True),
]


@pytest.mark.parametrize(
    ("role", "is_owner", "member", "cb", "asg", "expected"),
    [pytest.param(*r, id=_fully_id(r)) for r in ASSIGNEE],
)
def test_ac47_can_change_assignee(pol, roles, role, is_owner, member, cb, asg, expected) -> None:
    a = _actor(roles, role)
    p = _proj(pol, owner=ME if is_owner else OWNER, member=member)
    t = _task(pol, created_by=ME if cb == T_ME else OTHER, assignee=_uid(asg))
    assert pol.can_change_assignee(a, p, t) is expected


# --- can_create_task (FR-19a, FR-20, BR-1)
# (роль, участник, исполнитель: me/other/None, ожидание)
CREATE = [
    ("TECH_ADMIN", True, "me", False),
    (None, True, "me", False),
    ("USER", True, "me", True),
    ("USER", True, "other", False),  # создание задачи другому - нет
    ("USER", True, None, False),
    ("USER", False, "me", False),
    ("BUSINESS_ADMIN", True, "me", True),
    ("BUSINESS_ADMIN", True, "other", True),
    ("BUSINESS_ADMIN", True, None, True),
    ("BUSINESS_ADMIN", False, "me", False),
]


@pytest.mark.parametrize(
    ("role", "member", "asg", "expected"),
    [pytest.param(*r, id=f"{r[0]}-member={r[1]}-assignee={r[2]}") for r in CREATE],
)
def test_ac9_can_create_task(pol, roles, role, member, asg, expected) -> None:
    a = _actor(roles, role)
    assignee = {"me": ME, "other": OTHER, None: None}[asg]
    assert pol.can_create_task(a, _proj(pol, member=member), assignee) is expected


# --- can_create_subtask (SC-20)
# (роль, я_владелец, parent.created_by, parent.assignee, assignee подзадачи, ожидание)
SUB = [
    ("TECH_ADMIN", True, T_ME, T_ME, "me", False),
    (None, True, T_ME, T_ME, "me", False),
    # Пользователь: подзадача своей задачи себе - да; другому - нет (SC-20)
    ("USER", False, T_ME, T_ME, "me", True),
    ("USER", False, T_ME, T_ME, "other", False),
    ("USER", False, T_ME, T_ME, None, False),
    # родитель назначен мне (создал другой): себе - да, другому - нет
    ("USER", False, T_OTH, T_ME, "me", True),
    ("USER", False, T_OTH, T_ME, "other", False),
    # родитель чужой
    ("USER", False, T_OTH, T_OTH, "me", False),
    # БА-владелец: любая подзадача любому
    ("BUSINESS_ADMIN", True, T_OTH, T_OTH, "other", True),
    ("BUSINESS_ADMIN", True, T_OTH, T_OTH, None, True),
    # БА-участник не владелец (002/AC-13): подзадача к любой задаче проекта, любому исполнителю
    ("BUSINESS_ADMIN", False, T_OTH, T_OTH, "me", True),
    ("BUSINESS_ADMIN", False, T_OTH, T_ME, "me", True),
    (
        "BUSINESS_ADMIN",
        False,
        T_OTH,
        T_ME,
        "other",
        True,
    ),  # исполнитель родителя + TASK_ASSIGN_OTHERS
    ("BUSINESS_ADMIN", False, T_ME, T_OTH, "other", True),  # 002/AC-13
    ("BUSINESS_ADMIN", False, T_ME, T_ME, "other", True),
    ("BUSINESS_ADMIN", False, T_ME, T_NONE, "me", True),  # 002/AC-13
    ("BUSINESS_ADMIN", False, T_OTH, T_OTH, "other", True),  # прежде строка СМ (002/AC-13)
]


@pytest.mark.parametrize(
    ("role", "is_owner", "pcb", "pasg", "sub_asg", "expected"),
    [
        pytest.param(
            *r, id=f"{r[0]}-owner={r[1]}-parent_cb={r[2]}-parent_asg={r[3]}-sub_asg={r[4]}"
        )
        for r in SUB
    ],
)
def test_sc20_can_create_subtask(pol, roles, role, is_owner, pcb, pasg, sub_asg, expected) -> None:
    a = _actor(roles, role)
    p = _proj(pol, owner=ME if is_owner else OWNER, member=True)
    parent = _task(pol, created_by=ME if pcb == T_ME else OTHER, assignee=_uid(pasg))
    assignee = {"me": ME, "other": OTHER, None: None}[sub_asg]
    assert pol.can_create_subtask(a, p, parent, assignee) is expected


def test_sc20_subtask_requires_membership(pol, roles) -> None:
    """001/SC-20, обращён по 002/AC-13, AC-15: БА, не участник проекта, подзадачу не создаёт."""
    a = _actor(roles, "BUSINESS_ADMIN")
    p = _proj(pol, member=False)
    parent = _task(pol, created_by=ME, assignee=ME)
    assert pol.can_create_subtask(a, p, parent, ME) is False


# --- комментарии (FR-23)
@pytest.mark.parametrize(
    ("role", "author_me", "expected"),
    [
        ("TECH_ADMIN", True, False),
        (None, True, False),
        ("USER", True, True),
        ("USER", False, False),
        ("BUSINESS_ADMIN", True, True),
        ("BUSINESS_ADMIN", False, False),
    ],
    ids=lambda v: str(v),
)
def test_ac103_can_edit_comment(pol, roles, role, author_me, expected) -> None:
    a = _actor(roles, role)
    assert pol.can_edit_comment(a, ME if author_me else OTHER) is expected


# (роль, я_владелец, участник, автор_я, ожидание)
DEL_C = [
    ("TECH_ADMIN", True, True, True, False),
    (None, True, True, True, False),
    ("USER", False, True, True, True),
    ("USER", False, True, False, False),
    ("USER", False, False, True, False),  # не участник
    ("BUSINESS_ADMIN", True, True, False, True),  # владелец: чужие можно
    ("BUSINESS_ADMIN", True, True, True, True),
    ("BUSINESS_ADMIN", False, True, True, True),  # свой комментарий
    # 002/AC-13 (FR-9): БА-участник не владелец удаляет чужой комментарий (было False, D-54)
    ("BUSINESS_ADMIN", False, True, False, True),
    ("BUSINESS_ADMIN", False, False, False, False),
]


@pytest.mark.parametrize(
    ("role", "is_owner", "member", "author_me", "expected"),
    [pytest.param(*r, id=f"{r[0]}-owner={r[1]}-member={r[2]}-author_me={r[3]}") for r in DEL_C],
)
def test_ac103_can_delete_comment(pol, roles, role, is_owner, member, author_me, expected) -> None:
    a = _actor(roles, role)
    p = _proj(pol, owner=ME if is_owner else OWNER, member=member)
    assert pol.can_delete_comment(a, p, ME if author_me else OTHER) is expected


# --- проект: правка, владение, удаление
# (роль, я_владелец, участник, ожидание)
MANAGE = [
    ("TECH_ADMIN", True, True, False),
    (None, True, True, False),
    ("USER", True, True, False),
    ("USER", False, True, False),
    ("BUSINESS_ADMIN", True, True, True),
    # 002/AC-11, AC-12 (FR-8): БА управляет любым проектом, участие и владение не нужны
    ("BUSINESS_ADMIN", False, True, True),
    ("BUSINESS_ADMIN", False, False, True),
]


@pytest.mark.parametrize(
    ("role", "is_owner", "member", "expected"),
    [pytest.param(*r, id=f"{r[0]}-owner={r[1]}-member={r[2]}") for r in MANAGE],
)
def test_ac48_can_manage_project_and_members(pol, roles, role, is_owner, member, expected) -> None:
    """Правка (FR-14c), передача владения (FR-14a), удаление (FR-16), состав (FR-15)."""
    a = _actor(roles, role)
    p = _proj(pol, owner=ME if is_owner else OWNER, member=member)
    assert pol.can_manage_project(a, p) is expected
    assert pol.can_manage_members(a, p) is expected


@pytest.mark.parametrize(
    ("role", "is_owner", "target_me", "expected"),
    [
        ("BUSINESS_ADMIN", True, False, True),
        ("BUSINESS_ADMIN", True, True, True),  # 002/AC-11 (FR-8): БА добавляет себя
        ("BUSINESS_ADMIN", False, False, True),  # 002/AC-11: любой проект
        ("BUSINESS_ADMIN", False, True, True),  # 002/AC-11: себя в любой проект
        ("USER", False, False, False),
        ("TECH_ADMIN", False, False, False),
        (None, False, False, False),
    ],
    ids=lambda v: str(v),
)
def test_ac73_can_add_member(pol, roles, role, is_owner, target_me, expected) -> None:
    a = _actor(roles, role)
    p = _proj(pol, owner=ME if is_owner else OWNER, member=True)
    assert pol.can_add_member(a, p, ME if target_me else OTHER) is expected


@pytest.mark.parametrize(
    ("role", "is_owner", "member", "expected"),
    [
        ("USER", False, True, True),
        ("USER", False, False, False),
        ("BUSINESS_ADMIN", True, True, False),  # владелец не выходит (FR-15a)
        ("BUSINESS_ADMIN", False, True, True),
        ("BUSINESS_ADMIN", False, False, False),  # не участник (прежде строка СМ)
        ("TECH_ADMIN", False, True, False),
        (None, False, True, False),
    ],
    ids=lambda v: str(v),
)
def test_ac53_fr15a_can_remove_self(pol, roles, role, is_owner, member, expected) -> None:
    a = _actor(roles, role)
    p = _proj(pol, owner=ME if is_owner else OWNER, member=member)
    assert pol.can_remove_self(a, p) is expected


# --- бывший кейс OI-127 (а): обращён по 002/AC-13, AC-14 (FR-9); правило D-54 отменено
def test_oi127_ba_member_not_owner_own_task_allowed(pol, roles) -> None:
    """002/AC-13: БА-участник правит, удаляет и переназначает свою задачу (исполнителя - тоже)."""
    a = _actor(roles, "BUSINESS_ADMIN")
    p = _proj(pol, owner=OWNER, member=True)
    own = _task(pol, created_by=ME, assignee=ME)
    assert pol.can_edit_task_fully(a, p, own) is True
    assert pol.can_delete_task(a, p, own) is True
    assert pol.can_change_assignee(a, p, own) is True


@pytest.mark.parametrize("assignee", [OTHER, None])
def test_oi127_ba_member_not_owner_created_but_not_assignee_denied(pol, roles, assignee) -> None:
    """Обращён по 002/AC-13, AC-14: созданную им задачу с другим/без исполнителя БА-участник
    правит, удаляет и переназначает."""
    a = _actor(roles, "BUSINESS_ADMIN")
    p = _proj(pol, owner=OWNER, member=True)
    t = _task(pol, created_by=ME, assignee=assignee)
    assert pol.can_edit_task_fully(a, p, t) is True
    assert pol.can_delete_task(a, p, t) is True
    assert pol.can_change_assignee(a, p, t) is True


def test_oi127_ba_member_not_owner_assigned_but_not_author_denied(pol, roles) -> None:
    """Обращён по 002/AC-13: назначенную ему чужую задачу БА-участник правит и удаляет."""
    a = _actor(roles, "BUSINESS_ADMIN")
    p = _proj(pol, owner=OWNER, member=True)
    t = _task(pol, created_by=OTHER, assignee=ME)
    assert pol.can_edit_task_fully(a, p, t) is True
    assert pol.can_delete_task(a, p, t) is True


def test_oi127_ba_member_not_owner_foreign_task_allowed(pol, roles) -> None:
    """Обращён по 002/AC-13, AC-14: чужую задачу БА-участник правит, переназначает, удаляет;
    не участник (002/AC-15) - ничего."""
    a = _actor(roles, "BUSINESS_ADMIN")
    p = _proj(pol, owner=OWNER, member=True)
    foreign = _task(pol, created_by=OTHER, assignee=OTHER)
    assert pol.can_edit_task_fully(a, p, foreign) is True
    assert pol.can_change_assignee(a, p, foreign) is True
    assert pol.can_delete_task(a, p, foreign) is True
    outside = _proj(pol, owner=OWNER, member=False)
    assert pol.can_edit_task_fully(a, outside, foreign) is False
    assert pol.can_change_assignee(a, outside, foreign) is False
    assert pol.can_delete_task(a, outside, foreign) is False


def test_oi127_ba_member_not_owner_foreign_comment_deletable(pol, roles) -> None:
    """Обращён по 002/AC-13 (FR-9): БА-участник не владелец удаляет чужой комментарий;
    не-участник по-прежнему нет (002/AC-15)."""
    a = _actor(roles, "BUSINESS_ADMIN")
    p = _proj(pol, owner=OWNER, member=True)
    assert pol.can_delete_comment(a, p, OTHER) is True
    outside = _proj(pol, owner=OWNER, member=False)
    assert pol.can_delete_comment(a, outside, OTHER) is False


# --- чистота (архитектурные ограничения)
_APP = Path(__file__).resolve().parents[2] / "app"
_FORBIDDEN = ("sqlalchemy", "fastapi", "app.db")


@pytest.mark.parametrize("rel", ["domain/access/policy.py", "domain/access/recipients.py"])
def test_pure_module_has_no_infra_imports(rel: str) -> None:
    path = _APP / rel
    assert path.is_file(), f"нет модуля {rel}"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bad: list[str] = []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [n.name for n in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [node.module]
        for n in names:
            if any(n == f or n.startswith(f + ".") for f in _FORBIDDEN):
                bad.append(n)
    assert bad == []
