"""T18: API журнала аудита ``/api/v1/admin/audit*`` (plan §4.4, §4.6, D-7, D-8, D-34, ADR-0006).

AC-64, AC-65 (часть), AC-66, AC-121, AC-21; FR-35/FR-38 (основа), FR-41, FR-45a, FR-57,
BR-2 (ТА видит записи без значений бизнес-сущностей). Заметки ревью T07 (restrict_violation
-> 500 без текста SQL), T15 (стабильный порядок страниц), T17 (без N+1).

Контракт (plan §4.4/§4.6, принят как есть):
- ``GET /admin/audit`` -> ``Page[AuditEntry]``, ``id DESC``, фильтры ``entity_type`` (значения
  ``EntityType``, иное -> 422) и ``actor_id`` (UUID, иное -> 422); только ``in_audit``;
- ``GET /admin/audit/{id}`` -> ``AuditEntry``; чужое/несуществующее/не аудитное ->
  404 ``not_found``;
- ``AuditEntry = {id, occurred_at, actor{kind,id,login}, action, entity_type, entity_id,
  entity_deleted, changed_fields, details}``; поля ``changes`` нет.
"""

import re
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import event, text

from tests.admin_support import (
    ADMIN_USERS,
    OTP,
    OTP_FIELD,
    PW,
    admin_in_new_workspace,
    code_of,
    seed,
)
from tests.conftest import ApiEnv
from tests.factories import make_domain_event

AUDIT = "/api/v1/admin/audit"
ENTRY_FIELDS = {
    "id",
    "occurred_at",
    "actor",
    "action",
    "entity_type",
    "entity_id",
    "entity_deleted",
    "changed_fields",
    "details",
}
SECRET_NAME = "Секретный-проект-Альфа"
SECRET_VALUE = "ultra-secret-value-4242"
T0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)


# --- помощники -------------------------------------------------------------------------------


async def _add_events(env: ApiEnv, ws_id: uuid.UUID, specs: list[dict[str, Any]]) -> list[int]:
    """Вставляет события напрямую (в обход ``record_event``); возвращает id по порядку."""
    ids: list[int] = []
    async with env.sessionmaker() as session:
        for spec in specs:
            ids.append(await make_domain_event(session, workspace_id=ws_id, **spec))
        await session.commit()
    return ids


async def _get_list(env: ApiEnv, token: str, **params: Any) -> httpx.Response:
    return await env.client.get(AUDIT, params=params, headers=env.auth(token))


async def _all_entries(env: ApiEnv, token: str, **params: Any) -> list[dict[str, Any]]:
    r = await _get_list(env, token, page_size=100, **params)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["has_next"] is False
    return list(body["items"])


async def _event_rows(env: ApiEnv, ws_id: uuid.UUID | None = None) -> list[Any]:
    sql = (
        "SELECT id, workspace_id, occurred_at, actor_id, entity_type, entity_id, action, "
        "changed_fields, in_audit, changes, details FROM domain_event"
    )
    params: dict[str, Any] = {}
    if ws_id is not None:
        sql += " WHERE workspace_id = :w"
        params["w"] = ws_id
    rows = await env.execute(text(sql + " ORDER BY id").bindparams(**params))
    assert rows is not None
    return [tuple(r) for r in rows]


# --- AC-64 / AC-121: создание и назначение роли через админ-API -------------------------------


async def test_ac64_ac121_create_and_assign_role_give_exactly_two_entries(api_env: ApiEnv) -> None:
    env = api_env
    ws, admin, token = await admin_in_new_workspace(env)
    login = f"new.{uuid.uuid4().hex[:10]}"
    created = await env.client.post(
        ADMIN_USERS, json={"login": login, OTP_FIELD: OTP}, headers=env.auth(token)
    )
    assert created.status_code == 201, created.text
    new_id = created.json()["id"]

    # сразу после создания: ровно одна запись (AC-121: роли нет, назначение — отдельное действие)
    after_create = await _all_entries(env, token)
    assert [e["action"] for e in after_create] == ["user.created"]

    role = await env.client.put(
        f"{ADMIN_USERS}/{new_id}/role", json={"role": "user"}, headers=env.auth(token)
    )
    assert role.status_code in (200, 204), role.text

    entries = await _all_entries(env, token)
    assert [e["action"] for e in entries] == ["user.role_assigned", "user.created"]  # id DESC
    assigned, create = entries
    for entry in entries:
        assert set(entry) == ENTRY_FIELDS
        assert entry["entity_type"] == "user"
        assert entry["entity_id"] == new_id
        assert entry["entity_deleted"] is False
        assert entry["actor"] == {"kind": "user", "id": str(admin.id), "login": admin.login}
        occurred = datetime.fromisoformat(entry["occurred_at"].replace("Z", "+00:00"))
        assert occurred.utcoffset() == timedelta(0)  # UTC
    assert assigned["id"] > create["id"]
    assert assigned["details"]["role_to"] == "user"
    assert assigned["details"].get("role_from") is None
    assert create["details"] in (None, {})
    # AC-64: ни пароля, ни хеша, ни логина создаваемого в теле записи
    dump = str(entries)
    assert OTP not in dump
    assert "$argon2" not in dump


