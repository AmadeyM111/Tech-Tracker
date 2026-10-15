"""T70: проверка получателей (FR-70, plan §4.5 без DEAL_RESPONSIBLE, §11.5).

Порядок: user_not_found -> user_blocked -> recipient_wrong_role -> not_project_member;
все ошибки - ``Unprocessable`` (422) с кодом. AC-73, AC-74, AC-54, AC-110, FR-68.
"""

from __future__ import annotations

import importlib
import uuid
from types import ModuleType
from typing import Any

import pytest

UID = uuid.UUID(int=7)
OTHER = uuid.UUID(int=8)


@pytest.fixture(scope="module")
def rec() -> ModuleType:
    return importlib.import_module("app.domain.access.recipients")


@pytest.fixture(scope="module")
def roles() -> ModuleType:
    return importlib.import_module("app.domain.access.roles")


@pytest.fixture(scope="module")
def errors() -> ModuleType:
    return importlib.import_module("app.core.errors")


def _facts(
    rec: ModuleType,
    roles: ModuleType,
    role: str | None,
    *,
    in_workspace: bool = True,
    blocked: bool = False,
) -> Any:
    return rec.RecipientFacts(
        user_id=UID,
        in_workspace=in_workspace,
        is_blocked=blocked,
        role=None if role is None else roles.Role[role],
    )


def _code(exc: BaseException) -> str:
    return str(exc.code)  # type: ignore[attr-defined]


def test_purpose_has_no_deal_responsible(rec) -> None:
    assert {m.name for m in rec.RecipientPurpose} == {
        "PROJECT_MEMBER",
        "TASK_ASSIGNEE",
        "PROJECT_OWNER",
    }


# (purpose, роль, участник?, ожидание: None = допустим, иначе код)
TABLE = [
    ("PROJECT_MEMBER", "BUSINESS_ADMIN", False, None),
    ("PROJECT_MEMBER", "MIXED", False, None),
    ("PROJECT_MEMBER", "USER", False, None),
    ("PROJECT_MEMBER", "TECH_ADMIN", False, "recipient_wrong_role"),
    ("PROJECT_MEMBER", None, False, "recipient_wrong_role"),
    ("TASK_ASSIGNEE", "BUSINESS_ADMIN", True, None),
    ("TASK_ASSIGNEE", "MIXED", True, None),
    ("TASK_ASSIGNEE", "USER", True, None),
    ("TASK_ASSIGNEE", "BUSINESS_ADMIN", False, "not_project_member"),
    ("TASK_ASSIGNEE", "MIXED", False, "not_project_member"),
    ("TASK_ASSIGNEE", "USER", False, "not_project_member"),
    ("TASK_ASSIGNEE", "TECH_ADMIN", True, "recipient_wrong_role"),
    ("TASK_ASSIGNEE", None, True, "recipient_wrong_role"),
    ("TASK_ASSIGNEE", "TECH_ADMIN", False, "recipient_wrong_role"),  # роль проверяется раньше
    ("PROJECT_OWNER", "BUSINESS_ADMIN", True, None),
    ("PROJECT_OWNER", "MIXED", True, None),
    ("PROJECT_OWNER", "BUSINESS_ADMIN", False, "not_project_member"),
    ("PROJECT_OWNER", "MIXED", False, "not_project_member"),
    ("PROJECT_OWNER", "USER", True, "recipient_wrong_role"),
    ("PROJECT_OWNER", "USER", False, "recipient_wrong_role"),
    ("PROJECT_OWNER", "TECH_ADMIN", True, "recipient_wrong_role"),
    ("PROJECT_OWNER", None, True, "recipient_wrong_role"),
]


@pytest.mark.parametrize(
    ("purpose", "role", "is_member", "expected"),
    [pytest.param(*r, id=f"{r[0]}-{r[1]}-member={r[2]}") for r in TABLE],
)
def test_ac74_check_recipient_table(rec, roles, errors, purpose, role, is_member, expected) -> None:
    target = _facts(rec, roles, role)
    members = frozenset({UID, OTHER}) if is_member else frozenset({OTHER})
    p = rec.RecipientPurpose[purpose]
    if expected is None:
        assert rec.check_recipient(target, p, project_member_ids=members) is None
        return
    with pytest.raises(errors.Unprocessable) as ei:
        rec.check_recipient(target, p, project_member_ids=members)
    assert ei.value.status_code == 422
    assert _code(ei.value) == expected


@pytest.mark.parametrize("purpose", ["PROJECT_MEMBER", "TASK_ASSIGNEE", "PROJECT_OWNER"])
def test_ac74_not_in_workspace_is_user_not_found(rec, roles, errors, purpose) -> None:
    target = _facts(rec, roles, "USER", in_workspace=False)
    with pytest.raises(errors.Unprocessable) as ei:
        rec.check_recipient(
            target, rec.RecipientPurpose[purpose], project_member_ids=frozenset({UID})
        )
    assert _code(ei.value) == "user_not_found"


@pytest.mark.parametrize("purpose", ["PROJECT_MEMBER", "TASK_ASSIGNEE", "PROJECT_OWNER"])
def test_ac74_blocked_is_user_blocked(rec, roles, errors, purpose) -> None:
    target = _facts(rec, roles, "BUSINESS_ADMIN", blocked=True)
    with pytest.raises(errors.Unprocessable) as ei:
        rec.check_recipient(
            target, rec.RecipientPurpose[purpose], project_member_ids=frozenset({UID})
        )
    assert _code(ei.value) == "user_blocked"


def test_order_not_found_before_blocked(rec, roles, errors) -> None:
    target = _facts(rec, roles, None, in_workspace=False, blocked=True)
    with pytest.raises(errors.Unprocessable) as ei:
        rec.check_recipient(
            target, rec.RecipientPurpose.PROJECT_OWNER, project_member_ids=frozenset()
        )
    assert _code(ei.value) == "user_not_found"


def test_order_blocked_before_wrong_role(rec, roles, errors) -> None:
    target = _facts(rec, roles, "TECH_ADMIN", blocked=True)
    with pytest.raises(errors.Unprocessable) as ei:
        rec.check_recipient(target, rec.RecipientPurpose.PROJECT_MEMBER, project_member_ids=None)
    assert _code(ei.value) == "user_blocked"


def test_order_wrong_role_before_not_member(rec, roles, errors) -> None:
    target = _facts(rec, roles, "USER")
    with pytest.raises(errors.Unprocessable) as ei:
        rec.check_recipient(
            target, rec.RecipientPurpose.PROJECT_OWNER, project_member_ids=frozenset()
        )
    assert _code(ei.value) == "recipient_wrong_role"


def test_project_member_purpose_does_not_need_member_ids(rec, roles) -> None:
    target = _facts(rec, roles, "USER")
    assert (
        rec.check_recipient(target, rec.RecipientPurpose.PROJECT_MEMBER, project_member_ids=None)
        is None
    )


@pytest.mark.parametrize("purpose", ["TASK_ASSIGNEE", "PROJECT_OWNER"])
@pytest.mark.parametrize("role", ["BUSINESS_ADMIN", "MIXED"])
def test_membership_purpose_with_none_member_ids_is_caller_error(rec, roles, purpose, role) -> None:
    """Fail Fast: для целей с проверкой членства None - ошибка вызывающего кода."""
    target = _facts(rec, roles, role)
    with pytest.raises(ValueError):
        rec.check_recipient(target, rec.RecipientPurpose[purpose], project_member_ids=None)
