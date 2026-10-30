"""R7-T09: ключи агентов — выпуск, перечень, отзыв (сервис, 007, plan §4.6, PD-6, PD-8).

AC-6, AC-8, AC-9, AC-11, AC-12 (уровень домена), AC-38/AC-39 (секрет не утекает из сервиса);
FR-5…FR-11.

Публичный интерфейс (``app.domain.api_keys.service``)::

    key_state(*, expires_at, revoked_at, now) -> ApiKeyState
    issue_api_key(db, actor, user_id, /, *, name, ttl_days) -> IssuedApiKey
    list_api_keys(db, actor, user_id, params: PageParams) -> tuple[list[ApiKeyView], bool]
    revoke_api_key(db, actor, user_id, key_id, /) -> None

Секрет ключа в сообщениях assert не печатается: булево считается до assert.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from app.core.pagination import PageParams
from app.domain.access.roles import Actor, Role
from tests.factories import UserRow, make_api_key, make_user, make_workspace

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.clock import FixedClock

CLOCK = datetime(2026, 11, 2, 7, 0, tzinfo=UTC)


# --- фикстуры и помощники ---------------------------------------------------------------


@pytest.fixture
def svc() -> Any:
    import app.domain.api_keys.service as service

    return service


@pytest.fixture(autouse=True)
def _clock(fixed_clock: FixedClock) -> None:
    fixed_clock.set(CLOCK)


def actor_of(user: UserRow) -> Actor:
    return Actor(
        user_id=user.id,
        workspace_id=user.workspace_id,
        login=user.login,
        role=Role(user.role) if user.role is not None else None,
        must_change_password=False,
        session_id=b"\x01" * 32,
    )


async def world(db: AsyncSession) -> SimpleNamespace:
    ws = await make_workspace(db)
    ta = await make_user(db, workspace=ws, role="tech_admin", login="ta1")
    ba = await make_user(db, workspace=ws, role="business_admin", login="ba1")
    u1 = await make_user(db, workspace=ws, role="user", login="uu1")
    agent = await make_user(db, workspace=ws, role="user", login="agent.u", is_agent=True)
    other = await make_user(db, workspace=ws, role="user", login="agent.o", is_agent=True)
    await db.commit()
    return SimpleNamespace(
        ws=ws,
        ta=ta,
        ba=ba,
        u1=u1,
        agent=agent,
        other=other,
        actor=actor_of(ta),
    )


async def fails(
    db: AsyncSession, awaitable: Awaitable[Any], code: str | None, *, status: int = 422
) -> None:
    from app.core.errors import AppError

    with pytest.raises(AppError) as info:
        await awaitable
    assert info.value.status_code == status
    if code is not None:
        assert str(info.value.code) == code
    await db.rollback()


async def event_rows(db: AsyncSession, action: str | None = None) -> list[Any]:
    sql = (
        "SELECT id, workspace_id, actor_id, entity_type, entity_id, action, details "
        "FROM domain_event"
    )
    params: dict[str, Any] = {}
    if action is not None:
        sql += " WHERE action = :a"
        params["a"] = action
    return list((await db.execute(text(sql + " ORDER BY id"), params)).all())


async def event_count(db: AsyncSession) -> int:
    return int((await db.execute(text("SELECT count(*) FROM domain_event"))).scalar_one())


async def key_count(db: AsyncSession, user_id: uuid.UUID | None = None) -> int:
    if user_id is None:
        sql, params = "SELECT count(*) FROM api_key", {}
    else:
        sql, params = "SELECT count(*) FROM api_key WHERE user_id = :u", {"u": user_id}
    return int((await db.execute(text(sql), params)).scalar_one())


async def key_row(db: AsyncSession, key_id: uuid.UUID) -> Any:
    res = await db.execute(
        text(
            "SELECT id, workspace_id, user_id, name, secret_digest, created_at, created_by, "
            "expires_at, revoked_at, revoked_by, last_used_at FROM api_key WHERE id = :i"
        ),
        {"i": key_id},
    )
    return res.one()


async def seed_active_keys(db: AsyncSession, w: SimpleNamespace, n: int) -> list[Any]:
    rows = []
    for i in range(n):
        rows.append(
            await make_api_key(
                db,
                user=w.agent,
                created_by=w.ta,
                name=f"seed-{i}",
                created_at=CLOCK - timedelta(hours=n - i),
                expires_at=CLOCK + timedelta(days=30),
            )
        )
    await db.commit()
    return rows


# --- key_state --------------------------------------------------------------------------


def test_007_ac8_key_state_revoked_wins_over_expired(svc: Any) -> None:
    """PD-6: revoked, иначе expired (expires_at <= now), иначе active."""
    past = CLOCK - timedelta(days=1)
    future = CLOCK + timedelta(days=1)
    st = svc.ApiKeyState
    assert svc.key_state(expires_at=future, revoked_at=None, now=CLOCK) == st.ACTIVE
    assert svc.key_state(expires_at=future, revoked_at=past, now=CLOCK) == st.REVOKED
    assert svc.key_state(expires_at=past, revoked_at=past, now=CLOCK) == st.REVOKED
    assert svc.key_state(expires_at=past, revoked_at=None, now=CLOCK) == st.EXPIRED
    # граница: ровно в момент окончания срока ключ уже истёк (AC-10)
    assert svc.key_state(expires_at=CLOCK, revoked_at=None, now=CLOCK) == st.EXPIRED
    just_before = CLOCK + timedelta(seconds=1)
    assert svc.key_state(expires_at=just_before, revoked_at=None, now=CLOCK) == st.ACTIVE
    assert [s.value for s in st] == ["active", "expired", "revoked"]


def test_007_constants(svc: Any) -> None:
    """plan §4.6: пределы и лимит."""
    assert svc.MAX_ACTIVE_KEYS == 5
    assert svc.DEFAULT_TTL_DAYS == 90
    assert svc.MAX_TTL_DAYS == 365


# --- AC-6: выпуск -----------------------------------------------------------------------


async def test_007_ac6_issue_returns_secret_and_stores_only_digest(
    db: AsyncSession, svc: Any
) -> None:
    """AC-6/FR-6: секрет по формату; в БД sha256(секрета); repr без секрета."""
    import hashlib

    from app.core.security.api_keys import is_api_key_format

    w = await world(db)
    issued = await svc.issue_api_key(db, w.actor, w.agent.id, name="claude-laptop", ttl_days=90)

    assert isinstance(issued, svc.IssuedApiKey)
    secret = issued.secret
    assert is_api_key_format(secret), "формат ключа gtk_ + 43 символа"
    row = await key_row(db, issued.key.id)
    assert bytes(row.secret_digest) == hashlib.sha256(secret.encode("ascii")).digest()
    leaked = secret in repr(issued) or secret in repr(issued.key)
    assert not leaked, "секрет в repr"
    assert secret[8:] not in repr(issued), "часть секрета в repr"
    assert not hasattr(issued.key, "secret")
    assert not hasattr(issued.key, "secret_digest")
    assert row.name == "claude-laptop"
    assert row.user_id == w.agent.id
    assert row.workspace_id == w.ws.id
    assert row.created_by == w.ta.id
    assert row.revoked_at is None
    assert row.last_used_at is None


async def test_007_ac6_issued_view_fields(db: AsyncSession, svc: Any) -> None:
    """AC-6/FR-7: ApiKeyView — id, название, автор (UserRef), выпуск, срок, состояние active."""
    w = await world(db)
    issued = await svc.issue_api_key(db, w.actor, w.agent.id, name="k1", ttl_days=90)
    v = issued.key
    assert isinstance(v, svc.ApiKeyView)
    assert v.name == "k1"
    assert v.created_at == CLOCK
    assert v.expires_at == CLOCK + timedelta(days=90)
    assert v.last_used_at is None
    assert v.revoked_at is None
    assert v.state == svc.ApiKeyState.ACTIVE
    assert v.created_by is not None
    assert v.created_by.id == w.ta.id
    assert v.created_by.login == "ta1"
    assert v.created_by.is_agent is False


async def test_007_ac6_secrets_are_unique(db: AsyncSession, svc: Any) -> None:
    w = await world(db)
    a = await svc.issue_api_key(db, w.actor, w.agent.id, name="a", ttl_days=1)
    b = await svc.issue_api_key(db, w.actor, w.agent.id, name="b", ttl_days=1)
    assert a.secret != b.secret
    assert a.key.id != b.key.id


async def test_007_ac6_issue_writes_exactly_one_audit_event(db: AsyncSession, svc: Any) -> None:
    """AC-6/FR-11: одна запись user.api_key_issued: автор ТА, агент, id и название; без секрета."""
    w = await world(db)
    before = await event_count(db)
    issued = await svc.issue_api_key(db, w.actor, w.agent.id, name="claude-laptop", ttl_days=90)

    assert await event_count(db) == before + 1
    (ev,) = await event_rows(db, "user.api_key_issued")
    assert ev.actor_id == w.ta.id
    assert ev.entity_id == w.agent.id
    assert ev.entity_type == "user"
    assert ev.workspace_id == w.ws.id
    assert ev.details == {"api_key_id": str(issued.key.id), "api_key_name": "claude-laptop"}
    leaked = issued.secret in str(ev.details) or issued.secret[4:] in str(ev.details)
    assert not leaked, "секрет в журнале"


# --- AC-11: срок ------------------------------------------------------------------------


async def test_007_ac11_default_ttl_is_90_days(db: AsyncSession, svc: Any) -> None:
    """AC-11: срок по умолчанию — 90 суток (DEFAULT_TTL_DAYS)."""
    w = await world(db)
    issued = await svc.issue_api_key(
        db, w.actor, w.agent.id, name="def", ttl_days=svc.DEFAULT_TTL_DAYS
    )
    assert issued.key.expires_at == CLOCK + timedelta(days=90)
    row = await key_row(db, issued.key.id)
    assert row.expires_at == CLOCK + timedelta(days=90)


@pytest.mark.parametrize("days", [1, 365])
async def test_007_ac11_ttl_bounds_accepted(db: AsyncSession, svc: Any, days: int) -> None:
    """AC-11: 365 суток -> успех (и нижняя граница 1)."""
    w = await world(db)
    issued = await svc.issue_api_key(db, w.actor, w.agent.id, name="b", ttl_days=days)
    assert issued.key.expires_at == CLOCK + timedelta(days=days)
    assert (await key_row(db, issued.key.id)).expires_at == CLOCK + timedelta(days=days)


@pytest.mark.parametrize("days", [-1, 0, 366])
async def test_007_ac11_ttl_out_of_range_422(db: AsyncSession, svc: Any, days: int) -> None:
    """AC-11: в прошлом, нулевой, 366 суток -> 422 validation_error, ключ и запись не созданы."""
    w = await world(db)
    keys, events = await key_count(db), await event_count(db)
    await fails(
        db,
        svc.issue_api_key(db, w.actor, w.agent.id, name="x", ttl_days=days),
        "validation_error",
    )
    assert await key_count(db) == keys
    assert await event_count(db) == events


# --- имя ключа --------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["", "a" * 101, "bad\x00name"], ids=["empty", "101", "nul"])
async def test_007_ac7_bad_name_422(db: AsyncSession, svc: Any, name: str) -> None:
    """AC-7 (домен): пустое, 101 символ, NUL -> 422 validation_error; ничего не создано."""
    w = await world(db)
    keys, events = await key_count(db), await event_count(db)
    await fails(
        db,
        svc.issue_api_key(db, w.actor, w.agent.id, name=name, ttl_days=90),
        "validation_error",
    )
    assert await key_count(db) == keys
    assert await event_count(db) == events


@pytest.mark.parametrize("name", ["a", "я" * 100, "a" * 100, "с пробелами и (скобками)"])
async def test_007_name_boundaries_accepted(db: AsyncSession, svc: Any, name: str) -> None:
    w = await world(db)
    issued = await svc.issue_api_key(db, w.actor, w.agent.id, name=name, ttl_days=90)
    assert issued.key.name == name
    assert (await key_row(db, issued.key.id)).name == name


# --- AC-7 (домен): не агент, заблокирован, права, чужой пользователь --------------------


async def test_007_ac7_not_an_agent_422(db: AsyncSession, svc: Any) -> None:
    """AC-7/FR-5: обычному пользователю -> 422 not_an_agent."""
    w = await world(db)
    keys, events = await key_count(db), await event_count(db)
    await fails(
        db,
        svc.issue_api_key(db, w.actor, w.u1.id, name="k", ttl_days=90),
        "not_an_agent",
    )
    assert await key_count(db) == keys
    assert await event_count(db) == events


async def test_007_ac7_blocked_agent_422_user_blocked(db: AsyncSession, svc: Any) -> None:
    """AC-7: заблокированному агенту -> 422 user_blocked."""
    w = await world(db)
    blocked = await make_user(
        db, workspace=w.ws, role="user", login="agent.b", is_agent=True, blocked=True
    )
    await db.commit()
    keys, events = await key_count(db), await event_count(db)
    await fails(
        db,
        svc.issue_api_key(db, w.actor, blocked.id, name="k", ttl_days=90),
        "user_blocked",
    )
    assert await key_count(db) == keys
    assert await event_count(db) == events


async def test_007_ac7_blocked_human_is_not_an_agent_first(db: AsyncSession, svc: Any) -> None:
    """plan §4.6: not_an_agent проверяется раньше user_blocked."""
    w = await world(db)
    human = await make_user(db, workspace=w.ws, role="user", login="h.blocked", blocked=True)
    await db.commit()
    await fails(
        db,
        svc.issue_api_key(db, w.actor, human.id, name="k", ttl_days=90),
        "not_an_agent",
    )


@pytest.mark.parametrize("who", ["ba", "u1"])
async def test_007_ac7_without_capability_403(db: AsyncSession, svc: Any, who: str) -> None:
    """AC-7: БА и П -> 403 на все три операции; ключи и журнал не изменились."""
    w = await world(db)
    (existing,) = await seed_active_keys(db, w, 1)
    actor = actor_of(getattr(w, who))
    keys, events = await key_count(db), await event_count(db)

    await fails(
        db,
        svc.issue_api_key(db, actor, w.agent.id, name="k", ttl_days=90),
        None,
        status=403,
    )
    await fails(db, svc.list_api_keys(db, actor, w.agent.id, PageParams()), None, status=403)
    await fails(db, svc.revoke_api_key(db, actor, w.agent.id, existing.id), None, status=403)
    assert await key_count(db) == keys
    assert await event_count(db) == events
    assert (await key_row(db, existing.id)).revoked_at is None


async def test_007_ac7_forbidden_checked_before_validation(db: AsyncSession, svc: Any) -> None:
    """plan §4.6: 403 раньше 422 (БА с ttl_days=-1 получает 403)."""
    w = await world(db)
    await fails(
        db,
        svc.issue_api_key(db, actor_of(w.ba), w.agent.id, name="", ttl_days=-1),
        None,
        status=403,
    )


async def test_007_issue_unknown_or_foreign_user_404(db: AsyncSession, svc: Any) -> None:
    """Чужое пространство и несуществующий user_id -> 404, ключ не создан."""
    w = await world(db)
    foreign_ws = await make_workspace(db)
    foreign = await make_user(db, workspace=foreign_ws, role="user", is_agent=True)
    await db.commit()
    keys = await key_count(db)
    await fails(
        db,
        svc.issue_api_key(db, w.actor, foreign.id, name="k", ttl_days=90),
        None,
        status=404,
    )
    await fails(
        db,
        svc.issue_api_key(db, w.actor, uuid.uuid4(), name="k", ttl_days=90),
        None,
        status=404,
    )
    await fails(db, svc.list_api_keys(db, w.actor, foreign.id, PageParams()), None, status=404)
    assert await key_count(db) == keys


# --- AC-12: лимит -----------------------------------------------------------------------


async def test_007_ac12_sixth_active_key_rejected(db: AsyncSession, svc: Any) -> None:
    """AC-12/FR-10: 5 действующих -> шестой 422 api_key_limit_reached; ключей по-прежнему 5."""
    w = await world(db)
    await seed_active_keys(db, w, 5)
    events = await event_count(db)
    await fails(
        db,
        svc.issue_api_key(db, w.actor, w.agent.id, name="sixth", ttl_days=90),
        "api_key_limit_reached",
    )
    assert await key_count(db, w.agent.id) == 5
    assert await event_count(db) == events


async def test_007_ac12_fifth_key_is_accepted(db: AsyncSession, svc: Any) -> None:
    w = await world(db)
    await seed_active_keys(db, w, 4)
    await svc.issue_api_key(db, w.actor, w.agent.id, name="fifth", ttl_days=90)
    assert await key_count(db, w.agent.id) == 5


async def test_007_ac12_revoke_one_then_issue_succeeds(db: AsyncSession, svc: Any) -> None:
    """AC-12: отозвать один и выпустить новый -> успех."""
    w = await world(db)
    rows = await seed_active_keys(db, w, 5)
    await svc.revoke_api_key(db, w.actor, w.agent.id, rows[0].id)
    issued = await svc.issue_api_key(db, w.actor, w.agent.id, name="new", ttl_days=90)
    assert issued.key.state == svc.ApiKeyState.ACTIVE
    assert await key_count(db, w.agent.id) == 6  # 5 прежних (один отозван) + новый


async def test_007_ac12_expired_and_revoked_not_counted(db: AsyncSession, svc: Any) -> None:
    """Тест лимита: истёкшие (в т.ч. ровно на границе) и отозванные не считаются."""
    w = await world(db)
    await seed_active_keys(db, w, 3)
    await make_api_key(
        db,
        user=w.agent,
        created_by=w.ta,
        name="old",
        created_at=CLOCK - timedelta(days=100),
        expires_at=CLOCK - timedelta(days=10),
    )
    await make_api_key(
        db,
        user=w.agent,
        created_by=w.ta,
        name="edge",
        created_at=CLOCK - timedelta(days=100),
        expires_at=CLOCK,
    )
    await make_api_key(
        db,
        user=w.agent,
        created_by=w.ta,
        name="rev",
        created_at=CLOCK - timedelta(days=1),
        expires_at=CLOCK + timedelta(days=30),
        revoked_at=CLOCK - timedelta(hours=1),
        revoked_by=w.ta,
    )
    await db.commit()
    await svc.issue_api_key(db, w.actor, w.agent.id, name="four", ttl_days=90)
    await svc.issue_api_key(db, w.actor, w.agent.id, name="five", ttl_days=90)
    await fails(
        db,
        svc.issue_api_key(db, w.actor, w.agent.id, name="six", ttl_days=90),
        "api_key_limit_reached",
    )


async def test_007_ac12_limit_is_per_agent(db: AsyncSession, svc: Any) -> None:
    w = await world(db)
    await seed_active_keys(db, w, 5)
    issued = await svc.issue_api_key(db, w.actor, w.other.id, name="o", ttl_days=90)
    assert issued.key.state == svc.ApiKeyState.ACTIVE


# --- AC-8: перечень ---------------------------------------------------------------------


async def test_007_ac8_list_states_order_and_fields(
    db: AsyncSession, svc: Any, fixed_clock: FixedClock
) -> None:
    """AC-8/FR-7, FR-16: порядок created_at DESC; active/revoked(+revoked_at); last_used_at."""
    w = await world(db)
    used = CLOCK - timedelta(minutes=2)
    k1 = await make_api_key(
        db,
        user=w.agent,
        created_by=w.ta,
        name="used",
        created_at=CLOCK - timedelta(days=3),
        expires_at=CLOCK + timedelta(days=10),
        last_used_at=used,
    )
    k2 = await make_api_key(
        db,
        user=w.agent,
        created_by=w.ta,
        name="unused",
        created_at=CLOCK - timedelta(days=2),
        expires_at=CLOCK + timedelta(days=5),
    )
    revoked_at = CLOCK - timedelta(hours=5)
    k3 = await make_api_key(
        db,
        user=w.agent,
        created_by=w.ta,
        name="revoked",
        created_at=CLOCK - timedelta(days=1),
        expires_at=CLOCK + timedelta(days=20),
        revoked_at=revoked_at,
        revoked_by=w.ta,
    )
    # ключ другого агента в перечень не попадает
    await make_api_key(db, user=w.other, created_by=w.ta, name="foreign")
    await db.commit()

    items, has_next = await svc.list_api_keys(db, w.actor, w.agent.id, PageParams())
    assert has_next is False
    assert [v.id for v in items] == [k3.id, k2.id, k1.id]
    by = {v.id: v for v in items}
    assert by[k1.id].state == svc.ApiKeyState.ACTIVE
    assert by[k1.id].last_used_at == used
    assert by[k2.id].state == svc.ApiKeyState.ACTIVE
    assert by[k2.id].last_used_at is None
    assert by[k3.id].state == svc.ApiKeyState.REVOKED
    assert by[k3.id].revoked_at == revoked_at
    assert by[k1.id].revoked_at is None
    for v in items:
        assert isinstance(v, svc.ApiKeyView)
        assert v.created_by is not None
        assert v.created_by.id == w.ta.id
        assert v.created_by.login == "ta1"
    assert by[k1.id].name == "used"
    assert by[k2.id].created_at == CLOCK - timedelta(days=2)
    assert by[k2.id].expires_at == CLOCK + timedelta(days=5)

    # часы переведены за срок второго ключа -> «истёк»; отозванный остаётся отозванным
    fixed_clock.set(CLOCK + timedelta(days=5))
    items, _ = await svc.list_api_keys(db, w.actor, w.agent.id, PageParams())
    by = {v.id: v for v in items}
    assert by[k2.id].state == svc.ApiKeyState.EXPIRED
    assert by[k1.id].state == svc.ApiKeyState.ACTIVE
    assert by[k3.id].state == svc.ApiKeyState.REVOKED


async def test_007_ac8_state_expired_exactly_at_expires_at(
    db: AsyncSession, svc: Any, fixed_clock: FixedClock
) -> None:
    w = await world(db)
    issued = await svc.issue_api_key(db, w.actor, w.agent.id, name="k", ttl_days=1)
    fixed_clock.set(issued.key.expires_at - timedelta(seconds=1))
    (v,), _ = await svc.list_api_keys(db, w.actor, w.agent.id, PageParams())
    assert v.state == svc.ApiKeyState.ACTIVE
    fixed_clock.set(issued.key.expires_at)
    (v,), _ = await svc.list_api_keys(db, w.actor, w.agent.id, PageParams())
    assert v.state == svc.ApiKeyState.EXPIRED


async def test_007_ac8_list_has_no_secret(db: AsyncSession, svc: Any) -> None:
    """AC-8: ни в одном поле перечня нет секрета (и его подстрок от 8 символов)."""
    w = await world(db)
    issued = await svc.issue_api_key(db, w.actor, w.agent.id, name="k", ttl_days=90)
    items, _ = await svc.list_api_keys(db, w.actor, w.agent.id, PageParams())
    dump = repr(items) + str([vars(v) for v in items])
    secret = issued.secret
    windows = [secret[i : i + 8] for i in range(len(secret) - 7)]
    leaked = any(win in dump for win in windows)
    assert not leaked, "секрет или его часть в перечне"
    for v in items:
        assert not hasattr(v, "secret")
        assert not hasattr(v, "secret_digest")


async def test_007_ac8_list_pagination_and_tiebreak(db: AsyncSession, svc: Any) -> None:
    """created_at DESC, id DESC; has_next по страницам."""
    w = await world(db)
    same = CLOCK - timedelta(days=1)
    ids = []
    for i in range(3):
        r = await make_api_key(
            db,
            user=w.agent,
            created_by=w.ta,
            name=f"t{i}",
            created_at=same,
            expires_at=CLOCK + timedelta(days=9),
        )
        ids.append(r.id)
    await db.commit()
    p1, n1 = await svc.list_api_keys(db, w.actor, w.agent.id, PageParams(page=1, page_size=2))
    p2, n2 = await svc.list_api_keys(db, w.actor, w.agent.id, PageParams(page=2, page_size=2))
    assert (len(p1), n1) == (2, True)
    assert (len(p2), n2) == (1, False)
    assert [v.id for v in p1 + p2] == sorted(ids, reverse=True)


async def test_007_ac8_list_for_human_is_empty(db: AsyncSession, svc: Any) -> None:
    """PD-6: у не агента — пустой список, без ошибки."""
    w = await world(db)
    items, has_next = await svc.list_api_keys(db, w.actor, w.u1.id, PageParams())
    assert items == []
    assert has_next is False


async def test_007_ac8_list_does_not_write_audit(db: AsyncSession, svc: Any) -> None:
    w = await world(db)
    await seed_active_keys(db, w, 2)
    events = await event_count(db)
    await svc.list_api_keys(db, w.actor, w.agent.id, PageParams())
    assert await event_count(db) == events


async def test_007_ac8_list_works_for_blocked_agent(db: AsyncSession, svc: Any) -> None:
    """Перечень доступен и у заблокированного агента (история, PD-6): ошибки нет."""
    w = await world(db)
    blocked = await make_user(
        db, workspace=w.ws, role="user", login="agent.bl", is_agent=True, blocked=True
    )
    await make_api_key(
        db, user=blocked, created_by=w.ta, name="h", revoked_at=CLOCK, revoked_by=w.ta
    )
    await db.commit()
    items, _ = await svc.list_api_keys(db, w.actor, blocked.id, PageParams())
    assert len(items) == 1
    assert items[0].state == svc.ApiKeyState.REVOKED


# --- AC-9: отзыв ------------------------------------------------------------------------


async def test_007_ac9_revoke_sets_revoked_and_writes_one_event(db: AsyncSession, svc: Any) -> None:
    """AC-9/FR-8, FR-11: revoked_at/revoked_by; одна запись user.api_key_revoked."""
    w = await world(db)
    issued = await svc.issue_api_key(db, w.actor, w.agent.id, name="claude-laptop", ttl_days=90)
    before = await event_count(db)

    result = await svc.revoke_api_key(db, w.actor, w.agent.id, issued.key.id)
    assert result is None

    row = await key_row(db, issued.key.id)
    assert row.revoked_at == CLOCK
    assert row.revoked_by == w.ta.id
    assert await event_count(db) == before + 1
    (ev,) = await event_rows(db, "user.api_key_revoked")
    assert ev.actor_id == w.ta.id
    assert ev.entity_id == w.agent.id
    assert ev.entity_type == "user"
    assert ev.details == {"api_key_id": str(issued.key.id), "api_key_name": "claude-laptop"}
    leaked = issued.secret in str(ev.details) or issued.secret[4:] in str(ev.details)
    assert not leaked, "секрет в журнале"

    items, _ = await svc.list_api_keys(db, w.actor, w.agent.id, PageParams())
    assert items[0].state == svc.ApiKeyState.REVOKED
    assert items[0].revoked_at == CLOCK


async def test_007_ac9_repeat_revoke_is_noop(
    db: AsyncSession, svc: Any, fixed_clock: FixedClock
) -> None:
    """AC-9: повторный отзыв — успех, без новых записей и без изменения revoked_at."""
    w = await world(db)
    issued = await svc.issue_api_key(db, w.actor, w.agent.id, name="k", ttl_days=90)
    await svc.revoke_api_key(db, w.actor, w.agent.id, issued.key.id)
    first = await key_row(db, issued.key.id)
    events = await event_count(db)

    fixed_clock.set(CLOCK + timedelta(hours=1))
    await svc.revoke_api_key(db, w.actor, w.agent.id, issued.key.id)

    again = await key_row(db, issued.key.id)
    assert again.revoked_at == first.revoked_at == CLOCK
    assert again.revoked_by == first.revoked_by
    assert await event_count(db) == events
    assert len(await event_rows(db, "user.api_key_revoked")) == 1


async def test_007_ac9_revoke_expired_is_noop(
    db: AsyncSession, svc: Any, fixed_clock: FixedClock
) -> None:
    """plan §4.6: отзыв истёкшего — без изменений и без записи."""
    w = await world(db)
    issued = await svc.issue_api_key(db, w.actor, w.agent.id, name="k", ttl_days=1)
    fixed_clock.set(issued.key.expires_at)
    events = await event_count(db)
    await svc.revoke_api_key(db, w.actor, w.agent.id, issued.key.id)
    row = await key_row(db, issued.key.id)
    assert row.revoked_at is None
    assert row.revoked_by is None
    assert await event_count(db) == events


async def test_007_ac9_revoke_other_agents_key_404(db: AsyncSession, svc: Any) -> None:
    """Ключ другого агента по этому user_id -> 404; ключ не тронут, записи нет."""
    w = await world(db)
    foreign = await make_api_key(db, user=w.other, created_by=w.ta, name="o")
    await db.commit()
    events = await event_count(db)
    await fails(db, svc.revoke_api_key(db, w.actor, w.agent.id, foreign.id), None, status=404)
    assert (await key_row(db, foreign.id)).revoked_at is None
    assert await event_count(db) == events


async def test_007_ac9_revoke_unknown_key_or_user_404(db: AsyncSession, svc: Any) -> None:
    w = await world(db)
    await fails(db, svc.revoke_api_key(db, w.actor, w.agent.id, uuid.uuid4()), None, status=404)
    await fails(db, svc.revoke_api_key(db, w.actor, uuid.uuid4(), uuid.uuid4()), None, status=404)


async def test_007_ac9_revoke_key_from_foreign_workspace_404(db: AsyncSession, svc: Any) -> None:
    w = await world(db)
    ws2 = await make_workspace(db)
    ta2 = await make_user(db, workspace=ws2, role="tech_admin")
    agent2 = await make_user(db, workspace=ws2, role="user", is_agent=True)
    k = await make_api_key(db, user=agent2, created_by=ta2)
    await db.commit()
    await fails(db, svc.revoke_api_key(db, w.actor, agent2.id, k.id), None, status=404)
    await fails(db, svc.revoke_api_key(db, w.actor, w.agent.id, k.id), None, status=404)
    assert (await key_row(db, k.id)).revoked_at is None


async def test_007_ac9_revoke_works_for_blocked_agent(db: AsyncSession, svc: Any) -> None:
    """Отзыв не требует незаблокированного агента (ключ мог остаться только у активного, но
    ошибки user_blocked при отзыве нет)."""
    w = await world(db)
    blocked = await make_user(
        db, workspace=w.ws, role="user", login="agent.bl2", is_agent=True, blocked=True
    )
    k = await make_api_key(db, user=blocked, created_by=w.ta, expires_at=CLOCK + timedelta(days=3))
    await db.commit()
    await svc.revoke_api_key(db, w.actor, blocked.id, k.id)
    assert (await key_row(db, k.id)).revoked_at == CLOCK


# --- PD-8: протокол блокировок (гонка выпуска/отзыва с блокировкой) ---------------------


def _spy_order(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Пишет порядок вызовов lock_for_account_change и load_account в модуле users.service."""
    import app.domain.users.service as accounts

    calls: list[str] = []
    orig_lock = accounts.lock_for_account_change
    orig_load = accounts.load_account

    async def lock(db: Any, ws: Any, target: Any, actor_id: Any) -> Any:
        calls.append("lock")
        return await orig_lock(db, ws, target, actor_id)

    async def load(db: Any, ws: Any, uid: Any) -> Any:
        calls.append("load")
        return await orig_load(db, ws, uid)

    monkeypatch.setattr(accounts, "lock_for_account_change", lock)
    monkeypatch.setattr(accounts, "load_account", load)
    return calls


