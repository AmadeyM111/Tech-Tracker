"""T12: матрица Role x Capability (plan §4.5, BR-1, BR-2, BR-11, ADR-0009).

AC-26 (ASSIGN_ROLES: ТА и СМ), AC-39 (MANAGE_ACCOUNTS: ТА и СМ), AC-74/AC-75 (ТА и роль
NULL без бизнес-доступа), AC-11 (BUSINESS_ACCESS у БА/СМ/П); FR-8, FR-9, FR-66, BR-2.

Модуль ``app.domain.access.roles`` импортируется внутри фикстуры: пока его нет, каждый тест
падает отдельно с ImportError, а не ошибкой сбора.

Возможности адресуются по ИМЕНИ члена (``Capability["MANAGE_ACCOUNTS"]``): значения
StrEnum plan не фиксирует.
"""

from __future__ import annotations

import dataclasses
import uuid
from types import ModuleType
from typing import Any

import pytest

ALL_ROLES = ("TECH_ADMIN", "BUSINESS_ADMIN", "MIXED", "USER")
ALL_CAPS = (
    "MANAGE_ACCOUNTS",
    "ASSIGN_ROLES",
    "VIEW_AUDIT",
    "BUSINESS_ACCESS",
    "PROJECT_CREATE",
    "PROJECT_MANAGE_ANY",
    "TASK_ASSIGN_OTHERS",
    "LABELS_MANAGE",
    "CRM_READ",
    "CRM_WRITE",
    "PIPELINE_MANAGE",
)
_TA = {"MANAGE_ACCOUNTS", "ASSIGN_ROLES", "VIEW_AUDIT"}
_BA = {
    "BUSINESS_ACCESS",
    "PROJECT_CREATE",
    "TASK_ASSIGN_OTHERS",
    "LABELS_MANAGE",
    "CRM_READ",
    "CRM_WRITE",
    "PIPELINE_MANAGE",
}
# Таблица записана явно (а не вычислена), чтобы ошибка в реализации не повторялась в тесте.
EXPECTED: dict[str, frozenset[str]] = {
    "TECH_ADMIN": frozenset(_TA),
    "BUSINESS_ADMIN": frozenset(_BA),
    "MIXED": frozenset(_TA | _BA | {"PROJECT_MANAGE_ANY"}),
    "USER": frozenset({"BUSINESS_ACCESS"}),
}
BUSINESS_CAPS = frozenset(_BA | {"PROJECT_MANAGE_ANY"})
CELLS = [(r, c) for r in ALL_ROLES for c in ALL_CAPS]


@pytest.fixture
def roles() -> ModuleType:
    import app.domain.access.roles as module

    return module


# --- перечисления ------------------------------------------------------------------------


def test_fr8_role_values_are_db_strings(roles: ModuleType) -> None:
    assert {r.name: r.value for r in roles.Role} == {
        "TECH_ADMIN": "tech_admin",
        "BUSINESS_ADMIN": "business_admin",
        "MIXED": "mixed",
        "USER": "user",
    }
    # StrEnum: сравнение со строкой из БД работает напрямую
    assert roles.Role("mixed") is roles.Role.MIXED
    assert roles.Role.USER == "user"


def test_fr9_capability_set_is_exactly_plan_list(roles: ModuleType) -> None:
    assert {c.name for c in roles.Capability} == set(ALL_CAPS)


def test_fr66_role_values_match_db_check_constraint(roles: ModuleType) -> None:
    """Значения Role совпадают с допустимыми значениями ``workspace_member.role``."""
    from tests.factories import ROLES

    assert {r.value for r in roles.Role} == set(ROLES)


# --- матрица -----------------------------------------------------------------------------


def test_role_capabilities_covers_every_role(roles: ModuleType) -> None:
    assert set(roles.ROLE_CAPABILITIES.keys()) == set(roles.Role)


@pytest.mark.parametrize(("role", "cap"), CELLS)
def test_br1_matrix_cell(roles: ModuleType, role: str, cap: str) -> None:
    """BR-1/BR-11: каждая клетка Role x Capability."""
    granted = roles.Capability[cap] in roles.ROLE_CAPABILITIES[roles.Role[role]]
    assert granted is (cap in EXPECTED[role]), f"{role} x {cap}"


@pytest.mark.parametrize("role", ALL_ROLES)
def test_br1_role_row_is_exact(roles: ModuleType, role: str) -> None:
    got = {c.name for c in roles.ROLE_CAPABILITIES[roles.Role[role]]}
    assert got == EXPECTED[role]


@pytest.mark.parametrize("cap", sorted(BUSINESS_CAPS))
def test_br2_tech_admin_has_no_business_capability(roles: ModuleType, cap: str) -> None:
    assert roles.Capability[cap] not in roles.ROLE_CAPABILITIES[roles.Role.TECH_ADMIN]


def test_br2_tech_admin_has_only_administrative_capabilities(roles: ModuleType) -> None:
    got = {c.name for c in roles.ROLE_CAPABILITIES[roles.Role.TECH_ADMIN]}
    assert got == _TA
    assert "BUSINESS_ACCESS" not in got


