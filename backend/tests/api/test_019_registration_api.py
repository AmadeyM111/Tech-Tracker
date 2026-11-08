"""R8-T11: публичный API самостоятельной регистрации (spec 019; plan §4.4, §6, RG-5, RG-7..RG-9).

Трассировка plan §6 на уровне HTTP: AC-1, AC-4…AC-16, AC-18, AC-27…AC-29, AC-38. Контракт:
``POST /api/v1/auth/registration/request`` -> 200 ``{"detail": FR-4}`` для любого корректно
заполненного адреса; ``POST .../confirm`` -> 204 без тела и cookie. Без пространства или при
двух пространствах оба POST -> 404 ``feature_disabled`` (RG-9). SMTP всегда подменён
(``RecordingMailer`` через ``reset_api_env``); при выключенной функции (``api_env``) писем нет.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import statistics
import time
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.api.v1 import registration as registration_api
from app.core.mail import MailMessage
from app.domain.auth import registration as registration_domain
from tests.admin_support import (
    ADMIN_USERS,
    OTP,
    OTP_FIELD,
    code_of,
    events,
    new_workspace,
    seed,
)
from tests.conftest import ApiEnv

if TYPE_CHECKING:
    from tests.factories import WorkspaceRow

REQUEST = "/api/v1/auth/registration/request"
CONFIRM = "/api/v1/auth/registration/confirm"
RESET_REQUEST = "/api/v1/auth/password-reset/request"
ACCEPTED = {
    "detail": (
        "Если адрес можно использовать для регистрации, мы отправили на него письмо с "
        "подтверждением. Ссылка действует 30 минут."
    )
}
LINK_PREFIX = "https://tracker.example.test/register/confirm#token="
MAIL_SUBJECT = "Подтверждение регистрации"
PW = "Zq7-registration-pw"  # 19 символов, не в списке частых
FIRST = "Анна"
LAST = "Петрова-Иванова"
LOGIN = "anna.petrova"


def _body(email: str, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "email": email,
        "first_name": FIRST,
        "last_name": LAST,
        "login": LOGIN,
        "password": PW,
    }
    values.update(overrides)
    return values


def _ip(n: int) -> str:
    """Уникальный адрес клиента для номера ``n`` (лимит по IP не должен мешать замеру)."""
    return f"198.51.{n // 250}.{n % 250 + 1}"


async def _from_ip(env: ApiEnv, ip: str, method: str, url: str, **kwargs: Any) -> httpx.Response:
    """Запрос с заданным адресом клиента: ``request.client`` берётся из ``ASGITransport``."""
    transport = httpx.ASGITransport(app=env.app, client=(ip, 40000))
    async with httpx.AsyncClient(transport=transport, base_url=env.base_url) as client:
        return await client.request(method, url, **kwargs)


def _mails(env: ApiEnv) -> list[Any]:
    return list(env.app.state.mailer.sent)


def _last_token(env: ApiEnv) -> str:
    body = _mails(env)[-1].body
    return body.split(LINK_PREFIX, 1)[1].split()[0]


async def _rows(env: ApiEnv, sql: str, **params: Any) -> list[Any]:
    rows = await env.execute(text(sql).bindparams(**params))
    assert rows is not None
    return list(rows)


async def _accounts(env: ApiEnv, email: str) -> int:
    rows = await _rows(env, "SELECT count(*) FROM app_user WHERE email = :e", e=email)
    return int(rows[0][0])


async def _account_count(env: ApiEnv) -> int:
    rows = await _rows(env, "SELECT count(*) FROM app_user")
    return int(rows[0][0])


async def _request_count(env: ApiEnv, email: str) -> int:
    rows = await _rows(env, "SELECT count(*) FROM registration_request WHERE email = :e", e=email)
    return int(rows[0][0])


async def _post_request(env: ApiEnv, body: Any, *, ip: str | None = None) -> httpx.Response:
    if ip is None:
        return await env.client.post(REQUEST, json=body)
    return await _from_ip(env, ip, "POST", REQUEST, json=body)


async def _post_confirm(env: ApiEnv, token: str, *, ip: str | None = None) -> httpx.Response:
    body = {"token": token}
    if ip is None:
        return await env.client.post(CONFIRM, json=body)
    return await _from_ip(env, ip, "POST", CONFIRM, json=body)


def _headers_of(response: httpx.Response) -> list[tuple[str, str]]:
    return list(response.headers.multi_items())


class _BrokenMailer:
    """SMTP недоступен: исключение содержит адрес, чтобы утечка в лог была видна тесту."""

    def send(self, message: MailMessage) -> None:
        raise OSError(f"smtp refused {message.to}")


async def _post_with_log(env: ApiEnv, log: list[str], body: Any, ip: str) -> httpx.Response:
    """Запрос через ASGI-обёртку: ``response`` попадает в ``log`` при последнем фрагменте тела.

    Обёртка только смотрит на сообщения ``send``; приложение и его ответ не меняются.
    """

    async def app(scope: Any, receive: Any, send: Any) -> None:
        async def logged_send(message: Any) -> None:
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                log.append("response")
            await send(message)

        await env.app(scope, receive, logged_send)

    transport = httpx.ASGITransport(app=app, client=(ip, 40000))
    async with httpx.AsyncClient(transport=transport, base_url=env.base_url) as client:
        return await client.post(REQUEST, json=body)


@pytest_asyncio.fixture
async def reg_ws(reset_api_env: ApiEnv) -> WorkspaceRow:
    """Ровно одно пространство на тест (RG-9): без него регистрация отвечает 404."""
    return await new_workspace(reset_api_env)


# --- AC-1: функция выключена (SMTP не настроен) ------------------------------------------


async def test_019_ac1_disabled_request_and_confirm_are_404(api_env: ApiEnv) -> None:
    request = await api_env.client.post(REQUEST, json=_body("off@example.test"))
    assert request.status_code == 404
    assert code_of(request) == "feature_disabled"
    confirm = await api_env.client.post(CONFIRM, json={"token": "x" * 43})
    assert confirm.status_code == 404
    assert code_of(confirm) == "feature_disabled"
    assert api_env.app.state.mailer is None
    assert await _request_count(api_env, "off@example.test") == 0


# --- RG-9: пространство пилота ровно одно ---------------------------------------------


async def test_019_rg9_zero_workspaces_is_404_feature_disabled(reset_api_env: ApiEnv) -> None:
    env = reset_api_env
    request = await env.client.post(REQUEST, json=_body("nows@example.test"))
    assert (request.status_code, code_of(request)) == (404, "feature_disabled")
    confirm = await env.client.post(CONFIRM, json={"token": "x" * 43})
    assert (confirm.status_code, code_of(confirm)) == (404, "feature_disabled")
    assert _mails(env) == []


async def test_019_rg9_two_workspaces_is_404_feature_disabled(reset_api_env: ApiEnv) -> None:
    env = reset_api_env
    await new_workspace(env)
    await new_workspace(env)
    request = await env.client.post(REQUEST, json=_body("two@example.test"))
    assert (request.status_code, code_of(request)) == (404, "feature_disabled")
    confirm = await env.client.post(CONFIRM, json={"token": "x" * 43})
    assert (confirm.status_code, code_of(confirm)) == (404, "feature_disabled")
    assert _mails(env) == []
    assert await _request_count(env, "two@example.test") == 0


# --- общие ошибки формата (схема, JSON, Origin) ---------------------------------------


async def test_019_request_schema_and_json_errors(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv
) -> None:
    env = reset_api_env
    for body in (
        _body("a@example.test", extra=1),
        {k: v for k, v in _body("a@example.test").items() if k != "login"},
        _body("a@example.test", password=5),
    ):
        response = await env.client.post(REQUEST, json=body)
        assert (response.status_code, code_of(response)) == (422, "validation_error")
    # одиночный суррогат: httpx не кодирует его в json=, поэтому тело — ASCII-JSON с \ud800
    lone = json.dumps(_body("a@example.test", password="\ud800" + "x" * 15)).encode("ascii")
    response = await env.client.post(
        REQUEST, content=lone, headers={"Content-Type": "application/json"}
    )
    assert (response.status_code, code_of(response)) == (422, "validation_error")
    broken = await env.client.post(
        REQUEST, content=b'{"email": "a', headers={"Content-Type": "application/json"}
    )
    assert (broken.status_code, code_of(broken)) == (400, "bad_request")
    assert _mails(env) == []


async def test_019_confirm_schema_and_json_errors(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv
) -> None:
    env = reset_api_env
    for body in ({"token": "x" * 43, "extra": 1}, {}, {"token": "x" * 129}):
        response = await env.client.post(CONFIRM, json=body)
        assert (response.status_code, code_of(response)) == (422, "validation_error"), body
    broken = await env.client.post(
        CONFIRM, content=b'{"token": "', headers={"Content-Type": "application/json"}
    )
    assert (broken.status_code, code_of(broken)) == (400, "bad_request")


async def test_019_request_and_confirm_foreign_origin_is_403(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv
) -> None:
    env = reset_api_env
    foreign = {"Origin": "http://evil.example"}
    request = await env.client.post(REQUEST, json=_body("o@example.test"), headers=foreign)
    assert (request.status_code, code_of(request)) == (403, "origin_mismatch")
    confirm = await env.client.post(CONFIRM, json={"token": "x" * 43}, headers=foreign)
    assert (confirm.status_code, code_of(confirm)) == (403, "origin_mismatch")
    assert _mails(env) == []


# --- AC-4: адрес ----------------------------------------------------------------------


async def test_019_ac4_bad_email_is_422_email_invalid(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv
) -> None:
    env = reset_api_env
    for address in ("", "a" * 255, "no-at-sign.example.test"):
        response = await env.client.post(REQUEST, json=_body(address))
        assert (response.status_code, code_of(response)) == (422, "email_invalid"), address
    assert _mails(env) == []


def _address_of_length(total: int) -> str:
    """Адрес ровно ``total`` символов с одним ``@`` и метками домена по 63 символа и меньше."""
    address = "a" * 64 + "@" + "b" * 63 + "." + "c" * 63 + "." + "d" * (total - 65 - 128)
    assert len(address) == total
    return address


async def test_019_ac4_email_length_254_accepted_255_invalid(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv
) -> None:
    env = reset_api_env
    at_limit, over_limit = _address_of_length(254), _address_of_length(255)
    accepted = await _from_ip(env, _ip(1), "POST", REQUEST, json=_body(at_limit))
    assert (accepted.status_code, accepted.json()) == (200, ACCEPTED)
    rejected = await _from_ip(env, _ip(2), "POST", REQUEST, json=_body(over_limit))
    assert (rejected.status_code, code_of(rejected)) == (422, "email_invalid")
    assert [m.to for m in _mails(env)] == [at_limit]


# --- AC-5: нормализация адреса ----------------------------------------------------------


async def test_019_ac5_address_is_trimmed_and_lowered_before_mail(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv
) -> None:
    env = reset_api_env
    response = await env.client.post(REQUEST, json=_body(" New@Example.RU "))
    assert (response.status_code, response.json()) == (200, ACCEPTED)
    mails = _mails(env)
    assert len(mails) == 1
    assert mails[0].to == "new@example.ru"
    assert mails[0].subject == MAIL_SUBJECT


async def test_019_ac5_taken_check_ignores_case_and_spaces(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv
) -> None:
    env = reset_api_env
    await env.new_user(workspace=reg_ws, role="user", email="new@example.ru")
    response = await env.client.post(REQUEST, json=_body(" NEW@example.RU "))
    assert (response.status_code, response.json()) == (200, ACCEPTED)
    assert _mails(env) == []


# --- AC-6: домены не фильтруются --------------------------------------------------------


async def test_019_ac6_any_domain_gets_mail(reg_ws: WorkspaceRow, reset_api_env: ApiEnv) -> None:
    env = reset_api_env
    addresses = ["a@leggent.ru", "b@other.ru", "c@mail.example"]
    for address in addresses:
        response = await env.client.post(REQUEST, json=_body(address))
        assert (response.status_code, response.json()) == (200, ACCEPTED)
    assert [m.to for m in _mails(env)] == addresses


# --- AC-7: единый ответ, побайтно и по времени -------------------------------------------


async def test_019_ac7_four_variants_identical_bytes_and_close_medians(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv
) -> None:
    env = reset_api_env
    await env.new_user(workspace=reg_ws, role="user", email="active@example.test")
    await env.new_user(workspace=reg_ws, role="user", email="blocked@example.test", blocked=True)
    variants = {
        "free": "free@example.test",
        "active": "active@example.test",
        "blocked": "blocked@example.test",
        "pending": "pending@example.test",
    }
    # Неподтверждённая заявка по адресу «pending» уже есть до замеров.
    warm = await _from_ip(env, _ip(0), "POST", REQUEST, json=_body(variants["pending"]))
    assert (warm.status_code, warm.json()) == (200, ACCEPTED)
    responses: list[httpx.Response] = []
    samples: dict[str, list[float]] = {name: [] for name in variants}
    n = 0
    for _ in range(20):
        for name, address in variants.items():
            n += 1
            started = time.perf_counter()
            response = await _from_ip(env, _ip(n), "POST", REQUEST, json=_body(address))
            samples[name].append(time.perf_counter() - started)
            responses.append(response)
            assert (response.status_code, response.json()) == (200, ACCEPTED), name
    first = responses[0]
    for other in responses:
        assert other.status_code == first.status_code
        assert other.content == first.content
        assert _headers_of(other) == _headers_of(first)
    # письмо уходит только на свободный адрес и на адрес с неподтверждённой заявкой
    sent_to = [m.to for m in _mails(env)]
    assert sent_to.count("free@example.test") == 20
    assert sent_to.count("pending@example.test") == 21  # 1 прогрев + 20
    assert "active@example.test" not in sent_to
    assert "blocked@example.test" not in sent_to
    medians = {name: statistics.median(values) for name, values in samples.items()}
    print(f"AC-7 medians (s): {medians}")
    spread = max(medians.values()) - min(medians.values())
    assert spread <= 0.2, medians


async def test_019_ac7_each_median_response_time_within_200ms(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv
) -> None:
    """Абсолютный порог: медиана каждого варианта не больше 200 мс (тестовые параметры Argon2)."""
    env = reset_api_env
    await env.new_user(workspace=reg_ws, role="user", email="timed@example.test")
    samples: dict[str, list[float]] = {"free": [], "taken": []}
    counter = 0
    for n in range(20):
        for name, address in (("free", f"f{n}@example.test"), ("taken", "timed@example.test")):
            counter += 1
            started = time.perf_counter()
            response = await _from_ip(
                env, _ip(1000 + counter), "POST", REQUEST, json=_body(address)
            )
            samples[name].append(time.perf_counter() - started)
            assert response.status_code == 200
    medians = {name: statistics.median(values) for name, values in samples.items()}
    print(f"AC-7 absolute medians (s): {medians}")
    for name, value in medians.items():
        assert value <= 0.2, name


async def test_019_ac7_hash_runs_once_for_taken_and_free_address(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Хеш пароля считается ровно один раз и для занятого, и для свободного адреса (AC-7).

    Замер времени этого не ловит: CHEAP_ARGON2 хеширует за ~0.4 мс. Поэтому счётчик вызовов
    ``hash_in_thread`` в модуле, где его вызывает домен (``app.domain.auth.registration``).
    """
    env = reset_api_env
    await env.new_user(workspace=reg_ws, role="user", email="taken@example.test")
    real_hash = registration_domain.hash_in_thread
    calls: list[str] = []

    async def spy_hash(hasher: Any, password: str) -> str:
        calls.append("hash")
        return await real_hash(hasher, password)

    monkeypatch.setattr(registration_domain, "hash_in_thread", spy_hash)
    per_request: dict[str, int] = {}
    for n, address in enumerate(("free@example.test", "taken@example.test")):
        before = len(calls)
        response = await _from_ip(env, _ip(n), "POST", REQUEST, json=_body(address))
        assert (response.status_code, response.json()) == (200, ACCEPTED), address
        per_request[address] = len(calls) - before
    assert per_request == {"free@example.test": 1, "taken@example.test": 1}


