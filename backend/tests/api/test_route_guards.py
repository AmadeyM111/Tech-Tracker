"""T13: обход маршрутов и CSRF-проверка Origin (FR-7, AC-4, D-16, plan §4.5 п.5).

Часть FR-7: каждый маршрут ``/api/v1/*``, кроме входа и проверки живости, без действующей
аутентификации даёт 401 ``not_authenticated``. Обход строится по ``app.routes``, поэтому
новые маршруты следующих задач попадают под проверку автоматически.

Порядок проверок для тела запроса (plan §4.5 п.5, уточнение ревью T12): синтаксически битый
JSON даёт 422 раньше 401/403/``origin_mismatch``; валидация полей по схеме — после гейтов.

Имя cookie с префиксом ``__Host-``: plan §4.6/D-13 называют cookie ``gt_session`` и
``Settings.cookie_name`` его задаёт; автоматического переключения имени по ``cookie_secure``
plan не описывает — здесь проверяется только, что имя берётся из настроек (test_auth_login).
"""

import ast
import re
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import timedelta
from typing import Annotated, Any

import httpx
import pytest
import pytest_asyncio
from fastapi import Depends
from pydantic import BaseModel, Field

from tests.conftest import ApiEnv, parse_set_cookie
from tests.db_support import BACKEND_DIR

PW = "Sup3r-secret-Pa55phrase-xyz"
LOGIN_URL = "/api/v1/auth/login"
LOGOUT_URL = "/api/v1/auth/logout"
PASSWORD_URL = "/api/v1/auth/password"
PUBLIC: frozenset[tuple[str, str]] = frozenset(
    {("POST", "/api/v1/auth/login"), ("GET", "/api/v1/health")}
)
SOME_ID = "6f9619ff-8b86-4d11-b42d-00c04fc964ff"


def _code(response: httpx.Response) -> str:
    body = response.json()
    assert isinstance(body, dict)
    return str(body["code"])


def _iter_routes(routes: Any) -> Iterator[Any]:
    """Плоский обход маршрутов; в новых FastAPI ``include_router`` лениво (``_IncludedRouter``)."""
    for route in routes:
        contexts = getattr(route, "effective_route_contexts", None)
        if callable(contexts):
            yield from _iter_routes(contexts())
        elif getattr(route, "methods", None) and hasattr(route, "path"):
            yield route
        elif getattr(route, "routes", None):
            yield from _iter_routes(route.routes)


def _api_operations(env: ApiEnv) -> set[tuple[str, str]]:
    operations: set[tuple[str, str]] = set()
    for route in _iter_routes(env.app.routes):
        if route.path.startswith("/api/v1"):
            for method in set(route.methods) - {"HEAD", "OPTIONS"}:
                operations.add((method, route.path))
    return operations


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", SOME_ID, path)


# --- FR-7: обход маршрутов -------------------------------------------------------------------


async def test_fr7_all_api_routes_except_login_and_health_require_authentication(
    api_env: ApiEnv,
) -> None:
    operations = _api_operations(api_env)
    # обход не должен быть пустым: маршруты T13 присутствуют
    assert operations >= PUBLIC, "нет маршрутов входа/health"
    assert ("POST", LOGOUT_URL) in operations
    assert ("GET", "/api/v1/me") in operations

    failures: list[str] = []
    for method, path in sorted(operations - PUBLIC):
        url = _concrete(path)
        kwargs: dict[str, Any] = {}
        if method in {"POST", "PUT", "PATCH"}:
            kwargs["json"] = {}
        for label, headers in (
            ("без cookie", {}),
            ("мусорная cookie", api_env.auth("not-a-real-token-0123456789abcdef")),
        ):
            response = await api_env.client.request(method, url, headers=headers, **kwargs)
            if response.status_code != 401 or _code(response) != "not_authenticated":
                failures.append(
                    f"{method} {path} ({label}): {response.status_code} {response.text}"
                )
    assert failures == []


