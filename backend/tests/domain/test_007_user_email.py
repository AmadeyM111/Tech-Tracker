"""R7-T06: email пользователя в домене (spec 007: FR-1, FR-2, AC-1; plan §4.3, PR-1, PR-2, PR-4).

Публичный интерфейс: ``app.domain.users.email.normalize_email``;
``app.domain.users.service.create_user(..., email=)``, ``set_email(db, actor, user_id, email, /)``,
``UserAccount.email``, ``list_accounts``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from tests.domain.test_user_admin_service import (
    ONE_TIME,
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
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

INVALID = ["a", "a@", "@x.ru", "a b@x", "a@b@c", "a@x.ru\n", "a​@x.ru", "a@" + "x" * 255]


async def stored_email(db: AsyncSession, user_id: uuid.UUID) -> str | None:
    res = await db.execute(text("SELECT email FROM app_user WHERE id = :u"), {"u": user_id})
    return res.scalar_one()


async def create(
    db: AsyncSession, env: SimpleNamespace, svc: Any, actor: Any, login: str, email: Any
) -> Any:
    return await svc.create_user(
        db,
        actor,
        env.hasher,
        login=login,
        first_name="Иван",
        last_name="Петров",
        one_time_password=SecretStr(ONE_TIME),
        email=email,
    )


# --- normalize_email (plan §4.3) ---------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("A@x.ru", "a@x.ru"),
        ("  a@X.RU ", "a@x.ru"),
        ("ivan.p+tag@mail.example.com", "ivan.p+tag@mail.example.com"),
    ],
)
def test_007_ac1_normalize_email_strips_and_lowercases(raw: str, expected: str) -> None:
    from app.domain.users.email import normalize_email

    assert normalize_email(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", *INVALID, "a" * 250 + "@x.ru"])
def test_007_ac1_normalize_email_rejects_invalid(raw: str) -> None:
    from app.domain.users.email import MAX_EMAIL_LENGTH, normalize_email

    assert MAX_EMAIL_LENGTH == 254
    assert normalize_email(raw) is None


def test_007_ac1_normalize_email_accepts_exactly_254() -> None:
    from app.domain.users.email import normalize_email

    value = "a" * (254 - len("@x.ru")) + "@x.ru"
    assert len(value) == 254
    assert normalize_email(value) == value


# --- create_user(email=) -----------------------------------------------------------------


async def test_007_ac1_create_stores_lowercase_email_and_returns_it(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    w = await world(db)
    created = await create(db, env, svc, w.actor, "ivan.petrov", "A@x.ru")
    assert created.email == "a@x.ru"
    assert await stored_email(db, created.id) == "a@x.ru"


async def test_007_ac1_create_second_user_with_case_variant_is_409(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    w = await world(db)
    await create(db, env, svc, w.actor, "ivan.petrov", "A@x.ru")
    await db.commit()
    await fails(
        db, create(db, env, svc, w.actor, "petr.ivanov", "a@X.ru"), "email_taken", status=409
    )


@pytest.mark.parametrize("empty", [None, ""])
async def test_007_ac1_empty_email_allowed_for_several_users(
    db: AsyncSession, env: SimpleNamespace, svc: Any, empty: str | None
) -> None:
    w = await world(db)
    first = await create(db, env, svc, w.actor, "ivan.petrov", empty)
    second = await create(db, env, svc, w.actor, "petr.ivanov", empty)
    assert first.email is None
    assert second.email is None
    assert await stored_email(db, first.id) is None
    assert await stored_email(db, second.id) is None


async def test_007_ac1_create_without_email_argument_keeps_email_null(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    w = await world(db)
    created = await svc.create_user(
        db,
        w.actor,
        env.hasher,
        login="ivan.petrov",
        first_name="Иван",
        last_name="Петров",
        one_time_password=SecretStr(ONE_TIME),
    )
    assert created.email is None


@pytest.mark.parametrize("bad", INVALID)
async def test_007_ac1_create_invalid_email_is_422_email_invalid(
    db: AsyncSession, env: SimpleNamespace, svc: Any, bad: str
) -> None:
    w = await world(db)
    await fails(db, create(db, env, svc, w.actor, "ivan.petrov", bad), "email_invalid")


async def test_007_ac1_create_check_order_login_then_email_then_password(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    w = await world(db)
    await create(db, env, svc, w.actor, "ivan.petrov", "a@x.ru")
    await db.commit()
    # login_invalid раньше email_invalid
    await fails(db, create(db, env, svc, w.actor, "bad login!", "a"), "login_invalid")
    # login_taken раньше email_invalid
    await fails(db, create(db, env, svc, w.actor, "ivan.petrov", "a"), "login_taken")
    # email_taken раньше политики пароля
    await fails(
        db,
        svc.create_user(
            db,
            w.actor,
            env.hasher,
            login="petr.ivanov",
            first_name="Иван",
            last_name="Петров",
            one_time_password=SecretStr("short"),
            email="a@x.ru",
        ),
        "email_taken",
        status=409,
    )
    # email_invalid раньше политики пароля
    await fails(
        db,
        svc.create_user(
            db,
            w.actor,
            env.hasher,
            login="petr.ivanov",
            first_name="Иван",
            last_name="Петров",
            one_time_password=SecretStr("short"),
            email="a",
        ),
        "email_invalid",
    )


async def test_007_ac1_create_with_email_writes_only_user_created_event(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    w = await world(db)
    await create(db, env, svc, w.actor, "ivan.petrov", "a@x.ru")
    rows = await events(db, w.ws.id)
    assert [r.action for r in rows] == ["user.created"]
    assert "a@x.ru" not in repr(tuple(rows[0]))


async def test_007_ac1_create_forbidden_for_non_account_admin(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    w = await world(db)
    await forbidden(db, create(db, env, svc, actor_of(w.target), "ivan.petrov", "a@x.ru"))


async def test_007_ac1_email_taken_by_user_of_other_workspace(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    w = await world(db)
    other_ws = await make_workspace(db)
    await make_user(db, workspace=other_ws, email="a@x.ru")
    await db.commit()
    await fails(
        db, create(db, env, svc, w.actor, "ivan.petrov", "A@x.ru"), "email_taken", status=409
    )


async def test_007_pr2_blocked_user_still_holds_email(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    w = await world(db)
    await make_user(db, workspace=w.ws, blocked=True, email="a@x.ru")
    await db.commit()
    await fails(
        db, create(db, env, svc, w.actor, "ivan.petrov", "a@x.ru"), "email_taken", status=409
    )


# --- set_email ---------------------------------------------------------------------------


async def test_007_fr2_set_email_stores_lowercase_and_returns_account(
    db: AsyncSession, svc: Any
) -> None:
    w = await world(db)
    account = await svc.set_email(db, w.actor, w.target.id, "  A@X.ru ")
    assert account.id == w.target.id
    assert account.email == "a@x.ru"
    assert await stored_email(db, w.target.id) == "a@x.ru"


async def test_007_fr2_set_email_writes_user_email_changed_without_values(
    db: AsyncSession, svc: Any
) -> None:
    w = await world(db)
    await svc.set_email(db, w.actor, w.target.id, "a@x.ru")
    rows = await events(db, w.ws.id)
    assert len(rows) == 1
    ev = rows[0]
    assert ev.action == "user.email_changed"
    assert ev.entity_type == "user"
    assert ev.entity_id == w.target.id
    assert ev.actor_id == w.admin.id
    assert ev.in_audit is True
    assert not ev.changed_fields
    assert ev.details is None
    assert ev.changes is None
    assert "x.ru" not in repr(tuple(ev))


async def test_007_fr2_set_email_same_value_writes_no_event(db: AsyncSession, svc: Any) -> None:
    w = await world(db)
    await svc.set_email(db, w.actor, w.target.id, "a@x.ru")
    await db.commit()
    again = await svc.set_email(db, w.actor, w.target.id, "A@X.RU")
    assert again.email == "a@x.ru"
    assert len(await events(db, w.ws.id)) == 1


async def test_007_fr2_set_email_null_on_null_writes_no_event(db: AsyncSession, svc: Any) -> None:
    w = await world(db)
    account = await svc.set_email(db, w.actor, w.target.id, None)
    assert account.email is None
    assert await events(db, w.ws.id) == []


@pytest.mark.parametrize("empty", [None, "", "   "])
async def test_007_fr2_set_email_clears_and_logs_event(
    db: AsyncSession, svc: Any, empty: str | None
) -> None:
    w = await world(db)
    await svc.set_email(db, w.actor, w.target.id, "a@x.ru")
    await db.commit()
    account = await svc.set_email(db, w.actor, w.target.id, empty)
    assert account.email is None
    assert await stored_email(db, w.target.id) is None
    assert [r.action for r in await events(db, w.ws.id)] == ["user.email_changed"] * 2


@pytest.mark.parametrize("bad", INVALID)
async def test_007_fr2_set_email_invalid_is_422(db: AsyncSession, svc: Any, bad: str) -> None:
    w = await world(db)
    await fails(db, svc.set_email(db, w.actor, w.target.id, bad), "email_invalid")
    assert await stored_email(db, w.target.id) is None


async def test_007_ac1_set_email_taken_by_other_is_409_case_insensitive(
    db: AsyncSession, svc: Any
) -> None:
    w = await world(db)
    await make_user(db, workspace=w.ws, email="a@x.ru")
    await db.commit()
    await fails(db, svc.set_email(db, w.actor, w.target.id, "A@X.ru"), "email_taken", status=409)
    assert await stored_email(db, w.target.id) is None
    assert await events(db, w.ws.id) == []


async def test_007_ac1_set_email_taken_by_other_workspace_is_409(
    db: AsyncSession, svc: Any
) -> None:
    w = await world(db)
    await make_user(db, workspace=await make_workspace(db), email="a@x.ru")
    await db.commit()
    await fails(db, svc.set_email(db, w.actor, w.target.id, "a@x.ru"), "email_taken", status=409)


async def test_007_pr2_set_email_taken_by_blocked_user_is_409(db: AsyncSession, svc: Any) -> None:
    w = await world(db)
    await make_user(db, workspace=w.ws, blocked=True, email="a@x.ru")
    await db.commit()
    await fails(db, svc.set_email(db, w.actor, w.target.id, "a@x.ru"), "email_taken", status=409)


async def test_007_fr2_set_email_requires_manage_accounts(db: AsyncSession, svc: Any) -> None:
    w = await world(db)
    await forbidden(db, svc.set_email(db, actor_of(w.target), w.target.id, "a@x.ru"))
    assert await stored_email(db, w.target.id) is None


async def test_007_fr2_set_email_forbidden_checked_before_validation(
    db: AsyncSession, svc: Any
) -> None:
    w = await world(db)
    await forbidden(db, svc.set_email(db, actor_of(w.target), w.target.id, "a"))


async def test_007_fr2_set_email_foreign_workspace_or_unknown_is_404(
    db: AsyncSession, svc: Any
) -> None:
    import uuid as uuid_mod

    w = await world(db)
    foreign = await make_user(db, workspace=await make_workspace(db))
    await db.commit()
    await not_found(db, svc.set_email(db, w.actor, foreign.id, "a@x.ru"))
    await not_found(db, svc.set_email(db, w.actor, uuid_mod.uuid4(), "a@x.ru"))
    assert await stored_email(db, foreign.id) is None


async def test_007_fr2_set_email_does_not_touch_sessions(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    from tests.domain.test_user_admin_service import count_sessions, open_sessions

    w = await world(db)
    await open_sessions(db, env, w.target, 2)
    await db.commit()
    await svc.set_email(db, w.actor, w.target.id, "a@x.ru")
    assert await count_sessions(db, w.target.id) == 2


async def test_007_fr2_set_email_in_own_record_by_admin(db: AsyncSession, svc: Any) -> None:
    w = await world(db)
    account = await svc.set_email(db, w.actor, w.admin.id, "boss@x.ru")
    assert account.email == "boss@x.ru"


# --- list_accounts / UserAccount.email ---------------------------------------------------


async def test_007_ac1_list_accounts_returns_email(db: AsyncSession, svc: Any) -> None:
    from app.core.pagination import PageParams

    w = await world(db)
    await svc.set_email(db, w.actor, w.target.id, "a@x.ru")
    await db.commit()
    accounts, _ = await svc.list_accounts(db, w.actor, PageParams(page=1, page_size=50))
    by_id = {a.id: a.email for a in accounts}
    assert by_id[w.target.id] == "a@x.ru"
    assert by_id[w.admin.id] is None
