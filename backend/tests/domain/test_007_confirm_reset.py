"""R7-T09: домен ``confirm_reset`` (spec 007: FR-8, FR-11..FR-15, NFR-1, AC-7..AC-9, AC-11/12).

Публичный интерфейс: ``app.domain.auth.password_reset`` (``ResetPolicy``, ``request_reset``,
``confirm_reset``, ``TOKEN_TTL``, ``token_hash``). Порядок проверок — PR-20, эффекты — PR-16.
Время — ``fixed_clock``; Argon2 — дешёвые параметры; токен выдаётся настоящим ``request_reset``.
"""

from __future__ import annotations

import importlib
import re
import uuid
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from app.core.errors import FeatureDisabled, ResetTokenInvalid, Unprocessable
from tests.factories import make_user

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.clock import FixedClock
    from app.core.config import Settings

BASE = "https://tracker.example.test"
KEY = b"k" * 32
SECRET_KEY = b"unit-test-secret-key-0123456789ab"
CHEAP: dict[str, int] = {"time_cost": 1, "memory_cost_kib": 1024, "parallelism": 1}
NEW_PASSWORD = "brand-new-password-9157"
OLD_PASSWORD = "old-password-correct-1"
LINK_RE = re.compile(re.escape(BASE) + r"/password-reset/confirm#token=([A-Za-z0-9_-]+)")
INITIAL_FILE = "initial-admin-password.txt"
EMAIL = "ivan@x.ru"


@pytest.fixture
def pr() -> Any:
    return importlib.import_module("app.domain.auth.password_reset")


@pytest.fixture
def policy(pr: Any) -> Any:
    return pr.ResetPolicy(base_url=BASE, limit_key=KEY)


@pytest.fixture
def hasher() -> Any:
    from app.core.security.passwords import PasswordHasher

    return PasswordHasher(**CHEAP)


@pytest.fixture
def store(settings: Settings) -> Any:
    from app.domain.auth.sessions import SessionStore

    return SessionStore(
        SECRET_KEY,
        idle_timeout=settings.session_idle_timeout,
        absolute_timeout=settings.session_absolute_timeout,
    )


async def issue(
    pr: Any, db: AsyncSession, policy: Any, clock: FixedClock, email: str = EMAIL
) -> str:
    msg = await pr.request_reset(db, policy, email=email, client_ip="10.0.0.1", now=clock.now())
    assert msg is not None
    match = LINK_RE.search(msg.body)
    assert match is not None
    return match.group(1)


async def confirm(
    pr: Any,
    db: AsyncSession,
    policy: Any,
    hasher: Any,
    store: Any,
    settings: Settings,
    clock: FixedClock,
    token: str,
    password: str = NEW_PASSWORD,
) -> None:
    await pr.confirm_reset(
        db,
        policy,
        hasher,
        store,
        settings,
        token=SecretStr(token),
        new_password=SecretStr(password),
        now=clock.now(),
    )


async def user_row(db: AsyncSession, user_id: uuid.UUID) -> Any:
    res = await db.execute(
        text(
            "SELECT password_hash, must_change_password, failed_login_count, login_locked_until, "
            "password_changed_at FROM app_user WHERE id = :id"
        ),
        {"id": user_id},
    )
    return res.one()


async def token_rows(db: AsyncSession, user_id: uuid.UUID) -> list[Any]:
    res = await db.execute(
        text("SELECT used_at FROM password_reset_token WHERE user_id = :id"), {"id": user_id}
    )
    return list(res.all())


async def open_sessions(db: AsyncSession, store: Any, user: Any, count: int = 2) -> None:
    from app.core.clock import utcnow

    for _ in range(count):
        await store.create(db, user_id=user.id, workspace_id=user.workspace_id, now=utcnow())


async def session_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    res = await db.execute(
        text("SELECT count(*) FROM user_session WHERE user_id = :id"), {"id": user_id}
    )
    return int(res.scalar_one())


async def completed_events(db: AsyncSession) -> list[Any]:
    res = await db.execute(
        text(
            "SELECT workspace_id, actor_id, entity_type, entity_id, details, changes, "
            "changed_fields FROM domain_event WHERE action = 'user.password_reset_completed'"
        )
    )
    return list(res.all())


