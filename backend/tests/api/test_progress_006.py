"""R6-T06: прогресс 100/50/0 через API.

spec 006 AC-43, AC-44, AC-45, FR-30, FR-31; plan §4.3, PD-10.

Подзадачи пишутся напрямую в БД (``mk``), чтение - через публичный API карточки и Доски.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import ApiEnv
from tests.tasks_api_support import make_api_world, mk, send, task_url

DONE, WORK, REVIEW, TODO = "done", "in_progress", "review", "todo"

# Таблица AC-43: (статусы подзадач, ожидаемый прогресс)
TABLE_AC43: list[tuple[list[str], int]] = [
    ([TODO] * 3, 0),
    ([WORK, TODO, TODO], 16),
    ([REVIEW, TODO, TODO], 16),
    ([DONE, TODO, TODO], 33),
    ([WORK, REVIEW, DONE], 66),
    ([DONE, DONE, REVIEW], 83),
    ([WORK] * 3, 50),
    ([REVIEW, DONE], 75),
    ([REVIEW], 50),
    ([DONE] * 3, 100),
]
IDS = ["-".join(s) for s, _ in TABLE_AC43]


def _board_url(project_id: Any) -> str:
    return f"/api/v1/projects/{project_id}/board"


async def _board_cards(env: ApiEnv, token: str, project_id: Any) -> list[dict[str, Any]]:
    r = await send(env, token, "GET", _board_url(project_id))
    assert r.status_code == 200, r.text
    return [c for col in r.json()["columns"] for c in col["tasks"]]


@pytest.mark.parametrize(("statuses", "expected"), TABLE_AC43, ids=IDS)
async def test_ac43_card_progress_by_weights(
    api_env: ApiEnv, statuses: list[str], expected: int
) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w, title="BA1")
    for s in statuses:
        await mk(env, w, parent=parent, status=s)

    r = await send(env, w.tok("ba"), "GET", task_url(parent))

    assert r.status_code == 200, r.text
    assert r.json()["progress"] == expected


@pytest.mark.parametrize(("statuses", "expected"), TABLE_AC43, ids=IDS)
async def test_ac44_board_progress_equals_card_progress(
    api_env: ApiEnv, statuses: list[str], expected: int
) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w, title="BA1")
    for s in statuses:
        await mk(env, w, parent=parent, status=s)

    card = (await send(env, w.tok("ba"), "GET", task_url(parent))).json()
    cards = await _board_cards(env, w.tok("ba"), w.project_id)

    assert [c["id"] for c in cards] == [str(parent)]
    assert cards[0]["subtask_count"] == len(statuses)
    assert cards[0]["progress"] == expected
    assert cards[0]["progress"] == card["progress"]


async def test_ac43_deleted_subtasks_do_not_count_on_card_and_board(api_env: ApiEnv) -> None:
    """FR-30: вес считается только по неудалённым подзадачам."""
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w)
    await mk(env, w, parent=parent, status=WORK)
    await mk(env, w, parent=parent, status=DONE, deleted=True)
    await mk(env, w, parent=parent, status=REVIEW, deleted=True)

    card = (await send(env, w.tok("ba"), "GET", task_url(parent))).json()
    (board_card,) = await _board_cards(env, w.tok("ba"), w.project_id)

    assert card["progress"] == 50
    assert board_card["progress"] == 50
    assert board_card["subtask_count"] == 1


async def test_ac44_deleting_subtasks_recomputes_75_then_100_then_null(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w)
    await mk(env, w, parent=parent, status=DONE)
    working = await mk(env, w, parent=parent, status=WORK)
    ba = w.tok("ba")

    assert (await send(env, ba, "GET", task_url(parent))).json()["progress"] == 75

    assert (await send(env, ba, "DELETE", task_url(working))).status_code == 204
    assert (await send(env, ba, "GET", task_url(parent))).json()["progress"] == 100
    (bc,) = await _board_cards(env, ba, w.project_id)
    assert bc["progress"] == 100

    remaining = (await send(env, ba, "GET", task_url(parent))).json()["subtasks"]
    assert len(remaining) == 1
    assert (await send(env, ba, "DELETE", task_url(remaining[0]["id"]))).status_code == 204
    assert (await send(env, ba, "GET", task_url(parent))).json()["progress"] is None
    (bc,) = await _board_cards(env, ba, w.project_id)
    assert bc["progress"] is None
    assert bc["subtask_count"] == 0


async def test_ac44_task_without_subtasks_has_null_progress_on_card_and_board(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    plain = await mk(env, w)

    assert (await send(env, w.tok("ba"), "GET", task_url(plain))).json()["progress"] is None
    (bc,) = await _board_cards(env, w.tok("ba"), w.project_id)
    assert bc["progress"] is None


async def test_ac44_status_change_of_subtask_changes_progress_at_once(api_env: ApiEnv) -> None:
    """FR-30: смена статуса подзадачи сразу меняет прогресс (todo, in_progress, review, done)."""
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w)
    sub = await mk(env, w, parent=parent, status=TODO)
    await mk(env, w, parent=parent, status=TODO)
    ba = w.tok("ba")

    expected = [(WORK, 25), (REVIEW, 25), (DONE, 50), (TODO, 0)]
    for status, value in expected:
        r = await send(env, ba, "PATCH", task_url(sub), {"status": status})
        assert r.status_code == 200, r.text
        got = (await send(env, ba, "GET", task_url(parent))).json()["progress"]
        assert got == value, status


async def test_ac45_api_parent_with_review_subtask_can_be_closed(api_env: ApiEnv) -> None:
    """FR-31: «На проверке» не закрыта, но закрытие родителя разрешено (200); прогресс 75."""
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w)
    await mk(env, w, parent=parent, status=DONE)
    await mk(env, w, parent=parent, status=REVIEW)

    r = await send(env, w.tok("ba"), "PATCH", task_url(parent), {"status": "done"})

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "done"
    assert r.json()["progress"] == 75
