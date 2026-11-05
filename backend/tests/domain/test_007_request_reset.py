"""R7-T08: домен ``request_reset`` и политика сброса (spec 007: FR-3..FR-9, AC-2, AC-4..AC-6).

Публичный интерфейс: ``app.domain.auth.password_reset`` (``TOKEN_TTL``, ``ResetPolicy``,
``request_reset``), ``app.core.mail.deliver``, ``app.main.create_app``
(``state.password_reset_policy``).
Время — ``fixed_clock``; почта — ``RecordingMailer``.
"""

from __future__ import annotations

import hashlib
import importlib
import re
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from app.core.errors import FeatureDisabled
from tests.factories import make_user, make_workspace
from tests.mail_support import RecordingMailer

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.clock import FixedClock
    from app.core.config import Settings

BASE = "https://tracker.example.test"
KEY = b"k" * 32
IP = "10.0.0.1"
LINK_RE = re.compile(re.escape(BASE) + r"/password-reset/confirm#token=([A-Za-z0-9_-]+)")


@pytest.fixture
def pr() -> Any:
    return importlib.import_module("app.domain.auth.password_reset")


@pytest.fixture
def policy(pr: Any) -> Any:
    return pr.ResetPolicy(base_url=BASE, limit_key=KEY)


async def ask(
    pr: Any,
    db: AsyncSession,
    policy: Any,
    clock: FixedClock,
    email: str = "ivan@x.ru",
    ip: str | None = IP,
) -> Any:
    return await pr.request_reset(db, policy, email=email, client_ip=ip, now=clock.now())


async def tokens(db: AsyncSession) -> list[Any]:
    res = await db.execute(
        text("SELECT user_id, token_hash, expires_at, used_at FROM password_reset_token")
    )
    return list(res.all())


async def req_events(db: AsyncSession) -> list[Any]:
    res = await db.execute(
        text(
            "SELECT workspace_id, actor_id, entity_type, entity_id, action, details, changes, "
            "changed_fields FROM domain_event WHERE action = 'user.password_reset_requested'"
        )
    )
    return list(res.all())


async def attempt_scopes(db: AsyncSession) -> list[str]:
    res = await db.execute(text("SELECT scope FROM password_reset_attempt ORDER BY scope"))
    return [r[0] for r in res.all()]


def token_of(message: Any) -> str:
    match = LINK_RE.search(message.body)
    assert match is not None, "reset link not found in mail body"
    return match.group(1)


async def active_user(db: AsyncSession, email: str = "ivan@x.ru", **kw: Any) -> Any:
    return await make_user(db, email=email, role="user", **kw)


# --- успех: письмо, токен, событие (AC-5, FR-4, FR-7, FR-15) -----------------------------


