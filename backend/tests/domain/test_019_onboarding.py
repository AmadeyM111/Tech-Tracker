"""R8-T06: учётные записи без роли для БА.

Spec 019: AC-26, AC-30; FR-13a, раздел 3.1; plan §4.3, RG-11, RG-12.

Модуль ``app.domain.users.onboarding``: ``list_unassigned``, ``assign_user_role``.
Права, порядок проверок и блокировки: БА (``ONBOARD_ACCOUNTS``) -> роль не «Пользователь» -> 403 ->
протокол ``_lock_for_onboarding`` (актор всё ещё активный БА, иначе 403) -> цель в пространстве
актора (404) -> цель без роли (иначе 403) -> назначение и событие ``user.role_assigned``.
"""

from __future__ import annotations

import dataclasses
import uuid
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from app.core.pagination import PageParams
from app.domain.access.roles import Role
from tests.domain.test_user_admin_service import (
    actor_of,
    events,
    forbidden,
    member_role,
    not_found,
)
from tests.factories import make_user, make_workspace

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

PAGE = PageParams(page=1, page_size=100)
EMAIL = "applicant.secret@example.com"


@pytest.fixture
def onb() -> Any:
    import app.domain.users.onboarding as onboarding

    return onboarding


@pytest.fixture
def svc() -> Any:
    import app.domain.users.service as service

    return service


async def ba_world(db: AsyncSession) -> SimpleNamespace:
    """Пространство: БА (актор), ТА, участник с ролью «Пользователь», две учётные записи без роли
    (самостоятельная регистрация с email и созданная ТА). В чужом пространстве — учётная запись
    без роли.
    """
    ws = await make_workspace(db)
    ba = await make_user(db, workspace=ws, role="business_admin", login="ba.main")
    ta = await make_user(db, workspace=ws, role="tech_admin", login="ta.main")
    member = await make_user(db, workspace=ws, role="user", login="member.user")
    self_reg = await make_user(
        db,
        workspace=ws,
        role=None,
        login="self.reg",
        first_name="Анна",
        last_name="Петрова",
        email=EMAIL,
        self_registered=True,
    )
    by_ta = await make_user(
        db, workspace=ws, role=None, login="created.by.ta", first_name="Борис", last_name="Босов"
    )
    other_ws = await make_workspace(db)
    foreign = await make_user(db, workspace=other_ws, role=None, login="foreign.none")
    await db.commit()
    return SimpleNamespace(
        ws=ws,
        other_ws=other_ws,
        ba=ba,
        ta=ta,
        member=member,
        self_reg=self_reg,
        by_ta=by_ta,
        foreign=foreign,
        actor=actor_of(ba),
    )


# --- list_unassigned: AC-30 (список) ----------------------------------------------------


async def test_019_ac30_ba_sees_both_unassigned_accounts(db: AsyncSession, onb: Any) -> None:
    w = await ba_world(db)
    items, has_next = await onb.list_unassigned(db, w.actor, PAGE)
    assert has_next is False
    assert {item.id for item in items} == {w.self_reg.id, w.by_ta.id}
    by_id = {item.id: item for item in items}
    assert by_id[w.self_reg.id].login == "self.reg"
    assert (by_id[w.self_reg.id].first_name, by_id[w.self_reg.id].last_name) == ("Анна", "Петрова")
    assert by_id[w.by_ta.id].login == "created.by.ta"
    assert (by_id[w.by_ta.id].first_name, by_id[w.by_ta.id].last_name) == ("Борис", "Босов")


async def test_019_ac30_unassigned_list_order_is_login_then_id(db: AsyncSession, onb: Any) -> None:
    w = await ba_world(db)
    items, _ = await onb.list_unassigned(db, w.actor, PAGE)
    assert [item.login for item in items] == ["created.by.ta", "self.reg"]


