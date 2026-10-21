"""T77: ``/api/v1`` задачи — создание, карточка, правка, валидация, 503, контракт.

AC-9, AC-24, AC-46, AC-47, AC-49, AC-56, AC-68 (формат срока), AC-81, AC-106, AC-108, AC-109,
AC-123, AC-124; plan §11.4, D-46, D-51, D-52, D-65. Подзадачи — ``test_subtasks.py``, права по
ролям — ``test_task_permissions.py``, получатели — ``test_recipients.py``, удаление —
``test_soft_delete.py``.

Контракт ответов: ``TaskDetail {id, project{id,name}, parent_id, title, description, status,
priority, due_date, assignee, author, position, subtasks, progress, created_at, updated_at,
permissions{edit, change_status, change_assignee, delete, create_subtask}}``.
Порядок ошибок: гейты (401/403 роли) -> 422 схемы -> 404 -> 403 объекта -> 422 бизнес-правил.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest

from tests.api.test_route_guards import _api_operations
from tests.conftest import ApiEnv
from tests.db_support import BACKEND_DIR
from tests.tasks_api_support import (
    ALL_STATUSES,
    BRIEF_FIELDS,
    DETAIL_FIELDS,
    LIST_FIELDS,
    PERM_FIELDS,
    USER_REF_FIELDS,
    busy_database,
    error,
    hold_row,
    make_api_world,
    mk,
    pj,
    project_tasks_url,
    rows,
    send,
    task_db,
    task_url,
)

REPO_ROOT = BACKEND_DIR.parent
SOME_ID = "6f9619ff-8b86-4d11-b42d-00c04fc964ff"
# 006/FR-15, FR-16: задача создаётся с описанием и сроком не раньше «сегодня»; fixed_clock по
# умолчанию - 2026-10-13T09:00Z, «сегодня» по Москве = 2026-10-13.
REQ = {"description": "Описание", "due_date": "2026-10-13"}


async def _count(env: ApiEnv, project_id: Any) -> int:
    found = await rows(env, "SELECT count(*) FROM task WHERE project_id = :p", p=project_id)
    return int(found[0][0])


async def _create(env: ApiEnv, w: Any, who: str, body: dict[str, Any]) -> Any:
    return await send(env, w.tok(who), "POST", project_tasks_url(w.project_id), body)


# --- POST /projects/{id}/tasks: форма и умолчания ---------------------------------------------


async def test_ac49_ac24_create_minimal_body_defaults_and_shape(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)

    r = await _create(env, w, "ba", {"title": "Первая", **REQ})

    assert r.status_code == 201, r.text
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert set(body) == DETAIL_FIELDS
    assert body["title"] == "Первая"
    assert body["description"] == "Описание"  # 006/FR-15: описание обязательно
    assert body["status"] == "todo"  # AC-24
    assert body["priority"] == "medium"  # AC-49, 006/AC-12
    assert body["due_date"] == "2026-10-13"  # 006/FR-16: срок обязателен
    assert body["parent_id"] is None
    # 006/AC-19 (было: None, AC-56): не переданный исполнитель - создатель, в т.ч. БА
    assert body["assignee"] == {"id": str(w.uid("ba")), "login": w.login("ba")}
    assert body["subtasks"] == []
    assert body["progress"] is None
    assert isinstance(body["position"], int)
    assert body["project"] == {"id": str(w.project_id), "name": "Основной"}
    assert body["author"] == {"id": str(w.uid("ba")), "login": w.login("ba")}
    assert set(body["author"]) == USER_REF_FIELDS
    assert set(body["permissions"]) == PERM_FIELDS
    assert all(isinstance(v, bool) for v in body["permissions"].values())
    assert uuid.UUID(body["id"])
    row = await task_db(env, body["id"])
    assert (row.title, row.created_by, row.deleted_at) == ("Первая", w.uid("ba"), None)
    assert row.workspace_id == w.ws.id


async def test_ac49_ac68_create_with_all_fields_returns_them_as_given(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)

    r = await _create(
        env,
        w,
        "ba",
        {
            "title": "Полная",
            "description": "Описание\nс переводом строки",
            "assignee_id": str(w.uid("usr")),
            "due_date": "2026-10-20",
            "priority": "high",
        },
    )

    assert r.status_code == 201, r.text
    body = r.json()
    assert body["due_date"] == "2026-10-20"  # AC-68: без времени и пояса
    assert body["priority"] == "high"
    assert body["description"] == "Описание\nс переводом строки"
    assert body["assignee"] == {"id": str(w.uid("usr")), "login": w.login("usr")}
    again = await send(env, w.tok("ba"), "GET", task_url(body["id"]))
    assert again.json()["due_date"] == "2026-10-20"
    assert str((await task_db(env, body["id"])).due_date) == "2026-10-20"


async def test_ac81_new_task_goes_to_end_of_todo_column(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    first = await mk(env, w, position=5000)
    await mk(env, w, status="in_progress", position=9000)  # другая колонка не влияет

    r1 = await _create(env, w, "ba", {"title": "A", **REQ})
    r2 = await _create(env, w, "ba", {"title": "B", **REQ})

    assert r1.json()["position"] > (await task_db(env, first)).position
    assert r2.json()["position"] > r1.json()["position"]


async def test_title_and_description_are_stored_as_entered_d52(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    title = "  Задача с пробелами  "

    r = await _create(
        env, w, "ba", {"title": title, "description": "  d  ", "due_date": REQ["due_date"]}
    )

    assert r.status_code == 201, r.text
    assert r.json()["title"] == title
    assert (await task_db(env, r.json()["id"])).description == "  d  "


async def test_ac108_boundary_lengths_are_accepted(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)

    r = await _create(
        env, w, "ba", {"title": "Я" * 255, "description": "д" * 10_000, "due_date": REQ["due_date"]}
    )

    assert r.status_code == 201, r.text
    row = await task_db(env, r.json()["id"])
    assert (len(row.title), len(row.description)) == (255, 10_000)


# --- создание: исполнитель (AC-9, AC-56, AC-109) ----------------------------------------------


async def test_ac109_user_without_assignee_gets_himself_and_can_edit_title(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)

    r = await _create(env, w, "usr", {"title": "Моя", **REQ})

    assert r.status_code == 201, r.text
    me = {"id": str(w.uid("usr")), "login": w.login("usr")}
    assert r.json()["assignee"] == me
    assert r.json()["author"] == me
    assert r.json()["permissions"]["edit"] is True
    patched = await send(
        env, w.tok("usr"), "PATCH", task_url(r.json()["id"]), {"title": "Моя, переименована"}
    )
    assert patched.status_code == 200, patched.text


async def test_ac109_user_explicit_null_assignee_is_403_and_nothing_created(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    before = await _count(env, w.project_id)

    r = await _create(env, w, "usr", {"title": "Без исполнителя", **REQ, "assignee_id": None})

    assert error(r) == (403, "forbidden")
    assert await _count(env, w.project_id) == before


async def test_ac9_user_assigning_other_is_403_himself_is_201(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    before = await _count(env, w.project_id)

    other = await _create(
        env, w, "usr", {"title": "Другому", **REQ, "assignee_id": str(w.uid("ba2"))}
    )
    own = await _create(env, w, "usr", {"title": "Себе", **REQ, "assignee_id": str(w.uid("usr"))})

    assert error(other) == (403, "forbidden")
    assert own.status_code == 201, own.text
    assert await _count(env, w.project_id) == before + 1


@pytest.mark.parametrize("who", ["ba", "ba2"])
async def test_ac109_ac56_ba_without_assignee_gets_himself_and_null_is_422(
    api_env: ApiEnv, who: str
) -> None:
    """002/AC-13 + 006/AC-19, AC-20 (D-4): БА без поля - сам; null - 422; другой - ок.

    Раньше: без поля и с null - исполнитель None (001/AC-109); теперь для задачи верхнего уровня
    исполнитель обязателен.
    """
    env = api_env
    w = await make_api_world(env)
    before = await _count(env, w.project_id)

    omitted = await _create(env, w, who, {"title": "Без поля", **REQ})
    explicit = await _create(env, w, who, {"title": "Явный null", **REQ, "assignee_id": None})
    other = await _create(
        env, w, who, {"title": "Другому", **REQ, "assignee_id": str(w.uid("usr"))}
    )

    assert omitted.status_code == 201, omitted.text
    assert omitted.json()["assignee"] == {"id": str(w.uid(who)), "login": w.login(who)}
    assert error(explicit) == (422, "validation_error")
    assert other.status_code == 201, other.text
    assert other.json()["assignee"]["id"] == str(w.uid("usr"))
    assert await _count(env, w.project_id) == before + 2


@pytest.mark.parametrize("who", ["ba3", "usr2"])
async def test_ac106_non_member_cannot_create_task_403(api_env: ApiEnv, who: str) -> None:
    env = api_env
    w = await make_api_world(env)
    before = await _count(env, w.project_id)

    r = await _create(env, w, who, {"title": "Не участник"})

    assert error(r) == (403, "forbidden")
    assert await _count(env, w.project_id) == before


async def test_ac103_ba_non_member_becomes_member_and_creates(api_env: ApiEnv) -> None:
    """AC 002 AC-15: БА-неучастник ``ba3`` (прежде СМ ``sm``) - 403, после вступления - 201."""
    from tests.tasks_api_support import add_member_row

    env = api_env
    w = await make_api_world(env)
    assert error(await _create(env, w, "ba3", {"title": "x"})) == (403, "forbidden")

    await add_member_row(env, w, w.people["ba3"].user)

    assert (await _create(env, w, "ba3", {"title": "x", **REQ})).status_code == 201


# --- GET /tasks/{id}: карточка ----------------------------------------------------------------


async def test_card_fields_assignee_author_project_and_sorted_subtasks(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(
        env,
        w,
        by="ba2",
        assignee="usr",
        title="Родитель",
        description="Текст",
        priority="high",
        due_date=date(2026, 11, 2),
        status="review",
    )
    s2 = await mk(
        env,
        w,
        parent=parent,
        title="Вторая",
        status="done",
        assignee="ba2",
        created_at=datetime(2026, 10, 2, tzinfo=UTC),
    )
    s1 = await mk(
        env,
        w,
        parent=parent,
        title="Первая",
        status="todo",
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
    )

    r = await send(env, w.tok("usr"), "GET", task_url(parent))

    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == DETAIL_FIELDS
    assert (body["title"], body["description"], body["status"], body["priority"]) == (
        "Родитель",
        "Текст",
        "review",
        "high",
    )
    assert body["due_date"] == "2026-11-02"
    assert body["assignee"] == {"id": str(w.uid("usr")), "login": w.login("usr")}
    assert body["author"] == {"id": str(w.uid("ba2")), "login": w.login("ba2")}
    assert body["project"] == {"id": str(w.project_id), "name": "Основной"}
    assert body["parent_id"] is None
    assert [s["id"] for s in body["subtasks"]] == [str(s1), str(s2)]
    for item in body["subtasks"]:
        assert set(item) == BRIEF_FIELDS
    assert body["subtasks"][1]["assignee"] == {"id": str(w.uid("ba2")), "login": w.login("ba2")}
    assert body["subtasks"][0]["assignee"] is None
    assert body["progress"] == 50


async def test_ac7_progress_floor_deleted_excluded_and_review_not_closed(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w)
    done = await mk(env, w, parent=parent, status="done")
    for status in ("todo", "review"):
        await mk(env, w, parent=parent, status=status)
    gone = await mk(env, w, parent=parent, status="todo")

    r = await send(env, w.tok("ba"), "GET", task_url(parent))
    # AC-43 (006): Выполнена 100 + На проверке 50 + 2 x К выполнению 0 = 150 // 4 = 37
    assert r.json()["progress"] == 37

    assert (await send(env, w.tok("ba"), "DELETE", task_url(gone))).status_code == 204
    r = await send(env, w.tok("ba"), "GET", task_url(parent))
    # AC-44 (006): пересчёт по оставшимся: (100 + 50 + 0) // 3 = 50;
    # «На проверке» всё ещё не закрыта (FR-31)
    assert r.json()["progress"] == 50
    assert len(r.json()["subtasks"]) == 3
    assert str(gone) not in r.text

    await send(env, w.tok("ba"), "PATCH", task_url(done), {"status": "done"})
    for sub in r.json()["subtasks"]:
        await send(env, w.tok("ba"), "PATCH", task_url(sub["id"]), {"status": "done"})
    assert (await send(env, w.tok("ba"), "GET", task_url(parent))).json()["progress"] == 100


async def test_ac7_task_without_subtasks_has_null_progress_and_parent_can_be_done(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    plain = await mk(env, w)
    parent = await mk(env, w)
    await mk(env, w, parent=parent, status="todo")

    assert (await send(env, w.tok("ba"), "GET", task_url(plain))).json()["progress"] is None
    r = await send(env, w.tok("ba"), "PATCH", task_url(parent), {"status": "done"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "done"
    assert r.json()["progress"] == 0


async def test_card_of_subtask_has_parent_null_position_and_no_create_subtask(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w)
    sub = await mk(env, w, parent=parent)

    body = (await send(env, w.tok("ba"), "GET", task_url(sub))).json()

    assert body["parent_id"] == str(parent)
    assert body["position"] is None
    assert body["subtasks"] == []
    assert body["permissions"]["create_subtask"] is False


async def test_card_invalid_uuid_is_422(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    for method in ("GET", "PATCH", "DELETE"):
        r = await send(
            env, w.tok("ba"), method, "/api/v1/tasks/not-a-uuid", {} if method == "PATCH" else None
        )
        assert error(r) == (422, "validation_error"), method


# --- PATCH /tasks/{id} ------------------------------------------------------------------------


async def test_ac46_ac108_owner_changes_each_field_and_card_reflects(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, assignee="usr")
    payload = {
        "title": "Новое имя",
        "description": "Новое описание",
        "due_date": "2026-12-31",
        "priority": "high",
        "status": "review",
        "assignee_id": str(w.uid("ba2")),
    }

    r = await send(env, w.tok("ba"), "PATCH", task_url(t), payload)

    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == DETAIL_FIELDS
    assert (body["title"], body["description"], body["due_date"]) == (
        "Новое имя",
        "Новое описание",
        "2026-12-31",
    )
    assert (body["priority"], body["status"]) == ("high", "review")
    assert body["assignee"]["id"] == str(w.uid("ba2"))
    assert (await send(env, w.tok("ba"), "GET", task_url(t))).json() == body


async def test_patch_partial_changes_only_given_field(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, assignee="usr", title="Было", description="Описание", priority="high")

    r = await send(env, w.tok("ba"), "PATCH", task_url(t), {"title": "Стало"})

    assert r.status_code == 200, r.text
    row = await task_db(env, t)
    assert (row.title, row.description, row.priority, row.assignee_id) == (
        "Стало",
        "Описание",
        "high",
        w.uid("usr"),
    )


async def test_patch_null_due_date_and_null_assignee_clear_the_values(api_env: ApiEnv) -> None:
    """006/AC-27 (R6-T14): у ПОДЗАДАЧИ null снимает срок и исполнителя; у задачи верхнего уровня
    то же самое - 422 (api/test_task_update_006.py)."""
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w, assignee="usr", due_date=date(2026, 10, 20))
    t = await mk(env, w, assignee="usr", due_date=date(2026, 10, 20), parent=parent)

    r = await send(env, w.tok("ba"), "PATCH", task_url(t), {"due_date": None, "assignee_id": None})

    assert r.status_code == 200, r.text
    assert r.json()["due_date"] is None
    assert r.json()["assignee"] is None
    row = await task_db(env, t)
    assert (row.due_date, row.assignee_id) == (None, None)


async def test_d46_empty_and_same_value_patch_change_nothing(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, assignee="usr", title="Т", priority="high")
    before = await task_db(env, t)
    same = {
        "title": "Т",
        "description": "",
        "priority": "high",
        "status": "todo",
        "assignee_id": str(w.uid("usr")),
        "due_date": None,
    }

    for payload in ({}, same):
        r = await send(env, w.tok("ba"), "PATCH", task_url(t), payload)
        assert r.status_code == 200, r.text
        assert r.json()["title"] == "Т"
    after = await task_db(env, t)
    assert (after.updated_at, after.position, after.title) == (
        before.updated_at,
        before.position,
        before.title,
    )


async def test_d46_same_value_status_does_not_move_card_in_column(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    first = await mk(env, w, position=1024)
    await mk(env, w, position=2048)

    r = await send(env, w.tok("ba"), "PATCH", task_url(first), {"status": "todo"})

    assert r.status_code == 200
    assert (await task_db(env, first)).position == 1024


async def test_ac81_status_change_puts_task_to_end_of_target_column(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    for pos in (1024, 2048, 3072):
        await mk(env, w, status="in_progress", position=pos)
    fourth = await mk(env, w, status="todo", position=1024)

    r = await send(env, w.tok("ba"), "PATCH", task_url(fourth), {"status": "in_progress"})

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "in_progress"
    assert r.json()["position"] > 3072
    column = await rows(
        env,
        "SELECT id FROM task WHERE project_id = :p AND status = 'in_progress' "
        "AND parent_id IS NULL ORDER BY position, created_at, id",
        p=w.project_id,
    )
    assert column[-1][0] == fourth


async def test_status_change_of_subtask_keeps_position_null(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w)
    sub = await mk(env, w, parent=parent)

    r = await send(env, w.tok("ba"), "PATCH", task_url(sub), {"status": "done"})

    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["position"]) == ("done", None)


@pytest.mark.parametrize("status", ["archived", "Done", "", "DONE", "doing"])
async def test_ac24_status_outside_set_is_422_and_status_unchanged(
    api_env: ApiEnv, status: str
) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)

    r = await send(env, w.tok("ba"), "PATCH", task_url(t), {"status": status})

    assert error(r) == (422, "validation_error")
    assert (await task_db(env, t)).status == "todo"


@pytest.mark.parametrize("status", ALL_STATUSES)
async def test_ac24_every_status_of_the_set_is_accepted(api_env: ApiEnv, status: str) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)

    r = await send(env, w.tok("ba"), "PATCH", task_url(t), {"status": status})

    assert r.status_code == 200, r.text
    assert r.json()["status"] == status


async def test_ac47_assignee_changes_status_with_full_form_but_not_title(api_env: ApiEnv) -> None:
    """Исполнитель чужой задачи: форма целиком (поля не изменены) + статус — сохранено."""
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, assignee="usr", title="Т", description="О", priority="high")
    full_form = {
        "title": "Т",
        "description": "О",
        "priority": "high",
        "due_date": None,
        "assignee_id": str(w.uid("usr")),
        "status": "in_progress",
    }

    ok = await send(env, w.tok("usr"), "PATCH", task_url(t), full_form)
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "in_progress"

    # изменилось любое из полей правки — 403 целиком, статус тоже не меняется
    for field, value in (
        ("title", "Другое"),
        ("description", "Другое"),
        ("priority", "low"),  # 006/AC-12: «base» больше не значение; «low» отличается от «high»
        ("due_date", "2026-12-01"),
    ):
        r = await send(
            env, w.tok("usr"), "PATCH", task_url(t), {**full_form, "status": "done", field: value}
        )
        assert error(r) == (403, "forbidden"), field
    assert (await task_db(env, t)).status == "in_progress"
    assert (await task_db(env, t)).title == "Т"


async def test_ac46_user_own_task_title_status_ok_assignee_403(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    created = await _create(env, w, "usr", {"title": "Своя", **REQ})
    t = created.json()["id"]

    ok = await send(
        env,
        w.tok("usr"),
        "PATCH",
        task_url(t),
        {"title": "Своя 2", "description": "d", "due_date": "2026-11-11", "status": "done"},
    )
    denied = await send(env, w.tok("usr"), "PATCH", task_url(t), {"assignee_id": str(w.uid("ba2"))})
    cleared = await send(env, w.tok("usr"), "PATCH", task_url(t), {"assignee_id": None})
    same = await send(env, w.tok("usr"), "PATCH", task_url(t), {"assignee_id": str(w.uid("usr"))})

    assert ok.status_code == 200, ok.text
    assert error(denied) == (403, "forbidden")
    assert error(cleared) == (403, "forbidden")
    assert same.status_code == 200  # то же значение — не изменение (D-46)
    assert (await task_db(env, t)).assignee_id == w.uid("usr")


async def test_ac46_ba_owner_changes_assignee_of_user_task(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = (await _create(env, w, "usr", {"title": "Своя", **REQ})).json()["id"]

    r = await send(env, w.tok("ba"), "PATCH", task_url(t), {"assignee_id": str(w.uid("ba2"))})

    assert r.status_code == 200, r.text
    assert r.json()["assignee"]["id"] == str(w.uid("ba2"))


@pytest.mark.parametrize("who", ["usr2", "ba3"])
async def test_d46_membership_is_checked_even_for_empty_and_same_value_patch(
    api_env: ApiEnv, who: str
) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, title="Т")

    for payload in ({}, {"title": "Т"}, {"title": "Другое"}):
        r = await send(env, w.tok(who), "PATCH", task_url(t), payload)
        assert error(r) == (403, "forbidden"), payload
    assert (await task_db(env, t)).title == "Т"


async def test_d46_member_without_rights_gets_200_on_empty_and_same_value_patch(
    api_env: ApiEnv,
) -> None:
    """D-46: участник без прав («Пользователь» usr) на чужой задаче - 200 на пустое и
    совпадающее значение, 403 на реальную правку. Обращён по 002/AC-13 (FR-9): БА-участник
    ba2 (не владелец) ту же реальную правку выполняет."""
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, title="Т")  # usr — участник без прав на чужую задачу

    assert (await send(env, w.tok("usr"), "PATCH", task_url(t), {})).status_code == 200
    assert (await send(env, w.tok("usr"), "PATCH", task_url(t), {"title": "Т"})).status_code == 200
    r = await send(env, w.tok("usr"), "PATCH", task_url(t), {"title": "Чужое"})
    assert error(r) == (403, "forbidden")
    assert (await task_db(env, t)).title == "Т"
    r = await send(env, w.tok("ba2"), "PATCH", task_url(t), {"title": "Чужое"})
    assert r.status_code == 200, r.text
    assert (await task_db(env, t)).title == "Чужое"


async def test_patch_is_all_or_nothing_when_one_field_is_forbidden(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, assignee="usr", title="Т")

    r = await send(
        env,
        w.tok("usr"),
        "PATCH",
        task_url(t),
        {"status": "done", "assignee_id": str(w.uid("ba2"))},
    )

    assert error(r) == (403, "forbidden")
    row = await task_db(env, t)
    assert (row.status, row.assignee_id) == ("todo", w.uid("usr"))


# --- валидация входных данных -----------------------------------------------------------------

BAD_DUE_DATES: list[Any] = [
    "2026-10-20T10:00:00Z",
    "2026-10-20T00:00:00",
    "2026-10-20 10:00:00",
    "2026-02-30",
    "2026-13-01",
    "2026-1-5",
    "20261020",
    " 2026-10-20",
    "2026-10-20 ",
    "2026-10-20\n",
    "",
    "завтра",
    20261020,
    1760918400,
    1760918400.5,
    True,
    ["2026-10-20"],
    {"date": "2026-10-20"},
]


@pytest.mark.parametrize("due", BAD_DUE_DATES, ids=lambda v: repr(v)[:30])
async def test_ac68_d51_create_with_non_date_due_date_is_422_nothing_created(
    api_env: ApiEnv, due: Any
) -> None:
    env = api_env
    w = await make_api_world(env)
    before = await _count(env, w.project_id)

    r = await _create(env, w, "ba", {**REQ, "title": "Срок", "due_date": due})

    assert error(r) == (422, "validation_error")
    assert await _count(env, w.project_id) == before


@pytest.mark.parametrize("due", BAD_DUE_DATES, ids=lambda v: repr(v)[:30])
async def test_ac68_d51_patch_with_non_date_due_date_is_422_unchanged(
    api_env: ApiEnv, due: Any
) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, due_date=date(2026, 1, 2))

    r = await send(env, w.tok("ba"), "PATCH", task_url(t), {"due_date": due})

    assert error(r) == (422, "validation_error")
    assert str((await task_db(env, t)).due_date) == "2026-01-02"


@pytest.mark.parametrize("due", ["2026-10-20", "2028-02-29", "2026-12-31"])
async def test_ac68_d51_valid_dates_round_trip(api_env: ApiEnv, due: str) -> None:
    env = api_env
    w = await make_api_world(env)

    r = await _create(env, w, "ba", {"title": "Срок", "description": "d", "due_date": due})

    assert r.status_code == 201, r.text
    assert r.json()["due_date"] == due


@pytest.mark.parametrize(
    "payload",
    [
        {"title": ""},
        {"title": "   "},
        {"title": "\t\n "},
        {"title": "Я" * 256},
        {"title": "a\x00b"},
        {"title": "Ок", "description": "д" * 10_001},
        {"title": "Ок", "description": "a\x00b"},
        {"title": 5},
        {"title": ["a"]},
        {"title": "Ок", "description": 5},
        {"title": "Ок", "priority": "urgent"},
        {"title": "Ок", "priority": ""},
        {"title": "Ок", "priority": 1},
        {"title": "Ок", "assignee_id": "not-a-uuid"},
        {"title": "Ок", "assignee_id": 5},
        {"title": "Ок", "assignee_id": ""},
        {"description": "без названия"},
        {},
        {"title": None},
        {"title": "Ок", "description": None},
        {"title": "Ок", "priority": None},
    ],
    ids=lambda p: json.dumps(p, ensure_ascii=False)[:50],
)
async def test_ac108_create_invalid_payload_is_422_and_nothing_created(
    api_env: ApiEnv, payload: dict[str, Any]
) -> None:
    env = api_env
    w = await make_api_world(env)
    before = await _count(env, w.project_id)

    # 006: тело дополнено обязательными полями: 422 даёт проверяемая причина, а не их отсутствие
    r = await _create(env, w, "ba", {**REQ, **payload})

    assert error(r) == (422, "validation_error")
    assert await _count(env, w.project_id) == before


@pytest.mark.parametrize(
    "payload",
    [
        {"title": ""},
        {"title": "  "},
        {"title": "Я" * 256},
        {"title": "a\x00b"},
        {"description": "д" * 10_001},
        {"description": "a\x00b"},
        {"title": None},
        {"description": None},
        {"priority": None},
        {"status": None},
        {"priority": "urgent"},
        {"assignee_id": "not-a-uuid"},
        {"assignee_id": 5},
        {"title": 5},
    ],
    ids=lambda p: json.dumps(p, ensure_ascii=False)[:50],
)
async def test_ac108_patch_invalid_payload_is_422_and_data_unchanged(
    api_env: ApiEnv, payload: dict[str, Any]
) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, title="Было", description="Описание")
    before = await task_db(env, t)

    r = await send(env, w.tok("ba"), "PATCH", task_url(t), payload)

    assert error(r) == (422, "validation_error")
    after = await task_db(env, t)
    assert (after.title, after.description, after.priority, after.status, after.updated_at) == (
        before.title,
        before.description,
        before.priority,
        before.status,
        before.updated_at,
    )


async def test_ac108_patch_boundary_lengths_are_accepted(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)

    r = await send(
        env, w.tok("ba"), "PATCH", task_url(t), {"title": "Я" * 255, "description": "д" * 10_000}
    )

    assert r.status_code == 200, r.text


@pytest.mark.parametrize("extra", ["parent_id", "project_id", "position", "author", "x", "id"])
async def test_create_and_patch_with_extra_field_are_422(api_env: ApiEnv, extra: str) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, title="Было")
    before = await _count(env, w.project_id)
    value = str(w.project_id) if extra.endswith("_id") or extra == "id" else "v"

    created = await _create(env, w, "ba", {"title": "Лишнее", extra: value})
    patched = await send(env, w.tok("ba"), "PATCH", task_url(t), {"title": "Стало", extra: value})

    assert error(created) == (422, "validation_error")
    assert error(patched) == (422, "validation_error")
    assert await _count(env, w.project_id) == before
    assert (await task_db(env, t)).title == "Было"


# --- порядок ошибок, гейты, тело --------------------------------------------------------------


async def test_order_schema_422_before_404_before_403(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)
    bad = {"title": ""}

    unknown_project = await send(env, w.tok("ba"), "POST", project_tasks_url(uuid.uuid4()), bad)
    non_member = await send(env, w.tok("usr2"), "POST", project_tasks_url(w.project_id), bad)
    patch_unknown = await send(env, w.tok("ba"), "PATCH", task_url(uuid.uuid4()), bad)
    patch_non_member = await send(env, w.tok("usr2"), "PATCH", task_url(t), bad)
    subtask_non_member = await send(env, w.tok("usr2"), "POST", f"{task_url(t)}/subtasks", bad)

    for r in (unknown_project, non_member, patch_unknown, patch_non_member, subtask_non_member):
        assert error(r) == (422, "validation_error")
    # валидный запрос к тем же объектам: 404, затем 403
    ok_body = {"title": "Ок"}
    assert error(
        await send(env, w.tok("ba"), "POST", project_tasks_url(uuid.uuid4()), ok_body)
    ) == (404, "not_found")
    assert error(
        await send(env, w.tok("usr2"), "POST", project_tasks_url(w.project_id), ok_body)
    ) == (403, "forbidden")


@pytest.mark.parametrize("target", ["project", "task", "subtasks"])
async def test_ac123_broken_json_is_400_without_echo_and_before_401(
    api_env: ApiEnv, target: str
) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w, title="Цел")
    method, url = {
        "project": ("POST", project_tasks_url(w.project_id)),
        "task": ("PATCH", task_url(t)),
        "subtasks": ("POST", f"{task_url(t)}/subtasks"),
    }[target]
    raw = '{"title": "Секрет-задачи'.encode()
    before = await _count(env, w.project_id)

    for token in (w.tok("ba"), None, w.tok("usr2"), w.tok("ta")):
        r = await send(env, token, method, url, raw=raw)
        assert error(r) == (400, "bad_request"), (target, token)
        assert "Секрет-задачи" not in r.text
    assert await _count(env, w.project_id) == before
    assert (await task_db(env, t)).title == "Цел"


async def test_ac123_valid_json_wrong_fields_without_session_is_401_not_422(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)
    for method, url in (
        ("POST", project_tasks_url(w.project_id)),
        ("PATCH", task_url(t)),
        ("POST", f"{task_url(t)}/subtasks"),
    ):
        r = await send(env, None, method, url, {"title": 1, "x": 2})
        assert error(r) == (401, "not_authenticated"), (method, url)


async def test_ac123_wrong_fields_with_role_without_permission_is_403_not_422(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)
    for who, expected in (("ta", (403, "forbidden")), ("norole", (403, "no_role"))):
        for method, url in (
            ("POST", project_tasks_url(w.project_id)),
            ("PATCH", task_url(t)),
            ("POST", f"{task_url(t)}/subtasks"),
        ):
            r = await send(env, w.tok(who), method, url, {"title": 1})
            assert error(r) == expected, (who, method)


async def test_body_that_is_not_an_object_or_has_wrong_content_type_is_422(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_api_world(env)
    before = await _count(env, w.project_id)
    url = project_tasks_url(w.project_id)

    for body in (["title"], "title", 5, None):
        r = await send(env, w.tok("ba"), "POST", url, raw=json.dumps(body).encode())
        assert error(r) == (422, "validation_error"), body
    r = await env.client.post(
        url,
        content=b'{"title": "x"}',
        headers={**env.auth(w.tok("ba")), "Content-Type": "text/plain"},
    )
    assert error(r) == (422, "validation_error")
    assert await _count(env, w.project_id) == before


async def test_ac75_ac4_gates_on_every_task_route(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)
    table: list[tuple[str, str, Any]] = [
        ("GET", project_tasks_url(w.project_id), None),
        ("POST", project_tasks_url(w.project_id), {"title": "x"}),
        ("GET", "/api/v1/me/tasks", None),
        ("GET", task_url(t), None),
        ("PATCH", task_url(t), {"title": "x"}),
        ("DELETE", task_url(t), None),
        ("POST", f"{task_url(t)}/subtasks", {"title": "x"}),
    ]
    for method, url, body in table:
        assert error(await send(env, None, method, url, body)) == (401, "not_authenticated")
        assert error(await send(env, w.tok("norole"), method, url, body)) == (403, "no_role")
        assert error(await send(env, w.tok("otp"), method, url, body)) == (
            403,
            "password_change_required",
        )
        assert error(await send(env, w.tok("ta"), method, url, body)) == (403, "forbidden")
    assert (await task_db(env, t)).title == "Задача"
    assert (await task_db(env, t)).deleted_at is None


async def test_project_deleted_makes_create_404(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    assert (await _create(env, w, "ba", {"title": "До удаления", **REQ})).status_code == 201
    assert (await send(env, w.tok("ba"), "DELETE", pj(w.project_id))).status_code == 204

    r = await _create(env, w, "ba", {"title": "В удалённый", **REQ})

    assert error(r) == (404, "not_found")


# --- AC-124: 503 ------------------------------------------------------------------------------


async def test_ac124_busy_project_row_gives_503_on_create_patch_delete_subtask(
    committed_api_env: ApiEnv,
) -> None:
    env = committed_api_env
    w = await make_api_world(env)
    t = await mk(env, w, title="Цель")
    before = await _count(env, w.project_id)

    async with busy_database(env), hold_row(env, "project", w.project_id):
        calls: list[tuple[str, str, Any]] = [
            ("POST", project_tasks_url(w.project_id), {"title": "Занято"}),
            ("PATCH", task_url(t), {"title": "Занято"}),
            ("DELETE", task_url(t), None),
            ("POST", f"{task_url(t)}/subtasks", {"title": "Занято"}),
        ]
        for method, url, body in calls:
            r = await send(env, w.tok("ba"), method, url, body)
            assert r.status_code == 503, (method, url, r.text)
            assert r.headers.get("retry-after") == "5"
            assert r.json()["code"] == "service_busy"
            assert "Занято" not in r.text

    row = await task_db(env, t)
    assert (row.title, row.deleted_at) == ("Цель", None)
    assert await _count(env, w.project_id) == before
    ok = await send(env, w.tok("ba"), "PATCH", task_url(t), {"title": "После"})
    assert ok.status_code == 200, ok.text  # состояние восстановилось


async def test_ac124_busy_task_row_gives_503_on_patch_and_delete_but_read_works(
    committed_api_env: ApiEnv,
) -> None:
    env = committed_api_env
    w = await make_api_world(env)
    t = await mk(env, w, title="Цель")

    async with busy_database(env), hold_row(env, "task", t):
        read = await send(env, w.tok("ba"), "GET", task_url(t))
        assert read.status_code == 200, read.text
        for method, body in (("PATCH", {"title": "Занято"}), ("DELETE", None)):
            r = await send(env, w.tok("ba"), method, task_url(t), body)
            assert r.status_code == 503, (method, r.text)
            assert r.headers.get("retry-after") == "5"
            assert r.json()["code"] == "service_busy"

    row = await task_db(env, t)
    assert (row.title, row.deleted_at) == ("Цель", None)


async def test_t73_review_domain_service_busy_has_retry_after_header(api_env: ApiEnv) -> None:
    """Ревью T73 п.1: ``ServiceBusy`` из домена (не ``DBAPIError``) -> тот же заголовок."""
    import httpx

    from app.core.errors import ServiceBusy

    async def busy() -> Any:
        raise ServiceBusy()

    api_env.app.add_api_route("/_t/domain-busy", busy, methods=["POST"])
    transport = httpx.ASGITransport(app=api_env.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post("/_t/domain-busy")

    assert r.status_code == 503
    assert r.headers.get("retry-after") == "5"
    assert r.json()["code"] == "service_busy"
    assert set(r.json()) == {"detail", "code"}


# --- контракт: OpenAPI и маршруты -------------------------------------------------------------

TASK_OPERATIONS: set[tuple[str, str]] = {
    ("GET", "/api/v1/projects/{}/tasks"),
    ("POST", "/api/v1/projects/{}/tasks"),
    ("GET", "/api/v1/me/tasks"),
    ("GET", "/api/v1/tasks/{}"),
    ("PATCH", "/api/v1/tasks/{}"),
    ("DELETE", "/api/v1/tasks/{}"),
    ("POST", "/api/v1/tasks/{}/subtasks"),
}
WITH_BODY = {
    ("POST", "/api/v1/projects/{}/tasks"),
    ("PATCH", "/api/v1/tasks/{}"),
    ("POST", "/api/v1/tasks/{}/subtasks"),
}


def _norm(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path)


def _task_ops(spec: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for path, item in spec["paths"].items():
        for method, op in item.items():
            key = (method.upper(), _norm(path))
            if key in TASK_OPERATIONS:
                found[key] = op
    return found


def _resolve(spec: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    if "$ref" in node:
        return _resolve(spec, spec["components"]["schemas"][node["$ref"].rsplit("/", 1)[1]])
    return node


def _variants(node: dict[str, Any]) -> list[dict[str, Any]]:
    return [node, *node.get("anyOf", []), *node.get("oneOf", [])]


def _is_nullable(spec: dict[str, Any], node: dict[str, Any]) -> bool:
    return any(v.get("type") == "null" or v.get("nullable") is True for v in _variants(node))


async def test_t77_openapi_has_the_seven_task_operations(api_env: ApiEnv) -> None:
    spec = api_env.app.openapi()
    assert set(_task_ops(spec)) == TASK_OPERATIONS
    walked = {(m, _norm(p)) for m, p in _api_operations(api_env)}
    assert walked >= TASK_OPERATIONS


async def test_t77_declared_errors_follow_the_table(api_env: ApiEnv) -> None:
    ops = _task_ops(api_env.app.openapi())
    for key, op in ops.items():
        declared = set(op["responses"])
        assert {"401", "403", "422"} <= declared, key
        assert ("400" in declared) == (key in WITH_BODY), key  # D-65
        assert ("404" in declared) == ("{}" in key[1]), key
        assert "409" not in declared, key
    assert ops[("POST", "/api/v1/projects/{}/tasks")]["responses"]["201"]
    assert ops[("POST", "/api/v1/tasks/{}/subtasks")]["responses"]["201"]
    assert "204" in ops[("DELETE", "/api/v1/tasks/{}")]["responses"]


async def test_t77_operation_ids_unique_and_equal_function_names(api_env: ApiEnv) -> None:
    from tests.api.test_route_guards import _iter_routes

    spec = api_env.app.openapi()
    all_ids = [op["operationId"] for item in spec["paths"].values() for op in item.values()]
    assert len(all_ids) == len(set(all_ids))
    names: dict[tuple[str, str], str] = {}
    for route in _iter_routes(api_env.app.routes):
        for method in set(route.methods) - {"HEAD", "OPTIONS"}:
            names[(method, _norm(route.path))] = route.endpoint.__name__
    ops = _task_ops(spec)
    assert set(ops) == TASK_OPERATIONS
    for key, op in ops.items():
        assert op["operationId"] == names[key], key


async def test_t77_response_schemas_match_plan_11_4_and_nulls_only_where_allowed(
    api_env: ApiEnv,
) -> None:
    spec = api_env.app.openapi()
    schemas = spec["components"]["schemas"]
    detail, item, brief = schemas["TaskDetail"], schemas["TaskListItem"], schemas["TaskBrief"]
    assert set(detail["properties"]) == DETAIL_FIELDS
    assert set(item["properties"]) == LIST_FIELDS
    assert set(brief["properties"]) == BRIEF_FIELDS
    for schema in (detail, item, brief):
        assert set(schema["required"]) == set(schema["properties"])
    assert "description" not in item["properties"]  # в списках описания нет
    perms = _resolve(spec, detail["properties"]["permissions"])
    assert set(perms["properties"]) == PERM_FIELDS
    nullable_detail = {"parent_id", "due_date", "assignee", "position", "progress"}
    for name, prop in detail["properties"].items():
        assert _is_nullable(spec, prop) == (name in nullable_detail), name
    for name, prop in item["properties"].items():
        assert _is_nullable(spec, prop) == (name in {"parent_id", "due_date", "assignee"}), name
    for name, prop in brief["properties"].items():
        assert _is_nullable(spec, prop) == (name in {"due_date", "assignee"}), name
    assert any(n.startswith("Page_TaskListItem") for n in schemas)
    for schema in (detail, item, brief):
        for field in ("status", "priority"):
            if field in schema["properties"]:
                enum = _resolve(spec, schema["properties"][field])["enum"]
                assert set(enum) == (
                    set(ALL_STATUSES) if field == "status" else {"low", "medium", "high"}
                )


@pytest.mark.parametrize("name", ["TaskCreate", "TaskUpdate"])
async def test_t77_request_schemas_forbid_extra_and_have_no_null_where_required(
    api_env: ApiEnv, name: str
) -> None:
    spec = api_env.app.openapi()
    schema = spec["components"]["schemas"][name]
    expected = {"title", "description", "assignee_id", "due_date", "priority"}
    if name == "TaskUpdate":
        expected |= {"status"}
    assert set(schema["properties"]) == expected
    assert schema.get("additionalProperties") is False
    required = set(schema.get("required", []))
    assert required == ({"title"} if name == "TaskCreate" else set())
    props = schema["properties"]
    for field in ("title", "description", "priority", "status"):
        if field in props:
            assert not _is_nullable(spec, props[field]), field
    for field in ("assignee_id", "due_date"):
        assert _is_nullable(spec, props[field]), field
    assert any(v.get("type") == "string" for v in _variants(props["due_date"]))


async def test_t77_committed_contract_files_contain_task_routes() -> None:
    spec = json.loads((REPO_ROOT / "docs" / "api" / "openapi.json").read_text(encoding="utf-8"))
    committed = {(m.upper(), _norm(p)) for p, item in spec["paths"].items() for m in item}
    assert committed >= TASK_OPERATIONS
    schemas = spec["components"]["schemas"]
    for name in ("TaskCreate", "TaskUpdate", "TaskDetail", "TaskListItem", "TaskBrief"):
        assert name in schemas, name
    for name in ("TaskCreate", "TaskUpdate"):
        assert schemas[name].get("additionalProperties") is False
    dts = (REPO_ROOT / "frontend" / "src" / "shared" / "api" / "schema.d.ts").read_text(
        encoding="utf-8"
    )
    in_dts = {_norm(p) for p in re.findall(r'"(/api/v1/[^"]*)"', dts)}
    for _m, path in TASK_OPERATIONS:
        assert path in in_dts, path
    for name in ("TaskDetail", "TaskListItem", "TaskCreate", "TaskUpdate"):
        assert name in dts, name