async def test_019_ac7_mail_leaves_after_response_and_commit_only_for_free(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Письмо уходит фоновой задачей после ответа и после COMMIT, и только на свободный адрес.

    Журнал порядка: ``commit`` (слушатель ``after_commit`` класса ``Session``), ``response``
    (конец тела ответа в обёртке ASGI), ``deliver`` (вызов ``deliver`` из роутера).
    """
    env = reset_api_env
    await env.new_user(workspace=reg_ws, role="user", email="taken@example.test")
    log: list[str] = []
    real_deliver = registration_api.deliver

    async def spy_deliver(mailer: Any, message: MailMessage) -> None:
        log.append("deliver")
        await real_deliver(mailer, message)

    def on_commit(_session: Session) -> None:
        log.append("commit")

    monkeypatch.setattr(registration_api, "deliver", spy_deliver)
    event.listen(Session, "after_commit", on_commit)
    try:
        taken = await _post_with_log(env, log, _body("taken@example.test"), _ip(1))
        taken_log = list(log)
        log.clear()
        free = await _post_with_log(env, log, _body("free@example.test"), _ip(2))
        free_log = list(log)
    finally:
        event.remove(Session, "after_commit", on_commit)
    assert (taken.status_code, taken.json()) == (200, ACCEPTED)
    assert (free.status_code, free.json()) == (200, ACCEPTED)
    assert "deliver" not in taken_log
    assert free_log.count("deliver") == 1
    deliver_at = free_log.index("deliver")
    assert free_log.index("response") < deliver_at, free_log
    assert max(i for i, name in enumerate(free_log) if name == "commit") < deliver_at, free_log
    assert [m.to for m in _mails(env)] == ["free@example.test"]


async def test_019_smtp_failure_same_answer_and_no_address_in_log(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv, caplog: pytest.LogCaptureFixture
) -> None:
    """Отказ SMTP не меняет ответ (FR-4) и не выводит адрес в лог (NFR-1)."""
    env = reset_api_env
    caplog.set_level(logging.DEBUG)
    healthy = await _from_ip(env, _ip(1), "POST", REQUEST, json=_body("ok@example.test"))
    assert (healthy.status_code, healthy.json()) == (200, ACCEPTED)
    env.app.state.mailer = _BrokenMailer()
    broken = await _from_ip(env, _ip(2), "POST", REQUEST, json=_body("smtp@example.test"))
    assert (broken.status_code, broken.json()) == (200, ACCEPTED)
    assert broken.content == healthy.content
    assert _headers_of(broken) == _headers_of(healthy)
    assert "mail delivery failed: OSError" in caplog.text  # отказ действительно произошёл
    assert "smtp@example.test" not in caplog.text
    assert all("smtp@example.test" not in r.getMessage() for r in caplog.records)


# --- AC-8: письмо, токен и хранилище ---------------------------------------------------


async def test_019_ac8_one_mail_with_link_ttl_and_warning(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv
) -> None:
    env = reset_api_env
    response = await env.client.post(REQUEST, json=_body("new@example.test"))
    assert (response.status_code, response.json()) == (200, ACCEPTED)
    mails = _mails(env)
    assert len(mails) == 1
    mail = mails[0]
    assert mail.to == "new@example.test"
    assert mail.subject == MAIL_SUBJECT
    assert LINK_PREFIX in mail.body
    assert "Ссылка действует 30 минут." in mail.body
    assert "Если вы не регистрировались, ничего не делайте" in mail.body
    for secret in (PW, LOGIN, FIRST, LAST):
        assert secret not in mail.body


async def test_019_ac8_storage_keeps_hashes_only(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv
) -> None:
    env = reset_api_env
    await env.client.post(REQUEST, json=_body("store@example.test"))
    token = _last_token(env)
    rows = await _rows(
        env,
        "SELECT token_hash, password_hash FROM registration_request WHERE email = :e",
        e="store@example.test",
    )
    assert len(rows) == 1
    token_hash, password_hash = bytes(rows[0][0]), str(rows[0][1])
    assert token_hash == hashlib.sha256(token.encode()).digest()
    assert token.encode() not in token_hash
    assert password_hash.startswith("$argon2id$")
    assert PW not in password_hash


# --- AC-9: повторная заявка отзывает токен первой ---------------------------------------


async def test_019_ac9_second_request_revokes_first_token(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv
) -> None:
    env = reset_api_env
    await env.client.post(REQUEST, json=_body("twice@example.test"))
    first = _last_token(env)
    await env.client.post(REQUEST, json=_body("twice@example.test"))
    second = _last_token(env)
    assert first != second
    stale = await _post_confirm(env, first)
    assert (stale.status_code, code_of(stale)) == (400, "registration_token_invalid")
    fresh = await _post_confirm(env, second)
    assert fresh.status_code == 204
    assert await _accounts(env, "twice@example.test") == 1


# --- AC-10: срок 30 минут -------------------------------------------------------------


async def test_019_ac10_token_expires_after_30_minutes(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv
) -> None:
    env = reset_api_env
    await env.client.post(REQUEST, json=_body("exp@example.test"))
    token = _last_token(env)
    env.clock.advance(timedelta(minutes=30, seconds=1))
    late = await _post_confirm(env, token)
    assert (late.status_code, code_of(late)) == (400, "registration_token_invalid")
    assert await _accounts(env, "exp@example.test") == 0

    await env.client.post(REQUEST, json=_body("exp2@example.test"))
    token2 = _last_token(env)
    env.clock.advance(timedelta(minutes=29, seconds=59))
    in_time = await _post_confirm(env, token2)
    assert in_time.status_code == 204
    assert await _accounts(env, "exp2@example.test") == 1


# --- AC-11: занятый адрес (активная и заблокированная запись) --------------------------


async def test_019_ac11_taken_address_same_answer_no_mail_no_account(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv
) -> None:
    env = reset_api_env
    await env.new_user(workspace=reg_ws, role="user", email="active@example.test")
    await env.new_user(workspace=reg_ws, role="user", email="blocked@example.test", blocked=True)
    before = await _account_count(env)
    free = await env.client.post(REQUEST, json=_body("free@example.test"))
    active = await env.client.post(REQUEST, json=_body("active@example.test"))
    blocked = await env.client.post(REQUEST, json=_body(" Blocked@Example.TEST "))
    for response in (free, active, blocked):
        assert (response.status_code, response.json()) == (200, ACCEPTED)
        assert response.content == free.content
        assert _headers_of(response) == _headers_of(free)
    assert await _account_count(env) == before
    assert [m.to for m in _mails(env)] == ["free@example.test"]


# --- AC-12: неподтверждённая заявка не видна и не входит ---------------------------------


async def test_019_ac12_unconfirmed_request_is_invisible_and_cannot_log_in(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv
) -> None:
    env = reset_api_env
    _, (ta_token,) = await seed(env, reg_ws, "tech_admin")
    accepted = await env.client.post(REQUEST, json=_body("pending@example.test", login="newbie"))
    assert (accepted.status_code, accepted.json()) == (200, ACCEPTED)
    listed = await env.client.get(ADMIN_USERS, headers=env.auth(ta_token))
    assert listed.status_code == 200
    assert "newbie" not in [item["login"] for item in listed.json()["items"]]
    login = await env.login("newbie", PW)
    assert (login.status_code, code_of(login)) == (401, "invalid_credentials")


# --- AC-13: подтверждение создаёт учётную запись без роли ------------------------------


async def test_019_ac13_confirm_creates_account_without_role_then_reset_works(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv
) -> None:
    env = reset_api_env
    address = "anna@example.test"
    await env.client.post(REQUEST, json=_body(address, login="Anna.Petrova"))
    token = _last_token(env)
    response = await _post_confirm(env, token)
    assert response.status_code == 204
    assert response.content == b""
    assert "set-cookie" not in response.headers

    rows = await _rows(
        env,
        "SELECT id, login, login_display, first_name, last_name, self_registered, "
        "must_change_password FROM app_user WHERE email = :e",
        e=address,
    )
    assert len(rows) == 1
    user_id, login, display, first, last, self_registered, must_change = rows[0]
    assert (login, display) == ("anna.petrova", "Anna.Petrova")
    assert (first, last) == (FIRST, LAST)
    assert self_registered is True
    assert must_change is False
    members = await _rows(
        env,
        "SELECT workspace_id, role FROM workspace_member WHERE user_id = :u",
        u=user_id,
    )
    assert [(row[0], row[1]) for row in members] == [(reg_ws.id, None)]
    projects = await _rows(env, "SELECT count(*) FROM project_member WHERE user_id = :u", u=user_id)
    assert int(projects[0][0]) == 0
    assert await env.session_ids(user_id) == []

    assert (await env.login("Anna.Petrova", PW)).status_code == 200
    reset = await env.client.post(RESET_REQUEST, json={"email": address})
    assert reset.status_code == 200
    assert _mails(env)[-1].to == address


# --- AC-14: адрес занят между заявкой и подтверждением ----------------------------------


async def test_019_ac14_address_taken_by_admin_blocks_confirm(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv
) -> None:
    env = reset_api_env
    _, (ta_token,) = await seed(env, reg_ws, "tech_admin")
    victim = await env.new_user(workspace=reg_ws, role="user")
    await env.client.post(REQUEST, json=_body("clash@example.test", login="clashuser"))
    token = _last_token(env)
    moved = await env.client.put(
        f"{ADMIN_USERS}/{victim.id}/email",
        json={"email": "clash@example.test"},
        headers=env.auth(ta_token),
    )
    assert moved.status_code == 200
    response = await _post_confirm(env, token)
    assert (response.status_code, code_of(response)) == (400, "registration_token_invalid")
    assert await _accounts(env, "clash@example.test") == 1
    clashed = await _rows(env, "SELECT count(*) FROM app_user WHERE login = 'clashuser'")
    assert int(clashed[0][0]) == 0


# --- AC-15: пароль -----------------------------------------------------------------------


async def test_019_ac15_short_and_common_passwords_are_422_no_mail(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv
) -> None:
    env = reset_api_env
    short = await env.client.post(REQUEST, json=_body("pw1@example.test", password="Zq7-rt5-yu7"))
    assert (short.status_code, code_of(short)) == (422, "password_too_short")
    common = await env.client.post(REQUEST, json=_body("pw2@example.test", password="unbelievable"))
    assert (common.status_code, code_of(common)) == (422, "password_too_common")
    assert _mails(env) == []


async def test_019_ac15_twelve_chars_not_common_is_accepted(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv
) -> None:
    env = reset_api_env
    response = await env.client.post(
        REQUEST, json=_body("pw3@example.test", password="Qx7!vb4Lp9Wm")
    )
    assert (response.status_code, response.json()) == (200, ACCEPTED)
    assert len(_mails(env)) == 1


# --- AC-16: повтор и отсутствие сессии ---------------------------------------------------


async def test_019_ac16_confirm_has_no_cookie_and_repeat_is_400(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv
) -> None:
    env = reset_api_env
    await env.client.post(REQUEST, json=_body("once@example.test"))
    token = _last_token(env)
    first = await _post_confirm(env, token)
    assert (first.status_code, first.content) == (204, b"")
    assert "set-cookie" not in first.headers
    user = await _rows(env, "SELECT id FROM app_user WHERE email = :e", e="once@example.test")
    assert await env.session_ids(user[0][0]) == []
    again = await _post_confirm(env, token)
    assert (again.status_code, code_of(again)) == (400, "registration_token_invalid")


# --- AC-18 и RG-5: лимит заявок с одного IP ---------------------------------------------


async def test_019_ac18_ten_per_ip_then_429_same_for_taken_address(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv
) -> None:
    env = reset_api_env
    ip = "203.0.113.10"
    await env.new_user(workspace=reg_ws, role="user", email="taken@example.test")
    for n in range(10):
        response = await _from_ip(env, ip, "POST", REQUEST, json=_body(f"u{n}@example.test"))
        assert (response.status_code, response.json()) == (200, ACCEPTED), n
    free = await _from_ip(env, ip, "POST", REQUEST, json=_body("u10@example.test"))
    taken = await _from_ip(env, ip, "POST", REQUEST, json=_body("taken@example.test"))
    for response in (free, taken):
        assert (response.status_code, code_of(response)) == (429, "rate_limited")
    assert free.content == taken.content
    other = await _from_ip(env, "203.0.113.11", "POST", REQUEST, json=_body("other@example.test"))
    assert (other.status_code, other.json()) == (200, ACCEPTED)
    assert len(_mails(env)) == 11
    env.clock.advance(timedelta(minutes=61))
    later = await _from_ip(env, ip, "POST", REQUEST, json=_body("u11@example.test"))
    assert (later.status_code, later.json()) == (200, ACCEPTED)


async def test_019_ac18_ninth_then_tenth_is_accepted(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv
) -> None:
    env = reset_api_env
    ip = "203.0.113.12"
    for n in range(9):
        assert (
            await _from_ip(env, ip, "POST", REQUEST, json=_body(f"n{n}@example.test"))
        ).status_code == 200
    tenth = await _from_ip(env, ip, "POST", REQUEST, json=_body("n9@example.test"))
    assert (tenth.status_code, tenth.json()) == (200, ACCEPTED)


async def test_019_ac18_same_address_counts_each_request(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv
) -> None:
    env = reset_api_env
    ip = "203.0.113.13"
    for _ in range(10):
        response = await _from_ip(env, ip, "POST", REQUEST, json=_body("same@example.test"))
        assert (response.status_code, response.json()) == (200, ACCEPTED)
    eleventh = await _from_ip(env, ip, "POST", REQUEST, json=_body("same@example.test"))
    assert (eleventh.status_code, code_of(eleventh)) == (429, "rate_limited")
    assert len(_mails(env)) == 10


async def test_019_ac18_counters_store_no_plain_ip(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv
) -> None:
    env = reset_api_env
    ip = "203.0.113.14"
    await _from_ip(env, ip, "POST", REQUEST, json=_body("h@example.test"))
    rows = await _rows(env, "SELECT scope, key_hash FROM registration_attempt")
    assert rows
    for _scope, key_hash in rows:
        raw = bytes(key_hash)
        assert len(raw) == 32
        assert ip.encode() not in raw
        assert ip not in raw.hex()


async def test_019_rg5_422_requests_count_toward_ip_limit(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv
) -> None:
    env = reset_api_env
    ip = "203.0.113.20"
    await env.new_user(workspace=reg_ws, role="user", login="takenuser")
    for n in range(10):
        if n % 2:
            body = _body(f"busy{n}@example.test", login="takenuser")  # login_taken
            code = "login_taken"
        else:
            body = _body("not-an-address", login=f"probe{n}")  # email_invalid
            code = "email_invalid"
        response = await _from_ip(env, ip, "POST", REQUEST, json=body)
        assert (response.status_code, code_of(response)) == (422, code), n
    eleventh = await _from_ip(env, ip, "POST", REQUEST, json=_body("good@example.test"))
    assert (eleventh.status_code, code_of(eleventh)) == (429, "rate_limited")
    assert _mails(env) == []


# --- AC-19: журнал аудита ----------------------------------------------------------------


async def test_019_ac19_one_self_registered_event_after_confirm_only(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv
) -> None:
    env = reset_api_env
    await env.client.post(REQUEST, json=_body("audit@example.test", login="auditor"))
    await _post_confirm(env, "x" * 43)  # неверный токен: событий быть не должно
    assert [
        r for r in await events(env, workspace_id=reg_ws.id) if r[3] == "user.self_registered"
    ] == []
    await env.client.post(REQUEST, json=_body("audit2@example.test", login="auditor2"))
    token = _last_token(env)
    assert (await _post_confirm(env, token)).status_code == 204
    rows = [r for r in await events(env, workspace_id=reg_ws.id) if r[3] == "user.self_registered"]
    assert len(rows) == 1
    user = await _rows(env, "SELECT id FROM app_user WHERE email = :e", e="audit2@example.test")
    _id, actor_id, entity_id, _action, details, changed = rows[0]
    assert actor_id == entity_id == user[0][0]
    assert details is None
    assert list(changed or []) == []


# --- AC-27: логин раньше адреса ---------------------------------------------------------


async def test_019_ac27_taken_login_same_answer_for_free_and_taken_address(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv
) -> None:
    env = reset_api_env
    await env.new_user(workspace=reg_ws, role="user", login="takenlogin")
    await env.new_user(workspace=reg_ws, role="user", login="owner", email="owner@example.test")
    free = await env.client.post(REQUEST, json=_body("free@example.test", login="takenlogin"))
    taken = await env.client.post(REQUEST, json=_body("owner@example.test", login="takenlogin"))
    for response in (free, taken):
        assert (response.status_code, code_of(response)) == (422, "login_taken")
    assert free.content == taken.content
    assert _mails(env) == []


async def test_019_ac27_login_case_is_ignored(reg_ws: WorkspaceRow, reset_api_env: ApiEnv) -> None:
    env = reset_api_env
    await env.new_user(workspace=reg_ws, role="user", login="ab_c")
    response = await env.client.post(REQUEST, json=_body("case@example.test", login="Ab_c"))
    assert (response.status_code, code_of(response)) == (422, "login_taken")
    assert _mails(env) == []


# --- AC-28: логин занят после заявки ----------------------------------------------------


async def test_019_ac28_login_taken_after_request_gives_409_then_400(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv
) -> None:
    env = reset_api_env
    _, (ta_token,) = await seed(env, reg_ws, "tech_admin")
    await env.client.post(REQUEST, json=_body("late@example.test", login="newuser"))
    token = _last_token(env)
    created = await env.client.post(
        ADMIN_USERS,
        json={"login": "newuser", "first_name": FIRST, "last_name": LAST, OTP_FIELD: OTP},
        headers=env.auth(ta_token),
    )
    assert created.status_code == 201
    first = await _post_confirm(env, token)
    assert (first.status_code, code_of(first)) == (409, "login_taken")
    assert await _accounts(env, "late@example.test") == 0
    assert await _request_count(env, "late@example.test") == 0
    second = await _post_confirm(env, token)
    assert (second.status_code, code_of(second)) == (400, "registration_token_invalid")


# --- AC-29: имя и фамилия ---------------------------------------------------------------


async def test_019_ac29_bad_names_are_422_with_field_code_no_mail(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv
) -> None:
    env = reset_api_env
    cases = (
        ({"first_name": ""}, "first_name_invalid"),
        ({"first_name": "   "}, "first_name_invalid"),
        ({"first_name": "А" * 101}, "first_name_invalid"),
        ({"last_name": "   "}, "last_name_invalid"),
    )
    for override, code in cases:
        response = await env.client.post(REQUEST, json=_body("name@example.test", **override))
        assert (response.status_code, code_of(response)) == (422, code), override
    assert _mails(env) == []


async def test_019_ac29_trimmed_name_and_100_char_surname_accepted(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv
) -> None:
    env = reset_api_env
    response = await env.client.post(
        REQUEST, json=_body("long@example.test", first_name=f" {FIRST} ", last_name="Я" * 100)
    )
    assert (response.status_code, response.json()) == (200, ACCEPTED)
    rows = await _rows(
        env,
        "SELECT first_name, last_name FROM registration_request WHERE email = :e",
        e="long@example.test",
    )
    assert (rows[0][0], rows[0][1]) == (FIRST, "Я" * 100)


async def test_019_ac29_first_name_100_accepted_101_invalid(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv
) -> None:
    env = reset_api_env
    at_limit = await _from_ip(
        env, _ip(1), "POST", REQUEST, json=_body("n100@example.test", first_name="Я" * 100)
    )
    assert (at_limit.status_code, at_limit.json()) == (200, ACCEPTED)
    over = await _from_ip(
        env, _ip(2), "POST", REQUEST, json=_body("n101@example.test", first_name="Я" * 101)
    )
    assert (over.status_code, code_of(over)) == (422, "first_name_invalid")
    assert [m.to for m in _mails(env)] == ["n100@example.test"]


# --- RG-7: граница схемы 1024 (домен отвечает кодом поля), 1025 — validation_error ----------


async def test_019_schema_limit_1024_reaches_domain_1025_is_validation_error(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv
) -> None:
    env = reset_api_env
    fields = (
        ("email", "email_invalid"),
        ("first_name", "first_name_invalid"),
        ("last_name", "last_name_invalid"),
        ("login", "login_invalid"),
    )
    n = 0
    for field, domain_code in fields:
        for size, expected in ((1024, domain_code), (1025, "validation_error")):
            n += 1
            if field == "email":
                body = _body(_address_of_length(size))
            elif field == "login":
                body = _body("bound@example.test", login="a" * size)
            else:
                body = _body("bound@example.test", **{field: "А" * size})
            response = await _from_ip(env, _ip(n), "POST", REQUEST, json=body)
            assert (response.status_code, code_of(response)) == (422, expected), (field, size)
    assert _mails(env) == []


# --- AC-38: лимиты подтверждения --------------------------------------------------------


async def test_019_ac38_sixth_confirm_on_nonexistent_link_is_429(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv
) -> None:
    env = reset_api_env
    token = secrets.token_urlsafe(32)
    for _ in range(5):
        response = await _post_confirm(env, token, ip="203.0.113.30")
        assert (response.status_code, code_of(response)) == (400, "registration_token_invalid")
    sixth = await _post_confirm(env, token, ip="203.0.113.30")
    assert (sixth.status_code, code_of(sixth)) == (429, "rate_limited")
    assert await _account_count(env) == 0


async def test_019_ac38_sixth_confirm_on_used_link_is_429_account_kept(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv
) -> None:
    env = reset_api_env
    await env.client.post(REQUEST, json=_body("used@example.test"))
    token = _last_token(env)
    assert (await _post_confirm(env, token, ip="203.0.113.31")).status_code == 204
    for _ in range(4):
        response = await _post_confirm(env, token, ip="203.0.113.31")
        assert (response.status_code, code_of(response)) == (400, "registration_token_invalid")
    sixth = await _post_confirm(env, token, ip="203.0.113.31")
    assert (sixth.status_code, code_of(sixth)) == (429, "rate_limited")
    assert await _accounts(env, "used@example.test") == 1


async def test_019_ac38_twenty_confirms_per_ip_then_429_no_plain_secrets(
    reg_ws: WorkspaceRow, reset_api_env: ApiEnv
) -> None:
    env = reset_api_env
    ip = "203.0.113.32"
    tokens = [secrets.token_urlsafe(32) for _ in range(21)]
    for token in tokens[:20]:
        response = await _post_confirm(env, token, ip=ip)
        assert (response.status_code, code_of(response)) == (400, "registration_token_invalid")
    twenty_first = await _post_confirm(env, tokens[20], ip=ip)
    assert (twenty_first.status_code, code_of(twenty_first)) == (429, "rate_limited")
    assert await _account_count(env) == 0
    rows = await _rows(env, "SELECT key_hash FROM registration_attempt")
    assert rows
    for (key_hash,) in rows:
        raw = bytes(key_hash)
        assert len(raw) == 32
        assert ip.encode() not in raw
        assert all(token.encode() not in raw for token in tokens)
