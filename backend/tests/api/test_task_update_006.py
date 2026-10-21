"""R6-T14: изменение ЗАДАЧИ верхнего уровня не снимает исполнителя и срок, не очищает описание
(spec 006 AC-26, AC-27; FR-22, FR-23; Q-2 б); plan §4.2, PD-7.

Часы. ``fixed_clock`` стоит на 2026-10-13T09:00:00Z, «сегодня» по Москве = 2026-10-13 (как в
test_required_fields_006.py). Даты spec (CLOCK 2026-10-20) сдвинуты на неделю назад:
2026-10-19 -> 2026-10-12 («вчера»), 2026-10-20 -> 2026-10-13 («сегодня»), 2026-10-25 -> 2026-10-18.
Старый срок ``2026-10-01`` остаётся в прошлом и при сдвиге.

Задача ``T`` создаётся ``ba`` (BA1) через POST с исполнителем ``usr`` (U1); ``ba2`` - U2-кандидат
в БА-участники, ``u2`` - дополнительный «Пользователь»-участник (исполнитель U2 из AC-27).
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import pytest

from tests.conftest import ApiEnv
from tests.tasks_api_support import (
    ApiWorld,
    error,
    extra_user,
    make_api_world,
    mk,
    project_tasks_url,
    rows,
    send,
    task_db,
    task_url,
)

TODAY = "2026-10-13"
YESTERDAY = "2026-10-12"
LATER = "2026-10-18"
OLD_DUE = date(2026, 10, 1)


async def _create_t(env: ApiEnv, w: ApiWorld) -> str:
    r = await send(
        env,
        w.tok("ba"),
        "POST",
        project_tasks_url(w.project_id),
        {
            "title": "Исходное",
            "description": "Описание",
            "due_date": "2026-10-16",
            "assignee_id": str(w.uid("usr")),
        },
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def _patch(env: ApiEnv, w: ApiWorld, t: Any, body: dict[str, Any], who: str = "ba") -> Any:
    return await send(env, w.tok(who), "PATCH", task_url(t), body)


async def _state(env: ApiEnv, t: Any) -> tuple[Any, ...]:
    r = await task_db(env, t)
    return (r.title, r.description, r.due_date, r.assignee_id, r.status, r.priority, r.updated_at)


# --- AC-26: старые задачи (FR-22) ----------------------------------------------------------


async def _old_tasks(env: ApiEnv, w: ApiWorld) -> tuple[Any, Any]:
    bare = await mk(env, w, title="Старая", description="", priority="medium")
    past = await mk(env, w, title="Старая со сроком", description="", due_date=OLD_DUE)
    return bare, past


async def test_006_ac26_old_tasks_are_read_listed_and_on_board(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    bare, past = await _old_tasks(env, w)

    for t, due in ((bare, None), (past, "2026-10-01")):
        r = await send(env, w.tok("ba"), "GET", task_url(t))
        assert r.status_code == 200, r.text
        assert (r.json()["assignee"], r.json()["due_date"], r.json()["description"]) == (
            None,
            due,
            "",
        )

    listed = await send(env, w.tok("ba"), "GET", project_tasks_url(w.project_id))
    assert listed.status_code == 200, listed.text
    by_id = {i["id"]: i for i in listed.json()["items"]}
    assert by_id[str(bare)]["assignee"] is None and by_id[str(bare)]["due_date"] is None
    assert by_id[str(past)]["assignee"] is None and by_id[str(past)]["due_date"] == "2026-10-01"

    board = await send(env, w.tok("ba"), "GET", f"/api/v1/projects/{w.project_id}/board")
    assert board.status_code == 200, board.text
    cards = {c["id"]: c for col in board.json()["columns"] for c in col["tasks"]}
    assert cards[str(bare)]["assignee"] is None and cards[str(bare)]["due_date"] is None
    assert cards[str(past)]["assignee"] is None and cards[str(past)]["due_date"] == "2026-10-01"


@pytest.mark.parametrize("which", ["bare", "past"])
@pytest.mark.parametrize("field", ["status", "title"])
async def test_006_ac26_old_task_status_or_title_change_ok_due_untouched(
    api_env: ApiEnv, which: str, field: str
) -> None:
    env = api_env
    w = await make_api_world(env)
    bare, past = await _old_tasks(env, w)
    t = bare if which == "bare" else past
    before = await task_db(env, t)
    value = "in_progress" if field == "status" else "Новое название"

    r = await _patch(env, w, t, {field: value})

    assert r.status_code == 200, r.text
    assert r.json()[field] == value
    after = await task_db(env, t)
    assert getattr(after, field) == value
    assert (after.due_date, after.assignee_id, after.description) == (
        before.due_date,
        None,
        "",
    )


async def test_006_ac26_old_task_unchanged_empty_fields_in_full_form_are_ok(
    api_env: ApiEnv,
) -> None:
    """FR-23: проверяются только меняющиеся поля - форма со старым прошлым сроком, пустым
    описанием и тем же значением срока/описания проходит, если меняется название."""
    env = api_env
    w = await make_api_world(env)
    _, past = await _old_tasks(env, w)

    r = await _patch(
        env, w, past, {"title": "Только название", "description": "", "due_date": "2026-10-01"}
    )

    assert r.status_code == 200, r.text
    row = await task_db(env, past)
    assert (row.title, row.description, row.due_date) == ("Только название", "", OLD_DUE)


# --- AC-27: задача верхнего уровня ---------------------------------------------------------

_REJECTED = [
    pytest.param({"assignee_id": None}, id="assignee-null"),
    pytest.param({"due_date": None}, id="due-null"),
    pytest.param({"description": ""}, id="description-empty"),
    pytest.param({"description": "  "}, id="description-spaces"),
    pytest.param({"description": " \n\t "}, id="description-whitespace-mix"),
]


@pytest.mark.parametrize("body", _REJECTED)
async def test_006_ac27_clearing_fields_is_validation_error_task_unchanged(
    api_env: ApiEnv, body: dict[str, Any]
) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await _create_t(env, w)
    before = await _state(env, t)

    r = await _patch(env, w, t, body)

    assert error(r) == (422, "validation_error"), r.text
    assert await _state(env, t) == before


async def test_006_ac27_other_ba_member_cannot_clear_either(api_env: ApiEnv) -> None:
    """БА-участник (не владелец) правит задачу, созданную владельцем, только по FR-23: 422."""
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, by="ba2", assignee="usr", description="д", due_date=date(2026, 10, 16))
    before = await _state(env, t)

    for body in ({"due_date": None}, {"assignee_id": None}, {"description": ""}):
        r = await _patch(env, w, t, body, who="ba2")
        assert error(r) == (422, "validation_error"), (body, r.text)
    assert await _state(env, t) == before


async def test_006_ac27_non_member_ba_gets_403_before_422(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await _create_t(env, w)
    before = await _state(env, t)

    r = await _patch(env, w, t, {"due_date": None}, who="ba3")

    assert error(r) == (403, "forbidden")
    assert await _state(env, t) == before


async def test_006_ac27_user_assignee_clear_is_still_403_before_422(api_env: ApiEnv) -> None:
    """Права раньше проверок полей (plan §4.2: «как сейчас (права -> _validate)» + проверка)."""
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, assignee="usr", description="д", due_date=date(2026, 10, 16))

    r = await _patch(env, w, t, {"assignee_id": None}, who="usr")

    assert error(r) == (403, "forbidden")
    assert (await task_db(env, t)).assignee_id == w.uid("usr")


async def test_006_ac27_combined_title_and_null_due_date_is_422_title_unchanged(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await _create_t(env, w)
    before = await _state(env, t)

    r = await _patch(env, w, t, {"title": "Новое", "due_date": None})

    assert error(r) == (422, "validation_error"), r.text
    assert await _state(env, t) == before
    assert (await task_db(env, t)).title == "Исходное"


async def test_006_ac27_combined_status_and_null_assignee_is_422_nothing_changes(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await _create_t(env, w)
    before = await _state(env, t)

    r = await _patch(env, w, t, {"status": "done", "assignee_id": None})

    assert error(r) == (422, "validation_error"), r.text
    assert await _state(env, t) == before


async def test_006_ac27_past_due_date_is_due_date_in_past(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await _create_t(env, w)
    before = await _state(env, t)

    r = await _patch(env, w, t, {"due_date": YESTERDAY})

    assert error(r) == (422, "due_date_in_past"), r.text
    assert await _state(env, t) == before


async def test_006_ac27_validation_error_wins_over_due_date_in_past(api_env: ApiEnv) -> None:
    """PD-7: сначала все validation_error, потом срок в прошлом."""
    env = api_env
    w = await make_api_world(env)
    t = await _create_t(env, w)

    r = await _patch(env, w, t, {"due_date": YESTERDAY, "description": "  "})

    assert error(r) == (422, "validation_error"), r.text


@pytest.mark.parametrize("due", [TODAY, LATER])
async def test_006_ac27_today_and_future_due_date_ok(api_env: ApiEnv, due: str) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await _create_t(env, w)

    r = await _patch(env, w, t, {"due_date": due})

    assert r.status_code == 200, r.text
    assert r.json()["due_date"] == due
    assert str((await task_db(env, t)).due_date) == due


async def test_006_ac27_other_assignee_and_other_description_ok(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    u2 = await extra_user(env, w, "user", "t14.u2")
    t = await _create_t(env, w)

    a = await _patch(env, w, t, {"assignee_id": str(u2.user.id)})
    d = await _patch(env, w, t, {"description": "Другое"})

    assert a.status_code == 200, a.text
    assert a.json()["assignee"]["id"] == str(u2.user.id)
    assert d.status_code == 200, d.text
    row = await task_db(env, t)
    assert (row.assignee_id, row.description) == (u2.user.id, "Другое")


async def test_006_ac27_same_values_are_not_a_change(api_env: ApiEnv) -> None:
    """D-46: поле, равное текущему, не проверяется и не считается изменением."""
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, assignee="usr", description="", due_date=OLD_DUE)

    r = await _patch(env, w, t, {"description": "", "due_date": "2026-10-01"})

    assert r.status_code == 200, r.text
    assert (await task_db(env, t)).due_date == OLD_DUE


# --- AC-27: подзадача (FR-23: правила прежние) ---------------------------------------------


async def _subtask(env: ApiEnv, w: ApiWorld) -> Any:
    parent = await mk(env, w, assignee="usr", description="д", due_date=date(2026, 10, 16))
    return await mk(
        env,
        w,
        assignee="usr",
        parent=parent,
        description="Шаг",
        due_date=date(2026, 10, 16),
    )


@pytest.mark.parametrize(
    ("body", "column", "expected"),
    [
        ({"assignee_id": None}, "assignee_id", None),
        ({"due_date": None}, "due_date", None),
        ({"description": ""}, "description", ""),
        ({"due_date": "2026-10-01"}, "due_date", OLD_DUE),
    ],
    ids=["assignee-null", "due-null", "description-empty", "due-in-past"],
)
async def test_006_ac27_subtask_may_clear_fields_and_have_past_due(
    api_env: ApiEnv, body: dict[str, Any], column: str, expected: Any
) -> None:
    env = api_env
    w = await make_api_world(env)
    s = await _subtask(env, w)

    r = await _patch(env, w, s, body)

    assert r.status_code == 200, r.text
    assert getattr(await task_db(env, s), column) == expected


# --- AC-27 последний пункт: исключение участника (сервис проектов) -------------------------


async def test_006_ac27_removing_member_clears_assignee_then_status_change_ok(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await _create_t(env, w)
    assert (await task_db(env, t)).assignee_id == w.uid("usr")

    removed = await send(
        env, w.tok("ba"), "DELETE", f"/api/v1/projects/{w.project_id}/members/{w.uid('usr')}"
    )
    assert removed.status_code == 204, removed.text
    found = await rows(env, "SELECT assignee_id FROM task WHERE id = :t", t=uuid.UUID(t))
    assert found[0][0] is None  # снятие системой сохранено (001/FR-15a)

    r = await _patch(env, w, t, {"status": "in_progress"})

    assert r.status_code == 200, r.text
    assert r.json()["assignee"] is None
    assert r.json()["status"] == "in_progress"