async def test_ac64_by_id_returns_same_entry_as_in_list(api_env: ApiEnv) -> None:
    env = api_env
    ws, admin, token = await admin_in_new_workspace(env)
    target, _ = await seed(env, ws, "user", sessions=0)
    (eid,) = await _add_events(
        env,
        ws.id,
        [
            {
                "actor_id": admin.id,
                "entity_id": target.id,
                "action": "user.role_changed",
                "details": {"role_from": "user", "role_to": "business_admin"},
                "changed_fields": ["role"],
                "occurred_at": T0,
            }
        ],
    )
    (listed,) = await _all_entries(env, token)
    r = await env.client.get(f"{AUDIT}/{eid}", headers=env.auth(token))

    assert r.status_code == 200, r.text
    assert r.json() == listed
    assert listed["id"] == eid
    assert listed["changed_fields"] == ["role"]
    assert listed["details"] == {"role_from": "user", "role_to": "business_admin"}
    assert listed["entity_deleted"] is False  # пользователь существует
    assert datetime.fromisoformat(listed["occurred_at"].replace("Z", "+00:00")) == T0


async def test_t18_entity_deleted_true_when_user_object_does_not_exist(api_env: ApiEnv) -> None:
    env = api_env
    ws, admin, token = await admin_in_new_workspace(env)
    existing, _ = await seed(env, ws, "user", sessions=0)
    gone = uuid.uuid4()
    ids = await _add_events(
        env,
        ws.id,
        [
            {"actor_id": admin.id, "entity_id": existing.id},
            {"actor_id": admin.id, "entity_id": gone},
        ],
    )
    by_id = {e["id"]: e for e in await _all_entries(env, token)}
    assert by_id[ids[0]]["entity_deleted"] is False
    assert by_id[ids[1]]["entity_deleted"] is True


async def test_t18_actor_kind_system_when_actor_id_is_null(api_env: ApiEnv) -> None:
    env = api_env
    ws, admin, token = await admin_in_new_workspace(env)
    sys_id, usr_id = await _add_events(
        env,
        ws.id,
        [
            {"actor_id": None, "action": "user.created"},
            {"actor_id": admin.id, "action": "user.blocked"},
        ],
    )
    by_id = {e["id"]: e for e in await _all_entries(env, token)}
    system = by_id[sys_id]["actor"]
    assert system["kind"] == "system"
    assert system.get("id") is None
    assert system.get("login") is None
    assert by_id[usr_id]["actor"] == {"kind": "user", "id": str(admin.id), "login": admin.login}


# --- список: пагинация, порядок, фильтры ------------------------------------------------------


async def test_t18_list_empty_workspace_shape(api_env: ApiEnv) -> None:
    env = api_env
    _, _, token = await admin_in_new_workspace(env)
    r = await _get_list(env, token)
    assert r.status_code == 200, r.text
    assert r.json() == {"items": [], "page": 1, "page_size": 50, "has_next": False}


async def test_t18_order_id_desc_stable_with_equal_occurred_at_and_pages_disjoint(
    api_env: ApiEnv,
) -> None:
    env = api_env
    ws, admin, token = await admin_in_new_workspace(env)
    ids = await _add_events(
        env, ws.id, [{"actor_id": admin.id, "occurred_at": T0} for _ in range(7)]
    )
    expected = sorted(ids, reverse=True)

    seen: list[int] = []
    flags: list[bool] = []
    for page in (1, 2, 3):
        r = await _get_list(env, token, page=page, page_size=3)
        assert r.status_code == 200, r.text
        body = r.json()
        assert (body["page"], body["page_size"]) == (page, 3)
        seen += [e["id"] for e in body["items"]]
        flags.append(body["has_next"])
    assert seen == expected  # без пропусков и повторов, строго id DESC
    assert flags == [True, True, False]
    # повторный запрос — тот же порядок
    again = [e["id"] for e in await _all_entries(env, token)]
    assert again == expected


async def test_t18_has_next_on_exact_page_size_boundary(api_env: ApiEnv) -> None:
    env = api_env
    ws, admin, token = await admin_in_new_workspace(env)
    await _add_events(env, ws.id, [{"actor_id": admin.id} for _ in range(6)])

    exact = (await _get_list(env, token, page_size=6)).json()
    one_less = (await _get_list(env, token, page_size=5)).json()
    rest = (await _get_list(env, token, page_size=5, page=2)).json()

    assert (len(exact["items"]), exact["has_next"]) == (6, False)
    assert (len(one_less["items"]), one_less["has_next"]) == (5, True)
    assert (len(rest["items"]), rest["has_next"]) == (1, False)


async def test_t18_default_page_size_50_with_51_entries(api_env: ApiEnv) -> None:
    env = api_env
    ws, admin, token = await admin_in_new_workspace(env)
    await _add_events(env, ws.id, [{"actor_id": admin.id} for _ in range(51)])
    first = (await _get_list(env, token)).json()
    second = (await _get_list(env, token, page=2)).json()
    assert (len(first["items"]), first["has_next"]) == (50, True)
    assert (len(second["items"]), second["has_next"]) == (1, False)


