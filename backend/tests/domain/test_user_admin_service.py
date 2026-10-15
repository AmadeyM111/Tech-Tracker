"""T16: сервис учётных записей и ролей (plan §4.6 «Сервис учётных записей», §4.4, §4.5).

AC-26, AC-39, AC-44, AC-45, AC-64, AC-67, AC-75, AC-78, AC-113, AC-116, AC-121, AC-21;
FR-4, FR-5, FR-5a, FR-12, FR-55, FR-57, FR-62, FR-65, FR-66, FR-67, FR-69, FR-73; BR-2.
Заметки ревью T11 (единый шаблон логина), T14 (две ветки change_own_password), T15 (ValueError).

Публичный интерфейс (plan §4.6), модуль ``app.domain.users.service``::

    create_user(db, actor, hasher, *, login, one_time_password: SecretStr)
    block_user(db, actor, sessions, user_id) / unblock_user(db, actor, user_id)
    reset_password(db, actor, hasher, sessions, user_id, *, one_time_password)
    revoke_sessions(db, actor, sessions, user_id) -> int
    set_role(db, actor, user_id, role: Role | None)
    ensure_account_admin_remains(db, workspace_id)

Допущения (не закреплены в plan дословно, см. отчёт):
- проверка прав на уровне сервиса: ``actor.can(MANAGE_ACCOUNTS)`` (``set_role`` —
  ``ASSIGN_ROLES``), иначе ``Forbidden`` (403) ДО загрузки объекта (plan §4.5, п.4 < п.6);
- повторная блокировка заблокированного и разблокировка активного — без ошибки и без события;
- «транзакция запроса» моделируется так: данные теста фиксируются ``db.commit()`` (освобождает
  SAVEPOINT), при исключении сервиса тест делает ``db.rollback()``, как ``get_db``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import SecretStr
from sqlalchemy import select, text

from app.domain.access.roles import Actor, Role
from tests.db_support import BACKEND_DIR
from tests.factories import UserRow, make_user, make_workspace

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.core.clock import FixedClock
    from app.core.config import Settings

NOW = datetime(2026, 10, 13, 9, 0, 0, tzinfo=UTC)
SECRET_KEY = b"unit-test-secret-key-0123456789ab"
CHEAP: dict[str, int] = {"time_cost": 1, "memory_cost_kib": 1024, "parallelism": 1}
OLD_PASSWORD = "correct-horse-battery-staple"
ONE_TIME = "one-time-secret-7734-xq"
ONE_TIME_2 = "another-one-time-5521-zp"
WRONG = "definitely-wrong-password"
SHORT_11 = "zq9-lk3-px7"
OK_12 = "zq9-lk3-px7k"
SURROGATE = "abc\ud800" * 5
LOCK = timedelta(minutes=15)
ALL_USER_ACTIONS = (
    "user.created",
    "user.blocked",
    "user.unblocked",
    "user.password_reset",
    "user.sessions_revoked",
    "user.role_assigned",
    "user.role_changed",
    "user.role_removed",
)


# --- фикстуры и помощники ---------------------------------------------------------------


@pytest.fixture
def svc() -> Any:
    import app.domain.users.service as service

    return service


@pytest.fixture
def mods() -> SimpleNamespace:
    import app.domain.auth.provider as provider
    import app.domain.auth.service as auth_service
    import app.domain.auth.sessions as sessions
    from app.core import errors
    from app.core.security.passwords import PasswordHasher

    return SimpleNamespace(
        provider=provider,
        auth_service=auth_service,
        sessions=sessions,
        errors=errors,
        Hasher=PasswordHasher,
    )


@pytest.fixture
def env(mods: SimpleNamespace, fixed_clock: FixedClock, settings: Settings) -> SimpleNamespace:
    hasher = mods.Hasher(**CHEAP)
    provider = mods.provider.LocalPasswordProvider(hasher, max_failures=5, lock_duration=LOCK)
    store = mods.sessions.SessionStore(
        SECRET_KEY, idle_timeout=timedelta(hours=8), absolute_timeout=timedelta(days=7)
    )
    return SimpleNamespace(hasher=hasher, provider=provider, sessions=store, settings=settings)


def actor_of(user: UserRow, *, role: str | None | object = ...) -> Actor:
    the_role = user.role if role is ... else role
    return Actor(
        user_id=user.id,
        workspace_id=user.workspace_id,
        login=user.login,
        role=Role(the_role) if the_role is not None else None,  # type: ignore[arg-type]
        must_change_password=False,
        session_id=b"\x01" * 32,
    )


async def fails(
    db: AsyncSession, awaitable: Awaitable[Any], code: str, *, status: int = 422
) -> BaseException:
    """Сервис бросает AppError с кодом; затем откат, как у ``get_db``."""
    from app.core.errors import AppError

    with pytest.raises(AppError) as info:
        await awaitable
    exc = info.value
    assert exc.status_code == status
    assert str(exc.code) == code
    await db.rollback()
    return exc


async def forbidden(db: AsyncSession, awaitable: Awaitable[Any]) -> None:
    await fails(db, awaitable, "forbidden", status=403)


async def not_found(db: AsyncSession, awaitable: Awaitable[Any]) -> None:
    from app.core.errors import AppError

    with pytest.raises(AppError) as info:
        await awaitable
    assert info.value.status_code == 404
    await db.rollback()


async def events(db: AsyncSession, workspace_id: uuid.UUID | None = None) -> list[Any]:
    sql = (
        "SELECT id, workspace_id, actor_id, entity_type, entity_id, action, in_audit, "
        "changed_fields, details, changes, project_id, deal_id FROM domain_event"
    )
    params: dict[str, Any] = {}
    if workspace_id is not None:
        sql += " WHERE workspace_id = :w"
        params["w"] = workspace_id
    res = await db.execute(text(sql + " ORDER BY id"), params)
    return list(res.all())


async def member_role(db: AsyncSession, user_id: uuid.UUID) -> str | None:
    res = await db.execute(
        text("SELECT role FROM workspace_member WHERE user_id = :u"), {"u": user_id}
    )
    value = res.scalar_one()
    return value if value is None else str(value)


async def state(db: AsyncSession, user_id: uuid.UUID) -> Any:
    res = await db.execute(
        text(
            "SELECT is_blocked, must_change_password, password_hash, failed_login_count, "
            "login_locked_until FROM app_user WHERE id = :u"
        ),
        {"u": user_id},
    )
    return res.one()


async def user_by_login(db: AsyncSession, login: str) -> Any:
    res = await db.execute(
        text(
            "SELECT u.id, u.login, u.password_hash, u.must_change_password, u.is_blocked, "
            "m.role, m.workspace_id FROM app_user u JOIN workspace_member m ON m.user_id = u.id "
            "WHERE u.login = :l"
        ),
        {"l": login},
    )
    return res.one_or_none()


async def count_sessions(db: AsyncSession, user_id: uuid.UUID) -> int:
    res = await db.execute(
        text("SELECT count(*) FROM user_session WHERE user_id = :u"), {"u": user_id}
    )
    return int(res.scalar_one())


async def open_sessions(
    db: AsyncSession, env: SimpleNamespace, user: UserRow, n: int = 2
) -> list[str]:
    return [
        await env.sessions.create(db, user_id=user.id, workspace_id=user.workspace_id, now=NOW)
        for _ in range(n)
    ]


async def login_as(
    db: AsyncSession, env: SimpleNamespace, mods: SimpleNamespace, login: str, password: str
) -> Any:
    return await mods.auth_service.login(
        db, env.provider, env.sessions, login=login, password=SecretStr(password), now=NOW
    )


async def world(db: AsyncSession) -> SimpleNamespace:
    """Пространство: ТА-актор, второй активный ТА (не используется как «последний»), цель."""
    ws = await make_workspace(db)
    admin = await make_user(db, workspace=ws, role="tech_admin", login="admin.main")
    target = await make_user(db, workspace=ws, role="user", login="target.user")
    await db.commit()
    return SimpleNamespace(ws=ws, admin=admin, actor=actor_of(admin), target=target)


async def spy_hash_not_in(db: AsyncSession, *secrets: str) -> None:
    """Пароли и их производные не лежат ни в одном поле событий (FR-57, AC-113)."""
    for row in await events(db):
        blob = repr(tuple(row))
        for secret in secrets:
            assert secret not in blob


# --- create_user: AC-121, AC-64, FR-4, FR-55, FR-66 -------------------------------------


async def test_ac121_create_user_has_no_role_and_one_time_password_flag(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    w = await world(db)
    created = await svc.create_user(
        db, w.actor, env.hasher, login="ivan.petrov", one_time_password=SecretStr(ONE_TIME)
    )
    row = await user_by_login(db, "ivan.petrov")
    assert row is not None
    assert created.id == row.id
    assert row.role is None
    assert row.workspace_id == w.ws.id
    assert row.must_change_password is True
    assert row.is_blocked is False


async def test_ac113_one_time_password_stored_only_as_argon2id_hash(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    w = await world(db)
    await svc.create_user(
        db, w.actor, env.hasher, login="ivan.petrov", one_time_password=SecretStr(ONE_TIME)
    )
    row = await user_by_login(db, "ivan.petrov")
    assert row.password_hash.startswith("$argon2id$")
    assert ONE_TIME not in row.password_hash
    assert env.hasher.verify(row.password_hash, ONE_TIME)
    assert not env.hasher.verify(row.password_hash, OLD_PASSWORD)


async def test_ac113_created_user_can_log_in_with_one_time_password_and_has_no_role(
    db: AsyncSession, env: SimpleNamespace, svc: Any, mods: SimpleNamespace
) -> None:
    w = await world(db)
    await svc.create_user(
        db, w.actor, env.hasher, login="ivan.petrov", one_time_password=SecretStr(ONE_TIME)
    )
    result = await login_as(db, env, mods, "ivan.petrov", ONE_TIME)
    assert result.must_change_password is True
    assert result.role is None


async def test_ac121_ac64_create_writes_exactly_one_user_created_event(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    w = await world(db)
    created = await svc.create_user(
        db, w.actor, env.hasher, login="ivan.petrov", one_time_password=SecretStr(ONE_TIME)
    )
    rows = await events(db, w.ws.id)
    assert len(rows) == 1
    ev = rows[0]
    assert ev.action == "user.created"
    assert ev.entity_type == "user"
    assert ev.entity_id == created.id
    assert ev.actor_id == w.admin.id
    assert ev.in_audit is True
    assert ev.workspace_id == w.ws.id
    await spy_hash_not_in(db, ONE_TIME, "$argon2")


async def test_ac116_login_is_lowercased_on_create(
    db: AsyncSession, env: SimpleNamespace, svc: Any, mods: SimpleNamespace
) -> None:
    w = await world(db)
    created = await svc.create_user(
        db, w.actor, env.hasher, login="Ivan.Petrov", one_time_password=SecretStr(ONE_TIME)
    )
    assert created.login == "ivan.petrov"
    assert await user_by_login(db, "ivan.petrov") is not None
    assert (await login_as(db, env, mods, "IVAN.PETROV", ONE_TIME)).login == "ivan.petrov"


@pytest.mark.parametrize(
    "bad",
    [
        "ab",
        "a" * 65,
        ".ivan",
        "-ivan",
        "_ivan",
        "ivan petrov",
        " ivan",
        "ivan ",
        "иван",
        "Kivan",  # знак Кельвина: lower() дал бы 'k' (FR-73, ASCII-only)
        "ivanK",
        "ivan\x00",
        "\x00ivan",
        "ivan\n",
        "iv@n",
        "",
    ],
)
async def test_ac116_invalid_login_is_rejected_without_side_effects(
    db: AsyncSession, env: SimpleNamespace, svc: Any, bad: str
) -> None:
    w = await world(db)
    before = await events(db)
    count_before = (await db.execute(text("SELECT count(*) FROM app_user"))).scalar_one()
    await fails(
        db,
        svc.create_user(db, w.actor, env.hasher, login=bad, one_time_password=SecretStr(ONE_TIME)),
        "login_invalid",
    )
    assert (await db.execute(text("SELECT count(*) FROM app_user"))).scalar_one() == count_before
    assert await events(db) == before


@pytest.mark.parametrize("good", ["abc", "a" * 64, "0day", "a.b-c_d", "IVAN"])
async def test_ac116_boundary_valid_logins_are_accepted(
    db: AsyncSession, env: SimpleNamespace, svc: Any, good: str
) -> None:
    w = await world(db)
    created = await svc.create_user(
        db, w.actor, env.hasher, login=good, one_time_password=SecretStr(ONE_TIME)
    )
    assert created.login == good.lower()


@pytest.mark.parametrize("attempt", ["ivan.petrov", "Ivan.Petrov", "IVAN.PETROV"])
async def test_ac116_taken_login_incl_case_variant_is_login_taken(
    db: AsyncSession, env: SimpleNamespace, svc: Any, attempt: str
) -> None:
    w = await world(db)
    await make_user(db, workspace=w.ws, role="user", login="ivan.petrov")
    await db.commit()
    before = await events(db)
    await fails(
        db,
        svc.create_user(
            db, w.actor, env.hasher, login=attempt, one_time_password=SecretStr(ONE_TIME)
        ),
        "login_taken",
    )
    assert await events(db) == before


async def test_ac116_login_taken_by_user_of_other_workspace(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    w = await world(db)
    await make_user(db, role="user", login="ivan.petrov")  # другое пространство
    await db.commit()
    await fails(
        db,
        svc.create_user(
            db, w.actor, env.hasher, login="ivan.petrov", one_time_password=SecretStr(ONE_TIME)
        ),
        "login_taken",
    )


async def test_ac27_one_time_password_of_11_chars_is_too_short(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    w = await world(db)
    before = await events(db)
    await fails(
        db,
        svc.create_user(
            db, w.actor, env.hasher, login="ivan.petrov", one_time_password=SecretStr(SHORT_11)
        ),
        "password_too_short",
    )
    assert await user_by_login(db, "ivan.petrov") is None
    assert await events(db) == before


async def test_ac27_one_time_password_of_12_chars_is_accepted(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    w = await world(db)
    await svc.create_user(
        db, w.actor, env.hasher, login="ivan.petrov", one_time_password=SecretStr(OK_12)
    )
    assert await user_by_login(db, "ivan.petrov") is not None


async def test_ac28_common_one_time_password_is_rejected(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    path = BACKEND_DIR / "app" / "core" / "security" / "data" / "common-passwords-10k.txt"
    common = next(
        e
        for e in path.read_text(encoding="utf-8").split("\n")
        if len(e) >= 12 and e != OLD_PASSWORD
    )
    w = await world(db)
    await fails(
        db,
        svc.create_user(
            db, w.actor, env.hasher, login="ivan.petrov", one_time_password=SecretStr(common)
        ),
        "password_too_common",
    )
    assert await user_by_login(db, "ivan.petrov") is None


async def test_t08_note_surrogate_one_time_password_is_422_not_500(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    from app.core.errors import AppError

    w = await world(db)
    with pytest.raises(AppError) as info:
        await svc.create_user(
            db, w.actor, env.hasher, login="ivan.petrov", one_time_password=SecretStr(SURROGATE)
        )
    assert info.value.status_code == 422
    await db.rollback()
    assert await user_by_login(db, "ivan.petrov") is None


# --- доступ (FR-4, FR-12, AC-26, AC-39, AC-44, AC-45) -----------------------------------


@pytest.mark.parametrize("role", ["business_admin", "user", None])
async def test_ac39_ac44_ac45_non_account_admins_get_403_on_every_account_action(
    db: AsyncSession, env: SimpleNamespace, svc: Any, role: str | None
) -> None:
    w = await world(db)
    outsider = await make_user(db, workspace=w.ws, role=role, login="outsider.x")
    victim = await make_user(db, workspace=w.ws, role="business_admin", login="victim.x")
    token = (await open_sessions(db, env, victim, 1))[0]
    await db.commit()
    actor = actor_of(outsider)
    before = await events(db)

    await forbidden(
        db,
        svc.create_user(
            db, actor, env.hasher, login="new.user", one_time_password=SecretStr(ONE_TIME)
        ),
    )
    await forbidden(db, svc.block_user(db, actor, env.sessions, victim.id))
    await forbidden(db, svc.unblock_user(db, actor, victim.id))
    await forbidden(
        db,
        svc.reset_password(
            db, actor, env.hasher, env.sessions, victim.id, one_time_password=SecretStr(ONE_TIME)
        ),
    )
    await forbidden(db, svc.revoke_sessions(db, actor, env.sessions, victim.id))
    await forbidden(db, svc.set_role(db, actor, victim.id, Role.USER))
    await forbidden(db, svc.set_role(db, actor, outsider.id, Role.MIXED))  # себе — тоже 403

    assert await user_by_login(db, "new.user") is None
    assert (await state(db, victim.id)).is_blocked is False
    assert await member_role(db, victim.id) == "business_admin"
    assert await member_role(db, outsider.id) == role
    assert await env.sessions.resolve(db, token, now=NOW, background=True) is not None
    assert await events(db) == before


@pytest.mark.parametrize("role", ["tech_admin", "mixed"])
async def test_ac26_tech_admin_and_mixed_can_run_account_actions(
    db: AsyncSession, env: SimpleNamespace, svc: Any, role: str
) -> None:
    w = await world(db)
    boss = await make_user(db, workspace=w.ws, role=role, login="boss.x")
    await db.commit()
    actor = actor_of(boss)
    await svc.set_role(db, actor, w.target.id, Role.BUSINESS_ADMIN)
    await svc.block_user(db, actor, env.sessions, w.target.id)
    await svc.unblock_user(db, actor, w.target.id)
    assert await member_role(db, w.target.id) == "business_admin"


# --- set_role: AC-26, AC-75, AC-121, FR-12, FR-66, FR-67 ---------------------------------


async def test_ac121_assign_role_is_second_event_with_role_details(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    w = await world(db)
    created = await svc.create_user(
        db, w.actor, env.hasher, login="ivan.petrov", one_time_password=SecretStr(ONE_TIME)
    )
    await svc.set_role(db, w.actor, created.id, Role.BUSINESS_ADMIN)
    rows = await events(db, w.ws.id)
    assert [r.action for r in rows] == ["user.created", "user.role_assigned"]
    ev = rows[1]
    assert ev.entity_type == "user"
    assert ev.entity_id == created.id
    assert ev.actor_id == w.admin.id
    assert ev.in_audit is True
    assert ev.details.get("role_from") is None
    assert ev.details["role_to"] == "business_admin"
    assert await member_role(db, created.id) == "business_admin"


async def test_ac75_change_and_remove_role_events_and_single_role(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    w = await world(db)  # target: user
    await svc.set_role(db, w.actor, w.target.id, Role.BUSINESS_ADMIN)
    assert await member_role(db, w.target.id) == "business_admin"
    await svc.set_role(db, w.actor, w.target.id, None)
    assert await member_role(db, w.target.id) is None
    rows = await events(db, w.ws.id)
    assert [r.action for r in rows] == ["user.role_changed", "user.role_removed"]
    assert rows[0].details["role_from"] == "user"
    assert rows[0].details["role_to"] == "business_admin"
    assert rows[1].details["role_from"] == "business_admin"
    assert rows[1].details.get("role_to") is None
    res = await db.execute(
        text("SELECT count(*) FROM workspace_member WHERE user_id = :u"), {"u": w.target.id}
    )
    assert res.scalar_one() == 1


async def test_fr12_same_role_is_noop_without_event(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    w = await world(db)
    await svc.set_role(db, w.actor, w.target.id, Role.USER)
    nobody = await make_user(db, workspace=w.ws, role=None, login="norole.x")
    await db.commit()
    await svc.set_role(db, w.actor, nobody.id, None)
    assert await events(db, w.ws.id) == []
    assert await member_role(db, w.target.id) == "user"


@pytest.mark.parametrize("bad", ["superuser", "TECH_ADMIN", "", "admin"])
async def test_fr66_unknown_role_value_is_422(
    db: AsyncSession, env: SimpleNamespace, svc: Any, bad: str
) -> None:
    from app.core.errors import AppError

    w = await world(db)
    with pytest.raises(AppError) as info:
        await svc.set_role(db, w.actor, w.target.id, bad)
    assert info.value.status_code == 422
    await db.rollback()
    assert await member_role(db, w.target.id) == "user"
    assert await events(db, w.ws.id) == []


async def test_ac26_self_assignment_is_allowed_and_audited(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    w = await world(db)
    await svc.set_role(db, w.actor, w.admin.id, Role.MIXED)  # ТА -> СМ себе
    assert await member_role(db, w.admin.id) == "mixed"
    ev = (await events(db, w.ws.id))[0]
    assert ev.action == "user.role_changed"
    assert ev.entity_id == w.admin.id
    assert ev.actor_id == w.admin.id
    assert ev.details["role_from"] == "tech_admin"
    assert ev.details["role_to"] == "mixed"


async def test_fr67_set_role_does_not_touch_sessions_or_other_users(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    w = await world(db)
    tokens = await open_sessions(db, env, w.target, 2)
    other = await make_user(db, workspace=w.ws, role="user", login="other.user")
    await db.commit()
    await svc.set_role(db, w.actor, w.target.id, Role.MIXED)
    for token in tokens:  # действует со следующего запроса без повторного входа
        assert await env.sessions.resolve(db, token, now=NOW, background=True) is not None
    assert await member_role(db, other.id) == "user"


# --- FR-69 / AC-78: последний администратор ----------------------------------------------


async def lone_admin_world(db: AsyncSession) -> SimpleNamespace:
    """Единственный активный ТА; второй ТА и СМ заблокированы; есть БА и «Пользователь»."""
    ws = await make_workspace(db)
    last = await make_user(db, workspace=ws, role="tech_admin", login="last.admin")
    await make_user(db, workspace=ws, role="tech_admin", login="blocked.ta", blocked=True)
    await make_user(db, workspace=ws, role="mixed", login="blocked.sm", blocked=True)
    await make_user(db, workspace=ws, role="business_admin", login="plain.ba")
    await make_user(db, workspace=ws, role="user", login="plain.user")
    await db.commit()
    return SimpleNamespace(ws=ws, last=last, actor=actor_of(last))


@pytest.mark.parametrize("new_role", [None, Role.BUSINESS_ADMIN, Role.USER])
async def test_ac78_last_admin_cannot_remove_or_downgrade_own_role(
    db: AsyncSession, env: SimpleNamespace, svc: Any, new_role: Role | None
) -> None:
    w = await lone_admin_world(db)
    await fails(db, svc.set_role(db, w.actor, w.last.id, new_role), "last_account_admin")
    assert await member_role(db, w.last.id) == "tech_admin"
    assert await events(db, w.ws.id) == []


async def test_ac78_last_admin_cannot_block_self(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    w = await lone_admin_world(db)
    token = (await open_sessions(db, env, w.last, 1))[0]
    await db.commit()
    await fails(db, svc.block_user(db, w.actor, env.sessions, w.last.id), "last_account_admin")
    assert (await state(db, w.last.id)).is_blocked is False
    assert await env.sessions.resolve(db, token, now=NOW, background=True) is not None
    assert await events(db, w.ws.id) == []


async def test_ac78_last_admin_may_become_mixed(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    w = await lone_admin_world(db)
    await svc.set_role(db, w.actor, w.last.id, Role.MIXED)
    assert await member_role(db, w.last.id) == "mixed"


async def test_ac78_with_second_active_admin_first_may_remove_own_role(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    w = await lone_admin_world(db)
    await make_user(db, workspace=w.ws, role="mixed", login="second.sm")
    await db.commit()
    await svc.set_role(db, w.actor, w.last.id, None)
    assert await member_role(db, w.last.id) is None
    assert [r.action for r in await events(db, w.ws.id)] == ["user.role_removed"]


async def test_fr69_ensure_account_admin_remains_counts_only_active_holders(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    w = await lone_admin_world(db)
    await svc.ensure_account_admin_remains(db, w.ws.id)  # один активный — достаточно
    await db.execute(
        text("UPDATE workspace_member SET role = 'user' WHERE user_id = :u"), {"u": w.last.id}
    )
    await fails(db, svc.ensure_account_admin_remains(db, w.ws.id), "last_account_admin")


async def test_fr69_blocked_admin_does_not_count(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    ws = await make_workspace(db)
    a = await make_user(db, workspace=ws, role="tech_admin", login="admin.a")
    await make_user(db, workspace=ws, role="tech_admin", login="admin.b", blocked=True)
    await db.commit()
    await fails(db, svc.set_role(db, actor_of(a), a.id, Role.BUSINESS_ADMIN), "last_account_admin")


@pytest.mark.committed
@pytest.mark.parametrize("mode", ["role", "block"])
async def test_ac78_concurrent_mutual_demotion_leaves_one_admin(
    committed: async_sessionmaker[AsyncSession],
    env: SimpleNamespace,
    svc: Any,
    mode: str,
) -> None:
    """Два админа одновременно лишают друг друга права: ровно один успех, админ остаётся.

    Заодно требует отсутствия взаимной блокировки (DBAPIError/deadlock): гонка обязана
    завершаться отказом приложения, а не необработанным исключением БД.

    Проигравший получает ``forbidden`` (403) ИЛИ ``last_account_admin`` (422). После T16a
    протокол блокировок проверяет, что актор остался среди активных администраторов: если
    победитель уже зафиксировал лишение роли/блокировку проигравшего, тот отклоняется как
    актор без права (403); если проигравший успел пройти эту проверку, его действие упирается в
    инвариант FR-69 (422). Какой путь — зависит от порядка захвата advisory-блокировки.
    """
    from app.core.errors import AppError

    async with committed() as s:
        ws = await make_workspace(s)
        a = await make_user(s, workspace=ws, role="tech_admin", login="admin.a")
        b = await make_user(s, workspace=ws, role="tech_admin", login="admin.b")
        await s.commit()

    async def attempt(actor_user: UserRow, victim: UserRow) -> str:
        async with committed() as s:
            try:
                if mode == "role":
                    await svc.set_role(s, actor_of(actor_user), victim.id, Role.USER)
                else:
                    await svc.block_user(s, actor_of(actor_user), env.sessions, victim.id)
                await s.commit()
            except AppError as exc:
                await s.rollback()
                assert exc.status_code in (403, 422)
                return str(exc.code)
            return "ok"

    for _ in range(6):
        outcomes = await asyncio.gather(attempt(a, b), attempt(b, a))
        assert outcomes.count("ok") == 1, outcomes
        assert [o for o in outcomes if o != "ok"][0] in ("forbidden", "last_account_admin"), (
            outcomes
        )
        async with committed() as s:
            res = await s.execute(
                text(
                    "SELECT count(*) FROM workspace_member m JOIN app_user u ON u.id = m.user_id "
                    "WHERE m.workspace_id = :w AND m.role IN ('tech_admin','mixed') "
                    "AND NOT u.is_blocked"
                ),
                {"w": ws.id},
            )
            assert res.scalar_one() == 1
            # события сходятся с результатами: одно успешное действие - одно событие
            action = "user.role_changed" if mode == "role" else "user.blocked"
            count = await s.execute(
                text("SELECT count(*) FROM domain_event WHERE workspace_id = :w AND action = :a"),
                {"w": ws.id, "a": action},
            )
            assert count.scalar_one() == _ + 1
            await s.execute(
                text("UPDATE workspace_member SET role = 'tech_admin' WHERE workspace_id = :w"),
                {"w": ws.id},
            )
            await s.execute(text("UPDATE app_user SET is_blocked = false, blocked_at = NULL"))
            await s.commit()


# --- block / unblock: FR-5, FR-5a, FR-62, AC-44 -----------------------------------------


async def test_fr5_block_ends_all_sessions_and_prevents_login(
    db: AsyncSession, env: SimpleNamespace, svc: Any, mods: SimpleNamespace
) -> None:
    w = await world(db)
    victim_tokens = await open_sessions(db, env, w.target, 3)
    bystander = await make_user(db, workspace=w.ws, role="user", login="bystander.x")
    keep = (await open_sessions(db, env, bystander, 1))[0]
    await db.commit()

    await svc.block_user(db, w.actor, env.sessions, w.target.id)

    assert (await state(db, w.target.id)).is_blocked is True
    assert await count_sessions(db, w.target.id) == 0
    for token in victim_tokens:
        assert await env.sessions.resolve(db, token, now=NOW, background=True) is None
    assert await env.sessions.resolve(db, keep, now=NOW, background=True) is not None
    with pytest.raises(mods.errors.InvalidCredentials):
        await login_as(db, env, mods, w.target.login, "correct-horse-battery-staple")


async def test_fr5_block_writes_one_user_blocked_event(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    w = await world(db)
    await svc.block_user(db, w.actor, env.sessions, w.target.id)
    rows = await events(db, w.ws.id)
    assert len(rows) == 1
    ev = rows[0]
    assert (ev.action, ev.entity_type, ev.entity_id) == ("user.blocked", "user", w.target.id)
    assert ev.actor_id == w.admin.id
    assert ev.in_audit is True


async def test_fr5_block_already_blocked_is_idempotent_without_new_event(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    w = await world(db)
    await svc.block_user(db, w.actor, env.sessions, w.target.id)
    await svc.block_user(db, w.actor, env.sessions, w.target.id)
    assert (await state(db, w.target.id)).is_blocked is True
    assert [r.action for r in await events(db, w.ws.id)] == ["user.blocked"]


async def test_ac44_unblock_allows_login_but_does_not_restore_sessions(
    db: AsyncSession, env: SimpleNamespace, svc: Any, mods: SimpleNamespace
) -> None:
    w = await world(db)
    tokens = await open_sessions(db, env, w.target, 2)
    await db.commit()
    await svc.block_user(db, w.actor, env.sessions, w.target.id)
    await svc.unblock_user(db, w.actor, w.target.id)

    assert (await state(db, w.target.id)).is_blocked is False
    for token in tokens:
        assert await env.sessions.resolve(db, token, now=NOW, background=True) is None
    result = await login_as(db, env, mods, w.target.login, "correct-horse-battery-staple")
    assert result.user_id == w.target.id
    assert [r.action for r in await events(db, w.ws.id)] == ["user.blocked", "user.unblocked"]


async def test_fr5a_unblock_of_active_user_is_noop_without_event(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    w = await world(db)
    await svc.unblock_user(db, w.actor, w.target.id)
    assert (await state(db, w.target.id)).is_blocked is False
    assert await events(db, w.ws.id) == []


# --- reset_password: FR-65, AC-45, AC-113 -----------------------------------------------


async def test_ac45_reset_password_sets_new_hash_flag_and_ends_sessions(
    db: AsyncSession, env: SimpleNamespace, svc: Any, mods: SimpleNamespace
) -> None:
    w = await world(db)
    tokens = await open_sessions(db, env, w.target, 2)
    await db.commit()

    await svc.reset_password(
        db, w.actor, env.hasher, env.sessions, w.target.id, one_time_password=SecretStr(ONE_TIME)
    )

    st = await state(db, w.target.id)
    assert st.must_change_password is True
    assert st.password_hash.startswith("$argon2id$")
    assert ONE_TIME not in st.password_hash
    assert env.hasher.verify(st.password_hash, ONE_TIME)
    assert not env.hasher.verify(st.password_hash, "correct-horse-battery-staple")
    assert await count_sessions(db, w.target.id) == 0
    for token in tokens:
        assert await env.sessions.resolve(db, token, now=NOW, background=True) is None
    with pytest.raises(mods.errors.InvalidCredentials):
        await login_as(db, env, mods, w.target.login, "correct-horse-battery-staple")
    result = await login_as(db, env, mods, w.target.login, ONE_TIME)
    assert result.must_change_password is True


async def test_fr65_reset_clears_failed_counter_and_login_lock(
    db: AsyncSession, env: SimpleNamespace, svc: Any, mods: SimpleNamespace
) -> None:
    w = await world(db)
    await db.execute(
        text("UPDATE app_user SET failed_login_count = 3, login_locked_until = :t WHERE id = :u"),
        {"t": NOW + LOCK, "u": w.target.id},
    )
    await db.commit()
    await svc.reset_password(
        db, w.actor, env.hasher, env.sessions, w.target.id, one_time_password=SecretStr(ONE_TIME)
    )
    st = await state(db, w.target.id)
    assert st.failed_login_count == 0
    assert st.login_locked_until is None
    assert (await login_as(db, env, mods, w.target.login, ONE_TIME)).user_id == w.target.id


async def test_fr65_reset_writes_one_event_without_password(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    w = await world(db)
    await svc.reset_password(
        db, w.actor, env.hasher, env.sessions, w.target.id, one_time_password=SecretStr(ONE_TIME)
    )
    rows = await events(db, w.ws.id)
    assert len(rows) == 1
    ev = rows[0]
    assert (ev.action, ev.entity_type, ev.entity_id) == (
        "user.password_reset",
        "user",
        w.target.id,
    )
    assert ev.actor_id == w.admin.id
    assert ev.in_audit is True
    await spy_hash_not_in(db, ONE_TIME, "$argon2")


@pytest.mark.parametrize(("password", "code"), [(SHORT_11, "password_too_short")])
async def test_ac113_reset_enforces_password_policy_without_changes(
    db: AsyncSession, env: SimpleNamespace, svc: Any, password: str, code: str
) -> None:
    w = await world(db)
    token = (await open_sessions(db, env, w.target, 1))[0]
    await db.commit()
    before = await state(db, w.target.id)
    await fails(
        db,
        svc.reset_password(
            db,
            w.actor,
            env.hasher,
            env.sessions,
            w.target.id,
            one_time_password=SecretStr(password),
        ),
        code,
    )
    assert (await state(db, w.target.id)).password_hash == before.password_hash
    assert await env.sessions.resolve(db, token, now=NOW, background=True) is not None
    assert await events(db, w.ws.id) == []


async def test_ac113_reset_rejects_common_password(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    path = BACKEND_DIR / "app" / "core" / "security" / "data" / "common-passwords-10k.txt"
    common = next(e for e in path.read_text(encoding="utf-8").split("\n") if len(e) >= 12)
    w = await world(db)
    await fails(
        db,
        svc.reset_password(
            db, w.actor, env.hasher, env.sessions, w.target.id, one_time_password=SecretStr(common)
        ),
        "password_too_common",
    )


# --- revoke_sessions: FR-62, AC-39 -------------------------------------------------------


async def test_ac39_revoke_sessions_removes_all_and_login_still_possible(
    db: AsyncSession, env: SimpleNamespace, svc: Any, mods: SimpleNamespace
) -> None:
    w = await world(db)
    tokens = await open_sessions(db, env, w.target, 3)
    bystander = await make_user(db, workspace=w.ws, role="user", login="bystander.x")
    keep = (await open_sessions(db, env, bystander, 1))[0]
    await db.commit()

    removed = await svc.revoke_sessions(db, w.actor, env.sessions, w.target.id)

    assert removed == 3
    for token in tokens:
        assert await env.sessions.resolve(db, token, now=NOW, background=True) is None
    assert await env.sessions.resolve(db, keep, now=NOW, background=True) is not None
    st = await state(db, w.target.id)
    assert st.is_blocked is False
    assert st.password_hash == w.target.password_hash
    assert (await login_as(db, env, mods, w.target.login, "correct-horse-battery-staple")).user_id


async def test_fr62_revoke_with_zero_sessions_still_writes_event(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    w = await world(db)
    assert await svc.revoke_sessions(db, w.actor, env.sessions, w.target.id) == 0
    rows = await events(db, w.ws.id)
    assert [r.action for r in rows] == ["user.sessions_revoked"]
    assert rows[0].entity_id == w.target.id
    assert rows[0].actor_id == w.admin.id
    assert rows[0].in_audit is True


# --- изоляция пространства: FR-13, AC-21, BR-2 -------------------------------------------


async def test_ac21_foreign_workspace_user_is_404_for_every_action(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    w = await world(db)
    stranger = await make_user(db, role="user", login="stranger.x")  # другое пространство
    tokens = await open_sessions(db, env, stranger, 2)
    await db.commit()
    before = await events(db)
    before_state = await state(db, stranger.id)

    await not_found(db, svc.block_user(db, w.actor, env.sessions, stranger.id))
    await not_found(db, svc.unblock_user(db, w.actor, stranger.id))
    await not_found(
        db,
        svc.reset_password(
            db,
            w.actor,
            env.hasher,
            env.sessions,
            stranger.id,
            one_time_password=SecretStr(ONE_TIME),
        ),
    )
    await not_found(db, svc.revoke_sessions(db, w.actor, env.sessions, stranger.id))
    await not_found(db, svc.set_role(db, w.actor, stranger.id, Role.MIXED))
    await not_found(db, svc.set_role(db, w.actor, uuid.uuid4(), Role.MIXED))  # несуществующий

    assert await events(db) == before
    after_state = await state(db, stranger.id)
    assert after_state.password_hash == before_state.password_hash
    assert after_state.is_blocked is False
    assert await member_role(db, stranger.id) == "user"
    for token in tokens:
        assert await env.sessions.resolve(db, token, now=NOW, background=True) is not None


async def test_ac21_gate_comes_before_lookup_non_admin_gets_403_not_404(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    w = await world(db)
    stranger = await make_user(db, role="user", login="stranger.x")
    await db.commit()
    ba = actor_of(w.target, role="business_admin")
    await forbidden(db, svc.block_user(db, ba, env.sessions, stranger.id))


async def test_ac21_create_user_lands_in_actor_workspace(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    w = await world(db)
    other_ws = await make_workspace(db)
    await db.commit()
    await svc.create_user(
        db, w.actor, env.hasher, login="ivan.petrov", one_time_password=SecretStr(ONE_TIME)
    )
    row = await user_by_login(db, "ivan.petrov")
    assert row.workspace_id == w.ws.id
    res = await db.execute(
        text("SELECT count(*) FROM workspace_member WHERE workspace_id = :w"), {"w": other_ws.id}
    )
    assert res.scalar_one() == 0


async def test_br2_service_does_not_read_business_tables() -> None:
    """BR-2: сервис учётных записей не обращается к проектам и задачам (исходник)."""
    path = BACKEND_DIR / "app" / "domain" / "users" / "service.py"
    assert path.exists(), "нет backend/app/domain/users/service.py"
    source = path.read_text(encoding="utf-8")
    for forbidden_token in ("projects", "tasks", "app.domain.projects", "app.domain.tasks"):
        assert forbidden_token not in source


# --- события в одной транзакции: AC-67 ---------------------------------------------------


async def test_ac67_rollback_removes_event_and_change_together(
    db: AsyncSession, env: SimpleNamespace, svc: Any
) -> None:
    w = await world(db)
    token = (await open_sessions(db, env, w.target, 1))[0]
    await db.commit()

    await svc.create_user(
        db, w.actor, env.hasher, login="ivan.petrov", one_time_password=SecretStr(ONE_TIME)
    )
    await svc.set_role(db, w.actor, w.target.id, Role.MIXED)
    await svc.block_user(db, w.actor, env.sessions, w.target.id)
    await db.rollback()

    assert await user_by_login(db, "ivan.petrov") is None
    assert await member_role(db, w.target.id) == "user"
    assert (await state(db, w.target.id)).is_blocked is False
    assert await env.sessions.resolve(db, token, now=NOW, background=True) is not None
    assert await events(db, w.ws.id) == []


@pytest.mark.parametrize("action", ["create", "block", "unblock", "reset", "revoke", "role"])
async def test_ac67_event_write_failure_aborts_the_action(
    db: AsyncSession,
    env: SimpleNamespace,
    svc: Any,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    import app.domain.events.writer as writer

    w = await world(db)
    if action == "unblock":
        await svc.block_user(db, w.actor, env.sessions, w.target.id)
        await db.commit()
    token = (await open_sessions(db, env, w.target, 1))[0]
    await db.commit()
    before_events = await events(db)
    before_hash = (await state(db, w.target.id)).password_hash
    blocked_before = (await state(db, w.target.id)).is_blocked

    async def boom(*args: Any, **kwargs: Any) -> int:
        raise RuntimeError("event write failed")

    monkeypatch.setattr(writer, "record_event", boom)
    monkeypatch.setattr(svc, "record_event", boom, raising=False)

    calls = {
        "create": lambda: svc.create_user(
            db, w.actor, env.hasher, login="ivan.petrov", one_time_password=SecretStr(ONE_TIME)
        ),
        "block": lambda: svc.block_user(db, w.actor, env.sessions, w.target.id),
        "unblock": lambda: svc.unblock_user(db, w.actor, w.target.id),
        "reset": lambda: svc.reset_password(
            db,
            w.actor,
            env.hasher,
            env.sessions,
            w.target.id,
            one_time_password=SecretStr(ONE_TIME),
        ),
        "revoke": lambda: svc.revoke_sessions(db, w.actor, env.sessions, w.target.id),
        "role": lambda: svc.set_role(db, w.actor, w.target.id, Role.MIXED),
    }
    with pytest.raises(RuntimeError):
        await calls[action]()
    await db.rollback()

    assert await events(db) == before_events
    assert await user_by_login(db, "ivan.petrov") is None
    st = await state(db, w.target.id)
    assert st.password_hash == before_hash
    assert st.is_blocked == blocked_before
    assert await member_role(db, w.target.id) == "user"
    assert await env.sessions.resolve(db, token, now=NOW, background=True) is not None


# --- пароли не попадают в логи и ошибки: FR-57, AC-113 ----------------------------------


async def test_fr57_one_time_passwords_never_reach_logs_errors_or_events(
    db: AsyncSession,
    env: SimpleNamespace,
    svc: Any,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.core.errors import AppError
    from app.core.logging import configure_logging

    configure_logging("DEBUG")
    capsys.readouterr()
    caplog.set_level(logging.DEBUG)
    w = await world(db)
    errors: list[BaseException] = []

    created = await svc.create_user(
        db, w.actor, env.hasher, login="ivan.petrov", one_time_password=SecretStr(ONE_TIME)
    )
    await svc.reset_password(
        db, w.actor, env.hasher, env.sessions, created.id, one_time_password=SecretStr(ONE_TIME_2)
    )
    for secret_try in (SHORT_11, SURROGATE):
        try:
            await svc.reset_password(
                db,
                w.actor,
                env.hasher,
                env.sessions,
                created.id,
                one_time_password=SecretStr(secret_try),
            )
        except AppError as exc:
            errors.append(exc)
            await db.rollback()
    try:
        await svc.create_user(
            db, w.actor, env.hasher, login="ivan.petrov", one_time_password=SecretStr(ONE_TIME)
        )
    except AppError as exc:
        errors.append(exc)
        await db.rollback()
    assert errors, "ожидались отказы по политике и занятому логину"

    out = capsys.readouterr().out
    for line in out.splitlines():
        if line.strip():
            json.loads(line)
    haystacks = [caplog.text, out, *(r.getMessage() for r in caplog.records)]
    for record in caplog.records:
        haystacks.append(repr(record.args))
        haystacks.append(str(record.exc_text))
    for secret in (ONE_TIME, ONE_TIME_2, SHORT_11, SURROGATE):
        for h in haystacks:
            assert secret not in h
        for exc in errors:
            assert secret not in f"{exc!s} {exc!r} {exc.args!r} {getattr(exc, 'detail', '')}"
    await spy_hash_not_in(db, ONE_TIME, ONE_TIME_2, "$argon2")


# --- заметка ревью T11: единый шаблон логина ---------------------------------------------


BOUNDARY_LOGINS: list[tuple[str, bool]] = [
    ("abc", True),
    ("ab", False),
    ("a" * 64, True),
    ("a" * 65, False),
    (".abc", False),
    ("-abc", False),
    ("_abc", False),
    ("a.-_b", True),
    ("IVAN.Petrov", True),
    ("ivan petrov", False),
    ("иван", False),
    ("Kevin", False),
    ("kevinK", False),
    ("ivan\x00", False),
    ("ivan\n", False),
    ("0lead", True),
]


def test_t11_note_login_pattern_is_defined_in_one_place() -> None:
    """Шаблон FR-73 в коде приложения — один (provider.LOGIN_RE); CHECK модели — SQL."""
    needle = "[a-z0-9][a-z0-9._-]{2,63}"
    app_dir = BACKEND_DIR / "app"
    holders = sorted(
        str(p.relative_to(app_dir))
        for p in app_dir.rglob("*.py")
        if needle in p.read_text(encoding="utf-8")
        and p.relative_to(app_dir) != Path("domain/users/models.py")
    )
    assert len(holders) == 1, f"шаблон логина продублирован: {holders}"


def test_t11_note_bootstrap_and_provider_agree_on_boundary_logins(
    settings: Settings, mods: SimpleNamespace
) -> None:
    import app.domain.system.bootstrap as bootstrap

    for raw, valid in BOUNDARY_LOGINS:
        expected = mods.provider.normalize_login(raw)
        assert (expected is not None) is valid, repr(raw)
        cfg = settings.model_copy(update={"initial_admin_login": raw})
        if valid:
            assert bootstrap._initial_login(cfg) == expected
        else:
            with pytest.raises(ValueError):
                bootstrap._initial_login(cfg)


async def test_t11_note_create_user_and_login_normalize_identically(
    db: AsyncSession, env: SimpleNamespace, svc: Any, mods: SimpleNamespace
) -> None:
    from app.core.errors import AppError

    w = await world(db)
    for raw, valid in BOUNDARY_LOGINS:
        expected = mods.provider.normalize_login(raw)
        if not valid:
            assert expected is None
            with pytest.raises(AppError) as info:
                await svc.create_user(
                    db, w.actor, env.hasher, login=raw, one_time_password=SecretStr(ONE_TIME)
                )
            assert info.value.status_code == 422
            assert str(info.value.code) == "login_invalid", repr(raw)
            await db.rollback()
            with pytest.raises(mods.errors.InvalidCredentials):
                await login_as(db, env, mods, raw, ONE_TIME)
            continue
        created = await svc.create_user(
            db, w.actor, env.hasher, login=raw, one_time_password=SecretStr(ONE_TIME)
        )
        assert created.login == expected
        await db.commit()
        result = await login_as(db, env, mods, raw, ONE_TIME)
        assert result.user_id == created.id
        assert result.login == expected


# --- заметка ревью T14: две ветки change_own_password ------------------------------------


async def _change_ctx(
    committed: async_sessionmaker[AsyncSession],
    env: SimpleNamespace,
    *,
    failed: int,
    locked_until: datetime | None,
) -> SimpleNamespace:
    async with committed() as s:
        user = await make_user(
            s, password=OLD_PASSWORD, role="tech_admin", must_change_password=True
        )
        other = await env.sessions.create(
            s, user_id=user.id, workspace_id=user.workspace_id, now=NOW
        )
        current = await env.sessions.create(
            s, user_id=user.id, workspace_id=user.workspace_id, now=NOW
        )
        await s.execute(
            text(
                "UPDATE app_user SET failed_login_count = :c, login_locked_until = :t WHERE id = :u"
            ),
            {"c": failed, "t": locked_until, "u": user.id},
        )
        await s.commit()
    actor = Actor(
        user_id=user.id,
        workspace_id=user.workspace_id,
        login=user.login,
        role=Role.TECH_ADMIN,
        must_change_password=True,
        session_id=env.sessions.token_id(current),
    )
    return SimpleNamespace(user=user, actor=actor, tokens=[other, current])


async def _call_change(
    committed: async_sessionmaker[AsyncSession],
    mods: SimpleNamespace,
    env: SimpleNamespace,
    ctx: SimpleNamespace,
    *,
    current: str,
    new: str,
) -> str:
    """Один «запрос»: исключение -> ROLLBACK. Возвращает код ошибки или ``ok``."""
    from app.core.errors import AppError

    async with committed() as s:
        try:
            await mods.auth_service.change_own_password(
                s,
                ctx.actor,
                env.hasher,
                env.sessions,
                env.settings,
                current=SecretStr(current),
                new=SecretStr(new),
                now=NOW,
            )
            await s.commit()
        except AppError as exc:
            await s.rollback()
            return str(exc.code)
        return "ok"


@pytest.mark.committed
@pytest.mark.parametrize("current", [WRONG, OLD_PASSWORD])
async def test_t14_note_active_login_lock_rejects_without_counting_or_verifying(
    committed: async_sessionmaker[AsyncSession],
    env: SimpleNamespace,
    mods: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    current: str,
) -> None:
    lock = NOW + timedelta(minutes=10)
    ctx = await _change_ctx(committed, env, failed=2, locked_until=lock)
    verify_calls: list[str] = []
    real_verify = env.hasher.verify

    def spy(stored: str, password: str) -> bool:
        verify_calls.append("verify")
        return bool(real_verify(stored, password))

    monkeypatch.setattr(env.hasher, "verify", spy)

    for _ in range(3):  # повторные попытки не двигают ни счётчик, ни срок
        code = await _call_change(
            committed, mods, env, ctx, current=current, new="brand-new-password-9157"
        )
        assert code == "invalid_current_password"

    assert verify_calls == []
    async with committed() as s:
        st = await state(s, ctx.user.id)
        assert st.failed_login_count == 2
        assert st.login_locked_until == lock
        assert st.password_hash == ctx.user.password_hash
        assert st.must_change_password is True
        assert await count_sessions(s, ctx.user.id) == 2


@pytest.mark.committed
@pytest.mark.parametrize(
    ("new", "code"),
    [
        (OLD_PASSWORD, "password_reused"),
        (SHORT_11, "password_too_short"),
        ("__common__", "password_too_common"),
    ],
)
async def test_t14_note_correct_current_with_policy_refusal_resets_series_durably(
    committed: async_sessionmaker[AsyncSession],
    env: SimpleNamespace,
    mods: SimpleNamespace,
    new: str,
    code: str,
) -> None:
    if new == "__common__":
        path = BACKEND_DIR / "app" / "core" / "security" / "data" / "common-passwords-10k.txt"
        new = next(
            e
            for e in path.read_text(encoding="utf-8").split("\n")
            if len(e) >= 12 and e != OLD_PASSWORD
        )
    ctx = await _change_ctx(committed, env, failed=3, locked_until=None)

    result = await _call_change(committed, mods, env, ctx, current=OLD_PASSWORD, new=new)

    assert result == code
    async with committed() as s:  # новая сессия: сброс пережил ROLLBACK запроса
        st = await state(s, ctx.user.id)
        assert st.failed_login_count == 0
        assert st.login_locked_until is None
        assert st.password_hash == ctx.user.password_hash  # пароль не сменён
        assert st.must_change_password is True
        assert await count_sessions(s, ctx.user.id) == 2


# --- заметка ревью T15: paginate без ORDER BY --------------------------------------------


async def test_t15_note_paginate_without_order_by_raises_value_error(db: AsyncSession) -> None:
    from app.core.pagination import PageParams, paginate
    from app.domain.users.models import AppUser

    with pytest.raises(ValueError):
        await paginate(db, select(AppUser), PageParams())


# --- ревью T16: параллельные пары над ОДНОЙ целью (deadlock FOR UPDATE vs FOR KEY SHARE) ---

PAIR_ITERATIONS = 40


async def _pair_setup(
    committed: async_sessionmaker[AsyncSession],
    env: SimpleNamespace,
    *,
    blocked: bool,
) -> SimpleNamespace:
    async with committed() as s:
        ws = await make_workspace(s)
        a = await make_user(s, workspace=ws, role="tech_admin")
        c = await make_user(s, workspace=ws, role="mixed")
        x = await make_user(s, workspace=ws, role="user", blocked=blocked)
        for _ in range(2):
            await env.sessions.create(s, user_id=x.id, workspace_id=ws.id, now=NOW)
        await s.commit()
    return SimpleNamespace(ws=ws, a=a, c=c, x=x)


async def _run_pairs(
    committed: async_sessionmaker[AsyncSession],
    env: SimpleNamespace,
    svc: Any,
    *,
    first: str,
    second: str,
    blocked: bool,
    expected_actions: list[str],
    check: Any,
) -> None:
    from app.core.errors import AppError

    def make_call(kind: str, s: AsyncSession, actor: Actor, uid: uuid.UUID) -> Awaitable[Any]:
        if kind == "block":
            return svc.block_user(s, actor, env.sessions, uid)
        if kind == "unblock":
            return svc.unblock_user(s, actor, uid)
        if kind == "revoke":
            return svc.revoke_sessions(s, actor, env.sessions, uid)
        if kind == "reset":
            return svc.reset_password(
                s, actor, env.hasher, env.sessions, uid, one_time_password=SecretStr(ONE_TIME)
            )
        assert kind == "role"
        return svc.set_role(s, actor, uid, Role.BUSINESS_ADMIN)

    async def run(kind: str, actor_user: UserRow, uid: uuid.UUID, go: asyncio.Event) -> str:
        async with committed() as s:
            await go.wait()
            try:
                await make_call(kind, s, actor_of(actor_user), uid)
                await s.commit()
            except AppError as exc:
                await s.rollback()
                assert exc.status_code == 422, exc
                return str(exc.code)
            return "ok"

    for i in range(PAIR_ITERATIONS):
        w = await _pair_setup(committed, env, blocked=blocked)
        go = asyncio.Event()
        jobs = [(first, w.a), (second, w.c)]
        if i % 2:
            jobs.reverse()  # чередуем порядок запуска
        tasks = [asyncio.ensure_future(run(k, u, w.x.id, go)) for k, u in jobs]
        await asyncio.sleep(0)
        go.set()
        outcomes = await asyncio.gather(*tasks)  # DBAPIError/deadlock проваливает тест
        assert all(o in ("ok", "last_account_admin") for o in outcomes), outcomes
        async with committed() as s:
            acts = [
                r.action
                for r in await events(s, w.ws.id)
                if r.entity_id == w.x.id and r.action in ALL_USER_ACTIONS
            ]
            assert sorted(acts) == sorted(expected_actions), (acts, outcomes)
            await check(s, w)
            res = await s.execute(
                text(
                    "SELECT count(*) FROM workspace_member m JOIN app_user u ON u.id = m.user_id "
                    "WHERE m.workspace_id = :w AND m.role IN ('tech_admin','mixed') "
                    "AND NOT u.is_blocked"
                ),
                {"w": w.ws.id},
            )
            assert res.scalar_one() >= 1


async def _check_blocked_no_sessions(s: AsyncSession, w: SimpleNamespace) -> None:
    assert (await state(s, w.x.id)).is_blocked is True
    assert await count_sessions(s, w.x.id) == 0


@pytest.mark.committed
async def test_t16_review_concurrent_block_vs_revoke_same_target(
    committed: async_sessionmaker[AsyncSession], env: SimpleNamespace, svc: Any
) -> None:
    await _run_pairs(
        committed,
        env,
        svc,
        first="block",
        second="revoke",
        blocked=False,
        expected_actions=["user.blocked", "user.sessions_revoked"],
        check=_check_blocked_no_sessions,
    )


@pytest.mark.committed
async def test_t16_review_concurrent_block_vs_reset_password_same_target(
    committed: async_sessionmaker[AsyncSession], env: SimpleNamespace, svc: Any
) -> None:
    async def check(s: AsyncSession, w: SimpleNamespace) -> None:
        await _check_blocked_no_sessions(s, w)
        st = await state(s, w.x.id)
        assert st.must_change_password is True
        assert env.hasher.verify(st.password_hash, ONE_TIME)

    await _run_pairs(
        committed,
        env,
        svc,
        first="block",
        second="reset",
        blocked=False,
        expected_actions=["user.blocked", "user.password_reset"],
        check=check,
    )


@pytest.mark.committed
async def test_t16_review_concurrent_unblock_vs_set_role_same_target(
    committed: async_sessionmaker[AsyncSession], env: SimpleNamespace, svc: Any
) -> None:
    async def check(s: AsyncSession, w: SimpleNamespace) -> None:
        assert (await state(s, w.x.id)).is_blocked is False
        assert await member_role(s, w.x.id) == "business_admin"

    await _run_pairs(
        committed,
        env,
        svc,
        first="unblock",
        second="role",
        blocked=True,
        expected_actions=["user.unblocked", "user.role_changed"],
        check=check,
    )


@pytest.mark.committed
async def test_t16_review_concurrent_reset_password_vs_set_role_same_target(
    committed: async_sessionmaker[AsyncSession], env: SimpleNamespace, svc: Any
) -> None:
    async def check(s: AsyncSession, w: SimpleNamespace) -> None:
        st = await state(s, w.x.id)
        assert st.must_change_password is True
        assert await count_sessions(s, w.x.id) == 0
        assert await member_role(s, w.x.id) == "business_admin"

    await _run_pairs(
        committed,
        env,
        svc,
        first="reset",
        second="role",
        blocked=False,
        expected_actions=["user.password_reset", "user.role_changed"],
        check=check,
    )


@pytest.mark.committed
async def test_t16_review_two_concurrent_blocks_of_same_target(
    committed: async_sessionmaker[AsyncSession], env: SimpleNamespace, svc: Any
) -> None:
    await _run_pairs(
        committed,
        env,
        svc,
        first="block",
        second="block",
        blocked=False,
        expected_actions=["user.blocked"],
        check=_check_blocked_no_sessions,
    )


# --- ревью T16 (попытка 2): шесть одновременных действий трёх админов ----------------------

TRIO_ITERATIONS = 150


@pytest.mark.committed
@pytest.mark.parametrize("variant", ["roles", "mixed"])
async def test_t16_review_three_admins_six_concurrent_actions_no_deadlock(
    committed: async_sessionmaker[AsyncSession],
    env: SimpleNamespace,
    svc: Any,
    variant: str,
) -> None:
    from sqlalchemy.exc import DBAPIError

    from app.core.errors import AppError

    db_errors: list[str] = []

    async def run(
        kind: str,
        who: UserRow,
        target: UserRow,
        go: asyncio.Event,
    ) -> str:
        async with committed() as s:
            await go.wait()
            actor = actor_of(who)
            try:
                if kind == "block":
                    await svc.block_user(s, actor, env.sessions, target.id)
                elif kind == "unblock":
                    await svc.unblock_user(s, actor, target.id)
                elif kind == "revoke":
                    await svc.revoke_sessions(s, actor, env.sessions, target.id)
                elif kind == "reset":
                    await svc.reset_password(
                        s,
                        actor,
                        env.hasher,
                        env.sessions,
                        target.id,
                        one_time_password=SecretStr(ONE_TIME),
                    )
                elif kind == "to_ba":
                    await svc.set_role(s, actor, target.id, Role.BUSINESS_ADMIN)
                else:
                    assert kind == "to_user"
                    await svc.set_role(s, actor, target.id, Role.USER)
                await s.commit()
            except AppError as exc:
                await s.rollback()
                assert exc.status_code in (403, 404, 422), exc
                return str(exc.code)
            except DBAPIError as exc:
                await s.rollback()
                db_errors.append(str(exc.orig)[:80])
                return "db_error"
            return "ok"

    for i in range(TRIO_ITERATIONS):
        async with committed() as s:
            ws = await make_workspace(s)
            a = await make_user(s, workspace=ws, role="tech_admin")
            b = await make_user(s, workspace=ws, role="mixed")
            c = await make_user(s, workspace=ws, role="tech_admin")
            for u in (a, b, c):
                for _ in range(2):
                    await env.sessions.create(s, user_id=u.id, workspace_id=ws.id, now=NOW)
            await s.commit()
        if variant == "roles":
            plan = [
                ("block", a, b),
                ("to_ba", b, c),
                ("block", c, a),
                ("to_user", a, b),
                ("block", b, c),
                ("to_ba", c, a),
            ]
        else:
            plan = [
                ("block", a, b),
                ("reset", b, c),
                ("block", c, a),
                ("revoke", a, b),
                ("block", b, c),
                ("unblock", c, a),
            ]
        if i % 2:
            plan.reverse()
        if i % 3 == 0:
            plan = plan[2:] + plan[:2]
        go = asyncio.Event()
        tasks = [asyncio.ensure_future(run(k, w, t, go)) for k, w, t in plan]
        await asyncio.sleep(0)
        go.set()
        outcomes = await asyncio.gather(*tasks)

        async with committed() as s:
            ok = outcomes.count("ok")
            rows = [r for r in await events(s, ws.id) if r.action in ALL_USER_ACTIONS]
            if "db_error" not in outcomes:
                assert len(rows) <= ok, (outcomes, [r.action for r in rows])
            active = (
                await s.execute(
                    text(
                        "SELECT count(*) FROM workspace_member m JOIN app_user u "
                        "ON u.id = m.user_id WHERE m.workspace_id = :w "
                        "AND m.role IN ('tech_admin','mixed') AND NOT u.is_blocked"
                    ),
                    {"w": ws.id},
                )
            ).scalar_one()
            assert active >= 1, outcomes
            for u in (a, b, c):
                st = await state(s, u.id)
                if st.is_blocked:
                    assert await count_sessions(s, u.id) == 0, outcomes
                blocked_events = [
                    r for r in rows if r.entity_id == u.id and r.action == "user.blocked"
                ]
                if variant == "roles":
                    assert st.is_blocked == bool(blocked_events), outcomes
                role_events = [
                    r for r in rows if r.entity_id == u.id and r.action == "user.role_changed"
                ]
                if variant == "roles" and role_events and "db_error" not in outcomes:
                    assert await member_role(s, u.id) == role_events[-1].details["role_to"]

    assert db_errors == [], f"{len(db_errors)} ошибок БД из {TRIO_ITERATIONS}: {db_errors[:2]}"