async def make_active(db: AsyncSession, **kw: Any) -> Any:
    return await make_user(db, email=EMAIL, role="user", password=OLD_PASSWORD, **kw)


# --- успех (AC-8, FR-11..FR-15, PR-16) -------------------------------------------------


async def test_007_ac8_success_changes_hash_and_consumes_token(
    pr: Any,
    policy: Any,
    hasher: Any,
    store: Any,
    settings: Settings,
    db: AsyncSession,
    fixed_clock: FixedClock,
) -> None:
    user = await make_active(db)
    token = await issue(pr, db, policy, fixed_clock)
    fixed_clock.advance(timedelta(minutes=5))
    await confirm(pr, db, policy, hasher, store, settings, fixed_clock, token)
    row = await user_row(db, user.id)
    assert row.password_hash != user.password_hash
    assert hasher.verify(row.password_hash, NEW_PASSWORD)
    assert not hasher.verify(row.password_hash, OLD_PASSWORD)
    assert row.password_changed_at == fixed_clock.now()
    rows = await token_rows(db, user.id)
    assert len(rows) == 1
    assert rows[0].used_at == fixed_clock.now()


async def test_007_ac8_success_deletes_all_user_sessions_only(
    pr: Any,
    policy: Any,
    hasher: Any,
    store: Any,
    settings: Settings,
    db: AsyncSession,
    fixed_clock: FixedClock,
) -> None:
    user = await make_active(db)
    other = await make_user(db, role="user")
    await open_sessions(db, store, user, 2)
    await open_sessions(db, store, other, 1)
    token = await issue(pr, db, policy, fixed_clock)
    await confirm(pr, db, policy, hasher, store, settings, fixed_clock, token)
    assert await session_count(db, user.id) == 0
    assert await session_count(db, other.id) == 1


@pytest.mark.parametrize("was_true", [True, False])
async def test_007_ac8_must_change_password_becomes_false(
    pr: Any,
    policy: Any,
    hasher: Any,
    store: Any,
    settings: Settings,
    db: AsyncSession,
    fixed_clock: FixedClock,
    was_true: bool,
) -> None:
    user = await make_active(db, must_change_password=was_true)
    token = await issue(pr, db, policy, fixed_clock)
    await confirm(pr, db, policy, hasher, store, settings, fixed_clock, token)
    assert (await user_row(db, user.id)).must_change_password is False


async def test_007_pr16_resets_failed_logins_and_lock(
    pr: Any,
    policy: Any,
    hasher: Any,
    store: Any,
    settings: Settings,
    db: AsyncSession,
    fixed_clock: FixedClock,
) -> None:
    user = await make_active(db)
    await db.execute(
        text(
            "UPDATE app_user SET failed_login_count = 5, login_locked_until = :until WHERE id = :id"
        ),
        {"until": fixed_clock.now() + timedelta(minutes=10), "id": user.id},
    )
    token = await issue(pr, db, policy, fixed_clock)
    await confirm(pr, db, policy, hasher, store, settings, fixed_clock, token)
    row = await user_row(db, user.id)
    assert row.failed_login_count == 0
    assert row.login_locked_until is None


async def test_007_pr16_other_unused_tokens_of_user_are_deleted(
    pr: Any,
    policy: Any,
    hasher: Any,
    store: Any,
    settings: Settings,
    db: AsyncSession,
    fixed_clock: FixedClock,
) -> None:
    user = await make_active(db)
    token = await issue(pr, db, policy, fixed_clock)
    # второй неиспользованный токен (в обход request_reset, который удаляет прежние)
    await db.execute(
        text(
            "INSERT INTO password_reset_token (id, user_id, token_hash, created_at, expires_at) "
            "VALUES (:i, :u, :h, :c, :e)"
        ),
        {
            "i": uuid.uuid4(),
            "u": user.id,
            "h": b"\x01" * 32,
            "c": fixed_clock.now(),
            "e": fixed_clock.now() + timedelta(minutes=30),
        },
    )
    await confirm(pr, db, policy, hasher, store, settings, fixed_clock, token)
    rows = await token_rows(db, user.id)
    assert len(rows) == 1
    assert rows[0].used_at is not None


