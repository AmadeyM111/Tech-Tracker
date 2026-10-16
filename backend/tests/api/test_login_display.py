"""T96: отображаемый логин в проектах, участниках, задачах, комментариях и журнале (FR-73a, D-66).

AC-129 (сценарий целиком через API: ``Mixed.Admin`` создаёт учётные записи ``Ivanov.Petr``,
``Kuznetsov.Oleg``, ``Sidorova.Anna`` и назначает роли; ``Ivanov.Petr`` ведёт проект, задачу и
комментарий; затем передача владения и журнал), OI-129 а) (порядок участников проекта: по
нормализованному логину без учёта регистра); plan §11.12.4, §11.12.8.

Во всех ответах поле ``login`` несёт написание при создании (``UserRef``, ``AuditActor``); ни
один ответ не должен содержать строчный вариант логина с другим регистром (проверка по тексту
ответа). Имена полей контракта не меняются.
"""

from __future__ import annotations

from typing import Any

import httpx

from tests.admin_support import ADMIN_USERS, admin_in_new_workspace, new_workspace, seed
from tests.conftest import ApiEnv
from tests.projects_api_support import (
    AUDIT,
    PROJECTS,
    Person,
    add_project,
    members_url,
    pj,
)

MIXED = "Mixed.Admin"
IVANOV = "Ivanov.Petr"
KUZNETSOV = "Kuznetsov.Oleg"
SIDOROVA = "Sidorova.Anna"
LOWER_VARIANTS = ("mixed.admin", "ivanov.petr", "kuznetsov.oleg", "sidorova.anna")

MIXED_PW = "Mixed-Admin-Pa55phrase-1"
OTP = "Tmp-Pa55phrase-xyz-777"
FINAL_PW = {
    IVANOV: "Ivanov-final-Pa55phrase-2",
    KUZNETSOV: "Kuznetsov-final-Pa55phrase-3",
    SIDOROVA: "Sidorova-final-Pa55phrase-4",
}


def _no_lowercase_variants(response: httpx.Response) -> None:
    """В теле нет строчных вариантов логинов: ключ нигде не должен «протекать» наружу."""
    for variant in LOWER_VARIANTS:
        assert variant not in response.text, f"в ответе строчный логин {variant}: {response.text}"


async def _get(env: ApiEnv, token: str, url: str, **params: Any) -> Any:
    response = await env.client.get(url, params=params, headers=env.auth(token))
    assert response.status_code == 200, f"{url}: {response.status_code} {response.text}"
    _no_lowercase_variants(response)
    return response.json()


async def _post(env: ApiEnv, token: str, url: str, body: dict[str, Any]) -> Any:
    response = await env.client.post(url, json=body, headers=env.auth(token))
    assert response.status_code in (200, 201, 204), f"{url}: {response.status_code} {response.text}"
    _no_lowercase_variants(response)
    return response.json() if response.content else None


