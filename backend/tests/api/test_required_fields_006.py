"""R6-T13: обязательные поля при создании ЗАДАЧИ (spec 006 AC-19...AC-25, AC-41; FR-14...FR-24).

plan §4.2, PD-6...PD-9: проверка в сервисе после прав (403 раньше 422), схема ``TaskCreate`` общая
для задачи и подзадачи; срок раньше «сегодня» по Europe/Moscow - 422 ``due_date_in_past``; нет
описания / срока / исполнителя - 422 ``validation_error``; исполнитель по умолчанию - создатель.

Часы. Фикстура ``fixed_clock`` стоит на 2026-10-13T09:00:00Z, «сегодня» по Москве = 2026-10-13
(``CLOCK`` spec 2026-10-20 здесь не используется: сдвиг на неделю делает сессии мира
недействительными, образец - test_priority_006.py). Даты spec сдвинуты на неделю назад:
D = 2026-10-13, «вчера» = 2026-10-12. Граничные моменты AC-23 - тот же сдвиг (2026-10-13T21:30Z
= 00:30 14 октября по Москве); часы сдвигаются после создания мира, а у сессий мира
обновляется last_activity_at (``seed`` создаёт их на 09:00Z, неактивность 8 ч).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text

from app.core.clock import FixedClock
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

D = "2026-10-13"  # «сегодня» по Москве при fixed_clock по умолчанию
YESTERDAY = "2026-10-12"
FULL: dict[str, Any] = {"title": "Задача", "description": "Описание", "due_date": D}


async def _post(env: ApiEnv, w: ApiWorld, who: str, body: dict[str, Any]) -> Any:
    return await send(env, w.tok(who), "POST", project_tasks_url(w.project_id), body)


async def _count(env: ApiEnv, w: ApiWorld) -> int:
    found = await rows(env, "SELECT count(*) FROM task WHERE project_id = :p", p=w.project_id)
    return int(found[0][0])


def _without(body: dict[str, Any], key: str) -> dict[str, Any]:
    return {k: v for k, v in body.items() if k != key}


def _sub_url(task_id: Any) -> str:
    return f"{task_url(task_id)}/subtasks"


async def _assert_rejected(env: ApiEnv, w: ApiWorld, r: Any, expected: tuple[int, str]) -> None:
    assert error(r) == expected, r.text
    assert await _count(env, w) == 0


# --- AC-19: исполнитель по умолчанию - создатель -------------------------------------------


@pytest.mark.parametrize("who", ["ba", "usr"])
async def test_006_ac19_no_assignee_key_defaults_to_creator(api_env: ApiEnv, who: str) -> None:
    env = api_env
    w = await make_api_world(env)

    r = await _post(env, w, who, FULL)

    assert r.status_code == 201, r.text
    me = {"id": str(w.uid(who)), "login": w.login(who)}
    assert r.json()["assignee"] == me
    assert r.json()["author"] == me
    assert (await task_db(env, r.json()["id"])).assignee_id == w.uid(who)


# --- AC-20: исполнитель --------------------------------------------------------------------


async def test_006_ac20_ba_with_other_member_assignee(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    u2 = await extra_user(env, w, "user", "rf.u2")

    r = await _post(env, w, "ba", {**FULL, "assignee_id": str(u2.user.id)})

    assert r.status_code == 201, r.text
    assert r.json()["assignee"]["id"] == str(u2.user.id)
    assert r.json()["author"]["id"] == str(w.uid("ba"))


async def test_006_ac20_ba_explicit_null_assignee_is_validation_error(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)

    r = await _post(env, w, "ba", {**FULL, "assignee_id": None})

    await _assert_rejected(env, w, r, (422, "validation_error"))


async def test_006_ac20_ba_bad_recipients_keep_old_codes(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    blocked_member = await extra_user(env, w, "user", "rf.ub", blocked=True)
    cases = {
        "UB": (blocked_member.user.id, "user_blocked"),
        "TA": (w.uid("ta"), "recipient_wrong_role"),
        "U3": (w.uid("usr2"), "not_project_member"),
    }

    for name, (user_id, code) in cases.items():
        r = await _post(env, w, "ba", {**FULL, "assignee_id": str(user_id)})
        assert error(r) == (422, code), name
    assert await _count(env, w) == 0


@pytest.mark.parametrize("target", ["other", "null"])
async def test_006_ac20_user_other_or_null_assignee_is_forbidden(
    api_env: ApiEnv, target: str
) -> None:
    env = api_env
    w = await make_api_world(env)
    u2 = await extra_user(env, w, "user", "rf.u2")
    value = str(u2.user.id) if target == "other" else None

    r = await _post(env, w, "usr", {**FULL, "assignee_id": value})

    await _assert_rejected(env, w, r, (403, "forbidden"))


# --- AC-21: описание -----------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["missing", "empty", "spaces", "whitespace_mix"])
async def test_006_ac21_missing_or_blank_description_is_validation_error(
    api_env: ApiEnv, mode: str
) -> None:
    env = api_env
    w = await make_api_world(env)
    body = (
        _without(FULL, "description")
        if mode == "missing"
        else {
            **FULL,
            "description": {"empty": "", "spaces": "   ", "whitespace_mix": " \n\t "}[mode],
        }
    )

    r = await _post(env, w, "ba", body)

    await _assert_rejected(env, w, r, (422, "validation_error"))


async def test_006_ac21_description_over_10000_is_rejected(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)

    r = await _post(env, w, "ba", {**FULL, "description": "я" * 10_001})

    await _assert_rejected(env, w, r, (422, "validation_error"))


async def test_006_ac21_description_10000_and_padding_kept_as_entered(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)

    r = await _post(env, w, "ba", {**FULL, "description": "  Сделать отчёт  "})
    edge = await _post(env, w, "ba", {**FULL, "description": "я" * 10_000})

    assert r.status_code == 201, r.text
    assert r.json()["description"] == "  Сделать отчёт  "
    assert (await task_db(env, r.json()["id"])).description == "  Сделать отчёт  "
    assert edge.status_code == 201, edge.text


# --- AC-22: срок ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["missing", "null"])
async def test_006_ac22_missing_or_null_due_date_is_validation_error(
    api_env: ApiEnv, mode: str
) -> None:
    env = api_env
    w = await make_api_world(env)
    body = _without(FULL, "due_date") if mode == "missing" else {**FULL, "due_date": None}

    r = await _post(env, w, "ba", body)

    await _assert_rejected(env, w, r, (422, "validation_error"))


async def test_006_ac22_yesterday_is_due_date_in_past(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)

    r = await _post(env, w, "ba", {**FULL, "due_date": YESTERDAY})

    await _assert_rejected(env, w, r, (422, "due_date_in_past"))


async def test_006_ac22_far_past_is_due_date_in_past(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)

    r = await _post(env, w, "ba", {**FULL, "due_date": "2000-01-01"})

    await _assert_rejected(env, w, r, (422, "due_date_in_past"))


@pytest.mark.parametrize("due", [D, "2027-01-31"])
async def test_006_ac22_today_and_future_are_created(api_env: ApiEnv, due: str) -> None:
    env = api_env
    w = await make_api_world(env)

    r = await _post(env, w, "ba", {**FULL, "due_date": due})

    assert r.status_code == 201, r.text
    assert r.json()["due_date"] == due
    assert str((await task_db(env, r.json()["id"])).due_date) == due


@pytest.mark.parametrize("due", [f"{D}T10:00:00Z", "2026-02-30", "13.10.2026", 20261013, ""])
async def test_006_ac22_malformed_due_date_is_validation_error(api_env: ApiEnv, due: Any) -> None:
    env = api_env
    w = await make_api_world(env)

    r = await _post(env, w, "ba", {**FULL, "due_date": due})

    await _assert_rejected(env, w, r, (422, "validation_error"))


async def test_006_ac22_validation_errors_come_before_past_due_date(api_env: ApiEnv) -> None:
    """PD-7: сначала все ``validation_error`` (пустое описание), потом срок в прошлом."""
    env = api_env
    w = await make_api_world(env)

    r = await _post(env, w, "ba", {**FULL, "description": "  ", "due_date": YESTERDAY})

    await _assert_rejected(env, w, r, (422, "validation_error"))


async def test_006_ac22_past_due_date_comes_before_recipient_checks(api_env: ApiEnv) -> None:
    """PD-8/plan §4.2: ``_check_top_level`` раньше ``_check_assignee``."""
    env = api_env
    w = await make_api_world(env)

    r = await _post(
        env, w, "ba", {**FULL, "due_date": YESTERDAY, "assignee_id": str(w.uid("usr2"))}
    )

    await _assert_rejected(env, w, r, (422, "due_date_in_past"))


# --- AC-23: граница суток по Europe/Moscow ---------------------------------------------------
# Даты spec сдвинуты на неделю назад (20.10 -> 13.10); моменты и границы суток те же.
# ``seed`` создаёт сессии на 2026-10-13T09:00Z (неактивность 8 ч), поэтому после сдвига часов
# к вечеру обновляется ``last_activity_at`` сессий (только тестовая БД, только данные сессий).


async def _move_clock(env: ApiEnv, clock: FixedClock, at: datetime) -> None:
    clock.set(at)
    await env.execute(text("UPDATE user_session SET last_activity_at = :at").bindparams(at=at))


async def test_006_ac23_utc_evening_is_next_day_in_moscow(
    api_env: ApiEnv, fixed_clock: FixedClock
) -> None:
    env = api_env
    w = await make_api_world(env)
    await _move_clock(env, fixed_clock, datetime(2026, 10, 13, 21, 30, tzinfo=UTC))  # 00:30 14.10

    ok = await _post(env, w, "ba", {**FULL, "due_date": "2026-10-14"})
    past = await _post(env, w, "ba", {**FULL, "due_date": D})

    assert ok.status_code == 201, ok.text
    assert error(past) == (422, "due_date_in_past")
    assert await _count(env, w) == 1


async def test_006_ac23_last_second_of_moscow_day_keeps_today(
    api_env: ApiEnv, fixed_clock: FixedClock
) -> None:
    env = api_env
    w = await make_api_world(env)
    await _move_clock(env, fixed_clock, datetime(2026, 10, 13, 20, 59, 59, tzinfo=UTC))  # 23:59:59

    r = await _post(env, w, "ba", {**FULL, "due_date": D})

    assert r.status_code == 201, r.text


async def test_006_ac23_first_second_of_next_moscow_day_rejects_yesterday(
    api_env: ApiEnv, fixed_clock: FixedClock
) -> None:
    env = api_env
    w = await make_api_world(env)
    await _move_clock(
        env, fixed_clock, datetime(2026, 10, 13, 21, 0, 0, tzinfo=UTC)
    )  # 00:00:00 14.10

    r = await _post(env, w, "ba", {**FULL, "due_date": D})

    await _assert_rejected(env, w, r, (422, "due_date_in_past"))


# --- AC-24: порядок проверок, права раньше полей -------------------------------------------


@pytest.mark.parametrize("who", ["ba3", "usr2", "ta"])
async def test_006_ac24_no_rights_gets_403_not_422(api_env: ApiEnv, who: str) -> None:
    env = api_env
    w = await make_api_world(env)

    r = await _post(env, w, who, {"title": "Х"})

    assert r.status_code == 403, r.text
    assert await _count(env, w) == 0


async def test_006_ac24_missing_project_is_404(api_env: ApiEnv) -> None:
    import uuid

    env = api_env
    w = await make_api_world(env)

    r = await send(env, w.tok("ba"), "POST", project_tasks_url(uuid.uuid4()), {"title": "Х"})

    assert r.status_code == 404, r.text


async def test_006_ac24_title_only_from_member_is_422_not_403(api_env: ApiEnv) -> None:
    """Контрольный: с правами то же тело даёт 422 (а не 201 и не 403)."""
    env = api_env
    w = await make_api_world(env)

    r = await _post(env, w, "ba", {"title": "Х"})

    await _assert_rejected(env, w, r, (422, "validation_error"))


# --- AC-25 / FR-24: подзадачи без изменений ------------------------------------------------


async def test_006_ac25_ba_subtask_title_only(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w, title="Родитель")

    r = await send(env, w.tok("ba"), "POST", _sub_url(parent), {"title": "Шаг"})

    assert r.status_code == 201, r.text
    body = r.json()
    assert body["assignee"] is None
    assert body["description"] == ""
    assert body["due_date"] is None
    assert body["priority"] == "medium"


async def test_006_ac25_assignee_of_parent_creates_subtask_for_self(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w, title="Родитель", assignee="usr")

    r = await send(env, w.tok("usr"), "POST", _sub_url(parent), {"title": "Шаг"})

    assert r.status_code == 201, r.text
    assert r.json()["assignee"] == {"id": str(w.uid("usr")), "login": w.login("usr")}


async def test_006_ac25_subtask_past_due_date_is_kept(api_env: ApiEnv) -> None:
    """Подзадача: срок необязателен и «прошлое» не проверяется (FR-24)."""
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w, title="Родитель")

    r = await send(
        env, w.tok("ba"), "POST", _sub_url(parent), {"title": "Шаг", "due_date": YESTERDAY}
    )

    assert r.status_code == 201, r.text
    assert r.json()["due_date"] == YESTERDAY


async def test_006_ac25_subtask_null_assignee_is_allowed(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w, title="Родитель", assignee="usr")

    r = await send(
        env, w.tok("ba"), "POST", _sub_url(parent), {"title": "Шаг", "assignee_id": None}
    )

    assert r.status_code == 201, r.text
    assert r.json()["assignee"] is None


# --- AC-41: три подзадачи подряд -----------------------------------------------------------


async def test_006_ac41_three_subtasks_in_a_row(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    created = await _post(env, w, "ba", FULL)
    assert created.status_code == 201, created.text
    parent = created.json()["id"]

    for n in (1, 2, 3):
        r = await send(env, w.tok("ba"), "POST", _sub_url(parent), {"title": f"Шаг {n}"})
        assert r.status_code == 201, r.text

    card = await send(env, w.tok("ba"), "GET", task_url(parent))
    assert card.status_code == 200, card.text
    assert sorted(s["title"] for s in card.json()["subtasks"]) == ["Шаг 1", "Шаг 2", "Шаг 3"]


# --- OpenAPI: схема не меняет required (PD-6) ----------------------------------------------


async def test_006_pd6_schema_requires_only_title_and_mentions_error_code(
    api_env: ApiEnv,
) -> None:
    schema = api_env.app.openapi()["components"]["schemas"]["TaskCreate"]

    assert set(schema["required"]) == {"title"}
    assert "due_date_in_past" in schema.get("description", "")
