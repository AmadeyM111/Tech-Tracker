"""R7-T07: учётная запись агента — сервис (007, plan §4.5, §4.1).

AC-1, AC-2 (уровень домена), AC-4 (отзыв ключей при блокировке); FR-1, FR-2, FR-4.

Публичный интерфейс (plan §4.5), ``app.domain.users.service``::

    create_agent(db, actor, hasher, *, login, role: Role | None) -> UserAccount
    lock_for_account_change(db, workspace_id, target_id, actor_id)
    load_account(db, workspace_id, user_id) -> UserAccount        # 404 NotFound
    set_role / reset_password / block_user  (правила для агента)
    app.domain.auth.service.login: агент -> InvalidCredentials

Правило plan §4.1: результат ``create_agent``/``create_user`` проверяется сразу после записи,
в той же сессии, без refresh/expire/commit (иначе не поймать ``MissingGreenlet``).
Секреты в сообщениях assert не печатаются.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import SecretStr
from sqlalchemy import select, text

from app.domain.access.roles import Actor, Role
from tests.factories import UserRow, make_api_key, make_user, make_workspace

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.clock import FixedClock

CLOCK = datetime(2026, 11, 2, 7, 0, tzinfo=UTC)
SECRET_KEY = b"unit-test-secret-key-0123456789ab"
CHEAP: dict[str, int] = {"time_cost": 1, "memory_cost_kib": 1024, "parallelism": 1}
GUESS = "guessed-agent-password-4417"
WRONG = "definitely-wrong-password"


# --- фикстуры и помощники ---------------------------------------------------------------


@pytest.fixture
def svc() -> Any:
    import app.domain.users.service as service

    return service


@pytest.fixture
def env(fixed_clock: FixedClock) -> SimpleNamespace:
    import app.domain.auth.provider as provider
    import app.domain.auth.sessions as sessions
    from app.core.security.passwords import PasswordHasher

    fixed_clock.set(CLOCK)
    hasher = PasswordHasher(**CHEAP)
    return SimpleNamespace(
        hasher=hasher,
        provider=provider.LocalPasswordProvider(
            hasher, max_failures=5, lock_duration=timedelta(minutes=15)
        ),
        sessions=sessions.SessionStore(
            SECRET_KEY, idle_timeout=timedelta(hours=8), absolute_timeout=timedelta(days=7)
        ),
    )


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
    ta = await make_user(db, workspace=ws, role="tech_admin")
    await db.commit()
    return SimpleNamespace(ws=ws, ta=ta, actor=actor_of(ta))


async def fails(
    db: AsyncSession, awaitable: Awaitable[Any], code: str, *, status: int = 422
) -> None:
    from app.core.errors import AppError

    with pytest.raises(AppError) as info:
        await awaitable
    assert info.value.status_code == status
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


async def user_count(db: AsyncSession) -> int:
    return int((await db.execute(text("SELECT count(*) FROM app_user"))).scalar_one())


async def role_of(db: AsyncSession, user_id: uuid.UUID) -> str | None:
    res = await db.execute(
        text("SELECT role FROM workspace_member WHERE user_id = :u"), {"u": user_id}
    )
    value = res.scalar_one()
    return None if value is None else str(value)


async def is_agent_col(db: AsyncSession, user_id: uuid.UUID) -> bool:
    from app.domain.users.models import AppUser

    return bool(
        (await db.execute(select(AppUser.is_agent).where(AppUser.id == user_id))).scalar_one()
    )


async def login_error(env: SimpleNamespace, db: AsyncSession, login: str, password: str) -> Any:
    import app.domain.auth.service as auth_service
    from app.core.errors import InvalidCredentials

    with pytest.raises(InvalidCredentials) as info:
        await auth_service.login(
            db,
            env.provider,
            env.sessions,
            login=login,
            password=SecretStr(password),
            now=CLOCK,
        )
    await db.rollback()
    exc = info.value
    return (
        type(exc),
        exc.status_code,
        str(exc.code),
        getattr(exc, "detail", None),
        str(exc),
    )


async def keys_state(db: AsyncSession, user_id: uuid.UUID) -> dict[uuid.UUID, Any]:
    res = await db.execute(
        text("SELECT id, revoked_at, revoked_by FROM api_key WHERE user_id = :u"),
        {"u": user_id},
    )
    return {row.id: row for row in res.all()}


# --- AC-1: создание агента ----------------------------------------------------------------


async def test_007_ac1_create_agent_result_immediately_after_write(
    db: AsyncSession, svc: Any, env: SimpleNamespace
) -> None:
    """AC-1/FR-1: результат сразу после записи (без refresh/commit), затем повторные выборки."""
    w = await world(db)
    result = await svc.create_agent(db, w.actor, env.hasher, login="Review-Bot", role=Role.USER)

    assert result.is_agent is True
    assert result.role == Role.USER
    assert result.must_change_password is False
    assert result.is_blocked is False
    assert result.login == "Review-Bot"

    loaded = await svc.load_account(db, w.ws.id, result.id)
    assert loaded.is_agent is True
    assert loaded.role == Role.USER
    assert loaded.must_change_password is False
    assert loaded.login == "Review-Bot"
    assert await is_agent_col(db, result.id) is True
    assert await role_of(db, result.id) == "user"


async def test_007_ac1_agent_password_hash_is_random_and_not_stored(
    db: AsyncSession, svc: Any, env: SimpleNamespace
) -> None:
    """AC-1/PD-4: у агента есть валидный Argon2-хеш случайного значения; у двух агентов разный."""
    w = await world(db)
    a = await svc.create_agent(db, w.actor, env.hasher, login="bot-one", role=None)
    b = await svc.create_agent(db, w.actor, env.hasher, login="bot-two", role=None)
    rows = (
        await db.execute(
            text("SELECT password_hash FROM app_user WHERE id IN (:a, :b)"),
            {"a": a.id, "b": b.id},
        )
    ).all()
    hashes = {r.password_hash for r in rows}
    assert len(hashes) == 2
    assert all(h.startswith("$argon2") for h in hashes), "хеш агента не Argon2"


async def test_007_ac1_exactly_one_agent_created_event(
    db: AsyncSession, svc: Any, env: SimpleNamespace
) -> None:
    """AC-1/FR-4: ровно одно новое событие user.agent_created, details.role_to='user'."""
    w = await world(db)
    before = await event_count(db)
    result = await svc.create_agent(db, w.actor, env.hasher, login="bot-ev", role=Role.USER)

    assert await event_count(db) == before + 1
    (ev,) = await event_rows(db, "user.agent_created")
    assert ev.entity_id == result.id
    assert ev.actor_id == w.ta.id
    assert ev.workspace_id == w.ws.id
    assert ev.entity_type == "user"
    assert ev.details == {"role_to": "user"}


async def test_007_ac1_human_created_right_after_write_is_not_agent(
    db: AsyncSession, svc: Any, env: SimpleNamespace
) -> None:
    """AC-1: create_user сразу после записи -> is_agent False (без MissingGreenlet)."""
    w = await world(db)
    agent = await svc.create_agent(db, w.actor, env.hasher, login="bot-pair", role=None)
    human = await svc.create_user(
        db, w.actor, env.hasher, login="human-pair", one_time_password=SecretStr("zq9-lk3-px7k")
    )
    assert agent.is_agent is True
    assert human.is_agent is False
    assert await is_agent_col(db, human.id) is False
    assert await is_agent_col(db, agent.id) is True


async def test_007_ac1_list_accounts_in_same_session_shows_agent_flag(
    db: AsyncSession, svc: Any, env: SimpleNamespace
) -> None:
    """Заметка ревью R7-T05/T06: identity map — list_accounts после create_agent в той же сессии."""
    from app.core.pagination import PageParams

    w = await world(db)
    agent = await svc.create_agent(db, w.actor, env.hasher, login="bot-list", role=None)
    items, _ = await svc.list_accounts(db, w.actor, PageParams())
    by_id = {a.id: a for a in items}
    assert by_id[agent.id].is_agent is True
    assert by_id[w.ta.id].is_agent is False


@pytest.mark.parametrize("role", [None, Role.BUSINESS_ADMIN])
async def test_007_ac1_create_agent_without_role_and_business_admin(
    db: AsyncSession, svc: Any, env: SimpleNamespace, role: Role | None
) -> None:
    """FR-2: роль не задана или БА допустимы; в событии role_to соответствует."""
    w = await world(db)
    result = await svc.create_agent(db, w.actor, env.hasher, login="bot-role", role=role)
    assert result.is_agent is True
    assert result.role == role
    assert await role_of(db, result.id) == (None if role is None else role.value)
    (ev,) = await event_rows(db, "user.agent_created")
    assert ev.details == {"role_to": None if role is None else role.value}


async def test_007_ac1_login_invalid(db: AsyncSession, svc: Any, env: SimpleNamespace) -> None:
    w = await world(db)
    before_users, before_events = await user_count(db), await event_count(db)
    await fails(
        db,
        svc.create_agent(db, w.actor, env.hasher, login="bad login!", role=None),
        "login_invalid",
    )
    assert await user_count(db) == before_users
    assert await event_count(db) == before_events


async def test_007_ac1_login_taken_case_insensitive_and_global(
    db: AsyncSession, svc: Any, env: SimpleNamespace
) -> None:
    w = await world(db)
    other_ws = await make_workspace(db)
    foreign = await make_user(db, workspace=other_ws, login="Taken-Elsewhere")
    mine = await make_user(db, workspace=w.ws, login="Taken-Here")
    await db.commit()
    before = await event_count(db)

    await fails(
        db, svc.create_agent(db, w.actor, env.hasher, login="taken-here", role=None), "login_taken"
    )
    await fails(
        db,
        svc.create_agent(db, w.actor, env.hasher, login=foreign.login.upper(), role=None),
        "login_taken",
    )
    assert mine.id is not None
    assert await event_count(db) == before


@pytest.mark.parametrize("who", ["business_admin", "user", None])
async def test_007_ac1_create_agent_forbidden_for_non_tech_admin(
    db: AsyncSession, svc: Any, env: SimpleNamespace, who: str | None
) -> None:
    """FR-1: БА/П/без роли -> 403, записей и событий нет."""
    w = await world(db)
    caller = await make_user(db, workspace=w.ws, role=who)
    await db.commit()
    before_users, before_events = await user_count(db), await event_count(db)
    await fails(
        db,
        svc.create_agent(db, actor_of(caller), env.hasher, login="bot-403", role=None),
        "forbidden",
        status=403,
    )
    assert await user_count(db) == before_users
    assert await event_count(db) == before_events


# --- AC-1: агент не входит ----------------------------------------------------------------


async def test_007_ac1_created_agent_cannot_login(
    db: AsyncSession, svc: Any, env: SimpleNamespace
) -> None:
    """AC-1: вход созданного агента с любым паролем = отказ как при неверном пароле человека."""
    w = await world(db)
    human = await make_user(db, workspace=w.ws, login="human-login", password="human-pass-12345")
    agent = await svc.create_agent(db, w.actor, env.hasher, login="bot-login", role=Role.USER)
    await db.commit()

    human_sig = await login_error(env, db, human.login, WRONG)
    for password in (WRONG, GUESS, "", "x" * 12):
        assert await login_error(env, db, agent.login, password) == human_sig


async def test_007_ac1_agent_with_known_password_cannot_login(
    db: AsyncSession, env: SimpleNamespace
) -> None:
    """AC-1/FR-1: даже с «угаданным» верным паролем агент получает InvalidCredentials."""
    w = await world(db)
    human = await make_user(db, workspace=w.ws, login="human-ref", password="human-pass-12345")
    agent = await make_user(
        db, workspace=w.ws, login="agent-known", password=GUESS, role="user", is_agent=True
    )
    await db.commit()
    human_sig = await login_error(env, db, human.login, WRONG)
    assert await login_error(env, db, agent.login, GUESS) == human_sig


async def test_007_ac1_human_with_correct_password_still_logs_in(
    db: AsyncSession, env: SimpleNamespace
) -> None:
    """Контроль: вход человека не сломан правкой login()."""
    import app.domain.auth.service as auth_service

    w = await world(db)
    human = await make_user(db, workspace=w.ws, login="human-ok", password="human-pass-12345")
    await db.commit()
    result = await auth_service.login(
        db,
        env.provider,
        env.sessions,
        login=human.login,
        password=SecretStr("human-pass-12345"),
        now=CLOCK,
    )
    assert result is not None


async def test_007_ac1_reset_password_for_agent_rejected(
    db: AsyncSession, svc: Any, env: SimpleNamespace
) -> None:
    """FR-1: reset_password агента -> 422 agent_password_not_allowed, события не пишутся."""
    w = await world(db)
    agent = await svc.create_agent(db, w.actor, env.hasher, login="bot-reset", role=None)
    await db.commit()
    hash_before = (
        await db.execute(text("SELECT password_hash FROM app_user WHERE id = :u"), {"u": agent.id})
    ).scalar_one()
    before = await event_count(db)

    await fails(
        db,
        svc.reset_password(
            db,
            w.actor,
            env.hasher,
            env.sessions,
            agent.id,
            one_time_password=SecretStr("zq9-lk3-px7k"),
        ),
        "agent_password_not_allowed",
    )
    assert await event_count(db) == before
    hash_after = (
        await db.execute(text("SELECT password_hash FROM app_user WHERE id = :u"), {"u": agent.id})
    ).scalar_one()
    assert hash_after == hash_before


async def test_007_ac1_reset_password_unknown_user_is_404_before_agent_check(
    db: AsyncSession, svc: Any, env: SimpleNamespace
) -> None:
    """plan §4.5: порядок — 404 раньше agent_password_not_allowed."""
    from app.core.errors import AppError

    w = await world(db)
    with pytest.raises(AppError) as info:
        await svc.reset_password(
            db,
            w.actor,
            env.hasher,
            env.sessions,
            uuid.uuid4(),
            one_time_password=SecretStr("zq9-lk3-px7k"),
        )
    assert info.value.status_code == 404
    await db.rollback()


async def test_007_ac1_reset_password_for_human_still_works(
    db: AsyncSession, svc: Any, env: SimpleNamespace
) -> None:
    w = await world(db)
    human = await make_user(db, workspace=w.ws, role="user")
    await svc.reset_password(
        db, w.actor, env.hasher, env.sessions, human.id, one_time_password=SecretStr("zq9-lk3-px7k")
    )
    assert len(await event_rows(db, "user.password_reset")) == 1


# --- AC-2: роль агента --------------------------------------------------------------------


async def test_007_ac2_create_agent_tech_admin_rejected(
    db: AsyncSession, svc: Any, env: SimpleNamespace
) -> None:
    """AC-2/FR-2: create_agent(role=ТА) -> 422 agent_role_not_allowed, записи и события нет."""
    w = await world(db)
    before_users, before_events = await user_count(db), await event_count(db)
    await fails(
        db,
        svc.create_agent(db, w.actor, env.hasher, login="bot-ta", role=Role.TECH_ADMIN),
        "agent_role_not_allowed",
    )
    assert await user_count(db) == before_users
    assert await event_count(db) == before_events


async def test_007_ac2_set_role_tech_admin_for_agent_rejected(
    db: AsyncSession, svc: Any, env: SimpleNamespace
) -> None:
    """AC-2: set_role(agent, ТА) -> 422, роль остаётся П, событий нет."""
    w = await world(db)
    agent = await svc.create_agent(db, w.actor, env.hasher, login="bot-setrole", role=Role.USER)
    await db.commit()
    before = await event_count(db)

    await fails(db, svc.set_role(db, w.actor, agent.id, Role.TECH_ADMIN), "agent_role_not_allowed")
    assert await role_of(db, agent.id) == "user"
    assert await event_count(db) == before


async def test_007_ac2_set_role_user_business_admin_user_for_agent(
    db: AsyncSession, svc: Any, env: SimpleNamespace
) -> None:
    """AC-2: П -> БА -> П выполнимо; для каждого перехода одно событие."""
    w = await world(db)
    agent = await svc.create_agent(db, w.actor, env.hasher, login="bot-cycle", role=Role.USER)
    before = await event_count(db)

    await svc.set_role(db, w.actor, agent.id, Role.BUSINESS_ADMIN)
    assert await role_of(db, agent.id) == "business_admin"
    await svc.set_role(db, w.actor, agent.id, Role.USER)
    assert await role_of(db, agent.id) == "user"
    assert await event_count(db) == before + 2
    assert (await svc.load_account(db, w.ws.id, agent.id)).is_agent is True


async def test_007_ac2_set_role_tech_admin_for_human_still_works(
    db: AsyncSession, svc: Any
) -> None:
    """Контроль: человеку роль ТА назначается как прежде."""
    w = await world(db)
    human = await make_user(db, workspace=w.ws, role="user")
    await svc.set_role(db, w.actor, human.id, Role.TECH_ADMIN)
    assert await role_of(db, human.id) == "tech_admin"


# --- публичные lock_for_account_change и load_account -------------------------------------


async def test_007_load_account_not_found_and_foreign_workspace(
    db: AsyncSession, svc: Any, env: SimpleNamespace
) -> None:
    """plan §4.5: load_account -> 404 для неизвестного и чужого пространства."""
    from app.core.errors import AppError

    w = await world(db)
    other = await make_user(db, workspace=await make_workspace(db), role="user")
    for target in (uuid.uuid4(), other.id):
        with pytest.raises(AppError) as info:
            await svc.load_account(db, w.ws.id, target)
        assert info.value.status_code == 404
        await db.rollback()
        w = await world(db)


async def test_007_lock_for_account_change_is_public_and_callable(
    db: AsyncSession, svc: Any, env: SimpleNamespace
) -> None:
    """plan §4.5: публичный lock_for_account_change(db, workspace_id, target_id, actor_id)."""
    w = await world(db)
    agent = await svc.create_agent(db, w.actor, env.hasher, login="bot-lock", role=None)
    assert (await svc.lock_for_account_change(db, w.ws.id, agent.id, w.ta.id)) is None


async def test_007_lock_for_account_change_delegates_to_private(
    db: AsyncSession, svc: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Публичная функция вызывает _lock_for_account_change с теми же аргументами."""
    calls: list[tuple[Any, ...]] = []

    async def spy(db_: Any, ws: Any, target: Any, actor: Any) -> None:
        calls.append((ws, target, actor))

    monkeypatch.setattr(svc, "_lock_for_account_change", spy)
    ws_id, target_id, actor_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await svc.lock_for_account_change(db, ws_id, target_id, actor_id)
    assert calls == [(ws_id, target_id, actor_id)]


