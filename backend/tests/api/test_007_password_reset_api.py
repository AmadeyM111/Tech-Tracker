"""R7-T11: публичный API сброса пароля (FR-3, FR-6, FR-9, NFR-2; AC-2, AC-4, AC-5, AC-10, AC-11).

Контракт (plan §4.4): ``GET /api/v1/auth/password-reset/status`` -> 200 ``{"enabled": bool}``;
``POST .../request`` с ``{email}`` (``extra=forbid``, 1..254) -> 200 ``{"detail": FR-6}``
одинаково для любых случаев; без SMTP -> 404 ``feature_disabled``. Невалидный формат адреса
(plan §4.4, PR-21): схема принимает любую строку 1..254, ответ тот же 200, в лимите учитывается
только IP; 422 только для пустой строки, лишнего поля и неверного типа.
"""

import hashlib
import statistics
import time
from datetime import timedelta
from typing import Any

import httpx
from sqlalchemy import text

from tests.admin_support import code_of
from tests.conftest import ApiEnv

STATUS = "/api/v1/auth/password-reset/status"
REQUEST = "/api/v1/auth/password-reset/request"
CONFIRM = "/api/v1/auth/password-reset/confirm"
NEW_PW = "Brand-new-Pa55phrase-42"
ACCEPTED = {"detail": "Если для этого адреса есть учётная запись, мы отправили письмо со ссылкой."}
LINK_PREFIX = "https://tracker.example.test/password-reset/confirm#token="


async def _post(env: ApiEnv, email: Any, **kwargs: Any) -> httpx.Response:
    return await env.client.post(REQUEST, json={"email": email}, **kwargs)


def _mails(env: ApiEnv) -> list[Any]:
    return list(env.app.state.mailer.sent)


# --- AC-2: функция выключена -------------------------------------------------------------


async def test_007_ac2_status_disabled_without_smtp(api_env: ApiEnv) -> None:
    response = await api_env.client.get(STATUS)
    assert response.status_code == 200
    assert response.json() == {"enabled": False}
    assert "set-cookie" not in response.headers


async def test_007_ac2_request_disabled_is_404_feature_disabled(api_env: ApiEnv) -> None:
    await api_env.new_user(role="user", email="a@example.test")
    response = await _post(api_env, "a@example.test")
    assert response.status_code == 404
    assert code_of(response) == "feature_disabled"


# --- включено: status, формат ответа ----------------------------------------------------


async def test_007_status_enabled_is_public_without_cookie(reset_api_env: ApiEnv) -> None:
    response = await reset_api_env.client.get(STATUS)
    assert response.status_code == 200
    assert response.json() == {"enabled": True}
    assert "set-cookie" not in response.headers


async def test_007_request_response_has_no_set_cookie(reset_api_env: ApiEnv) -> None:
    response = await _post(reset_api_env, "nobody@example.test")
    assert response.status_code == 200
    assert response.json() == ACCEPTED
    assert "set-cookie" not in response.headers


# --- AC-4: одинаковый ответ -------------------------------------------------------------


async def test_007_ac4_response_identical_for_all_cases(reset_api_env: ApiEnv) -> None:
    env = reset_api_env
    await env.new_user(role="user", email="active@example.test")
    noemail = await env.new_user(role="user")  # без email
    rows = await env.execute(
        text("SELECT email FROM app_user WHERE id = :u").bindparams(u=noemail.id)
    )
    assert rows is not None and len(rows) == 1 and rows[0][0] is None
    await env.new_user(role="user", email="blocked@example.test", blocked=True)
    # Активность = не заблокирован И есть членство (PR-2, Q-3); роль не важна. Фабрика всегда
    # создаёт членство, поэтому для случая «без членства» удаляем его явно.
    nomember = await env.new_user(role=None, email="nomember@example.test")
    await env.execute(
        text("DELETE FROM workspace_member WHERE user_id = :u").bindparams(u=nomember.id)
    )
    responses = []
    for address in (
        "active@example.test",
        "unknown@example.test",
        "blocked@example.test",
        "nomember@example.test",
        "not-an-email",
    ):
        env.clock.advance(timedelta(minutes=61))
        responses.append(await _post(env, address))
    first = responses[0]
    for other in responses:
        assert other.status_code == first.status_code == 200
        assert other.content == first.content
        assert other.headers["content-type"] == first.headers["content-type"]
        assert other.headers["content-length"] == first.headers["content-length"]
    assert first.json() == ACCEPTED
    assert len(_mails(env)) == 1  # только активному


async def test_007_ac4_invalid_format_is_same_200_not_422(reset_api_env: ApiEnv) -> None:
    for bad in ("not-an-email", "a@b", "@@", " ", "a" * 254):
        reset_api_env.clock.advance(timedelta(minutes=61))
        response = await _post(reset_api_env, bad)
        assert (response.status_code, response.json()) == (200, ACCEPTED), bad
    assert _mails(reset_api_env) == []