async def _create_account(env: ApiEnv, admin_token: str, login: str, role: str) -> str:
    """Создаёт учётную запись и назначает роль через API; возвращает id."""
    created = await _post(env, admin_token, ADMIN_USERS, {"login": login, "one_time_password": OTP})
    assert created["login"] == login
    uid = str(created["id"])
    assigned = await env.client.put(
        f"{ADMIN_USERS}/{uid}/role", json={"role": role}, headers=env.auth(admin_token)
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["login"] == login
    return uid


async def _permanent_session(env: ApiEnv, login: str) -> str:
    """Вход с одноразовым паролем, смена на постоянный, повторный вход (логин — строчными)."""
    first = await env.login(login.lower(), OTP)
    assert first.status_code == 200, first.text
    assert first.json()["user"]["login"] == login
    token = env.token_from(first)
    assert token
    changed = await env.client.post(
        "/api/v1/auth/password",
        json={"current_password": OTP, "new_password": FINAL_PW[login]},
        headers=env.auth(token),
    )
    assert changed.status_code == 204, changed.text
    second = await env.login(login.upper(), FINAL_PW[login])
    assert second.status_code == 200, second.text
    assert second.json()["user"]["login"] == login
    assert second.json()["user"]["must_change_password"] is False
    again = env.token_from(second)
    assert again
    return str(again)


async def test_ac129_display_login_is_shown_everywhere_in_projects_tasks_comments_and_audit(
    api_env: ApiEnv,
) -> None:
    env = api_env

    # --- Mixed.Admin (СМ, учётная запись фабрикой) создаёт остальных через API ---
    ws = await new_workspace(env)
    await seed(env, ws, "mixed", login=MIXED, password=MIXED_PW)
    mixed_login = await env.login(MIXED.lower(), MIXED_PW)
    assert mixed_login.status_code == 200, mixed_login.text
    assert mixed_login.json()["user"]["login"] == MIXED
    mixed_token = env.token_from(mixed_login)
    assert mixed_token

    await _create_account(env, mixed_token, IVANOV, "business_admin")
    kuznetsov_id = await _create_account(env, mixed_token, KUZNETSOV, "business_admin")
    sidorova_id = await _create_account(env, mixed_token, SIDOROVA, "user")
    ivanov = await _permanent_session(env, IVANOV)
    kuznetsov = await _permanent_session(env, KUZNETSOV)
    sidorova = await _permanent_session(env, SIDOROVA)

    for token, login in ((mixed_token, MIXED), (ivanov, IVANOV), (sidorova, SIDOROVA)):
        assert (await _get(env, token, "/api/v1/me"))["login"] == login

    # --- Ivanov.Petr: проект, участники, задача с исполнителем, комментарий ---
    project = await _post(env, ivanov, PROJECTS, {"name": "Проект логинов"})
    project_id = project["id"]
    assert project["owner"]["login"] == IVANOV
    for uid in (kuznetsov_id, sidorova_id):
        await _post(env, ivanov, members_url(project_id), {"user_id": uid})
    task = await _post(
        env,
        ivanov,
        f"{PROJECTS}/{project_id}/tasks",
        {"title": "Задача с исполнителем", "assignee_id": sidorova_id},
    )
    task_id = task["id"]
    assert task["assignee"]["login"] == SIDOROVA
    assert task["author"]["login"] == IVANOV
    comment = await _post(env, ivanov, f"/api/v1/tasks/{task_id}/comments", {"body": "Первый"})
    assert comment["author"]["login"] == IVANOV

    # --- чтение участниками: списки и карточки ---
    for token in (ivanov, kuznetsov, sidorova):
        listed = await _get(env, token, PROJECTS)
        item = next(i for i in listed["items"] if i["id"] == project_id)
        assert item["owner"]["login"] == IVANOV

        card = await _get(env, token, pj(project_id))
        assert card["owner"]["login"] == IVANOV

        members = await _get(env, token, members_url(project_id))
        assert [m["user"]["login"] for m in members["items"]] == [IVANOV, KUZNETSOV, SIDOROVA]

        tasks = await _get(env, token, f"{PROJECTS}/{project_id}/tasks")
        assert [t["assignee"]["login"] for t in tasks["items"]] == [SIDOROVA]

        board = await _get(env, token, f"{PROJECTS}/{project_id}/board")
        cards = [c for col in board["columns"] for c in col["tasks"]]
        assert [c["assignee"]["login"] for c in cards] == [SIDOROVA]

        detail = await _get(env, token, f"/api/v1/tasks/{task_id}")
        assert detail["assignee"]["login"] == SIDOROVA
        assert detail["author"]["login"] == IVANOV

        comments = await _get(env, token, f"/api/v1/tasks/{task_id}/comments")
        assert [c["author"]["login"] for c in comments["items"]] == [IVANOV]

    mine = await _get(env, sidorova, "/api/v1/me/tasks")
    assert [t["assignee"]["login"] for t in mine["items"]] == [SIDOROVA]

    # --- справочник пользователей: поиск без учёта регистра, показ в написании ---
    found = await _get(env, ivanov, "/api/v1/users", q="IVANOV")
    assert [u["login"] for u in found["items"]] == [IVANOV]

    # --- передача владения и журнал ---
    transferred = await env.client.put(
        f"{pj(project_id)}/owner", json={"user_id": kuznetsov_id}, headers=env.auth(ivanov)
    )
    assert transferred.status_code == 200, transferred.text
    _no_lowercase_variants(transferred)
    assert transferred.json()["owner"]["login"] == KUZNETSOV
    assert (await _get(env, kuznetsov, pj(project_id)))["owner"]["login"] == KUZNETSOV
    listed = await _get(env, sidorova, PROJECTS)
    assert next(i for i in listed["items"] if i["id"] == project_id)["owner"]["login"] == KUZNETSOV

    audit = await _get(env, mixed_token, AUDIT, page_size=100)
    actors_by_action: dict[str, set[str]] = {}
    for entry in audit["items"]:
        assert entry["actor"]["kind"] == "user"
        actors_by_action.setdefault(entry["action"], set()).add(entry["actor"]["login"])
    assert actors_by_action["user.created"] == {MIXED}
    assert actors_by_action["user.role_assigned"] == {MIXED}
    assert actors_by_action["project.ownership_transferred"] == {IVANOV}
    created = [e for e in audit["items"] if e["action"] == "user.created"]
    assert len(created) == 3


async def test_ac129_admin_account_list_and_card_show_display_logins(api_env: ApiEnv) -> None:
    env = api_env
    ws, _, token = await admin_in_new_workspace(env)
    seeded = [
        (await seed(env, ws, "business_admin", login=IVANOV))[0],
        (await seed(env, ws, "user", login=SIDOROVA))[0],
    ]

    listing = await _get(env, token, ADMIN_USERS, page_size=100)
    by_id = {i["id"]: i["login"] for i in listing["items"]}
    assert by_id[str(seeded[0].id)] == IVANOV
    assert by_id[str(seeded[1].id)] == SIDOROVA
    card = await _get(env, token, f"{ADMIN_USERS}/{seeded[1].id}")
    assert card["login"] == SIDOROVA


async def test_oi129_members_are_ordered_by_normalized_login_ignoring_case(
    api_env: ApiEnv,
) -> None:
    """OI-129 а): ``anna, Boris, ivan, Kirill`` (без пунктуации: порядок не зависит от БД)."""
    env = api_env
    ws = await new_workspace(env)
    owner, (token,) = await seed(env, ws, "business_admin", login="zeta")
    people: dict[str, Person] = {}
    for login in ("Kirill", "ivan", "Boris", "anna"):
        user, _ = await seed(env, ws, "user", login=login, sessions=0)
        people[login] = Person(user, "")
    project_id = await add_project(
        env, ws, owner, name="Порядок", members=list(people), people=people
    )

    members = await _get(env, token, members_url(project_id))

    assert [m["user"]["login"] for m in members["items"]] == [
        "anna",
        "Boris",
        "ivan",
        "Kirill",
        "zeta",
    ]