async def test_007_pd8_issue_locks_before_loading_account(
    db: AsyncSession, svc: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PD-8: выпуск вызывает lock_for_account_change (с рабочим пространством, агентом, ТА) ДО
    load_account, а не после."""
    import app.domain.users.service as accounts

    w = await world(db)
    args: list[tuple[Any, ...]] = []
    calls = _spy_order(monkeypatch)
    inner = accounts.lock_for_account_change

    async def both(db_: Any, ws: Any, target: Any, actor_id: Any) -> Any:
        args.append((ws, target, actor_id))
        return await inner(db_, ws, target, actor_id)

    monkeypatch.setattr(accounts, "lock_for_account_change", both)

    await svc.issue_api_key(db, w.actor, w.agent.id, name="k", ttl_days=90)

    assert calls[:2] == ["lock", "load"], f"порядок вызовов: {calls}"
    assert calls.count("lock") == 1
    assert args == [(w.ws.id, w.agent.id, w.ta.id)]


async def test_007_pd8_revoke_locks_before_loading_account(
    db: AsyncSession, svc: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PD-8: отзыв — тот же порядок lock -> load_account."""
    w = await world(db)
    (k,) = await seed_active_keys(db, w, 1)
    calls = _spy_order(monkeypatch)
    await svc.revoke_api_key(db, w.actor, w.agent.id, k.id)
    assert calls[:2] == ["lock", "load"], f"порядок вызовов: {calls}"
    assert calls.count("lock") == 1


async def test_007_pd8_forbidden_does_not_take_lock(
    db: AsyncSession, svc: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """plan §4.6: 403 и 422 validation — до блокировки (блокировка не берётся зря)."""
    w = await world(db)
    calls = _spy_order(monkeypatch)
    await fails(
        db,
        svc.issue_api_key(db, actor_of(w.ba), w.agent.id, name="k", ttl_days=90),
        None,
        status=403,
    )
    await fails(
        db,
        svc.issue_api_key(db, w.actor, w.agent.id, name="k", ttl_days=0),
        "validation_error",
    )
    assert calls == []


async def test_007_pd8_issue_reads_block_state_after_lock(
    db: AsyncSession, svc: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PD-8 (гонка): конкурентная блокировка «успевает» в БД, пока выпуск ждёт advisory-lock.
    Модель: после возврата из lock_for_account_change агент оказывается заблокированным.
    Выпуск обязан прочитать is_blocked ПОСЛЕ блокировки -> 422 user_blocked, ключа нет."""
    import app.domain.users.service as accounts

    w = await world(db)
    orig_lock = accounts.lock_for_account_change

    async def lock_then_concurrent_block(db_: Any, ws: Any, target: Any, actor_id: Any) -> Any:
        await orig_lock(db_, ws, target, actor_id)
        await db_.execute(
            text("UPDATE app_user SET is_blocked = true, blocked_at = now() WHERE id = :u"),
            {"u": target},
        )

    monkeypatch.setattr(accounts, "lock_for_account_change", lock_then_concurrent_block)
    keys, events = await key_count(db), await event_count(db)
    await fails(
        db,
        svc.issue_api_key(db, w.actor, w.agent.id, name="k", ttl_days=90),
        "user_blocked",
    )
    assert await key_count(db) == keys
    assert await event_count(db) == events


async def test_007_pd8_issue_reads_agent_flag_after_lock(
    db: AsyncSession, svc: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PD-8: is_agent тоже читается после блокировки (состояние изменилось, пока ждали)."""
    import app.domain.users.service as accounts

    w = await world(db)
    orig_lock = accounts.lock_for_account_change

    async def lock_then_change(db_: Any, ws: Any, target: Any, actor_id: Any) -> Any:
        await orig_lock(db_, ws, target, actor_id)
        await db_.execute(text("UPDATE app_user SET is_agent = false WHERE id = :u"), {"u": target})

    monkeypatch.setattr(accounts, "lock_for_account_change", lock_then_change)
    await fails(
        db,
        svc.issue_api_key(db, w.actor, w.agent.id, name="k", ttl_days=90),
        "not_an_agent",
    )
    assert await key_count(db, w.agent.id) == 0


async def test_007_pd8_limit_counted_after_lock(
    db: AsyncSession, svc: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PD-8 (гонка выпусков): подсчёт пяти действующих — после блокировки. Конкурентный выпуск
    «успевает» между входом и возвратом lock -> шестой отклоняется."""
    import app.domain.users.service as accounts

    w = await world(db)
    await seed_active_keys(db, w, 4)
    orig_lock = accounts.lock_for_account_change

    async def lock_then_other_issue(db_: Any, ws: Any, target: Any, actor_id: Any) -> Any:
        await orig_lock(db_, ws, target, actor_id)
        await make_api_key(
            db_,
            user=w.agent,
            created_by=w.ta,
            name="concurrent",
            created_at=CLOCK - timedelta(minutes=1),
            expires_at=CLOCK + timedelta(days=30),
        )

    monkeypatch.setattr(accounts, "lock_for_account_change", lock_then_other_issue)
    await fails(
        db,
        svc.issue_api_key(db, w.actor, w.agent.id, name="late", ttl_days=90),
        "api_key_limit_reached",
    )


async def test_007_pd8_revoke_reads_key_after_lock(
    db: AsyncSession, svc: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PD-8: отзыв читает состояние ключа после блокировки: если ключ уже отозван конкурентно
    (блокировкой агента), повторной записи журнала нет."""
    import app.domain.users.service as accounts

    w = await world(db)
    (k,) = await seed_active_keys(db, w, 1)
    orig_lock = accounts.lock_for_account_change

    async def lock_then_concurrent_revoke(db_: Any, ws: Any, target: Any, actor_id: Any) -> Any:
        await orig_lock(db_, ws, target, actor_id)
        await db_.execute(
            text("UPDATE api_key SET revoked_at = now(), revoked_by = :a WHERE id = :k"),
            {"a": actor_id, "k": k.id},
        )

    monkeypatch.setattr(accounts, "lock_for_account_change", lock_then_concurrent_revoke)
    events = await event_count(db)
    await svc.revoke_api_key(db, w.actor, w.agent.id, k.id)
    assert await event_count(db) == events


async def test_007_pd8_block_user_revokes_keys_and_issue_refused_after(
    db: AsyncSession, svc: Any
) -> None:
    """Согласованность с R7-T07 (PD-7): после block_user действующих ключей нет, выпуск -> 422,
    разблокировка ключи не возвращает."""
    import app.domain.users.service as accounts
    from app.domain.auth.sessions import SessionStore

    w = await world(db)
    await seed_active_keys(db, w, 2)
    store = SessionStore(
        b"unit-test-secret-key-0123456789ab",
        idle_timeout=timedelta(hours=8),
        absolute_timeout=timedelta(days=7),
    )
    await accounts.block_user(db, w.actor, store, w.agent.id)
    items, _ = await svc.list_api_keys(db, w.actor, w.agent.id, PageParams())
    assert [v.state for v in items] == [svc.ApiKeyState.REVOKED] * 2
    await fails(
        db,
        svc.issue_api_key(db, w.actor, w.agent.id, name="k", ttl_days=90),
        "user_blocked",
    )


# --- AC-38 / AC-39: секрет не утекает ---------------------------------------------------


async def test_007_ac38_issue_logs_do_not_contain_secret(
    db: AsyncSession, svc: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """AC-38/FR-32: при выпуске и отзыве в логах (все уровни) нет секрета и его подстрок >= 8."""
    w = await world(db)
    with caplog.at_level(logging.DEBUG):
        issued = await svc.issue_api_key(db, w.actor, w.agent.id, name="k", ttl_days=90)
        await svc.list_api_keys(db, w.actor, w.agent.id, PageParams())
        await svc.revoke_api_key(db, w.actor, w.agent.id, issued.key.id)
    log_text = caplog.text + "".join(str(r.args) + r.getMessage() for r in caplog.records)
    secret = issued.secret
    windows = [secret[i : i + 8] for i in range(len(secret) - 7)]
    leaked = any(win in log_text for win in windows)
    assert not leaked, "секрет или его часть в логах"


async def test_007_ac39_secret_absent_from_all_tables(db: AsyncSession, svc: Any) -> None:
    """AC-39/FR-6: после выпуска секрет и его подстроки >= 8 символов не найдены ни в одной
    таблице (текст строки), ни в bytea столбцах (сырые байты)."""
    w = await world(db)
    issued = await svc.issue_api_key(db, w.actor, w.agent.id, name="k", ttl_days=90)
    secret = issued.secret
    windows = [secret[i : i + 8] for i in range(len(secret) - 7)]
    patterns = ["%" + win.replace("_", "\\_").replace("%", "\\%") + "%" for win in windows]

    tables = [
        r[0]
        for r in (
            await db.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
        ).all()
    ]
    assert "api_key" in tables
    hit_tables: list[str] = []
    for t in tables:
        n = (
            await db.execute(
                text(f'SELECT count(*) FROM "{t}" x WHERE x::text LIKE ANY(:p)'),  # noqa: S608
                {"p": patterns},
            )
        ).scalar_one()
        if n:
            hit_tables.append(t)
    assert hit_tables == [], f"секрет найден в таблицах: {hit_tables}"

    raw = secret.encode("ascii")
    row = await key_row(db, issued.key.id)
    stored = bytes(row.secret_digest)
    assert len(stored) == 32
    has_raw = any(raw[i : i + 8] in stored for i in range(len(raw) - 7))
    assert not has_raw, "часть секрета в сыром виде в secret_digest"