async def test_019_ac30_accounts_with_role_are_not_listed(db: AsyncSession, onb: Any) -> None:
    w = await ba_world(db)
    items, _ = await onb.list_unassigned(db, w.actor, PAGE)
    ids = {item.id for item in items}
    assert w.ba.id not in ids
    assert w.ta.id not in ids
    assert w.member.id not in ids


async def test_019_ac30_foreign_workspace_accounts_are_not_listed(
    db: AsyncSession, onb: Any
) -> None:
    w = await ba_world(db)
    items, _ = await onb.list_unassigned(db, w.actor, PAGE)
    assert w.foreign.id not in {item.id for item in items}


async def test_019_ac30_unassigned_list_has_no_email(db: AsyncSession, onb: Any) -> None:
    w = await ba_world(db)
    items, _ = await onb.list_unassigned(db, w.actor, PAGE)
    assert {f.name for f in dataclasses.fields(onb.UnassignedAccount)} == {
        "id",
        "login",
        "first_name",
        "last_name",
        "created_at",
    }
    for item in items:
        assert not hasattr(item, "email")
        assert EMAIL not in repr(item)


async def test_019_ac30_unassigned_list_is_paginated(db: AsyncSession, onb: Any) -> None:
    w = await ba_world(db)
    first, has_next = await onb.list_unassigned(db, w.actor, PageParams(page=1, page_size=1))
    assert [item.login for item in first] == ["created.by.ta"]
    assert has_next is True
    second, has_next = await onb.list_unassigned(db, w.actor, PageParams(page=2, page_size=1))
    assert [item.login for item in second] == ["self.reg"]
    assert has_next is False


async def test_019_rg12_blocked_unassigned_account_is_listed(db: AsyncSession, onb: Any) -> None:
    w = await ba_world(db)
    blocked = await make_user(db, workspace=w.ws, role=None, login="blocked.none", blocked=True)
    await db.commit()
    items, _ = await onb.list_unassigned(db, w.actor, PAGE)
    assert blocked.id in {item.id for item in items}


async def test_019_ac30_ta_and_user_and_roleless_actor_cannot_list(
    db: AsyncSession, onb: Any
) -> None:
    w = await ba_world(db)
    for role in ("tech_admin", "user", None):
        actor_row = await make_user(db, workspace=w.ws, role=role, login=f"actor.{role}")
        await db.commit()
        await forbidden(db, onb.list_unassigned(db, actor_of(actor_row), PAGE))


# --- assign_user_role: AC-26, AC-30 (назначение, событие) --------------------------------


@pytest.mark.parametrize("target_name", ["self_reg", "by_ta"])
async def test_019_ac30_ba_assigns_user_role(db: AsyncSession, onb: Any, target_name: str) -> None:
    w = await ba_world(db)
    target = getattr(w, target_name)
    await onb.assign_user_role(db, w.actor, target.id, Role.USER)
    assert await member_role(db, target.id) == "user"


async def test_019_ac26_assign_writes_role_assigned_event_with_ba_actor(
    db: AsyncSession, onb: Any
) -> None:
    w = await ba_world(db)
    await onb.assign_user_role(db, w.actor, w.by_ta.id, Role.USER)
    rows = await events(db, w.ws.id)
    assert len(rows) == 1
    ev = rows[0]
    assert ev.action == "user.role_assigned"
    assert ev.entity_type == "user"
    assert ev.entity_id == w.by_ta.id
    assert ev.actor_id == w.ba.id
    assert ev.in_audit is True
    assert ev.details == {"role_from": None, "role_to": "user"}


async def test_019_rg12_assign_to_blocked_unassigned_account_is_allowed(
    db: AsyncSession, onb: Any
) -> None:
    w = await ba_world(db)
    blocked = await make_user(db, workspace=w.ws, role=None, login="blocked.none", blocked=True)
    await db.commit()
    await onb.assign_user_role(db, w.actor, blocked.id, Role.USER)
    assert await member_role(db, blocked.id) == "user"


