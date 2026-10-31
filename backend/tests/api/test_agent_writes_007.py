"""R7-T15: операции записи по ключу агента - приёмочные тесты (007/FR-23...FR-29).

AC-22...AC-32, AC-34 (plan §6.1: существующие сервисы задач и комментариев, код не меняется) и
заметка ревью R7-T14: «было» при параллельных изменениях одной карточки, снятие исполнителя
подзадачи (``old``/``new`` = str/None), правка только описания (``changes IS NULL``), статус
подзадачи через PATCH.

Мир spec §5 - ``make_world007`` (часы на ``CLOCK``). Ошибки проверяются по статусу, коду и
точному составу ключей тела (``{"detail", "code"}``). «Задача не изменилась» - сравнение всей
строки ``task`` до и после. Секрет ключа в сообщения ``assert`` не попадает (``hide``).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, timedelta
from typing import Any

import httpx
import pytest

from tests.agents007_support import (
    API,
    MY_TASKS_URL,
    World007,
    bearer,
    board_url,
    comments_url,
    domain_events,
    make_world007,
    project_task_count,
    project_tasks_url,
    subtasks_url,
    task_comment_count,
    task_snapshot,
    task_url,
)
from tests.conftest import ApiEnv

ERROR_KEYS = {"detail", "code"}


class Caller:
    """Запросы от лица человека (cookie) или агента (ключ)."""

    def __init__(self, env: ApiEnv, headers: dict[str, str]) -> None:
        self.env = env
        self.headers = headers

    async def __call__(
        self, method: str, url: str, body: Any = None, *, raw: bytes | None = None
    ) -> httpx.Response:
        kwargs: dict[str, Any] = {}
        headers = dict(self.headers)
        if raw is not None:
            kwargs["content"] = raw
            headers["Content-Type"] = "application/json"
        elif body is not None:
            kwargs["json"] = body
        return await self.env.client.request(method, url, headers=headers, **kwargs)


def human(env: ApiEnv, w: World007, who: str) -> Caller:
    return Caller(env, env.auth(w.cookie(who)))


def agent(env: ApiEnv, key: Any) -> Caller:
    return Caller(env, bearer(key.secret))


def assert_error(r: httpx.Response, status: int, code: str | None = None) -> None:
    """Статус, код и ровно ключи ``detail``, ``code`` (FR-28, 001/FR-45)."""
    assert r.status_code == status, (r.status_code, r.text)
    body = r.json()
    assert set(body) == ERROR_KEYS, body
    if code is not None:
        assert body["code"] == code, body


async def card(env: ApiEnv, w: World007, tid: Any, who: str = "ba1") -> dict[str, Any]:
    r = await human(env, w, who)("GET", task_url(tid))
    assert r.status_code == 200, r.status_code
    return dict(r.json())


async def board_column_ids(env: ApiEnv, w: World007, status: str) -> list[str]:
    r = await human(env, w, "ba1")("GET", board_url(w.P))
    assert r.status_code == 200, r.status_code
    (col,) = [c for c in r.json()["columns"] if c["status"] == status]
    return [c["id"] for c in col["tasks"]]


async def board_status_of(env: ApiEnv, w: World007, tid: Any) -> list[str]:
    """Статусы колонок доски P, в которых есть карточка ``tid`` (ожидается ровно одна)."""
    r = await human(env, w, "ba1")("GET", board_url(w.P))
    assert r.status_code == 200, r.status_code
    return [c["status"] for c in r.json()["columns"] if str(tid) in {t["id"] for t in c["tasks"]}]


async def project_list_ids(env: ApiEnv, w: World007, who: str = "ba1") -> set[str]:
    r = await human(env, w, who)("GET", f"{project_tasks_url(w.P)}?page_size=100")
    assert r.status_code == 200, r.status_code
    return {i["id"] for i in r.json()["items"]}


async def create_t4(env: ApiEnv, w: World007) -> uuid.UUID:
    """T4 - задача agent.u себе (данные AC-22)."""
    r = await agent(env, w.K_u)(
        "POST",
        project_tasks_url(w.P),
        {"title": "Отчёт", "description": "Собрать метрики", "due_date": "2026-11-02"},
    )
    assert r.status_code == 201, (r.status_code, r.text)
    return uuid.UUID(r.json()["id"])


async def task_events(env: ApiEnv, w: World007, tid: Any) -> list[Any]:
    return [e for e in await domain_events(env, w.ws.id) if e.entity_id == tid]


# --- AC-22 ------------------------------------------------------------------------------------


async def test_007_ac22_agent_creates_task_visible_to_ba1(api_env: ApiEnv) -> None:
    """AC-22 (FR-23, FR-29): K_u создаёт «Отчёт» -> 201, автор и исполнитель agent.u, todo,
    medium; ba1 видит задачу в карточке, в списке P и на доске в колонке todo."""
    env = api_env
    w = await make_world007(env)
    before = await project_task_count(env, w.P)
    r = await agent(env, w.K_u)(
        "POST",
        project_tasks_url(w.P),
        {"title": "Отчёт", "description": "Собрать метрики", "due_date": "2026-11-02"},
    )
    assert r.status_code == 201, (r.status_code, r.text)
    body = r.json()
    tid = body["id"]
    assert body["author"]["id"] == str(w.agent_u.id)
    assert body["assignee"]["id"] == str(w.agent_u.id)
    assert body["status"] == "todo"
    assert body["priority"] == "medium"
    assert body["parent_id"] is None
    assert body["project"]["id"] == str(w.P)
    assert await project_task_count(env, w.P) == before + 1

    c = await card(env, w, tid)
    assert (c["title"], c["description"], c["due_date"]) == (
        "Отчёт",
        "Собрать метрики",
        "2026-11-02",
    )
    assert c["author"]["id"] == str(w.agent_u.id)
    assert c["author"]["login"] == "agent.u"
    assert c["assignee"]["id"] == str(w.agent_u.id)
    assert (c["status"], c["priority"]) == ("todo", "medium")
    assert tid in await project_list_ids(env, w)
    assert tid in await board_column_ids(env, w, "todo")
    assert await board_status_of(env, w, tid) == ["todo"]


# --- AC-23 ------------------------------------------------------------------------------------

_VALID = {"title": "Отчёт", "description": "Собрать метрики", "due_date": "2026-11-02"}
AC23_INVALID: list[tuple[str, dict[str, Any]]] = [
    ("без описания", {"title": "Отчёт", "due_date": "2026-11-02"}),
    ("описание из пробелов", {**_VALID, "description": "   \t  "}),
    ("без срока", {"title": "Отчёт", "description": "Собрать метрики"}),
    ("срок 02.11.2026", {**_VALID, "due_date": "02.11.2026"}),
    ("срок 2026-02-30", {**_VALID, "due_date": "2026-02-30"}),
    ("название 256 символов", {**_VALID, "title": "я" * 256}),
    ("лишнее поле status", {**_VALID, "status": "done"}),
]


@pytest.mark.parametrize(("case", "payload"), AC23_INVALID, ids=[c for c, _ in AC23_INVALID])
async def test_007_ac23_invalid_create_is_validation_error(
    api_env: ApiEnv, case: str, payload: dict[str, Any]
) -> None:
    """AC-23 (FR-23, 006): семь случаев -> 422 validation_error, число задач P прежнее."""
    env = api_env
    w = await make_world007(env)
    before = await project_task_count(env, w.P)
    r = await agent(env, w.K_u)("POST", project_tasks_url(w.P), payload)
    assert_error(r, 422, "validation_error")
    assert await project_task_count(env, w.P) == before, case


async def test_007_ac23_due_date_in_past_and_boundary(api_env: ApiEnv) -> None:
    """AC-23: срок 2026-11-01 (вчера по Москве) -> 422 due_date_in_past, задач не прибавилось;
    255 символов в названии и срок «сегодня» - граница допустимого (201)."""
    env = api_env
    w = await make_world007(env)
    ku = agent(env, w.K_u)
    before = await project_task_count(env, w.P)
    r = await ku("POST", project_tasks_url(w.P), {**_VALID, "due_date": "2026-11-01"})
    assert_error(r, 422, "due_date_in_past")
    assert await project_task_count(env, w.P) == before
    r = await ku("POST", project_tasks_url(w.P), {**_VALID, "title": "я" * 255})
    assert r.status_code == 201, (r.status_code, r.text)
    assert await project_task_count(env, w.P) == before + 1


# --- AC-24 ------------------------------------------------------------------------------------


AC24_REFUSALS: list[tuple[str, str, str, str | None, int, str]] = [
    # (случай, ключ, проект, исполнитель, статус, код); исполнитель: имя из мира, None - явный null
    ("u-исполнитель u1", "K_u", "P", "u1", 403, "forbidden"),
    ("u-явный пустой исполнитель", "K_u", "P", None, 403, "forbidden"),
    ("ba-исполнитель не из P", "K_ba", "P", "outsider", 422, "not_project_member"),
    ("ba-исполнитель ta1", "K_ba", "P", "ta1", 422, "recipient_wrong_role"),
    ("u-в P2", "K_u", "P2", "omit", 403, "forbidden"),
]


@pytest.mark.parametrize(
    ("case", "key", "project", "assignee", "status", "code"),
    AC24_REFUSALS,
    ids=[c[0] for c in AC24_REFUSALS],
)
async def test_007_ac24_create_refusals(
    api_env: ApiEnv,
    case: str,
    key: str,
    project: str,
    assignee: str | None,
    status: int,
    code: str,
) -> None:
    """AC-24 (FR-23, FR-3): пять отказов с ожидаемыми кодами; задача не создана."""
    env = api_env
    w = await make_world007(env)
    outsider = await env.new_user(workspace=w.ws, login="outsider", role="user")
    people = {"u1": w.u1.id, "ta1": w.ta1.id, "outsider": outsider.id}
    payload: dict[str, Any] = dict(_VALID)
    if assignee is None:
        payload["assignee_id"] = None
    elif assignee != "omit":
        payload["assignee_id"] = str(people[assignee])
    pid = getattr(w, project)
    before = await project_task_count(env, pid)
    r = await agent(env, getattr(w, key))("POST", project_tasks_url(pid), payload)
    assert_error(r, status, code)
    assert await project_task_count(env, pid) == before, case


async def test_007_ac24_ba_agent_assigns_u1(api_env: ApiEnv) -> None:
    """AC-24: agent.ba создаёт задачу с исполнителем u1 -> 201, исполнитель u1, автор agent.ba."""
    env = api_env
    w = await make_world007(env)
    before = await project_task_count(env, w.P)
    r = await agent(env, w.K_ba)(
        "POST", project_tasks_url(w.P), {**_VALID, "assignee_id": str(w.u1.id)}
    )
    assert r.status_code == 201, (r.status_code, r.text)
    body = r.json()
    assert body["assignee"]["id"] == str(w.u1.id)
    assert body["author"]["id"] == str(w.agent_ba.id)
    assert (await card(env, w, body["id"]))["assignee"]["id"] == str(w.u1.id)
    assert await project_task_count(env, w.P) == before + 1


# --- AC-25 ------------------------------------------------------------------------------------


async def test_007_ac25_subtasks_by_key(api_env: ApiEnv) -> None:
    """AC-25 (FR-24): подзадача к T1 только с названием -> 201, автор и исполнитель agent.u;
    подзадача к подзадаче -> 422 subtask_depth_exceeded; к T2 -> 403."""
    env = api_env
    w = await make_world007(env)
    ku = agent(env, w.K_u)
    r = await ku("POST", subtasks_url(w.T1), {"title": "Шаг 1"})
    assert r.status_code == 201, (r.status_code, r.text)
    sub = r.json()
    assert sub["parent_id"] == str(w.T1)
    assert sub["author"]["id"] == str(w.agent_u.id)
    assert sub["assignee"]["id"] == str(w.agent_u.id)
    assert sub["status"] == "todo"
    parent = await card(env, w, w.T1)
    assert sub["id"] in {s["id"] for s in parent["subtasks"]}

    before = await project_task_count(env, w.P)
    r = await ku("POST", subtasks_url(sub["id"]), {"title": "Шаг 1.1"})
    assert_error(r, 422, "subtask_depth_exceeded")
    r = await ku("POST", subtasks_url(w.T2), {"title": "Чужое"})
    assert_error(r, 403, "forbidden")
    assert await project_task_count(env, w.P) == before


# --- AC-26 ------------------------------------------------------------------------------------


async def test_007_ac26_status_steps_visible_in_card_and_board(api_env: ApiEnv) -> None:
    """AC-26 (FR-25): T1 -> in_progress, review, done, todo; каждый ответ 200; после каждого шага
    карточка у ba1 - новый статус, на доске P T1 ровно в колонке этого статуса."""
    env = api_env
    w = await make_world007(env)
    ku = agent(env, w.K_u)
    for status in ("in_progress", "review", "done", "todo"):
        r = await ku("PATCH", task_url(w.T1), {"status": status})
        assert r.status_code == 200, (status, r.status_code, r.text)
        assert r.json()["status"] == status
        assert (await card(env, w, w.T1))["status"] == status
        assert await board_status_of(env, w, w.T1) == [status], status
        assert str(w.T1) in await board_column_ids(env, w, status)


# --- AC-27 ------------------------------------------------------------------------------------


async def test_007_ac27_close_shows_done_in_my_tasks(api_env: ApiEnv) -> None:
    """AC-27 (FR-25): agent.u закрывает T1 -> в «моих задачах» agent.u T1 со статусом done."""
    env = api_env
    w = await make_world007(env)
    ku = agent(env, w.K_u)
    r = await ku("PATCH", task_url(w.T1), {"status": "done"})
    assert r.status_code == 200, (r.status_code, r.text)
    r = await ku("GET", f"{MY_TASKS_URL}?page_size=100")
    assert r.status_code == 200, r.status_code
    mine = {i["id"]: i["status"] for i in r.json()["items"]}
    assert mine.get(str(w.T1)) == "done"


async def test_007_ac27_close_with_open_subtask_allowed(api_env: ApiEnv) -> None:
    """AC-27 (001/FR-22): у T1 незакрытая подзадача -> закрытие T1 по ключу 200, подзадача
    осталась незакрытой."""
    env = api_env
    w = await make_world007(env)
    ku = agent(env, w.K_u)
    r = await ku("POST", subtasks_url(w.T1), {"title": "Не закрыта"})
    assert r.status_code == 201, (r.status_code, r.text)
    sub = r.json()["id"]
    r = await ku("PATCH", task_url(w.T1), {"status": "done"})
    assert r.status_code == 200, (r.status_code, r.text)
    body = r.json()
    assert body["status"] == "done"
    assert {s["id"]: s["status"] for s in body["subtasks"]}[sub] == "todo"
    assert (await card(env, w, w.T1))["status"] == "done"


# --- AC-28 ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad", ["closed", "DONE", "", None], ids=["closed", "DONE", "empty", "null"]
)
async def test_007_ac28_invalid_status_is_validation_error(api_env: ApiEnv, bad: Any) -> None:
    """AC-28 (FR-25): closed, DONE, "", null -> 422 validation_error, T1 не изменилась."""
    env = api_env
    w = await make_world007(env)
    before = await task_snapshot(env, w.T1)
    r = await agent(env, w.K_u)("PATCH", task_url(w.T1), {"status": bad})
    assert_error(r, 422, "validation_error")
    after = await task_snapshot(env, w.T1)
    assert after["status"] == "todo"
    assert after == before


async def test_007_ac28_same_status_is_ok_without_changes(api_env: ApiEnv) -> None:
    """AC-28: T1 в todo, agent.u ставит todo -> 200, строка задачи не изменилась, событий по T1
    нет (основная проверка событий - test_agent_events_007.py)."""
    env = api_env
    w = await make_world007(env)
    before = await task_snapshot(env, w.T1)
    events_before = len(await task_events(env, w, w.T1))
    r = await agent(env, w.K_u)("PATCH", task_url(w.T1), {"status": "todo"})
    assert r.status_code == 200, (r.status_code, r.text)
    assert r.json()["status"] == "todo"
    assert await task_snapshot(env, w.T1) == before
    assert len(await task_events(env, w, w.T1)) == events_before


# --- AC-29 ------------------------------------------------------------------------------------


async def test_007_ac29_status_change_with_stale_due_and_empty_description(
    api_env: ApiEnv,
) -> None:
    """AC-29 (FR-25, 006/FR-23): T3 (срок в прошлом, пустое описание) -> done: 200, срок и
    описание не изменились."""
    env = api_env
    w = await make_world007(env)
    before = await task_snapshot(env, w.T3)
    r = await agent(env, w.K_u)("PATCH", task_url(w.T3), {"status": "done"})
    assert r.status_code == 200, (r.status_code, r.text)
    body = r.json()
    assert body["status"] == "done"
    assert (body["due_date"], body["description"]) == ("2026-10-01", "")
    after = await task_snapshot(env, w.T3)
    assert after["status"] == "done"
    assert after["due_date"] == date(2026, 10, 1) == before["due_date"]
    assert after["description"] == "" == before["description"]
    assert (after["title"], after["priority"], after["assignee_id"]) == (
        before["title"],
        before["priority"],
        before["assignee_id"],
    )


# --- AC-30 ------------------------------------------------------------------------------------


async def test_007_ac30_status_of_foreign_task_by_role(api_env: ApiEnv) -> None:
    """AC-30 (FR-25, FR-3): agent.u меняет статус T2 (исполнитель u1) -> 403, T2 прежняя;
    agent.ba -> 200."""
    env = api_env
    w = await make_world007(env)
    before = await task_snapshot(env, w.T2)
    r = await agent(env, w.K_u)("PATCH", task_url(w.T2), {"status": "in_progress"})
    assert_error(r, 403, "forbidden")
    assert await task_snapshot(env, w.T2) == before
    r = await agent(env, w.K_ba)("PATCH", task_url(w.T2), {"status": "in_progress"})
    assert r.status_code == 200, (r.status_code, r.text)
    assert (await task_snapshot(env, w.T2))["status"] == "in_progress"
    assert (await card(env, w, w.T2))["status"] == "in_progress"


# --- AC-31 ------------------------------------------------------------------------------------


async def test_007_ac31_agent_edits_own_task_fields(api_env: ApiEnv) -> None:
    """AC-31 п.1 (FR-26): agent.u меняет у T4 название, описание, срок 2026-11-10, приоритет
    high -> 200, всё сохранено (видно ba1)."""
    env = api_env
    w = await make_world007(env)
    t4 = await create_t4(env, w)
    patch = {
        "title": "Отчёт v2",
        "description": "Собрать и сравнить метрики",
        "due_date": "2026-11-10",
        "priority": "high",
    }
    r = await agent(env, w.K_u)("PATCH", task_url(t4), patch)
    assert r.status_code == 200, (r.status_code, r.text)
    for got in (r.json(), await card(env, w, t4)):
        assert {k: got[k] for k in patch} == patch
        assert got["assignee"]["id"] == str(w.agent_u.id)
        assert got["status"] == "todo"


AC31_REFUSALS: list[tuple[str, str, str, dict[str, Any], int, str]] = [
    # (случай, ключ, задача, тело, статус, код)
    ("срок 2026-11-01", "K_u", "T4", {"due_date": "2026-11-01"}, 422, "due_date_in_past"),
    ("описание из пробелов", "K_u", "T4", {"description": "   "}, 422, "validation_error"),
    ("исполнитель T4 -> u1", "K_u", "T4", {"assignee_id": "u1"}, 403, "forbidden"),
    ("название T1 (автор ba1)", "K_u", "T1", {"title": "Чужое"}, 403, "forbidden"),
    ("ba снимает исполнителя T2", "K_ba", "T2", {"assignee_id": None}, 422, "validation_error"),
]


AC31_CASES = [
    (*case, with_title)
    for case in AC31_REFUSALS
    for with_title in ((False, True) if case[2] != "T1" else (False,))
]


@pytest.mark.parametrize(
    ("case", "key", "target", "patch", "status", "code", "with_title"),
    AC31_CASES,
    ids=[f"{c[0]}{' +title' if c[6] else ''}" for c in AC31_CASES],
)
async def test_007_ac31_refusals_leave_task_unchanged(
    api_env: ApiEnv,
    case: str,
    key: str,
    target: str,
    patch: dict[str, Any],
    status: int,
    code: str,
    with_title: bool,
) -> None:
    """AC-31 (FR-26, FR-3, 006): отказ -> ожидаемый код; задача не изменилась ни в одном поле.
    Вариант ``+title``: в тело добавлена допустимая правка названия - не применится (всё или
    ничего)."""
    env = api_env
    w = await make_world007(env)
    tid = await create_t4(env, w) if target == "T4" else getattr(w, target)
    body = {k: (str(w.u1.id) if v == "u1" else v) for k, v in patch.items()}
    if with_title:
        body["title"] = "Новое название"
    before = await task_snapshot(env, tid)
    r = await agent(env, getattr(w, key))("PATCH", task_url(tid), body)
    assert_error(r, status, code)
    assert await task_snapshot(env, tid) == before, case


async def test_007_ac31_ba_agent_reassigns_t2(api_env: ApiEnv) -> None:
    """AC-31 (FR-26, 001/FR-19a): agent.ba меняет исполнителя T2 на agent.u -> 200."""
    env = api_env
    w = await make_world007(env)
    r = await agent(env, w.K_ba)("PATCH", task_url(w.T2), {"assignee_id": str(w.agent_u.id)})
    assert r.status_code == 200, (r.status_code, r.text)
    assert r.json()["assignee"]["id"] == str(w.agent_u.id)
    assert (await task_snapshot(env, w.T2))["assignee_id"] == w.agent_u.id
    assert (await card(env, w, w.T2))["assignee"]["id"] == str(w.agent_u.id)


# --- AC-32 ------------------------------------------------------------------------------------


async def test_007_ac32_agent_comment_html_stripped_and_ordered(api_env: ApiEnv) -> None:
    """AC-32 (FR-27, FR-29): комментарий «Готово: <b>см. отчёт</b>» -> 201, автор agent.u, HTML
    вырезан; список T1 по K_u и у ba1 - c1, затем новый (по времени создания)."""
    env = api_env
    w = await make_world007(env)
    env.clock.advance(timedelta(minutes=1))  # c1 создан на CLOCK, новый - позже
    r = await agent(env, w.K_u)("POST", comments_url(w.T1), {"body": "Готово: <b>см. отчёт</b>"})
    assert r.status_code == 201, (r.status_code, r.text)
    new = r.json()
    assert new["body"] == "Готово: см. отчёт"
    assert new["author"]["id"] == str(w.agent_u.id)
    assert new["author"]["is_agent"] is True
    assert new["task_id"] == str(w.T1)

    for who in (agent(env, w.K_u), human(env, w, "ba1")):
        r = await who("GET", comments_url(w.T1))
        assert r.status_code == 200, r.status_code
        items = r.json()["items"]
        assert [i["id"] for i in items] == [str(w.c1), new["id"]]
        assert items[1]["body"] == "Готово: см. отчёт"
        assert items[1]["author"]["id"] == str(w.agent_u.id)


@pytest.mark.parametrize(
    "text", ["я" * 10_001, "", "<b></b>"], ids=["10001_chars", "empty", "only_tag"]
)
async def test_007_ac32_invalid_comment_is_422(api_env: ApiEnv, text: str) -> None:
    """AC-32: 10 001 символ, пустой, из одного HTML-тега -> 422; комментарий не добавлен."""
    env = api_env
    w = await make_world007(env)
    before = await task_comment_count(env, w.T1)
    r = await agent(env, w.K_u)("POST", comments_url(w.T1), {"body": text})
    assert_error(r, 422, "validation_error")
    assert await task_comment_count(env, w.T1) == before


async def test_007_ac32_comment_on_t9_forbidden(api_env: ApiEnv) -> None:
    """AC-32 (FR-27): комментарий к T9 (проект P2, agent.u не участник) -> 403."""
    env = api_env
    w = await make_world007(env)
    before = await task_comment_count(env, w.T9)
    r = await agent(env, w.K_u)("POST", comments_url(w.T9), {"body": "нельзя"})
    assert_error(r, 403, "forbidden")
    assert await task_comment_count(env, w.T9) == before


# --- AC-34 ------------------------------------------------------------------------------------


@pytest.mark.parametrize("op", ["get_card", "patch_status", "comment"])
async def test_007_ac34_soft_deleted_task_is_404(api_env: ApiEnv, op: str) -> None:
    """AC-34 (FR-28, 001/FR-25): T2 мягко удалена ba1 -> карточка, смена статуса, комментарий по
    K_ba -> 404 not_found, тело ровно {detail, code}; статус и комментарии T2 не изменились."""
    env = api_env
    w = await make_world007(env)
    r = await human(env, w, "ba1")("DELETE", task_url(w.T2))
    assert r.status_code == 204, r.status_code
    kba = agent(env, w.K_ba)
    comments_before = await task_comment_count(env, w.T2)
    before = await task_snapshot(env, w.T2)
    assert before["deleted_at"] is not None
    if op == "get_card":
        r = await kba("GET", task_url(w.T2))
    elif op == "patch_status":
        r = await kba("PATCH", task_url(w.T2), {"status": "done"})
    else:
        r = await kba("POST", comments_url(w.T2), {"body": "есть?"})
    assert_error(r, 404, "not_found")
    assert await task_snapshot(env, w.T2) == before
    assert await task_comment_count(env, w.T2) == comments_before


async def test_007_ac34_unknown_task_id_is_404(api_env: ApiEnv) -> None:
    """AC-34: несуществующий идентификатор задачи -> 404 not_found во всех операциях записи."""
    env = api_env
    w = await make_world007(env)
    kba = agent(env, w.K_ba)
    ghost = uuid.uuid4()
    assert_error(await kba("GET", task_url(ghost)), 404, "not_found")
    assert_error(await kba("PATCH", task_url(ghost), {"status": "done"}), 404, "not_found")
    assert_error(await kba("POST", comments_url(ghost), {"body": "x"}), 404, "not_found")
    assert_error(await kba("POST", subtasks_url(ghost), {"title": "x"}), 404, "not_found")
    assert_error(await kba("GET", comments_url(ghost)), 404, "not_found")


async def test_007_ac34_invalid_json_is_400_bad_request(api_env: ApiEnv) -> None:
    """AC-34: тело - невалидный JSON -> 400 bad_request (PATCH, создание задачи, комментарий),
    тело ровно {detail, code}; данные не изменились."""
    env = api_env
    w = await make_world007(env)
    kba = agent(env, w.K_ba)
    before = await task_snapshot(env, w.T1)
    count = await project_task_count(env, w.P)
    comments = await task_comment_count(env, w.T1)
    raw = b'{"status": "done",'
    assert_error(await kba("PATCH", task_url(w.T1), raw=raw), 400, "bad_request")
    assert_error(await kba("POST", project_tasks_url(w.P), raw=raw), 400, "bad_request")
    assert_error(await kba("POST", comments_url(w.T1), raw=b"{not json"), 400, "bad_request")
    assert_error(await kba("POST", subtasks_url(w.T1), raw=b"{not json"), 400, "bad_request")
    assert await task_snapshot(env, w.T1) == before
    assert await project_task_count(env, w.P) == count
    assert await task_comment_count(env, w.T1) == comments


# --- заметка ревью R7-T14: значения «было/стало» в событиях (FR-42, PD-9) ---------------------


async def test_007_fr42_unassign_subtask_writes_str_and_none(api_env: ApiEnv) -> None:
    """FR-42: agent.ba снимает исполнителя подзадачи -> task.updated [assignee_id], changes
    old = str(id agent.u), new = None; ключ K_ba."""
    env = api_env
    w = await make_world007(env)
    r = await agent(env, w.K_u)("POST", subtasks_url(w.T1), {"title": "Подзадача"})
    assert r.status_code == 201, (r.status_code, r.text)
    sub = uuid.UUID(r.json()["id"])
    before = len(await domain_events(env, w.ws.id))
    r = await agent(env, w.K_ba)("PATCH", task_url(sub), {"assignee_id": None})
    assert r.status_code == 200, (r.status_code, r.text)
    assert r.json()["assignee"] is None
    (e,) = (await domain_events(env, w.ws.id))[before:]
    assert (e.action, e.entity_id) == ("task.updated", sub)
    assert e.changed_fields == ["assignee_id"]
    assert e.changes == [{"field": "assignee_id", "old": str(w.agent_u.id), "new": None}]
    assert (e.actor_id, e.api_key_id) == (w.agent_ba.id, w.K_ba.id)


async def test_007_fr42_description_only_change_has_null_changes(api_env: ApiEnv) -> None:
    """FR-42 (PD-22): agent.u правит только описание T4 -> task.updated [description],
    changes IS NULL (значения описания не пишутся)."""
    env = api_env
    w = await make_world007(env)
    t4 = await create_t4(env, w)
    before = len(await domain_events(env, w.ws.id))
    r = await agent(env, w.K_u)("PATCH", task_url(t4), {"description": "Секретные цифры"})
    assert r.status_code == 200, (r.status_code, r.text)
    (e,) = (await domain_events(env, w.ws.id))[before:]
    assert (e.action, e.entity_id) == ("task.updated", t4)
    assert e.changed_fields == ["description"]
    assert e.changes is None
    assert (e.actor_id, e.api_key_id) == (w.agent_u.id, w.K_u.id)


async def test_007_fr42_subtask_status_via_patch(api_env: ApiEnv) -> None:
    """FR-25, FR-42: agent.u меняет статус своей подзадачи через PATCH -> 200, статус в карточке
    родителя, событие task.updated [status] todo -> done с ключом K_u."""
    env = api_env
    w = await make_world007(env)
    ku = agent(env, w.K_u)
    r = await ku("POST", subtasks_url(w.T1), {"title": "Подзадача"})
    assert r.status_code == 201, (r.status_code, r.text)
    sub = uuid.UUID(r.json()["id"])
    before = len(await domain_events(env, w.ws.id))
    r = await ku("PATCH", task_url(sub), {"status": "done"})
    assert r.status_code == 200, (r.status_code, r.text)
    assert r.json()["status"] == "done"
    parent = await card(env, w, w.T1)
    assert {s["id"]: s["status"] for s in parent["subtasks"]}[str(sub)] == "done"
    (e,) = (await domain_events(env, w.ws.id))[before:]
    assert (e.action, e.entity_id) == ("task.updated", sub)
    assert e.changed_fields == ["status"]
    assert e.changes == [{"field": "status", "old": "todo", "new": "done"}]
    assert (e.actor_id, e.api_key_id) == (w.agent_u.id, w.K_u.id)


CONCURRENT_ROUNDS = 5


def _assert_chain(events: list[Any], start: str, field: str = "status") -> None:
    """«Было» каждого события равно «стало» предыдущего; первое «было» - исходное значение."""
    prev = start
    for e in events:
        assert e.action == "task.updated"
        (change,) = e.changes
        assert change["field"] == field
        assert change["old"] == prev, (change, prev)
        assert change["new"] != change["old"]
        prev = change["new"]


@pytest.mark.committed
async def test_007_fr42_concurrent_patches_chain_old_values(committed_api_env: ApiEnv) -> None:
    """FR-42 (заметка ревью R7-T14): два параллельных PATCH статуса одной карточки по ключам
    K_u и K_ba -> оба 200; changes[0].old второго события равен new первого (строка читается
    под блокировкой, «было» не устаревает)."""
    env = committed_api_env
    w = await make_world007(env)
    ku, kba = agent(env, w.K_u), agent(env, w.K_ba)
    start = "todo"
    for i in range(CONCURRENT_ROUNDS):
        targets = ("in_progress", "review") if i % 2 == 0 else ("done", "todo")
        if start in targets:
            targets = ("review", "done")
        before = len(await task_events(env, w, w.T1))
        r1, r2 = await asyncio.gather(
            ku("PATCH", task_url(w.T1), {"status": targets[0]}),
            kba("PATCH", task_url(w.T1), {"status": targets[1]}),
        )
        assert (r1.status_code, r2.status_code) == (200, 200), (i, r1.text, r2.text)
        new = (await task_events(env, w, w.T1))[before:]
        assert len(new) == 2, (i, len(new))
        _assert_chain(new, start)
        final = (await task_snapshot(env, w.T1))["status"]
        assert final == new[-1].changes[0]["new"]
        start = final


@pytest.mark.committed
async def test_007_fr42_concurrent_moves_chain_old_values(committed_api_env: ApiEnv) -> None:
    """FR-42 (заметка ревью R7-T14, PD-23): два параллельных переноса T2 по доске (ba1 и u1) в
    разные колонки -> оба 204; «было» второго события равно «стало» первого."""
    env = committed_api_env
    w = await make_world007(env)
    ba, u1 = human(env, w, "ba1"), human(env, w, "u1")
    move = f"{API}/tasks/{w.T2}/move"
    start = "todo"
    for i in range(CONCURRENT_ROUNDS):
        targets = [s for s in ("in_progress", "review", "done", "todo") if s != start][:2]
        before = len(await task_events(env, w, w.T2))
        r1, r2 = await asyncio.gather(
            ba("POST", move, {"status": targets[0]}),
            u1("POST", move, {"status": targets[1]}),
        )
        assert (r1.status_code, r2.status_code) == (204, 204), (i, r1.text, r2.text)
        new = (await task_events(env, w, w.T2))[before:]
        assert len(new) == 2, (i, len(new))
        _assert_chain(new, start)
        final = (await task_snapshot(env, w.T2))["status"]
        assert final == new[-1].changes[0]["new"]
        start = final
