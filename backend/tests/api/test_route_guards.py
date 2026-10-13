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

import re
import uuid
from collections.abc import Iterator
from typing import Annotated, Any

import httpx
import pytest
from fastapi import Depends
from pydantic import BaseModel, Field

from tests.conftest import ApiEnv

PW = "Sup3r-secret-Pa55phrase-xyz"
LOGIN_URL = "/api/v1/auth/login"
LOGOUT_URL = "/api/v1/auth/logout"
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


# --- sanity: uuid в обходе -----------------------------------------------------------------------


def test_helper_concrete_replaces_all_path_params() -> None:
    assert uuid.UUID(_concrete("/api/v1/x/{item_id}").rsplit("/", 1)[1])