async def test_007_ac5_active_user_gets_mail_with_link(
    pr: Any, policy: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    user = await active_user(db)
    msg = await ask(pr, db, policy, fixed_clock)
    assert msg is not None
    assert msg.to == "ivan@x.ru"
    assert msg.subject == "Сброс пароля"
    token = token_of(msg)
    assert len(token) == 43  # 32 байта в base64url без заполнения
    assert "30 минут" in msg.body
    assert user.login not in msg.body
    assert token not in repr(msg)


async def test_007_ac5_db_stores_sha256_hash_and_expiry(
    pr: Any, policy: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    user = await active_user(db)
    msg = await ask(pr, db, policy, fixed_clock)
    token = token_of(msg)
    rows = await tokens(db)
    assert len(rows) == 1
    user_id, stored, expires_at, used_at = rows[0]
    assert user_id == user.id
    assert bytes(stored) == hashlib.sha256(token.encode()).digest()
    assert expires_at == fixed_clock.now() + timedelta(minutes=30)
    assert timedelta(minutes=30) == pr.TOKEN_TTL
    assert used_at is None


async def test_007_ac5_email_is_normalized_for_lookup(
    pr: Any, policy: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    await active_user(db)
    msg = await ask(pr, db, policy, fixed_clock, email="  Ivan@X.RU ")
    assert msg is not None
    assert msg.to == "ivan@x.ru"


async def test_007_fr15_requested_event_actor_null_and_no_secrets(
    pr: Any, policy: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    user = await active_user(db)
    msg = await ask(pr, db, policy, fixed_clock)
    evs = await req_events(db)
    assert len(evs) == 1
    ev = evs[0]
    assert ev.actor_id is None
    assert ev.entity_type == "user"
    assert ev.entity_id == user.id
    assert ev.workspace_id == user.workspace_id
    dump = " ".join(str(v) for v in ev)
    assert token_of(msg) not in dump
    assert "ivan@x.ru" not in dump


async def test_007_pr2_user_in_second_workspace_uses_first_membership(
    pr: Any, policy: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    user = await active_user(db)
    second = await make_workspace(db)
    await db.execute(
        text(
            "INSERT INTO workspace_member (workspace_id, user_id, role, created_at, updated_at) "
            "VALUES (:w, :u, 'user', :t, :t)"
        ),
        {"w": second.id, "u": user.id, "t": fixed_clock.now() + timedelta(days=1)},
    )
    assert await ask(pr, db, policy, fixed_clock) is not None
    evs = await req_events(db)
    assert [e.workspace_id for e in evs] == [user.workspace_id]


# --- отзыв прежних токенов (AC-6) -----------------------------------------------------------


async def test_007_ac6_new_request_deletes_previous_unused_token(
    pr: Any, policy: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    await active_user(db)
    first = token_of(await ask(pr, db, policy, fixed_clock))
    second = token_of(await ask(pr, db, policy, fixed_clock))
    assert first != second
    rows = await tokens(db)
    assert [bytes(r.token_hash) for r in rows] == [hashlib.sha256(second.encode()).digest()]


async def test_007_ac6_other_users_tokens_untouched(
    pr: Any, policy: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    await active_user(db)
    other = await active_user(db, email="petr@x.ru")
    await ask(pr, db, policy, fixed_clock, email="petr@x.ru")
    await ask(pr, db, policy, fixed_clock)
    owners = sorted(str(r.user_id) for r in await tokens(db))
    assert len(owners) == 2
    assert str(other.id) in owners


# --- единый «пустой» исход (FR-6, AC-4, AC-11) -------------------------------------------


async def assert_nothing_issued(db: AsyncSession) -> None:
    assert await tokens(db) == []
    assert await req_events(db) == []


async def test_007_ac4_unknown_email_returns_none(
    pr: Any, policy: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    await active_user(db)
    assert await ask(pr, db, policy, fixed_clock, email="nobody@x.ru") is None
    await assert_nothing_issued(db)


async def test_007_ac11_blocked_user_gets_nothing(
    pr: Any, policy: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    await active_user(db, blocked=True)
    assert await ask(pr, db, policy, fixed_clock) is None
    await assert_nothing_issued(db)


async def test_007_ac11_user_without_membership_gets_nothing(
    pr: Any, policy: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    user = await active_user(db)
    await db.execute(text("DELETE FROM workspace_member WHERE user_id = :u"), {"u": user.id})
    assert await ask(pr, db, policy, fixed_clock) is None
    await assert_nothing_issued(db)


async def test_007_fr7_user_without_email_is_unreachable(
    pr: Any, policy: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    await make_user(db, role="user")  # email NULL
    assert await ask(pr, db, policy, fixed_clock, email="") is None
    await assert_nothing_issued(db)


@pytest.mark.parametrize("bad", ["not-an-email", "a@", "@x.ru", "a b@x.ru", "a@b@c", "x" * 300])
async def test_007_ac4_invalid_email_returns_none(
    pr: Any, policy: Any, db: AsyncSession, fixed_clock: FixedClock, bad: str
) -> None:
    await active_user(db)
    assert await ask(pr, db, policy, fixed_clock, email=bad) is None
    await assert_nothing_issued(db)


async def test_007_fr9_invalid_email_counts_only_ip_limit(
    pr: Any, policy: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    assert await ask(pr, db, policy, fixed_clock, email="garbage") is None
    assert await attempt_scopes(db) == ["ip"]


async def test_007_fr9_invalid_email_exhausts_ip_limit_not_email_limit(
    pr: Any, policy: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    await active_user(db)
    for _ in range(10):  # больше 3 раз одного и того же мусора: лимит email не срабатывает
        assert await ask(pr, db, policy, fixed_clock, email="garbage") is None
    assert await attempt_scopes(db) == ["ip"] * 10
    # IP исчерпан: даже валидный запрос с этого IP не получает письма
    assert await ask(pr, db, policy, fixed_clock) is None
    await assert_nothing_issued(db)
    # другой IP тем же адресом проходит
    assert await ask(pr, db, policy, fixed_clock, ip="10.0.0.2") is not None


# --- лимиты (FR-9, AC-10) ----------------------------------------------------------------


async def test_007_ac10_email_limit_blocks_fourth_request(
    pr: Any, policy: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    await active_user(db)
    last = None
    for _ in range(3):
        last = token_of(await ask(pr, db, policy, fixed_clock))
    assert await ask(pr, db, policy, fixed_clock) is None
    rows = await tokens(db)
    assert [bytes(r.token_hash) for r in rows] == [hashlib.sha256(last.encode()).digest()]
    assert len(await req_events(db)) == 3
    fixed_clock.advance(timedelta(minutes=61))
    assert await ask(pr, db, policy, fixed_clock) is not None


async def test_007_ac10_ip_limit_applies_across_emails(
    pr: Any, policy: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    await active_user(db)
    for i in range(10):
        await ask(pr, db, policy, fixed_clock, email=f"u{i}@x.ru")
    assert await ask(pr, db, policy, fixed_clock) is None
    await assert_nothing_issued(db)


async def test_007_fr9_unknown_email_still_consumes_limit(
    pr: Any, policy: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    for _ in range(3):
        assert await ask(pr, db, policy, fixed_clock, email="nobody@x.ru") is None
    await active_user(db, email="nobody@x.ru")
    assert await ask(pr, db, policy, fixed_clock, email="nobody@x.ru") is None  # лимит общий


async def test_007_fr9_client_ip_none_skips_ip_scope(
    pr: Any, policy: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    await active_user(db)
    assert await ask(pr, db, policy, fixed_clock, ip=None) is not None
    assert await attempt_scopes(db) == ["email"]


# --- функция отключена (FR-3, AC-2) ------------------------------------------------------


async def test_007_ac2_policy_none_raises_feature_disabled(
    pr: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    await active_user(db)
    with pytest.raises(FeatureDisabled):
        await ask(pr, db, None, fixed_clock)
    await assert_nothing_issued(db)
    assert await attempt_scopes(db) == []


# --- ResetPolicy, ссылка, отправка -------------------------------------------------------


def test_007_policy_repr_hides_limit_key(pr: Any) -> None:
    p = pr.ResetPolicy(base_url=BASE, limit_key=b"SECRETKEYSECRETKEYSECRETKEY123456")
    assert "SECRETKEY" not in repr(p)
    assert str(b"SECRETKEY") not in repr(p)
    assert BASE in repr(p)


def test_007_reset_link_format(pr: Any) -> None:
    assert pr.reset_link(BASE, "abc") == f"{BASE}/password-reset/confirm#token=abc"


def test_007_new_token_and_token_hash(pr: Any) -> None:
    token, digest = pr.new_token()
    assert len(token) == 43
    assert digest == hashlib.sha256(token.encode()).digest()
    assert pr.token_hash(token) == digest
    assert pr.token_hash("токен") is None
    assert pr.new_token()[0] != token


async def test_007_ac5_delivery_through_recording_mailer(
    pr: Any, policy: Any, db: AsyncSession, fixed_clock: FixedClock
) -> None:
    from app.core.mail import deliver

    await active_user(db)
    mailer = RecordingMailer()
    msg = await ask(pr, db, policy, fixed_clock)
    await deliver(mailer, msg)
    assert mailer.sent == [msg]


# --- lifespan (plan §4.5) ----------------------------------------------------------------


async def test_007_fr3_lifespan_without_smtp_has_no_policy(
    settings: Settings, fixed_clock: FixedClock
) -> None:
    from app.main import create_app

    application = create_app(settings, clock=fixed_clock)
    async with application.router.lifespan_context(application):
        assert application.state.password_reset_policy is None
        assert application.state.mailer is None


async def test_007_fr3_lifespan_with_smtp_builds_policy_and_mailer(
    settings: Settings, fixed_clock: FixedClock
) -> None:
    from app.core.mail import SmtpMailer
    from app.domain.auth.password_reset import ResetPolicy
    from app.main import create_app

    enabled = settings.model_copy(
        update={
            "smtp_host": "smtp.invalid",
            "smtp_from": "tracker@example.test",
            "public_base_url": BASE,
        }
    )
    application = create_app(enabled, clock=fixed_clock)
    async with application.router.lifespan_context(application):
        policy = application.state.password_reset_policy
        assert isinstance(policy, ResetPolicy)
        assert policy.base_url == BASE
        assert isinstance(policy.limit_key, bytes)
        assert len(policy.limit_key) >= 32
        assert policy.limit_key.hex() not in repr(policy)
        assert policy.limit_key not in repr(policy).encode()
        assert isinstance(application.state.mailer, SmtpMailer)