async def test_fr7_health_is_public(api_env: ApiEnv) -> None:
    response = await api_env.client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_fr7_login_is_public_and_answers_invalid_credentials_not_not_authenticated(
    api_env: ApiEnv,
) -> None:
    response = await api_env.login("nobody.here", PW)
    assert response.status_code == 401
    assert _code(response) == "invalid_credentials"


async def test_ac4_expired_session_cookie_gives_401_on_every_guarded_route(
    api_env: ApiEnv,
) -> None:
    user = await api_env.new_user(role="mixed", password=PW)
    token = await api_env.login_ok(user)
    await api_env.client.post(LOGOUT_URL, headers=api_env.auth(token))
    for method, path in sorted(_api_operations(api_env) - PUBLIC):
        kwargs: dict[str, Any] = {"json": {}} if method in {"POST", "PUT", "PATCH"} else {}
        response = await api_env.client.request(
            method, _concrete(path), headers=api_env.auth(token), **kwargs
        )
        assert (response.status_code, _code(response)) == (401, "not_authenticated"), (
            method,
            path,
        )


# --- plan §4.5 п.5: порядок проверок и тело запроса -------------------------------------------


class _Body(BaseModel):
    name: str = Field(min_length=3)


@pytest.fixture
def body_routes(api_env: ApiEnv) -> ApiEnv:
    from app.api.deps import get_active_actor, get_actor
    from app.domain.access.roles import Actor

    async def authed(actor: Annotated[Actor, Depends(get_actor)], body: _Body) -> Any:
        return {"name": body.name}

    async def active(actor: Annotated[Actor, Depends(get_active_actor)], body: _Body) -> Any:
        return {"name": body.name}

    api_env.app.add_api_route("/_t/body", authed, methods=["POST"])
    api_env.app.add_api_route("/_t/body-active", active, methods=["POST"])
    return api_env


