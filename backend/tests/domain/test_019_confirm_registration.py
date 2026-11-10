"""R8-T10: подтверждение регистрации (spec 019: FR-6, FR-8, FR-9, FR-10, FR-11; AC-9, AC-10, AC-13,
AC-14, AC-16, AC-19, AC-28, AC-38; plan §4.3, RG-6, RG-8, RG-9).

Публичный интерфейс: ``app.domain.auth.registration.confirm_registration``. Ссылку для подтверждения
готовит ``request_registration`` (R8-T09); токен берётся из тела письма, которое возвращает домен.
Время — ``fixed_clock``; Argon2 — дешёвые параметры; почта не отправляется.
"""

from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from app.core.errors import (
    FeatureDisabled,
    LoginTakenConflict,
    RateLimited,
    RegistrationTokenInvalid,
)
from app.core.security.passwords import PasswordHasher
from app.domain.auth import registration as reg
from tests.factories import make_user, make_workspace

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.core.clock import FixedClock
    from app.core.mail import MailMessage

BASE = "https://tracker.example.test"
KEY = b"k" * 32
IP = "203.0.113.10"
OTHER_IP = "203.0.113.11"
PASSWORD = "Zq7-registration-pw"  # 19 символов, не в списке частых
EMAIL = "anna@example.ru"
LINK_RE = re.compile(re.escape(BASE) + r"/register/confirm#token=([A-Za-z0-9_-]+)")


@pytest.fixture
def hasher() -> PasswordHasher:
    return PasswordHasher(time_cost=1, memory_cost_kib=1024, parallelism=1)


@pytest.fixture
def policy() -> reg.RegistrationPolicy:
    return reg.RegistrationPolicy(base_url=BASE, limit_key=KEY)


def token_of(message: MailMessage | None) -> str:
    assert message is not None, "письмо не выдано"
    match = LINK_RE.search(message.body)
    assert match is not None, "ссылка подтверждения не найдена в письме"
    return match.group(1)


async def request_link(
    db: AsyncSession,
    policy: reg.RegistrationPolicy | None,
    hasher: PasswordHasher,
    clock: FixedClock,
    *,
    email: str = EMAIL,
    ip: str | None = IP,
) -> str:
    """Заявка через домен (R8-T09); возвращает токен из письма. Логин выбирает сервер (v0.5)."""
    form = reg.RegistrationForm(
        email=email,
        first_name="Анна",
        last_name="Петрова-Иванова",
        password=SecretStr(PASSWORD),
    )
    message = await reg.request_registration(
        db, policy, hasher, form=form, client_ip=ip, now=clock.now()
    )
    return token_of(message)


async def confirm(
    db: AsyncSession,
    policy: reg.RegistrationPolicy | None,
    clock: FixedClock,
    token: str,
    *,
    ip: str | None = IP,
) -> None:
    await reg.confirm_registration(
        db, policy, token=SecretStr(token), client_ip=ip, now=clock.now()
    )


async def scalar_count(db: AsyncSession, sql: str, **params: Any) -> int:
    return int(await db.scalar(text(sql), params) or 0)


async def count_users(db: AsyncSession) -> int:
    return await scalar_count(db, "SELECT count(*) FROM app_user")


async def count_requests(db: AsyncSession) -> int:
    return await scalar_count(db, "SELECT count(*) FROM registration_request")


async def count_attempts(db: AsyncSession, scope: str) -> int:
    return await scalar_count(
        db, "SELECT count(*) FROM registration_attempt WHERE scope = :scope", scope=scope
    )


async def count_sessions(db: AsyncSession) -> int:
    return await scalar_count(db, "SELECT count(*) FROM user_session")


async def count_self_registered_events(db: AsyncSession) -> int:
    return await scalar_count(
        db,
        "SELECT count(*) FROM domain_event WHERE action = 'user.self_registered'",
    )


async def count_all_events(db: AsyncSession) -> int:
    return await scalar_count(db, "SELECT count(*) FROM domain_event")