@pytest.mark.parametrize("role", [Role.BUSINESS_ADMIN, Role.TECH_ADMIN, None])
async def test_019_ac30_ba_cannot_assign_other_roles_to_unassigned(
    db: AsyncSession, onb: Any, role: Role | None
) -> None:
    w = await ba_world(db)
    await forbidden(db, onb.assign_user_role(db, w.actor, w.by_ta.id, role))
    assert await member_role(db, w.by_ta.id) is None
    assert await events(db, w.ws.id) == []


@pytest.mark.parametrize(
    ("target_name", "existing"),
    [("member", "user"), ("ba", "business_admin"), ("ta", "tech_admin")],
)
async def test_019_ac30_assign_to_account_with_role_is_forbidden(
    db: AsyncSession, onb: Any, target_name: str, existing: str
) -> None:
    w = await ba_world(db)
    target = getattr(w, target_name)
    await forbidden(db, onb.assign_user_role(db, w.actor, target.id, Role.USER))
    assert await member_role(db, target.id) == existing
    assert await events(db, w.ws.id) == []


async def test_019_ac30_repeat_assign_after_user_role_is_forbidden(
    db: AsyncSession, onb: Any
) -> None:
    w = await ba_world(db)
    await onb.assign_user_role(db, w.actor, w.self_reg.id, Role.USER)
    await db.commit()
    await forbidden(db, onb.assign_user_role(db, w.actor, w.self_reg.id, Role.USER))
    assert await member_role(db, w.self_reg.id) == "user"
    assert [r.action for r in await events(db, w.ws.id)] == ["user.role_assigned"]


async def test_019_ac30_role_is_checked_before_target_lookup(db: AsyncSession, onb: Any) -> None:
    w = await ba_world(db)
    await forbidden(db, onb.assign_user_role(db, w.actor, w.foreign.id, Role.BUSINESS_ADMIN))


async def test_019_ac30_ta_and_user_and_roleless_actor_cannot_assign(
    db: AsyncSession, onb: Any
) -> None:
    w = await ba_world(db)
    for role in ("tech_admin", "user", None):
        actor_row = await make_user(db, workspace=w.ws, role=role, login=f"actor.{role}")
        await db.commit()
        await forbidden(db, onb.assign_user_role(db, actor_of(actor_row), w.by_ta.id, Role.USER))
    assert await member_role(db, w.by_ta.id) is None
    assert await events(db, w.ws.id) == []


async def test_019_ac30_blocked_ba_is_forbidden_after_get_actor(db: AsyncSession, onb: Any) -> None:
    w = await ba_world(db)
    actor = actor_of(w.ba)
    await db.execute(text("UPDATE app_user SET is_blocked = true WHERE id = :u"), {"u": w.ba.id})
    await db.commit()
    await forbidden(db, onb.assign_user_role(db, actor, w.by_ta.id, Role.USER))
    assert await member_role(db, w.by_ta.id) is None
    assert await events(db, w.ws.id) == []


async def test_019_ac30_foreign_workspace_target_is_not_found(db: AsyncSession, onb: Any) -> None:
    w = await ba_world(db)
    await not_found(db, onb.assign_user_role(db, w.actor, w.foreign.id, Role.USER))
    assert await member_role(db, w.foreign.id) is None
    assert await events(db, w.other_ws.id) == []
    assert await events(db, w.ws.id) == []


async def test_019_ac30_unknown_target_is_not_found(db: AsyncSession, onb: Any) -> None:
    w = await ba_world(db)
    await not_found(db, onb.assign_user_role(db, w.actor, uuid.uuid4(), Role.USER))
    assert await events(db, w.ws.id) == []


def test_019_rg11_advisory_key_is_imported_from_service(onb: Any, svc: Any) -> None:
    assert onb._ACCOUNT_LOCK_NAMESPACE is svc._ACCOUNT_LOCK_NAMESPACE
