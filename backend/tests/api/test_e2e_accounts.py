"""T32: сквозные API-сценарии AC-2 и AC-64 (приёмка R1.0, замечание 3).

AC-2 (FR-1, FR-4, FR-8, AC-121): ТА создаёт 12 учётных записей и назначает 4 роли по 3;
каждый входит одноразовым паролем, получает 403 ``password_change_required``, меняет пароль,
``/me`` отдаёт назначенную роль; в журнале ровно 24 записи (12 created + 12 role_assigned).

AC-64 (FR-41, FR-12, ADR-0006): один сценарий ТА над учётными записями; на каждое действие
ровно одна запись журнала с автором, временем UTC, действием и затронутым пользователем; ни
одна запись журнала и ни один ответ API не содержат значений паролей.
"""

import json
import uuid
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

import httpx

from tests.admin_support import ADMIN_USERS, OTP_FIELD, admin_in_new_workspace
from tests.conftest import ApiEnv

AUDIT = "/api/v1/admin/audit"
PASSWORD_URL = "/api/v1/auth/password"
ROLES = ["user", "business_admin", "mixed", "tech_admin"]


async def _audit(env: ApiEnv, token: str) -> list[dict[str, Any]]:
    r = await env.client.get(AUDIT, params={"page_size": 100}, headers=env.auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["has_next"] is False
    return list(reversed(body["items"]))  # по возрастанию id


async def test_ac2_ta_creates_12_users_with_4_roles_each_logs_in_and_gets_role(
    api_env: ApiEnv,
) -> None:
    env = api_env
    _, admin, ta_token = await admin_in_new_workspace(env)
    users: list[tuple[str, str, str, str]] = []  # (id, login, otp, role)

    for i in range(12):
        login = f"ac2.user{i:02d}"
        otp = f"Otp-{i:02d}-Pa55phrase-xyz-{uuid.uuid4().hex[:8]}"
        role = ROLES[i % 4]
        created = await env.client.post(
            ADMIN_USERS, json={"login": login, OTP_FIELD: otp}, headers=env.auth(ta_token)
        )
        assert created.status_code == 201, created.text
        assert created.json()["role"] is None
        uid = created.json()["id"]
        assigned = await env.client.put(
            f"{ADMIN_USERS}/{uid}/role", json={"role": role}, headers=env.auth(ta_token)
        )
        assert assigned.status_code == 200, assigned.text
        assert assigned.json()["role"] == role
        users.append((uid, login, otp, role))

    assert Counter(role for *_, role in users) == {r: 3 for r in ROLES}

    for uid, login, otp, role in users:
        response = await env.login(login, otp)
        assert response.status_code == 200, response.text
        token = env.token_from(response)
        assert token
        gated = await env.me(token)
        assert gated.status_code == 403
        assert gated.json()["code"] == "password_change_required"

        new_password = f"New-{login}-Pa55phrase-{uuid.uuid4().hex[:6]}"
        changed = await env.client.post(
            PASSWORD_URL,
            json={"current_password": otp, "new_password": new_password},
            headers=env.auth(token),
        )
        assert changed.status_code == 204, changed.text

        me = await env.me(token)
        assert me.status_code == 200, me.text
        assert me.json()["id"] == uid
        assert me.json()["login"] == login
        assert me.json()["role"] == role
        assert me.json()["must_change_password"] is False

        # новый пароль действует, одноразовый — нет
        assert (await env.login(login, new_password)).status_code == 200
        assert (await env.login(login, otp)).status_code == 401

    entries = await _audit(env, ta_token)
    assert len(entries) == 24, [e["action"] for e in entries]
    assert Counter(e["action"] for e in entries) == {
        "user.created": 12,
        "user.role_assigned": 12,
    }
    assert {e["entity_id"] for e in entries} == {u[0] for u in users}
    assert all(e["actor"]["id"] == str(admin.id) for e in entries)


async def test_ac64_ta_scenario_one_entry_per_action_without_password_values(
    api_env: ApiEnv,
) -> None:
    env = api_env
    _, admin, ta = await admin_in_new_workspace(env)  # ТА меняет свою роль на mixed (админ)
    responses: list[httpx.Response] = []
    otp1, otp2 = "Otp1-Pa55phrase-first-4711", "Otp2-Pa55phrase-reset-4712"
    new_pw = "New-Pa55phrase-chosen-4713"
    login = f"ac64.{uuid.uuid4().hex[:8]}"

    async def act(method: str, url: str, **kwargs: Any) -> httpx.Response:
        r = await env.client.request(method, url, headers=env.auth(ta), **kwargs)
        responses.append(r)
        assert r.status_code in (200, 201, 204), (method, url, r.text)
        return r

    created = await act("POST", ADMIN_USERS, json={"login": login, OTP_FIELD: otp1})
    uid = created.json()["id"]
    base = f"{ADMIN_USERS}/{uid}"
    expected = [("user.created", uid)]

    async def step(action: str, entity: str, method: str, url: str, **kw: Any) -> None:
        await act(method, url, **kw)
        expected.append((action, entity))
        entries = await _audit(env, ta)
        assert [(e["action"], e["entity_id"]) for e in entries] == expected, action

    await step("user.blocked", uid, "POST", f"{base}/block")
    await step("user.unblocked", uid, "POST", f"{base}/unblock")
    await step("user.password_reset", uid, "POST", f"{base}/reset-password", json={OTP_FIELD: otp2})
    await step("user.sessions_revoked", uid, "POST", f"{base}/revoke-sessions")
    await step("user.role_assigned", uid, "PUT", f"{base}/role", json={"role": "user"})
    await step("user.role_changed", uid, "PUT", f"{base}/role", json={"role": "business_admin"})
    await step("user.role_removed", uid, "PUT", f"{base}/role", json={"role": None})
    await step(
        "user.role_changed", str(admin.id), "PUT", f"{ADMIN_USERS}/{admin.id}/role",
        json={"role": "mixed"},
    )  # fmt: skip

    # пользователь входит одноразовым паролем и выбирает свой: действия самого пользователя
    # (смена пароля, вход) в журнал не попадают и значений паролей не раскрывают
    login_resp = await env.login(login, otp2)
    responses.append(login_resp)
    assert login_resp.status_code == 200, login_resp.text
    token = env.token_from(login_resp)
    assert token
    changed = await env.client.post(
        PASSWORD_URL,
        json={"current_password": otp2, "new_password": new_pw},
        headers=env.auth(token),
    )
    responses.append(changed)
    assert changed.status_code == 204, changed.text

    entries = await _audit(env, ta)
    assert len(entries) == len(expected) == 9
    for entry in entries:
        assert entry["entity_type"] == "user"
        assert entry["actor"] == {"kind": "user", "id": str(admin.id), "login": admin.login}
        occurred = datetime.fromisoformat(entry["occurred_at"].replace("Z", "+00:00"))
        assert occurred.utcoffset() == timedelta(0)
        assert entry["entity_id"] in {uid, str(admin.id)}
    listing = await env.client.get(AUDIT, params={"page_size": 100}, headers=env.auth(ta))
    responses.append(listing)

    dump = json.dumps(entries, ensure_ascii=False) + "".join(r.text for r in responses)
    for secret in (otp1, otp2, new_pw):
        assert secret not in dump
    assert "$argon2" not in dump