async def test_007_pr16_tokens_of_other_users_untouched(
    pr: Any,
    policy: Any,
    hasher: Any,
    store: Any,
    settings: Settings,
    db: AsyncSession,
    fixed_clock: FixedClock,
) -> None:
    await make_active(db)
    other = await make_user(db, email="petr@x.ru", role="user")
    await issue(pr, db, policy, fixed_clock, "petr@x.ru")
    token = await issue(pr, db, policy, fixed_clock)
    await confirm(pr, db, policy, hasher, store, settings, fixed_clock, token)
    rows = await token_rows(db, other.id)
    assert len(rows) == 1
    assert rows[0].used_at is None


async def test_007_ac12_one_completed_event_without_values(
    pr: Any,
    policy: Any,
    hasher: Any,
    store: Any,
    settings: Settings,
    db: AsyncSession,
    fixed_clock: FixedClock,
) -> None:
    user = await make_active(db)
    token = await issue(pr, db, policy, fixed_clock)
    await confirm(pr, db, policy, hasher, store, settings, fixed_clock, token)
    events = await completed_events(db)
    assert len(events) == 1
    ev = events[0]
    assert ev.actor_id == user.id
    assert ev.entity_id == user.id
    assert ev.entity_type == "user"
    assert ev.workspace_id == user.workspace_id
    assert list(ev.changed_fields) == []
    assert ev.details is None
    assert ev.changes is None


# --- файл пароля первого ТА (Q-11, PR-16) ----------------------------------------------


def write_initial_file(settings: Settings, login: str) -> Any:
    settings.secrets_dir.mkdir(parents=True, exist_ok=True)
    path = settings.secrets_dir / INITIAL_FILE
    path.write_text(f"login={login}\npassword=irrelevant-pass-1\n", encoding="utf-8")
    return path


async def test_007_q11_initial_admin_file_removed_after_commit_only(
    pr: Any,
    policy: Any,
    hasher: Any,
    store: Any,
    settings: Settings,
    db: AsyncSession,
    fixed_clock: FixedClock,
) -> None:
    user = await make_active(db, login="admin", must_change_password=True)
    path = write_initial_file(settings, user.login)
    token = await issue(pr, db, policy, fixed_clock)
    await confirm(pr, db, policy, hasher, store, settings, fixed_clock, token)
    assert path.exists()  # до COMMIT файл на месте
    await db.commit()
    assert not path.exists()


async def test_007_q11_initial_admin_file_of_other_login_kept(
    pr: Any,
    policy: Any,
    hasher: Any,
    store: Any,
    settings: Settings,
    db: AsyncSession,
    fixed_clock: FixedClock,
) -> None:
    await make_active(db, login="second.admin")
    path = write_initial_file(settings, "admin")
    token = await issue(pr, db, policy, fixed_clock)
    await confirm(pr, db, policy, hasher, store, settings, fixed_clock, token)
    await db.commit()
    assert path.exists()


async def test_007_q11_rejected_confirm_keeps_initial_admin_file(
    pr: Any,
    policy: Any,
    hasher: Any,
    store: Any,
    settings: Settings,
    db: AsyncSession,
    fixed_clock: FixedClock,
) -> None:
    user = await make_active(db, login="admin")
    path = write_initial_file(settings, user.login)
    token = await issue(pr, db, policy, fixed_clock)
    with pytest.raises(Unprocessable):
        await confirm(pr, db, policy, hasher, store, settings, fixed_clock, token, "short")
    await db.rollback()
    assert path.exists()


# --- одноразовость и срок (AC-7, FR-8, FR-11) ------------------------------------------


async def test_007_fr11_second_use_of_token_is_invalid(
    pr: Any,
    policy: Any,
    hasher: Any,
    store: Any,
    settings: Settings,
    db: AsyncSession,
    fixed_clock: FixedClock,
) -> None:
    user = await make_active(db)
    token = await issue(pr, db, policy, fixed_clock)
    await confirm(pr, db, policy, hasher, store, settings, fixed_clock, token)
    after_first = (await user_row(db, user.id)).password_hash
    with pytest.raises(ResetTokenInvalid):
        await confirm(
            pr, db, policy, hasher, store, settings, fixed_clock, token, "another-password-4455"
        )
    assert (await user_row(db, user.id)).password_hash == after_first
    assert len(await completed_events(db)) == 1


