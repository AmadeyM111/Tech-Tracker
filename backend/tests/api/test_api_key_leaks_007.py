"""R7-T16: секрет ключа агента не утекает (007/AC-38, AC-39; FR-32, FR-6; plan PD-1, PD-11).

AC-38: перехват ВСЕХ логов приложения (JSON-вывод ``configure_logging("DEBUG")`` в stdout/stderr
через ``capsys`` и ``caplog``, включая access-лог ``app.access`` и ``app.errors``) при выпуске
ключа; «кто я», создании задачи и комментарии по ключу; 403 (маршрут вне перечня и чужая
задача), 422, 429 по ключу; 500 по ключу (подмена ``app.domain.tasks.queries.get_task``
исключением, текст которого содержит секрет); ключе с изменённым символом; запросах после
отзыва. Ни в логах, ни в телах и заголовках ответов (кроме тела ответа на выпуск), ни в
``domain_event`` (все столбцы, текстом), ни в ответах ``/admin/audit`` нет секрета и подстрок
длиной от 8 символов.

Заметки ревью R7-T03 (``reviews/R7-T03-1.md`` п.1–2): ключ с ``/`` или ``+`` внутри (в заголовке
и в пути) и ключ в ИМЕНИ поля ``extra`` (в том числе во вложенном Mapping) — отдельные тесты,
чтобы находка указывала на точное место.

AC-39: после выпуска (и использования) выгружаются все таблицы схемы ``public``; текстовые
значения, ``bytea`` как байты и в hex-кодировке, а также строка целиком в текстовом виде
Postgres — секрета и подстрок от 8 символов нет.

Логи тестового клиента (``httpx``/``httpcore``) — не логи приложения, из проверки исключаются.
Секрет не печатается: проверки вхождения считаются в булеву переменную до ``assert``; окна по
8 символов строятся в рантайме; секрет обёрнут в ``HiddenSecret``.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterable
from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from tests.agents007_support import (
    ADMIN_AGENTS,
    AUDIT,
    ME_URL,
    PROJECTS_URL,
    HiddenSecret,
    World007,
    bearer,
    comments_url,
    make_world007,
    mutated_secret,
    project_tasks_url,
    task_url,
)
from tests.conftest import ApiEnv

WINDOW = 8
CLIENT_LOGGERS = ("httpx", "httpcore")  # логи тестового клиента, не приложения
# обязательные поля создания задачи (006): название, описание, срок (CLOCK = 2026-11-02)
TASK_BODY = {"title": "Отчёт агента", "description": "Собрать метрики", "due_date": "2026-11-03"}


# --- поиск секрета -------------------------------------------------------------------------


def windows(secret: str) -> list[str]:
    """Все подстроки секрета длиной ``WINDOW`` (любая более длинная подстрока содержит одну)."""
    return [secret[i : i + WINDOW] for i in range(len(secret) - WINDOW + 1)]


def leaked(secret: str, haystack: str) -> bool:
    """Секрет или его подстрока от 8 символов в тексте (AC-38)."""
    return any(w in haystack for w in windows(secret))


def leaked_bytes(secret: str, blob: bytes) -> bool:
    """В байтах: подстрока секрета как ASCII-байты либо её hex-кодировка (любой регистр)."""
    hexed = blob.hex()
    for w in windows(secret):
        raw = w.encode("ascii")
        if raw in blob:
            return True
        if raw.hex() in hexed:
            return True
        # bytea, который сам хранит hex-текст подстроки
        if raw.hex().encode() in blob or raw.hex().upper().encode() in blob:
            return True
    return False


def leaked_value(secret: str, value: Any) -> bool:
    """Значение столбца: ``bytes``/``memoryview`` — побайтно и в hex; прочее — текстом."""
    if value is None:
        return False
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytes | bytearray):
        return leaked_bytes(secret, bytes(value))
    if isinstance(value, dict | list):
        return leaked(secret, json.dumps(value, ensure_ascii=False, default=str)) or leaked(
            secret, str(value)
        )
    return leaked(secret, str(value))


def broken_with(secret: str, char: str, pos: int) -> HiddenSecret:
    """Ключ, где символ на позиции ``pos`` заменён на ``char`` (``/`` или ``+``)."""
    return HiddenSecret(secret[:pos] + char + secret[pos + 1 :])


# --- перехват логов ------------------------------------------------------------------------


class LogCapture:
    """Тексты всех логов приложения: строки JSON stdout/stderr (целиком: сообщение, имена и
    значения полей, трассировки), ``caplog.text``, сообщения и трассировки записей."""

    def __init__(self, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture):
        self.capsys = capsys
        self.caplog = caplog
        self.lines: list[dict[str, Any]] = []
        self.raw: list[str] = []

    def start(self) -> None:
        from app.core.logging import configure_logging

        configure_logging("DEBUG")
        self.capsys.readouterr()
        self.caplog.set_level(logging.DEBUG)
        # лог тестового клиента печатает URL (с ключом в пути/строке запроса) в отчёт pytest:
        # глушим, чтобы секрет не попал в вывод теста; в проверку он и так не входит
        for name in CLIENT_LOGGERS:
            self.caplog.set_level(logging.WARNING, logger=name)

    def collect(self) -> None:
        captured = self.capsys.readouterr()
        for line in captured.out.splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)  # каждая запись — валидный JSON
            if str(entry.get("logger", "")).startswith(CLIENT_LOGGERS):
                continue
            self.lines.append(entry)
            self.raw.append(line)
        if captured.err.strip():
            self.raw.append(captured.err)

    def app_records(self) -> list[logging.LogRecord]:
        return [r for r in self.caplog.records if not r.name.startswith(CLIENT_LOGGERS)]

    def haystacks(self) -> list[str]:
        out = list(self.raw)
        for rec in self.app_records():
            out += [
                self.caplog.handler.format(rec),  # как в caplog.text
                rec.getMessage(),
                str(rec.exc_text or ""),
                str(rec.stack_info or ""),
            ]
        return out

    def access(self) -> list[dict[str, Any]]:
        return [e for e in self.lines if e.get("logger") == "app.access"]


def any_leak(secret: str, texts: Iterable[str]) -> bool:
    return any(leaked(secret, t) for t in texts)


# --- запросы -------------------------------------------------------------------------------


def keys_url(agent_id: uuid.UUID | str) -> str:
    return f"{ADMIN_AGENTS}/{agent_id}/api-keys"


def revoke_url(agent_id: uuid.UUID | str, key_id: uuid.UUID | str) -> str:
    return f"{ADMIN_AGENTS}/{agent_id}/api-keys/{key_id}/revoke"


async def by_key(
    env: ApiEnv, secret: str, method: str, url: str, body: Any = None, **kw: Any
) -> httpx.Response:
    kwargs: dict[str, Any] = {} if body is None else {"json": body}
    return await env.client.request(method, url, headers=bearer(secret), **kwargs, **kw)


async def by_cookie(
    env: ApiEnv, w: World007, who: str, method: str, url: str, body: Any = None
) -> httpx.Response:
    kwargs: dict[str, Any] = {} if body is None else {"json": body}
    return await env.client.request(method, url, headers=env.auth(w.cookie(who)), **kwargs)


async def issue_key(env: ApiEnv, w: World007, name: str = "leak-check") -> tuple[str, HiddenSecret]:
    """Выпуск ключа ``agent.u`` через API глазами ``ta1``: (id ключа, секрет)."""
    r = await by_cookie(
        env, w, "ta1", "POST", keys_url(w.agent_u.id), {"name": name, "expires_in_days": 90}
    )
    assert r.status_code == 201, r.status_code
    body = r.json()
    return str(body["key"]["id"]), HiddenSecret(body["secret"])


def response_texts(responses: Iterable[httpx.Response]) -> list[str]:
    out: list[str] = []
    for r in responses:
        out.append(r.text)
        out.append(str(sorted(r.headers.multi_items())))
    return out


async def domain_event_texts(env: ApiEnv) -> list[str]:
    """Все строки ``domain_event`` всей БД целиком в текстовом виде Postgres (все столбцы)."""
    rows = await env.execute(text("SELECT e::text FROM domain_event e ORDER BY e.id"))
    assert rows is not None
    return [str(r[0]) for r in rows]


async def audit_texts(env: ApiEnv, w: World007) -> tuple[list[str], list[str]]:
    """Все страницы ``/admin/audit`` и каждая запись по id глазами ``ta1``: (тексты, действия)."""
    texts: list[str] = []
    actions: list[str] = []
    page = 1
    while True:
        r = await by_cookie(env, w, "ta1", "GET", f"{AUDIT}?page={page}&page_size=100")
        assert r.status_code == 200, r.status_code
        texts.append(r.text)
        body = r.json()
        for item in body["items"]:
            actions.append(str(item["action"]))
            one = await by_cookie(env, w, "ta1", "GET", f"{AUDIT}/{item['id']}")
            assert one.status_code == 200, one.status_code
            texts.append(one.text)
        if not body["has_next"]:
            break
        page += 1
    return texts, actions


# --- AC-38: сквозной сценарий ---------------------------------------------------------------


async def test_007_ac38_full_scenario_no_secret_in_logs_bodies_events_and_audit(
    api_env: ApiEnv,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-38 (FR-32): выпуск, успешные операции, 403×2, 422, 500, 429, изменённый символ,
    отзыв и запросы после отзыва — секрета и подстрок ≥ 8 нет нигде, кроме тела ответа на
    выпуск."""
    env = api_env
    logs = LogCapture(capsys, caplog)
    logs.start()
    w = await make_world007(env)
    responses: list[httpx.Response] = []

    # выпуск: секрет только в теле этого ответа (положительный контроль), не в его заголовках
    issued = await by_cookie(
        env, w, "ta1", "POST", keys_url(w.agent_u.id), {"name": "leak", "expires_in_days": 90}
    )
    assert issued.status_code == 201, issued.status_code
    key_id = str(issued.json()["key"]["id"])
    secret = HiddenSecret(issued.json()["secret"])
    in_issue_body = secret in issued.text
    assert in_issue_body, "ответ на выпуск не содержит секрета: контроль сломан"
    issue_headers_leak = leaked(secret, str(sorted(issued.headers.multi_items())))
    assert not issue_headers_leak, "секрет в заголовках ответа на выпуск"

    # успешные операции
    me = await by_key(env, secret, "GET", ME_URL)
    assert me.status_code == 200, me.status_code
    created = await by_key(env, secret, "POST", project_tasks_url(w.P), TASK_BODY)
    assert created.status_code == 201, created.status_code
    comment = await by_key(env, secret, "POST", comments_url(w.T1), {"body": "Готово"})
    assert comment.status_code == 201, comment.status_code
    responses += [me, created, comment]

    # 403: маршрут вне перечня и чужая задача (P2)
    outside = await by_key(env, secret, "GET", AUDIT)
    foreign = await by_key(env, secret, "GET", task_url(w.T9))
    assert (outside.status_code, foreign.status_code) == (403, 403)
    # 422
    invalid = await by_key(env, secret, "POST", project_tasks_url(w.P), {"title": ""})
    assert invalid.status_code == 422, invalid.status_code
    responses += [outside, foreign, invalid]

    # изменён один символ
    mutated = await by_key(env, mutated_secret(secret), "GET", ME_URL)
    assert mutated.status_code == 401, mutated.status_code
    responses.append(mutated)

    # 500: подменённый запрос карточки падает исключением, в тексте которого секрет
    import app.domain.tasks.queries as task_queries

    async def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("injected failure for api key " + secret)

    monkeypatch.setattr(task_queries, "get_task", boom)
    transport = httpx.ASGITransport(app=env.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url=env.base_url) as quiet:
        failed = await quiet.get(task_url(w.T1), headers=bearer(secret))
    monkeypatch.undo()
    assert failed.status_code == 500, failed.status_code
    responses.append(failed)

    # 429: до исчерпания лимита (120 в минуту), затем ещё и запись
    limited: httpx.Response | None = None
    for _ in range(130):
        r = await by_key(env, secret, "GET", ME_URL)
        if r.status_code == 429:
            limited = r
            break
        assert r.status_code == 200, r.status_code
    assert limited is not None, "лимит не сработал за 130 запросов"
    limited_write = await by_key(env, secret, "POST", project_tasks_url(w.P), TASK_BODY)
    assert limited_write.status_code == 429, limited_write.status_code
    responses += [limited, limited_write]

    # отзыв (окно лимита закрыто), запросы после отзыва
    env.clock.advance(timedelta(minutes=2))
    revoked = await by_cookie(env, w, "ta1", "POST", revoke_url(w.agent_u.id, key_id))
    assert revoked.status_code == 204, revoked.status_code
    after = [
        await by_key(env, secret, "GET", ME_URL),
        await by_key(env, secret, "GET", PROJECTS_URL),
        await by_key(env, secret, "POST", comments_url(w.T1), {"body": "после отзыва"}),
    ]
    assert [r.status_code for r in after] == [401, 401, 401]
    responses += [revoked, *after]

    # перечень ключей глазами ТА (FR-7): ни секрета, ни части
    listing = await by_cookie(env, w, "ta1", "GET", f"{keys_url(w.agent_u.id)}?page_size=100")
    assert listing.status_code == 200, listing.status_code
    responses.append(listing)

    # --- проверки
    logs.collect()
    statuses = {e.get("status") for e in logs.access()}
    assert {200, 201, 204, 401, 403, 422, 429, 500} <= statuses, "access-лог перехвачен не весь"
    assert any(e.get("logger") == "app.errors" and e.get("exception") for e in logs.lines), (
        "трассировка 500 не перехвачена: проверка логов бессмысленна"
    )

    in_bodies = any_leak(secret, response_texts(responses))
    in_logs = any_leak(secret, logs.haystacks())

    events = await domain_event_texts(env)
    event_text = "\n".join(events)
    for action in (
        "user.api_key_issued",
        "user.api_key_revoked",
        "task.created",
        "comment.created",
    ):
        assert action in event_text, f"нет события {action}: проверка событий бессмысленна"
    in_events = any_leak(secret, events)

    audit, actions = await audit_texts(env, w)
    assert {"user.api_key_issued", "user.api_key_revoked"} <= set(actions), (
        "аудит без событий ключа"
    )
    in_audit = any_leak(secret, audit)

    assert not in_bodies, "секрет или его подстрока ≥ 8 в теле/заголовках ответа"
    assert not in_logs, "секрет или его подстрока ≥ 8 в логах приложения"
    assert not in_events, "секрет или его подстрока ≥ 8 в domain_event"
    assert not in_audit, "секрет или его подстрока ≥ 8 в ответах /admin/audit"


