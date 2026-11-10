"""R8-T09: домен заявки на регистрацию (spec 019: FR-3, FR-3a, FR-4..FR-7, FR-10, FR-11;
AC-4..AC-11, AC-15, AC-18, AC-19, AC-27, AC-29; plan §4.2, §4.3, RG-1, RG-5..RG-7, RG-9, RG-19).

Публичный интерфейс: ``app.domain.auth.registration`` (``RegistrationPolicy``, ``RegistrationForm``,
``TOKEN_TTL``, ``ACCEPTED_DETAIL``, ``confirm_link``, ``request_registration``) и
``app.main.create_app`` (``state.registration_policy``). Время — ``fixed_clock``; Argon2 — дешёвые
параметры; почта не отправляется: функция возвращает письмо, доставку делает вызывающий слой.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from app.core.errors import FeatureDisabled, RateLimited, Unprocessable
from app.core.security.passwords import PasswordHasher
from app.domain.auth import password_reset
from app.domain.auth import registration as reg
from app.domain.auth.models import RegistrationRequest
from tests.factories import make_user, make_workspace

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.core.clock import FixedClock
    from app.core.config import Settings
    from app.core.mail import MailMessage

BASE = "https://tracker.example.test"
KEY = b"k" * 32
IP = "203.0.113.10"
OTHER_IP = "203.0.113.11"
PASSWORD = "Zq7-registration-pw"  # 19 символов, не в списке частых
LINK_RE = re.compile(re.escape(BASE) + r"/register/confirm#token=([A-Za-z0-9_-]+)")
VALID: dict[str, str] = {
    "email": "anna@example.ru",
    "first_name": "Анна",
    "last_name": "Петрова-Иванова",
    "password": PASSWORD,
}  # v0.5: логина в форме нет, сервер генерирует petrova-ivanova.anna


@pytest.fixture
def hasher() -> PasswordHasher:
    return PasswordHasher(time_cost=1, memory_cost_kib=1024, parallelism=1)


@pytest.fixture
def policy() -> reg.RegistrationPolicy:
    return reg.RegistrationPolicy(base_url=BASE, limit_key=KEY)


def make_form(**overrides: str) -> reg.RegistrationForm:
    data = {**VALID, **overrides}
    return reg.RegistrationForm(
        email=data["email"],
        first_name=data["first_name"],
        last_name=data["last_name"],
        password=SecretStr(data["password"]),
    )


async def ask(
    db: AsyncSession,
    policy: reg.RegistrationPolicy | None,
    hasher: PasswordHasher,
    clock: FixedClock,
    *,
    ip: str | None = IP,
    **overrides: str,
) -> MailMessage | None:
    return await reg.request_registration(
        db, policy, hasher, form=make_form(**overrides), client_ip=ip, now=clock.now()
    )


def token_of(message: MailMessage | None) -> str:
    assert message is not None, "письмо не выдано"
    match = LINK_RE.search(message.body)
    assert match is not None, "ссылка подтверждения не найдена в письме"
    return match.group(1)


def sha256(token: str) -> bytes:
    return hashlib.sha256(token.encode("ascii")).digest()


def spy_hash(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Считает вызовы Argon2 через ``hash_in_thread`` модуля регистрации (результат не меняет)."""
    calls: list[int] = []
    real = reg.hash_in_thread

    async def spy(hasher: PasswordHasher, password: str) -> str:
        calls.append(1)
        return await real(hasher, password)

    monkeypatch.setattr(reg, "hash_in_thread", spy)
    return calls


async def request_rows(db: AsyncSession) -> list[Any]:
    res = await db.execute(
        text(
            "SELECT email, login, login_display, first_name, last_name, password_hash, "
            "token_hash, created_at, expires_at FROM registration_request ORDER BY email"
        )
    )
    return list(res.all())


async def count_requests(db: AsyncSession) -> int:
    return int(await db.scalar(text("SELECT count(*) FROM registration_request")) or 0)


