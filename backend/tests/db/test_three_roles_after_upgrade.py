"""R3-T14: поведение API после обновления 0005 -> 0006 (spec 002 AC-20, AC-22, AC-23, AC-25, AC-26).

Схема D-12: ``committed``-тест на head -> ``downgrade 0005`` -> данные предыдущей версии
(``tests/upgrade002_support``: роль ``mixed`` ставится SQL-ом, сессия S создаётся через
``SessionStore`` ДО обновления) -> ``alembic upgrade head`` -> шаги AC буквально через HTTP API.
Роли, журнал и данные в БД после миграции проверяет ``test_three_roles_upgrade.py`` (R3-T13);
здесь только поведение API. Логины синтетические: ``u002.m1`` для ``m1`` из spec.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from tests.admin_support import ADMIN_USERS, code_of
from tests.factories import DEFAULT_PASSWORD, make_domain_event
from tests.projects_api_support import PROJECTS, pj, send
from tests.tasks_api_support import TASK_REQ
from tests.upgrade002_support import (
    PREFIX,
    World,
    make_ac20_world,
    make_ac22_world,
    to_head,
)

if TYPE_CHECKING:
    import httpx

    from tests.conftest import ApiEnv

AUDIT = "/api/v1/admin/audit"
LOGIN_URL = "/api/v1/auth/login"
LOGOUT_URL = "/api/v1/auth/logout"
PASSWORD_URL = "/api/v1/auth/password"
ME = "/api/v1/me"
USERS = "/api/v1/users"
MY_TASKS = "/api/v1/me/tasks"
NEW_PASSWORD = "Brand-new-Pa55phrase-2026"
NEW_ACCOUNT_OTP = "Fresh-0ne-time-Pa55-909"


def _login_of(name: str) -> str:
    return f"{PREFIX}{name}"


async def _login(env: ApiEnv, name: str, password: str = DEFAULT_PASSWORD) -> tuple[str, Any]:
    """Вход пользователя фикстуры по HTTP; возвращает (токен, тело ответа). Ответ - 200."""
    response = await env.login(_login_of(name), password)
    assert response.status_code == 200, f"вход {name}: {response.status_code} {response.text}"
    token = env.token_from(response)
    assert token, f"вход {name} не поставил cookie"
    return token, response.json()


def _no_mixed(response: httpx.Response) -> None:
    assert "mixed" not in response.text.lower(), f"в ответе есть mixed: {response.text[:300]}"


def _probes(w: World) -> list[tuple[str, str, Any]]:
    """Запросы разных разделов API: проекты, задачи, участники, учётные записи, журнал."""
    assert w.project_p is not None and w.task_t2 is not None
    return [
        ("GET", PROJECTS, None),
        ("POST", PROJECTS, {"name": "Нельзя"}),
        ("GET", pj(w.project_p), None),
        ("GET", f"{pj(w.project_p)}/members", None),
        ("GET", f"{pj(w.project_p)}/tasks", None),
        ("GET", f"/api/v1/tasks/{w.task_t2}", None),
        ("GET", MY_TASKS, None),
        ("GET", USERS, None),
        ("GET", ME, None),
        ("GET", ADMIN_USERS, None),
        ("GET", AUDIT, None),
    ]


async def _assert_all_forbidden_no_role(env: ApiEnv, token: str, w: World) -> None:
    for method, url, body in _probes(w):
        r = await send(env, token, method, url, body)
        assert r.status_code == 403, f"{method} {url}: {r.status_code} {r.text}"
        assert code_of(r) == "no_role", f"{method} {url}: {r.text}"


async def _count(env: ApiEnv, sql: str, **params: Any) -> int:
    rows = await env.execute(text(sql).bindparams(**params))
    assert rows is not None
    return int(rows[0][0])


# --- AC-20 --------------------------------------------------------------------------------


@pytest.mark.committed
async def test_002_ac20_session_s_opened_before_upgrade_gets_403_and_can_logout(
    committed_api_env: ApiEnv,
) -> None:
    """002/AC-20: запрос списка проектов в сессии S (открыта до обновления) - 403 no_role;
    выход в S выполняется и сессия после него недействительна."""
    env = committed_api_env
    w, _ = await make_ac20_world(env)
    s_token = w.tokens["m1"]
    s_id = env.token_id(s_token)
    assert await env.session_ids(w.uid("m1")) == [s_id]  # S создана до обновления
    await to_head(env)

    listed = await send(env, s_token, "GET", PROJECTS)
    assert listed.status_code == 403, listed.text
    assert code_of(listed) == "no_role"
    _no_mixed(listed)

    out = await send(env, s_token, "POST", LOGOUT_URL)
    assert out.status_code == 204, out.text
    assert await env.session_ids(w.uid("m1")) == []
    again = await send(env, s_token, "GET", PROJECTS)
    assert again.status_code == 401, again.text


@pytest.mark.committed
async def test_002_ac20_m1_logs_in_with_old_password_role_null_only_logout_and_password(
    committed_api_env: ApiEnv,
) -> None:
    """002/AC-20: вход m1 прежним паролем - роль null; далее всё, кроме выхода и смены своего
    пароля, - 403; смена своего пароля выполняется (и новый пароль работает)."""
    env = committed_api_env
    w, _ = await make_ac20_world(env)
    await to_head(env)

    token, body = await _login(env, "m1")
    assert body["user"]["role"] is None, body
    assert body["user"]["must_change_password"] is False
    assert body["user"]["login"] == _login_of("m1")

    await _assert_all_forbidden_no_role(env, token, w)

    changed = await send(
        env,
        token,
        "POST",
        PASSWORD_URL,
        {"current_password": DEFAULT_PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert changed.status_code == 204, changed.text
    assert (await env.login(_login_of("m1"), DEFAULT_PASSWORD)).status_code == 401
    token2, body2 = await _login(env, "m1", NEW_PASSWORD)
    assert body2["user"]["role"] is None

    out = await send(env, token2, "POST", LOGOUT_URL)
    assert out.status_code == 204, out.text


@pytest.mark.committed
async def test_002_ac20_m3_logs_in_with_one_time_password_changes_it_then_403(
    committed_api_env: ApiEnv,
) -> None:
    """002/AC-20: вход m3 с одноразовым паролем - ответ требует смены пароля; после смены
    любой запрос, кроме выхода и смены своего пароля, - 403; выход выполняется."""
    env = committed_api_env
    w, _ = await make_ac20_world(env)
    await to_head(env)

    token, body = await _login(env, "m3")
    assert body["user"]["role"] is None, body
    assert body["user"]["must_change_password"] is True, body

    changed = await send(
        env,
        token,
        "POST",
        PASSWORD_URL,
        {"current_password": DEFAULT_PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert changed.status_code == 204, changed.text

    token2, body2 = await _login(env, "m3", NEW_PASSWORD)
    assert body2["user"]["must_change_password"] is False
    assert body2["user"]["role"] is None
    await _assert_all_forbidden_no_role(env, token2, w)
    out = await send(env, token2, "POST", LOGOUT_URL)
    assert out.status_code == 204, out.text


@pytest.mark.committed
async def test_002_ac20_m2_stays_blocked_and_cannot_login(committed_api_env: ApiEnv) -> None:
    """002/AC-20: m2 по-прежнему заблокирован - вход отклонён (единый 401, FR-5)."""
    env = committed_api_env
    await make_ac20_world(env)
    await to_head(env)
    r = await env.login(_login_of("m2"), DEFAULT_PASSWORD)
    assert r.status_code == 401, r.text
    assert code_of(r) == "invalid_credentials"


# --- AC-22 --------------------------------------------------------------------------------


@pytest.mark.committed
async def test_002_ac22_new_tech_admins_m1_m3_log_in_and_create_accounts(
    committed_api_env: ApiEnv,
) -> None:
    """002/AC-22 (нет активного ТА): m1 входит и создаёт учётную запись; список проектов от
    m1 - 403 (ТА не читает бизнес-данные); владелец PM - m1, m1 - участник PM; m3 входит с
    одноразовым паролем, меняет пароль и создаёт учётную запись."""
    env = committed_api_env
    w, _ = await make_ac22_world(env, with_active_ta=False)
    assert w.project_pm is not None
    await to_head(env)

    token1, body1 = await _login(env, "m1")
    assert body1["user"]["role"] == "tech_admin", body1
    created = await send(
        env,
        token1,
        "POST",
        ADMIN_USERS,
        {"login": "u002.created.by.m1", "one_time_password": NEW_ACCOUNT_OTP},
    )
    assert created.status_code == 201, created.text
    assert created.json()["login"] == "u002.created.by.m1"
    assert created.json()["role"] is None

    listed = await send(env, token1, "GET", PROJECTS)
    assert listed.status_code == 403, listed.text

    detail_owner = await env.execute(
        text("SELECT owner_id FROM project WHERE id = :p").bindparams(p=w.project_pm)
    )
    assert detail_owner is not None and detail_owner[0][0] == w.uid("m1")
    member = await _count(
        env,
        "SELECT count(*) FROM project_member WHERE project_id = :p AND user_id = :u",
        p=w.project_pm,
        u=w.uid("m1"),
    )
    assert member == 1

    token3, body3 = await _login(env, "m3")
    assert body3["user"]["role"] == "tech_admin", body3
    assert body3["user"]["must_change_password"] is True
    changed = await send(
        env,
        token3,
        "POST",
        PASSWORD_URL,
        {"current_password": DEFAULT_PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert changed.status_code == 204, changed.text
    token3b, body3b = await _login(env, "m3", NEW_PASSWORD)
    assert body3b["user"]["must_change_password"] is False
    created3 = await send(
        env,
        token3b,
        "POST",
        ADMIN_USERS,
        {"login": "u002.created.by.m3", "one_time_password": NEW_ACCOUNT_OTP},
    )
    assert created3.status_code == 201, created3.text
    assert (await send(env, token3b, "GET", PROJECTS)).status_code == 403

    # m2 (заблокирован) остался без роли и войти не может
    assert (await env.login(_login_of("m2"), DEFAULT_PASSWORD)).status_code == 401


@pytest.mark.committed
async def test_002_ac22_ba_pm_transfers_pm_ownership_to_self(committed_api_env: ApiEnv) -> None:
    """002/AC-22: ba.pm (участник PM) передаёт владение PM, принадлежавшее бывшему СМ m1, себе."""
    env = committed_api_env
    w, _ = await make_ac22_world(env, with_active_ta=False)
    assert w.project_pm is not None
    await to_head(env)

    token, _ = await _login(env, "ba.pm")
    r = await send(env, token, "PUT", f"{pj(w.project_pm)}/owner", {"user_id": str(w.uid("ba.pm"))})
    assert r.status_code == 200, r.text
    assert r.json()["owner"]["id"] == str(w.uid("ba.pm"))
    _no_mixed(r)
    rows = await env.execute(
        text("SELECT owner_id FROM project WHERE id = :p").bindparams(p=w.project_pm)
    )
    assert rows is not None and rows[0][0] == w.uid("ba.pm")


# --- AC-23 --------------------------------------------------------------------------------


@pytest.mark.committed
async def test_002_ac23_ownership_task_reassign_and_wrong_role_assignee(
    committed_api_env: ApiEnv,
) -> None:
    """002/AC-23: ba.owner (не участник PM) передаёт PM участнику ba.pm - владелец ba.pm и
    запись журнала с автором ba.owner; переназначает T2 с m1 на u1 - сохранено; создаёт в P
    задачу с исполнителем m1 - 422 recipient_wrong_role, задача не создана."""
    env = committed_api_env
    w, _ = await make_ac20_world(env)
    assert w.project_p is not None and w.project_pm is not None and w.task_t2 is not None
    await to_head(env)
    ba_owner = w.uid("ba.owner")
    token, _ = await _login(env, "ba.owner")

    moved = await send(
        env, token, "PUT", f"{pj(w.project_pm)}/owner", {"user_id": str(w.uid("ba.pm"))}
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["owner"]["id"] == str(w.uid("ba.pm"))
    events = await env.execute(
        text(
            "SELECT actor_id, entity_id FROM domain_event "
            "WHERE action = 'project.ownership_transferred' AND entity_id = :p"
        ).bindparams(p=w.project_pm)
    )
    assert events is not None and len(events) == 1
    assert events[0][0] == ba_owner

    reassigned = await send(
        env, token, "PATCH", f"/api/v1/tasks/{w.task_t2}", {"assignee_id": str(w.uid("u1"))}
    )
    assert reassigned.status_code == 200, reassigned.text
    assert reassigned.json()["assignee"]["id"] == str(w.uid("u1"))
    stored = await env.execute(
        text("SELECT assignee_id FROM task WHERE id = :t").bindparams(t=w.task_t2)
    )
    assert stored is not None and stored[0][0] == w.uid("u1")

    tasks_before = await _count(
        env, "SELECT count(*) FROM task WHERE project_id = :p", p=w.project_p
    )
    refused = await send(
        env,
        token,
        "POST",
        f"{pj(w.project_p)}/tasks",
        {**TASK_REQ, "title": "Для бывшего СМ", "assignee_id": str(w.uid("m1"))},
    )
    assert refused.status_code == 422, refused.text
    assert code_of(refused) == "recipient_wrong_role"
    tasks_after = await _count(
        env, "SELECT count(*) FROM task WHERE project_id = :p", p=w.project_p
    )
    assert tasks_after == tasks_before


# --- AC-25 --------------------------------------------------------------------------------


@pytest.mark.committed
async def test_002_ac25_no_mixed_in_any_api_response(committed_api_env: ApiEnv) -> None:
    """002/AC-25: вход m1 - роль null; /me от m1 - 403; ta1: список и карточка m1 - роль
    null; ba.owner: участники P - роль m1 null, справочник без m1. Ни в одном ответе нет mixed
    (по тексту ответа и по полям role)."""
    env = committed_api_env
    w, _ = await make_ac20_world(env)
    assert w.project_p is not None
    await to_head(env)
    m1 = str(w.uid("m1"))
    responses: list[httpx.Response] = []

    login_r = await env.login(_login_of("m1"), DEFAULT_PASSWORD)
    assert login_r.status_code == 200, login_r.text
    assert login_r.json()["user"]["role"] is None
    responses.append(login_r)
    m1_token = env.token_from(login_r)
    assert m1_token
    me = await send(env, m1_token, "GET", ME)
    assert me.status_code == 403, me.text
    responses.append(me)
    # ответ для сессии S (открыта до обновления) тоже без mixed
    responses.append(await send(env, w.tokens["m1"], "GET", ME))

    ta_token, _ = await _login(env, "ta1")
    listed = await send(env, ta_token, "GET", f"{ADMIN_USERS}?page_size=100")
    assert listed.status_code == 200, listed.text
    responses.append(listed)
    body = listed.json()
    assert body["has_next"] is False
    by_id = {item["id"]: item for item in body["items"]}
    assert len(by_id) == len(w.users)
    for name in ("m1", "m2", "m3"):
        assert by_id[str(w.uid(name))]["role"] is None, name
    assert by_id[str(w.uid("ta1"))]["role"] == "tech_admin"
    assert {i["role"] for i in body["items"]} == {None, "tech_admin", "business_admin", "user"}

    card = await send(env, ta_token, "GET", f"{ADMIN_USERS}/{m1}")
    assert card.status_code == 200, card.text
    assert card.json()["role"] is None
    responses.append(card)

    ba_token, _ = await _login(env, "ba.owner")
    members = await send(env, ba_token, "GET", f"{pj(w.project_p)}/members?page_size=100")
    assert members.status_code == 200, members.text
    responses.append(members)
    by_user = {item["user"]["id"]: item for item in members.json()["items"]}
    assert set(by_user) == {str(w.uid(n)) for n in ("ba.owner", "m1", "u1")}
    assert by_user[m1]["role"] is None
    assert by_user[str(w.uid("u1"))]["role"] == "user"

    directory = await send(env, ba_token, "GET", f"{USERS}?page_size=100")
    assert directory.status_code == 200, directory.text
    responses.append(directory)
    dir_items = directory.json()["items"]
    assert str(w.uid("m1")) not in {i["id"] for i in dir_items}
    assert _login_of("m1") not in {i["login"] for i in dir_items}
    assert {i["role"] for i in dir_items} <= {"business_admin", "user"}
    assert {i["id"] for i in dir_items} >= {str(w.uid(n)) for n in ("ba.owner", "ba.pm", "u1")}

    for r in responses:
        _no_mixed(r)
    # то же по значениям полей role во всех JSON-ответах
    for r in responses:
        for value in _role_values(r.text):
            assert value in {None, "tech_admin", "business_admin", "user"}, value


def _role_values(raw: str) -> list[Any]:
    """Все значения полей ``role`` в JSON-ответе (рекурсивно)."""
    found: list[Any] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "role":
                    found.append(value)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    try:
        walk(json.loads(raw))
    except ValueError:
        return []
    return found


# --- AC-26 --------------------------------------------------------------------------------


@pytest.mark.committed
async def test_002_ac26_history_with_mixed_is_read_page_by_page(
    committed_api_env: ApiEnv,
) -> None:
    """002/AC-26: три исторические записи (назначение: null -> mixed, смена: user -> mixed,
    снятие: mixed -> null), созданные в схеме 0005; после обновления ta1 читает журнал
    постранично (page_size < числа записей): все записи на месте, без пропусков и повторов,
    значения mixed как до обновления."""
    env = committed_api_env
    w, _ = await make_ac20_world(env)
    historic: dict[str, tuple[str, dict[str, object]]] = {}
    cases: list[tuple[str, str, dict[str, object]]] = [
        ("u1", "user.role_assigned", {"role_from": None, "role_to": "mixed"}),
        ("ba.pm", "user.role_changed", {"role_from": "user", "role_to": "mixed"}),
        ("ta1", "user.role_removed", {"role_from": "mixed", "role_to": None}),
    ]
    async with env.sessionmaker() as s:
        for name, action, details in cases:
            created_id = await make_domain_event(
                s,
                workspace_id=w.ws.id,
                actor_id=w.uid("ta1"),
                entity_type="user",
                entity_id=w.uid(name),
                action=action,
                in_audit=True,
                details=details,
            )
            historic[str(created_id)] = (action, details)
        await s.commit()
    assert len(historic) == 3
    await to_head(env)

    db_ids = await env.execute(text("SELECT id FROM domain_event WHERE in_audit ORDER BY id DESC"))
    assert db_ids is not None
    expected_ids = [str(r[0]) for r in db_ids]
    total = len(expected_ids)
    assert total > 6

    token, _ = await _login(env, "ta1")
    page_size = 4
    assert page_size < total
    seen: list[dict[str, Any]] = []
    page = 1
    while True:
        r = await send(env, token, "GET", f"{AUDIT}?page={page}&page_size={page_size}")
        assert r.status_code == 200, f"страница {page}: {r.status_code} {r.text}"
        data = r.json()
        assert data["page"] == page and data["page_size"] == page_size
        assert 0 < len(data["items"]) <= page_size
        seen.extend(data["items"])
        if not data["has_next"]:
            break
        assert len(data["items"]) == page_size
        page += 1
        assert page < 50
    assert page > 1
    assert [str(i["id"]) for i in seen] == expected_ids  # без пропусков, повторов, порядок id DESC

    by_id = {str(i["id"]): i for i in seen}
    for key, (action, details) in historic.items():
        entry = by_id[key]
        assert entry["action"] == action
        assert entry["details"] == details, entry
    # запись по id тоже читается
    one = await send(env, token, "GET", f"{AUDIT}/{next(iter(historic))}")
    assert one.status_code == 200, one.text