async def test_007_ac38_key_in_url_path_and_query_not_logged_or_echoed(
    api_env: ApiEnv,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC-38, PD-11 (2): ключ, по ошибке переданный в пути и в строке запроса, не попадает в
    access-лог (путь маскируется, строка запроса не пишется) и не возвращается в теле ответа."""
    env = api_env
    logs = LogCapture(capsys, caplog)
    logs.start()
    w = await make_world007(env)
    _key_id, secret = await issue_key(env, w)

    responses = [
        await by_key(env, secret, "GET", task_url(secret)),
        await by_key(env, secret, "GET", f"{task_url(secret)}/comments"),
        await by_key(env, secret, "GET", ME_URL, params={"api_key": secret}),
        await env.client.get(ME_URL, params={"access_token": secret}),
        await env.client.get(f"{ME_URL}/{secret}"),
    ]
    assert responses[2].status_code == 200, "ключ в заголовке действует (контроль)"

    logs.collect()
    paths = [str(e.get("path", "")) for e in logs.access()]
    assert len(paths) >= len(responses), "access-лог запросов не перехвачен"
    in_bodies = any_leak(secret, response_texts(responses))
    in_logs = any_leak(secret, logs.haystacks())
    assert not in_bodies, "ключ из пути/строки запроса вернулся в ответе"
    assert not in_logs, "ключ из пути/строки запроса попал в лог"


@pytest.mark.parametrize("char", ["/", "+"], ids=["slash", "plus"])
async def test_007_ac38_key_with_slash_or_plus_inside_not_in_logs(
    api_env: ApiEnv,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    char: str,
) -> None:
    """AC-38 («изменён один символ»), ревью R7-T03 п.2: символ ключа заменён на ``/`` или ``+``
    (вне алфавита base64url). Ключ в заголовке ``Authorization`` и в пути запроса: ни хвост, ни
    голова такого ключа (подстроки настоящего секрета ≥ 8) не попадают в логи и ответы.
    При находке — вернуться к plan PD-11 (маскировать до разделителя)."""
    env = api_env
    logs = LogCapture(capsys, caplog)
    logs.start()
    w = await make_world007(env)
    _key_id, secret = await issue_key(env, w)

    responses: list[httpx.Response] = []
    for pos in (11, 12, len(secret) // 2, len(secret) - 10):
        broken = broken_with(secret, char, pos)
        responses += [
            await by_key(env, broken, "GET", ME_URL),  # заголовок
            await by_key(env, broken, "GET", task_url(broken)),  # заголовок и путь
            await by_key(env, broken, "GET", ME_URL, params={"key": broken}),  # строка запроса
        ]
    statuses = [r.status_code for r in responses]
    assert all(s >= 400 for s in statuses), statuses
    assert statuses[0] == 401, statuses

    logs.collect()
    assert len(logs.access()) >= len(responses), "access-лог запросов не перехвачен"
    in_bodies = any_leak(secret, response_texts(responses))
    in_logs = any_leak(secret, logs.haystacks())
    assert not in_bodies, "подстрока секрета ≥ 8 из испорченного ключа в ответе"
    assert not in_logs, "подстрока секрета ≥ 8 из испорченного ключа в логе (PD-11)"


# --- AC-38: ключ в имени поля extra (ревью R7-T03 п.1) -------------------------------------


def _emit_and_collect(
    capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture, extra: dict[str, Any]
) -> LogCapture:
    logs = LogCapture(capsys, caplog)
    logs.start()
    logging.getLogger("app.test007.leaks").info("marker-007-extra", extra=extra)
    logs.collect()
    assert any(e.get("message") == "marker-007-extra" for e in logs.lines), "запись не перехвачена"
    return logs


def _fresh_secret() -> HiddenSecret:
    from app.core.security.api_keys import generate_api_key

    return HiddenSecret(generate_api_key())


def test_007_ac38_secret_as_extra_field_name_is_not_logged(
    capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    """Ревью R7-T03 п.1 (``core/logging.py`` 381, 419): ``extra={<секрет>: 1}`` — имя поля
    проходит маскирование, как и значение."""
    secret = _fresh_secret()
    logs = _emit_and_collect(capsys, caplog, {secret: 1, "plain": secret})
    in_logs = any_leak(secret, logs.haystacks())
    assert not in_logs, "секрет в имени поля extra попал в лог"


def test_007_ac38_secret_as_nested_mapping_key_is_not_logged(
    capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    """Ревью R7-T03 п.1 (``core/logging.py`` 245): ключ вложенного Mapping в ``extra``."""
    secret = _fresh_secret()
    logs = _emit_and_collect(
        capsys, caplog, {"ctx": {"outer": {secret: "v"}, "list": [{secret: 2}]}}
    )
    in_logs = any_leak(secret, logs.haystacks())
    assert not in_logs, "секрет в ключе вложенного словаря extra попал в лог"


# --- AC-39: выгрузка всех таблиц -------------------------------------------------------------


async def _public_tables(env: ApiEnv) -> list[str]:
    rows = await env.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name"
        )
    )
    assert rows is not None
    return [str(r[0]) for r in rows]


async def test_007_ac39_dump_of_all_public_tables_has_no_secret(api_env: ApiEnv) -> None:
    """AC-39 (FR-6, PD-1): выпущен (и использован) ключ; все таблицы ``public`` — значения
    столбцов (текст; ``bytea`` как байты и hex) и строки целиком (``t::text``) — без секрета и
    его подстрок ≥ 8. Ревью R7-T10: ``bytea`` проверяется побайтно, не только ``::text``."""
    env = api_env
    w = await make_world007(env)
    key_id, secret = await issue_key(env, w, name="dump-check")
    assert (await by_key(env, secret, "GET", ME_URL)).status_code == 200
    r = await by_key(env, secret, "POST", project_tasks_url(w.P), TASK_BODY)
    assert r.status_code == 201, r.status_code
    r = await by_key(env, secret, "POST", comments_url(w.T1), {"body": "Комментарий по ключу"})
    assert r.status_code == 201, r.status_code

    tables = await _public_tables(env)
    assert {"api_key", "domain_event", "app_user", "task", "comment"} <= set(tables), tables

    key_rows = await env.execute(
        text("SELECT count(*) FROM api_key WHERE id = :k").bindparams(k=uuid.UUID(key_id))
    )
    assert key_rows is not None and key_rows[0][0] == 1, "строка выпущенного ключа не найдена"

    leaked_tables: list[str] = []
    bytea_seen = 0
    for table in tables:
        rows = await env.execute(text(f'SELECT * FROM "{table}"'))  # noqa: S608
        assert rows is not None
        hit = False
        for row in rows:
            for value in row:
                if isinstance(value, bytes | bytearray | memoryview):
                    bytea_seen += 1
                if leaked_value(secret, value):
                    hit = True
        whole = await env.execute(text(f'SELECT t::text FROM "{table}" t'))  # noqa: S608
        assert whole is not None
        if any(leaked(secret, str(x[0])) for x in whole):
            hit = True
        if hit:
            leaked_tables.append(table)

    assert bytea_seen > 0, "ни одного bytea-значения: проверка байтов бессмысленна"
    assert not leaked_tables, f"секрет или его подстрока ≥ 8 в таблицах: {leaked_tables}"
