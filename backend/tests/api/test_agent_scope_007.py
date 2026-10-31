"""R7-T12: объём доступа по ключу (007/FR-17, AC-33; plan §4.7, PD-3, З-4).

Контракт (plan §4.7)::

    app.api.deps.AGENT_OPERATIONS: frozenset[str]   # имена маршрутов FR-18…FR-27
    require_agent_scope — app-level зависимость после check_origin: есть Authorization и
    scope["route"].name не в AGENT_OPERATIONS -> 403 forbidden; БД не трогает.

Маршрут вне перечня отвечает 403 ``forbidden`` при любом заголовке ``Authorization`` —
действующем ключе, недействительном ключе или схеме не Bearer (ключ не проверяется, З-4).
Обход строится по ``app.routes`` (как ``test_route_guards.py``), поэтому новые маршруты
следующих задач попадают под проверку автоматически.

Секрет ключа в сообщения ``assert`` не попадает: в сообщения пишутся только метод, путь,
статус и код ошибки.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import httpx

from tests.agents007_support import (
    AGENT_OPERATION_NAMES,
    HEALTH_URL,
    LOGIN_URL,
    LOGOUT_URL,
    PASSWORD_URL,
    World007,
    bearer,
    make_world007,
    session_count,
    table_digest,
)
from tests.conftest import ApiEnv

SOME_ID = "6f9619ff-8b86-4d11-b42d-00c04fc964ff"
PW = "Sup3r-secret-Pa55phrase-xyz"
DATA_TABLES = (
    "app_user",
    "workspace_member",
    "project",
    "project_member",
    "task",
    "comment",
    "api_key",
    "user_session",
    "domain_event",
)


def _iter_routes(routes: Any) -> Iterator[Any]:
    """Плоский обход маршрутов (копия ``test_route_guards._iter_routes``: базовые имена
    тестовых модулей уникальны, импорт из тест-модуля не используется)."""
    for route in routes:
        contexts = getattr(route, "effective_route_contexts", None)
        if callable(contexts):
            yield from _iter_routes(contexts())
        elif getattr(route, "methods", None) and hasattr(route, "path"):
            yield route
        elif getattr(route, "routes", None):
            yield from _iter_routes(route.routes)


def _api_routes(env: ApiEnv) -> list[tuple[str, str, str]]:
    """(метод, путь, имя) всех операций ``/api/v1``."""
    out: set[tuple[str, str, str]] = set()
    for route in _iter_routes(env.app.routes):
        if route.path.startswith("/api/v1"):
            for method in set(route.methods) - {"HEAD", "OPTIONS"}:
                out.add((method, route.path, route.name))
    return sorted(out)


def _concrete(path: str, w: World007) -> str:
    """Подставляет настоящие идентификаторы мира: запрос, пропущенный гейтом, изменил бы данные."""
    values = {
        "project_id": str(w.P),
        "task_id": str(w.T2),
        "comment_id": str(w.c1),
        "user_id": str(w.agent_u.id),
        "key_id": str(w.K_u.id),
    }
    return re.sub(r"\{([^}]+)\}", lambda m: values.get(m.group(1), SOME_ID), path)


def _body(method: str, path: str, w: World007) -> dict[str, Any] | None:
    """Правдоподобное тело: без гейта запрос прошёл бы валидацию и выполнил действие."""
    if method not in {"POST", "PUT", "PATCH"}:
        return None
    if path.endswith("/auth/login"):
        return {"login": "nobody.here", "password": PW}
    if path.endswith("/auth/password"):
        return {"current_password": PW, "new_password": PW + "-new"}
    if path.endswith("/role"):
        return {"role": "business_admin"}
    if path.endswith("/owner") or path.endswith("/members"):
        return {"user_id": str(w.agent_ba.id)}
    if path.endswith("/api-keys"):
        return {"name": "через-ключ", "expires_in_days": 30}
    if path.endswith("/move"):
        return {"status": "done"}
    if path.endswith("/admin/users"):
        return {"login": "via.key.user", "role": "user"}
    if path.endswith("/admin/agents"):
        return {"login": "via.key.agent", "role": "user"}
    if path.endswith("/projects"):
        return {"name": "через ключ"}
    return {"name": "через ключ", "title": "через ключ", "body": "через ключ"}


def _code(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    return str(body.get("code")) if isinstance(body, dict) else None


# --- PD-3: перечень операций агента ----------------------------------------------------------


async def test_007_fr17_agent_operations_match_plan_and_exist_among_routes(
    api_env: ApiEnv,
) -> None:
    """Каждое имя из ``AGENT_OPERATIONS`` — имя существующего маршрута ``/api/v1`` (plan PD-3)."""
    from app.api.deps import AGENT_OPERATIONS

    assert frozenset(AGENT_OPERATIONS) == AGENT_OPERATION_NAMES
    names = {name for _, _, name in _api_routes(api_env)}
    missing = sorted(set(AGENT_OPERATIONS) - names)
    assert missing == [], f"имена из AGENT_OPERATIONS без маршрута: {missing}"


async def test_007_fr17_route_names_are_unique_for_scope_check(api_env: ApiEnv) -> None:
    """Гейт сверяет имя маршрута: имя операции агента не должно принадлежать другому маршруту."""
    by_name: dict[str, list[tuple[str, str]]] = {}
    for method, path, name in _api_routes(api_env):
        by_name.setdefault(name, []).append((method, path))
    dup = {n: ops for n, ops in by_name.items() if n in AGENT_OPERATION_NAMES and len(ops) > 1}
    assert dup == {}
    # гейт подключён к приложению (plan §4.7: dependencies=[check_origin, require_agent_scope])
    from app.api.deps import require_agent_scope

    deps = [d.dependency for d in api_env.app.router.dependencies]
    assert require_agent_scope in deps, "require_agent_scope не подключён app-level"


# --- AC-33 / FR-17: обход всех маршрутов вне перечня ------------------------------------------


async def test_007_ac33_every_route_outside_agent_operations_is_forbidden_by_key(
    api_env: ApiEnv,
) -> None:
    """С действующим ``K_ba`` (роль БА, участник P) любой маршрут вне перечня -> 403 forbidden,
    включая ``/auth/login``, ``/health``, ``/auth/logout``, ``/auth/password``, админку, ключи.
    Данные (в т.ч. сессии, ключи, события) не меняются."""
    env = api_env
    w = await make_world007(env)
    routes = [r for r in _api_routes(env) if r[2] not in AGENT_OPERATION_NAMES]
    paths = {path for _, path, _ in routes}
    for must in (LOGIN_URL, HEALTH_URL, LOGOUT_URL, PASSWORD_URL):
        assert must in paths, f"маршрут {must} не найден в обходе"
    assert any("/api-keys" in p for p in paths)
    assert any(p.startswith("/api/v1/admin/users") for p in paths)
    before = await table_digest(env, *DATA_TABLES)

    failures: list[str] = []
    for method, path, name in routes:
        body = _body(method, path, w)
        kwargs: dict[str, Any] = {} if body is None else {"json": body}
        response = await env.client.request(
            method, _concrete(path, w), headers=bearer(w.K_ba.secret), **kwargs
        )
        if response.status_code != 403 or _code(response) != "forbidden":
            failures.append(f"{method} {path} ({name}): {response.status_code} {_code(response)}")
        if response.headers.get_list("set-cookie"):
            failures.append(f"{method} {path} ({name}): Set-Cookie в ответе на запрос по ключу")
    assert failures == []
    assert await table_digest(env, *DATA_TABLES) == before, "данные изменились"


async def test_007_ac33_outside_routes_forbidden_even_with_invalid_or_non_bearer_key(
    api_env: ApiEnv,
) -> None:
    """З-4, plan §4.7: вне перечня ключ не проверяется — недействительный ключ и схема не
    Bearer тоже дают 403 forbidden, а не 401."""
    env = api_env
    w = await make_world007(env)
    routes = [r for r in _api_routes(env) if r[2] not in AGENT_OPERATION_NAMES]
    variants = {
        "мусорный Bearer": {"Authorization": "Bearer not-a-key"},
        "Basic": {"Authorization": "Basic dXNlcjpwYXNz"},
    }
    failures: list[str] = []
    for method, path, name in routes:
        body = _body(method, path, w)
        kwargs: dict[str, Any] = {} if body is None else {"json": body}
        for label, headers in variants.items():
            response = await env.client.request(
                method, _concrete(path, w), headers=headers, **kwargs
            )
            if response.status_code != 403 or _code(response) != "forbidden":
                failures.append(
                    f"{method} {path} ({name}, {label}): {response.status_code} {_code(response)}"
                )
    assert failures == []


async def test_007_ac33_login_with_key_and_valid_password_is_forbidden_without_session(
    api_env: ApiEnv,
) -> None:
    """Вход с действующими учётными данными человека и заголовком ключа -> 403, сессия не
    создана, cookie не выдана (FR-15, FR-17)."""
    env = api_env
    w = await make_world007(env)
    person = await env.new_user(workspace=w.ws, role="user", login="human.pw", password=PW)
    sessions_before = await session_count(env)

    response = await env.client.post(
        LOGIN_URL,
        json={"login": person.login, "password": PW},
        headers=bearer(w.K_ba.secret),
    )

    assert (response.status_code, _code(response)) == (403, "forbidden")
    assert response.headers.get_list("set-cookie") == []
    assert await session_count(env) == sessions_before
    # без ключа тот же вход выполняется: 403 вызван заголовком ключа
    ok = await env.login(person.login, PW)
    assert ok.status_code == 200


async def test_007_ac33_health_with_key_is_forbidden_and_public_without_it(
    api_env: ApiEnv,
) -> None:
    env = api_env
    w = await make_world007(env)
    response = await env.client.get(HEALTH_URL, headers=bearer(w.K_ba.secret))
    assert (response.status_code, _code(response)) == (403, "forbidden")
    plain = await env.client.get(HEALTH_URL)
    assert plain.status_code == 200


async def test_007_ac33_agent_operations_are_not_blocked_by_scope_gate(api_env: ApiEnv) -> None:
    """Маршруты перечня по ``K_ba`` не получают 403 forbidden от гейта перечня (чтение)."""
    env = api_env
    w = await make_world007(env)
    reads = [
        ("GET", "/api/v1/me"),
        ("GET", "/api/v1/projects"),
        ("GET", "/api/v1/me/tasks"),
        ("GET", f"/api/v1/projects/{w.P}/tasks"),
        ("GET", f"/api/v1/tasks/{w.T1}"),
        ("GET", f"/api/v1/tasks/{w.T1}/comments"),
    ]
    statuses = {}
    for method, url in reads:
        response = await env.client.request(method, url, headers=bearer(w.K_ba.secret))
        statuses[(method, url)] = response.status_code
    assert set(statuses.values()) == {200}, statuses