async def test_t18_huge_page_is_fast_empty_page(api_env: ApiEnv) -> None:
    from app.core.pagination import MAX_PAGE

    env = api_env
    ws, admin, token = await admin_in_new_workspace(env)
    await _add_events(env, ws.id, [{"actor_id": admin.id}])
    started = time.monotonic()
    r = await _get_list(env, token, page=MAX_PAGE, page_size=100)
    elapsed = time.monotonic() - started

    assert r.status_code == 200, r.text
    assert r.json()["items"] == []
    assert r.json()["has_next"] is False
    assert elapsed < 2.0
    over = await _get_list(env, token, page=MAX_PAGE + 1)
    assert (over.status_code, code_of(over)) == (422, "validation_error")


@pytest.mark.parametrize(
    "params",
    [{"page": 0}, {"page_size": 0}, {"page_size": 101}, {"page": "x"}],
)
async def test_t18_invalid_page_params_are_422(api_env: ApiEnv, params: dict[str, Any]) -> None:
    env = api_env
    _, _, token = await admin_in_new_workspace(env)
    r = await _get_list(env, token, **params)
    assert (r.status_code, code_of(r)) == (422, "validation_error")


async def test_t18_filter_entity_type_and_actor_id(api_env: ApiEnv) -> None:
    env = api_env
    ws, admin, token = await admin_in_new_workspace(env)
    other, _ = await seed(env, ws, "mixed", sessions=0)
    u_admin, u_other, p_admin = await _add_events(
        env,
        ws.id,
        [
            {"actor_id": admin.id, "entity_type": "user", "action": "user.blocked"},
            {"actor_id": other.id, "entity_type": "user", "action": "user.unblocked"},
            {
                "actor_id": admin.id,
                "entity_type": "project",
                "action": "project.archived",
                "project_id": uuid.uuid4(),
            },
        ],
    )

    by_user = [e["id"] for e in await _all_entries(env, token, entity_type="user")]
    by_project = [e["id"] for e in await _all_entries(env, token, entity_type="project")]
    by_actor = [e["id"] for e in await _all_entries(env, token, actor_id=str(admin.id))]
    both = [
        e["id"]
        for e in await _all_entries(env, token, actor_id=str(admin.id), entity_type="project")
    ]
    nobody = await _all_entries(env, token, actor_id=str(uuid.uuid4()))
    everything = [e["id"] for e in await _all_entries(env, token)]

    assert by_user == [u_other, u_admin]
    assert by_project == [p_admin]
    assert by_actor == [p_admin, u_admin]
    assert both == [p_admin]
    assert nobody == []
    assert everything == [p_admin, u_other, u_admin]


async def test_t18_filter_validation_errors_are_422(api_env: ApiEnv) -> None:
    env = api_env
    _, _, token = await admin_in_new_workspace(env)
    for params in (
        {"entity_type": "no_such_entity"},
        {"entity_type": "USER"},
        {"actor_id": "not-a-uuid"},
        {"actor_id": "1"},
    ):
        r = await _get_list(env, token, **params)
        assert (r.status_code, code_of(r)) == (422, "validation_error"), params
        assert "not-a-uuid" not in r.text


async def test_t18_filter_values_do_not_reach_sql_as_text(api_env: ApiEnv) -> None:
    """Инъекция в ``entity_type`` отвергается валидацией, журнал цел."""
    env = api_env
    ws, admin, token = await admin_in_new_workspace(env)
    await _add_events(env, ws.id, [{"actor_id": admin.id}])
    r = await _get_list(env, token, entity_type="user' OR '1'='1")
    assert r.status_code == 422
    assert len(await _all_entries(env, token)) == 1


async def test_t18_only_audit_events_are_listed_and_by_id_404_for_non_audit(
    api_env: ApiEnv,
) -> None:
    env = api_env
    ws, admin, token = await admin_in_new_workspace(env)
    shown, hidden = await _add_events(
        env,
        ws.id,
        [
            {"actor_id": admin.id, "in_audit": True},
            {
                "actor_id": admin.id,
                "in_audit": False,
                "entity_type": "task",
                "action": "task.created",
                "project_id": uuid.uuid4(),
            },
        ],
    )
    assert [e["id"] for e in await _all_entries(env, token)] == [shown]
    r = await env.client.get(f"{AUDIT}/{hidden}", headers=env.auth(token))
    assert (r.status_code, code_of(r)) == (404, "not_found")


async def test_t18_by_id_errors(api_env: ApiEnv) -> None:
    env = api_env
    _, _, token = await admin_in_new_workspace(env)
    missing = await env.client.get(f"{AUDIT}/999999999", headers=env.auth(token))
    bad = await env.client.get(f"{AUDIT}/not-a-number", headers=env.auth(token))
    assert (missing.status_code, code_of(missing)) == (404, "not_found")
    assert (bad.status_code, code_of(bad)) == (422, "validation_error")


async def test_t18_roles_tech_admin_and_mixed_can_view(api_env: ApiEnv) -> None:
    env = api_env
    ws, admin, ta_token = await admin_in_new_workspace(env)
    _, (mixed_token,) = await seed(env, ws, "mixed")
    await _add_events(env, ws.id, [{"actor_id": admin.id}])
    for token in (ta_token, mixed_token):
        r = await _get_list(env, token)
        assert r.status_code == 200, r.text
        assert len(r.json()["items"]) == 1


