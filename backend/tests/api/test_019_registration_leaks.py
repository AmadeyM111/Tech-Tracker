"""R8-T14: сквозной сценарий самостоятельной регистрации, утечки и аудит (spec 019: AC-12, AC-13,
AC-19, AC-20, AC-25, AC-26; plan §6; NFR-1).

Сценарий (``_run_scenario``): заявка -> письмо -> подтверждение по ссылке -> вход (учётная
запись без роли) -> ``/me`` и ``/projects`` 403 ``no_role`` -> БА назначает «Пользователь» ->
``/projects`` 200 той же сессией -> сброс пароля по email новой учётной записи -> вход новым
паролем.

Проверки утечек идут по всему сценарию. caplog уровня DEBUG и сырые записи логов не содержат ПДн,
паролей, токенов и их хешей. Сырой перехватчик стоит перед ``SecretsFilter`` приложения: фильтр
маскирует только значения секретных ключей, а email, имя и логин в тексте он не трогает, поэтому
его вывод проверяется отдельно. Ответы API не содержат токенов, хешей и ``key_hash``.
"""

from __future__ import annotations

import hashlib
import logging
import traceback
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest_asyncio
from sqlalchemy import text

from tests.admin_support import code_of, events, new_workspace, seed

if TYPE_CHECKING:
    import httpx

    from tests.conftest import ApiEnv
    from tests.factories import WorkspaceRow

REQUEST = "/api/v1/auth/registration/request"
CONFIRM = "/api/v1/auth/registration/confirm"
RESET_REQUEST = "/api/v1/auth/password-reset/request"
RESET_CONFIRM = "/api/v1/auth/password-reset/confirm"
ME = "/api/v1/me"
PROJECTS = "/api/v1/projects"
UNASSIGNED = "/api/v1/unassigned-accounts"
REG_LINK = "https://tracker.example.test/register/confirm#token="
RESET_LINK = "https://tracker.example.test/password-reset/confirm#token="
ACCEPTED = {
    "detail": (
        "Если адрес можно использовать для регистрации, мы отправили на него письмо с "
        "подтверждением. Ссылка действует 30 минут."
    )
}
# Уникальные для этого файла значения: по ним ищется утечка в логах и ответах.
EMAIL = "zinaida.mark.4e8b@example.test"
FIRST = "Зинаида"
LAST = "Фотиева-Лейкова"
LOGIN = "Leak.Probe.9f2e"
PW = "Zq7-leak-probe-9f2e-pw"
NEW_PW = "Qw8-reset-probe-4c1d-pw"
WRONG_PW = "Wr0ng-probe-7a7a-pw"
# Публичные ответы не называют ни адрес, ни имя, ни логин (AC-20, FR-3 ответ единый).
PUBLIC_PATHS = frozenset({REQUEST, CONFIRM, RESET_REQUEST, RESET_CONFIRM})
# Ключи, которых не должно быть ни в одном JSON-ответе сценария (NFR-1).
FORBIDDEN_KEYS = frozenset(
    {
        "token",
        "token_hash",
        "key_hash",
        "password",
        "password_hash",
        "one_time_password",
        "new_password",
    }
)
_STANDARD_RECORD_ATTRS = frozenset(vars(logging.LogRecord("n", 0, "p", 0, "m", None, None))) | {
    "message",
    "asctime",
    "taskName",
}


@dataclass
class Scenario:
    responses: list[httpx.Response] = field(default_factory=list)
    secrets: dict[str, str] = field(default_factory=dict)
    personal: dict[str, str] = field(default_factory=dict)
    user_id: uuid.UUID | None = None

    @property
    def markers(self) -> dict[str, str]:
        """Всё, что нельзя выводить в логи и журнал: секреты и ПДн вместе."""
        return {**self.personal, **self.secrets}