async def test_plan_4_5_p5_broken_json_without_cookie_is_422_before_401(
    body_routes: ApiEnv,
) -> None:
    response = await body_routes.client.post(
        "/_t/body",
        content=b'{"name": "abc',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert _code(response) == "validation_error"
    assert "abc" not in response.text


async def test_plan_4_5_p5_valid_json_with_wrong_fields_without_cookie_is_401_before_422(
    body_routes: ApiEnv,
) -> None:
    response = await body_routes.client.post("/_t/body", json={"name": "x"})
    assert (response.status_code, _code(response)) == (401, "not_authenticated")
    response = await body_routes.client.post("/_t/body", json={"unexpected": 1})
    assert (response.status_code, _code(response)) == (401, "not_authenticated")


async def test_plan_4_5_p5_gates_precede_field_validation(body_routes: ApiEnv) -> None:
    env = body_routes
    locked = await env.new_user(role="user", password=PW, must_change_password=True)
    token = await env.login_ok(locked)
    response = await env.client.post("/_t/body-active", json={"name": "x"}, headers=env.auth(token))
    assert (response.status_code, _code(response)) == (403, "password_change_required")

    norole = await env.new_user(role=None, password=PW)
    token = await env.login_ok(norole)
    response = await env.client.post("/_t/body-active", json={"name": "x"}, headers=env.auth(token))
    assert (response.status_code, _code(response)) == (403, "no_role")

    ok = await env.new_user(role="user", password=PW)
    token = await env.login_ok(ok)
    response = await env.client.post("/_t/body-active", json={"name": "x"}, headers=env.auth(token))
    assert (response.status_code, _code(response)) == (422, "validation_error")
    response = await env.client.post(
        "/_t/body-active", json={"name": "valid"}, headers=env.auth(token)
    )
    assert response.status_code == 200


async def test_d16_origin_mismatch_precedes_field_validation_and_authentication(
    body_routes: ApiEnv,
) -> None:
    response = await body_routes.client.post(
        "/_t/body", json={"name": "x"}, headers={"Origin": "http://evil.example"}
    )
    assert (response.status_code, _code(response)) == (403, "origin_mismatch")


# --- D-16: check_origin на login/logout ---------------------------------------------------------


async def test_d16_foreign_origin_on_login_is_403_origin_mismatch_and_no_side_effects(
    api_env: ApiEnv,
) -> None:
    user = await api_env.new_user(role="user", password=PW)
    response = await api_env.login(user.login, PW, headers={"Origin": "http://evil.example"})
    assert response.status_code == 403
    assert _code(response) == "origin_mismatch"
    assert api_env.token_from(response) is None
    assert not response.headers.get_list("set-cookie")
    assert await api_env.session_ids(user.id) == []


async def test_d16_foreign_origin_on_login_with_wrong_password_is_403_and_not_counted(
    api_env: ApiEnv,
) -> None:
    user = await api_env.new_user(role="user", password=PW)
    response = await api_env.login(
        user.login, "Wr0ng-Pa55phrase-unique", headers={"Origin": "http://evil.example"}
    )
    assert (response.status_code, _code(response)) == (403, "origin_mismatch")
    assert (await api_env.user_row(user.id)).failed_login_count == 0


async def test_d16_foreign_origin_on_logout_is_403_and_session_survives(api_env: ApiEnv) -> None:
    user = await api_env.new_user(role="user", password=PW)
    token = await api_env.login_ok(user)
    response = await api_env.client.post(
        LOGOUT_URL, headers=api_env.auth(token, Origin="http://evil.example")
    )
    assert (response.status_code, _code(response)) == (403, "origin_mismatch")
    assert (await api_env.me(token)).status_code == 200
    assert len(await api_env.session_ids(user.id)) == 1


async def test_d16_origin_with_other_port_is_403(api_env: ApiEnv) -> None:
    user = await api_env.new_user(role="user", password=PW)
    response = await api_env.login(user.login, PW, headers={"Origin": "http://testserver:8000"})
    assert (response.status_code, _code(response)) == (403, "origin_mismatch")


async def test_d16_same_origin_login_and_logout_pass(api_env: ApiEnv) -> None:
    user = await api_env.new_user(role="user", password=PW)
    response = await api_env.login(user.login, PW, headers={"Origin": "http://testserver"})
    assert response.status_code == 200
    token = api_env.token_from(response)
    assert token
    out = await api_env.client.post(
        LOGOUT_URL, headers=api_env.auth(token, Origin="http://testserver")
    )
    assert out.status_code == 204


async def test_d16_request_without_origin_and_foreign_referer_passes(api_env: ApiEnv) -> None:
    """Проверяется только ``Origin`` (tasks.md T12: ``Referer`` не используется)."""
    user = await api_env.new_user(role="user", password=PW)
    response = await api_env.login(user.login, PW, headers={"Referer": "http://evil.example/page"})
    assert response.status_code == 200


async def test_d16_safe_method_with_foreign_origin_is_not_checked(api_env: ApiEnv) -> None:
    response = await api_env.client.get("/api/v1/health", headers={"Origin": "http://evil.example"})
    assert response.status_code == 200


# --- D-16, заметка ревью T12 (b): схема и строгий разбор Origin ----------------------------------


async def test_t12_review_b_origin_scheme_must_match_request_scheme_http_origin_https_request(
    api_env: ApiEnv,
) -> None:
    user = await api_env.new_user(role="user", password=PW)
    response = await api_env.client.post(
        "https://testserver" + LOGIN_URL,
        json={"login": user.login, "password": PW},
        headers={"Origin": "http://testserver"},
    )
    assert (response.status_code, _code(response)) == (403, "origin_mismatch")
    assert api_env.token_from(response) is None


async def test_t12_review_b_origin_scheme_must_match_request_scheme_https_origin_http_request(
    api_env: ApiEnv,
) -> None:
    user = await api_env.new_user(role="user", password=PW)
    response = await api_env.client.post(
        "http://testserver" + LOGIN_URL,
        json={"login": user.login, "password": PW},
        headers={"Origin": "https://testserver"},
    )
    assert (response.status_code, _code(response)) == (403, "origin_mismatch")


async def test_t12_review_b_matching_https_origin_passes(api_env: ApiEnv) -> None:
    user = await api_env.new_user(role="user", password=PW)
    for origin in ("https://testserver", "https://testserver:443"):
        response = await api_env.client.post(
            "https://testserver" + LOGIN_URL,
            json={"login": user.login, "password": PW},
            headers={"Origin": origin},
        )
        assert response.status_code == 200, origin


async def test_t12_review_b_nonstandard_port_requires_port_in_origin(api_env: ApiEnv) -> None:
    user = await api_env.new_user(role="user", password=PW)
    url = "https://testserver:8443" + LOGIN_URL
    payload = {"login": user.login, "password": PW}
    ok = await api_env.client.post(url, json=payload, headers={"Origin": "https://testserver:8443"})
    assert ok.status_code == 200
    bad = await api_env.client.post(url, json=payload, headers={"Origin": "https://testserver"})
    assert (bad.status_code, _code(bad)) == (403, "origin_mismatch")


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example@testserver",  # userinfo
        "https://testserver@evil.example",
        "https://testserver/path",  # Origin не содержит путь
        "https://testserver/",
        "https://testserver?x=1",
        "null",
        "testserver",
        "https://",
        "",
    ],
)
async def test_t12_review_b_malformed_origin_is_403(api_env: ApiEnv, origin: str) -> None:
    user = await api_env.new_user(role="user", password=PW)
    response = await api_env.client.post(
        "https://testserver" + LOGIN_URL,
        json={"login": user.login, "password": PW},
        headers={"Origin": origin},
    )
    assert (response.status_code, _code(response)) == (403, "origin_mismatch")
    assert api_env.token_from(response) is None