async def account(db: AsyncSession, login_key: str) -> dict[str, Any]:
    """Учётная запись и её членство в пространстве (поля AC-13)."""
    row = (
        (
            await db.execute(
                text(
                    "SELECT u.id, u.login, u.login_display, u.email, u.first_name, u.last_name, "
                    "u.password_hash, u.self_registered, u.must_change_password, u.is_blocked, "
                    "u.failed_login_count, u.created_by, m.workspace_id, m.role, "
                    "m.created_by AS member_created_by "
                    "FROM app_user u JOIN workspace_member m ON m.user_id = u.id "
                    "WHERE u.login = :login"
                ),
                {"login": login_key},
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


# --- успех и поля учётной записи (AC-13, AC-16, AC-19) -----------------------------------------


async def test_019_ac13_confirm_creates_self_registered_account(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    ws = await make_workspace(db)
    token = await request_link(db, policy, hasher, fixed_clock)
    await confirm(db, policy, fixed_clock, token)

    row = await account(db, "petrova-ivanova.anna")
    assert row["login_display"] == "petrova-ivanova.anna"
    assert row["email"] == EMAIL
    assert (row["first_name"], row["last_name"]) == ("Анна", "Петрова-Иванова")
    assert row["self_registered"] is True
    assert row["must_change_password"] is False
    assert row["is_blocked"] is False
    assert row["failed_login_count"] == 0
    assert row["created_by"] is None
    assert row["workspace_id"] == ws.id
    assert row["role"] is None  # «без роли» (ADR-0013)
    assert row["member_created_by"] is None
    assert hasher.verify(row["password_hash"], PASSWORD)
    assert await count_requests(db) == 0  # заявка поглощена


async def test_019_ac16_confirm_creates_no_session_and_token_is_single_use(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    await make_workspace(db)
    token = await request_link(db, policy, hasher, fixed_clock)
    assert await confirm(db, policy, fixed_clock, token) is None
    assert await count_sessions(db) == 0
    with pytest.raises(RegistrationTokenInvalid) as exc:
        await confirm(db, policy, fixed_clock, token)
    assert exc.value.status_code == 400
    assert exc.value.code == "registration_token_invalid"
    assert await count_users(db) == 1


async def test_019_ac19_success_writes_exactly_one_self_registered_event(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    ws = await make_workspace(db)
    token = await request_link(db, policy, hasher, fixed_clock)
    await confirm(db, policy, fixed_clock, token)

    row = await account(db, "petrova-ivanova.anna")
    events = (
        (
            await db.execute(
                text(
                    "SELECT workspace_id, actor_id, entity_type, entity_id, changed_fields "
                    "FROM domain_event WHERE action = 'user.self_registered'"
                )
            )
        )
        .mappings()
        .all()
    )
    assert len(events) == 1
    event = events[0]
    assert event["workspace_id"] == ws.id
    assert event["actor_id"] == row["id"] == event["entity_id"]
    assert event["entity_type"] == "user"
    assert list(event["changed_fields"]) == []
    assert await count_all_events(db) == 1


# --- срок токена (AC-10) и повторные заявки (AC-9) ---------------------------------------------


@pytest.mark.parametrize(
    ("elapsed", "accepted"),
    [
        (timedelta(minutes=29, seconds=59), True),
        (timedelta(minutes=30), False),
        (timedelta(minutes=30, seconds=1), False),
    ],
    ids=["29:59", "30:00", "30:01"],
)
async def test_019_ac10_token_lifetime_boundary(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
    elapsed: timedelta,
    accepted: bool,
) -> None:
    await make_workspace(db)
    token = await request_link(db, policy, hasher, fixed_clock)
    fixed_clock.advance(elapsed)
    if accepted:
        await confirm(db, policy, fixed_clock, token)
        assert await count_users(db) == 1
        return
    with pytest.raises(RegistrationTokenInvalid) as exc:
        await confirm(db, policy, fixed_clock, token)
    assert exc.value.status_code == 400
    assert exc.value.code == "registration_token_invalid"
    assert await count_users(db) == 0


async def test_019_ac9_first_token_after_second_request_is_invalid(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    await make_workspace(db)
    first = await request_link(db, policy, hasher, fixed_clock)
    second = await request_link(db, policy, hasher, fixed_clock)
    with pytest.raises(RegistrationTokenInvalid):
        await confirm(db, policy, fixed_clock, first)
    assert await count_users(db) == 0
    await confirm(db, policy, fixed_clock, second)
    assert await count_users(db) == 1


@pytest.mark.parametrize(
    "raw",
    ["ток-ен", "\ud800abc", "x" * 5000],
    ids=["non_ascii", "lone_surrogate", "very_long"],
)
async def test_019_garbage_token_is_invalid_not_a_server_error(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    fixed_clock: FixedClock,
    raw: str,
) -> None:
    await make_workspace(db)
    with pytest.raises(RegistrationTokenInvalid):
        await confirm(db, policy, fixed_clock, raw)
    assert await count_users(db) == 0


# --- конфигурация и пространство (RG-8, RG-9) --------------------------------------------------


async def test_019_confirm_policy_none_is_feature_disabled(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    await make_workspace(db)
    token = await request_link(db, policy, hasher, fixed_clock)
    with pytest.raises(FeatureDisabled):
        await confirm(db, None, fixed_clock, token)
    assert await count_users(db) == 0
    assert await count_attempts(db, "confirm_ip") == 0


async def test_019_confirm_with_two_workspaces_is_feature_disabled(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    await make_workspace(db)
    token = await request_link(db, policy, hasher, fixed_clock)
    await make_workspace(db)  # второе пространство: пилот больше не единственный
    with pytest.raises(FeatureDisabled):
        await confirm(db, policy, fixed_clock, token)
    assert await count_users(db) == 0


async def test_019_confirm_wrong_token_with_zero_workspaces_is_feature_disabled(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    fixed_clock: FixedClock,
) -> None:
    # RG-8: пространство проверяется раньше лимитов и токена (как в RG-7), поэтому неверный токен
    # при нуле пространств не записывает попыток и не отвечает 400 (нет оракула валидности).
    with pytest.raises(FeatureDisabled) as exc:
        await confirm(db, policy, fixed_clock, "unknown-token")
    assert exc.value.status_code == 404
    assert await count_attempts(db, "confirm_ip") == 0
    assert await count_attempts(db, "confirm_token") == 0


async def test_019_confirm_wrong_token_with_two_workspaces_is_feature_disabled(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    fixed_clock: FixedClock,
) -> None:
    await make_workspace(db)
    await make_workspace(db)
    with pytest.raises(FeatureDisabled) as exc:
        await confirm(db, policy, fixed_clock, "unknown-token")
    assert exc.value.status_code == 404
    assert await count_attempts(db, "confirm_ip") == 0
    assert await count_attempts(db, "confirm_token") == 0
    assert await count_users(db) == 0


async def test_019_confirm_valid_token_with_zero_workspaces_works_after_one_is_back(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    ws = await make_workspace(db)
    token = await request_link(db, policy, hasher, fixed_clock)
    await db.execute(text("DELETE FROM workspace WHERE id = :id"), {"id": ws.id})
    with pytest.raises(FeatureDisabled) as exc:
        await confirm(db, policy, fixed_clock, token)
    assert exc.value.status_code == 404
    assert await count_attempts(db, "confirm_token") == 0
    assert await count_users(db) == 0
    await make_workspace(db)  # вернулось одно пространство
    await confirm(db, policy, fixed_clock, token)
    assert await count_users(db) == 1


# --- занятость адреса и логина при подтверждении (AC-14, AC-28, RG-8) --------------------------


@pytest.mark.committed
async def test_019_ac14_address_taken_at_confirm_is_400_and_request_removed(
    committed: async_sessionmaker[AsyncSession],
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    async with committed() as s:
        ws = await make_workspace(s)
        token = await request_link(s, policy, hasher, fixed_clock)
        await s.commit()
    async with committed() as s:
        await make_user(s, workspace=ws, login="other_user", email=EMAIL)
        await s.commit()
    async with committed() as s:
        with pytest.raises(RegistrationTokenInvalid):
            await confirm(s, policy, fixed_clock, token)
        await s.rollback()  # так поступает get_db при исключении
    async with committed() as s:
        assert await count_requests(s) == 0  # удаление заявки пережило откат (RG-6)
        assert await count_users(s) == 1
        assert await count_self_registered_events(s) == 0
        with pytest.raises(RegistrationTokenInvalid):
            await confirm(s, policy, fixed_clock, token)


@pytest.mark.committed
async def test_019_ac28_login_taken_after_request_gets_next_suffix(
    committed: async_sessionmaker[AsyncSession],
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    async with committed() as s:
        ws = await make_workspace(s)
        token = await request_link(s, policy, hasher, fixed_clock)
        await s.commit()
    async with committed() as s:
        await make_user(s, workspace=ws, login="petrova-ivanova.anna", email="owner@example.ru")
        await s.commit()
    async with committed() as s:
        login = await reg.confirm_registration(
            s, policy, token=SecretStr(token), client_ip=IP, now=fixed_clock.now()
        )
        await s.commit()
    assert login == "petrova-ivanova.anna.2"
    async with committed() as s:
        assert await count_requests(s) == 0
        assert await count_users(s) == 2
        row = await account(s, "petrova-ivanova.anna.2")
        assert row["email"] == EMAIL


async def test_019_all_candidates_taken_is_409_request_removed_then_400(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = await make_workspace(db)
    token = await request_link(db, policy, hasher, fixed_clock)
    await make_user(db, workspace=ws, login="petrova-ivanova.anna", email="owner1@example.ru")
    await make_user(db, workspace=ws, login="petrova-ivanova.anna.2", email="owner2@example.ru")
    monkeypatch.setattr(reg, "CONFIRM_LOGIN_ATTEMPTS", 2)  # только два кандидата
    with pytest.raises(LoginTakenConflict) as exc:
        await confirm(db, policy, fixed_clock, token)
    assert exc.value.code == "login_taken"
    assert await count_requests(db) == 0
    assert await count_users(db) == 2
    assert await count_self_registered_events(db) == 0
    with pytest.raises(RegistrationTokenInvalid):
        await confirm(db, policy, fixed_clock, token)


async def test_019_rg8_address_check_precedes_login_check(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    ws = await make_workspace(db)
    token = await request_link(db, policy, hasher, fixed_clock)
    await make_user(db, workspace=ws, login="petrova-ivanova.anna", email="owner1@example.ru")
    await make_user(db, workspace=ws, login="owner_two", email=EMAIL)
    with pytest.raises(RegistrationTokenInvalid):
        await confirm(db, policy, fixed_clock, token)
    assert await count_users(db) == 2


async def test_019_race_address_taken_after_check_is_400(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = await make_workspace(db)
    token = await request_link(db, policy, hasher, fixed_clock)
    await make_user(db, workspace=ws, login="owner_one", email=EMAIL)

    async def seen_as_free(_db: AsyncSession, _email: str) -> bool:
        return False  # проверка прошла, параллельная учётная запись появилась позже

    monkeypatch.setattr(reg, "_email_taken", seen_as_free)
    with pytest.raises(RegistrationTokenInvalid):
        await confirm(db, policy, fixed_clock, token)  # гонка: uq_app_user_email
    assert await count_requests(db) == 0
    assert await count_users(db) == 1
    assert await count_self_registered_events(db) == 0


async def test_019_race_login_conflict_on_insert_moves_to_next_candidate(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = await make_workspace(db)
    token = await request_link(db, policy, hasher, fixed_clock)
    await make_user(db, workspace=ws, login="petrova-ivanova.anna", email="owner1@example.ru")

    async def seen_as_free(_db: AsyncSession, _login: str) -> bool:
        return False  # проверка прошла, логин занял параллельный запрос

    monkeypatch.setattr(reg, "_login_taken", seen_as_free)
    login = await reg.confirm_registration(
        db, policy, token=SecretStr(token), client_ip=IP, now=fixed_clock.now()
    )  # гонка: ON CONFLICT (login) DO NOTHING -> следующий кандидат, без login_taken
    assert login == "petrova-ivanova.anna.2"
    assert await count_requests(db) == 0
    assert await count_users(db) == 2
    assert await count_self_registered_events(db) == 1


async def test_019_ac19_failed_confirms_write_no_events(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    ws = await make_workspace(db)
    expired = await request_link(db, policy, hasher, fixed_clock, email="late@example.ru")
    fixed_clock.advance(timedelta(minutes=31))
    with pytest.raises(RegistrationTokenInvalid):
        await confirm(db, policy, fixed_clock, expired)

    busy = await request_link(db, policy, hasher, fixed_clock, email="busy@example.ru")
    await make_user(db, workspace=ws, login="owner_one", email="busy@example.ru")
    with pytest.raises(RegistrationTokenInvalid):
        await confirm(db, policy, fixed_clock, busy)

    assert await count_all_events(db) == 0
    assert await count_users(db) == 1


# --- лимиты подтверждения (AC-38, FR-10, RG-4, RG-6) -------------------------------------------


async def test_019_ac38_sixth_confirm_with_same_token_is_rate_limited(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    ws = await make_workspace(db)
    token = await request_link(db, policy, hasher, fixed_clock)
    # Адрес занят: первые пять попыток отказывают (заявка уходит с первой), учётная запись
    # не создаётся. Шестая попытка должна отказать по лимиту раньше поиска токена.
    await make_user(db, workspace=ws, login="owner_one", email=EMAIL)
    for _ in range(5):
        with pytest.raises(RegistrationTokenInvalid):
            await confirm(db, policy, fixed_clock, token)
    with pytest.raises(RateLimited) as exc:
        await confirm(db, policy, fixed_clock, token)
    assert exc.value.status_code == 429
    assert exc.value.code == "rate_limited"
    assert await count_attempts(db, "confirm_token") == 5  # отклонённая попытка не записана
    assert await count_users(db) == 1


async def test_019_ac38_twenty_first_confirm_from_ip_is_rate_limited(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
) -> None:
    await make_workspace(db)
    token = await request_link(db, policy, hasher, fixed_clock)
    for i in range(20):
        with pytest.raises(RegistrationTokenInvalid):
            await confirm(db, policy, fixed_clock, f"unknown-token-{i:02d}")
    with pytest.raises(RateLimited) as exc:
        await confirm(db, policy, fixed_clock, token)  # действующий токен тоже под лимитом
    assert exc.value.status_code == 429
    assert await count_attempts(db, "confirm_ip") == 20
    assert await count_users(db) == 0
    with pytest.raises(RegistrationTokenInvalid):
        await confirm(db, policy, fixed_clock, "unknown-token-other", ip=OTHER_IP)


@pytest.mark.committed
async def test_019_rg6_failed_confirm_attempt_survives_rollback(
    committed: async_sessionmaker[AsyncSession],
    policy: reg.RegistrationPolicy,
    fixed_clock: FixedClock,
) -> None:
    async with committed() as s:
        await make_workspace(s)
        await s.commit()
    async with committed() as s:
        with pytest.raises(RegistrationTokenInvalid):
            await confirm(s, policy, fixed_clock, "unknown-token")
        await s.rollback()  # так поступает get_db при исключении
    async with committed() as s:
        assert await count_attempts(s, "confirm_ip") == 1
        assert await count_attempts(s, "confirm_token") == 1


# --- логи (NFR-1) ------------------------------------------------------------------------------


async def test_019_no_logs_with_personal_data_or_secrets_on_confirm(
    db: AsyncSession,
    policy: reg.RegistrationPolicy,
    hasher: PasswordHasher,
    fixed_clock: FixedClock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    # контрольная запись: caplog ловит логи этого теста, иначе проверка ниже ничего не доказывает
    control = "control-marker-019-confirm"
    logging.getLogger("tests.domain.test_019").info("%s", control)
    assert control in caplog.text
    await make_workspace(db)
    token = await request_link(db, policy, hasher, fixed_clock)
    await confirm(db, policy, fixed_clock, token)
    with pytest.raises(RegistrationTokenInvalid):
        await confirm(db, policy, fixed_clock, token)
    for secret in (EMAIL, "Анна", "Петрова-Иванова", "petrova-ivanova.anna", PASSWORD, token):
        assert secret not in caplog.text
