"""R7-T12: аутентификация по ключу через API (007).

AC-4, AC-5, AC-6 («кто я» по выпущенному секрету), AC-7 (агент по ключу), AC-8 (по реальному
запросу), AC-9 (401 после отзыва), AC-10, AC-13, AC-14, AC-15, AC-17, AC-33, AC-40;
FR-12…FR-15, FR-17, FR-18, FR-33; plan §4.7, PD-2, PD-3, PD-5; обязательные условия ревью
R7-T11 (``commit_durably`` до разбора отказа, проверки ``is_blocked``/членства/``is_agent``,
выход и смена пароля с ключом и cookie -> 403).

Контракт (plan §4.7)::

    Authorization: Bearer <ключ>  (регистр схемы не важен)
    get_actor: ключ есть -> _actor_from_api_key; любой отказ -> 401 ровно
        {"detail": "Требуется вход в систему", "code": "not_authenticated"}
    лимит: 120 запросов в окне 60 с на ключ; 121-й -> 429 too_many_requests + Retry-After;
        счётчик фиксируется до разбора отказа (rate_count = 121 в БД после 429)
    по ключу cookie-сессии не создаются, не продлеваются и не завершаются; Set-Cookie нет

Часы: мир ``make_world007`` ставит ``CLOCK`` (2026-11-02 07:00Z = 10:00 MSK) и создаёт
cookie-сессии на нём, поэтому сдвиги на минуты не роняют cookie. Секрет ключа не попадает в
сообщения ``assert``: проверки вхождения считаются в булеву переменную до ``assert``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from tests.agents007_support import (
    ADMIN_AGENTS,
    ADMIN_USERS,
    AUDIT,
    CLOCK,
    LOGOUT_URL,
    ME_URL,
    MY_TASKS_URL,
    NOT_AUTHENTICATED_BODY,
    PASSWORD_URL,
    PROJECTS_URL,
    HiddenSecret,
    World007,
    bearer,
    hide,
    make_agent,
    make_key,
    make_world007,
    mutated_secret,
    session_count,
    table_digest,
)
from tests.conftest import ApiEnv

PW = "Sup3r-secret-Pa55phrase-xyz"


# --- помощники -----------------------------------------------------------------------------


def keys_url(agent_id: uuid.UUID | str) -> str:
    return f"{ADMIN_AGENTS}/{agent_id}/api-keys"


def revoke_url(agent_id: uuid.UUID | str, key_id: uuid.UUID | str) -> str:
    return f"{ADMIN_AGENTS}/{agent_id}/api-keys/{key_id}/revoke"


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def code(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    return str(body.get("code")) if isinstance(body, dict) else None


def leaked(secret: str, haystack: str) -> bool:
    """Секрет или его подстрока длиной от 8 символов в тексте (AC-38)."""
    return any(secret[i : i + 8] in haystack for i in range(len(secret) - 7))


async def me_by_key(env: ApiEnv, secret: str, **extra: str) -> httpx.Response:
    return await env.client.get(ME_URL, headers={**bearer(secret), **extra})


async def cookie_req(
    env: ApiEnv, w: World007, who: str, method: str, url: str, body: Any = None
) -> httpx.Response:
    kwargs: dict[str, Any] = {} if body is None else {"json": body}
    return await env.client.request(method, url, headers=env.auth(w.cookie(who)), **kwargs)


async def key_req(
    env: ApiEnv, secret: str, method: str, url: str, body: Any = None
) -> httpx.Response:
    kwargs: dict[str, Any] = {} if body is None else {"json": body}
    return await env.client.request(method, url, headers=bearer(secret), **kwargs)


async def scalar(env: ApiEnv, sql: str, **params: Any) -> Any:
    rows = await env.execute(text(sql).bindparams(**params))
    assert rows is not None
    return rows[0][0]


async def key_state(env: ApiEnv, w: World007, key_id: uuid.UUID) -> dict[str, Any]:
    """Элемент перечня ключей ``agent.u`` глазами ``ta1`` (cookie)."""
    r = await cookie_req(env, w, "ta1", "GET", f"{keys_url(w.agent_u.id)}?page_size=100")
    assert r.status_code == 200, r.text
    items = {item["id"]: item for item in r.json()["items"]}
    return dict(items[str(key_id)])


def assert_unauthenticated(response: httpx.Response, label: str) -> None:
    assert response.status_code == 401, f"{label}: {response.status_code}"
    assert response.json() == NOT_AUTHENTICATED_BODY, f"{label}: тело отказа"


async def assert_key_works(env: ApiEnv, secret: str, label: str) -> None:
    """Положительный контроль: без него 401 в тестах отказа ничего не доказывал бы."""
    r = await me_by_key(env, secret)
    assert r.status_code == 200, f"{label}: действующий ключ не принят ({r.status_code})"


def _task_count_sql() -> str:
    return "SELECT count(*) FROM task WHERE project_id = :p"


# --- AC-13, AC-17: «кто я» по ключу, без сессий --------------------------------------------


async def test_007_ac13_me_by_key_no_set_cookie_and_sessions_unchanged(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_world007(env)
    sessions_before = await session_count(env)

    r = await me_by_key(env, w.K_u.secret)

    assert r.status_code == 200
    assert r.json()["id"] == str(w.agent_u.id)
    assert r.json()["login"] == "agent.u"
    assert r.headers.get_list("set-cookie") == []
    assert await session_count(env) == sessions_before


async def test_007_ac17_me_by_key_returns_agent_identity(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_world007(env)

    r = await me_by_key(env, w.K_u.secret)

    assert r.status_code == 200
    body = r.json()
    assert body["id"] == str(w.agent_u.id)
    assert body["login"] == "agent.u"
    assert body["role"] == "user"
    assert body["is_agent"] is True
    assert body["must_change_password"] is False


async def test_007_fr12_bearer_scheme_is_case_insensitive(api_env: ApiEnv) -> None:
    """plan §4.7 ``presented_api_key``: регистр схемы не важен."""
    env = api_env
    w = await make_world007(env)
    r = await env.client.get(ME_URL, headers={"Authorization": "bearer " + w.K_ba.secret})
    assert r.status_code == 200
    assert r.json()["login"] == "agent.ba"
    assert r.json()["role"] == "business_admin"
    assert r.json()["is_agent"] is True


# --- AC-14: единый отказ 401 -----------------------------------------------------------------


async def test_007_ac14_eight_refusals_have_identical_body(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_world007(env)
    await assert_key_works(env, w.K_u.secret, "K_u")
    revoked = hide(await make_key(env, w.agent_u, created_by=w.ta1, name="rev", revoked_at=CLOCK))
    expired = hide(
        await make_key(
            env, w.agent_u, created_by=w.ta1, name="exp", created_at=CLOCK - timedelta(days=91)
        )
    )
    blk = await make_agent(env, "agent.blk", "user", workspace=w.ws)
    blk_key = hide(await make_key(env, blk, created_by=w.ta1, name="blk"))
    await assert_key_works(env, blk_key.secret, "ключ agent.blk до блокировки")
    # блокировка напрямую в БД — ключ НЕ отзывается: отказ даёт проверка is_blocked
    await env.execute(
        text("UPDATE app_user SET is_blocked = true WHERE id = :u").bindparams(u=blk.id)
    )

    cases: dict[str, httpx.Response] = {
        "без ключа": await env.client.get(ME_URL),
        "пустой ключ": await env.client.get(ME_URL, headers={"Authorization": "Bearer "}),
        "только схема": await env.client.get(ME_URL, headers={"Authorization": "Bearer"}),
        "не по формату": await env.client.get(
            ME_URL, headers={"Authorization": "Bearer not-a-key"}
        ),
        "изменён один символ": await me_by_key(env, mutated_secret(w.K_u.secret)),
        "отозван": await me_by_key(env, revoked.secret),
        "истёк": await me_by_key(env, expired.secret),
        "учётная запись заблокирована": await me_by_key(env, blk_key.secret),
    }
    for param in ("api_key", "key", "token", "access_token", "authorization"):
        cases[f"в параметре {param}"] = await env.client.get(ME_URL, params={param: w.K_u.secret})
    for label, response in cases.items():
        assert_unauthenticated(response, label)
    bodies = {response.content for response in cases.values()}
    assert len(bodies) == 1, "тела отказа различаются"


async def test_007_ac14_basic_scheme_and_two_authorization_headers_are_401(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_world007(env)
    await assert_key_works(env, w.K_u.secret, "K_u")

    basic = await env.client.get(ME_URL, headers={"Authorization": "Basic YWdlbnQudTpwYXNz"})
    basic_key = await env.client.get(ME_URL, headers={"Authorization": "Basic " + w.K_u.secret})
    two = await env.client.get(
        ME_URL,
        headers=[("Authorization", "Bearer " + w.K_u.secret), ("Authorization", "Bearer x")],
    )
    two_same = await env.client.get(
        ME_URL,
        headers=[
            ("Authorization", "Bearer " + w.K_u.secret),
            ("Authorization", "Bearer " + w.K_u.secret),
        ],
    )
    for label, response in {
        "Basic": basic,
        "Basic с ключом": basic_key,
        "два заголовка": two,
        "два одинаковых заголовка": two_same,
    }.items():
        assert_unauthenticated(response, label)


async def test_007_fr13_key_of_non_agent_account_is_401(api_env: ApiEnv) -> None:
    """Обязательное условие R7-T11 (2): строка ключа у учётной записи без ``is_agent`` -> 401."""
    env = api_env
    w = await make_world007(env)
    await assert_key_works(env, w.K_u.secret, "K_u")
    human_key = hide(await make_key(env, w.u1, created_by=w.ta1, name="human"))

    r = await me_by_key(env, human_key.secret)

    assert_unauthenticated(r, "ключ не-агента")


async def test_007_fr13_key_outside_owner_workspace_membership_is_401(api_env: ApiEnv) -> None:
    """Обязательное условие R7-T11 (2): учётная запись не состоит в пространстве ключа -> 401."""
    from tests.admin_support import new_workspace

    env = api_env
    w = await make_world007(env)
    key = hide(await make_key(env, w.agent_u, created_by=w.ta1, name="foreign-ws"))
    await assert_key_works(env, key.secret, "ключ до переноса")
    other = await new_workspace(env)
    await env.execute(
        text("UPDATE api_key SET workspace_id = :w WHERE id = :k").bindparams(w=other.id, k=key.id)
    )

    r = await me_by_key(env, key.secret)

    assert_unauthenticated(r, "не член пространства ключа")


# --- AC-15: ключ и cookie одновременно -------------------------------------------------------


async def test_007_ac15_cookie_with_revoked_key_is_401_and_with_valid_key_acts_as_agent(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_world007(env)
    revoked = hide(await make_key(env, w.agent_u, created_by=w.ta1, name="rev", revoked_at=CLOCK))
    plain = await env.me(w.cookie("ba1"))
    assert plain.status_code == 200
    assert plain.json()["login"] == "ba1"

    bad = await env.client.get(
        ME_URL, headers=env.auth(w.cookie("ba1"), Authorization="Bearer " + revoked.secret)
    )
    good = await env.client.get(
        ME_URL, headers=env.auth(w.cookie("ba1"), Authorization="Bearer " + w.K_u.secret)
    )
    basic = await env.client.get(
        ME_URL, headers=env.auth(w.cookie("ba1"), Authorization="Basic YmExOnBhc3M=")
    )

    assert_unauthenticated(bad, "cookie + отозванный ключ")
    assert_unauthenticated(basic, "cookie + Basic")
    assert good.status_code == 200
    assert good.json()["id"] == str(w.agent_u.id)
    assert good.json()["login"] == "agent.u"
    assert good.headers.get_list("set-cookie") == []


async def test_007_fr15_key_with_cookie_does_not_touch_cookie_session(api_env: ApiEnv) -> None:
    """Сессия cookie при запросе по ключу не продлевается (``last_activity_at`` не меняется)."""
    env = api_env
    w = await make_world007(env)
    sid = env.token_id(w.cookie("ba1"))
    sql = "SELECT last_activity_at FROM user_session WHERE id = :s"
    before = await scalar(env, sql, s=sid)
    env.clock.advance(timedelta(minutes=1))

    r = await env.client.get(
        ME_URL, headers=env.auth(w.cookie("ba1"), Authorization="Bearer " + w.K_u.secret)
    )

    assert r.status_code == 200
    assert r.json()["login"] == "agent.u"
    assert await scalar(env, sql, s=sid) == before, "cookie-сессия продлена запросом по ключу"


async def test_007_fr15_logout_with_key_and_cookie_is_403_and_session_survives(
    api_env: ApiEnv,
) -> None:
    """Обязательное условие R7-T11 (4): ``/auth/logout`` с Bearer и действующей cookie."""
    env = api_env
    w = await make_world007(env)
    sessions = await env.session_ids(w.ba1.id)
    assert len(sessions) == 1

    r = await env.client.post(
        LOGOUT_URL, headers=env.auth(w.cookie("ba1"), Authorization="Bearer " + w.K_u.secret)
    )

    assert (r.status_code, code(r)) == (403, "forbidden")
    assert r.headers.get_list("set-cookie") == []
    assert await env.session_ids(w.ba1.id) == sessions, "cookie-сессия завершена"
    still = await env.me(w.cookie("ba1"))
    assert still.status_code == 200


async def test_007_fr15_password_change_with_key_and_cookie_is_403_and_nothing_changes(
    api_env: ApiEnv,
) -> None:
    """Обязательное условие R7-T11 (4): ``/auth/password`` с Bearer и действующей cookie."""
    env = api_env
    w = await make_world007(env)
    person = w.ba1
    sessions = await env.session_ids(person.id)
    hash_before = (await env.user_row(person.id)).password_hash

    r = await env.client.post(
        PASSWORD_URL,
        json={"current_password": PW, "new_password": PW + "-new"},
        headers=env.auth(w.cookie("ba1"), Authorization="Bearer " + w.K_u.secret),
    )

    assert (r.status_code, code(r)) == (403, "forbidden")
    assert r.headers.get_list("set-cookie") == []
    assert await env.session_ids(person.id) == sessions
    assert (await env.user_row(person.id)).password_hash == hash_before
    still = await env.me(w.cookie("ba1"))
    assert still.status_code == 200


# --- AC-4, AC-5: блокировка и роль ----------------------------------------------------------


async def test_007_ac4_block_unblock_leaves_key_revoked_new_key_works(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_world007(env)
    await assert_key_works(env, w.K_u.secret, "K_u")

    blocked = await cookie_req(env, w, "ta1", "POST", f"{ADMIN_USERS}/{w.agent_u.id}/block")
    assert blocked.status_code == 204
    assert_unauthenticated(await me_by_key(env, w.K_u.secret), "после блокировки")

    unblocked = await cookie_req(env, w, "ta1", "POST", f"{ADMIN_USERS}/{w.agent_u.id}/unblock")
    assert unblocked.status_code == 204
    assert_unauthenticated(await me_by_key(env, w.K_u.secret), "после разблокировки")
    assert (await key_state(env, w, w.K_u.id))["state"] == "revoked"

    issued = await cookie_req(
        env, w, "ta1", "POST", keys_url(w.agent_u.id), {"name": "new", "expires_in_days": 90}
    )
    assert issued.status_code == 201
    r = await me_by_key(env, HiddenSecret(issued.json()["secret"]))
    assert r.status_code == 200
    assert r.json()["login"] == "agent.u"


async def test_007_ac4_blocked_owner_with_unrevoked_key_is_401_on_every_request(
    api_env: ApiEnv,
) -> None:
    """Блокировка, читаемая на каждый запрос (FR-14), даже если ключ не отозван."""
    env = api_env
    w = await make_world007(env)
    await assert_key_works(env, w.K_u.secret, "K_u")
    set_blocked = "UPDATE app_user SET is_blocked = :b WHERE id = :u"

    await env.execute(text(set_blocked).bindparams(b=True, u=w.agent_u.id))
    revoked_at = await scalar(env, "SELECT revoked_at FROM api_key WHERE id = :k", k=w.K_u.id)
    assert revoked_at is None
    assert_unauthenticated(await me_by_key(env, w.K_u.secret), "заблокирован, ключ не отозван")
    tasks = await key_req(env, w.K_u.secret, "GET", MY_TASKS_URL)
    assert_unauthenticated(tasks, "мои задачи, заблокирован")

    await env.execute(text(set_blocked).bindparams(b=False, u=w.agent_u.id))
    await assert_key_works(env, w.K_u.secret, "после снятия блокировки в БД")


def _ten_operations(w: World007) -> list[tuple[str, str, dict[str, Any] | None]]:
    return [
        ("GET", ME_URL, None),
        ("GET", PROJECTS_URL, None),
        ("GET", MY_TASKS_URL, None),
        ("GET", f"{PROJECTS_URL}/{w.P}/tasks", None),
        ("GET", f"/api/v1/tasks/{w.T1}", None),
        (
            "POST",
            f"{PROJECTS_URL}/{w.P}/tasks",
            {"title": "Новая", "assignee_id": str(w.agent_u.id)},
        ),
        (
            "POST",
            f"/api/v1/tasks/{w.T1}/subtasks",
            {"title": "Под", "assignee_id": str(w.agent_u.id)},
        ),
        ("PATCH", f"/api/v1/tasks/{w.T1}", {"status": "in_progress"}),
        ("GET", f"/api/v1/tasks/{w.T1}/comments", None),
        ("POST", f"/api/v1/tasks/{w.T1}/comments", {"body": "Комментарий агента"}),
    ]


async def test_007_ac5_no_role_gives_403_on_all_ten_operations_then_role_restores(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_world007(env)
    await assert_key_works(env, w.K_u.secret, "K_u")
    role_url = f"{ADMIN_USERS}/{w.agent_u.id}/role"

    dropped = await cookie_req(env, w, "ta1", "PUT", role_url, {"role": None})
    assert dropped.status_code == 200, dropped.text
    tasks_before = await scalar(env, _task_count_sql(), p=w.P)

    results = {}
    for method, url, body in _ten_operations(w):
        r = await key_req(env, w.K_u.secret, method, url, body)
        results[(method, url)] = (r.status_code, code(r))
    assert set(results.values()) == {(403, "no_role")}, results
    assert await scalar(env, _task_count_sql(), p=w.P) == tasks_before

    restored = await cookie_req(env, w, "ta1", "PUT", role_url, {"role": "user"})
    assert restored.status_code == 200
    r = await me_by_key(env, w.K_u.secret)
    assert r.status_code == 200
    assert r.json()["role"] == "user"
    assert (await key_state(env, w, w.K_u.id))["state"] == "active"


# --- AC-6…AC-10: ключ, выпущенный через API; перечень; отзыв; срок ---------------------------


async def test_007_ac6_me_with_secret_issued_via_api(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_world007(env)
    issued = await cookie_req(
        env,
        w,
        "ta1",
        "POST",
        keys_url(w.agent_u.id),
        {"name": "claude-laptop", "expires_in_days": 90},
    )
    assert issued.status_code == 201

    r = await me_by_key(env, HiddenSecret(issued.json()["secret"]))

    assert r.status_code == 200
    assert r.json()["id"] == str(w.agent_u.id)
    assert r.json()["login"] == "agent.u"


async def test_007_ac7_agent_ba_by_key_cannot_issue_revoke_or_list_keys(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_world007(env)
    await assert_key_works(env, w.K_ba.secret, "K_ba")
    before = await table_digest(env, "api_key", "domain_event")

    issue = await key_req(
        env, w.K_ba.secret, "POST", keys_url(w.agent_u.id), {"name": "x", "expires_in_days": 30}
    )
    revoke = await key_req(env, w.K_ba.secret, "POST", revoke_url(w.agent_u.id, w.K_u.id))
    listing = await key_req(env, w.K_ba.secret, "GET", keys_url(w.agent_u.id))

    for label, r in {"выпуск": issue, "отзыв": revoke, "перечень": listing}.items():
        assert (r.status_code, code(r)) == (403, "forbidden"), label
    # K_ba не тронут гейтом перечня: rate_count/last_used_at не изменились
    assert await table_digest(env, "api_key", "domain_event") == before
    await assert_key_works(env, w.K_u.secret, "K_u не отозван")


async def test_007_ac8_last_used_at_set_by_real_request(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_world007(env)
    assert env.clock.now() == CLOCK
    assert (await key_state(env, w, w.K_u.id))["last_used_at"] is None

    r = await me_by_key(env, w.K_u.secret)
    assert r.status_code == 200

    item = await key_state(env, w, w.K_u.id)
    assert item["last_used_at"] is not None
    assert abs(parse(item["last_used_at"]) - CLOCK) <= timedelta(minutes=5)
    ba_item = await cookie_req(env, w, "ta1", "GET", keys_url(w.agent_ba.id))
    assert ba_item.json()["items"][0]["last_used_at"] is None


async def test_007_ac9_revoked_via_api_key_is_401(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_world007(env)
    await assert_key_works(env, w.K_u.secret, "K_u")

    revoked = await cookie_req(env, w, "ta1", "POST", revoke_url(w.agent_u.id, w.K_u.id))
    assert revoked.status_code == 204

    assert_unauthenticated(await me_by_key(env, w.K_u.secret), "после отзыва")
    assert_unauthenticated(
        await key_req(env, w.K_u.secret, "GET", PROJECTS_URL), "проекты после отзыва"
    )


async def test_007_ac10_expiry_boundary_via_api(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_world007(env)
    key = hide(await make_key(env, w.agent_u, created_by=w.ta1, name="ttl", created_at=CLOCK))
    end = CLOCK + timedelta(days=90)

    env.clock.set(end - timedelta(seconds=1))
    before_end = await me_by_key(env, key.secret)
    env.clock.set(end)
    at_end = await me_by_key(env, key.secret)

    assert before_end.status_code == 200
    assert_unauthenticated(at_end, "в момент окончания срока")


# --- AC-33: 14 действий по K_ba ----------------------------------------------------------------


async def _ac33_fixture(env: ApiEnv, w: World007) -> dict[str, uuid.UUID]:
    from tests.factories import make_comment, make_task

    async with env.sessionmaker() as s:
        sub = await make_task(
            s,
            project_id=w.P,
            workspace_id=w.ws.id,
            created_by=w.ba1.id,
            parent_id=w.T2,
            title="sub",
        )
        own = await make_comment(
            s, task_id=w.T1, workspace_id=w.ws.id, created_by=w.agent_ba.id, body="мой"
        )
        await s.commit()
    return {"sub": sub.id, "own": own.id}


async def test_007_ac33_fourteen_actions_by_key_are_forbidden_and_data_unchanged(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_world007(env)
    ids = await _ac33_fixture(env, w)
    await assert_key_works(env, w.K_ba.secret, "K_ba")
    tables = ("project", "project_member", "task", "comment", "api_key", "user_session")
    tables += ("domain_event", "app_user", "workspace_member")
    before = await table_digest(env, *tables)
    k = w.K_ba.secret
    p = f"{PROJECTS_URL}/{w.P}"

    actions: dict[str, httpx.Response] = {
        "удаление T2": await key_req(env, k, "DELETE", f"/api/v1/tasks/{w.T2}"),
        "удаление подзадачи": await key_req(env, k, "DELETE", f"/api/v1/tasks/{ids['sub']}"),
        "правка c1": await key_req(env, k, "PATCH", f"/api/v1/comments/{w.c1}", {"body": "x"}),
        "удаление c1": await key_req(env, k, "DELETE", f"/api/v1/comments/{w.c1}"),
        "правка своего": await key_req(
            env, k, "PATCH", f"/api/v1/comments/{ids['own']}", {"body": "x"}
        ),
        "удаление своего": await key_req(env, k, "DELETE", f"/api/v1/comments/{ids['own']}"),
        "название P": await key_req(env, k, "PATCH", p, {"name": "P-новое"}),
        "удаление P": await key_req(env, k, "DELETE", p),
        "добавление участника": await key_req(
            env, k, "POST", f"{p}/members", {"user_id": str(w.ta1.id)}
        ),
        "исключение участника": await key_req(env, k, "DELETE", f"{p}/members/{w.u1.id}"),
        "передача владения": await key_req(
            env, k, "PUT", f"{p}/owner", {"user_id": str(w.agent_ba.id)}
        ),
        "перенос T2 по доске": await key_req(
            env,
            k,
            "POST",
            f"/api/v1/tasks/{w.T2}/move",
            {"status": "in_progress", "before_task_id": str(w.T3)},
        ),
        "список учётных записей": await key_req(env, k, "GET", ADMIN_USERS),
        "журнал аудита": await key_req(env, k, "GET", AUDIT),
        "выпуск ключа": await key_req(
            env, k, "POST", keys_url(w.agent_ba.id), {"name": "self", "expires_in_days": 30}
        ),
        "выход": await key_req(env, k, "POST", LOGOUT_URL),
        "смена пароля": await key_req(
            env, k, "POST", PASSWORD_URL, {"current_password": PW, "new_password": PW + "-n"}
        ),
    }

    got = {label: (r.status_code, code(r)) for label, r in actions.items()}
    assert got == dict.fromkeys(actions, (403, "forbidden"))
    assert await table_digest(env, *tables) == before, "данные изменились"


async def test_007_ac33_same_task_and_comment_actions_by_ba1_cookie_follow_002(
    api_env: ApiEnv,
) -> None:
    """Для людей поведение не изменилось (002): БА-участник удаляет задачи и любые
    комментарии проекта, правит только свои, переносит карточки."""
    env = api_env
    w = await make_world007(env)
    ids = await _ac33_fixture(env, w)

    edit_c1 = await cookie_req(env, w, "ba1", "PATCH", f"/api/v1/comments/{w.c1}", {"body": "x"})
    mine = await cookie_req(env, w, "ba1", "POST", f"/api/v1/tasks/{w.T1}/comments", {"body": "b"})
    assert mine.status_code == 201
    edit_mine = await cookie_req(
        env, w, "ba1", "PATCH", f"/api/v1/comments/{mine.json()['id']}", {"body": "b2"}
    )
    del_c1 = await cookie_req(env, w, "ba1", "DELETE", f"/api/v1/comments/{w.c1}")
    del_agent = await cookie_req(env, w, "ba1", "DELETE", f"/api/v1/comments/{ids['own']}")
    move = await cookie_req(
        env,
        w,
        "ba1",
        "POST",
        f"/api/v1/tasks/{w.T2}/move",
        {"status": "in_progress", "before_task_id": str(w.T3)},
    )
    del_sub = await cookie_req(env, w, "ba1", "DELETE", f"/api/v1/tasks/{ids['sub']}")
    del_t2 = await cookie_req(env, w, "ba1", "DELETE", f"/api/v1/tasks/{w.T2}")

    assert (edit_c1.status_code, code(edit_c1)) == (403, "forbidden")  # чужой — только автор
    assert edit_mine.status_code == 200
    assert del_c1.status_code == 204
    assert del_agent.status_code == 204
    assert move.status_code == 204
    assert del_sub.status_code == 204
    assert del_t2.status_code == 204


# --- AC-40: лимит частоты --------------------------------------------------------------------


async def test_007_ac40_rate_limit_120_per_minute_per_key(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_world007(env)
    k = w.K_u.secret

    statuses = [(await me_by_key(env, k)).status_code for _ in range(120)]
    assert statuses == [200] * 120

    limited = await me_by_key(env, k)
    assert (limited.status_code, code(limited)) == (429, "too_many_requests")
    assert limited.headers.get("retry-after") == "60"
    assert limited.headers.get_list("set-cookie") == []

    # 121-й — создание задачи: 429, задачи не прибавилось
    tasks_before = await scalar(env, _task_count_sql(), p=w.P)
    create = await key_req(
        env,
        k,
        "POST",
        f"{PROJECTS_URL}/{w.P}/tasks",
        {"title": "x", "assignee_id": str(w.agent_u.id)},
    )
    assert (create.status_code, code(create)) == (429, "too_many_requests")
    assert await scalar(env, _task_count_sql(), p=w.P) == tasks_before

    # в ту же минуту: другой ключ и человек по cookie не ограничены
    other = await me_by_key(env, w.K_ba.secret)
    human = await env.me(w.cookie("u1"))
    assert other.status_code == 200
    assert human.status_code == 200

    env.clock.advance(timedelta(seconds=30))
    half = await me_by_key(env, k)
    assert half.status_code == 429
    assert half.headers.get("retry-after") == "30"

    env.clock.set(CLOCK + timedelta(seconds=60))
    again = await me_by_key(env, k)
    assert again.status_code == 200


async def test_007_ac40_counter_is_committed_before_429_and_next_request_still_limited(
    api_env: ApiEnv,
) -> None:
    """Обязательное условие R7-T11 (1): ``commit_durably`` до разбора ``RateLimited``: после
    429 в БД ``rate_count = 121``, ``last_used_at`` — время последнего успешного запроса, и
    следующий запрос в том же окне тоже 429."""
    env = api_env
    w = await make_world007(env)
    k = w.K_u.secret
    sql = "SELECT rate_count, rate_window_start, last_used_at FROM api_key WHERE id = :k"

    for _ in range(119):
        assert (await me_by_key(env, k)).status_code == 200
    env.clock.advance(timedelta(seconds=10))
    assert (await me_by_key(env, k)).status_code == 200  # 120-й, last_used_at = CLOCK+10s
    last_ok = env.clock.now()
    env.clock.advance(timedelta(seconds=5))

    first = await me_by_key(env, k)
    assert first.status_code == 429
    rows = await env.execute(text(sql).bindparams(k=w.K_u.id))
    assert rows is not None
    rate_count, window_start, last_used = rows[0]
    assert rate_count == 121
    assert window_start == CLOCK
    assert last_used == last_ok

    second = await me_by_key(env, k)
    assert second.status_code == 429
    assert second.headers.get("retry-after") == "45"
    rows = await env.execute(text(sql).bindparams(k=w.K_u.id))
    assert rows is not None
    assert rows[0][0] == 121


async def test_007_ac40_requests_with_bad_key_do_not_consume_valid_key_quota(
    api_env: ApiEnv,
) -> None:
    """Отказ 401 по чужому/изменённому ключу не трогает счётчик ``K_u``."""
    env = api_env
    w = await make_world007(env)
    for _ in range(5):
        assert (await me_by_key(env, mutated_secret(w.K_u.secret))).status_code == 401
    assert (await me_by_key(env, w.K_u.secret)).status_code == 200
    count = await scalar(env, "SELECT rate_count FROM api_key WHERE id = :k", k=w.K_u.id)
    assert count == 1


# --- FR-32 (в рамках задачи): секрет не в логах и ответах -------------------------------------


async def test_007_fr32_secret_not_in_logs_or_bodies_for_key_requests(
    api_env: ApiEnv, caplog: pytest.LogCaptureFixture
) -> None:
    env = api_env
    w = await make_world007(env)
    secret = w.K_u.secret
    responses: list[httpx.Response] = []

    with caplog.at_level(logging.DEBUG):
        responses.append(await me_by_key(env, secret))  # 200
        responses.append(await me_by_key(env, mutated_secret(secret)))  # 401
        responses.append(await key_req(env, secret, "DELETE", f"/api/v1/tasks/{w.T2}"))  # 403
        responses.append(
            await key_req(env, secret, "POST", f"{PROJECTS_URL}/{w.P}/tasks", {"title": ""})
        )  # 422
        responses.append(await env.client.get(ME_URL, params={"api_key": secret}))  # 401
        responses.append(
            await env.client.get(ME_URL, headers=[("Authorization", "Bearer " + secret)] * 2)
        )
    statuses = [r.status_code for r in responses]
    assert statuses[:4] == [200, 401, 403, 422]
    assert statuses[4:] == [401, 401]

    in_bodies = any(leaked(secret, r.text) for r in responses)
    in_headers = any(leaked(secret, str(dict(r.headers))) for r in responses)
    app_log = "\n".join(
        rec.getMessage() + (rec.exc_text or "")
        for rec in caplog.records
        if not rec.name.startswith(("httpx", "httpcore"))  # лог тестового клиента, не приложения
    )
    assert any(rec.name == "app.access" for rec in caplog.records), "access-лог не перехвачен"
    in_logs = leaked(secret, app_log)
    assert not in_bodies, "секрет в теле ответа"
    assert not in_headers, "секрет в заголовках ответа"
    assert not in_logs, "секрет в логе приложения"