# --- T14: FR-55, FR-66 - обход маршрутов при одноразовом пароле и без роли ----------------------


def _body_kwargs(method: str) -> dict[str, Any]:
    return {"json": {}} if method in {"POST", "PUT", "PATCH"} else {}


async def test_fr55_fr66_every_guarded_route_gives_403_for_one_time_password_and_no_role(
    api_env: ApiEnv,
) -> None:
    """Все маршруты, кроме входа, выхода, смены пароля и health, закрыты гейтами 2-3."""
    env = api_env
    operations = _api_operations(env)
    assert ("POST", PASSWORD_URL) in operations
    exempt = PUBLIC | {("POST", LOGOUT_URL), ("POST", PASSWORD_URL)}
    guarded = sorted(operations - exempt)
    assert ("GET", "/api/v1/me") in guarded

    once = await env.new_user(role="user", password=PW, must_change_password=True)
    once_token = await env.login_ok(once)
    norole = await env.new_user(role=None, password=PW)
    norole_token = await env.login_ok(norole)
    both = await env.new_user(role=None, password=PW, must_change_password=True)
    both_token = await env.login_ok(both)

    failures: list[str] = []
    for method, path in guarded:
        for label, token, expected in (
            ("одноразовый пароль", once_token, "password_change_required"),
            ("без роли", norole_token, "no_role"),
            ("оба признака", both_token, "password_change_required"),
        ):
            response = await env.client.request(
                method, _concrete(path), headers=env.auth(token), **_body_kwargs(method)
            )
            if response.status_code != 403 or _code(response) != expected:
                failures.append(
                    f"{method} {path} ({label}): {response.status_code} {response.text}"
                )
    assert failures == []


async def test_fr55_fr66_password_and_logout_are_not_gated_by_one_time_password_or_no_role(
    api_env: ApiEnv,
) -> None:
    env = api_env
    for role, must_change in ((None, False), ("user", True), (None, True)):
        user = await env.new_user(role=role, password=PW, must_change_password=must_change)
        token = await env.login_ok(user)
        # гейт не срабатывает: пустое тело даёт 422 валидации, а не 403
        empty = await env.client.post(PASSWORD_URL, json={}, headers=env.auth(token))
        assert (empty.status_code, _code(empty)) == (422, "validation_error"), (role, must_change)
        wrong = await env.client.post(
            PASSWORD_URL,
            json={"current_password": "Wr0ng-Pa55phrase-unique-qq", "new_password": "x" * 20},
            headers=env.auth(token),
        )
        assert (wrong.status_code, _code(wrong)) == (422, "invalid_current_password")
        out = await env.client.post(LOGOUT_URL, headers=env.auth(token))
        assert out.status_code == 204, (role, must_change)
        after = await env.client.post(LOGOUT_URL, headers=env.auth(token))
        assert after.status_code == 401