# --- AC-65: доступ -----------------------------------------------------------------------------


async def test_ac65_business_admin_and_user_get_403_on_list_and_by_id(api_env: ApiEnv) -> None:
    env = api_env
    ws, admin, _ = await admin_in_new_workspace(env)
    (eid,) = await _add_events(env, ws.id, [{"actor_id": admin.id}])
    for role in ("business_admin", "user"):
        _, (token,) = await seed(env, ws, role)
        for url in (AUDIT, f"{AUDIT}/{eid}", f"{AUDIT}/{uuid.uuid4()}", f"{AUDIT}/not-a-uuid"):
            r = await env.client.get(url, headers=env.auth(token))
            assert (r.status_code, code_of(r)) == (403, "forbidden"), (role, url, r.text)
        # гейт раньше валидации запроса
        r = await env.client.get(
            AUDIT, params={"entity_type": "zzz", "page": 0}, headers=env.auth(token)
        )
        assert r.status_code == 403, (role, r.text)


async def test_ac65_no_role_one_time_password_and_anonymous(api_env: ApiEnv) -> None:
    env = api_env
    ws, admin, _ = await admin_in_new_workspace(env)
    (eid,) = await _add_events(env, ws.id, [{"actor_id": admin.id}])
    _, (norole,) = await seed(env, ws, None)
    _, (otp_admin,) = await seed(env, ws, "tech_admin", must_change_password=True)

    for url in (AUDIT, f"{AUDIT}/{eid}"):
        r = await env.client.get(url, headers=env.auth(norole))
        assert (r.status_code, code_of(r)) == (403, "no_role"), url
        r = await env.client.get(url, headers=env.auth(otp_admin))
        assert (r.status_code, code_of(r)) == (403, "password_change_required"), url
        r = await env.client.get(url)
        assert r.status_code == 401, url


async def test_ac65_login_success_failure_and_password_change_create_no_entries(
    api_env: ApiEnv,
) -> None:
    """FR-41, ADR-0006: вход (успешный и нет) и смена своего пароля в журнал не попадают."""
    env = api_env
    ws, _, ta_token = await admin_in_new_workspace(env)
    user, _ = await seed(env, ws, "user", password=PW, sessions=0)

    bad = await env.login(user.login, PW + "-wrong")
    assert bad.status_code == 401
    ok = await env.login(user.login, PW)
    assert ok.status_code == 200, ok.text
    token = env.token_from(ok)
    assert token
    changed = await env.client.post(
        "/api/v1/auth/password",
        json={"current_password": PW, "new_password": "Brand-new-Pa55phrase-abc-9"},
        headers=env.auth(token),
    )
    assert changed.status_code in (200, 204), changed.text

    assert await _all_entries(env, ta_token) == []
    assert await _event_rows(env, ws.id) == []


# --- AC-66: журнал только читается ---------------------------------------------------------------


async def test_ac66_write_methods_are_405_and_log_is_unchanged(api_env: ApiEnv) -> None:
    env = api_env
    ws, admin, token = await admin_in_new_workspace(env)
    (eid,) = await _add_events(env, ws.id, [{"actor_id": admin.id, "details": {"role_to": "user"}}])
    before = await _event_rows(env)

    for method in ("PUT", "PATCH", "DELETE", "POST"):
        for url in (AUDIT, f"{AUDIT}/{eid}"):
            r = await env.client.request(method, url, json={"action": "x"}, headers=env.auth(token))
            assert (r.status_code, code_of(r)) == (405, "method_not_allowed"), (method, url)

    assert await _event_rows(env) == before


# --- AC-21: изоляция пространств -----------------------------------------------------------------


async def test_ac21_foreign_workspace_audit_is_invisible(api_env: ApiEnv) -> None:
    env = api_env
    ws_a, admin_a, token_a = await admin_in_new_workspace(env)
    ws_b, admin_b, token_b = await admin_in_new_workspace(env)
    (a_id,) = await _add_events(env, ws_a.id, [{"actor_id": admin_a.id}])
    (b_id,) = await _add_events(env, ws_b.id, [{"actor_id": admin_b.id}])

    assert [e["id"] for e in await _all_entries(env, token_a)] == [a_id]
    assert [e["id"] for e in await _all_entries(env, token_b)] == [b_id]
    # фильтр по автору из другого пространства ничего не раскрывает
    assert await _all_entries(env, token_a, actor_id=str(admin_b.id)) == []

    foreign = await env.client.get(f"{AUDIT}/{b_id}", headers=env.auth(token_a))
    missing = await env.client.get(f"{AUDIT}/{b_id + 10**6}", headers=env.auth(token_a))
    assert (foreign.status_code, code_of(foreign)) == (404, "not_found")
    assert foreign.status_code == missing.status_code
    assert foreign.json() == missing.json()  # неотличимо от несуществующего


async def test_ac21_actor_from_foreign_workspace_login_not_leaked(api_env: ApiEnv) -> None:
    """Автор записи всегда из того же пространства; чужой логин в ответ не попадает."""
    env = api_env
    ws_a, admin_a, token_a = await admin_in_new_workspace(env)
    ws_b, admin_b, _ = await admin_in_new_workspace(env)
    await _add_events(env, ws_a.id, [{"actor_id": admin_a.id}])
    await _add_events(env, ws_b.id, [{"actor_id": admin_b.id}])
    r = await _get_list(env, token_a)
    assert admin_b.login not in r.text
    assert str(admin_b.id) not in r.text