class _RawLog(logging.Handler):
    """Перехватчик, стоящий первым в корне: видит запись так, как её создал код приложения."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.chunks: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:  # дефект формата не должен ломать сам тест
            message = str(record.msg)
        parts = [message]
        parts.extend(
            f"{key}={value!r}"
            for key, value in vars(record).items()
            if key not in _STANDARD_RECORD_ATTRS
        )
        if record.exc_info:
            parts.append("".join(traceback.format_exception(*record.exc_info)))
        self.chunks.append("\n".join(parts))

    @property
    def text(self) -> str:
        return "\n".join(self.chunks)


@contextmanager
def _raw_capture() -> Iterator[_RawLog]:
    """``create_app`` вызывает ``configure_logging``: он ставит stdout-обработчик с фильтром
    в начало списка корня. Перехватчик ставится ещё раньше и снимается при выходе."""
    handler = _RawLog()
    root = logging.getLogger()
    previous = root.level
    root.setLevel(logging.DEBUG)
    root.handlers.insert(0, handler)
    try:
        yield handler
    finally:
        root.handlers.remove(handler)
        root.setLevel(previous)


@pytest_asyncio.fixture
async def reg_ws(reset_api_env: ApiEnv) -> WorkspaceRow:
    """Ровно одно пространство на тест (RG-9): без него регистрация отвечает 404."""
    return await new_workspace(reset_api_env)


def _body() -> dict[str, Any]:
    return {"email": EMAIL, "first_name": FIRST, "last_name": LAST, "login": LOGIN, "password": PW}


def _last_mail(env: ApiEnv) -> Any:
    return env.app.state.mailer.sent[-1]


def _link_token(mail_body: str, prefix: str) -> str:
    return mail_body.split(prefix, 1)[1].split()[0]


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _visible(response: httpx.Response) -> str:
    """Тело и заголовки, которые видит клиент, кроме ``Set-Cookie``: сеансовая cookie туда
    входит по назначению, а её значение проверяется отдельно через маркер сеанса."""
    headers = "\n".join(
        f"{key}: {value}" for key, value in response.headers.multi_items() if key != "set-cookie"
    )
    return f"{response.text}\n{headers}"


def _json_keys(value: Any) -> set[str]:
    """Все ключи JSON-структуры на любой глубине."""
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(key)
            keys |= _json_keys(item)
    elif isinstance(value, list):
        for item in value:
            keys |= _json_keys(item)
    return keys


def _assert_no_markers(haystack: str, markers: dict[str, str], where: str) -> None:
    """Выводит в сообщении только имена маркеров: сами значения в отчёт о падении не попадают."""
    leaked = sorted(label for label, value in markers.items() if value and value in haystack)
    assert not leaked, f"{where}: найдены маркеры: {', '.join(leaked)}"


async def _password_hash(env: ApiEnv, user_id: uuid.UUID) -> str:
    rows = await env.execute(
        text("SELECT password_hash FROM app_user WHERE id = :u").bindparams(u=user_id)
    )
    assert rows
    return str(rows[0][0])


async def _run_scenario(env: ApiEnv, ws: WorkspaceRow) -> Scenario:
    """Весь сценарий от заявки до входа новым паролем; утверждения шагов — внутри."""
    scenario = Scenario()

    def keep(response: httpx.Response) -> httpx.Response:
        scenario.responses.append(response)
        return response

    ba, (ba_token,) = await seed(env, ws, "business_admin", login="leak.ba")

    # 1. заявка: единый ответ, письмо уходит на адрес из заявки
    accepted = keep(await env.client.post(REQUEST, json=_body()))
    assert (accepted.status_code, accepted.json()) == (200, ACCEPTED)
    registration_mail = _last_mail(env)
    assert registration_mail.to == EMAIL
    registration_token = _link_token(registration_mail.body, REG_LINK)

    # 2. до подтверждения учётной записи нет и вход не проходит (AC-12)
    pending = keep(await env.login(LOGIN, PW))
    assert (pending.status_code, code_of(pending)) == (401, "invalid_credentials")
    count = await env.execute(
        text("SELECT count(*) FROM app_user WHERE email = :e").bindparams(e=EMAIL)
    )
    assert count is not None and int(count[0][0]) == 0

    # 3. шаг без последствий: чужой токен
    bad = keep(await env.client.post(CONFIRM, json={"token": "x" * 43}))
    assert (bad.status_code, code_of(bad)) == (400, "registration_token_invalid")

    # 4. подтверждение по ссылке из письма
    confirmed = keep(await env.client.post(CONFIRM, json={"token": registration_token}))
    assert confirmed.status_code == 204
    rows = await env.execute(
        text(
            "SELECT id, login_display, first_name, last_name, self_registered, "
            "must_change_password FROM app_user WHERE email = :e"
        ).bindparams(e=EMAIL)
    )
    assert rows is not None and len(rows) == 1
    user_id, login_display, first, last, self_registered, must_change = rows[0]
    assert (login_display, first, last, self_registered, must_change) == (
        LOGIN,
        FIRST,
        LAST,
        True,
        False,
    )
    scenario.user_id = user_id
    hash_before = await _password_hash(env, user_id)

    # 5. вход: неверный пароль отклоняется, верный — учётная запись без роли
    wrong = keep(await env.login(LOGIN, WRONG_PW))
    assert (wrong.status_code, code_of(wrong)) == (401, "invalid_credentials")
    entered = keep(await env.login(LOGIN, PW))
    assert entered.status_code == 200, entered.text
    assert entered.json()["user"]["role"] is None
    session = env.token_from(entered)
    assert session

    # 6. без роли: /me и /projects отвечают 403 no_role (AC-25)
    for url in (ME, PROJECTS):
        denied = keep(await env.client.get(url, headers=env.auth(session)))
        assert (denied.status_code, code_of(denied)) == (403, "no_role"), url

    # 7. БА видит учётную запись без роли (без email) и назначает «Пользователь» (AC-26)
    listed = keep(await env.client.get(UNASSIGNED, headers=env.auth(ba_token)))
    assert listed.status_code == 200, listed.text
    assert LOGIN in [item["login"] for item in listed.json()["items"]]
    assigned = keep(
        await env.client.put(
            f"{UNASSIGNED}/{user_id}/role", json={"role": "user"}, headers=env.auth(ba_token)
        )
    )
    assert assigned.status_code == 204, assigned.text
    # AC-26: в журнале назначение роли с автором — этим БА
    granted = [
        row for row in await events(env, entity_id=user_id) if row[3] == "user.role_assigned"
    ]
    assert len(granted) == 1
    assert granted[0][1] == ba.id

    # 8. та же сессия без повторного входа: /projects 200 (роль читается из БД, FR-67)
    projects = keep(await env.client.get(PROJECTS, headers=env.auth(session)))
    assert projects.status_code == 200, projects.text

    # 9. сброс пароля по email новой учётной записи (AC-13)
    reset = keep(await env.client.post(RESET_REQUEST, json={"email": EMAIL}))
    assert reset.status_code == 200
    reset_mail = _last_mail(env)
    assert reset_mail.to == EMAIL
    reset_token = _link_token(reset_mail.body, RESET_LINK)
    done = keep(
        await env.client.post(RESET_CONFIRM, json={"token": reset_token, "new_password": NEW_PW})
    )
    assert done.status_code == 204, done.text
    old = keep(await env.login(LOGIN, PW))
    assert (old.status_code, code_of(old)) == (401, "invalid_credentials")
    fresh = keep(await env.login(LOGIN, NEW_PW))
    assert fresh.status_code == 200, fresh.text
    hash_after = await _password_hash(env, user_id)

    # ПДн: законно есть только в своих ответах (/login, /me, список БА); в публичных их нет
    scenario.personal = {
        "email": EMAIL,
        "имя": FIRST,
        "фамилия": LAST,
        "логин": LOGIN,
        "логин в нижнем регистре": LOGIN.lower(),
    }
    # секреты: не должны быть ни в одном ответе (сеансовая cookie вынесена из _visible)
    scenario.secrets = {
        "пароль": PW,
        "новый пароль": NEW_PW,
        "неверный пароль": WRONG_PW,
        "токен подтверждения": registration_token,
        "токен сброса": reset_token,
        "сеансовый токен": session,
        "хеш токена подтверждения": _sha256_hex(registration_token),
        "хеш токена сброса": _sha256_hex(reset_token),
        "хеш пароля до сброса": hash_before,
        "хеш пароля после сброса": hash_after,
        "префикс хеша Argon2": "$argon2",
    }
    return scenario


async def test_019_e2e_registration_to_business_access_and_password_reset(
    reset_api_env: ApiEnv, reg_ws: WorkspaceRow
) -> None:
    """AC-12, AC-13, AC-25, AC-26: заявка -> подтверждение -> вход -> no_role -> роль -> 200.

    Утверждения шагов находятся в ``_run_scenario``; здесь фиксируем итог: учётная запись
    создана, и после сброса пароля вход новым паролем проходит (проверено внутри сценария).
    """
    scenario = await _run_scenario(reset_api_env, reg_ws)
    assert scenario.user_id is not None


async def test_019_scenario_logs_at_debug_have_no_pii_or_secrets(
    reset_api_env: ApiEnv, reg_ws: WorkspaceRow, caplog: Any
) -> None:
    """NFR-1, AC-20: DEBUG-логи всего сценария без email, имени, фамилии, логина, токена, пароля."""
    caplog.set_level(logging.DEBUG)
    with _raw_capture() as raw:
        # контроль: DEBUG доходит и до caplog, и до сырого перехватчика, иначе проверка пустая
        logging.getLogger("app.leak_probe").debug("probe %s", "marker-ok")
        scenario = await _run_scenario(reset_api_env, reg_ws)
    assert "probe marker-ok" in caplog.text
    assert "probe marker-ok" in raw.text
    _assert_no_markers(caplog.text, scenario.markers, "caplog уровня DEBUG")
    _assert_no_markers(raw.text, scenario.markers, "сырые записи логов уровня DEBUG")


async def test_019_scenario_api_responses_have_no_token_hash_or_key_hash(
    reset_api_env: ApiEnv, reg_ws: WorkspaceRow
) -> None:
    """NFR-1: ответы API без токенов и хешей; публичные без ПДн; в списке БА нет email."""
    scenario = await _run_scenario(reset_api_env, reg_ws)
    assert scenario.responses
    for response in scenario.responses:
        path = response.request.url.path
        where = f"{response.request.method} {path} -> {response.status_code}"
        _assert_no_markers(_visible(response), scenario.secrets, where)
        keys = _json_keys(response.json()) if response.content else set()
        assert not sorted(keys & FORBIDDEN_KEYS), where
        if path in PUBLIC_PATHS:
            _assert_no_markers(_visible(response), scenario.personal, where)
        if path == UNASSIGNED:
            _assert_no_markers(_visible(response), {"email": EMAIL}, where)
            assert all("email" not in item for item in response.json()["items"]), where


async def test_019_ac19_one_self_registered_record_for_whole_scenario(
    reset_api_env: ApiEnv, reg_ws: WorkspaceRow
) -> None:
    """AC-19: за весь сценарий одна запись ``user.self_registered``, actor = entity = учётная."""
    env = reset_api_env
    scenario = await _run_scenario(env, reg_ws)
    rows = await events(env, workspace_id=reg_ws.id)
    registered = [row for row in rows if row[3] == "user.self_registered"]
    assert len(registered) == 1
    _event_id, actor_id, entity_id, _action, details, changed = registered[0]
    assert actor_id == entity_id == scenario.user_id
    assert details is None
    assert list(changed or []) == []
    # журнал без значений: ни адреса, ни имени, ни логина, ни секретов
    _assert_no_markers(repr(rows), scenario.markers, "журнал аудита")


async def test_019_ac19_no_audit_record_for_request_or_failed_confirm(
    reset_api_env: ApiEnv, reg_ws: WorkspaceRow
) -> None:
    """AC-19: неподтверждённая заявка, её повтор и неудачное подтверждение событий не пишут."""
    env = reset_api_env
    first = await env.client.post(REQUEST, json=_body())
    again = await env.client.post(REQUEST, json=_body())
    assert (first.status_code, again.status_code) == (200, 200)
    bad = await env.client.post(CONFIRM, json={"token": "x" * 43})
    assert bad.status_code == 400
    rows = await events(env, workspace_id=reg_ws.id)
    assert [row for row in rows if row[3] == "user.self_registered"] == []
    count = await env.execute(
        text("SELECT count(*) FROM app_user WHERE email = :e").bindparams(e=EMAIL)
    )
    assert count is not None and int(count[0][0]) == 0
