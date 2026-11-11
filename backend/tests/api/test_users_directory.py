"""T35: ``GET /api/v1/users`` — справочник пользователей (plan §10.3, §10.4, D-24).

AC-21 (только своё пространство), AC-75 (без роли — 403, обход маршрутов), FR-13, FR-70,
FR-45a (ТА — 403: ``require_capability(BUSINESS_ACCESS)``).

Контракт: ``?q&page&page_size`` -> ``Page[DirectoryUser {id, login, role}]``;
незаблокированные с ролью БА/П, ``ORDER BY login, id``; 422 на невалидные page/page_size.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
import pytest

from tests.admin_support import PW, new_workspace, seed
from tests.api.test_route_guards import _api_operations
from tests.conftest import ApiEnv
from tests.db_support import BACKEND_DIR
from tests.factories import make_project, make_project_member

URL = "/api/v1/users"
ITEM_FIELDS = {"id", "login", "role"}
PAGE_FIELDS = {"items", "page", "page_size", "has_next"}


async def _token(env: ApiEnv, role: str | None, **kw: Any) -> str:
    user = await env.new_user(role=role, password=PW, **kw)
    return await env.login_ok(user)


async def _get(env: ApiEnv, token: str | None, **params: Any) -> httpx.Response:
    headers = env.auth(token) if token else {}
    return await env.client.get(URL, params=params, headers=headers)


async def _share_project(
    env: ApiEnv, ws: Any, owner: Any, *members: Any, deleted: bool = False
) -> None:
    """Проект ``owner`` с участниками ``members`` (spec 027: «Пользователь» видит общие проекты)."""
    async with env.sessionmaker() as session:
        project = await make_project(session, workspace_id=ws.id, owner_id=owner.id, name="Общий")
        for member in members:
            await make_project_member(
                session, project_id=project.id, user_id=member.id, workspace_id=ws.id
            )
        await session.commit()
    if deleted:
        from sqlalchemy import text

        await env.execute(
            text("UPDATE project SET deleted_at = now() WHERE id = :p").bindparams(p=project.id)
        )


def _code(r: httpx.Response) -> str:
    return str(r.json()["code"])


@pytest.mark.parametrize("role", ["business_admin", "user"])
async def test_fr13_business_roles_get_directory_page(api_env: ApiEnv, role: str) -> None:
    env = api_env
    ws = await new_workspace(env)
    me, (token,) = await seed(env, ws, role, login="dir.me")
    other, _ = await seed(env, ws, "user", login="dir.other")
    await _share_project(env, ws, me, other)  # «Пользователь» видит только общие проекты (027)

    r = await _get(env, token)

    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == PAGE_FIELDS
    assert body["page"] == 1
    assert body["has_next"] is False
    assert [i["login"] for i in body["items"]] == ["dir.me", "dir.other"]
    assert [i["id"] for i in body["items"]] == [str(me.id), str(other.id)]
    for item in body["items"]:
        assert set(item) == ITEM_FIELDS
    assert body["items"][0]["role"] == role


async def test_fr70_directory_excludes_ta_norole_and_blocked(api_env: ApiEnv) -> None:
    env = api_env
    ws = await new_workspace(env)
    _, (token,) = await seed(env, ws, "business_admin", login="d.ba")
    await seed(env, ws, "tech_admin", login="d.ta")
    await seed(env, ws, None, login="d.none")
    await seed(env, ws, "user", login="d.blocked", blocked=True)
    await seed(env, ws, "user", login="d.user")

    r = await _get(env, token)

    assert r.status_code == 200, r.text
    assert [i["login"] for i in r.json()["items"]] == ["d.ba", "d.user"]


async def test_fr45a_tech_admin_gets_403(api_env: ApiEnv) -> None:
    env = api_env
    ws = await new_workspace(env)
    _, (token,) = await seed(env, ws, "tech_admin")
    r = await _get(env, token)
    assert r.status_code == 403, r.text
    assert _code(r) == "forbidden"


async def test_ac4_no_session_is_401(api_env: ApiEnv) -> None:
    r = await _get(api_env, None)
    assert (r.status_code, _code(r)) == (401, "not_authenticated")


async def test_ac75_user_without_role_is_403_no_role(api_env: ApiEnv) -> None:
    token = await _token(api_env, None)
    r = await _get(api_env, token)
    assert (r.status_code, _code(r)) == (403, "no_role")


async def test_fr65_one_time_password_is_403_password_change_required(api_env: ApiEnv) -> None:
    token = await _token(api_env, "user", must_change_password=True)
    r = await _get(api_env, token)
    assert (r.status_code, _code(r)) == (403, "password_change_required")


async def test_ac21_other_workspace_users_are_invisible(api_env: ApiEnv) -> None:
    env = api_env
    ws1 = await new_workspace(env)
    ws2 = await new_workspace(env)
    _, (token,) = await seed(env, ws1, "user", login="ws1.me")
    await seed(env, ws2, "user", login="ws2.stranger")

    r = await _get(env, token)
    assert [i["login"] for i in r.json()["items"]] == ["ws1.me"]
    r = await _get(env, token, q="stranger")
    assert r.status_code == 200
    assert r.json()["items"] == []


async def test_t35_q_filters_by_substring_case_insensitive(api_env: ApiEnv) -> None:
    env = api_env
    ws = await new_workspace(env)
    _, (token,) = await seed(env, ws, "business_admin", login="me.self")
    await seed(env, ws, "user", login="ivan.petrov")
    await seed(env, ws, "user", login="olga")
    r = await _get(env, token, q="IVAN")
    assert [i["login"] for i in r.json()["items"]] == ["ivan.petrov"]


@pytest.mark.parametrize("q", ["%", "_", "\\", "a_b", "a%b", "\\%", "%_\\"])
async def test_d24_special_chars_in_q_are_safe_and_literal(api_env: ApiEnv, q: str) -> None:
    env = api_env
    ws = await new_workspace(env)
    _, (token,) = await seed(env, ws, "business_admin", login="me.self")
    await seed(env, ws, "user", login="axb")
    await seed(env, ws, "user", login="a_b")

    r = await _get(env, token, q=q)

    assert r.status_code == 200, r.text
    logins = [i["login"] for i in r.json()["items"]]
    if q == "a_b":
        assert logins == ["a_b"]
    elif q == "_":
        # «_» литерален (не wildcard): только логины с символом «_»
        assert logins == ["a_b"]
    else:
        assert logins == []  # ни маска «%», ни «_» не совпадают как шаблон


async def test_t35_pagination_has_next_and_page_echo(api_env: ApiEnv) -> None:
    env = api_env
    ws = await new_workspace(env)
    _, (token,) = await seed(env, ws, "business_admin", login="p.0")
    for i in range(1, 5):
        await seed(env, ws, "user", login=f"p.{i}", sessions=0)

    r1 = (await _get(env, token, page=1, page_size=2)).json()
    r3 = (await _get(env, token, page=3, page_size=2)).json()

    assert (r1["page"], r1["page_size"], r1["has_next"]) == (1, 2, True)
    assert [i["login"] for i in r1["items"]] == ["p.0", "p.1"]
    assert (r3["page"], r3["has_next"]) == (3, False)
    assert [i["login"] for i in r3["items"]] == ["p.4"]


@pytest.mark.parametrize(
    "params",
    [
        {"page": 0},
        {"page": -1},
        {"page": "x"},
        {"page_size": 0},
        {"page_size": 101},
        {"page_size": "x"},
    ],
)
async def test_t35_invalid_pagination_is_422(api_env: ApiEnv, params: dict[str, Any]) -> None:
    token = await _token(api_env, "user")
    r = await _get(api_env, token, **params)
    assert (r.status_code, _code(r)) == (422, "validation_error")


@pytest.mark.parametrize(
    "q",
    [
        pytest.param("a\x00", id="nul-suffix"),
        pytest.param("\x00", id="nul-only"),
        pytest.param("x" * 65, id="len-65"),
        pytest.param("x" * 10_000, id="len-10000"),
    ],
)
async def test_t35_invalid_q_is_422(api_env: ApiEnv, q: str) -> None:
    """Fail Fast: q длиннее 64 или с NUL -> 422 validation_error (не 500)."""
    token = await _token(api_env, "user")
    r = await _get(api_env, token, q=q)
    assert (r.status_code, _code(r)) == (422, "validation_error"), r.text


async def test_t35_q_of_64_chars_is_accepted(api_env: ApiEnv) -> None:
    env = api_env
    ws = await new_workspace(env)
    _, (token,) = await seed(env, ws, "user", login="me.self")
    r = await _get(env, token, q="x" * 64)
    assert r.status_code == 200, r.text
    assert r.json()["items"] == []


async def test_t35_response_has_no_secrets_or_extra_fields(api_env: ApiEnv) -> None:
    env = api_env
    ws = await new_workspace(env)
    other, _ = await seed(env, ws, "user", login="sec.other", password=PW)
    _, (token,) = await seed(env, ws, "business_admin", login="sec.me")

    r = await _get(env, token)

    assert r.status_code == 200, r.text
    assert [i["login"] for i in r.json()["items"]] == ["sec.me", "sec.other"]
    text = r.text
    for forbidden in ("password", "hash", "argon2", "email", "is_blocked", "must_change"):
        assert forbidden not in text.lower(), forbidden
    assert other.password_hash not in text


async def test_ac75_route_is_registered_and_walks_guards(api_env: ApiEnv) -> None:
    assert ("GET", URL) in _api_operations(api_env)


def test_t35_route_in_committed_openapi_contract() -> None:
    """Контракт: docs/api/openapi.json и schema.d.ts описывают GET /api/v1/users."""
    root = BACKEND_DIR.parent
    spec = json.loads((root / "docs/api/openapi.json").read_text(encoding="utf-8"))
    path = spec["paths"].get("/api/v1/users")
    assert path is not None and "get" in path, "GET /api/v1/users нет в docs/api/openapi.json"
    params = {p["name"] for p in path["get"].get("parameters", [])}
    assert {"q", "page", "page_size"} <= params
    dts = (root / "frontend/src/shared/api/schema.d.ts").read_text(encoding="utf-8")
    assert re.search(r'"/api/v1/users"\s*:', dts), "нет /api/v1/users в schema.d.ts"


def test_t35_q_param_has_max_length_64_in_openapi() -> None:
    spec = json.loads((BACKEND_DIR.parent / "docs/api/openapi.json").read_text(encoding="utf-8"))
    params = spec["paths"]["/api/v1/users"]["get"]["parameters"]
    q = next(p for p in params if p["name"] == "q")
    schema = q["schema"]
    variants = schema.get("anyOf", [schema])
    assert any(v.get("maxLength") == 64 for v in variants), schema


# --- AC-130, OI-129 (FR-73a, D-66): отображаемый логин в справочнике ---------------------------


@pytest.mark.parametrize("role", ["business_admin", "user"])
@pytest.mark.parametrize(
    ("q", "expected"),
    [
        ("petr", "Ivanov.Petr"),
        ("PETR", "Ivanov.Petr"),
        ("Ivanov.P", "Ivanov.Petr"),
        ("ivanov.p", "Ivanov.Petr"),
        ("ANNA", "Sidorova.Anna"),
        ("sidorova", "Sidorova.Anna"),
    ],
)
async def test_ac130_search_ignores_case_and_returns_login_as_created(
    api_env: ApiEnv, role: str, q: str, expected: str
) -> None:
    env = api_env
    ws = await new_workspace(env)
    me, (token,) = await seed(env, ws, role, login="Searcher.One")
    petr, _ = await seed(env, ws, "business_admin", login="Ivanov.Petr")
    anna, _ = await seed(env, ws, "user", login="Sidorova.Anna")
    await _share_project(env, ws, me, petr, anna)

    r = await _get(env, token, q=q)

    assert r.status_code == 200, r.text
    logins = [i["login"] for i in r.json()["items"]]
    assert expected in logins
    assert [x for x in logins if x.lower() == expected.lower()] == [expected]


async def test_ac130_directory_without_q_shows_mixed_case_logins(api_env: ApiEnv) -> None:
    env = api_env
    ws = await new_workspace(env)
    _, (token,) = await seed(env, ws, "business_admin", login="Ivanov.Petr")
    me, _ = await seed(env, ws, "user", login="Sidorova.Anna")

    r = await _get(env, token)

    assert r.status_code == 200, r.text
    by_id = {i["id"]: i["login"] for i in r.json()["items"]}
    assert by_id[str(me.id)] == "Sidorova.Anna"
    assert "Ivanov.Petr" in by_id.values()


async def test_oi129_directory_is_ordered_by_normalized_login_ignoring_case(
    api_env: ApiEnv,
) -> None:
    """OI-129 а): ``anna, Boris, ivan, Kirill`` (без пунктуации: порядок не зависит от БД)."""
    env = api_env
    ws = await new_workspace(env)
    _, (token,) = await seed(env, ws, "business_admin", login="zed")
    for login in ("Kirill", "ivan", "Boris", "anna"):
        await seed(env, ws, "user", login=login, sessions=0)

    r = await _get(env, token)

    assert [i["login"] for i in r.json()["items"]] == ["anna", "Boris", "ivan", "Kirill", "zed"]


# --- 027 FR-5: «Пользователь» видит только людей из общих проектов ----------------------------


async def test_027_user_sees_only_people_from_shared_projects_and_self(api_env: ApiEnv) -> None:
    env = api_env
    ws = await new_workspace(env)
    me, (token,) = await seed(env, ws, "user", login="u.me")
    mate, _ = await seed(env, ws, "user", login="u.mate")  # участник общего проекта
    boss, _ = await seed(env, ws, "business_admin", login="u.boss")  # владелец общего проекта
    await seed(env, ws, "user", login="u.stranger")  # общего проекта нет
    await seed(env, ws, "business_admin", login="u.other.ba")
    await _share_project(env, ws, boss, me, mate)

    r = await _get(env, token)

    assert r.status_code == 200, r.text
    assert [i["login"] for i in r.json()["items"]] == ["u.boss", "u.mate", "u.me"]


async def test_027_owner_counts_as_member_of_own_project(api_env: ApiEnv) -> None:
    env = api_env
    ws = await new_workspace(env)
    me, (token,) = await seed(env, ws, "user", login="o.me")
    mate, _ = await seed(env, ws, "user", login="o.mate")
    await _share_project(env, ws, me, mate)  # я владелец, mate — участник

    logins = [i["login"] for i in (await _get(env, token)).json()["items"]]
    assert logins == ["o.mate", "o.me"]


async def test_027_no_shared_project_means_only_self_and_blocked_stay_hidden(
    api_env: ApiEnv,
) -> None:
    env = api_env
    ws = await new_workspace(env)
    me, (token,) = await seed(env, ws, "user", login="n.me")
    blocked, _ = await seed(env, ws, "user", login="n.blocked", blocked=True)
    await _share_project(env, ws, me, blocked)
    assert [i["login"] for i in (await _get(env, token)).json()["items"]] == ["n.me"]
    # без общих проектов — только он сам
    alone, (token2,) = await seed(env, ws, "user", login="n.alone")
    assert [i["login"] for i in (await _get(env, token2)).json()["items"]] == ["n.alone"]


async def test_027_deleted_project_does_not_make_people_visible(api_env: ApiEnv) -> None:
    env = api_env
    ws = await new_workspace(env)
    me, (token,) = await seed(env, ws, "user", login="d.me")
    mate, _ = await seed(env, ws, "user", login="d.mate")
    await _share_project(env, ws, me, mate, deleted=True)
    assert [i["login"] for i in (await _get(env, token)).json()["items"]] == ["d.me"]


async def test_027_other_workspace_projects_do_not_leak(api_env: ApiEnv) -> None:
    env = api_env
    ws = await new_workspace(env)
    other_ws = await new_workspace(env)
    me, (token,) = await seed(env, ws, "user", login="w.me")
    foreign, _ = await seed(env, other_ws, "user", login="w.foreign")
    await _share_project(env, other_ws, foreign)
    assert [i["login"] for i in (await _get(env, token)).json()["items"]] == ["w.me"]
    assert me.id


async def test_027_search_and_paging_apply_inside_the_shared_set(api_env: ApiEnv) -> None:
    env = api_env
    ws = await new_workspace(env)
    me, (token,) = await seed(env, ws, "user", login="s.me")
    a, _ = await seed(env, ws, "user", login="s.anna")
    b, _ = await seed(env, ws, "user", login="s.boris")
    await seed(env, ws, "user", login="s.anna.hidden")  # не в общем проекте
    await _share_project(env, ws, me, a, b)
    assert [i["login"] for i in (await _get(env, token, q="anna")).json()["items"]] == ["s.anna"]
    page = (await _get(env, token, page_size=2)).json()
    assert [i["login"] for i in page["items"]] == ["s.anna", "s.boris"]
    assert page["has_next"] is True


async def test_027_business_admin_directory_is_unchanged(api_env: ApiEnv) -> None:
    env = api_env
    ws = await new_workspace(env)
    _, (token,) = await seed(env, ws, "business_admin", login="b.me")
    await seed(env, ws, "user", login="b.a")
    await seed(env, ws, "user", login="b.b")
    assert [i["login"] for i in (await _get(env, token)).json()["items"]] == ["b.a", "b.b", "b.me"]
