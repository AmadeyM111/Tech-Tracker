"""T11: домен аутентификации — провайдер, защита от перебора, сессии (plan §4.6, D-10, D-13).

AC-20 (вход заблокированного), AC-29, AC-30, AC-31, AC-32, AC-33, AC-34, AC-37, AC-79,
AC-113 (вход с одноразовым паролем), AC-115, AC-116 (вход без учёта регистра);
FR-1, FR-3, FR-5, FR-55, FR-56, FR-57, FR-58, FR-59, FR-60, FR-61, FR-62, FR-65 (уровень
сессий), FR-66, FR-73; заметки ревью T06 (миграция 0003) и T08 (суррогаты).

Модули ``app.domain.auth.provider|sessions|service`` импортируются внутри фикстуры ``mods``:
пока их нет, каждый тест падает отдельно с ImportError.

Время — только явный ``now`` (FixedClock также установлен фикстурой ``fixed_clock``).
Argon2 — дешёвые параметры. БД — фикстуры ``db`` (откат) и ``committed`` (реальные фиксации).

Допущения, не закреплённые в plan §4.6 дословно (см. отчёт):
- ``Actor`` (plan §4.5, T12) ещё не существует: тесты передают структурный двойник с теми же
  полями (user_id, workspace_id, login, role, must_change_password, session_id);
- вход, выход и смена своего пароля НЕ пишут событий (FR-41: «Вход … не аудируются»,
  в каталоге plan §4.4 нет соответствующих действий).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.db_support import BACKEND_DIR, run_alembic
from tests.factories import UserRow, get_table, make_user

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.core.clock import FixedClock
    from app.core.config import Settings

NOW = datetime(2026, 10, 13, 9, 0, 0, tzinfo=UTC)
SECRET_KEY = b"unit-test-secret-key-0123456789ab"
CHEAP: dict[str, int] = {"time_cost": 1, "memory_cost_kib": 1024, "parallelism": 1}
PASSWORD = "correct-horse-battery-staple"
WRONG = "definitely-wrong-password"
NEW_PASSWORD = "brand-new-password-9157"
SURROGATE = "abc\ud800" * 5
IDLE = timedelta(hours=8)
ABSOLUTE = timedelta(days=7)
LOCK = timedelta(minutes=15)
CHECK_VIOLATION = "23514"
INITIAL_FILE = "initial-admin-password.txt"
MIGRATION_0003_GLOB = "0003_*.py"


# --- вспомогательное ---------------------------------------------------------------------


@dataclass(frozen=True)
class FakeActor:
    """Структурный двойник Actor (plan §4.5): T12 ещё не реализована."""

    user_id: uuid.UUID
    workspace_id: uuid.UUID
    login: str
    role: str | None
    must_change_password: bool
    session_id: bytes

    def can(self, cap: object) -> bool:  # pragma: no cover - сервис T11 не проверяет права
        return False


@pytest.fixture
def mods() -> SimpleNamespace:
    import app.domain.auth.provider as provider
    import app.domain.auth.service as service
    import app.domain.auth.sessions as sessions
    from app.core import errors
    from app.core.security.passwords import PasswordHasher

    return SimpleNamespace(
        provider=provider, service=service, sessions=sessions, errors=errors, Hasher=PasswordHasher
    )


@pytest.fixture
def auth(mods: SimpleNamespace, fixed_clock: FixedClock, settings: Settings) -> SimpleNamespace:
    hasher = mods.Hasher(**CHEAP)
    provider = mods.provider.LocalPasswordProvider(hasher, max_failures=5, lock_duration=LOCK)
    store = mods.sessions.SessionStore(SECRET_KEY, idle_timeout=IDLE, absolute_timeout=ABSOLUTE)
    return SimpleNamespace(hasher=hasher, provider=provider, sessions=store, settings=settings)


def creds(mods: SimpleNamespace, login: str, password: str) -> Any:
    return mods.provider.PasswordCredentials(login=login, password=SecretStr(password))


async def user_state(db: AsyncSession, user_id: uuid.UUID) -> Any:
    row = await db.execute(
        text(
            "SELECT failed_login_count, login_locked_until, password_hash, "
            "must_change_password, password_changed_at, is_blocked "
            "FROM app_user WHERE id = :id"
        ),
        {"id": user_id},
    )
    return row.one()


async def session_row(db: AsyncSession, sid: bytes) -> Any:
    row = await db.execute(
        text(
            "SELECT id, user_id, workspace_id, created_at, last_activity_at, "
            "absolute_expires_at FROM user_session WHERE id = :id"
        ),
        {"id": sid},
    )
    return row.one_or_none()


async def count_sessions(db: AsyncSession, user_id: uuid.UUID | None = None) -> int:
    if user_id is None:
        res = await db.execute(text("SELECT count(*) FROM user_session"))
    else:
        res = await db.execute(
            text("SELECT count(*) FROM user_session WHERE user_id = :u"), {"u": user_id}
        )
    return int(res.scalar_one())


async def count_events(db: AsyncSession) -> int:
    return int((await db.execute(text("SELECT count(*) FROM domain_event"))).scalar_one())


async def fail_n(auth: SimpleNamespace, mods: SimpleNamespace, db: Any, login: str, n: int) -> None:
    for _ in range(n):
        result = await auth.provider.authenticate(db, creds(mods, login, WRONG), now=NOW)
        assert result is None


async def do_login(
    db: AsyncSession,
    auth: SimpleNamespace,
    mods: SimpleNamespace,
    login: str,
    password: str,
    *,
    now: datetime = NOW,
) -> Any:
    return await mods.service.login(
        db, auth.provider, auth.sessions, login=login, password=SecretStr(password), now=now
    )


def error_signature(exc: BaseException) -> tuple[Any, ...]:
    return (
        type(exc),
        getattr(exc, "status_code", None),
        str(getattr(exc, "code", None)),
        getattr(exc, "detail", None),
        str(exc),
    )


def policy_actor(user: UserRow, sessions: Any, token: str) -> FakeActor:
    return FakeActor(
        user_id=user.id,
        workspace_id=user.workspace_id,
        login=user.login,
        role=user.role,
        must_change_password=user.must_change_password,
        session_id=sessions.token_id(token),
    )


def write_initial_file(settings: Settings, login: str, password: str = "irrelevant-pass-1") -> Path:
    directory = settings.secrets_dir
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / INITIAL_FILE
    path.write_text(f"login={login}\npassword={password}\n", encoding="utf-8")
    return path


def _sqlstate(exc: DBAPIError) -> str | None:
    orig: Any = exc.orig
    for obj in (orig, getattr(orig, "__cause__", None)):
        code = getattr(obj, "sqlstate", None) or getattr(obj, "pgcode", None)
        if code:
            return str(code)
    return None


# --- LocalPasswordProvider: пароль, блокировка (AC-30, AC-37, FR-61) --------------------


async def test_ac37_provider_success_returns_user_id(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    user = await make_user(db, password=PASSWORD)
    got = await auth.provider.authenticate(db, creds(mods, user.login, PASSWORD), now=NOW)
    assert got == user.id


async def test_ac30_provider_wrong_password_and_unknown_login_return_none(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    user = await make_user(db, password=PASSWORD)
    assert await auth.provider.authenticate(db, creds(mods, user.login, WRONG), now=NOW) is None
    assert await auth.provider.authenticate(db, creds(mods, "nobody.here", WRONG), now=NOW) is None


async def test_ac37_failure_increments_counter(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    user = await make_user(db, password=PASSWORD)
    await fail_n(auth, mods, db, user.login, 3)
    state = await user_state(db, user.id)
    assert state.failed_login_count == 3
    assert state.login_locked_until is None


async def test_ac37_four_failures_then_correct_password_logs_in_and_resets_counter(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    user = await make_user(db, password=PASSWORD)
    await fail_n(auth, mods, db, user.login, 4)
    assert (await user_state(db, user.id)).failed_login_count == 4
    got = await auth.provider.authenticate(db, creds(mods, user.login, PASSWORD), now=NOW)
    assert got == user.id
    state = await user_state(db, user.id)
    assert state.failed_login_count == 0
    assert state.login_locked_until is None


async def test_ac37_success_resets_streak_failures_must_be_consecutive(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    user = await make_user(db, password=PASSWORD)
    await fail_n(auth, mods, db, user.login, 2)
    assert await auth.provider.authenticate(db, creds(mods, user.login, PASSWORD), now=NOW)
    await fail_n(auth, mods, db, user.login, 4)
    state = await user_state(db, user.id)
    assert state.failed_login_count == 4
    assert state.login_locked_until is None
    assert await auth.provider.authenticate(db, creds(mods, user.login, PASSWORD), now=NOW)


async def test_ac37_fifth_failure_locks_for_15_minutes_and_resets_counter(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    user = await make_user(db, password=PASSWORD)
    await fail_n(auth, mods, db, user.login, 5)
    state = await user_state(db, user.id)
    assert state.login_locked_until == NOW + LOCK
    assert state.failed_login_count == 0


async def test_ac37_correct_password_rejected_while_locked_and_state_untouched(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    user = await make_user(db, password=PASSWORD)
    await fail_n(auth, mods, db, user.login, 5)
    inside = NOW + LOCK - timedelta(seconds=1)
    got = await auth.provider.authenticate(db, creds(mods, user.login, PASSWORD), now=inside)
    assert got is None
    # неверный пароль внутри окна блокировки: счётчик не трогается, срок не продлевается
    got = await auth.provider.authenticate(db, creds(mods, user.login, WRONG), now=inside)
    assert got is None
    state = await user_state(db, user.id)
    assert state.failed_login_count == 0
    assert state.login_locked_until == NOW + LOCK


async def test_ac37_login_allowed_exactly_after_15_minutes(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    user = await make_user(db, password=PASSWORD)
    await fail_n(auth, mods, db, user.login, 5)
    got = await auth.provider.authenticate(db, creds(mods, user.login, PASSWORD), now=NOW + LOCK)
    assert got == user.id
    state = await user_state(db, user.id)
    assert state.failed_login_count == 0
    assert state.login_locked_until is None


async def test_ac37_wrong_password_after_lock_expired_starts_new_streak(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    user = await make_user(db, password=PASSWORD)
    await fail_n(auth, mods, db, user.login, 5)
    later = NOW + LOCK + timedelta(seconds=1)
    assert await auth.provider.authenticate(db, creds(mods, user.login, WRONG), now=later) is None
    state = await user_state(db, user.id)
    assert state.failed_login_count == 1


async def test_ac37_thresholds_come_from_constructor(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    provider = mods.provider.LocalPasswordProvider(
        auth.hasher, max_failures=3, lock_duration=timedelta(minutes=1)
    )
    user = await make_user(db, password=PASSWORD)
    for _ in range(3):
        assert await provider.authenticate(db, creds(mods, user.login, WRONG), now=NOW) is None
    state = await user_state(db, user.id)
    assert state.login_locked_until == NOW + timedelta(minutes=1)


async def test_ac30_unknown_login_runs_dummy_verify_not_verify(
    db: AsyncSession,
    auth: SimpleNamespace,
    mods: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    real_dummy = auth.hasher.dummy_verify
    real_verify = auth.hasher.verify

    def dummy_spy(password: str) -> None:
        calls.append("dummy")
        real_dummy(password)

    def verify_spy(password_hash: str, password: str) -> bool:
        calls.append("verify")
        return bool(real_verify(password_hash, password))

    monkeypatch.setattr(auth.hasher, "dummy_verify", dummy_spy)
    monkeypatch.setattr(auth.hasher, "verify", verify_spy)
    assert await auth.provider.authenticate(db, creds(mods, "nobody.here", WRONG), now=NOW) is None
    assert calls == ["dummy"]


async def test_ac37_locked_login_runs_dummy_verify_not_verify(
    db: AsyncSession,
    auth: SimpleNamespace,
    mods: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await make_user(db, password=PASSWORD)
    await fail_n(auth, mods, db, user.login, 5)
    calls: list[str] = []
    real_dummy = auth.hasher.dummy_verify

    def dummy_spy(password: str) -> None:
        calls.append("dummy")
        real_dummy(password)

    def verify_spy(password_hash: str, password: str) -> bool:
        calls.append("verify")
        return False

    monkeypatch.setattr(auth.hasher, "dummy_verify", dummy_spy)
    monkeypatch.setattr(auth.hasher, "verify", verify_spy)
    got = await auth.provider.authenticate(db, creds(mods, user.login, PASSWORD), now=NOW)
    assert got is None
    assert calls == ["dummy"]


async def test_ac30_unknown_login_creates_no_rows_and_is_never_locked(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    before = int((await db.execute(text("SELECT count(*) FROM app_user"))).scalar_one())
    for _ in range(8):
        assert (
            await auth.provider.authenticate(db, creds(mods, "ghost.user", WRONG), now=NOW) is None
        )
    after = int((await db.execute(text("SELECT count(*) FROM app_user"))).scalar_one())
    assert after == before


async def test_ac37_success_rehashes_outdated_hash(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    weaker = mods.Hasher(time_cost=2, memory_cost_kib=1024, parallelism=1)
    old_hash = weaker.hash(PASSWORD)
    assert auth.hasher.needs_rehash(old_hash)
    user = await make_user(db, password=PASSWORD, password_hash=old_hash)
    got = await auth.provider.authenticate(db, creds(mods, user.login, PASSWORD), now=NOW)
    assert got == user.id
    new_hash = (await user_state(db, user.id)).password_hash
    assert new_hash != old_hash
    assert not auth.hasher.needs_rehash(new_hash)
    assert auth.hasher.verify(new_hash, PASSWORD)


async def test_ac30_surrogate_password_is_plain_failure_not_exception(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    user = await make_user(db, password=PASSWORD)
    assert await auth.provider.authenticate(db, creds(mods, user.login, SURROGATE), now=NOW) is None
    assert (
        await auth.provider.authenticate(db, creds(mods, "ghost.user", SURROGATE), now=NOW) is None
    )


# --- login(): одинаковый отказ (AC-20, AC-30, AC-37, FR-61, FR-73) ----------------------

LONG_LOGIN = "a" * 65


async def _scenario_wrong_password(db: Any, auth: Any, mods: Any) -> tuple[str, str]:
    user = await make_user(db, password=PASSWORD)
    return user.login, WRONG


async def _scenario_unknown_login(db: Any, auth: Any, mods: Any) -> tuple[str, str]:
    return "nobody.here", WRONG


async def _scenario_blocked_correct(db: Any, auth: Any, mods: Any) -> tuple[str, str]:
    user = await make_user(db, password=PASSWORD, blocked=True, role="user")
    return user.login, PASSWORD


async def _scenario_blocked_wrong(db: Any, auth: Any, mods: Any) -> tuple[str, str]:
    user = await make_user(db, password=PASSWORD, blocked=True)
    return user.login, WRONG


async def _scenario_locked_correct(db: Any, auth: Any, mods: Any) -> tuple[str, str]:
    user = await make_user(db, password=PASSWORD)
    await fail_n(auth, mods, db, user.login, 5)
    return user.login, PASSWORD


async def _scenario_no_membership(db: Any, auth: Any, mods: Any) -> tuple[str, str]:
    user = await make_user(db, password=PASSWORD, role="user")
    await db.execute(text("DELETE FROM workspace_member WHERE user_id = :u"), {"u": user.id})
    return user.login, PASSWORD


async def _scenario_pattern_short(db: Any, auth: Any, mods: Any) -> tuple[str, str]:
    return "ab", PASSWORD


async def _scenario_pattern_cyrillic(db: Any, auth: Any, mods: Any) -> tuple[str, str]:
    return "иван", PASSWORD


async def _scenario_pattern_space(db: Any, auth: Any, mods: Any) -> tuple[str, str]:
    return "ivan petrov", PASSWORD


async def _scenario_pattern_long(db: Any, auth: Any, mods: Any) -> tuple[str, str]:
    return LONG_LOGIN, PASSWORD


async def _scenario_pattern_empty(db: Any, auth: Any, mods: Any) -> tuple[str, str]:
    return "", PASSWORD


async def _scenario_pattern_nul(db: Any, auth: Any, mods: Any) -> tuple[str, str]:
    return "ivan\x00petrov", PASSWORD


async def _scenario_surrogate_password(db: Any, auth: Any, mods: Any) -> tuple[str, str]:
    user = await make_user(db, password=PASSWORD)
    return user.login, SURROGATE


async def _scenario_surrogate_unknown(db: Any, auth: Any, mods: Any) -> tuple[str, str]:
    return "nobody.here", SURROGATE


SCENARIOS = {
    "wrong_password": _scenario_wrong_password,
    "unknown_login": _scenario_unknown_login,
    "blocked_correct_password": _scenario_blocked_correct,
    "blocked_wrong_password": _scenario_blocked_wrong,
    "locked_correct_password": _scenario_locked_correct,
    "no_workspace_membership": _scenario_no_membership,
    "pattern_too_short": _scenario_pattern_short,
    "pattern_cyrillic": _scenario_pattern_cyrillic,
    "pattern_space": _scenario_pattern_space,
    "pattern_65_chars": _scenario_pattern_long,
    "pattern_empty": _scenario_pattern_empty,
    "pattern_nul": _scenario_pattern_nul,
    "surrogate_password": _scenario_surrogate_password,
    "surrogate_unknown_login": _scenario_surrogate_unknown,
}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
async def test_ac30_every_failure_reason_is_plain_invalid_credentials(
    name: str, db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    """AC-20, AC-30, AC-37, FR-61: один тип, код, статус и текст для всех причин отказа."""
    login, password = await SCENARIOS[name](db, auth, mods)
    sessions_before = await count_sessions(db)
    with pytest.raises(mods.errors.InvalidCredentials) as info:
        await do_login(db, auth, mods, login, password)
    exc = info.value
    assert type(exc) is mods.errors.InvalidCredentials
    assert exc.status_code == 401
    assert str(exc.code) == "invalid_credentials"
    assert exc.detail == mods.errors.InvalidCredentials.default_detail
    assert await count_sessions(db) == sessions_before, "отказ не должен создавать сессию"


async def test_ac30_failure_signatures_are_identical_across_reasons(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    signatures = set()
    for name in sorted(SCENARIOS):
        login, password = await SCENARIOS[name](db, auth, mods)
        with pytest.raises(mods.errors.InvalidCredentials) as info:
            await do_login(db, auth, mods, login, password)
        signatures.add(error_signature(info.value))
    assert len(signatures) == 1, signatures


async def test_ac30_unknown_login_via_service_runs_dummy_verify(
    db: AsyncSession,
    auth: SimpleNamespace,
    mods: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    real = auth.hasher.dummy_verify

    def spy(password: str) -> None:
        calls.append("dummy")
        real(password)

    monkeypatch.setattr(auth.hasher, "dummy_verify", spy)
    with pytest.raises(mods.errors.InvalidCredentials):
        await do_login(db, auth, mods, "nobody.here", WRONG)
    assert calls == ["dummy"]


# --- login(): успешный вход (FR-1, FR-66, FR-73, AC-116, AC-113) ------------------------


async def test_fr1_login_success_returns_token_user_and_creates_session(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    user = await make_user(db, password=PASSWORD, role="business_admin")
    result = await do_login(db, auth, mods, user.login, PASSWORD)
    assert result.user_id == user.id
    assert result.login == user.login
    assert result.role == "business_admin"
    assert result.must_change_password is False
    assert isinstance(result.token, str) and result.token
    record = await auth.sessions.resolve(db, result.token, now=NOW, background=False)
    assert record is not None
    assert record.user_id == user.id
    assert record.workspace_id == user.workspace_id
    assert await count_sessions(db, user.id) == 1


async def test_ac116_login_is_lowercased(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    user = await make_user(db, password=PASSWORD, login="ivan.petrov", role="user")
    result = await do_login(db, auth, mods, "IVAN.PETROV", PASSWORD)
    assert result.user_id == user.id
    assert result.login == "ivan.petrov"
    result2 = await do_login(db, auth, mods, "Ivan.Petrov", PASSWORD)
    assert result2.user_id == user.id


async def test_fr66_user_without_role_can_log_in(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    user = await make_user(db, password=PASSWORD, role=None)
    result = await do_login(db, auth, mods, user.login, PASSWORD)
    assert result.role is None
    assert result.user_id == user.id
    assert await auth.sessions.resolve(db, result.token, now=NOW, background=False) is not None


async def test_ac113_login_with_one_time_password_reports_must_change(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    user = await make_user(db, password=PASSWORD, role="user", must_change_password=True)
    result = await do_login(db, auth, mods, user.login, PASSWORD)
    assert result.must_change_password is True


async def test_ac37_login_after_four_failures_succeeds_via_service(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    user = await make_user(db, password=PASSWORD, role="user")
    for _ in range(4):
        with pytest.raises(mods.errors.InvalidCredentials):
            await do_login(db, auth, mods, user.login, WRONG)
    result = await do_login(db, auth, mods, user.login, PASSWORD)
    assert result.user_id == user.id
    assert (await user_state(db, user.id)).failed_login_count == 0


async def test_ac37_five_failures_then_correct_password_rejected_then_ok_after_15_min(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    user = await make_user(db, password=PASSWORD, role="user")
    for _ in range(5):
        with pytest.raises(mods.errors.InvalidCredentials):
            await do_login(db, auth, mods, user.login, WRONG)
    with pytest.raises(mods.errors.InvalidCredentials):
        await do_login(db, auth, mods, user.login, PASSWORD, now=NOW + LOCK - timedelta(seconds=1))
    result = await do_login(db, auth, mods, user.login, PASSWORD, now=NOW + LOCK)
    assert result.user_id == user.id


async def test_ac20_blocked_user_with_correct_password_gets_no_session(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    user = await make_user(db, password=PASSWORD, role="user", blocked=True)
    with pytest.raises(mods.errors.InvalidCredentials):
        await do_login(db, auth, mods, user.login, PASSWORD)
    assert await count_sessions(db, user.id) == 0


@pytest.mark.committed
async def test_ac37_failed_attempts_survive_request_rollback_plan_issue(
    committed: async_sessionmaker[AsyncSession], mods: SimpleNamespace, fixed_clock: FixedClock
) -> None:
    """PLAN_ISSUE (см. отчёт): get_db откатывает транзакцию при исключении, а сервисы не
    вызывают commit(); без отдельной фиксации счётчик неудач теряется и блокировка (AC-37)
    не срабатывает. Тест моделирует запрос: исключение -> ROLLBACK сессии."""
    hasher = mods.Hasher(**CHEAP)
    provider = mods.provider.LocalPasswordProvider(hasher, max_failures=5, lock_duration=LOCK)
    store = mods.sessions.SessionStore(SECRET_KEY, idle_timeout=IDLE, absolute_timeout=ABSOLUTE)
    async with committed() as s:
        user = await make_user(s, password=PASSWORD, role="user")
        await s.commit()
    for _ in range(5):
        async with committed() as s:
            try:
                await mods.service.login(
                    s, provider, store, login=user.login, password=SecretStr(WRONG), now=NOW
                )
            except mods.errors.InvalidCredentials:
                await s.rollback()
            else:  # pragma: no cover
                pytest.fail("вход с неверным паролем не должен проходить")
    async with committed() as s:
        with pytest.raises(mods.errors.InvalidCredentials):
            await mods.service.login(
                s, provider, store, login=user.login, password=SecretStr(PASSWORD), now=NOW
            )
        await s.rollback()
    async with committed() as s:
        assert await count_sessions(s, user.id) == 0
        assert (await user_state(s, user.id)).login_locked_until == NOW + LOCK


# --- SessionStore: токен и хранение (D-13, FR-58) ---------------------------------------


async def test_d13_token_is_long_random_urlsafe_and_unique(
    db: AsyncSession, auth: SimpleNamespace
) -> None:
    user = await make_user(db, role="user")
    tokens = [
        await auth.sessions.create(db, user_id=user.id, workspace_id=user.workspace_id, now=NOW)
        for _ in range(3)
    ]
    assert len(set(tokens)) == 3
    for token in tokens:
        assert re.fullmatch(r"[A-Za-z0-9_-]+", token), token
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        assert len(raw) >= 32


async def test_d13_db_stores_hmac_of_token_not_token(
    db: AsyncSession, auth: SimpleNamespace
) -> None:
    user = await make_user(db, role="user")
    token = await auth.sessions.create(db, user_id=user.id, workspace_id=user.workspace_id, now=NOW)
    expected = hmac.new(SECRET_KEY, token.encode("utf-8"), hashlib.sha256).digest()
    assert auth.sessions.token_id(token) == expected
    row = await session_row(db, expected)
    assert row is not None
    assert len(row.id) == 32
    assert row.id != token.encode("utf-8")
    assert await session_row(db, token.encode("utf-8")) is None
    dump = await db.execute(text("SELECT id FROM user_session"))
    stored = [bytes(r[0]) for r in dump]
    assert all(token.encode("utf-8") not in value for value in stored)


async def test_d13_token_id_depends_on_secret_key(mods: SimpleNamespace) -> None:
    a = mods.sessions.SessionStore(b"a" * 32, idle_timeout=IDLE, absolute_timeout=ABSOLUTE)
    b = mods.sessions.SessionStore(b"b" * 32, idle_timeout=IDLE, absolute_timeout=ABSOLUTE)
    assert a.token_id("some-token") == a.token_id("some-token")
    assert a.token_id("some-token") != b.token_id("some-token")
    assert len(a.token_id("some-token")) == 32


async def test_d13_session_row_timestamps(db: AsyncSession, auth: SimpleNamespace) -> None:
    user = await make_user(db, role="user")
    token = await auth.sessions.create(db, user_id=user.id, workspace_id=user.workspace_id, now=NOW)
    row = await session_row(db, auth.sessions.token_id(token))
    assert row.user_id == user.id
    assert row.workspace_id == user.workspace_id
    assert row.created_at == NOW
    assert row.last_activity_at == NOW
    assert row.absolute_expires_at == NOW + ABSOLUTE


async def test_d13_resolve_unknown_or_foreign_key_token_is_none(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    user = await make_user(db, role="user")
    token = await auth.sessions.create(db, user_id=user.id, workspace_id=user.workspace_id, now=NOW)
    assert await auth.sessions.resolve(db, "x" * 43, now=NOW, background=False) is None
    assert await auth.sessions.resolve(db, token[:-1], now=NOW, background=False) is None
    other = mods.sessions.SessionStore(b"z" * 32, idle_timeout=IDLE, absolute_timeout=ABSOLUTE)
    assert await other.resolve(db, token, now=NOW, background=False) is None
    assert await auth.sessions.resolve(db, token, now=NOW, background=False) is not None


# --- SessionStore: сроки (AC-32, AC-33, AC-79, FR-59) -----------------------------------


@pytest.mark.parametrize("background", [False, True])
async def test_ac32_idle_boundary_alive_one_second_before_8h(
    background: bool, db: AsyncSession, auth: SimpleNamespace
) -> None:
    user = await make_user(db, role="user")
    token = await auth.sessions.create(db, user_id=user.id, workspace_id=user.workspace_id, now=NOW)
    at = NOW + IDLE - timedelta(seconds=1)
    record = await auth.sessions.resolve(db, token, now=at, background=background)
    assert record is not None
    assert record.user_id == user.id


@pytest.mark.parametrize("background", [False, True])
async def test_ac32_idle_boundary_dead_at_exactly_8h_and_row_deleted(
    background: bool, db: AsyncSession, auth: SimpleNamespace
) -> None:
    user = await make_user(db, role="user")
    token = await auth.sessions.create(db, user_id=user.id, workspace_id=user.workspace_id, now=NOW)
    sid = auth.sessions.token_id(token)
    assert await auth.sessions.resolve(db, token, now=NOW + IDLE, background=background) is None
    assert await session_row(db, sid) is None
    # удалена: «воскреснуть» в пределах окна нельзя
    assert await auth.sessions.resolve(db, token, now=NOW, background=False) is None


async def test_ac32_activity_extends_idle_window(db: AsyncSession, auth: SimpleNamespace) -> None:
    user = await make_user(db, role="user")
    token = await auth.sessions.create(db, user_id=user.id, workspace_id=user.workspace_id, now=NOW)
    t1 = NOW + timedelta(hours=7)
    assert await auth.sessions.resolve(db, token, now=t1, background=False) is not None
    row = await session_row(db, auth.sessions.token_id(token))
    assert row.last_activity_at == t1
    # 7 ч + 7 ч 59 мин 59 с после создания, но < 8 ч после последней активности
    t2 = t1 + IDLE - timedelta(seconds=1)
    assert await auth.sessions.resolve(db, token, now=t2, background=False) is not None


async def test_ac79_background_does_not_touch_last_activity(
    db: AsyncSession, auth: SimpleNamespace
) -> None:
    user = await make_user(db, role="user")
    token = await auth.sessions.create(db, user_id=user.id, workspace_id=user.workspace_id, now=NOW)
    sid = auth.sessions.token_id(token)
    for minutes in (30, 120, 7 * 60 + 59):
        at = NOW + timedelta(minutes=minutes)
        assert await auth.sessions.resolve(db, token, now=at, background=True) is not None
        assert (await session_row(db, sid)).last_activity_at == NOW


async def test_ac79_after_7h59_of_polling_ordinary_request_works_and_refreshes(
    db: AsyncSession, auth: SimpleNamespace
) -> None:
    user = await make_user(db, role="user")
    token = await auth.sessions.create(db, user_id=user.id, workspace_id=user.workspace_id, now=NOW)
    t = NOW + timedelta(hours=7, minutes=59)
    assert await auth.sessions.resolve(db, token, now=t, background=True) is not None
    assert await auth.sessions.resolve(db, token, now=t, background=False) is not None
    assert (await session_row(db, auth.sessions.token_id(token))).last_activity_at == t


async def test_ac79_after_8h01_of_polling_session_is_dead(
    db: AsyncSession, auth: SimpleNamespace
) -> None:
    user = await make_user(db, role="user")
    token = await auth.sessions.create(db, user_id=user.id, workspace_id=user.workspace_id, now=NOW)
    for minutes in (60, 4 * 60, 7 * 60 + 59):
        assert (
            await auth.sessions.resolve(
                db, token, now=NOW + timedelta(minutes=minutes), background=True
            )
            is not None
        )
    at = NOW + timedelta(hours=8, minutes=1)
    assert await auth.sessions.resolve(db, token, now=at, background=False) is None


async def test_ac33_absolute_timeout_7_days_despite_continuous_activity(
    db: AsyncSession, auth: SimpleNamespace
) -> None:
    user = await make_user(db, role="user")
    token = await auth.sessions.create(db, user_id=user.id, workspace_id=user.workspace_id, now=NOW)
    sid = auth.sessions.token_id(token)
    for k in range(1, 28):  # каждые 6 ч, до 162 ч
        at = NOW + timedelta(hours=6 * k)
        assert await auth.sessions.resolve(db, token, now=at, background=False) is not None
    last = NOW + ABSOLUTE - timedelta(seconds=1)
    assert await auth.sessions.resolve(db, token, now=last, background=False) is not None
    # активность была 1 секунду назад, но 7 суток с входа истекли
    assert await auth.sessions.resolve(db, token, now=NOW + ABSOLUTE, background=False) is None
    assert await session_row(db, sid) is None


async def test_ac33_absolute_timeout_applies_to_background_requests_too(
    db: AsyncSession, auth: SimpleNamespace
) -> None:
    user = await make_user(db, role="user")
    token = await auth.sessions.create(db, user_id=user.id, workspace_id=user.workspace_id, now=NOW)
    for k in range(1, 28):
        at = NOW + timedelta(hours=6 * k)
        assert await auth.sessions.resolve(db, token, now=at, background=False) is not None
    at = NOW + ABSOLUTE
    assert await auth.sessions.resolve(db, token, now=at, background=True) is None


async def test_ac33_expiry_deletes_only_the_expired_session(
    db: AsyncSession, auth: SimpleNamespace
) -> None:
    user = await make_user(db, role="user")
    old = await auth.sessions.create(db, user_id=user.id, workspace_id=user.workspace_id, now=NOW)
    later = NOW + timedelta(hours=7)
    fresh = await auth.sessions.create(
        db, user_id=user.id, workspace_id=user.workspace_id, now=later
    )
    at = NOW + IDLE + timedelta(minutes=1)
    assert await auth.sessions.resolve(db, old, now=at, background=False) is None
    assert await auth.sessions.resolve(db, fresh, now=at, background=False) is not None
    assert await count_sessions(db, user.id) == 1


# --- logout, завершение сессий (AC-34, AC-20, FR-5, FR-60, FR-62) -----------------------


async def test_ac34_logout_deletes_session_on_server(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    user = await make_user(db, password=PASSWORD, role="user")
    result = await do_login(db, auth, mods, user.login, PASSWORD)
    other = await do_login(db, auth, mods, user.login, PASSWORD)
    await mods.service.logout(db, auth.sessions, result.token)
    assert await session_row(db, auth.sessions.token_id(result.token)) is None
    assert await auth.sessions.resolve(db, result.token, now=NOW, background=False) is None
    assert await auth.sessions.resolve(db, other.token, now=NOW, background=False) is not None


async def test_ac34_logout_is_idempotent_for_unknown_or_repeated_token(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    user = await make_user(db, password=PASSWORD, role="user")
    result = await do_login(db, auth, mods, user.login, PASSWORD)
    await mods.service.logout(db, auth.sessions, result.token)
    await mods.service.logout(db, auth.sessions, result.token)
    await mods.service.logout(db, auth.sessions, "never-issued-token")
    assert await auth.sessions.resolve(db, result.token, now=NOW, background=False) is None


async def test_ac113_logout_works_for_user_with_one_time_password(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    user = await make_user(db, password=PASSWORD, role="user", must_change_password=True)
    result = await do_login(db, auth, mods, user.login, PASSWORD)
    await mods.service.logout(db, auth.sessions, result.token)
    assert await auth.sessions.resolve(db, result.token, now=NOW, background=False) is None


async def test_fr62_delete_all_for_user_removes_every_session_and_counts(
    db: AsyncSession, auth: SimpleNamespace
) -> None:
    victim = await make_user(db, role="user")
    bystander = await make_user(db, role="user")
    tokens = [
        await auth.sessions.create(db, user_id=victim.id, workspace_id=victim.workspace_id, now=NOW)
        for _ in range(3)
    ]
    keep = await auth.sessions.create(
        db, user_id=bystander.id, workspace_id=bystander.workspace_id, now=NOW
    )
    removed = await auth.sessions.delete_all_for_user(db, victim.id)
    assert removed == 3
    for token in tokens:
        assert await auth.sessions.resolve(db, token, now=NOW, background=False) is None
    assert await auth.sessions.resolve(db, keep, now=NOW, background=False) is not None
    assert await auth.sessions.delete_all_for_user(db, victim.id) == 0


async def test_fr5_delete_all_for_user_keep_id_spares_exactly_one(
    db: AsyncSession, auth: SimpleNamespace
) -> None:
    user = await make_user(db, role="user")
    tokens = [
        await auth.sessions.create(db, user_id=user.id, workspace_id=user.workspace_id, now=NOW)
        for _ in range(3)
    ]
    keep_id = auth.sessions.token_id(tokens[1])
    removed = await auth.sessions.delete_all_for_user(db, user.id, keep_id=keep_id)
    assert removed == 2
    assert await auth.sessions.resolve(db, tokens[1], now=NOW, background=False) is not None
    assert await auth.sessions.resolve(db, tokens[0], now=NOW, background=False) is None
    assert await auth.sessions.resolve(db, tokens[2], now=NOW, background=False) is None


# --- change_own_password (AC-27, AC-28, AC-29, AC-31, AC-115, FR-56, FR-6, FR-57) -------


async def _prepare_change(
    db: AsyncSession,
    auth: SimpleNamespace,
    *,
    role: str | None = "tech_admin",
    must_change: bool = False,
    login: str | None = None,
) -> SimpleNamespace:
    user = await make_user(
        db, password=PASSWORD, role=role, must_change_password=must_change, login=login
    )
    stranger = await make_user(db, password=PASSWORD, role="user")
    tokens = [
        await auth.sessions.create(db, user_id=user.id, workspace_id=user.workspace_id, now=NOW)
        for _ in range(3)
    ]
    stranger_token = await auth.sessions.create(
        db, user_id=stranger.id, workspace_id=stranger.workspace_id, now=NOW
    )
    return SimpleNamespace(
        user=user,
        stranger=stranger,
        tokens=tokens,
        stranger_token=stranger_token,
        actor=policy_actor(user, auth.sessions, tokens[0]),
    )


async def change(
    db: AsyncSession,
    auth: SimpleNamespace,
    mods: SimpleNamespace,
    ctx: SimpleNamespace,
    *,
    current: str = PASSWORD,
    new: str = NEW_PASSWORD,
    now: datetime = NOW,
) -> None:
    await mods.service.change_own_password(
        db,
        ctx.actor,
        auth.hasher,
        auth.sessions,
        auth.settings,
        current=SecretStr(current),
        new=SecretStr(new),
        now=now,
    )


async def assert_unchanged(
    db: AsyncSession, auth: SimpleNamespace, ctx: SimpleNamespace, before_hash: str
) -> None:
    state = await user_state(db, ctx.user.id)
    assert state.password_hash == before_hash
    for token in ctx.tokens:
        assert await auth.sessions.resolve(db, token, now=NOW, background=True) is not None


async def expect_code(
    mods: SimpleNamespace, awaitable: Any, code: str, *, status: int = 422
) -> BaseException:
    with pytest.raises(mods.errors.AppError) as info:
        await awaitable
    exc = info.value
    assert exc.status_code == status
    assert str(exc.code) == code
    return exc  # type: ignore[no-any-return]


async def test_ac31_change_password_keeps_current_and_drops_other_sessions(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    ctx = await _prepare_change(db, auth)
    later = NOW + timedelta(minutes=5)
    await change(db, auth, mods, ctx, now=later)
    assert await auth.sessions.resolve(db, ctx.tokens[0], now=later, background=False) is not None
    assert await auth.sessions.resolve(db, ctx.tokens[1], now=later, background=False) is None
    assert await auth.sessions.resolve(db, ctx.tokens[2], now=later, background=False) is None
    assert (
        await auth.sessions.resolve(db, ctx.stranger_token, now=later, background=False) is not None
    )
    assert await count_sessions(db, ctx.user.id) == 1


async def test_ac29_change_password_updates_hash_flags_and_timestamp(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    ctx = await _prepare_change(db, auth, must_change=True)
    later = NOW + timedelta(minutes=5)
    await change(db, auth, mods, ctx, now=later)
    state = await user_state(db, ctx.user.id)
    assert state.must_change_password is False
    assert state.password_changed_at == later
    assert state.password_hash.startswith("$argon2id$")
    assert NEW_PASSWORD not in state.password_hash
    assert auth.hasher.verify(state.password_hash, NEW_PASSWORD)
    assert not auth.hasher.verify(state.password_hash, PASSWORD)


async def test_ac29_after_change_old_password_fails_and_new_works(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    ctx = await _prepare_change(db, auth, must_change=True)
    await change(db, auth, mods, ctx)
    with pytest.raises(mods.errors.InvalidCredentials):
        await do_login(db, auth, mods, ctx.user.login, PASSWORD)
    result = await do_login(db, auth, mods, ctx.user.login, NEW_PASSWORD)
    assert result.must_change_password is False
    assert result.user_id == ctx.user.id


async def test_fr56_wrong_current_password_code_and_no_changes(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    ctx = await _prepare_change(db, auth, must_change=True)
    before = (await user_state(db, ctx.user.id)).password_hash
    await expect_code(mods, change(db, auth, mods, ctx, current=WRONG), "invalid_current_password")
    await assert_unchanged(db, auth, ctx, before)
    assert (await user_state(db, ctx.user.id)).must_change_password is True


async def test_fr56_same_password_is_reused(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    ctx = await _prepare_change(db, auth)
    before = (await user_state(db, ctx.user.id)).password_hash
    await expect_code(mods, change(db, auth, mods, ctx, new=PASSWORD), "password_reused")
    await assert_unchanged(db, auth, ctx, before)


async def test_ac27_new_password_of_11_chars_is_too_short_and_12_accepted(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    ctx = await _prepare_change(db, auth)
    before = (await user_state(db, ctx.user.id)).password_hash
    await expect_code(mods, change(db, auth, mods, ctx, new="zq9-lk3-px7"), "password_too_short")
    await assert_unchanged(db, auth, ctx, before)
    await change(db, auth, mods, ctx, new="zq9-lk3-px7w")
    assert auth.hasher.verify((await user_state(db, ctx.user.id)).password_hash, "zq9-lk3-px7w")


def _common_entries() -> list[str]:
    path = BACKEND_DIR / "app" / "core" / "security" / "data" / "common-passwords-10k.txt"
    return path.read_text(encoding="utf-8").split("\n")[:-1]


async def test_ac28_common_password_of_12_plus_chars_rejected(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    common = next(e for e in _common_entries() if len(e) >= 12 and e != PASSWORD)
    ctx = await _prepare_change(db, auth)
    before = (await user_state(db, ctx.user.id)).password_hash
    await expect_code(mods, change(db, auth, mods, ctx, new=common), "password_too_common")
    await assert_unchanged(db, auth, ctx, before)


async def test_ac115_common_password_with_one_letter_case_changed_is_accepted(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    from app.core.security.common_passwords import is_common_password

    variant = None
    for entry in _common_entries():
        if len(entry) < 12:
            continue
        idx = next((i for i, ch in enumerate(entry) if ch.islower()), None)
        if idx is None:
            continue
        candidate = entry[:idx] + entry[idx].upper() + entry[idx + 1 :]
        if not is_common_password(candidate):
            variant = candidate
            break
    assert variant is not None
    ctx = await _prepare_change(db, auth)
    await change(db, auth, mods, ctx, new=variant)
    assert auth.hasher.verify((await user_state(db, ctx.user.id)).password_hash, variant)


async def test_ac27_short_and_common_reports_too_short(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    from app.core.security.common_passwords import is_common_password

    short_common = next(e for e in _common_entries() if 4 <= len(e) < 12)
    assert is_common_password(short_common)
    ctx = await _prepare_change(db, auth)
    await expect_code(mods, change(db, auth, mods, ctx, new=short_common), "password_too_short")


async def test_fr56_current_password_is_checked_before_policy(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    """Порядок plan §4.6: invalid_current_password, затем password_reused, затем политика."""
    ctx = await _prepare_change(db, auth)
    await expect_code(
        mods, change(db, auth, mods, ctx, current=WRONG, new="short"), "invalid_current_password"
    )


async def test_t08_note_new_password_with_lone_surrogate_is_domain_422(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    ctx = await _prepare_change(db, auth)
    before = (await user_state(db, ctx.user.id)).password_hash
    with pytest.raises(mods.errors.AppError) as info:
        await change(db, auth, mods, ctx, new=SURROGATE)
    assert info.value.status_code == 422
    assert SURROGATE not in str(info.value)
    assert SURROGATE not in repr(info.value.args)
    await assert_unchanged(db, auth, ctx, before)


async def test_t08_note_current_password_with_lone_surrogate_is_invalid_current(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    ctx = await _prepare_change(db, auth)
    await expect_code(
        mods, change(db, auth, mods, ctx, current=SURROGATE), "invalid_current_password"
    )


async def test_fr6_change_does_not_remove_initial_admin_file_for_this_login_before_commit(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    """Порядок T14 (tasks.md, «Уточнения» п.2): файл удаляется ПОСЛЕ COMMIT, а не внутри сервиса.

    Сервис не фиксирует транзакцию, поэтому в момент возврата из ``change_own_password`` смена
    ещё может быть откачена, и файл с прежним паролем обязан остаться на месте. Удаление после
    фиксации (на уровне роута или хука ``after_commit``) проверяется через HTTP:
    ``tests/api/test_password_change.py`` (``test_ac23_*``: после 204 файла нет; при сбое COMMIT
    файл на месте; в момент ``before_commit`` файл ещё существует).
    """
    ctx = await _prepare_change(db, auth, must_change=True, login="admin")
    path = write_initial_file(auth.settings, "admin")
    assert path.exists()
    await change(db, auth, mods, ctx)
    assert path.exists()
    # смена применена в транзакции, но не зафиксирована: откат вернул бы старый пароль
    state = await user_state(db, ctx.user.id)
    assert auth.hasher.verify(state.password_hash, NEW_PASSWORD)


async def test_fr6_change_keeps_initial_admin_file_of_other_login(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    ctx = await _prepare_change(db, auth, must_change=True, login="second.admin")
    path = write_initial_file(auth.settings, "admin")
    await change(db, auth, mods, ctx)
    assert path.exists()


async def test_fr6_rejected_change_keeps_initial_admin_file(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    ctx = await _prepare_change(db, auth, must_change=True, login="admin")
    path = write_initial_file(auth.settings, "admin")
    await expect_code(mods, change(db, auth, mods, ctx, current=WRONG), "invalid_current_password")
    assert path.exists()


async def test_fr6_file_removal_failure_does_not_undo_password_change(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    """Plan молчит об исходе (см. отчёт). Фиксируем: пароль сменён, остальные сессии удалены,
    исключение не выходит наружу (файл с уже недействительным паролем безвреден)."""
    ctx = await _prepare_change(db, auth, must_change=True, login="admin")
    auth.settings.secrets_dir.mkdir(parents=True, exist_ok=True)
    (auth.settings.secrets_dir / INITIAL_FILE).mkdir()  # read_bytes -> IsADirectoryError
    await change(db, auth, mods, ctx)
    state = await user_state(db, ctx.user.id)
    assert auth.hasher.verify(state.password_hash, NEW_PASSWORD)
    assert state.must_change_password is False
    assert await count_sessions(db, ctx.user.id) == 1


# --- события и логи (FR-41, FR-57) ------------------------------------------------------


async def test_fr41_login_logout_change_password_write_no_events(
    db: AsyncSession, auth: SimpleNamespace, mods: SimpleNamespace
) -> None:
    ctx = await _prepare_change(db, auth, must_change=True)
    before = await count_events(db)
    for _ in range(6):  # неудачи + блокировка
        with pytest.raises(mods.errors.InvalidCredentials):
            await do_login(db, auth, mods, ctx.user.login, WRONG)
    await do_login(db, auth, mods, ctx.user.login, PASSWORD, now=NOW + LOCK)
    await change(db, auth, mods, ctx)
    await mods.service.logout(db, auth.sessions, ctx.tokens[0])
    assert await count_events(db) == before


async def test_fr57_no_secrets_in_logs_or_error_objects(
    db: AsyncSession,
    auth: SimpleNamespace,
    mods: SimpleNamespace,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.core.logging import configure_logging

    configure_logging("DEBUG")
    capsys.readouterr()
    caplog.set_level(logging.DEBUG)
    typed_wrong = "leaky-wrong-password-4412"
    typed_new = "leaky-new-password-7781"
    ctx = await _prepare_change(db, auth, must_change=True)
    errors: list[BaseException] = []
    for password in (typed_wrong, SURROGATE):
        try:
            await do_login(db, auth, mods, ctx.user.login, password)
        except mods.errors.InvalidCredentials as exc:
            errors.append(exc)
    for kwargs in (
        {"current": typed_wrong, "new": typed_new},
        {"new": SURROGATE},
        {"new": "short-1"},
    ):
        try:
            await change(db, auth, mods, ctx, **kwargs)
        except mods.errors.AppError as exc:
            errors.append(exc)
    token = (await do_login(db, auth, mods, ctx.user.login, PASSWORD)).token
    await change(db, auth, mods, ctx, new=typed_new)
    await mods.service.logout(db, auth.sessions, token)

    out = capsys.readouterr().out
    haystacks = [caplog.text, out, *(r.getMessage() for r in caplog.records)]
    for record in caplog.records:
        haystacks.append(repr(record.args))
        haystacks.append(str(record.exc_text))
    for line in out.splitlines():
        if line.strip():
            json.loads(line)  # JSON-вывод остаётся валидным
    for secret in (PASSWORD, typed_wrong, typed_new, NEW_PASSWORD, SURROGATE, token):
        for text_ in haystacks:
            assert secret not in text_, f"секрет попал в лог: {secret[:8]}..."
    for exc in errors:
        blob = f"{exc!s} {exc!r} {exc.args!r} {getattr(exc, 'detail', '')}"
        for secret in (PASSWORD, typed_wrong, typed_new, SURROGATE):
            assert secret not in blob


# --- миграция 0003 (заметка ревью T06) --------------------------------------------------


def _migration_0003() -> Path | None:
    found = sorted((BACKEND_DIR / "migrations" / "versions").glob(MIGRATION_0003_GLOB))
    return found[0] if found else None


def test_t06_note_migration_0003_file_chain() -> None:
    import ast

    path = _migration_0003()
    assert path is not None, "нет backend/migrations/versions/0003_*.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    funcs = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert {"upgrade", "downgrade"} <= funcs
    values: dict[str, Any] = {}
    for n in tree.body:
        target: Any = None
        value: Any = None
        if isinstance(n, ast.Assign) and len(n.targets) == 1:
            target, value = n.targets[0], n.value
        elif isinstance(n, ast.AnnAssign):
            target, value = n.target, n.value
        if isinstance(target, ast.Name) and isinstance(value, ast.Constant):
            values[target.id] = value.value
    assert values.get("revision") == "0003"
    assert values.get("down_revision") == "0002"


async def _try_insert_session(db: AsyncSession, user: UserRow, sid: bytes) -> None:
    await db.execute(
        get_table("user_session")
        .insert()
        .values(
            id=sid,
            user_id=user.id,
            workspace_id=user.workspace_id,
            created_at=NOW,
            last_activity_at=NOW,
            absolute_expires_at=NOW + ABSOLUTE,
        )
    )


@pytest.mark.parametrize("length", [0, 1, 31, 33, 64])
async def test_t06_note_user_session_id_length_check_rejects(length: int, db: AsyncSession) -> None:
    user = await make_user(db, role="user")
    with pytest.raises(DBAPIError) as info:
        async with db.begin_nested():
            await _try_insert_session(db, user, b"\x01" * length)
    assert _sqlstate(info.value) == CHECK_VIOLATION


async def test_t06_note_user_session_id_of_32_bytes_accepted(db: AsyncSession) -> None:
    user = await make_user(db, role="user")
    await _try_insert_session(db, user, b"\x02" * 32)
    assert await count_sessions(db, user.id) == 1


@pytest.mark.committed
async def test_t06_note_migration_0003_upgrade_downgrade_upgrade_check(
    committed: async_sessionmaker[AsyncSession], test_database_url: str
) -> None:
    import asyncio

    async def alembic(*args: str) -> None:
        result = await asyncio.to_thread(run_alembic, test_database_url, *args)
        assert result.returncode == 0, (
            f"alembic {' '.join(args)} rc={result.returncode}\n{result.stdout}\n{result.stderr}"
        )

    async def length_check_exists() -> bool:
        async with committed() as s:
            rows = await s.execute(
                text(
                    "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
                    "WHERE c.conrelid = 'user_session'::regclass AND c.contype = 'c'"
                )
            )
            return any("octet_length" in str(r[0]) for r in rows)

    async with committed() as s:
        user = await make_user(s, role="user")
        await s.commit()

    assert await length_check_exists(), "после upgrade head нет CHECK octet_length(id)"
    await alembic("downgrade", "0002")
    assert not await length_check_exists(), "downgrade 0003 оставил CHECK"
    async with committed() as s:  # без CHECK короткий id вставляется
        await _try_insert_session(s, user, b"\x03" * 31)
        await s.commit()
    async with committed() as s:
        await s.execute(text("DELETE FROM user_session"))
        await s.commit()
    await alembic("upgrade", "head")
    assert await length_check_exists()
    await alembic("check")


# --- SessionStore: ключ (ревью T11) -----------------------------------------------------


@pytest.mark.parametrize("key", [b"", b"x", b"short-secret-key-value", b"k" * 31])
def test_session_store_rejects_empty_or_short_key_without_leaking_it(
    key: bytes, mods: SimpleNamespace
) -> None:
    with pytest.raises(ValueError) as info:
        mods.sessions.SessionStore(key, idle_timeout=IDLE, absolute_timeout=ABSOLUTE)
    shown = f"{info.value!s} {info.value!r} {info.value.args!r}"
    if key:
        assert key.decode() not in shown
        assert repr(key) not in shown


def test_session_store_accepts_32_byte_key_and_generated_key(
    mods: SimpleNamespace, settings: Settings
) -> None:
    from app.core.secrets import ensure_secret_key

    mods.sessions.SessionStore(b"k" * 32, idle_timeout=IDLE, absolute_timeout=ABSOLUTE)
    generated = ensure_secret_key(settings)
    mods.sessions.SessionStore(generated, idle_timeout=IDLE, absolute_timeout=ABSOLUTE)


# --- гонка блокировки (FR-61, AC-37, ревью T11) -----------------------------------------


class _VerifyProbe:
    """Шпион на ``hasher.verify``: считает вызовы; верный пароль ждёт ``gate`` (поток)."""

    def __init__(self, real: Any, good: str) -> None:
        self.real = real
        self.good = good
        self.calls = 0
        self.good_started = threading.Event()
        self.gate = threading.Event()
        self._lock = threading.Lock()

    def __call__(self, password_hash: str, password: str) -> bool:
        with self._lock:
            self.calls += 1
        if password == self.good:
            self.good_started.set()
            self.gate.wait(timeout=20)
        return bool(self.real(password_hash, password))


async def _attempt(
    maker: async_sessionmaker[AsyncSession],
    auth: SimpleNamespace,
    mods: SimpleNamespace,
    login: str,
    password: str,
    now: datetime = NOW,
) -> Any:
    """Один «запрос»: своя сессия; исключение -> ROLLBACK, как в get_db."""
    async with maker() as s:
        try:
            result = await mods.service.login(
                s, auth.provider, auth.sessions, login=login, password=SecretStr(password), now=now
            )
            await s.commit()
            return result
        except mods.errors.InvalidCredentials as exc:
            await s.rollback()
            return exc


async def _race_setup(
    committed: async_sessionmaker[AsyncSession],
    mods: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[SimpleNamespace, UserRow, _VerifyProbe]:
    hasher = mods.Hasher(**CHEAP)
    probe = _VerifyProbe(hasher.verify, PASSWORD)
    monkeypatch.setattr(hasher, "verify", probe)
    provider = mods.provider.LocalPasswordProvider(hasher, max_failures=5, lock_duration=LOCK)
    store = mods.sessions.SessionStore(SECRET_KEY, idle_timeout=IDLE, absolute_timeout=ABSOLUTE)
    auth = SimpleNamespace(hasher=hasher, provider=provider, sessions=store)
    async with committed() as s:
        user = await make_user(s, password=PASSWORD, role="user")
        await s.commit()
    return auth, user, probe


async def _assert_locked_and_recovers(
    committed: async_sessionmaker[AsyncSession],
    auth: SimpleNamespace,
    mods: SimpleNamespace,
    user: UserRow,
) -> None:
    async with committed() as s:
        state = await user_state(s, user.id)
        assert state.login_locked_until == NOW + LOCK
        assert state.failed_login_count == 0
        assert await count_sessions(s, user.id) == 0
    # (c) по окончании окна верный пароль проходит, счётчик сброшен
    result = await _attempt(committed, auth, mods, user.login, PASSWORD, NOW + LOCK)
    assert not isinstance(result, Exception), result
    assert result.user_id == user.id
    async with committed() as s:
        state = await user_state(s, user.id)
        assert state.failed_login_count == 0
        assert state.login_locked_until is None


@pytest.mark.committed
async def test_ac37_race_correct_password_in_flight_while_lock_is_committed(
    committed: async_sessionmaker[AsyncSession],
    mods: SimpleNamespace,
    fixed_clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Верный пароль начал проверку до блокировки и закончил после неё -> отказ, сессии нет."""
    auth, user, probe = await _race_setup(committed, mods, monkeypatch)
    good = asyncio.create_task(_attempt(committed, auth, mods, user.login, PASSWORD))
    assert await asyncio.to_thread(probe.good_started.wait, 10), "верный пароль не дошёл до verify"

    async def five_wrong() -> None:
        for _ in range(5):
            res = await _attempt(committed, auth, mods, user.login, WRONG)
            assert isinstance(res, mods.errors.InvalidCredentials)

    wrongs = asyncio.create_task(five_wrong())
    try:
        await asyncio.wait({wrongs}, timeout=5)  # реализация с блокировкой строки может ждать
    finally:
        probe.gate.set()
    await wrongs
    result = await good
    assert isinstance(result, mods.errors.InvalidCredentials), (
        "верный пароль прошёл после зафиксированной блокировки"
    )
    await _assert_locked_and_recovers(committed, auth, mods, user)


@pytest.mark.committed
async def test_ac37_race_burst_of_30_wrong_plus_correct_makes_at_most_5_verifications(
    committed: async_sessionmaker[AsyncSession],
    mods: SimpleNamespace,
    fixed_clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """30 неверных + 1 верный параллельно: не больше порога вызовов verify; верный отклонён."""
    auth, user, probe = await _race_setup(committed, mods, monkeypatch)
    wrongs = [
        asyncio.create_task(_attempt(committed, auth, mods, user.login, WRONG)) for _ in range(30)
    ]
    good = asyncio.create_task(_attempt(committed, auth, mods, user.login, PASSWORD))
    try:
        await asyncio.wait(wrongs, timeout=20)
    finally:
        probe.gate.set()  # верный пароль завершает проверку только после пачки неверных
    outcomes = await asyncio.gather(*wrongs)
    good_result = await good
    assert all(isinstance(o, mods.errors.InvalidCredentials) for o in outcomes)
    assert isinstance(good_result, mods.errors.InvalidCredentials), (
        "верный пароль получил сессию, хотя пачка закончилась блокировкой"
    )
    assert probe.calls <= 5, f"verify вызван {probe.calls} раз при пороге 5"
    await _assert_locked_and_recovers(committed, auth, mods, user)