async def test_007_ac4_response_time_within_200ms_median(reset_api_env: ApiEnv) -> None:
    env = reset_api_env
    await env.new_user(role="user", email="active@example.test")
    samples: dict[str, list[float]] = {"active@example.test": [], "unknown@example.test": []}
    for _ in range(20):
        for address, bucket in samples.items():
            env.clock.advance(timedelta(minutes=61))  # окно лимитов не мешает замеру
            started = time.perf_counter()
            response = await _post(env, address)
            bucket.append(time.perf_counter() - started)
            assert (response.status_code, response.json()) == (200, ACCEPTED)
    assert len(_mails(env)) == 20  # ветка «с письмом» действительно выполнялась
    median_mail = statistics.median(samples["active@example.test"])
    median_unknown = statistics.median(samples["unknown@example.test"])
    print(f"median with mail={median_mail:.4f}s unknown={median_unknown:.4f}s")
    assert abs(median_mail - median_unknown) <= 0.2


# --- валидация схемы ---------------------------------------------------------------------


async def test_007_request_schema_validation_422(reset_api_env: ApiEnv) -> None:
    env = reset_api_env
    for body in (
        {"email": "a@example.test", "extra": 1},
        {},
        {"email": ""},
        {"email": 5},
        {"email": "a" * 255},
    ):
        response = await env.client.post(REQUEST, json=body)
        assert response.status_code == 422, body
        assert code_of(response) == "validation_error", body
    assert _mails(env) == []