async def test_fr7_password_route_without_session_is_401_even_with_invalid_body(
    api_env: ApiEnv,
) -> None:
    response = await api_env.client.post(PASSWORD_URL, json={"unexpected": 1})
    assert (response.status_code, _code(response)) == (401, "not_authenticated")


# --- заметки ревью T13 (tasks.md T14) -------------------------------------------------------


@pytest_asyncio.fixture
async def env_custom_absolute(
    settings: Any, fixed_clock: Any, db_sessionmaker: Any
) -> AsyncIterator[ApiEnv]:
    """Приложение с нестандартным абсолютным сроком сессии (2 суток и 30 секунд)."""
    from app.main import create_app
    from tests.conftest import _open_api_env

    custom = settings.model_copy(update={"session_absolute_timeout": timedelta(days=2, seconds=30)})
    application = create_app(custom, clock=fixed_clock)
    async for env in _open_api_env(
        application, custom, fixed_clock, db_sessionmaker, "http://testserver"
    ):
        yield env


async def test_t13_review_login_cookie_max_age_follows_session_absolute_timeout(
    env_custom_absolute: ApiEnv,
) -> None:
    env = env_custom_absolute
    user = await env.new_user(role="user", password=PW)
    response = await env.login(user.login, PW)
    assert response.status_code == 200, response.text
    morsel = parse_set_cookie(response, "gt_session")
    assert morsel is not None
    expected = int(env.settings.session_absolute_timeout.total_seconds())
    assert expected == 2 * 24 * 3600 + 30
    assert int(morsel["max-age"]) == expected
    assert int(morsel["max-age"]) != 604800


def test_t13_review_require_capability_without_arguments_is_rejected() -> None:
    from app.api.deps import require_capability

    with pytest.raises((AssertionError, ValueError)):
        require_capability()


@pytest.mark.parametrize(
    "origins",
    [
        ("http://testserver", "http://testserver"),
        ("http://testserver", "http://evil.example"),
        ("http://evil.example", "http://testserver"),
    ],
)
async def test_t13_review_duplicate_origin_header_is_403(
    api_env: ApiEnv, origins: tuple[str, str]
) -> None:
    env = api_env
    user = await env.new_user(role="user", password=PW)
    headers = [("Origin", origins[0]), ("Origin", origins[1])]
    response = await env.client.post(
        LOGIN_URL, json={"login": user.login, "password": PW}, headers=headers
    )
    assert response.status_code == 403, response.text
    assert _code(response) == "origin_mismatch"
    assert api_env.token_from(response) is None
    assert await env.session_ids(user.id) == []


async def test_t13_review_duplicate_origin_header_on_password_change_is_403(
    api_env: ApiEnv,
) -> None:
    env = api_env
    user = await env.new_user(role="user", password=PW)
    token = await env.login_ok(user)
    headers = [
        ("Cookie", f"{env.cookie_name}={token}"),
        ("Origin", "http://testserver"),
        ("Origin", "http://testserver"),
    ]
    response = await env.client.post(
        PASSWORD_URL,
        json={"current_password": PW, "new_password": "Br4nd-new-Pa55phrase-uvw"},
        headers=headers,
    )
    assert response.status_code == 403, response.text
    assert _code(response) == "origin_mismatch"
    assert (await env.login(user.login, PW)).status_code == 200  # пароль не сменён