async def count_attempts(db: AsyncSession) -> int:
    return int(await db.scalar(text("SELECT count(*) FROM registration_attempt")) or 0)


async def count_users(db: AsyncSession) -> int:
    return int(await db.scalar(text("SELECT count(*) FROM app_user")) or 0)


async def count_events(db: AsyncSession) -> int:
    return int(await db.scalar(text("SELECT count(*) FROM domain_event")) or 0)


# --- константы, ссылка, политика (plan §4.2, §4.3) -----------------------------------------


def test_019_token_ttl_and_accepted_text() -> None:
    assert timedelta(minutes=30) == reg.TOKEN_TTL
    assert reg.ACCEPTED_DETAIL == (
        "Если адрес можно использовать для регистрации, мы отправили на него письмо с "
        "подтверждением. Ссылка действует 30 минут."
    )


def test_019_confirm_link_puts_token_in_fragment() -> None:
    assert reg.confirm_link(BASE, "abc_-") == f"{BASE}/register/confirm#token=abc_-"


def test_019_policy_repr_hides_limit_key() -> None:
    policy = reg.RegistrationPolicy(base_url=BASE, limit_key=KEY)
    assert KEY.hex() not in repr(policy)
    assert KEY not in repr(policy).encode()


# --- RG-9 и политика: ровно одно пространство, иначе 404 feature_disabled ----------------


async def test_019_policy_none_is_feature_disabled(
    db: AsyncSession, hasher: PasswordHasher, fixed_clock: FixedClock
) -> None:
    await make_workspace(db)
    with pytest.raises(FeatureDisabled):
        await ask(db, None, hasher, fixed_clock)
    assert await count_requests(db) == 0
    assert await count_attempts(db) == 0


