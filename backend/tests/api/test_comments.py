"""T80: API комментариев (AC-58, AC-103, AC-21, FR-23, D-65, plan §11.4).

``GET|POST /tasks/{id}/comments``, ``PATCH|DELETE /comments/{id}``. Тело ``{body}``: 1-10 000
символов до очистки, ``extra=forbid``. Порядок: гейт роли 401/403 -> 422 схемы -> 404 -> 403 ->
422 домена. ``Retry-After`` только у 503.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from tests.conftest import ApiEnv
from tests.factories import make_comment
from tests.tasks_api_support import (
    PAGE_FIELDS,
    TASK_REQ,
    USER_REF_FIELDS,
    ApiWorld,
    busy_database,
    error,
    hold_row,
    make_api_world,
    make_foreign,
    mk,
    rows,
    send,
    task_url,
)

COMMENT_FIELDS = {
    "id",
    "task_id",
    "author",
    "body",
    "is_deleted",
    "created_at",
    "edited_at",
    "permissions",
}
PERMS = {"edit", "delete"}


def _list_url(task_id: Any, query: str = "") -> str:
    return f"{task_url(task_id)}/comments{query}"


def _c_url(comment_id: Any) -> str:
    return f"/api/v1/comments/{comment_id}"


async def _comment(
    env: ApiEnv, w: ApiWorld, task_id: uuid.UUID, by: str = "usr", **kw: Any
) -> uuid.UUID:
    async with env.sessionmaker() as session:
        row = await make_comment(
            session, task_id=task_id, workspace_id=w.ws.id, created_by=w.uid(by), **kw
        )
        await session.commit()
    return row.id


async def _db(env: ApiEnv, comment_id: Any) -> Any:
    found = await rows(env, "SELECT * FROM comment WHERE id = :c", c=uuid.UUID(str(comment_id)))
    assert len(found) == 1
    return found[0]


async def _count(env: ApiEnv, task_id: uuid.UUID) -> int:
    found = await rows(env, "SELECT count(*) FROM comment WHERE task_id = :t", t=task_id)
    return int(found[0][0])


# --- POST -------------------------------------------------------------------------------------


async def test_fr23_create_returns_201_comment_shape_and_stores(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)

    r = await send(env, w.tok("usr"), "POST", _list_url(t), {"body": "Привет"})

    assert r.status_code == 201, r.text
    body = r.json()
    assert set(body) == COMMENT_FIELDS
    assert set(body["author"]) == USER_REF_FIELDS
    assert set(body["permissions"]) == PERMS
    assert body["task_id"] == str(t)
    assert body["author"] == {"id": str(w.uid("usr")), "login": w.login("usr")}
    assert body["body"] == "Привет"
    assert body["is_deleted"] is False
    assert body["edited_at"] is None
    assert body["permissions"] == {"edit": True, "delete": True}
    row = await _db(env, body["id"])
    assert (row.task_id, row.created_by, row.body, row.workspace_id) == (
        t,
        w.uid("usr"),
        "Привет",
        w.ws.id,
    )
    assert "retry-after" not in r.headers


@pytest.mark.parametrize("who", ["ba", "ba2", "usr"])
async def test_ac103_members_of_every_role_can_comment(api_env: ApiEnv, who: str) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)  # чужая задача, исполнителя нет

    r = await send(env, w.tok(who), "POST", _list_url(t), {"body": "ok"})

    assert r.status_code == 201, r.text
    assert r.json()["author"]["id"] == str(w.uid(who))


async def test_fr23_comment_on_subtask_belongs_to_subtask(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    parent = await mk(env, w)
    sub = await mk(env, w, parent=parent)

    r = await send(env, w.tok("ba"), "POST", _list_url(sub), {"body": "К подзадаче"})

    assert r.status_code == 201, r.text
    assert r.json()["task_id"] == str(sub)
    assert (await _count(env, sub), await _count(env, parent)) == (1, 0)


async def test_ac58_create_sanitizes_html_in_stored_and_returned_body(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)

    r = await send(
        env, w.tok("ba"), "POST", _list_url(t), {"body": "Привет <b>мир</b><script>x()</script>!"}
    )

    assert r.status_code == 201, r.text
    assert r.json()["body"] == "Привет мир!"
    assert (await _db(env, r.json()["id"])).body == "Привет мир!"


@pytest.mark.parametrize("body", ["   \n ", "<b></b>", "<script>alert(1)</script>", "<!-- c -->"])
async def test_ac58_create_empty_after_sanitize_is_422_domain_nothing_stored(
    api_env: ApiEnv, body: str
) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)

    r = await send(env, w.tok("ba"), "POST", _list_url(t), {"body": body})

    assert error(r) == (422, "validation_error")
    assert await _count(env, t) == 0


async def test_ac58_create_10000_ok_10001_and_empty_are_422(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)

    ok = await send(env, w.tok("ba"), "POST", _list_url(t), {"body": "д" * 10_000})
    too_long = await send(env, w.tok("ba"), "POST", _list_url(t), {"body": "д" * 10_001})
    empty = await send(env, w.tok("ba"), "POST", _list_url(t), {"body": ""})

    assert ok.status_code == 201, ok.text
    assert error(too_long) == (422, "validation_error")
    assert error(empty) == (422, "validation_error")
    assert await _count(env, t) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"body": None},
        {"body": 5},
        {"body": ["a"]},
        {"body": "a\x00b"},
        {"body": "ok", "task_id": str(uuid.uuid4())},
        {"body": "ok", "author": "x"},
        {"body": "ok", "extra": 1},
    ],
)
async def test_d65_create_schema_violations_are_422_validation_error(
    api_env: ApiEnv, payload: dict[str, Any]
) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)

    r = await send(env, w.tok("ba"), "POST", _list_url(t), payload)

    assert error(r) == (422, "validation_error")
    assert await _count(env, t) == 0


async def test_d65_schema_422_comes_before_404_and_403(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)

    unknown = await send(env, w.tok("ba"), "POST", _list_url(uuid.uuid4()), {"body": ""})
    stranger = await send(env, w.tok("usr2"), "POST", _list_url(t), {"body": ""})
    bad_id = await send(env, w.tok("ba"), "POST", _list_url("not-a-uuid"), {"body": "x"})

    assert error(unknown) == (422, "validation_error")
    assert error(stranger) == (422, "validation_error")
    assert error(bad_id) == (422, "validation_error")


async def test_d65_domain_422_comes_after_404_and_403(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)

    unknown = await send(env, w.tok("usr"), "POST", _list_url(uuid.uuid4()), {"body": "<b></b>"})
    stranger = await send(env, w.tok("usr2"), "POST", _list_url(t), {"body": "<b></b>"})
    member = await send(env, w.tok("usr"), "POST", _list_url(t), {"body": "<b></b>"})

    assert error(unknown) == (404, "not_found")
    assert error(stranger) == (403, "forbidden")
    assert error(member) == (422, "validation_error")


@pytest.mark.parametrize(
    "method,make_url",
    [
        ("POST", lambda ids: _list_url(ids["task"])),
        ("PATCH", lambda ids: _c_url(ids["comment"])),
    ],
)
@pytest.mark.parametrize("raw", [b"{", b"not json", b'{"body": }'])
async def test_d65_invalid_json_is_400_bad_request(
    api_env: ApiEnv, method: str, make_url: Any, raw: bytes
) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)
    c = await _comment(env, w, t, "usr")

    r = await send(env, w.tok("usr"), method, make_url({"task": t, "comment": c}), raw=raw)

    assert error(r) == (400, "bad_request")
    assert (await _db(env, c)).body == "Комментарий"
    assert await _count(env, t) == 1


@pytest.mark.parametrize(
    "who,expected",
    [("usr2", (403, "forbidden")), ("ba3", (403, "forbidden"))],
)
async def test_ac103_create_non_member_is_403_nothing_stored(
    api_env: ApiEnv, who: str, expected: tuple[int, str]
) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)

    r = await send(env, w.tok(who), "POST", _list_url(t), {"body": "x"})

    assert error(r) == expected
    assert await _count(env, t) == 0


async def test_ac103_ba_becomes_able_after_membership(api_env: ApiEnv) -> None:
    """AC 002 AC-15: БА-неучастник ``ba3`` (прежде СМ ``sm``) - 403, после вступления - 200."""
    from tests.tasks_api_support import add_member_row

    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)

    assert error(await send(env, w.tok("ba3"), "GET", _list_url(t))) == (403, "forbidden")
    await add_member_row(env, w, w.people["ba3"].user)
    ok = await send(env, w.tok("ba3"), "GET", _list_url(t))

    assert ok.status_code == 200, ok.text


@pytest.mark.parametrize("who", ["ta", "norole"])
@pytest.mark.parametrize("call", ["list", "create", "edit", "delete"])
async def test_fr10_tech_admin_and_no_role_get_403_before_404(
    api_env: ApiEnv, who: str, call: str
) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)
    c = await _comment(env, w, t, "usr")
    real = {"list": _list_url(t), "create": _list_url(t), "edit": _c_url(c), "delete": _c_url(c)}
    fake = {
        "list": _list_url(uuid.uuid4()),
        "create": _list_url(uuid.uuid4()),
        "edit": _c_url(uuid.uuid4()),
        "delete": _c_url(uuid.uuid4()),
    }
    method = {"list": "GET", "create": "POST", "edit": "PATCH", "delete": "DELETE"}[call]
    payload = {"body": "x"} if call in {"create", "edit"} else None

    for url in (real[call], fake[call]):
        r = await send(env, w.tok(who), method, url, payload)
        assert error(r) == (403, "no_role" if who == "norole" else "forbidden"), url
        assert "retry-after" not in r.headers
    assert (await _db(env, c)).body == "Комментарий"
    assert (await _db(env, c)).deleted_at is None


@pytest.mark.parametrize(
    "method,url,payload",
    [
        ("GET", "/api/v1/tasks/{t}/comments", None),
        ("POST", "/api/v1/tasks/{t}/comments", {"body": "x"}),
        ("PATCH", "/api/v1/comments/{c}", {"body": "x"}),
        ("DELETE", "/api/v1/comments/{c}", None),
    ],
)
async def test_d65_without_session_is_401(
    api_env: ApiEnv, method: str, url: str, payload: Any
) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)
    c = await _comment(env, w, t)

    r = await send(env, None, method, url.format(t=t, c=c), payload)

    assert r.status_code == 401, r.text


async def test_d65_blocked_user_is_401(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)

    r = await send(env, w.tok("blocked"), "GET", _list_url(t))

    assert r.status_code == 401, r.text


async def test_fr23_create_on_unknown_or_deleted_task_or_project_is_404(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    dead = await mk(env, w, deleted=True)
    gone_parent = await mk(env, w, deleted=True)
    sub_of_dead = await mk(env, w, parent=gone_parent, deleted=True)
    live = await mk(env, w)
    assert (
        await send(env, w.tok("ba"), "POST", _list_url(live), {"body": "жив"})
    ).status_code == 201  # маршрут есть: 404 ниже именно про задачу

    for tid in (uuid.uuid4(), dead, sub_of_dead):
        r = await send(env, w.tok("ba"), "POST", _list_url(tid), {"body": "x"})
        assert error(r) == (404, "not_found"), tid
        assert error(await send(env, w.tok("ba"), "GET", _list_url(tid))) == (404, "not_found")


async def test_ac21_foreign_workspace_task_and_comment_are_404_untouched(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    foreign = await make_foreign(env)
    made = await send(
        env,
        foreign.ba_token,
        "POST",
        f"/api/v1/projects/{foreign.project_id}/tasks",
        {"title": "Чужая", **TASK_REQ},
    )
    tid = made.json()["id"]
    cm = await send(env, foreign.ba_token, "POST", _list_url(tid), {"body": "секрет"})
    assert cm.status_code == 201, cm.text
    cid = cm.json()["id"]

    for who in ("ba", "usr"):
        for method, url, payload in (
            ("GET", _list_url(tid), None),
            ("POST", _list_url(tid), {"body": "взлом"}),
            ("PATCH", _c_url(cid), {"body": "взлом"}),
            ("DELETE", _c_url(cid), None),
        ):
            r = await send(env, w.tok(who), method, url, payload)
            assert error(r) == (404, "not_found"), (who, method)
            assert "секрет" not in r.text
    row = await _db(env, cid)
    assert (row.body, row.deleted_at, row.edited_at) == ("секрет", None, None)
    assert await _count(env, uuid.UUID(tid)) == 1


# --- GET --------------------------------------------------------------------------------------


async def test_fr23_list_shape_order_and_permissions_per_actor(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)
    t0 = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    late = await _comment(env, w, t, "ba", body="поздний", created_at=t0 + timedelta(hours=1))
    early = await _comment(env, w, t, "usr", body="ранний", created_at=t0)

    r = await send(env, w.tok("usr"), "GET", _list_url(t))

    assert r.status_code == 200, r.text
    page = r.json()
    assert set(page) == PAGE_FIELDS
    assert (page["page"], page["page_size"], page["has_next"]) == (1, 50, False)
    assert [i["id"] for i in page["items"]] == [str(early), str(late)]
    mine, foreign = page["items"]
    assert set(mine) == COMMENT_FIELDS
    assert mine["permissions"] == {"edit": True, "delete": True}
    assert foreign["permissions"] == {"edit": False, "delete": False}
    assert foreign["author"] == {"id": str(w.uid("ba")), "login": w.login("ba")}
    owner_view = (await send(env, w.tok("ba"), "GET", _list_url(t))).json()["items"]
    assert [i["permissions"] for i in owner_view] == [
        {"edit": False, "delete": True},  # БА-владелец удаляет чужой, править не может
        {"edit": True, "delete": True},
    ]


async def test_fr47_list_paginates_and_validates_params(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)
    t0 = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    ids = [
        str(await _comment(env, w, t, "usr", created_at=t0 + timedelta(minutes=i)))
        for i in range(5)
    ]

    p1 = (await send(env, w.tok("usr"), "GET", _list_url(t, "?page=1&page_size=2"))).json()
    p3 = (await send(env, w.tok("usr"), "GET", _list_url(t, "?page=3&page_size=2"))).json()

    assert [i["id"] for i in p1["items"]] == ids[:2]
    assert (p1["page"], p1["page_size"], p1["has_next"]) == (1, 2, True)
    assert [i["id"] for i in p3["items"]] == ids[4:]
    assert p3["has_next"] is False
    for q in ("?page=0", "?page_size=0", "?page_size=101", "?page=x"):
        r = await send(env, w.tok("usr"), "GET", _list_url(t, q))
        assert error(r) == (422, "validation_error"), q


async def test_ac58_list_deleted_comment_is_stub_without_body(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)
    t0 = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    alive = await _comment(env, w, t, "ba", body="живой", created_at=t0)
    gone = await _comment(
        env,
        w,
        t,
        "usr",
        body="секрет",
        created_at=t0 + timedelta(minutes=1),
        deleted_at=t0 + timedelta(days=1),
        deleted_batch_id=uuid.uuid4(),
    )

    r = await send(env, w.tok("ba"), "GET", _list_url(t))

    assert "секрет" not in r.text
    by_id = {i["id"]: i for i in r.json()["items"]}
    assert set(by_id) == {str(alive), str(gone)}
    stub = by_id[str(gone)]
    assert stub["body"] is None
    assert stub["is_deleted"] is True
    assert stub["author"] == {"id": str(w.uid("usr")), "login": w.login("usr")}
    assert stub["permissions"] == {"edit": False, "delete": False}
    assert by_id[str(alive)]["is_deleted"] is False


async def test_fr23_list_of_other_tasks_comments_not_mixed(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    a, b = await mk(env, w), await mk(env, w)
    ca = await _comment(env, w, a, "usr")
    await _comment(env, w, b, "usr")

    items = (await send(env, w.tok("ba"), "GET", _list_url(a))).json()["items"]

    assert [i["id"] for i in items] == [str(ca)]


# --- PATCH ------------------------------------------------------------------------------------


async def test_ac58_edit_by_author_200_sets_body_and_edited_at(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)
    c = await _comment(env, w, t, "usr", body="было")

    r = await send(env, w.tok("usr"), "PATCH", _c_url(c), {"body": "стало <i>x</i>"})

    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == COMMENT_FIELDS
    assert (body["id"], body["task_id"], body["body"]) == (str(c), str(t), "стало x")
    assert body["edited_at"] is not None
    assert body["is_deleted"] is False
    row = await _db(env, c)
    assert row.body == "стало x"
    assert row.edited_at is not None
    assert row.created_by == w.uid("usr")


@pytest.mark.parametrize("who", ["ba", "ba2"])
async def test_ac58_edit_foreign_comment_is_403_even_for_owner(api_env: ApiEnv, who: str) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)
    c = await _comment(env, w, t, "usr", body="моё")

    r = await send(env, w.tok(who), "PATCH", _c_url(c), {"body": "взлом"})

    assert error(r) == (403, "forbidden")
    row = await _db(env, c)
    assert (row.body, row.edited_at) == ("моё", None)


async def test_fr23_edit_non_member_is_403_and_unknown_is_404(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)
    c = await _comment(env, w, t, "usr")

    stranger = await send(env, w.tok("usr2"), "PATCH", _c_url(c), {"body": "x"})
    unknown = await send(env, w.tok("usr2"), "PATCH", _c_url(uuid.uuid4()), {"body": "x"})

    assert error(stranger) == (403, "forbidden")
    assert error(unknown) == (404, "not_found")


async def test_ac58_edit_422_variants_leave_comment_unchanged(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)
    c = await _comment(env, w, t, "usr", body="было")

    for payload in (
        {"body": ""},
        {"body": "д" * 10_001},
        {"body": "<b></b>"},
        {},
        {"body": "a\x00"},
        {"body": "x", "task_id": str(t)},
    ):
        r = await send(env, w.tok("usr"), "PATCH", _c_url(c), payload)
        assert error(r) == (422, "validation_error"), payload
    row = await _db(env, c)
    assert (row.body, row.edited_at) == ("было", None)


async def test_fr23_edit_deleted_comment_or_of_deleted_task_is_404(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)
    dead_t = await mk(env, w)
    gone = await _comment(
        env, w, t, "usr", deleted_at=datetime(2026, 4, 1, tzinfo=UTC), deleted_batch_id=uuid.uuid4()
    )
    in_dead = await _comment(env, w, dead_t, "usr")
    live = await _comment(env, w, t, "usr")
    assert (await send(env, w.tok("usr"), "PATCH", _c_url(live), {"body": "ok"})).status_code == 200
    assert (await send(env, w.tok("ba"), "DELETE", task_url(dead_t))).status_code == 204

    for cid in (gone, in_dead):
        r = await send(env, w.tok("usr"), "PATCH", _c_url(cid), {"body": "x"})
        assert error(r) == (404, "not_found"), cid


async def test_fr23_edit_by_author_removed_from_project_is_403(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)
    c = await _comment(env, w, t, "usr", body="было")
    removed = await send(
        env, w.tok("ba"), "DELETE", f"/api/v1/projects/{w.project_id}/members/{w.uid('usr')}"
    )
    assert removed.status_code == 204, removed.text

    r = await send(env, w.tok("usr"), "PATCH", _c_url(c), {"body": "стало"})

    assert error(r) == (403, "forbidden")
    assert (await _db(env, c)).body == "было"


# --- DELETE -----------------------------------------------------------------------------------


async def test_ac58_author_deletes_own_204_soft_and_list_shows_stub(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)
    c = await _comment(env, w, t, "usr", body="удали меня")

    r = await send(env, w.tok("usr"), "DELETE", _c_url(c))

    assert r.status_code == 204, r.text
    assert r.content == b""
    row = await _db(env, c)
    assert row.deleted_at is not None
    assert row.deleted_batch_id is not None
    assert row.body == "удали меня"  # мягкое удаление: текст в БД для корзины
    items = (await send(env, w.tok("ba"), "GET", _list_url(t))).json()["items"]
    assert [(i["id"], i["body"], i["is_deleted"]) for i in items] == [(str(c), None, True)]
    assert "удали меня" not in json.dumps(items, ensure_ascii=False)


async def test_ac58_owner_and_ba_member_delete_foreign(api_env: ApiEnv) -> None:
    """AC 002 AC-13: владелец и БА-участник ``ba2`` (прежде СМ ``sm_m``) удаляют чужой."""
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)
    by_owner = await _comment(env, w, t, "usr")
    by_ba2 = await _comment(env, w, t, "usr")

    r1 = await send(env, w.tok("ba"), "DELETE", _c_url(by_owner))
    r2 = await send(env, w.tok("ba2"), "DELETE", _c_url(by_ba2))

    assert (r1.status_code, r2.status_code) == (204, 204)
    assert (await _db(env, by_owner)).deleted_at is not None
    assert (await _db(env, by_ba2)).deleted_at is not None


@pytest.mark.parametrize("who", ["usr2", "ba3"])
async def test_ac58_delete_foreign_by_non_owner_or_non_member_is_403(
    api_env: ApiEnv, who: str
) -> None:
    """002/AC-13: ba2 (БА-участник не владелец) убран - он удаляет чужой комментарий, см.
    ``test_002_ac13_ba_non_owner_member_deletes_foreign``; 403 остаётся для не-участников."""
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)
    c = await _comment(env, w, t, "usr")

    r = await send(env, w.tok(who), "DELETE", _c_url(c))

    assert error(r) == (403, "forbidden")
    assert (await _db(env, c)).deleted_at is None


async def test_002_ac13_ba_non_owner_member_deletes_foreign(api_env: ApiEnv) -> None:
    """002/AC-13 (FR-9; обращает прежний 403 для ba2 из
    ``test_ac58_delete_foreign_by_non_owner_or_non_member_is_403``): БА-участник не владелец
    удаляет чужой комментарий - 204, мягко."""
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)
    c = await _comment(env, w, t, "usr")

    r = await send(env, w.tok("ba2"), "DELETE", _c_url(c))

    assert r.status_code == 204, r.text
    assert (await _db(env, c)).deleted_at is not None


async def test_ac58_user_cannot_delete_foreign_comment_403(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)
    c = await _comment(env, w, t, "ba")

    r = await send(env, w.tok("usr"), "DELETE", _c_url(c))

    assert error(r) == (403, "forbidden")
    assert (await _db(env, c)).deleted_at is None


async def test_fr23_delete_twice_and_unknown_are_404(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)
    c = await _comment(env, w, t, "usr")
    assert (await send(env, w.tok("usr"), "DELETE", _c_url(c))).status_code == 204
    first = await _db(env, c)

    again = await send(env, w.tok("usr"), "DELETE", _c_url(c))
    unknown = await send(env, w.tok("usr"), "DELETE", _c_url(uuid.uuid4()))
    bad_id = await send(env, w.tok("usr"), "DELETE", _c_url("not-a-uuid"))

    assert error(again) == (404, "not_found")
    assert error(unknown) == (404, "not_found")
    assert error(bad_id) == (422, "validation_error")
    assert (await _db(env, c)).deleted_batch_id == first.deleted_batch_id


async def test_d56_task_delete_hides_its_comments_from_comment_api(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)
    c = await _comment(env, w, t, "usr")
    before = await send(env, w.tok("ba"), "GET", _list_url(t))
    assert [i["id"] for i in before.json()["items"]] == [str(c)]
    assert (await send(env, w.tok("ba"), "DELETE", task_url(t))).status_code == 204

    for method, url, payload in (
        ("GET", _list_url(t), None),
        ("POST", _list_url(t), {"body": "x"}),
        ("PATCH", _c_url(c), {"body": "x"}),
        ("DELETE", _c_url(c), None),
    ):
        r = await send(env, w.tok("ba"), method, url, payload)
        assert error(r) == (404, "not_found"), method


# --- 503 --------------------------------------------------------------------------------------


async def test_d40_busy_project_row_gives_503_retry_after_only_there(
    committed_api_env: ApiEnv,
) -> None:
    env = committed_api_env
    w = await make_api_world(env)
    t = await mk(env, w)
    c = await _comment(env, w, t, "usr")

    async with busy_database(env), hold_row(env, "project", w.project_id):
        # FOR SHARE на проекте несовместим с FOR UPDATE держателя
        r = await send(env, w.tok("usr"), "POST", _list_url(t), {"body": "x"})
        assert r.status_code == 503, r.text
        assert r.headers.get("retry-after") == "5"
        assert r.json()["code"] == "service_busy"
        r2 = await send(env, w.tok("usr"), "DELETE", _c_url(c))
        assert (r2.status_code, r2.headers.get("retry-after")) == (503, "5")
        r3 = await send(env, w.tok("usr2"), "POST", _list_url(t), {"body": "x"})
        assert "retry-after" not in r3.headers or r3.status_code == 503

    assert await _count(env, t) == 1
    assert (await _db(env, c)).deleted_at is None
    ok = await send(env, w.tok("usr"), "POST", _list_url(t), {"body": "x"})
    assert ok.status_code == 201, ok.text


@pytest.mark.parametrize("method", ["POST", "PATCH"])
async def test_d65_empty_body_is_422_missing_not_400(api_env: ApiEnv, method: str) -> None:
    env = api_env
    w = await make_api_world(env)
    t = await mk(env, w)
    c = await _comment(env, w, t, "usr")
    url = _list_url(t) if method == "POST" else _c_url(c)

    r = await send(env, w.tok("usr"), method, url, raw=b"")

    assert error(r) == (422, "validation_error")
    assert all(i["type"] == "missing" for i in r.json()["detail"])
    assert (await _db(env, c)).body == "Комментарий"
