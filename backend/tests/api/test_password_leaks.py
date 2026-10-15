"""T14: пароли не попадают в ответы и логи (AC-35, FR-57).

Сценарий: неудачный вход, успешный вход, неверный current, слишком короткий новый пароль,
суррогат, слишком длинное значение, смена пароля, ошибка сервера при входе (подмена провайдера:
``RuntimeError(f"password=...")``). Ни один из использованных паролей не встречается:
в телах и заголовках ответов (включая 422 и 500), в JSON-логах stdout (``configure_logging``,
в том числе access-лог), в ``caplog``. Токен сессии и его HMAC в логах отсутствуют.
"""

import base64
import json
import logging
from typing import Any

import httpx
import pytest

from tests.conftest import ApiEnv

OLD = "Old-Leak-Pa55phrase-4412"
NEW = "New-Leak-Pa55phrase-7781"
WRONG_LOGIN = "WrongLogin-Leak-9137"
WRONG_CURRENT = "WrongCurrent-Leak-5520"
SHORT_NEW = "Sh0rt-Lk-1"  # 10 символов
SERVER_ERROR_PW = "ServerError-Leak-6603"
LONG_PW = "LongLeak-" + "z" * 1030
SURROGATE_MARK = "SurrogateLeak-"
PASSWORD_URL = "/api/v1/auth/password"
LOGIN_URL = "/api/v1/auth/login"


class _ExplodingProvider:
    """Провайдер, чьё исключение содержит введённый пароль (худший случай для логов)."""

    name = "exploding"

    async def authenticate(
        self, db: Any, credentials: Any, *, now: Any, checkpoint: Any = None
    ) -> Any:
        raise RuntimeError(f"password={credentials.password.get_secret_value()}")


def _token_forms(env: ApiEnv, token: str) -> list[str]:
    token_id = env.token_id(token)
    return [
        token,
        token_id.hex(),
        token_id.hex().upper(),
        base64.b64encode(token_id).decode(),
        base64.urlsafe_b64encode(token_id).decode(),
        base64.urlsafe_b64encode(token_id).decode().rstrip("="),
    ]


async def test_ac35_full_scenario_leaves_no_passwords_in_responses_or_logs(
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    api_env: ApiEnv,
) -> None:
    from app.core.logging import configure_logging

    env = api_env
    configure_logging("DEBUG")
    capsys.readouterr()
    caplog.set_level(logging.DEBUG)

    user = await env.new_user(role="user", password=OLD, must_change_password=True)
    responses: list[httpx.Response] = []
    tokens: list[str] = []

    # 1. неудачный вход
    failed = await env.login(user.login, WRONG_LOGIN)
    assert failed.status_code == 401
    responses.append(failed)

    # 2. успешный вход
    login = await env.login(user.login, OLD)
    assert login.status_code == 200
    responses.append(login)
    token = env.token_from(login)
    assert token
    tokens.append(token)

    def change(current: str, new: str) -> Any:
        return env.client.post(
            PASSWORD_URL,
            json={"current_password": current, "new_password": new},
            headers=env.auth(token),
        )

    # 3. отказы смены: неверный current, короткий новый, слишком длинное значение
    wrong = await change(WRONG_CURRENT, NEW)
    assert wrong.status_code == 422
    short = await change(OLD, SHORT_NEW)
    assert short.status_code == 422
    too_long = await change(OLD, LONG_PW)
    assert too_long.status_code == 422
    too_long_login = await env.client.post(
        LOGIN_URL, json={"login": user.login, "password": LONG_PW}
    )
    assert too_long_login.status_code == 422
    responses += [wrong, short, too_long, too_long_login]

    # 4. суррогат в новом пароле: 422 (не 500)
    surrogate_body = (
        '{"current_password": ' + json.dumps(OLD) + f', "new_password": "{SURROGATE_MARK}\\ud800"}}'
    ).encode()
    surrogate = await env.client.post(
        PASSWORD_URL,
        content=surrogate_body,
        headers={**env.auth(token), "Content-Type": "application/json"},
    )
    assert surrogate.status_code == 422
    responses.append(surrogate)

    # 5. успешная смена, затем вход по новому паролю и отказ по старому
    changed = await change(OLD, NEW)
    assert changed.status_code == 204
    old_again = await env.login(user.login, OLD)
    assert old_again.status_code == 401
    new_login = await env.login(user.login, NEW)
    assert new_login.status_code == 200
    new_token = env.token_from(new_login)
    assert new_token
    tokens.append(new_token)
    responses += [changed, old_again, new_login]

    # 6. ошибка сервера при входе: исключение провайдера содержит пароль
    env.app.state.auth_provider = _ExplodingProvider()
    transport = httpx.ASGITransport(app=env.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url=env.base_url) as quiet:
        boom = await quiet.post(LOGIN_URL, json={"login": user.login, "password": SERVER_ERROR_PW})
    assert boom.status_code == 500
    assert boom.json()["code"] == "internal_error"
    responses.append(boom)

    secrets = [OLD, NEW, WRONG_LOGIN, WRONG_CURRENT, SHORT_NEW, SERVER_ERROR_PW, SURROGATE_MARK]
    secrets.append(LONG_PW[:40])

    # ответы: тела и заголовки
    for response in responses:
        haystacks = [response.text, str(sorted(response.headers.items()))]
        for secret in secrets:
            for haystack in haystacks:
                assert secret not in haystack, (response.request.url, secret[:10])

    # логи: stdout (JSON-строки), caplog и его записи
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    assert lines, "access-лог пуст: проверка бессмысленна"
    for line in lines:
        json.loads(line)  # каждая запись остаётся валидным JSON
    assert PASSWORD_URL in out and LOGIN_URL in out
    log_haystacks = [out, caplog.text]
    for record in caplog.records:
        log_haystacks += [record.getMessage(), repr(record.args), str(record.exc_text)]
    for secret in secrets:
        for haystack in log_haystacks:
            assert secret not in haystack, f"пароль попал в лог: {secret[:10]}..."
    for tok in tokens:
        for form in _token_forms(env, tok):
            for haystack in log_haystacks:
                assert form not in haystack, "токен сессии или его HMAC попал в лог"
