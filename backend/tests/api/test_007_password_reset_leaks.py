"""R7-T13: сброс пароля не пропускает токен, пароль и email (AC-12, NFR-1, FR-15).

Сценарий: request -> confirm (400, 422, 204) -> login -> ``GET /admin/audit`` от технического
администратора. Образец: ``test_password_leaks.py``. Отдельно: ошибка SMTP (исключение с email и
токеном в тексте) -> в логе только имя типа, ответ ``/request`` прежний.
"""

import base64
import hashlib
import logging
from typing import Any

import httpx
from sqlalchemy import text

from app.core.mail import MailMessage
from tests.admin_support import admin_in_new_workspace, events, seed
from tests.conftest import ApiEnv

REQUEST = "/api/v1/auth/password-reset/request"
CONFIRM = "/api/v1/auth/password-reset/confirm"
AUDIT = "/api/v1/admin/audit"
LINK_PREFIX = "https://tracker.example.test/password-reset/confirm#token="
OLD_PW = "Old-Reset-Pa55phrase-3318"
NEW_PW = "New-Reset-Pa55phrase-9042"
WEAK_PW = "Sh0rt-Rs-1"  # 10 символов
EMAIL = "leak.person@example.test"
REQUESTED = "user.password_reset_requested"
COMPLETED = "user.password_reset_completed"


def _token_from_mail(env: ApiEnv) -> str:
    sent = env.app.state.mailer.sent
    assert len(sent) == 1
    return str(sent[0].body.split(LINK_PREFIX, 1)[1].split()[0])


def _forms(token: str) -> list[str]:
    digest = hashlib.sha256(token.encode()).digest()
    return [
        token,
        digest.hex(),
        digest.hex().upper(),
        base64.b64encode(digest).decode(),
        base64.urlsafe_b64encode(digest).decode().rstrip("="),
    ]


def _assert_clean(haystack: str, needles: list[str], where: str) -> None:
    for needle in needles:
        assert needle not in haystack, f"{where}: утечка значения (длина {len(needle)})"