async def test_007_ac7_expired_after_30_minutes_keeps_old_password(
    pr: Any,
    policy: Any,
    hasher: Any,
    store: Any,
    settings: Settings,
    db: AsyncSession,
    fixed_clock: FixedClock,
) -> None:
    user = await make_active(db)
    token = await issue(pr, db, policy, fixed_clock)
    fixed_clock.advance(pr.TOKEN_TTL + timedelta(seconds=1))
    with pytest.raises(ResetTokenInvalid):
        await confirm(pr, db, policy, hasher, store, settings, fixed_clock, token)
    row = await user_row(db, user.id)
    assert row.password_hash == user.password_hash
    assert (await token_rows(db, user.id))[0].used_at is None
    assert await completed_events(db) == []


async def test_007_ac7_exactly_30_minutes_is_already_invalid(
    pr: Any,
    policy: Any,
    hasher: Any,
    store: Any,
    settings: Settings,
    db: AsyncSession,
    fixed_clock: FixedClock,
) -> None:
    user = await make_active(db)
    token = await issue(pr, db, policy, fixed_clock)
    fixed_clock.advance(pr.TOKEN_TTL)
    with pytest.raises(ResetTokenInvalid):
        await confirm(pr, db, policy, hasher, store, settings, fixed_clock, token)
    assert (await user_row(db, user.id)).password_hash == user.password_hash


async def test_007_ac7_just_before_30_minutes_is_valid(
    pr: Any,
    policy: Any,
    hasher: Any,
    store: Any,
    settings: Settings,
    db: AsyncSession,
    fixed_clock: FixedClock,
) -> None:
    user = await make_active(db)
    token = await issue(pr, db, policy, fixed_clock)
    fixed_clock.advance(pr.TOKEN_TTL - timedelta(seconds=1))
    await confirm(pr, db, policy, hasher, store, settings, fixed_clock, token)
    assert hasher.verify((await user_row(db, user.id)).password_hash, NEW_PASSWORD)