# --- AC-4: блокировка агента отзывает ключи -----------------------------------------------


async def test_007_ac4_block_agent_revokes_active_keys_only(
    db: AsyncSession, svc: Any, env: SimpleNamespace
) -> None:
    """AC-4/PD-7: действующие ключи отозваны (revoked_at=сейчас, revoked_by=ТА); истёкший и
    отозванный не тронуты; одно событие user.blocked."""
    w = await world(db)
    other_ta = await make_user(db, workspace=w.ws, role="tech_admin")
    agent = await make_user(db, workspace=w.ws, role="user", is_agent=True)
    created = CLOCK - timedelta(days=30)
    active1 = await make_api_key(
        db, user=agent, created_by=w.ta, created_at=created, expires_at=CLOCK + timedelta(days=5)
    )
    active2 = await make_api_key(
        db, user=agent, created_by=w.ta, created_at=created, expires_at=CLOCK + timedelta(days=60)
    )
    expired = await make_api_key(
        db, user=agent, created_by=w.ta, created_at=created, expires_at=CLOCK - timedelta(days=1)
    )
    old_revoked_at = CLOCK - timedelta(days=3)
    revoked = await make_api_key(
        db,
        user=agent,
        created_by=w.ta,
        created_at=created,
        expires_at=CLOCK + timedelta(days=60),
        revoked_at=old_revoked_at,
        revoked_by=other_ta,
    )
    before = await event_count(db)

    await svc.block_user(db, w.actor, env.sessions, agent.id)

    state = await keys_state(db, agent.id)
    for key in (active1, active2):
        assert state[key.id].revoked_at == CLOCK
        assert state[key.id].revoked_by == w.ta.id
    assert state[expired.id].revoked_at is None
    assert state[expired.id].revoked_by is None
    assert state[revoked.id].revoked_at == old_revoked_at
    assert state[revoked.id].revoked_by == other_ta.id

    assert await event_count(db) == before + 1
    (ev,) = await event_rows(db, "user.blocked")
    assert ev.entity_id == agent.id
    assert ev.actor_id == w.ta.id


