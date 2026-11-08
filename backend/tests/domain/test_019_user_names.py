"""R8-T03: set_name и поля имени в домене (spec 019: FR-3c, FR-13a, AC-35; plan §4.3, RG-10)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from tests.domain.test_user_admin_service import (
    actor_of,
    events,
    fails,
    forbidden,
    not_found,
    world,
)
from tests.domain.test_user_admin_service import env as env  # noqa: PLC0414 (fixture re-export)
from tests.domain.test_user_admin_service import mods as mods  # noqa: PLC0414
from tests.domain.test_user_admin_service import svc as svc  # noqa: PLC0414
from tests.factories import make_user, make_workspace

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def stored_names(db: AsyncSession, user_id: uuid.UUID) -> tuple[str | None, str | None]:
    res = await db.execute(
        text("SELECT first_name, last_name FROM app_user WHERE id = :u"), {"u": user_id}
    )
    row = res.one()
    return row[0], row[1]


async def test_019_ac35_set_name_stores_and_returns_account(db: AsyncSession, svc: Any) -> None:
    w = await world(db)
    account = await svc.set_name(db, w.actor, w.target.id, "  Анна ", "Петрова-Иванова")
    assert account.id == w.target.id
    assert account.first_name == "Анна"
    assert account.last_name == "Петрова-Иванова"
    assert account.self_registered is False
    assert await stored_names(db, w.target.id) == ("Анна", "Петрова-Иванова")


async def test_019_fr3c_set_name_event_has_no_values(db: AsyncSession, svc: Any) -> None:
    w = await world(db)
    await svc.set_name(db, w.actor, w.target.id, "Анна", "Петрова")
    rows = await events(db, w.ws.id)
    assert len(rows) == 1
    ev = rows[0]
    assert ev.action == "user.name_changed"
    assert ev.entity_type == "user"
    assert ev.entity_id == w.target.id
    assert ev.actor_id == w.admin.id
    assert ev.in_audit is True
    assert list(ev.changed_fields) == ["first_name", "last_name"]
    assert ev.details is None
    assert ev.changes is None
    blob = repr(tuple(ev))
    assert "Анна" not in blob
    assert "Петрова" not in blob


async def test_019_fr3c_set_name_changed_fields_only_actually_changed(
    db: AsyncSession, svc: Any
) -> None:
    w = await world(db)
    await svc.set_name(db, w.actor, w.target.id, "Анна", "Петрова")
    await db.commit()
    await svc.set_name(db, w.actor, w.target.id, "Анна", "Сидорова")
    await db.commit()
    await svc.set_name(db, w.actor, w.target.id, "Мария", "Сидорова")
    rows = await events(db, w.ws.id)
    assert [list(r.changed_fields) for r in rows] == [
        ["first_name", "last_name"],
        ["last_name"],
        ["first_name"],
    ]
    assert "Сидорова" not in repr([tuple(r) for r in rows])


async def test_019_fr3c_set_name_for_null_names_first_time_ta_fills_both(
    db: AsyncSession, svc: Any
) -> None:
    w = await world(db)
    assert await stored_names(db, w.target.id) == (None, None)
    await svc.set_name(db, w.actor, w.target.id, "Анна", "Петрова")
    assert await stored_names(db, w.target.id) == ("Анна", "Петрова")


async def test_019_fr3c_set_name_same_values_writes_no_event(db: AsyncSession, svc: Any) -> None:
    w = await world(db)
    await svc.set_name(db, w.actor, w.target.id, "Анна", "Петрова")
    await db.commit()
    again = await svc.set_name(db, w.actor, w.target.id, " Анна", "Петрова ")
    assert (again.first_name, again.last_name) == ("Анна", "Петрова")
    assert len(await events(db, w.ws.id)) == 1


async def test_019_fr3c_set_name_does_not_touch_other_users(db: AsyncSession, svc: Any) -> None:
    w = await world(db)
    await svc.set_name(db, w.actor, w.target.id, "Анна", "Петрова")
    assert await stored_names(db, w.admin.id) == (None, None)


@pytest.mark.parametrize("bad", ["", "   ", "я" * 101, "Ан\nна", "Ан\x00на"])
async def test_019_ac29_set_name_invalid_first_name_is_422(
    db: AsyncSession, svc: Any, bad: str
) -> None:
    w = await world(db)
    await fails(db, svc.set_name(db, w.actor, w.target.id, bad, "Петрова"), "first_name_invalid")
    assert await stored_names(db, w.target.id) == (None, None)
    assert await events(db, w.ws.id) == []


@pytest.mark.parametrize("bad", ["", "   ", "я" * 101, "Пет\nрова"])
async def test_019_ac29_set_name_invalid_last_name_is_422(
    db: AsyncSession, svc: Any, bad: str
) -> None:
    w = await world(db)
    await fails(db, svc.set_name(db, w.actor, w.target.id, "Анна", bad), "last_name_invalid")
    assert await stored_names(db, w.target.id) == (None, None)
    assert await events(db, w.ws.id) == []


async def test_019_ac29_set_name_first_name_checked_before_last(db: AsyncSession, svc: Any) -> None:
    w = await world(db)
    await fails(db, svc.set_name(db, w.actor, w.target.id, "", ""), "first_name_invalid")


async def test_019_ac29_set_name_accepts_100_chars(db: AsyncSession, svc: Any) -> None:
    w = await world(db)
    account = await svc.set_name(db, w.actor, w.target.id, "я" * 100, "ф" * 100)
    assert (account.first_name, account.last_name) == ("я" * 100, "ф" * 100)


async def test_019_ac35_set_name_invalid_does_not_leak_value(db: AsyncSession, svc: Any) -> None:
    w = await world(db)
    secret = "Секретное\nимя"
    exc = await fails(
        db, svc.set_name(db, w.actor, w.target.id, secret, "Петрова"), "first_name_invalid"
    )
    assert "Секретное" not in str(exc)
    assert "Секретное" not in repr(exc)


@pytest.mark.parametrize("role", ["business_admin", "user"])
async def test_019_fr13a_set_name_forbidden_for_ba_and_user(
    db: AsyncSession, svc: Any, role: str
) -> None:
    w = await world(db)
    other = await make_user(db, workspace=w.ws, role=role, login=f"actor.{role}")
    await db.commit()
    await forbidden(db, svc.set_name(db, actor_of(other), w.target.id, "Анна", "Петрова"))
    await forbidden(db, svc.set_name(db, actor_of(other), other.id, "Анна", "Петрова"))
    assert await stored_names(db, w.target.id) == (None, None)
    assert await stored_names(db, other.id) == (None, None)
    assert await events(db, w.ws.id) == []


async def test_019_fr3c_set_name_forbidden_for_actor_without_role(
    db: AsyncSession, svc: Any
) -> None:
    w = await world(db)
    await forbidden(db, svc.set_name(db, actor_of(w.target, role=None), w.target.id, "A", "B"))


async def test_019_fr3c_set_name_forbidden_checked_before_validation(
    db: AsyncSession, svc: Any
) -> None:
    w = await world(db)
    await forbidden(db, svc.set_name(db, actor_of(w.target), w.target.id, "", ""))


async def test_019_fr3c_set_name_foreign_workspace_or_unknown_is_404(
    db: AsyncSession, svc: Any
) -> None:
    w = await world(db)
    foreign = await make_user(db, workspace=await make_workspace(db))
    await db.commit()
    await not_found(db, svc.set_name(db, w.actor, foreign.id, "Анна", "Петрова"))
    await not_found(db, svc.set_name(db, w.actor, uuid.uuid4(), "Анна", "Петрова"))
    assert await stored_names(db, foreign.id) == (None, None)


async def test_019_fr3c_set_name_in_own_record_by_ta(db: AsyncSession, svc: Any) -> None:
    w = await world(db)
    account = await svc.set_name(db, w.actor, w.admin.id, "Борис", "Босс")
    assert (account.first_name, account.last_name) == ("Борис", "Босс")


async def test_019_fr3c_set_name_works_for_blocked_user_and_keeps_state(
    db: AsyncSession, svc: Any
) -> None:
    w = await world(db)
    blocked = await make_user(db, workspace=w.ws, blocked=True, login="blocked.one")
    await db.commit()
    account = await svc.set_name(db, w.actor, blocked.id, "Анна", "Петрова")
    assert account.first_name == "Анна"
    assert await stored_names(db, blocked.id) == ("Анна", "Петрова")


async def test_019_ac22_list_accounts_returns_new_fields(db: AsyncSession, svc: Any) -> None:
    from app.core.pagination import PageParams

    w = await world(db)
    reg = await make_user(
        db,
        workspace=w.ws,
        role=None,
        login="self.reg",
        first_name="Олег",
        last_name="Смирнов",
        self_registered=True,
    )
    await svc.set_name(db, w.actor, w.target.id, "Анна", "Петрова")
    await db.commit()
    accounts, _ = await svc.list_accounts(db, w.actor, PageParams(page=1, page_size=50))
    by_id = {a.id: a for a in accounts}
    assert (by_id[w.target.id].first_name, by_id[w.target.id].last_name) == ("Анна", "Петрова")
    assert by_id[w.target.id].self_registered is False
    assert (by_id[w.admin.id].first_name, by_id[w.admin.id].last_name) == (None, None)
    assert (by_id[reg.id].first_name, by_id[reg.id].last_name) == ("Олег", "Смирнов")
    assert by_id[reg.id].self_registered is True
