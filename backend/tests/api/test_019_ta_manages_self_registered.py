"""R8-T14: управление ТА самостоятельно зарегистрированными учётными записями (spec 019: AC-22,
AC-26, AC-33; plan §6, ADR-0019, ADR-0013).

ТА видит учётную запись без роли с именами и признаком ``self_registered``, блокирует её, сбрасывает
пароль и назначает каждую из трёх ролей. ТА создаёт учётную запись с именами, одноразовым паролем
и обязательной сменой пароля. Регистрация идёт через публичный API (заявка -> ссылка ->
подтверждение), SMTP подменён ``RecordingMailer``.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio
from sqlalchemy import text

from tests.admin_support import (
    ADMIN_USERS,
    ADMIN_VIEW_FIELDS,
    OTP,
    OTP_FIELD,
    admin_call,
    code_of,
    new_workspace,
    seed,
)

if TYPE_CHECKING:
    from tests.conftest import ApiEnv
    from tests.factories import WorkspaceRow

REQUEST = "/api/v1/auth/registration/request"
CONFIRM = "/api/v1/auth/registration/confirm"
PROJECTS = "/api/v1/projects"
REG_LINK = "https://tracker.example.test/register/confirm#token="
FIRST = "Ирина"
LAST = "Сидорова-Левина"
PW = "Zq7-ta-registration-pw"  # не в списке частых, длиннее 12 символов


@pytest_asyncio.fixture
async def reg_ws(reset_api_env: ApiEnv) -> WorkspaceRow:
    """Ровно одно пространство на тест (RG-9)."""
    return await new_workspace(reset_api_env)


async def _register(env: ApiEnv, n: int) -> tuple[uuid.UUID, str]:
    """Заявка и подтверждение по ссылке из письма; возвращает (id, логин, выбранный сервером)."""
    email = f"ta.reg{n}@example.test"
    accepted = await env.client.post(
        REQUEST,
        json={
            "email": email,
            "first_name": FIRST,
            "last_name": LAST,
            "password": PW,
        },
    )
    assert accepted.status_code == 200, accepted.text
    mail = env.app.state.mailer.sent[-1]
    assert mail.to == email
    token = mail.body.split(REG_LINK, 1)[1].split()[0]
    confirmed = await env.client.post(CONFIRM, json={"token": token})
    assert confirmed.status_code == 200, confirmed.text
    login = confirmed.json()["login"]  # v0.5: логин выбирает сервер
    rows = await env.execute(text("SELECT id FROM app_user WHERE email = :e").bindparams(e=email))
    assert rows is not None and len(rows) == 1
    return rows[0][0], login


async def _admin_view(env: ApiEnv, token: str, user_id: Any) -> dict[str, Any]:
    """Строка ``GET /admin/users`` для ``user_id`` (список целиком, одна запись)."""
    response = await env.client.get(ADMIN_USERS, params={"page_size": 100}, headers=env.auth(token))
    assert response.status_code == 200, response.text
    found = [item for item in response.json()["items"] if item["id"] == str(user_id)]
    assert len(found) == 1
    return found[0]


async def test_019_ac22_ta_list_shows_self_registered_with_names_and_flag(
    reset_api_env: ApiEnv, reg_ws: WorkspaceRow
) -> None:
    env = reset_api_env
    _, (ta_token,) = await seed(env, reg_ws, "tech_admin", login="ta.lister")
    user_id, login = await _register(env, 1)
    created = await env.client.post(
        ADMIN_USERS,
        json={"login": "Ta.Created", "first_name": "Павел", "last_name": "Громов", OTP_FIELD: OTP},
        headers=env.auth(ta_token),
    )
    assert created.status_code == 201, created.text

    view = await _admin_view(env, ta_token, user_id)
    assert set(view) == ADMIN_VIEW_FIELDS
    assert view["login"] == login
    assert (view["first_name"], view["last_name"]) == (FIRST, LAST)
    assert view["self_registered"] is True
    assert view["email"] == "ta.reg1@example.test"
    assert view["role"] == "user"  # роль назначена при подтверждении (2026-11-11)
    assert view["is_blocked"] is False
    assert view["must_change_password"] is False

    # отличие от учётной записи, созданной ТА: признак ``self_registered`` у неё ложный
    created_view = await _admin_view(env, ta_token, created.json()["id"])
    assert created_view["self_registered"] is False


@pytest.mark.parametrize(
    ("role_action", "expected_role"),
    [("role_user", "user"), ("role_ba", "business_admin"), ("role_ta", "tech_admin")],
)
async def test_019_ac22_ta_blocks_resets_and_assigns_each_role(
    reset_api_env: ApiEnv, reg_ws: WorkspaceRow, role_action: str, expected_role: str
) -> None:
    env = reset_api_env
    _, (ta_token,) = await seed(env, reg_ws, "tech_admin", login="ta.actor")
    user_id, login = await _register(env, 2)

    # блокировка: вход отклоняется, в списке виден флаг; снятие блокировки
    blocked = await admin_call(env, ta_token, "block", user_id)
    assert blocked.status_code == 204, blocked.text
    assert (await _admin_view(env, ta_token, user_id))["is_blocked"] is True
    refused = await env.login(login, PW)
    assert (refused.status_code, code_of(refused)) == (401, "invalid_credentials")
    unblocked = await admin_call(env, ta_token, "unblock", user_id)
    assert unblocked.status_code == 204, unblocked.text
    assert (await _admin_view(env, ta_token, user_id))["is_blocked"] is False

    # сброс пароля администратором: одноразовый пароль входит и требует смены
    reset = await admin_call(env, ta_token, "reset", user_id)
    assert reset.status_code == 204, reset.text
    once = await env.login(login, OTP)
    assert once.status_code == 200, once.text
    assert once.json()["user"]["must_change_password"] is True

    # назначение каждой из трёх ролей (ADR-0013: назначает ТА)
    assigned = await admin_call(env, ta_token, role_action, user_id)
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["role"] == expected_role
    assert (await _admin_view(env, ta_token, user_id))["role"] == expected_role


async def test_019_self_registered_works_at_once_and_ta_can_change_the_role(
    reset_api_env: ApiEnv, reg_ws: WorkspaceRow
) -> None:
    """AC-25, AC-26: сразу роль «Пользователь» и /projects 200; ТА может сменить роль."""
    env = reset_api_env
    _, (ta_token,) = await seed(env, reg_ws, "tech_admin", login="ta.role")
    user_id, login = await _register(env, 3)

    entered = await env.login(login, PW)
    assert entered.status_code == 200, entered.text
    assert entered.json()["user"]["role"] == "user"
    session = env.token_from(entered)
    assert session
    projects = await env.client.get(PROJECTS, headers=env.auth(session))
    assert projects.status_code == 200, projects.text
    me = await env.me(session)
    assert me.status_code == 200, me.text
    assert me.json()["role"] == "user"
    assert me.json()["first_name"] == FIRST and me.json()["last_name"] == LAST

    promoted = await admin_call(env, ta_token, "role_ba", user_id)  # ТА может сменить роль
    assert promoted.status_code == 200, promoted.text
    assert (await env.me(session)).json()["role"] == "business_admin"  # та же сессия (FR-67)


async def test_019_ac33_ta_creates_account_with_names_one_time_password_and_must_change(
    reset_api_env: ApiEnv, reg_ws: WorkspaceRow
) -> None:
    """AC-33, AC-22: ТА создаёт запись с именами и одноразовым паролем; смена обязательна."""
    env = reset_api_env
    _, (ta_token,) = await seed(env, reg_ws, "tech_admin", login="ta.creator")
    created = await env.client.post(
        ADMIN_USERS,
        json={"login": "Ta.Onetime", "first_name": FIRST, "last_name": LAST, OTP_FIELD: OTP},
        headers=env.auth(ta_token),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert (body["first_name"], body["last_name"]) == (FIRST, LAST)
    assert body["must_change_password"] is True
    assert body["self_registered"] is False
    assert body["role"] is None

    rows = await env.execute(
        text(
            "SELECT first_name, last_name, must_change_password, self_registered "
            "FROM app_user WHERE id = :u"
        ).bindparams(u=uuid.UUID(body["id"]))
    )
    assert rows is not None
    assert tuple(rows[0]) == (FIRST, LAST, True, False)

    entered = await env.login("Ta.Onetime", OTP)
    assert entered.status_code == 200, entered.text
    assert entered.json()["user"]["must_change_password"] is True