def test_t13_review_me_handler_has_no_assert_statement() -> None:
    tree = ast.parse((BACKEND_DIR / "app" / "api" / "v1" / "me.py").read_text(encoding="utf-8"))
    asserts = [node.lineno for node in ast.walk(tree) if isinstance(node, ast.Assert)]
    assert asserts == [], f"assert в me.py (строки {asserts}): под -O проверка исчезнет"


async def test_t13_review_me_handler_rejects_actor_without_role_explicitly(
    api_env: ApiEnv,
) -> None:
    """Прямой вызов обработчика с актором без роли: 403 ``no_role``, а не AssertionError."""
    from app.core.errors import AppError
    from app.domain.access.roles import Actor

    endpoint = next(
        route.endpoint for route in _iter_routes(api_env.app.routes) if route.path == "/api/v1/me"
    )
    actor = Actor(
        user_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        login="user.norole",
        role=None,
        must_change_password=False,
        session_id=b"\x00" * 32,
    )
    with pytest.raises(AppError) as info:
        await endpoint(actor)
    assert info.value.status_code == 403
    assert str(info.value.code) == "no_role"


# --- sanity: uuid в обходе -----------------------------------------------------------------------


def test_helper_concrete_replaces_all_path_params() -> None:
    assert uuid.UUID(_concrete("/api/v1/x/{item_id}").rsplit("/", 1)[1])


# --- T17: каждый маршрут /api/v1/admin/* защищён (FR-42, FR-45a, FR-55, FR-66) ----------------


def _admin_operations(env: ApiEnv) -> set[tuple[str, str]]:
    return {op for op in _api_operations(env) if op[1].startswith("/api/v1/admin/")}


async def test_t17_admin_routes_exist_in_route_walk(api_env: ApiEnv) -> None:
    operations = _admin_operations(api_env)
    assert ("GET", "/api/v1/admin/users") in operations
    assert ("POST", "/api/v1/admin/users") in operations
    assert any(m == "PUT" and p.endswith("/role") for m, p in operations)
    assert len(operations) >= 8


@pytest.mark.parametrize(
    ("role", "extra", "expected"),
    [
        ("business_admin", {}, (403, "forbidden")),
        ("user", {}, (403, "forbidden")),
        (None, {}, (403, "no_role")),
        ("tech_admin", {"must_change_password": True}, (403, "password_change_required")),
        ("mixed", {"must_change_password": True}, (403, "password_change_required")),
    ],
    ids=["business_admin", "user", "no_role", "ta_one_time_password", "mixed_one_time_password"],
)
async def test_t17_every_admin_route_rejects_non_admin_actors(
    api_env: ApiEnv, role: str | None, extra: dict[str, Any], expected: tuple[int, str]
) -> None:
    env = api_env
    # администратор пространства есть, чтобы отказ не объяснялся «пустым» пространством
    await env.new_user(role="tech_admin")
    actor = await env.new_user(role=role, password=PW, **extra)
    login = await env.login(actor.login, PW)
    assert login.status_code == 200, login.text
    token = env.token_from(login)
    assert token

    failures: list[str] = []
    for method, path in sorted(_admin_operations(env)):
        kwargs: dict[str, Any] = {"json": {}} if method in {"POST", "PUT", "PATCH"} else {}
        response = await env.client.request(
            method, _concrete(path), headers=env.auth(token), **kwargs
        )
        if (response.status_code, _code(response)) != expected:
            failures.append(f"{method} {path}: {response.status_code} {response.text}")
    assert failures == []


async def test_t17_every_admin_unsafe_route_rejects_foreign_origin(api_env: ApiEnv) -> None:
    env = api_env
    admin = await env.new_user(role="tech_admin", password=PW)
    token = await env.login_ok(admin)
    failures: list[str] = []
    for method, path in sorted(_admin_operations(env)):
        if method == "GET":
            continue
        response = await env.client.request(
            method,
            _concrete(path),
            headers={**env.auth(token), "Origin": "http://evil.example"},
            json={},
        )
        if (response.status_code, _code(response)) != (403, "origin_mismatch"):
            failures.append(f"{method} {path}: {response.status_code} {response.text}")
    assert failures == []