# --- BR-2: бизнес-сущности без значений -----------------------------------------------------------


async def test_br2_business_entity_entries_have_no_values_names_or_details(
    api_env: ApiEnv,
) -> None:
    env = api_env
    ws, admin, token = await admin_in_new_workspace(env)
    changes = [{"field": "name", "old": SECRET_NAME, "new": SECRET_VALUE}]
    specs: list[dict[str, Any]] = [
        {
            "actor_id": admin.id,
            "entity_type": et,
            "action": action,
            "changed_fields": ["name"],
            "changes": changes,
            # даже если в строку попало details — для не-user наружу оно не выходит
            "details": {"role_from": SECRET_NAME, "role_to": SECRET_VALUE},
            "project_id": uuid.uuid4() if et != "deal" else None,
            "deal_id": uuid.uuid4() if et == "deal" else None,
        }
        for et, action in (
            ("project", "project.archived"),
            ("task", "task.updated"),
            ("deal", "deal.updated"),
            ("stage", "stage.updated"),
        )
    ]
    ids = await _add_events(env, ws.id, specs)

    r = await _get_list(env, token)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert {e["id"] for e in items} == set(ids)
    for entry in items:
        assert set(entry) == ENTRY_FIELDS
        assert "changes" not in entry
        assert entry.get("details") is None
        assert entry["changed_fields"] == ["name"]  # имена полей допустимы, значения — нет
        assert isinstance(entry["entity_deleted"], bool)
    for needle in (SECRET_NAME, SECRET_VALUE):
        assert needle not in r.text
        one = await env.client.get(f"{AUDIT}/{ids[0]}", headers=env.auth(token))
        assert needle not in one.text
        assert "changes" not in one.json()


async def test_br2_response_has_no_secrets_fields(api_env: ApiEnv) -> None:
    env = api_env
    ws, admin, token = await admin_in_new_workspace(env)
    created = await env.client.post(
        ADMIN_USERS, json={"login": "audit.target", OTP_FIELD: OTP}, headers=env.auth(token)
    )
    assert created.status_code == 201
    await env.client.post(
        f"{ADMIN_USERS}/{created.json()['id']}/reset-password",
        json={OTP_FIELD: OTP + "-2"},
        headers=env.auth(token),
    )
    r = await _get_list(env, token)
    assert [e["action"] for e in r.json()["items"]] == ["user.password_reset", "user.created"]
    lowered = r.text.lower()
    for needle in (OTP, OTP + "-2", "$argon2", "password_hash", "token", "secret"):
        assert needle.lower() not in lowered, needle


# --- N+1 ------------------------------------------------------------------------------------------


async def _select_count(env: ApiEnv, token: str, **params: Any) -> int:
    conn = env.sessionmaker.kw["bind"].sync_connection
    seen: list[str] = []

    def on_execute(c: Any, cursor: Any, statement: str, *a: Any) -> None:
        seen.append(statement)

    event.listen(conn, "before_cursor_execute", on_execute)
    try:
        r = await _get_list(env, token, **params)
    finally:
        event.remove(conn, "before_cursor_execute", on_execute)
    assert r.status_code == 200, r.text
    return len(seen)


async def test_t18_query_count_per_page_is_constant(api_env: ApiEnv) -> None:
    """actor.login и entity_deleted загружаются батчем: число SQL не растёт с числом строк."""
    env = api_env
    ws, admin, token = await admin_in_new_workspace(env)
    actors = [admin] + [(await seed(env, ws, "user", sessions=0))[0] for _ in range(4)]
    targets = [(await seed(env, ws, "user", sessions=0))[0] for _ in range(4)]

    def spec(i: int) -> dict[str, Any]:
        return {
            "actor_id": actors[i % len(actors)].id,
            "entity_id": targets[i % len(targets)].id if i % 3 else uuid.uuid4(),
        }

    await _add_events(env, ws.id, [spec(i) for i in range(2)])
    small = await _select_count(env, token)
    await _add_events(env, ws.id, [spec(i) for i in range(2, 30)])
    large = await _select_count(env, token)

    assert large == small, (small, large)


# --- T07: триггер журнала, restrict_violation -> 500 без текста SQL ---


