"""R7-T14: события задач и комментариев для всех авторов (007/FR-42, FR-29, FR-30).

AC-35 (три события агента, идентификатор ключа), AC-28 (тот же статус - события нет), AC-43
(часть про события через обычный API), AC-49 и AC-50 (люди через обычный API), AC-51 (приоритет),
AC-52 (перенос по доске), AC-53 (каскадное удаление без ``comment.deleted``);
plan §4.8, PD-9, PD-22, PD-23, PD-24. Демо-данные событий не получают - проверяет существующий
``cli/test_demo_data.py::test_d55_no_project_or_task_events`` (здесь не дублируется).

Чтение хранилища - SQL по ``workspace_id``, порядок по ``id``; «новых событий нет» - сравнение
числа строк до и после. Секрет ключа в сообщения ``assert`` не попадает.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text

from tests.agents007_support import (
    AUDIT,
    World007,
    bearer,
    domain_events,
    make_world007,
)
from tests.conftest import ApiEnv
from tests.factories import make_comment, make_task

API = "/api/v1"
BASELINE = Path(__file__).parent / "openapi_baseline_f7f19cf.json"


def project_tasks(pid: Any) -> str:
    return f"{API}/projects/{pid}/tasks"


def task_url(tid: Any) -> str:
    return f"{API}/tasks/{tid}"


def comments_url(tid: Any) -> str:
    return f"{API}/tasks/{tid}/comments"


def comment_url(cid: Any) -> str:
    return f"{API}/comments/{cid}"


def move_url(tid: Any) -> str:
    return f"{API}/tasks/{tid}/move"


def board_url(pid: Any) -> str:
    return f"{API}/projects/{pid}/board"


class Caller:
    """Запросы от лица ``ba1``/``u1`` (cookie) или агента (ключ)."""

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


async def count(env: ApiEnv, w: World007) -> int:
    return len(await domain_events(env, w.ws.id))


async def since(env: ApiEnv, w: World007, before: int) -> list[Any]:
    return (await domain_events(env, w.ws.id))[before:]


def shape(events: list[Any]) -> list[tuple[str, uuid.UUID]]:
    return [(e.action, e.entity_id) for e in events]


def assert_by(events: list[Any], w: World007, *, actor: Any, key: Any = None) -> None:
    """Автор, проект P, идентификатор ключа и ``in_audit = false`` у каждого события."""
    for e in events:
        assert e.actor_id == actor.id, e.action
        assert e.project_id == w.P, e.action
        assert e.in_audit is False, e.action
        assert e.workspace_id == w.ws.id, e.action
        if key is None:
            assert e.api_key_id is None, e.action
        else:
            assert e.api_key_id == key.id, e.action


async def task_cols(env: ApiEnv, tid: Any) -> Any:
    rows = await env.execute(
        text(
            "SELECT status, priority, due_date, description, title, deleted_at FROM task "
            "WHERE id = :t"
        ).bindparams(t=tid)
    )
    assert rows
    return rows[0]


async def comment_deleted_at(env: ApiEnv, cid: Any) -> Any:
    rows = await env.execute(text("SELECT deleted_at FROM comment WHERE id = :c").bindparams(c=cid))
    assert rows
    return rows[0][0]


# --- AC-35 ------------------------------------------------------------------------------------


async def test_007_ac35_agent_by_key_writes_three_events_with_key_id(api_env: ApiEnv) -> None:
    """AC-35 (FR-29, FR-30): K_u создаёт задачу, ставит in_progress, комментирует -> ровно три
    новых события; автор agent.u, api_key_id = K_u, in_audit = false, секрета нет."""
    env = api_env
    w = await make_world007(env)
    ku = agent(env, w.K_u)
    before = await count(env, w)

    r = await ku(
        "POST",
        project_tasks(w.P),
        {"title": "Отчёт", "description": "Описание", "due_date": "2026-11-10"},
    )
    assert r.status_code == 201, r.status_code
    tid = uuid.UUID(r.json()["id"])
    r = await ku("PATCH", task_url(tid), {"status": "in_progress"})
    assert r.status_code == 200, r.status_code
    r = await ku("POST", comments_url(tid), {"body": "Готово"})
    assert r.status_code == 201, r.status_code
    cid = uuid.UUID(r.json()["id"])

    written = await since(env, w, before)
    assert [e.action for e in written] == ["task.created", "task.updated", "comment.created"]
    assert shape(written) == [
        ("task.created", tid),
        ("task.updated", tid),
        ("comment.created", cid),
    ]
    assert [e.entity_type for e in written] == ["task", "task", "comment"]
    assert_by(written, w, actor=w.agent_u, key=w.K_u)
    assert written[1].changed_fields == ["status"]
    assert written[1].changes == [{"field": "status", "old": "todo", "new": "in_progress"}]
    leaked = w.K_u.secret in repr([tuple(e) for e in written])
    assert not leaked, "секрет ключа попал в столбцы событий"


async def test_007_ac35_human_status_change_has_no_key_id(api_env: ApiEnv) -> None:
    """AC-35: ba1 по cookie меняет статус T2 -> task.updated, автор ba1, api_key_id IS NULL."""
    env = api_env
    w = await make_world007(env)
    before = await count(env, w)
    r = await human(env, w, "ba1")("PATCH", task_url(w.T2), {"status": "in_progress"})
    assert r.status_code == 200, r.status_code
    (e,) = await since(env, w, before)
    assert (e.action, e.entity_id) == ("task.updated", w.T2)
    assert e.changed_fields == ["status"]
    assert_by([e], w, actor=w.ba1)


async def test_007_ac35_subtask_by_key_writes_task_created(api_env: ApiEnv) -> None:
    """AC-35 (FR-42): подзадача по ключу -> task.created с автором-агентом и ключом."""
    env = api_env
    w = await make_world007(env)
    ku = agent(env, w.K_u)
    r = await ku(
        "POST",
        project_tasks(w.P),
        {"title": "Родитель", "description": "d", "due_date": "2026-11-10"},
    )
    assert r.status_code == 201, r.status_code
    parent = uuid.UUID(r.json()["id"])
    before = await count(env, w)
    r = await ku("POST", f"{task_url(parent)}/subtasks", {"title": "Подзадача"})
    assert r.status_code == 201, r.status_code
    sub = uuid.UUID(r.json()["id"])
    (e,) = await since(env, w, before)
    assert (e.action, e.entity_id, e.entity_type) == ("task.created", sub, "task")
    assert_by([e], w, actor=w.agent_u, key=w.K_u)


# --- AC-28 ------------------------------------------------------------------------------------


async def test_007_ac28_same_status_by_key_writes_no_event(api_env: ApiEnv) -> None:
    """AC-28 (D-46, FR-42): T1 в todo, agent.u ставит todo -> 200, событий нет."""
    env = api_env
    w = await make_world007(env)
    before = await count(env, w)
    r = await agent(env, w.K_u)("PATCH", task_url(w.T1), {"status": "todo"})
    assert r.status_code == 200, r.status_code
    assert await count(env, w) == before


# --- AC-43 (часть про события, через обычный API) ---------------------------------------------


async def test_007_ac43_five_agent_calls_write_events_with_key(api_env: ApiEnv) -> None:
    """AC-43 (часть событий): создать, in_progress, review, комментарий, done -> по событию на
    каждый вызов, у всех автор agent.u и api_key_id = K_u (сквозная проверка через MCP - R7-T18)."""
    env = api_env
    w = await make_world007(env)
    ku = agent(env, w.K_u)
    before = await count(env, w)
    r = await ku(
        "POST",
        project_tasks(w.P),
        {"title": "Сквозная", "description": "d", "due_date": "2026-11-10"},
    )
    assert r.status_code == 201, r.status_code
    tid = uuid.UUID(r.json()["id"])
    for status in ("in_progress", "review"):
        assert (await ku("PATCH", task_url(tid), {"status": status})).status_code == 200
    assert (await ku("POST", comments_url(tid), {"body": "Результат: ок"})).status_code == 201
    assert (await ku("PATCH", task_url(tid), {"status": "done"})).status_code == 200

    written = await since(env, w, before)
    assert [e.action for e in written] == [
        "task.created",
        "task.updated",
        "task.updated",
        "comment.created",
        "task.updated",
    ]
    assert_by(written, w, actor=w.agent_u, key=w.K_u)
    updates = [e.changes for e in written if e.action == "task.updated"]
    assert updates == [
        [{"field": "status", "old": "todo", "new": "in_progress"}],
        [{"field": "status", "old": "in_progress", "new": "review"}],
        [{"field": "status", "old": "review", "new": "done"}],
    ]


# --- AC-49 ------------------------------------------------------------------------------------


async def test_007_ac49_ba1_seven_steps_write_exactly_five_events(api_env: ApiEnv) -> None:
    """AC-49 (FR-42): семь шагов ba1 -> ровно пять событий в заданном порядке; шаги 4 и 6 событий
    не добавили; автор ba1, проект P, без api_key_id."""
    env = api_env
    w = await make_world007(env)
    ba = human(env, w, "ba1")
    before = await count(env, w)

    r = await ba(
        "POST",
        project_tasks(w.P),
        {
            "title": "T5",
            "description": "Описание T5",
            "due_date": "2026-11-05",
            "assignee_id": str(w.u1.id),
        },
    )
    assert r.status_code == 201, r.status_code
    t5 = uuid.UUID(r.json()["id"])
    r = await ba("POST", f"{task_url(t5)}/subtasks", {"title": "T5.1"})
    assert r.status_code == 201, r.status_code
    t51 = uuid.UUID(r.json()["id"])
    r = await ba("PATCH", task_url(t5), {"title": "T5 новое", "due_date": "2026-11-06"})
    assert r.status_code == 200, r.status_code
    after_step3 = await count(env, w)
    r = await ba("PATCH", task_url(t5), {"title": "T5 новое", "due_date": "2026-11-06"})
    assert r.status_code == 200, r.status_code  # шаг 4
    assert await count(env, w) == after_step3
    r = await ba("POST", comments_url(t5), {"body": "c5"})
    assert r.status_code == 201, r.status_code
    c5 = uuid.UUID(r.json()["id"])
    after_step5 = await count(env, w)
    r = await ba("PATCH", comment_url(c5), {"body": "c5 правка"})
    assert r.status_code == 200, r.status_code  # шаг 6
    assert await count(env, w) == after_step5
    r = await ba("DELETE", comment_url(c5))
    assert r.status_code == 204, r.status_code

    written = await since(env, w, before)
    assert shape(written) == [
        ("task.created", t5),
        ("task.created", t51),
        ("task.updated", t5),
        ("comment.created", c5),
        ("comment.deleted", c5),
    ]
    assert_by(written, w, actor=w.ba1)
    assert written[2].changed_fields == ["due_date", "title"]  # порядок EVENT_FIELDS
    assert written[2].changes == [{"field": "due_date", "old": "2026-11-05", "new": "2026-11-06"}]


async def test_007_ac49_assignee_status_change_one_event_and_audit_clean(
    api_env: ApiEnv,
) -> None:
    """AC-49: u1 (исполнитель T2) меняет статус -> одно task.updated [status], автор u1, без
    ключа; ta1 в журнале аудита не видит ни одного события задач и комментариев."""
    env = api_env
    w = await make_world007(env)
    ba = human(env, w, "ba1")
    r = await ba("POST", comments_url(w.T2), {"body": "x"})
    assert r.status_code == 201, r.status_code
    before = await count(env, w)
    r = await human(env, w, "u1")("PATCH", task_url(w.T2), {"status": "in_progress"})
    assert r.status_code == 200, r.status_code
    (e,) = await since(env, w, before)
    assert (e.action, e.entity_id) == ("task.updated", w.T2)
    assert e.changed_fields == ["status"]
    assert_by([e], w, actor=w.u1)

    entries: list[dict[str, Any]] = []
    page = 1
    ta = human(env, w, "ta1")
    while True:
        r = await ta("GET", f"{AUDIT}?page={page}&page_size=100")
        assert r.status_code == 200, r.status_code
        body = r.json()
        entries += body["items"]
        if not body["has_next"]:
            break
        page += 1
    event_ids = {str(x.entity_id) for x in await domain_events(env, w.ws.id)}
    assert event_ids  # события есть, поэтому проверка ниже не пуста
    assert not [
        i
        for i in entries
        if i["action"].startswith(("task.", "comment.")) or i["entity_type"] in ("task", "comment")
    ]
    assert not [i for i in entries if i["entity_id"] in event_ids]


async def test_007_ac49_task_and_comment_response_format_unchanged(api_env: ApiEnv) -> None:
    """AC-49: ключи верхнего уровня карточки T5 и элемента комментариев - ровно свойства схем
    TaskDetail/Comment на f7f19cf (ни событий, ни ленты в ответах)."""
    env = api_env
    w = await make_world007(env)
    schemas = json.loads(BASELINE.read_text())["components"]["schemas"]
    ba = human(env, w, "ba1")
    r = await ba(
        "POST",
        project_tasks(w.P),
        {"title": "T5", "description": "d", "due_date": "2026-11-05"},
    )
    assert r.status_code == 201, r.status_code
    t5 = r.json()["id"]
    assert (await ba("POST", comments_url(t5), {"body": "c5"})).status_code == 201
    card = await ba("GET", task_url(t5))
    assert card.status_code == 200, card.status_code
    assert set(card.json()) == set(schemas["TaskDetail"]["properties"])
    listing = await ba("GET", comments_url(t5))
    assert listing.status_code == 200, listing.status_code
    (item,) = listing.json()["items"]
    assert set(item) == set(schemas["Comment"]["properties"])


# --- AC-50 ------------------------------------------------------------------------------------


async def test_007_ac50_refusals_write_no_events_and_delete_without_comments_neither(
    api_env: ApiEnv,
) -> None:
    """AC-50 (FR-42): шесть отказов (422, 422 due_date_in_past, 403, 403, 400, 404) событий не
    пишут; удаление T2 без комментариев - 204 без событий."""
    env = api_env
    w = await make_world007(env)
    ba, u1 = human(env, w, "ba1"), human(env, w, "u1")
    before = await count(env, w)

    r = await ba("POST", project_tasks(w.P), {"title": "Без описания", "due_date": "2026-11-05"})
    assert r.status_code == 422, r.status_code
    r = await ba("PATCH", task_url(w.T2), {"due_date": "2026-11-01"})
    assert r.status_code == 422, r.status_code
    assert r.json()["code"] == "due_date_in_past"
    r = await u1("PATCH", task_url(w.T1), {"title": "Чужое"})
    assert r.status_code == 403, r.status_code
    r = await u1("POST", comments_url(w.T9), {"body": "нельзя"})
    assert r.status_code == 403, r.status_code
    r = await ba("PATCH", task_url(w.T2), raw=b"{not json")
    assert r.status_code == 400, r.status_code
    r = await ba("DELETE", comment_url(uuid.uuid4()))
    assert r.status_code == 404, r.status_code
    assert await count(env, w) == before

    r = await ba("DELETE", task_url(w.T2))
    assert r.status_code == 204, r.status_code
    assert await count(env, w) == before


# --- AC-51 ------------------------------------------------------------------------------------


async def test_007_ac51_priority_events(api_env: ApiEnv) -> None:
    """AC-51 (FR-42, Q-11, PD-22): только приоритет -> task.updated [priority]; повтор - нет
    события; название + приоритет -> [priority, title]; urgent -> 422 без события."""
    env = api_env
    w = await make_world007(env)
    ba = human(env, w, "ba1")
    before = await count(env, w)

    r = await ba("PATCH", task_url(w.T2), {"priority": "high"})
    assert r.status_code == 200, r.status_code
    (e1,) = await since(env, w, before)
    assert (e1.action, e1.entity_id) == ("task.updated", w.T2)
    assert e1.changed_fields == ["priority"]
    assert e1.changes == [{"field": "priority", "old": "medium", "new": "high"}]
    assert_by([e1], w, actor=w.ba1)

    r = await ba("PATCH", task_url(w.T2), {"priority": "high"})
    assert r.status_code == 200, r.status_code
    assert await count(env, w) == before + 1

    r = await ba("PATCH", task_url(w.T2), {"title": "T2 новое", "priority": "low"})
    assert r.status_code == 200, r.status_code
    written = await since(env, w, before)
    assert len(written) == 2
    e3 = written[1]
    assert (e3.action, e3.entity_id) == ("task.updated", w.T2)
    assert e3.changed_fields == ["priority", "title"]
    assert e3.changes == [{"field": "priority", "old": "high", "new": "low"}]

    r = await ba("PATCH", task_url(w.T2), {"priority": "urgent"})
    assert r.status_code == 422, r.status_code
    assert r.json()["code"] == "validation_error"
    assert (await task_cols(env, w.T2)).priority == "low"
    assert await count(env, w) == before + 2


async def test_007_ac51_agent_changes_only_priority_with_stale_fields(api_env: ApiEnv) -> None:
    """AC-51 (FR-26, 006/FR-23): agent.u по K_u меняет у T3 только приоритет -> 200, одно событие
    с ключом; срок в прошлом и пустое описание не мешают и не изменились."""
    env = api_env
    w = await make_world007(env)
    before = await count(env, w)
    r = await agent(env, w.K_u)("PATCH", task_url(w.T3), {"priority": "high"})
    assert r.status_code == 200, r.status_code
    (e,) = await since(env, w, before)
    assert (e.action, e.entity_id) == ("task.updated", w.T3)
    assert e.changed_fields == ["priority"]
    assert e.changes == [{"field": "priority", "old": "medium", "new": "high"}]
    assert_by([e], w, actor=w.agent_u, key=w.K_u)
    row = await task_cols(env, w.T3)
    assert row.due_date == date(2026, 10, 1)
    assert row.description == ""
    assert row.priority == "high"


# --- AC-52 ------------------------------------------------------------------------------------


async def _todo_order(env: ApiEnv, who: Caller, w: World007) -> list[str]:
    r = await who("GET", board_url(w.P))
    assert r.status_code == 200, r.status_code
    (col,) = [c for c in r.json()["columns"] if c["status"] == "todo"]
    return [c["id"] for c in col["tasks"]]


async def test_007_ac52_board_move_events(api_env: ApiEnv) -> None:
    """AC-52 (FR-42, Q-12, PD-23): внутри колонки - без события; в другую колонку - одно
    task.updated [status]; 422 invalid_neighbors и 403 - без события."""
    env = api_env
    w = await make_world007(env)
    ba, u1 = human(env, w, "ba1"), human(env, w, "u1")
    assert await _todo_order(env, ba, w) == [str(w.T1), str(w.T2)]
    before = await count(env, w)

    r = await ba("POST", move_url(w.T2), {"status": "todo", "before_task_id": str(w.T1)})
    assert r.status_code == 204, r.status_code
    assert await _todo_order(env, ba, w) == [str(w.T2), str(w.T1)]
    assert (await task_cols(env, w.T2)).status == "todo"
    assert await count(env, w) == before

    r = await ba("POST", move_url(w.T2), {"status": "in_progress"})
    assert r.status_code == 204, r.status_code
    assert (await task_cols(env, w.T2)).status == "in_progress"
    (e,) = await since(env, w, before)
    assert (e.action, e.entity_id) == ("task.updated", w.T2)
    assert e.changed_fields == ["status"]
    assert e.changes == [{"field": "status", "old": "todo", "new": "in_progress"}]
    assert_by([e], w, actor=w.ba1)

    r = await u1("POST", move_url(w.T2), {"status": "review"})
    assert r.status_code == 204, r.status_code
    written = await since(env, w, before)
    assert len(written) == 2
    e2 = written[1]
    assert (e2.action, e2.entity_id) == ("task.updated", w.T2)
    assert e2.changed_fields == ["status"]
    assert e2.changes == [{"field": "status", "old": "in_progress", "new": "review"}]
    assert_by([e2], w, actor=w.u1)

    # соседом - карточка другой колонки (T3 в «В работе»)
    r = await ba("POST", move_url(w.T2), {"status": "done", "after_task_id": str(w.T3)})
    assert r.status_code == 422, r.status_code
    assert r.json()["code"] == "invalid_neighbors"
    assert (await task_cols(env, w.T2)).status == "review"
    assert await count(env, w) == before + 2

    r = await u1("POST", move_url(w.T1), {"status": "in_progress"})
    assert r.status_code == 403, r.status_code
    assert (await task_cols(env, w.T1)).status == "todo"
    assert await count(env, w) == before + 2


# --- AC-53 ------------------------------------------------------------------------------------


async def test_007_ac53_cascade_deletes_write_no_comment_deleted(api_env: ApiEnv) -> None:
    """AC-53 (FR-42, Q-13, PD-24): каскад (задача, подзадача, проект) событий не пишет; прямое
    удаление c10 - ровно одно comment.deleted; повторное удаление c1 - 404 без события."""
    env = api_env
    w = await make_world007(env)
    async with env.sessionmaker() as s:
        t11 = await make_task(
            s,
            project_id=w.P,
            workspace_id=w.ws.id,
            created_by=w.ba1.id,
            parent_id=w.T1,
            title="T1.1",
        )
        c7 = await make_comment(
            s, task_id=t11.id, workspace_id=w.ws.id, created_by=w.agent_u.id, body="c7"
        )
        t21 = await make_task(
            s,
            project_id=w.P,
            workspace_id=w.ws.id,
            created_by=w.ba1.id,
            parent_id=w.T2,
            title="T2.1",
        )
        c8 = await make_comment(
            s, task_id=t21.id, workspace_id=w.ws.id, created_by=w.ba1.id, body="c8"
        )
        c10 = await make_comment(
            s, task_id=w.T2, workspace_id=w.ws.id, created_by=w.u1.id, body="c10"
        )
        c9 = await make_comment(
            s, task_id=w.T9, workspace_id=w.ws.id, created_by=w.ba1.id, body="c9"
        )
        await s.commit()
    ba = human(env, w, "ba1")
    before = await count(env, w)

    r = await ba("DELETE", task_url(w.T1))
    assert r.status_code == 204, r.status_code
    for gone in (w.T1, t11.id):
        assert (await ba("GET", task_url(gone))).status_code == 404
    assert await comment_deleted_at(env, w.c1) is not None
    assert await comment_deleted_at(env, c7.id) is not None
    assert await count(env, w) == before

    r = await ba("DELETE", comment_url(w.c1))
    assert r.status_code == 404, r.status_code
    assert r.json()["code"] == "not_found"
    assert await count(env, w) == before

    r = await ba("DELETE", task_url(t21.id))
    assert r.status_code == 204, r.status_code
    assert await comment_deleted_at(env, c8.id) is not None
    assert await count(env, w) == before

    r = await ba("DELETE", comment_url(c10.id))
    assert r.status_code == 204, r.status_code
    (e,) = await since(env, w, before)
    assert (e.action, e.entity_type, e.entity_id) == ("comment.deleted", "comment", c10.id)
    assert_by([e], w, actor=w.ba1)

    r = await ba("DELETE", f"{API}/projects/{w.P2}")
    assert r.status_code == 204, r.status_code
    assert await comment_deleted_at(env, c9.id) is not None
    assert await count(env, w) == before + 1