async def test_007_ac12_reset_scenario_leaks_nothing(reset_api_env: ApiEnv, caplog: Any) -> None:
    env = reset_api_env
    caplog.set_level(logging.DEBUG)
    ws, _admin, admin_token = await admin_in_new_workspace(env)
    user, _ = await seed(env, ws, "user", password=OLD_PW)
    await env.execute(
        text("UPDATE app_user SET email = :e WHERE id = :u").bindparams(e=EMAIL, u=user.id)
    )

    responses: list[httpx.Response] = []
    request = await env.client.post(REQUEST, json={"email": EMAIL})
    assert request.status_code == 200
    responses.append(request)
    token = _token_from_mail(env)
    assert len(token) >= 40

    bad_token = await env.client.post(
        CONFIRM, json={"token": "no-such-token", "new_password": NEW_PW}
    )
    weak = await env.client.post(CONFIRM, json={"token": token, "new_password": WEAK_PW})
    assert (bad_token.status_code, weak.status_code) == (400, 422)
    done = await env.client.post(CONFIRM, json={"token": token, "new_password": NEW_PW})
    assert done.status_code == 204
    reuse = await env.client.post(CONFIRM, json={"token": token, "new_password": NEW_PW})
    assert reuse.status_code == 400
    old_login = await env.login(user.login, OLD_PW)
    new_login = await env.login(user.login, NEW_PW)
    assert (old_login.status_code, new_login.status_code) == (401, 200)
    responses += [bad_token, weak, done, reuse, old_login, new_login]

    audit = await env.client.get(AUDIT, params={"page_size": 100}, headers=env.auth(admin_token))
    assert audit.status_code == 200, audit.text

    secrets = [EMAIL, OLD_PW, NEW_PW, WEAK_PW, *_forms(token)]
    for response in responses:
        where = f"{response.request.method} {response.request.url.path}"
        _assert_clean(response.text, secrets, where)
        _assert_clean(str(sorted(response.headers.items())), secrets, where + " headers")
    # ответ админке: email допустим (FR-2), остальное нет
    admin_secrets = [s for s in secrets if s != EMAIL]
    _assert_clean(audit.text, admin_secrets, "audit")
    _assert_clean(str(sorted(audit.headers.items())), secrets, "audit headers")
    assert EMAIL not in audit.text  # события сброса не несут адрес и в журнале

    log_haystacks = [caplog.text]
    for record in caplog.records:
        log_haystacks += [record.getMessage(), repr(record.args), str(record.exc_text)]
    assert caplog.records, "лог пуст: проверка бессмысленна"
    for haystack in log_haystacks:
        _assert_clean(haystack, secrets, "caplog")

    # domain_event: ровно два события сброса, без значений
    found = [e for e in await events(env, entity_id=user.id) if e.action in (REQUESTED, COMPLETED)]
    assert [e.action for e in found] == [REQUESTED, COMPLETED]
    assert found[0].actor_id is None
    assert found[1].actor_id == user.id
    rows = await env.execute(
        text(
            "SELECT action, changed_fields, details, changes FROM domain_event "
            "WHERE entity_id = :u AND action IN (:a, :b) ORDER BY id"
        ).bindparams(u=user.id, a=REQUESTED, b=COMPLETED)
    )
    assert rows is not None and len(rows) == 2
    for action, changed_fields, details, changes in rows:
        assert list(changed_fields) == [], action
        assert details is None and changes is None, action
    dump = str(
        await env.execute(
            text("SELECT * FROM domain_event WHERE entity_id = :u").bindparams(u=user.id)
        )
    )
    _assert_clean(dump, secrets, "domain_event")
    entries = [e for e in audit.json()["items"] if e["action"] in (REQUESTED, COMPLETED)]
    assert {e["action"] for e in entries} == {REQUESTED, COMPLETED}


class _FailingMailer:
    def __init__(self) -> None:
        self.calls = 0
        self.token = ""

    def send(self, message: MailMessage) -> None:
        self.calls += 1
        link = message.body.split(LINK_PREFIX, 1)[1].split()[0]
        self.token = link
        raise ConnectionRefusedError(
            f"cannot send to {message.to}: token={link} body={message.body}"
        )


async def test_007_nfr1_smtp_failure_logs_only_exception_type(
    reset_api_env: ApiEnv, caplog: Any
) -> None:
    env = reset_api_env
    caplog.set_level(logging.DEBUG)
    await env.new_user(role="user", email=EMAIL)
    ok = await env.client.post(REQUEST, json={"email": EMAIL})
    token = _token_from_mail(env)
    unknown = await env.client.post(REQUEST, json={"email": "nobody@example.test"})

    failing = _FailingMailer()
    env.app.state.mailer = failing
    caplog.clear()
    failed = await env.client.post(REQUEST, json={"email": EMAIL})
    assert failing.token and failing.calls == 1, (
        "подменённый Mailer не вызван: проверка бессмысленна"
    )
    # единый ответ: статус, тело и заголовки как у успешного и у неизвестного адреса
    assert failed.status_code == ok.status_code == unknown.status_code == 200
    assert failed.json() == ok.json() == unknown.json()

    assert "ConnectionRefusedError" in caplog.text
    secrets = [EMAIL, "example.test", *_forms(token), *_forms(failing.token)]
    _assert_clean(failed.text, secrets, "response")
    _assert_clean(str(sorted(failed.headers.items())), secrets, "headers")
    haystacks = [caplog.text]
    for record in caplog.records:
        haystacks += [record.getMessage(), repr(record.args), str(record.exc_text)]
    for haystack in haystacks:
        _assert_clean(haystack, secrets, "caplog")
        assert "cannot send" not in haystack and LINK_PREFIX not in haystack