@pytest.mark.parametrize("statement", ["update", "delete"])
async def test_t07_trigger_violation_inside_app_is_500_internal_error_without_sql(
    api_env: ApiEnv, statement: str
) -> None:
    """Имитация ошибки кода: UPDATE/DELETE по журналу из обработчика.

    Триггер БД даёт ``restrict_violation`` (SQLSTATE 23001, класс 23): это не ошибка клиента, а
    дефект кода -> 500 ``internal_error`` фиксированного тела, без SQL, имён триггера/таблицы.
    """
    from app.core.db import DbSession

    env = api_env
    ws, admin, token = await admin_in_new_workspace(env)
    (eid,) = await _add_events(env, ws.id, [{"actor_id": admin.id, "action": "user.created"}])
    before = await _event_rows(env)

    sql = {
        "update": "UPDATE domain_event SET action = 'user.blocked' WHERE id = :i",
        "delete": "DELETE FROM domain_event WHERE id = :i",
    }[statement]

    async def mutate(db: DbSession) -> dict[str, str]:
        await db.execute(text(sql), {"i": eid})
        return {"ok": "yes"}

    env.app.add_api_route("/_t/mutate-audit", mutate, methods=["GET"])
    transport = httpx.ASGITransport(app=env.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url=env.base_url) as client:
        r = await client.get("/_t/mutate-audit", headers=env.auth(token))

    assert r.status_code == 500, r.text
    assert r.json() == {"detail": "Внутренняя ошибка", "code": "internal_error"}
    for needle in ("domain_event", "gt_forbid", "trigger", "UPDATE", "DELETE", "restrict", "SQL"):
        assert needle not in r.text, needle
    assert await _event_rows(env) == before


# --- OpenAPI ---


def _audit_operations(env: ApiEnv) -> dict[tuple[str, str], dict[str, Any]]:
    ops: dict[tuple[str, str], dict[str, Any]] = {}
    for path, item in env.app.openapi()["paths"].items():
        if path.startswith("/api/v1/admin/audit"):
            for method, op in item.items():
                ops[(method.upper(), path)] = op
    return ops


async def test_t18_openapi_operations_and_ids(api_env: ApiEnv) -> None:
    from tests.api.test_route_guards import _iter_routes

    ops = _audit_operations(api_env)
    normalized = {(m, re.sub(r"\{[^}]+\}", "{id}", p)) for (m, p) in ops}
    assert normalized == {("GET", "/api/v1/admin/audit"), ("GET", "/api/v1/admin/audit/{id}")}

    names: dict[tuple[str, str], str] = {}
    for route in _iter_routes(api_env.app.routes):
        if route.path.startswith("/api/v1/admin/audit"):
            for method in set(route.methods) - {"HEAD", "OPTIONS"}:
                names[(method, route.path)] = route.endpoint.__name__
    assert set(names) == set(ops)
    all_ids = [
        op["operationId"]
        for item in api_env.app.openapi()["paths"].values()
        for op in item.values()
    ]
    assert len(all_ids) == len(set(all_ids))  # без коллизий в целом приложении
    for key, op in ops.items():
        assert op["operationId"] == names[key], key


async def test_t18_openapi_audit_entry_has_no_changes_and_page_schema_is_unique(
    api_env: ApiEnv,
) -> None:
    schemas = api_env.app.openapi()["components"]["schemas"]
    assert "AuditEntry" in schemas
    props = set(schemas["AuditEntry"]["properties"])
    assert props == ENTRY_FIELDS
    assert "changes" not in props
    page_names = [n for n in schemas if n.startswith("Page_") and "AuditEntry" in n]
    assert len(page_names) == 1, page_names
    assert not any("changes" in set(s.get("properties", {})) for s in schemas.values())
    actor = schemas.get("AuditActor") or schemas.get("AuditEntryActor")
    if actor is not None:  # форма actor: kind, id, login
        assert set(actor["properties"]) == {"kind", "id", "login"}


# --- T18 ревью: индекс и перечень колонок ---


async def _capture_requests(
    env: ApiEnv, urls: list[tuple[str, dict[str, Any]]], token: str
) -> list[tuple[str, Any]]:
    conn = env.sessionmaker.kw["bind"].sync_connection
    seen: list[tuple[str, Any]] = []

    def on_execute(c: Any, cursor: Any, statement: str, parameters: Any, *a: Any) -> None:
        seen.append((statement, parameters))

    event.listen(conn, "before_cursor_execute", on_execute)
    try:
        for url, params in urls:
            r = await env.client.get(url, params=params, headers=env.auth(token))
            assert r.status_code == 200, r.text
    finally:
        event.remove(conn, "before_cursor_execute", on_execute)
    return seen


def _event_selects(seen: list[tuple[str, Any]]) -> list[tuple[str, Any]]:
    return [
        (s, p)
        for s, p in seen
        if s.lstrip().lower().startswith("select") and re.search(r"from domain_event", s, re.I)
    ]


async def test_br2_select_does_not_read_changes_or_link_columns(api_env: ApiEnv) -> None:
    """BR-2: значения не читаются из БД вовсе: в списке выбираемых колонок нет ``changes``."""
    env = api_env
    ws, admin, token = await admin_in_new_workspace(env)
    (eid,) = await _add_events(
        env,
        ws.id,
        [
            {
                "actor_id": admin.id,
                "entity_type": "project",
                "action": "project.archived",
                "project_id": uuid.uuid4(),
                "changes": [{"field": "name", "old": SECRET_NAME, "new": SECRET_VALUE}],
            }
        ],
    )
    seen = await _capture_requests(env, [(AUDIT, {}), (f"{AUDIT}/{eid}", {})], token)

    selects = _event_selects(seen)
    assert len(selects) >= 2, [s for s, _ in seen]
    for statement, _ in selects:
        select_list = re.split(r"\sFROM\s", statement, maxsplit=1, flags=re.I)[0]
        for column in ("changes", "project_id", "deal_id", "workspace_id", "in_audit"):
            assert column not in select_list, (column, select_list)
    for statement, _ in seen:
        assert SECRET_NAME not in statement