def test_br1_mixed_is_union_of_admin_roles_plus_manage_any(roles: ModuleType) -> None:
    caps = roles.ROLE_CAPABILITIES
    ta, ba = caps[roles.Role.TECH_ADMIN], caps[roles.Role.BUSINESS_ADMIN]
    mixed = caps[roles.Role.MIXED]
    assert mixed == ta | ba | {roles.Capability.PROJECT_MANAGE_ANY}
    assert roles.Capability.PROJECT_MANAGE_ANY not in ba
    assert roles.Capability.PROJECT_MANAGE_ANY not in ta


def test_br1_user_only_business_access(roles: ModuleType) -> None:
    """Пользователь: в матрице только доступ к разделу (свои задачи — policy R1.1)."""
    assert roles.ROLE_CAPABILITIES[roles.Role.USER] == frozenset({roles.Capability.BUSINESS_ACCESS})


def test_br11_user_cannot_assign_others_manage_labels_or_crm(roles: ModuleType) -> None:
    user = roles.ROLE_CAPABILITIES[roles.Role.USER]
    for name in ("TASK_ASSIGN_OTHERS", "LABELS_MANAGE", "CRM_READ", "CRM_WRITE", "PIPELINE_MANAGE"):
        assert roles.Capability[name] not in user


def test_ac26_ac39_account_capabilities_only_ta_and_mixed(roles: ModuleType) -> None:
    for cap in ("MANAGE_ACCOUNTS", "ASSIGN_ROLES", "VIEW_AUDIT"):
        holders = {
            r.name for r in roles.Role if roles.Capability[cap] in roles.ROLE_CAPABILITIES[r]
        }
        assert holders == {"TECH_ADMIN", "MIXED"}, cap


# --- ACCOUNT_ADMIN_ROLES -----------------------------------------------------------------


def test_fr69_account_admin_roles_is_tech_admin_and_mixed(roles: ModuleType) -> None:
    expected = frozenset({roles.Role.TECH_ADMIN, roles.Role.MIXED})
    assert expected == roles.ACCOUNT_ADMIN_ROLES
    assert isinstance(roles.ACCOUNT_ADMIN_ROLES, frozenset)


def test_account_admin_roles_are_holders_of_manage_accounts(roles: ModuleType) -> None:
    holders = {
        r for r in roles.Role if roles.Capability.MANAGE_ACCOUNTS in roles.ROLE_CAPABILITIES[r]
    }
    assert holders == set(roles.ACCOUNT_ADMIN_ROLES)


# --- неизменяемость ----------------------------------------------------------------------


def test_role_capabilities_mapping_is_read_only(roles: ModuleType) -> None:
    caps: Any = roles.ROLE_CAPABILITIES
    with pytest.raises((TypeError, AttributeError)):
        caps[roles.Role.USER] = frozenset(roles.Capability)
    with pytest.raises((TypeError, AttributeError)):
        del caps[roles.Role.USER]
    with pytest.raises((TypeError, AttributeError)):
        caps[roles.Role.USER] = frozenset()
    assert roles.ROLE_CAPABILITIES[roles.Role.USER] == frozenset({roles.Capability.BUSINESS_ACCESS})


def test_role_capabilities_values_are_frozensets(roles: ModuleType) -> None:
    for role in roles.Role:
        value = roles.ROLE_CAPABILITIES[role]
        assert isinstance(value, frozenset), role
        assert not hasattr(value, "add")


# --- Actor -------------------------------------------------------------------------------


def _actor(roles: ModuleType, role: Any = "USER", **overrides: Any) -> Any:
    kwargs: dict[str, Any] = {
        "user_id": uuid.UUID(int=1),
        "workspace_id": uuid.UUID(int=2),
        "login": "alice",
        "role": roles.Role[role] if isinstance(role, str) else role,
        "must_change_password": False,
        "session_id": b"\x01" * 32,
    }
    kwargs.update(overrides)
    return roles.Actor(**kwargs)


def test_actor_is_frozen_dataclass_with_plan_fields(roles: ModuleType) -> None:
    assert dataclasses.is_dataclass(roles.Actor)
    fields = [f.name for f in dataclasses.fields(roles.Actor)]
    assert fields == [
        "user_id",
        "workspace_id",
        "login",
        "role",
        "must_change_password",
        "session_id",
    ]
    actor = _actor(roles)
    with pytest.raises(dataclasses.FrozenInstanceError):
        actor.role = roles.Role.MIXED
    with pytest.raises(dataclasses.FrozenInstanceError):
        actor.must_change_password = True


def test_actor_equality_by_value(roles: ModuleType) -> None:
    assert _actor(roles) == _actor(roles)
    assert _actor(roles) != _actor(roles, role="MIXED")


@pytest.mark.parametrize(("role", "cap"), CELLS)
def test_actor_can_follows_matrix(roles: ModuleType, role: str, cap: str) -> None:
    actor = _actor(roles, role)
    assert actor.can(roles.Capability[cap]) is (cap in EXPECTED[role])


@pytest.mark.parametrize("cap", ALL_CAPS)
def test_fr66_actor_without_role_has_no_capabilities(roles: ModuleType, cap: str) -> None:
    actor = _actor(roles, None)
    assert actor.role is None
    assert actor.can(roles.Capability[cap]) is False