@pytest.mark.parametrize(
    "bad", ["AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "токен-не-ascii", "", "é" * 43]
)
async def test_007_fr11_unknown_or_non_ascii_token_is_invalid(
    pr: Any,
    policy: Any,
    hasher: Any,
    store: Any,
    settings: Settings,
    db: AsyncSession,
    fixed_clock: FixedClock,
    bad: str,
) -> None:
    user = await make_active(db)
    await issue(pr, db, policy, fixed_clock)
    with pytest.raises(ResetTokenInvalid):
        await confirm(pr, db, policy, hasher, store, settings, fixed_clock, bad)
    assert (await user_row(db, user.id)).password_hash == user.password_hash


# --- политика пароля (AC-9, FR-14, PR-15, PR-20) ---------------------------------------


async def test_007_ac9_short_password_422_and_token_not_consumed(
    pr: Any,
    policy: Any,
    hasher: Any,
    store: Any,
    settings: Settings,
    db: AsyncSession,
    fixed_clock: FixedClock,
) -> None:
    user = await make_active(db)
    token = await issue(pr, db, policy, fixed_clock)
    with pytest.raises(Unprocessable) as info:
        await confirm(pr, db, policy, hasher, store, settings, fixed_clock, token, "x" * 11)
    assert info.value.code == "password_too_short"
    assert (await token_rows(db, user.id))[0].used_at is None
    assert (await user_row(db, user.id)).password_hash == user.password_hash
    # тот же токен с хорошим паролем принимается
    await confirm(pr, db, policy, hasher, store, settings, fixed_clock, token)
    assert hasher.verify((await user_row(db, user.id)).password_hash, NEW_PASSWORD)


async def test_007_ac9_common_password_422_and_token_not_consumed(
    pr: Any,
    policy: Any,
    hasher: Any,
    store: Any,
    settings: Settings,
    db: AsyncSession,
    fixed_clock: FixedClock,
) -> None:
    user = await make_active(db)
    await open_sessions(db, store, user, 1)
    token = await issue(pr, db, policy, fixed_clock)
    with pytest.raises(Unprocessable) as info:
        await confirm(pr, db, policy, hasher, store, settings, fixed_clock, token, "unbelievable")
    assert info.value.code == "password_too_common"
    assert (await token_rows(db, user.id))[0].used_at is None
    assert await session_count(db, user.id) == 1
    assert await completed_events(db) == []


async def test_007_ac9_surrogate_password_is_validation_error_without_leak(
    pr: Any,
    policy: Any,
    hasher: Any,
    store: Any,
    settings: Settings,
    db: AsyncSession,
    fixed_clock: FixedClock,
) -> None:
    user = await make_active(db)
    token = await issue(pr, db, policy, fixed_clock)
    bad = "abc\ud800" * 5
    with pytest.raises(Unprocessable) as info:
        await confirm(pr, db, policy, hasher, store, settings, fixed_clock, token, bad)
    assert info.value.code == "validation_error"
    assert bad not in str(info.value)
    assert (await token_rows(db, user.id))[0].used_at is None


async def test_007_pr20_invalid_token_wins_over_bad_password(
    pr: Any,
    policy: Any,
    hasher: Any,
    store: Any,
    settings: Settings,
    db: AsyncSession,
    fixed_clock: FixedClock,
) -> None:
    await make_active(db)
    with pytest.raises(ResetTokenInvalid):
        await confirm(pr, db, policy, hasher, store, settings, fixed_clock, "nope" * 10, "short")


# --- блокировка (AC-11, FR-12) ---------------------------------------------------------


async def test_007_ac11_user_blocked_after_issue_cannot_confirm(
    pr: Any,
    policy: Any,
    hasher: Any,
    store: Any,
    settings: Settings,
    db: AsyncSession,
    fixed_clock: FixedClock,
) -> None:
    user = await make_active(db)
    token = await issue(pr, db, policy, fixed_clock)
    await db.execute(
        text("UPDATE app_user SET is_blocked = true, blocked_at = :n WHERE id = :id"),
        {"n": fixed_clock.now(), "id": user.id},
    )
    with pytest.raises(ResetTokenInvalid):
        await confirm(pr, db, policy, hasher, store, settings, fixed_clock, token)
    row = await user_row(db, user.id)
    assert row.password_hash == user.password_hash
    assert (await token_rows(db, user.id))[0].used_at is None
    assert await completed_events(db) == []


async def test_007_ac11_user_without_membership_cannot_confirm(
    pr: Any,
    policy: Any,
    hasher: Any,
    store: Any,
    settings: Settings,
    db: AsyncSession,
    fixed_clock: FixedClock,
) -> None:
    user = await make_active(db)
    token = await issue(pr, db, policy, fixed_clock)
    await db.execute(text("DELETE FROM workspace_member WHERE user_id = :id"), {"id": user.id})
    with pytest.raises(ResetTokenInvalid):
        await confirm(pr, db, policy, hasher, store, settings, fixed_clock, token)
    assert (await user_row(db, user.id)).password_hash == user.password_hash


# --- политика выключена (FR-3) ---------------------------------------------------------


async def test_007_fr3_policy_none_is_feature_disabled(
    pr: Any,
    hasher: Any,
    store: Any,
    settings: Settings,
    db: AsyncSession,
    fixed_clock: FixedClock,
) -> None:
    with pytest.raises(FeatureDisabled):
        await confirm(pr, db, None, hasher, store, settings, fixed_clock, "anything")


# --- секреты (NFR-1, AC-12) ------------------------------------------------------------


async def test_007_nfr1_exceptions_do_not_contain_token_or_password(
    pr: Any,
    policy: Any,
    hasher: Any,
    store: Any,
    settings: Settings,
    db: AsyncSession,
    fixed_clock: FixedClock,
) -> None:
    await make_active(db)
    token = await issue(pr, db, policy, fixed_clock)
    secret_password = "Zq9-secret-pass-short"[:11]
    with pytest.raises(Unprocessable) as short:
        await confirm(pr, db, policy, hasher, store, settings, fixed_clock, token, secret_password)
    fixed_clock.advance(pr.TOKEN_TTL)
    with pytest.raises(ResetTokenInvalid) as expired:
        await confirm(pr, db, policy, hasher, store, settings, fixed_clock, token, NEW_PASSWORD)
    for exc in (short.value, expired.value):
        blob = f"{exc!s} {exc!r} {exc.args!r}"
        assert token not in blob
        assert secret_password not in blob
        assert NEW_PASSWORD not in blob