async def test_t18_in_audit_predicate_is_index_compatible(api_env: ApiEnv) -> None:
    """``in_audit IS true`` не совпадает с предикатом частичного индекса (``WHERE in_audit``)."""
    env = api_env
    ws, admin, token = await admin_in_new_workspace(env)
    (eid,) = await _add_events(env, ws.id, [{"actor_id": admin.id}])
    seen = await _capture_requests(
        env, [(AUDIT, {}), (AUDIT, {"entity_type": "user"}), (f"{AUDIT}/{eid}", {})], token
    )
    selects = _event_selects(seen)
    assert selects
    for statement, _ in selects:
        assert not re.search(r"\bIS\s+true\b", statement, re.I), statement
        assert re.search(r"in_audit", statement), statement


async def test_t18_list_plan_uses_partial_audit_index_for_small_workspace(
    api_env: ApiEnv,
) -> None:
    env = api_env
    ws, admin, token = await admin_in_new_workspace(env)
    big, big_admin, _ = await admin_in_new_workspace(env)
    await _add_events(env, ws.id, [{"actor_id": admin.id} for _ in range(3)])
    conn = env.sessionmaker.kw["bind"]
    await conn.execute(
        text(
            "INSERT INTO domain_event (workspace_id, occurred_at, actor_id, entity_type, "
            "entity_id, action, changed_fields, in_audit) "
            "SELECT :w, now(), :a, 'user', gen_random_uuid(), 'user.created', '{}', (g % 2 = 0) "
            "FROM generate_series(1, 12000) g"
        ).bindparams(w=big.id, a=big_admin.id)
    )
    await conn.execute(text("ANALYZE domain_event"))

    seen = await _capture_requests(env, [(AUDIT, {})], token)
    ((statement, params),) = _event_selects(seen)[:1]
    result = await conn.exec_driver_sql("EXPLAIN " + statement, params)
    plan = "\n".join(str(r[0]) for r in result)

    assert "ix_domain_event_workspace_id_id_audit" in plan, plan
    assert "Seq Scan on domain_event" not in plan, plan


# --- T30: устойчивое чтение журнала (plan D-41, §4.4) ---------------------------------------------

UNKNOWN_TYPE = "gizmo"


async def _drop_entity_type_check(env: ApiEnv) -> None:
    """Снимает CHECK (если T33 уже добавил) внутри транзакции теста; INSERT остаётся допустимым."""
    await env.execute(
        text("ALTER TABLE domain_event DROP CONSTRAINT IF EXISTS ck_domain_event_entity_type_valid")
    )


async def _seed_with_unknown_type(
    env: ApiEnv, ws_id: uuid.UUID, actor_id: uuid.UUID, layout: list[str]
) -> list[int]:
    """События по порядку ``layout`` (``"user"`` или неизвестный тип); id в том же порядке."""
    await _drop_entity_type_check(env)
    specs: list[dict[str, Any]] = [
        {
            "actor_id": actor_id,
            "entity_type": et,
            "action": "user.created" if et == "user" else "gizmo.created",
            "details": {"role_from": SECRET_NAME, "role_to": SECRET_VALUE},
            "changes": [{"field": "name", "old": SECRET_NAME, "new": SECRET_VALUE}],
            "occurred_at": T0 + timedelta(minutes=i),
        }
        for i, et in enumerate(layout)
    ]
    return await _add_events(env, ws_id, specs)


async def test_t30_unknown_entity_type_row_is_skipped_with_warning(
    api_env: ApiEnv, caplog: pytest.LogCaptureFixture
) -> None:
    env = api_env
    ws, admin, token = await admin_in_new_workspace(env)
    ids = await _seed_with_unknown_type(env, ws.id, admin.id, ["user", UNKNOWN_TYPE, "user"])
    bad_id = ids[1]

    with caplog.at_level("WARNING"):
        r = await _get_list(env, token, page_size=100)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [e["id"] for e in body["items"]] == [ids[2], ids[0]]
    assert body["has_next"] is False
    assert UNKNOWN_TYPE not in r.text

    warnings = [rec for rec in caplog.records if rec.levelname == "WARNING"]
    mentioning = [rec for rec in warnings if str(bad_id) in rec.getMessage()]
    assert mentioning, "нет warning с id пропущенной записи"
    assert any(UNKNOWN_TYPE in rec.getMessage() for rec in mentioning)
    for rec in caplog.records:
        rendered = rec.getMessage() + " " + str(rec.__dict__.get("args", ""))
        assert SECRET_NAME not in rendered
        assert SECRET_VALUE not in rendered
    assert SECRET_NAME not in caplog.text
    assert SECRET_VALUE not in caplog.text


async def test_t30_pagination_survives_skipped_rows(api_env: ApiEnv) -> None:
    env = api_env
    ws, admin, token = await admin_in_new_workspace(env)
    layout = ["user", "user", UNKNOWN_TYPE, "user", "user", UNKNOWN_TYPE, "user"]
    ids = await _seed_with_unknown_type(env, ws.id, admin.id, layout)
    good_desc = [i for i, et in sorted(zip(ids, layout, strict=True), reverse=True) if et == "user"]

    seen: list[int] = []
    page, last_has_next = 1, True
    while last_has_next:
        assert page <= len(layout) + 1, "has_next не становится False"
        r = await _get_list(env, token, page=page, page_size=2)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["page"] == page
        assert len(body["items"]) <= 2
        seen.extend(e["id"] for e in body["items"])
        last_has_next = body["has_next"]
        page += 1
    assert seen == good_desc  # без пропусков порядка, дублей и неизвестных типов


