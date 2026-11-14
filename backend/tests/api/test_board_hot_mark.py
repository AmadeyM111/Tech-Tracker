"""Доска: поле ``hot`` в карточке — тот же критерий «Горит», что на «Сводке» (spec 008 FR-8).

Высокий приоритет, срок сегодня (МСК) или раньше, задача не завершена. Проверяется на границах.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.core.clock import today_msk
from tests.api.test_board import _board
from tests.conftest import ApiEnv
from tests.tasks_api_support import make_api_world, mk


def _card(body: dict[str, Any], task_id: str) -> dict[str, Any]:
    for column in body["columns"]:
        for card in column["tasks"]:
            if card["id"] == task_id:
                result: dict[str, Any] = card
                return result
    raise AssertionError(f"card {task_id} not on board")


async def test_hot_mark_matches_summary_criterion_on_boundaries(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    today = today_msk()
    cases = {
        "high_today_todo": ("high", today, "todo", True),
        "high_past_in_progress": ("high", today - timedelta(days=3), "in_progress", True),
        "high_tomorrow": ("high", today + timedelta(days=1), "todo", False),
        "medium_today": ("medium", today, "todo", False),
        "high_today_done": ("high", today, "done", False),
        "high_no_due": ("high", None, "todo", False),
    }
    ids = {}
    for name, (priority, due, status, _) in cases.items():
        ids[name] = await mk(env, w, priority=priority, due_date=due, status=status, title=name)
    body = await _board(env, w.tok("ba"), w.project_id)
    for name, (_, _, _, expected) in cases.items():
        assert _card(body, str(ids[name]))["hot"] is expected, name


async def test_hot_field_is_boolean_on_every_card(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    await mk(env, w, priority="low", title="plain")
    body = await _board(env, w.tok("usr"), w.project_id)
    cards = [c for col in body["columns"] for c in col["tasks"]]
    assert cards and all(isinstance(c["hot"], bool) for c in cards)
