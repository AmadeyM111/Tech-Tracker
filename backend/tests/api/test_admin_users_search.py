"""Поиск на странице учётных записей: ``GET /api/v1/admin/users?q=`` (макет ta-accounts-search).

Поиск без учёта регистра по логину, имени, фамилии и email внутри пространства актора. ``q``
обрезается по краям; пустая строка — без фильтра. Лимит длины — 100 символов (422 при
превышении, как у остальных параметров запроса). ``total`` — число найденных записей по всем
страницам, а не размер страницы. Права — как у списка: ``manage_accounts`` (БА и «Пользователь»
получают 403).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from tests.admin_support import ADMIN_USERS, admin_in_new_workspace, code_of, new_workspace, seed
from tests.conftest import ApiEnv

Q_MAX_LENGTH = 100


async def _search(env: ApiEnv, token: str, q: str | None = None, **params: Any) -> httpx.Response:
    query: dict[str, Any] = dict(params)
    if q is not None:
        query["q"] = q
    return await env.client.get(ADMIN_USERS, params=query, headers=env.auth(token))


def _logins(response: httpx.Response) -> list[str]:
    assert response.status_code == 200, response.text
    return [item["login"] for item in response.json()["items"]]


async def _seed_directory(env: ApiEnv, ws: Any) -> None:
    """Четыре записи с разными полями для поиска."""
    await seed(
        env,
        ws,
        "user",
        sessions=0,
        login="ivan.petrov",
        first_name="Иван",
        last_name="Петров",
        email="ivan.petrov@example.com",
    )
    await seed(
        env,
        ws,
        "business_admin",
        sessions=0,
        login="olga.smirnova",
        first_name="Ольга",
        last_name="Смирнова",
        email="olga@example.org",
    )
    await seed(env, ws, None, sessions=0, login="kirill.sokolov", first_name="Кирилл")


# --- поиск по полям -------------------------------------------------------------------------


async def test_search_by_login_finds_only_matching_account(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    await _seed_directory(env, ws)

    assert _logins(await _search(env, token, "petrov")) == ["ivan.petrov"]


async def test_search_by_first_name_finds_account(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    await _seed_directory(env, ws)

    assert _logins(await _search(env, token, "Ольга")) == ["olga.smirnova"]


async def test_search_by_last_name_finds_account(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    await _seed_directory(env, ws)

    assert _logins(await _search(env, token, "Смирн")) == ["olga.smirnova"]


async def test_search_by_email_finds_account_by_part_of_address(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    await _seed_directory(env, ws)

    assert _logins(await _search(env, token, "@example.org")) == ["olga.smirnova"]
    assert _logins(await _search(env, token, "ivan.petrov@")) == ["ivan.petrov"]


async def test_search_matches_any_of_the_four_fields(api_env: ApiEnv) -> None:
    """Один запрос ищет одновременно по логину, имени, фамилии и email (OR, не AND)."""
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    await seed(
        env,
        ws,
        "user",
        sessions=0,
        login="zed.one",
        first_name="Пётр",
        last_name="Зайцев",
        email="zed@corp.test",
    )
    await seed(env, ws, "user", sessions=0, login="other.two", first_name="Ирина")
    await seed(env, ws, "user", sessions=0, login="zedish.three", first_name="Анна")

    # Порядок логинов зависит от collation БД (точка), сравниваем наборы.
    assert sorted(_logins(await _search(env, token, "zed"))) == ["zed.one", "zedish.three"]


# --- регистр, пробелы, пустой запрос --------------------------------------------------------


@pytest.mark.parametrize(
    ("q", "login"),
    [
        ("IVAN", "ivan.petrov"),
        ("Ivan.Petrov", "ivan.petrov"),
        ("ПЕТРОВ", "ivan.petrov"),
        ("иван", "ivan.petrov"),
        ("ОЛЬГА", "olga.smirnova"),
        ("PETROV@EXAMPLE.COM", "ivan.petrov"),
    ],
)
async def test_search_ignores_case_for_latin_and_cyrillic(
    api_env: ApiEnv, q: str, login: str
) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    await _seed_directory(env, ws)

    assert _logins(await _search(env, token, q)) == [login]


@pytest.mark.parametrize("q", ["", "   ", "\t"])
async def test_empty_or_blank_q_means_no_filter(api_env: ApiEnv, q: str) -> None:
    env = api_env
    ws, admin, token = await admin_in_new_workspace(env)
    await _seed_directory(env, ws)

    without = await _search(env, token)
    with_empty = await _search(env, token, q)

    assert with_empty.status_code == 200, with_empty.text
    assert with_empty.json() == without.json()
    assert with_empty.json()["total"] == 4  # администратор + три записи из _seed_directory
    assert str(admin.id) in [item["id"] for item in with_empty.json()["items"]]


async def test_q_is_trimmed_at_the_edges(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    await _seed_directory(env, ws)

    assert _logins(await _search(env, token, "  petrov \t")) == ["ivan.petrov"]


# --- экранирование LIKE ---------------------------------------------------------------------


async def test_underscore_in_q_is_literal_not_wildcard(api_env: ApiEnv) -> None:
    """``_`` в ILIKE — один любой символ; без экранирования ``ivan_`` нашёл бы ``ivanxx``."""
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    await seed(env, ws, "user", sessions=0, login="ivan_x")
    await seed(env, ws, "user", sessions=0, login="ivanxx")

    assert _logins(await _search(env, token, "ivan_")) == ["ivan_x"]


@pytest.mark.parametrize("q", ["%", "%%", "\\"])
async def test_percent_and_backslash_in_q_are_literal(api_env: ApiEnv, q: str) -> None:
    """``%`` без экранирования совпал бы со всеми записями; в логинах этих символов нет."""
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    await _seed_directory(env, ws)

    response = await _search(env, token, q)

    assert response.status_code == 200, response.text
    assert response.json()["items"] == []
    assert response.json()["total"] == 0


async def test_percent_matches_literal_percent_in_email(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    await seed(env, ws, "user", sessions=0, login="pct.user", email="a%b@corp.test")
    await seed(env, ws, "user", sessions=0, login="pct.other", email="axb@corp.test")

    assert _logins(await _search(env, token, "a%b")) == ["pct.user"]


# --- нет совпадений, счётчик, страницы ------------------------------------------------------


async def test_no_matches_is_empty_list_with_total_zero(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    await _seed_directory(env, ws)

    response = await _search(env, token, "zzz")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert body["has_next"] is False


async def test_total_counts_all_matches_not_only_the_page(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    for n in range(3):
        await seed(env, ws, "user", sessions=0, login=f"ivanov.{n}")
    await seed(env, ws, "user", sessions=0, login="petrov.one")

    first = (await _search(env, token, "ivanov", page_size=2)).json()
    second = (await _search(env, token, "ivanov", page=2, page_size=2)).json()

    assert first["total"] == second["total"] == 3
    assert (len(first["items"]), first["has_next"]) == (2, True)
    assert (len(second["items"]), second["has_next"]) == (1, False)
    assert [i["login"] for i in first["items"] + second["items"]] == [
        "ivanov.0",
        "ivanov.1",
        "ivanov.2",
    ]


async def test_total_without_q_is_all_workspace_accounts(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    await _seed_directory(env, ws)

    body = (await _search(env, token, page_size=2)).json()

    assert body["total"] == 4
    assert len(body["items"]) == 2
    assert body["has_next"] is True


async def test_search_results_keep_login_order(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    await seed(env, ws, "user", sessions=0, login="ivan.zeta")
    await seed(env, ws, "user", sessions=0, login="ivan.alpha")

    assert _logins(await _search(env, token, "ivan")) == ["ivan.alpha", "ivan.zeta"]


# --- пространство ---------------------------------------------------------------------------


async def test_search_never_returns_accounts_of_another_workspace(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    await seed(env, ws, "user", sessions=0, login="ivan.local", first_name="Иван")
    foreign = await new_workspace(env)
    await seed(env, foreign, "user", sessions=0, login="ivan.foreign", first_name="Иван")

    body = (await _search(env, token, "иван")).json()

    assert [i["login"] for i in body["items"]] == ["ivan.local"]
    assert body["total"] == 1


# --- длина, NUL, права ----------------------------------------------------------------------


async def test_q_of_100_chars_is_accepted(api_env: ApiEnv) -> None:
    _, _, token = await admin_in_new_workspace(api_env)
    response = await _search(api_env, token, "x" * Q_MAX_LENGTH)
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 0


async def test_q_length_is_checked_after_trim(api_env: ApiEnv) -> None:
    """100 значащих символов с пробелами по краям — допустимо: длина считается после обрезки."""
    _, _, token = await admin_in_new_workspace(api_env)
    response = await _search(api_env, token, "   " + "x" * Q_MAX_LENGTH + "   ")
    assert response.status_code == 200, response.text


async def test_q_longer_than_100_chars_is_422(api_env: ApiEnv) -> None:
    _, _, token = await admin_in_new_workspace(api_env)
    response = await _search(api_env, token, "x" * (Q_MAX_LENGTH + 1))
    assert response.status_code == 422, response.text
    assert code_of(response) == "validation_error"


@pytest.mark.parametrize("q", ["a\x00", "\x00"])
async def test_q_with_nul_is_422(api_env: ApiEnv, q: str) -> None:
    _, _, token = await admin_in_new_workspace(api_env)
    response = await _search(api_env, token, q)
    assert response.status_code == 422, response.text
    assert code_of(response) == "validation_error"


@pytest.mark.parametrize("role", ["business_admin", "user", None])
async def test_search_is_403_for_roles_without_manage_accounts(
    api_env: ApiEnv, role: str | None
) -> None:
    env = api_env
    ws = await new_workspace(env)
    _, (token,) = await seed(env, ws, role)
    await seed(env, ws, "user", sessions=0, login="ivan.petrov")

    response = await _search(env, token, "ivan")

    assert response.status_code == 403, response.text


def test_q_and_total_are_in_openapi_contract(api_env: ApiEnv) -> None:
    schema = api_env.app.openapi()
    operation = schema["paths"][ADMIN_USERS]["get"]
    q = next(p for p in operation["parameters"] if p["name"] == "q")
    variants = q["schema"].get("anyOf", [q["schema"]])
    assert any(v.get("maxLength") == Q_MAX_LENGTH for v in variants), q["schema"]

    ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    page = schema["components"]["schemas"][ref.rsplit("/", 1)[-1]]
    assert "total" in page["properties"], page["properties"]