async def test_007_request_broken_json_is_400(reset_api_env: ApiEnv) -> None:
    response = await reset_api_env.client.post(
        REQUEST, content=b'{"email": "a', headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400
    assert code_of(response) == "bad_request"


async def test_007_request_foreign_origin_is_403(reset_api_env: ApiEnv) -> None:
    await reset_api_env.new_user(role="user", email="a@example.test")
    response = await _post(
        reset_api_env, "a@example.test", headers={"Origin": "http://evil.example"}
    )
    assert (response.status_code, code_of(response)) == (403, "origin_mismatch")
    assert _mails(reset_api_env) == []


# --- AC-5: письмо через HTTP -------------------------------------------------------------


async def test_007_ac5_mail_sent_with_link_and_hashed_token(reset_api_env: ApiEnv) -> None:
    env = reset_api_env
    user = await env.new_user(role="user", email="active@example.test")
    response = await _post(env, "  Active@Example.TEST ")
    assert (response.status_code, response.json()) == (200, ACCEPTED)
    mails = _mails(env)
    assert len(mails) == 1
    mail = mails[0]
    assert mail.to == "active@example.test"
    assert "30 минут" in mail.body
    assert "Если это были не вы" in mail.body or "если это были не вы" in mail.body
    assert LINK_PREFIX in mail.body
    token = mail.body.split(LINK_PREFIX, 1)[1].split()[0]
    assert user.login not in mail.body
    rows = await env.execute(
        text("SELECT token_hash FROM password_reset_token WHERE user_id = :u").bindparams(u=user.id)
    )
    assert rows is not None and len(rows) == 1
    assert bytes(rows[0][0]) == hashlib.sha256(token.encode()).digest()
    assert token.encode() not in bytes(rows[0][0])


# --- AC-10: лимиты через HTTP ------------------------------------------------------------


async def test_007_ac10_fourth_request_same_response_three_mails(reset_api_env: ApiEnv) -> None:
    env = reset_api_env
    await env.new_user(role="user", email="active@example.test")
    responses = [await _post(env, "active@example.test") for _ in range(4)]
    assert {r.status_code for r in responses} == {200}
    assert {r.content for r in responses} == {responses[0].content}
    assert responses[0].json() == ACCEPTED
    assert len(_mails(env)) == 3
    env.clock.advance(timedelta(minutes=61))
    assert (await _post(env, "active@example.test")).json() == ACCEPTED
    assert len(_mails(env)) == 4


# --- AC-11: заблокированный и без членства ----------------------------------------------


async def test_007_ac11_blocked_gets_same_response_no_mail(reset_api_env: ApiEnv) -> None:
    env = reset_api_env
    user = await env.new_user(role="user", email="blocked@example.test", blocked=True)
    response = await _post(env, "blocked@example.test")
    assert (response.status_code, response.json()) == (200, ACCEPTED)
    assert _mails(env) == []
    # токены именно заблокированного пользователя: проверка не зависит от чужих строк таблицы
    rows = await env.execute(
        text("SELECT count(*) FROM password_reset_token WHERE user_id = :u").bindparams(u=user.id)
    )
    assert rows is not None and rows[0][0] == 0


# --- PR-8: X-Forwarded-For не влияет на лимит по IP ---------------------------------------


async def test_007_pr8_forwarded_for_does_not_affect_ip_limit(reset_api_env: ApiEnv) -> None:
    env = reset_api_env
    for n in range(11):
        await env.new_user(role="user", email=f"user{n}@example.test")
    transport = httpx.ASGITransport(app=env.app, client=("203.0.113.7", 4321))
    async with httpx.AsyncClient(transport=transport, base_url=env.base_url) as client:
        responses = [
            await client.post(
                REQUEST,
                json={"email": f"user{n}@example.test"},
                headers={"X-Forwarded-For": f"198.51.100.{n + 1}"},
            )
            for n in range(11)
        ]
    assert {r.status_code for r in responses} == {200}
    assert {r.content for r in responses} == {responses[0].content}
    assert responses[0].json() == ACCEPTED
    # Первые 10 запросов с одного client-IP приняты, 11-й отклонён по IP: письма нет.
    assert len(_mails(env)) == 10
    assert all(m.to != "user10@example.test" for m in _mails(env))


# --- R7-T12: POST /confirm (FR-11..FR-14, NFR-1; AC-6..AC-9, AC-11) --------------------------


async def _issue(env: ApiEnv, address: str) -> str:
    """Запрашивает письмо и возвращает токен из последней ссылки."""
    response = await _post(env, address)
    assert response.status_code == 200
    body = _mails(env)[-1].body
    return body.split(LINK_PREFIX, 1)[1].split()[0]


async def _confirm(env: ApiEnv, token: str, password: str = NEW_PW) -> httpx.Response:
    return await env.client.post(CONFIRM, json={"token": token, "new_password": password})


async def _hash_of(env: ApiEnv, user_id: Any) -> str:
    return str((await env.user_row(user_id)).password_hash)


def _assert_invalid(response: httpx.Response) -> None:
    assert response.status_code == 400
    assert code_of(response) == "reset_token_invalid"
    assert "set-cookie" not in response.headers


async def test_007_confirm_disabled_is_404_feature_disabled(api_env: ApiEnv) -> None:
    response = await _confirm(api_env, "x" * 43)
    assert response.status_code == 404
    assert code_of(response) == "feature_disabled"


async def test_007_ac8_confirm_success_204_no_cookie_login_new_password(
    reset_api_env: ApiEnv,
) -> None:
    env = reset_api_env
    user = await env.new_user(role="user", email="a@example.test", must_change_password=True)
    old_a = await env.login_ok(user)
    old_b = await env.login_ok(user)
    assert old_a and old_b
    assert len(await env.session_ids(user.id)) == 2
    token = await _issue(env, "a@example.test")
    response = await _confirm(env, token)
    assert response.status_code == 204
    assert response.content == b""
    assert "set-cookie" not in response.headers  # вход отдельным действием (FR-13)
    assert await env.session_ids(user.id) == []
    assert (await env.user_row(user.id)).must_change_password is False
    assert (await env.login(user.login, NEW_PW)).status_code == 200
    assert (await env.login(user.login, user.password)).status_code == 401
    assert token not in response.text and NEW_PW not in response.text


async def test_007_ac8_confirm_reuse_is_400(reset_api_env: ApiEnv) -> None:
    env = reset_api_env
    await env.new_user(role="user", email="a@example.test")
    token = await _issue(env, "a@example.test")
    assert (await _confirm(env, token)).status_code == 204
    _assert_invalid(await _confirm(env, token, "Another-Pa55phrase-77"))


async def test_007_ac6_older_token_invalid_after_second_request(reset_api_env: ApiEnv) -> None:
    env = reset_api_env
    user = await env.new_user(role="user", email="a@example.test")
    first = await _issue(env, "a@example.test")
    env.clock.advance(timedelta(minutes=5))
    second = await _issue(env, "a@example.test")
    assert first != second
    before = await _hash_of(env, user.id)
    _assert_invalid(await _confirm(env, first))
    assert await _hash_of(env, user.id) == before
    assert (await _confirm(env, second)).status_code == 204


async def test_007_ac7_expired_token_is_400_hash_unchanged(reset_api_env: ApiEnv) -> None:
    env = reset_api_env
    user = await env.new_user(role="user", email="a@example.test")
    token = await _issue(env, "a@example.test")
    before = await _hash_of(env, user.id)
    env.clock.advance(timedelta(minutes=30, seconds=1))
    _assert_invalid(await _confirm(env, token))
    assert await _hash_of(env, user.id) == before


async def test_007_ac7_token_valid_until_boundary_exclusive(reset_api_env: ApiEnv) -> None:
    env = reset_api_env
    await env.new_user(role="user", email="a@example.test")
    token = await _issue(env, "a@example.test")
    env.clock.advance(timedelta(minutes=30))  # expires_at > now строго
    _assert_invalid(await _confirm(env, token))
    token2 = await _issue(env, "a@example.test")
    env.clock.advance(timedelta(minutes=29, seconds=59))
    assert (await _confirm(env, token2)).status_code == 204


async def test_007_confirm_unknown_garbage_tokens_are_400(reset_api_env: ApiEnv) -> None:
    env = reset_api_env
    for token in ("", "unknown-token", "x" * 128, "я" * 10, "\u0000"):
        _assert_invalid(await _confirm(env, token))


async def test_007_ac9_weak_password_422_token_not_consumed(reset_api_env: ApiEnv) -> None:
    env = reset_api_env
    user = await env.new_user(role="user", email="a@example.test")
    token = await _issue(env, "a@example.test")
    before = await _hash_of(env, user.id)
    short = await _confirm(env, token, "Abcdefg-123")  # 11 символов
    assert short.status_code == 422
    assert code_of(short) == "password_too_short"
    common = await _confirm(env, token, "unbelievable")
    assert common.status_code == 422
    assert code_of(common) == "password_too_common"
    assert await _hash_of(env, user.id) == before
    for response in (short, common):
        assert token not in response.text
        assert "set-cookie" not in response.headers
    assert (await _confirm(env, token)).status_code == 204


async def test_007_confirm_invalid_token_checked_before_password(reset_api_env: ApiEnv) -> None:
    """PR-20: сначала токен; плохой пароль с неверным токеном даёт 400, не 422."""
    _assert_invalid(await _confirm(reset_api_env, "unknown-token", "short"))


async def test_007_ac11_confirm_blocked_user_is_400(reset_api_env: ApiEnv) -> None:
    env = reset_api_env
    user = await env.new_user(role="user", email="a@example.test")
    token = await _issue(env, "a@example.test")
    await env.execute(
        text("UPDATE app_user SET is_blocked = true WHERE id = :u").bindparams(u=user.id)
    )
    before = await _hash_of(env, user.id)
    _assert_invalid(await _confirm(env, token))
    assert await _hash_of(env, user.id) == before


async def test_007_ac11_confirm_without_membership_is_400(reset_api_env: ApiEnv) -> None:
    env = reset_api_env
    user = await env.new_user(role="user", email="a@example.test")
    token = await _issue(env, "a@example.test")
    await env.execute(text("DELETE FROM workspace_member WHERE user_id = :u").bindparams(u=user.id))
    before = await _hash_of(env, user.id)
    _assert_invalid(await _confirm(env, token))
    assert await _hash_of(env, user.id) == before


async def test_007_confirm_schema_validation_422(reset_api_env: ApiEnv) -> None:
    env = reset_api_env
    for body in (
        {},
        {"token": "t"},
        {"new_password": NEW_PW},
        {"token": "t", "new_password": NEW_PW, "extra": 1},
        {"token": 5, "new_password": NEW_PW},
        {"token": "t", "new_password": 5},
        {"token": "x" * 129, "new_password": NEW_PW},
    ):
        response = await env.client.post(CONFIRM, json=body)
        assert response.status_code == 422, body
        assert code_of(response) == "validation_error", body
        assert NEW_PW not in response.text


async def test_007_confirm_broken_json_is_400(reset_api_env: ApiEnv) -> None:
    response = await reset_api_env.client.post(
        CONFIRM, content=b'{"token": "a', headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400
    assert code_of(response) == "bad_request"


async def test_007_confirm_foreign_origin_is_403(reset_api_env: ApiEnv) -> None:
    env = reset_api_env
    await env.new_user(role="user", email="a@example.test")
    token = await _issue(env, "a@example.test")
    response = await env.client.post(
        CONFIRM,
        json={"token": token, "new_password": NEW_PW},
        headers={"Origin": "http://evil.example"},
    )
    assert (response.status_code, code_of(response)) == (403, "origin_mismatch")
    assert (await _confirm(env, token)).status_code == 204


async def test_007_confirm_secrets_not_in_logs(reset_api_env: ApiEnv, caplog: Any) -> None:
    import logging

    caplog.set_level(logging.DEBUG)
    env = reset_api_env
    await env.new_user(role="user", email="a@example.test")
    token = await _issue(env, "a@example.test")
    results = [
        await _confirm(env, token, "short"),
        await _confirm(env, "bad-token-value", NEW_PW),
        await _confirm(env, token),
    ]
    assert [r.status_code for r in results] == [422, 400, 204]
    for body in results:
        assert token not in body.text and NEW_PW not in body.text
    assert token not in caplog.text
    assert NEW_PW not in caplog.text
    assert hashlib.sha256(token.encode()).hexdigest() not in caplog.text