async def test_019_zero_workspaces_is_feature_disabled(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    with pytest.raises(FeatureDisabled):
        await ask(db, policy, hasher, fixed_clock)
    assert await count_requests(db) == 0
    assert await count_attempts(db) == 0


async def test_019_two_workspaces_is_feature_disabled(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    await make_workspace(db)
    await make_workspace(db)
    with pytest.raises(FeatureDisabled) as exc:
        await ask(db, policy, hasher, fixed_clock)
    assert exc.value.code == "feature_disabled"
    assert await count_requests(db) == 0
    assert await count_attempts(db) == 0


async def test_019_lifespan_without_smtp_has_no_registration_policy(
    settings: Settings, fixed_clock: FixedClock
) -> None:
    from app.main import create_app

    application = create_app(settings, clock=fixed_clock)
    async with application.router.lifespan_context(application):
        assert application.state.registration_policy is None


async def test_019_lifespan_with_smtp_builds_registration_policy(
    settings: Settings, fixed_clock: FixedClock
) -> None:
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
        policy = application.state.registration_policy
        assert isinstance(policy, reg.RegistrationPolicy)
        assert policy.base_url == BASE
        assert len(policy.limit_key) >= 32
        assert application.state.password_reset_policy is not None


# --- успех: письмо, токен, хеши, upsert (AC-5, AC-8, AC-9, RG-1, RG-19) ----------------------


async def test_019_ac5_success_mails_normalized_address(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    await make_workspace(db)
    msg = await ask(db, policy, hasher, fixed_clock, email=" Anna@Example.RU ")
    assert msg is not None
    assert msg.to == "anna@example.ru"
    assert msg.subject == "Подтверждение регистрации"


async def test_019_ac5_address_of_254_chars_is_accepted(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    await make_workspace(db)
    email = "a" * 243 + "@example.ru"
    assert len(email) == 254
    msg = await ask(db, policy, hasher, fixed_clock, email=email)
    assert msg is not None
    assert msg.to == email


async def test_019_ac8_mail_is_built_by_registration_template(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await make_workspace(db)
    token = "fixed-token-for-registration-test"
    monkeypatch.setattr(
        password_reset, "new_token", lambda: (token, hashlib.sha256(token.encode()).digest())
    )
    msg = await ask(db, policy, hasher, fixed_clock)
    assert msg is not None
    assert msg.to == "anna@example.ru"
    assert msg.subject == "Подтверждение регистрации"
    assert msg.body == (
        f"{BASE}/register/confirm#token={token}\n"
        "\n"
        "Ссылка действует 30 минут.\n"
        "\n"
        "Если вы не регистрировались, ничего не делайте: учётная запись не будет создана.\n"
    )
    for secret in (PASSWORD, "Anna_P", "anna_p", "Анна", "Петрова-Иванова"):
        assert secret not in msg.body


async def test_019_token_comes_from_password_reset_new_token(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await make_workspace(db)
    real = password_reset.new_token
    calls: list[int] = []

    def spy() -> tuple[str, bytes]:
        calls.append(1)
        return real()

    monkeypatch.setattr(password_reset, "new_token", spy)
    token = token_of(await ask(db, policy, hasher, fixed_clock))
    assert len(calls) == 1
    (row,) = await request_rows(db)
    assert bytes(row.token_hash) == sha256(token)


async def test_019_ac8_db_keeps_token_hash_and_argon2_hash_only(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    await make_workspace(db)
    token = token_of(await ask(db, policy, hasher, fixed_clock))
    (row,) = await request_rows(db)
    assert bytes(row.token_hash) == sha256(token)
    assert row.password_hash.startswith("$argon2id$")
    assert PASSWORD not in row.password_hash
    assert hasher.verify(row.password_hash, PASSWORD)


async def test_019_request_stores_normalized_fields_and_expiry(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    await make_workspace(db)
    await ask(db, policy, hasher, fixed_clock, first_name=" Анна ")
    (row,) = await request_rows(db)
    assert row.email == "anna@example.ru"
    assert row.login == "petrova-ivanova.anna"
    assert row.login_display == "petrova-ivanova.anna"
    assert row.first_name == "Анна"
    assert row.last_name == "Петрова-Иванова"
    assert row.created_at == fixed_clock.now()
    assert row.expires_at == fixed_clock.now() + timedelta(minutes=30)


async def test_019_generated_login_is_lowercase_and_display_equals_key(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    await make_workspace(db)
    await ask(db, policy, hasher, fixed_clock, last_name="SURIKOV", first_name="Антон")
    (row,) = await request_rows(db)
    assert row.login == "surikov.anton"
    assert row.login_display == "surikov.anton"


async def test_019_ac9_repeat_request_replaces_token_and_data(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    await make_workspace(db)
    first = token_of(await ask(db, policy, hasher, fixed_clock, first_name="Анна"))
    fixed_clock.advance(timedelta(minutes=5))
    second_password = "Another-Pw-2026-x"
    second = token_of(
        await ask(
            db,
            policy,
            hasher,
            fixed_clock,
            first_name="Мария",
            password=second_password,
        )
    )
    rows = await request_rows(db)
    assert len(rows) == 1
    row = rows[0]
    assert bytes(row.token_hash) == sha256(second)
    assert bytes(row.token_hash) != sha256(first)
    assert row.login == "petrova-ivanova.mariia"
    assert row.login_display == "petrova-ivanova.mariia"
    assert row.first_name == "Мария"
    assert hasher.verify(row.password_hash, second_password)
    assert row.created_at == fixed_clock.now()
    assert row.expires_at == fixed_clock.now() + timedelta(minutes=30)


async def test_019_first_name_of_100_chars_after_trim_is_accepted(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    await make_workspace(db)
    await ask(db, policy, hasher, fixed_clock, first_name=" " + "а" * 100 + " ")
    (row,) = await request_rows(db)
    assert row.first_name == "а" * 100


async def test_019_success_creates_no_account_and_no_event(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    await make_workspace(db)
    users, events = await count_users(db), await count_events(db)
    assert await ask(db, policy, hasher, fixed_clock) is not None
    assert await count_users(db) == users
    assert await count_events(db) == events


async def test_019_expired_requests_are_purged_when_request_accepted(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    await make_workspace(db)
    now = fixed_clock.now()

    def stored(email: str, token_byte: bytes, expires_at: Any) -> RegistrationRequest:
        return RegistrationRequest(
            email=email,
            login=email.split("@")[0],
            login_display=email.split("@")[0],
            first_name="Имя",
            last_name="Фамилия",
            password_hash="$argon2id$stub",
            token_hash=token_byte * 32,
            created_at=now - timedelta(hours=1),
            expires_at=expires_at,
        )

    db.add_all(
        [
            stored("old@example.ru", b"\x01", now - timedelta(minutes=1)),
            stored("edge@example.ru", b"\x02", now),  # граница: expires_at <= now удаляется
            stored("live@example.ru", b"\x03", now + timedelta(minutes=1)),
        ]
    )
    await db.flush()
    await ask(db, policy, hasher, fixed_clock)
    emails = [row.email for row in await request_rows(db)]
    assert emails == ["anna@example.ru", "live@example.ru"]


# --- адрес занят (FR-7, AC-7, AC-11, RG-7): None, заявки нет, Argon2 выполнен ---------------


@pytest.mark.parametrize("blocked", [False, True], ids=["active", "blocked"])
async def test_019_ac11_taken_address_returns_none_without_request(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
    blocked: bool,
) -> None:
    ws = await make_workspace(db)
    await make_user(db, workspace=ws, email="anna@example.ru", blocked=blocked)
    users = await count_users(db)
    assert await ask(db, policy, hasher, fixed_clock, email=" Anna@Example.RU ") is None
    assert await count_requests(db) == 0
    assert await count_users(db) == users
    assert await count_attempts(db) == 1  # попытка учтена в лимите (RG-5)


async def test_019_ac7_taken_address_still_runs_argon2_once(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = await make_workspace(db)
    await make_user(db, workspace=ws, email="anna@example.ru")
    calls = spy_hash(monkeypatch)
    assert await ask(db, policy, hasher, fixed_clock) is None
    assert len(calls) == 1


async def test_019_ac7_free_address_runs_argon2_once(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await make_workspace(db)
    calls = spy_hash(monkeypatch)
    assert await ask(db, policy, hasher, fixed_clock) is not None
    assert len(calls) == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"email": ""},
        {"first_name": "  "},
        {"last_name": ""},
        {"last_name": "李"},
        {"password": "short-pass"},
    ],
    ids=["email", "first_name", "last_name", "last_name_no_latin", "password"],
)
async def test_019_rg7_no_argon2_before_validation_passes(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, str],
) -> None:
    await make_workspace(db)
    calls = spy_hash(monkeypatch)
    with pytest.raises(Unprocessable):
        await ask(db, policy, hasher, fixed_clock, **overrides)
    assert calls == []


# --- валидация: коды и порядок проверок RG-7 (FR-3, FR-3a, AC-4, AC-15, AC-27, AC-29) ----


@pytest.mark.parametrize(
    "email",
    [
        "",
        "   ",
        "a" * 244 + "@example.ru",  # 255 символов
        "anna.example.ru",
        "a@b@example.ru",
        "anna@",
        "anna@example.ru\n",
    ],
    ids=["empty", "spaces", "255_chars", "no_at", "two_at", "no_domain", "newline"],
)
async def test_019_ac4_invalid_email_is_email_invalid(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
    email: str,
) -> None:
    await make_workspace(db)
    with pytest.raises(Unprocessable) as exc:
        await ask(db, policy, hasher, fixed_clock, email=email)
    assert exc.value.status_code == 422
    assert exc.value.code == "email_invalid"
    assert await count_requests(db) == 0


@pytest.mark.parametrize("first_name", ["", "   ", "а" * 101, "Ан\x07на"])
async def test_019_ac29_bad_first_name_is_first_name_invalid(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
    first_name: str,
) -> None:
    await make_workspace(db)
    with pytest.raises(Unprocessable) as exc:
        await ask(db, policy, hasher, fixed_clock, first_name=first_name)
    assert exc.value.code == "first_name_invalid"
    assert await count_requests(db) == 0


@pytest.mark.parametrize("last_name", ["", "\t", "б" * 101])
async def test_019_ac29_bad_last_name_is_last_name_invalid(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
    last_name: str,
) -> None:
    await make_workspace(db)
    with pytest.raises(Unprocessable) as exc:
        await ask(db, policy, hasher, fixed_clock, last_name=last_name)
    assert exc.value.code == "last_name_invalid"
    assert await count_requests(db) == 0


async def test_019_login_held_by_user_gets_next_suffix(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    ws = await make_workspace(db)
    await make_user(db, workspace=ws, login="surikov.anton", email="busy@example.ru")
    message = await ask(
        db,
        policy,
        hasher,
        fixed_clock,
        email="free@example.ru",
        last_name="Суриков",
        first_name="Антон",
    )
    assert message is not None
    (row,) = await request_rows(db)
    assert row.login == "surikov.anton.2"
    assert row.login_display == "surikov.anton.2"


async def test_019_busy_address_with_taken_login_gives_same_answer(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    ws = await make_workspace(db)
    await make_user(db, workspace=ws, login="surikov.anton", email="busy@example.ru")
    free = await ask(
        db,
        policy,
        hasher,
        fixed_clock,
        email="free@example.ru",
        last_name="Суриков",
        first_name="Антон",
    )
    busy = await ask(
        db,
        policy,
        hasher,
        fixed_clock,
        email="busy@example.ru",
        last_name="Суриков",
        first_name="Антон",
    )
    assert free is not None
    assert busy is None
    assert await count_requests(db) == 1


async def test_019_active_request_of_other_address_blocks_login(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    await make_workspace(db)
    await ask(
        db,
        policy,
        hasher,
        fixed_clock,
        email="first@example.ru",
        last_name="Суриков",
        first_name="Антон",
    )
    await ask(
        db,
        policy,
        hasher,
        fixed_clock,
        email="second@example.ru",
        last_name="Суриков",
        first_name="Антон",
    )
    logins = {row.email: row.login for row in await request_rows(db)}
    assert logins == {"first@example.ru": "surikov.anton", "second@example.ru": "surikov.anton.2"}


async def test_019_expired_request_does_not_block_login(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    await make_workspace(db)
    await ask(
        db,
        policy,
        hasher,
        fixed_clock,
        email="first@example.ru",
        last_name="Суриков",
        first_name="Антон",
    )
    fixed_clock.advance(timedelta(minutes=31))
    await ask(
        db,
        policy,
        hasher,
        fixed_clock,
        email="second@example.ru",
        last_name="Суриков",
        first_name="Антон",
    )
    logins = {row.email: row.login for row in await request_rows(db)}
    assert logins == {"second@example.ru": "surikov.anton"}


async def test_019_own_request_of_same_address_does_not_block_itself(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    await make_workspace(db)
    await ask(db, policy, hasher, fixed_clock, last_name="Суриков", first_name="Антон")
    fixed_clock.advance(timedelta(minutes=5))
    await ask(db, policy, hasher, fixed_clock, last_name="Суриков", first_name="Антон")
    (row,) = await request_rows(db)
    assert row.login == "surikov.anton"


async def test_019_suffix_skips_every_taken_candidate(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    ws = await make_workspace(db)
    await make_user(db, workspace=ws, login="surikov.anton", email="busy@example.ru")
    await ask(
        db,
        policy,
        hasher,
        fixed_clock,
        email="first@example.ru",
        last_name="Суриков",
        first_name="Антон",
    )
    await ask(
        db,
        policy,
        hasher,
        fixed_clock,
        email="second@example.ru",
        last_name="Суриков",
        first_name="Антон",
    )
    logins = {row.email: row.login for row in await request_rows(db)}
    assert logins == {"first@example.ru": "surikov.anton.2", "second@example.ru": "surikov.anton.3"}


async def test_019_login_in_form_is_not_part_of_the_form(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    await make_workspace(db)
    with pytest.raises(TypeError):
        reg.RegistrationForm(  # type: ignore[call-arg]
            email="anna@example.ru",
            first_name="Анна",
            last_name="Петрова-Иванова",
            login="anna",
            password=SecretStr(PASSWORD),
        )


@pytest.mark.parametrize(
    ("password", "code"),
    [
        ("a" * 11, "password_too_short"),
        ("unbelievable", "password_too_common"),
        ("\ud800" + "x" * 11, "validation_error"),  # не кодируется в UTF-8
    ],
    ids=["too_short", "too_common", "not_utf8"],
)
async def test_019_ac15_bad_password_is_422_with_code(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
    password: str,
    code: str,
) -> None:
    await make_workspace(db)
    with pytest.raises(Unprocessable) as exc:
        await ask(db, policy, hasher, fixed_clock, password=password)
    assert exc.value.status_code == 422
    assert exc.value.code == code
    assert password not in exc.value.detail


async def test_019_ac15_password_of_12_chars_is_accepted(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    await make_workspace(db)
    assert await ask(db, policy, hasher, fixed_clock, password="Zq7!Zq7!Zq7!") is not None


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"email": "bad", "password": "short"}, "email_invalid"),
        ({"first_name": "", "password": "short"}, "first_name_invalid"),
        ({"last_name": "", "password": "short"}, "last_name_invalid"),
        ({"last_name": "李", "password": "short"}, "last_name_invalid"),
        ({"first_name": "李", "password": "short"}, "first_name_invalid"),
        ({"email": "busy@example.ru", "password": "short"}, "password_too_short"),
        ({"password": "short"}, "password_too_short"),
    ],
    ids=[
        "email_before_name_and_password",
        "first_name_before_password",
        "last_name_before_password",
        "last_name_no_latin",
        "first_name_no_latin",
        "password_before_taken_address",
        "password_only",
    ],
)
async def test_019_rg7_checks_run_in_documented_order(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
    overrides: dict[str, str],
    code: str,
) -> None:
    ws = await make_workspace(db)
    await make_user(db, workspace=ws, login="newuser", email="busy@example.ru")
    with pytest.raises(Unprocessable) as exc:
        await ask(db, policy, hasher, fixed_clock, **overrides)
    assert exc.value.code == code
    assert await count_requests(db) == 0


async def test_019_rg7_validation_answer_does_not_depend_on_address(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    ws = await make_workspace(db)
    await make_user(db, workspace=ws, email="busy@example.ru")
    answers: list[tuple[int, str, str]] = []
    for email in ("free@example.ru", "busy@example.ru"):
        with pytest.raises(Unprocessable) as exc:
            await ask(db, policy, hasher, fixed_clock, email=email, password="short")
        answers.append((exc.value.status_code, exc.value.code, exc.value.detail))
    assert answers[0] == answers[1]


# --- лимит заявок с IP (FR-10, AC-18, RG-5, RG-7) --------------------------------------------


async def test_019_ac18_ten_requests_per_ip_then_rate_limited(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    await make_workspace(db)
    for i in range(10):
        assert await ask(db, policy, hasher, fixed_clock, email=f"user{i}@example.ru") is not None
    with pytest.raises(RateLimited) as exc:
        await ask(db, policy, hasher, fixed_clock, email="user10@example.ru")
    assert exc.value.status_code == 429
    assert exc.value.code == "rate_limited"
    assert await count_requests(db) == 10
    assert await count_attempts(db) == 10


async def test_019_ac18_other_ip_is_not_limited(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    await make_workspace(db)
    for i in range(10):
        await ask(db, policy, hasher, fixed_clock, email=f"user{i}@example.ru")
    assert (
        await ask(db, policy, hasher, fixed_clock, ip=OTHER_IP, email="other@example.ru")
        is not None
    )


async def test_019_ac18_unknown_ip_shares_one_bucket(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    # client_ip=None: общая корзина "no-ip" (ревью R8-T09; требует подтверждения владельца)
    await make_workspace(db)
    for i in range(10):
        msg = await ask(db, policy, hasher, fixed_clock, ip=None, email=f"unknown{i}@example.ru")
        assert msg is not None
    with pytest.raises(RateLimited) as exc:
        await ask(db, policy, hasher, fixed_clock, ip=None, email="unknown10@example.ru")
    assert exc.value.code == "rate_limited"
    assert await count_attempts(db) == 10
    assert await ask(db, policy, hasher, fixed_clock, ip=IP, email="known@example.ru") is not None


@pytest.mark.parametrize("busy", [False, True], ids=["free_address", "taken_address"])
async def test_019_ac18_same_address_ten_times_then_rate_limited(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
    busy: bool,
) -> None:
    ws = await make_workspace(db)
    if busy:
        await make_user(db, workspace=ws, email="anna@example.ru")
    for _ in range(10):
        await ask(db, policy, hasher, fixed_clock)
    with pytest.raises(RateLimited) as exc:
        await ask(db, policy, hasher, fixed_clock)
    assert exc.value.code == "rate_limited"


async def test_019_rg5_422_attempts_count_toward_ip_limit(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    await make_workspace(db)
    bad_forms = [{"last_name": "李"}, {"email": "bad"}, {"password": "short"}]
    for i in range(10):
        with pytest.raises(Unprocessable):
            await ask(db, policy, hasher, fixed_clock, **bad_forms[i % 3])
    assert await count_attempts(db) == 10
    assert await count_requests(db) == 0
    with pytest.raises(RateLimited):
        await ask(db, policy, hasher, fixed_clock)


async def test_019_rg5_rate_limit_is_checked_before_form_validation(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    await make_workspace(db)
    for i in range(10):
        await ask(db, policy, hasher, fixed_clock, email=f"user{i}@example.ru")
    with pytest.raises(RateLimited):
        await ask(db, policy, hasher, fixed_clock, email="bad")


@pytest.mark.committed
async def test_019_rg6_422_attempt_survives_request_rollback(
    committed: async_sessionmaker[AsyncSession],
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    async with committed() as s:
        await make_workspace(s)
        await s.commit()
    async with committed() as s:
        with pytest.raises(Unprocessable):
            await reg.request_registration(
                s,
                policy,
                hasher,
                form=make_form(last_name="李"),
                client_ip=IP,
                now=fixed_clock.now(),
            )
        await s.rollback()  # так поступает get_db при исключении
    async with committed() as s:
        assert await count_attempts(s) == 1


# --- логи (NFR-1, AC-20) -----------------------------------------------------------------------


async def test_019_no_logs_with_personal_data_or_secrets(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    # контрольная запись: caplog ловит логи этого теста, иначе проверка ниже ничего не доказывает
    control = "control-marker-019"
    logging.getLogger("tests.domain.test_019").info("%s", control)
    assert control in caplog.text
    await make_workspace(db)
    token = token_of(await ask(db, policy, hasher, fixed_clock))
    with pytest.raises(Unprocessable):
        await ask(db, policy, hasher, fixed_clock, email="other@example.ru", password="short")
    for secret in (
        "anna@example.ru",
        "Анна",
        "Петрова-Иванова",
        "Anna_P",
        "anna_p",
        PASSWORD,
        token,
    ):
        assert secret not in caplog.text