async def test_007_ac4_unblock_agent_does_not_restore_keys(
    db: AsyncSession, svc: Any, env: SimpleNamespace
) -> None:
    """AC-4: разблокировка revoked_at не меняет."""
    w = await world(db)
    agent = await make_user(db, workspace=w.ws, role="user", is_agent=True)
    key = await make_api_key(
        db,
        user=agent,
        created_by=w.ta,
        created_at=CLOCK - timedelta(days=1),
        expires_at=CLOCK + timedelta(days=30),
    )
    await svc.block_user(db, w.actor, env.sessions, agent.id)
    blocked_state = (await keys_state(db, agent.id))[key.id]
    assert blocked_state.revoked_at == CLOCK

    await svc.unblock_user(db, w.actor, agent.id)
    after = (await keys_state(db, agent.id))[key.id]
    assert after.revoked_at == blocked_state.revoked_at
    assert after.revoked_by == w.ta.id


async def test_007_ac4_block_human_leaves_other_users_keys_untouched(
    db: AsyncSession, svc: Any, env: SimpleNamespace
) -> None:
    """Блокировка человека не отзывает ключи чужого агента."""
    w = await world(db)
    agent = await make_user(db, workspace=w.ws, role="user", is_agent=True)
    human = await make_user(db, workspace=w.ws, role="user")
    key = await make_api_key(
        db,
        user=agent,
        created_by=w.ta,
        created_at=CLOCK - timedelta(days=1),
        expires_at=CLOCK + timedelta(days=30),
    )
    await svc.block_user(db, w.actor, env.sessions, human.id)
    assert (await keys_state(db, agent.id))[key.id].revoked_at is None


async def test_007_ac4_repeat_block_of_agent_is_noop(
    db: AsyncSession, svc: Any, env: SimpleNamespace
) -> None:
    """Повторная блокировка агента — без второго события и без перезаписи revoked_at."""
    w = await world(db)
    agent = await make_user(db, workspace=w.ws, role="user", is_agent=True)
    key = await make_api_key(
        db,
        user=agent,
        created_by=w.ta,
        created_at=CLOCK - timedelta(days=1),
        expires_at=CLOCK + timedelta(days=30),
    )
    await svc.block_user(db, w.actor, env.sessions, agent.id)
    before = await event_count(db)
    await svc.block_user(db, w.actor, env.sessions, agent.id)
    assert await event_count(db) == before
    assert (await keys_state(db, agent.id))[key.id].revoked_at == CLOCK