async def test_t30_unknown_entity_type_by_id_is_404_not_500(api_env: ApiEnv) -> None:
    env = api_env
    ws, admin, token = await admin_in_new_workspace(env)
    ids = await _seed_with_unknown_type(env, ws.id, admin.id, ["user", UNKNOWN_TYPE])
    ok = await env.client.get(f"{AUDIT}/{ids[0]}", headers=env.auth(token))
    assert ok.status_code == 200, ok.text
    r = await env.client.get(f"{AUDIT}/{ids[1]}", headers=env.auth(token))
    assert (r.status_code, code_of(r)) == (404, "not_found")


# --- T72: передача владения проектом в журнале (AC-65, FR-41, BR-2) --------------------------


async def _project_world(env: ApiEnv) -> Any:
    from tests.projects_api_support import make_api_world

    return await make_api_world(env)


async def test_t72_ac65_ownership_transfer_entry_via_audit_api(api_env: ApiEnv) -> None:
    from tests.projects_api_support import error, pj, send

    env = api_env
    w = await _project_world(env)
    moved = await send(
        env, w.tok("ba"), "PUT", f"{pj(w.project_id)}/owner", {"user_id": str(w.uid("ba2"))}
    )
    assert moved.status_code == 200, moved.text

    for reader in ("ta", "sm"):  # ТА и СМ читают журнал
        r = await _get_list(env, w.tok(reader), entity_type="project")
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert len(items) == 1, items
        entry = items[0]
        assert set(entry) == ENTRY_FIELDS
        assert "changes" not in entry
        assert entry["action"] == "project.ownership_transferred"
        assert entry["entity_type"] == "project"
        assert entry["entity_id"] == str(w.project_id)
        assert entry["entity_deleted"] is False
        assert entry["changed_fields"] == ["owner_id"]
        assert entry["actor"] == {"kind": "user", "id": str(w.uid("ba")), "login": w.login("ba")}
        occurred = datetime.fromisoformat(entry["occurred_at"].replace("Z", "+00:00"))
        assert occurred.utcoffset() == timedelta(0)  # UTC
        assert entry.get("details") is None  # ни названий, ни логинов
        # BR-2: ни названия проекта, ни логина нового владельца, ни значений полей
        assert w.project_name not in r.text
        assert w.login("ba2") not in r.text
        assert str(w.uid("ba2")) not in r.text
        by_id = await env.client.get(f"{AUDIT}/{entry['id']}", headers=env.auth(w.tok(reader)))
        assert by_id.status_code == 200
        assert by_id.json() == entry
        assert w.login("ba2") not in by_id.text
    for denied in ("ba", "usr"):
        r = await _get_list(env, w.tok(denied), entity_type="project")
        assert error(r) == (403, "forbidden")


async def test_t72_ac65_repeat_and_failed_transfers_write_nothing(api_env: ApiEnv) -> None:
    from tests.projects_api_support import pj, send

    env = api_env
    w = await _project_world(env)
    url = f"{pj(w.project_id)}/owner"

    same = await send(env, w.tok("ba"), "PUT", url, {"user_id": str(w.uid("ba"))})  # D-46
    wrong_role = await send(env, w.tok("ba"), "PUT", url, {"user_id": str(w.uid("usr"))})
    # актор ba2 (БА) заменён на usr (П): 002/AC-12, AC-16 - у БА 403 на передачу больше нет
    denied = await send(env, w.tok("usr"), "PUT", url, {"user_id": str(w.uid("ba2"))})

    assert (same.status_code, wrong_role.status_code, denied.status_code) == (200, 422, 403)
    assert await _all_entries(env, w.tok("ta"), entity_type="project") == []


async def test_t72_d55_other_project_operations_do_not_write_audit(api_env: ApiEnv) -> None:
    from tests.projects_api_support import PROJECTS, members_url, pj, send

    env = api_env
    w = await _project_world(env)
    before = await _all_entries(env, w.tok("ta"))

    created = await send(env, w.tok("ba"), "POST", PROJECTS, {"name": "Журнал-проект"})
    assert created.status_code == 201
    new_id = created.json()["id"]
    assert (
        await send(env, w.tok("ba"), "PATCH", pj(new_id), {"name": "Другое"})
    ).status_code == 200
    add = await send(env, w.tok("ba"), "POST", members_url(new_id), {"user_id": str(w.uid("usr"))})
    assert add.status_code == 204
    rem = await send(env, w.tok("ba"), "DELETE", members_url(new_id, w.uid("usr")))
    assert rem.status_code == 204
    assert (await send(env, w.tok("ba"), "DELETE", pj(new_id))).status_code == 204

    after = await _all_entries(env, w.tok("ta"))
    assert after == before
    assert await _all_entries(env, w.tok("ta"), entity_type="project") == []
