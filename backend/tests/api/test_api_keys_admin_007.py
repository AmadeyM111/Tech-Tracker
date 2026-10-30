"""R7-T10: API ключей агента для техадминистратора (007).

AC-6, AC-7 (люди, 422, гейты), AC-8, AC-9, AC-11, AC-12, AC-38, AC-39; FR-5…FR-10, FR-40;
plan §4.6, PD-6.

Контракт (``/api/v1/admin/agents``, гейт ``MANAGE_ACCOUNTS``)::

    GET  /{user_id}/api-keys                  -> 200 Page[ApiKeyInfo] (created_at DESC, id DESC)
    POST /{user_id}/api-keys                  {name, expires_in_days=90} -> 201 {key, secret},
                                              Cache-Control: no-store
    POST /{user_id}/api-keys/{key_id}/revoke  -> 204 (повтор -> 204 без события)

Отзыв — именно ``POST .../revoke`` (plan §4.6, PD-6 отвергает ``DELETE``).
Секрет ключа в сообщениях assert не печатается: булево считается до assert.

Часы не уводятся далеко: сессии ``seed`` созданы на ``FIXED_NOW`` (простой 8 часов), поэтому
сроки считаются от ``env.clock.now()``, а переход в ``expired`` проверяется сдвигом в пределах
часа.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from tests.admin_support import ADMIN_VIEW_FIELDS, code_of, new_workspace, seed
from tests.agents007_support import (
    ADMIN_AGENTS,
    ADMIN_USERS,
    AUDIT,
    CLOCK,
    bearer,
    make_agent,
    make_key,
)
from tests.conftest import FIXED_NOW, ApiEnv
from tests.projects_api_support import ApiWorld, make_api_world, send

KEY_FIELDS = {
    "id",
    "name",
    "created_at",
    "created_by",
    "expires_at",
    "last_used_at",
    "revoked_at",
    "state",
}
SECRET_RE = re.compile(r"gtk_[A-Za-z0-9_-]{43}", re.ASCII)
LEAK_RE = re.compile(r"gtk_[A-Za-z0-9_-]{8,}", re.ASCII)


def keys_url(agent_id: uuid.UUID | str) -> str:
    return f"{ADMIN_AGENTS}/{agent_id}/api-keys"


def revoke_url(agent_id: uuid.UUID | str, key_id: uuid.UUID | str) -> str:
    return f"{ADMIN_AGENTS}/{agent_id}/api-keys/{key_id}/revoke"


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def leaked(secret: str, haystack: str) -> bool:
    windows = [secret[i : i + 8] for i in range(len(secret) - 7)]
    return any(w in haystack for w in windows)


async def _issue(
    env: ApiEnv, token: str | None, agent_id: Any, body: dict[str, Any] | None = None
) -> httpx.Response:
    payload = {"name": "claude-laptop", "expires_in_days": 90} if body is None else body
    response: httpx.Response = await send(env, token, "POST", keys_url(agent_id), payload)
    return response


async def _audit(env: ApiEnv, token: str) -> list[dict[str, Any]]:
    r = await send(env, token, "GET", f"{AUDIT}?page_size=100")
    assert r.status_code == 200, r.text
    assert r.json()["has_next"] is False
    return list(r.json()["items"])


async def _rows(env: ApiEnv, user_id: uuid.UUID) -> list[Any]:
    rows = await env.execute(
        text(
            "SELECT id, workspace_id, name, secret_digest, created_at, created_by, expires_at, "
            "revoked_at, revoked_by, last_used_at FROM api_key WHERE user_id = :u "
            "ORDER BY created_at, id"
        ).bindparams(u=user_id)
    )
    assert rows is not None
    return list(rows)


async def _key_events(env: ApiEnv, ws_id: uuid.UUID, action: str) -> list[Any]:
    rows = await env.execute(
        text(
            "SELECT actor_id, entity_type, entity_id, action, details FROM domain_event "
            "WHERE workspace_id = :w AND action = :a ORDER BY id"
        ).bindparams(w=ws_id, a=action)
    )
    assert rows is not None
    return list(rows)


async def _agent_world(env: ApiEnv) -> tuple[ApiWorld, Any]:
    w = await make_api_world(env)
    agent = await make_agent(env, "agent.u", "user", workspace=w.ws)
    return w, agent


# --- AC-6: выпуск ----------------------------------------------------------------------------


async def test_007_ac6_issue_returns_secret_once_with_no_store(
    api_env: ApiEnv, caplog: pytest.LogCaptureFixture
) -> None:
    env = api_env
    w, agent = await _agent_world(env)
    before = await _audit(env, w.tok("ta"))

    with caplog.at_level(logging.DEBUG):
        r = await _issue(
            env, w.tok("ta"), agent.id, {"name": "claude-laptop", "expires_in_days": 90}
        )

    assert r.status_code == 201, "выпуск не вернул 201"
    assert "no-store" in r.headers.get("cache-control", "").lower()
    body = r.json()
    assert set(body) == {"key", "secret"}
    secret = body["secret"]
    assert SECRET_RE.fullmatch(secret) is not None, "формат секрета"
    key = body["key"]
    assert set(key) == KEY_FIELDS
    assert key["name"] == "claude-laptop"
    assert key["state"] == "active"
    assert key["created_by"]["id"] == str(w.uid("ta"))
    assert key["last_used_at"] is None
    assert key["revoked_at"] is None
    assert parse(key["created_at"]) == env.clock.now()
    assert parse(key["expires_at"]) == env.clock.now() + timedelta(days=90)

    after = await _audit(env, w.tok("ta"))
    seen = {e["id"] for e in before}
    new = [e for e in after if e["id"] not in seen]
    assert [e["action"] for e in new] == ["user.api_key_issued"]
    assert new[0]["actor"]["id"] == str(w.uid("ta"))
    assert new[0]["entity_id"] == str(agent.id)
    assert new[0]["details"]["api_key_id"] == key["id"]
    assert new[0]["details"]["api_key_name"] == "claude-laptop"
    audit_text = str(after)
    assert not leaked(secret, audit_text), "секрет в журнале"

    assert not leaked(secret, caplog.text), "секрет в логе"
    assert not LEAK_RE.search(caplog.text), "ключ gtk_ в логе"


async def test_007_ac6_secret_absent_from_every_later_read(api_env: ApiEnv) -> None:
    env = api_env
    w, agent = await _agent_world(env)
    r = await _issue(env, w.tok("ta"), agent.id)
    assert r.status_code == 201
    secret = r.json()["secret"]
    key_id = r.json()["key"]["id"]

    listing = await send(env, w.tok("ta"), "GET", keys_url(agent.id))
    card = await send(env, w.tok("ta"), "GET", f"{ADMIN_USERS}/{agent.id}")
    accounts = await send(env, w.tok("ta"), "GET", f"{ADMIN_USERS}?page_size=100")
    audit = await send(env, w.tok("ta"), "GET", f"{AUDIT}?page_size=100")
    revoked = await send(env, w.tok("ta"), "POST", revoke_url(agent.id, key_id))

    for resp in (listing, card, accounts, audit, revoked):
        assert resp.status_code in (200, 204)
        assert secret not in resp.text, "секрет в повторном чтении"
        assert not leaked(secret, resp.text), "часть секрета в повторном чтении"
    (item,) = listing.json()["items"]
    assert set(item) == KEY_FIELDS
    assert "secret" not in listing.text
    assert "digest" not in listing.text.lower()
    assert set(card.json()) == ADMIN_VIEW_FIELDS


async def test_007_ac6_secrets_of_two_issues_differ_and_digest_is_sha256(api_env: ApiEnv) -> None:
    env = api_env
    w, agent = await _agent_world(env)

    a = await _issue(env, w.tok("ta"), agent.id, {"name": "a"})
    b = await _issue(env, w.tok("ta"), agent.id, {"name": "b"})

    assert a.status_code == b.status_code == 201
    assert a.json()["secret"] != b.json()["secret"]
    rows = {str(r.id): r for r in await _rows(env, agent.id)}
    for resp in (a, b):
        digest = hashlib.sha256(resp.json()["secret"].encode("ascii")).digest()
        assert bytes(rows[resp.json()["key"]["id"]].secret_digest) == digest


async def test_007_ac39_secret_absent_from_all_tables(api_env: ApiEnv) -> None:
    env = api_env
    w, agent = await _agent_world(env)
    r = await _issue(env, w.tok("ta"), agent.id)
    assert r.status_code == 201
    secret = r.json()["secret"]
    windows = [secret[i : i + 8] for i in range(len(secret) - 7)]
    patterns = ["%" + win.replace("_", "\\_").replace("%", "\\%") + "%" for win in windows]

    tables = await env.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
    assert tables is not None
    names = [t[0] for t in tables]
    assert "api_key" in names
    hits: list[str] = []
    for name in names:
        rows = await env.execute(
            text(f'SELECT count(*) FROM "{name}" x WHERE x::text LIKE ANY(:p)').bindparams(  # noqa: S608
                p=patterns
            )
        )
        assert rows is not None
        if rows[0][0]:
            hits.append(name)
    assert hits == [], f"секрет найден в таблицах: {hits}"
    raw = secret.encode("ascii")
    for row in await _rows(env, agent.id):
        stored = bytes(row.secret_digest)
        assert not any(raw[i : i + 8] in stored for i in range(len(raw) - 7))


async def test_007_ac38_failed_issue_does_not_log_secret_shape(
    api_env: ApiEnv, caplog: pytest.LogCaptureFixture
) -> None:
    env = api_env
    w, agent = await _agent_world(env)
    with caplog.at_level(logging.DEBUG):
        ok = await _issue(env, w.tok("ta"), agent.id)
        lst = await send(env, w.tok("ta"), "GET", keys_url(agent.id))
        rev = await send(env, w.tok("ta"), "POST", revoke_url(agent.id, ok.json()["key"]["id"]))
        bad = await _issue(env, w.tok("ta"), agent.id, {"name": ""})
    assert (ok.status_code, lst.status_code, rev.status_code, bad.status_code) == (
        201,
        200,
        204,
        422,
    )
    assert not LEAK_RE.search(caplog.text), "ключ gtk_ в логе"
    assert not leaked(ok.json()["secret"], caplog.text), "секрет в логе"


# --- AC-6: ключ создан и привязан к агенту ---------------------------------------------------


async def test_007_ac6_row_is_bound_to_agent_workspace_and_creator(api_env: ApiEnv) -> None:
    env = api_env
    w, agent = await _agent_world(env)

    r = await _issue(env, w.tok("ta"), agent.id, {"name": "claude-laptop"})

    assert r.status_code == 201
    (row,) = await _rows(env, agent.id)
    assert str(row.id) == r.json()["key"]["id"]
    assert row.workspace_id == w.ws.id
    assert row.name == "claude-laptop"
    assert row.created_by == w.uid("ta")
    assert row.revoked_at is None
    assert row.last_used_at is None


# --- AC-7: люди, 422, гейты ------------------------------------------------------------------


async def test_007_ac7_issue_for_human_is_422_not_an_agent(api_env: ApiEnv) -> None:
    env = api_env
    w, _ = await _agent_world(env)
    before = await _audit(env, w.tok("ta"))

    r = await _issue(env, w.tok("ta"), w.uid("usr"))

    assert (r.status_code, code_of(r)) == (422, "not_an_agent")
    assert await _rows(env, w.uid("usr")) == []
    assert len(await _audit(env, w.tok("ta"))) == len(before)


async def test_007_ac7_issue_for_blocked_agent_is_422_user_blocked(api_env: ApiEnv) -> None:
    env = api_env
    w = await make_api_world(env)
    blocked = await env.new_user(
        workspace=w.ws, login="agent.blocked", role="user", is_agent=True, blocked=True
    )
    before = await _audit(env, w.tok("ta"))

    r = await _issue(env, w.tok("ta"), blocked.id)

    assert (r.status_code, code_of(r)) == (422, "user_blocked")
    assert await _rows(env, blocked.id) == []
    assert len(await _audit(env, w.tok("ta"))) == len(before)


@pytest.mark.parametrize("name", ["", "x" * 101, "a\x00b"])
async def test_007_ac7_bad_name_is_422_nothing_created(api_env: ApiEnv, name: str) -> None:
    env = api_env
    w, agent = await _agent_world(env)
    before = await _audit(env, w.tok("ta"))

    r = await _issue(env, w.tok("ta"), agent.id, {"name": name, "expires_in_days": 30})

    assert (r.status_code, code_of(r)) == (422, "validation_error")
    assert await _rows(env, agent.id) == []
    assert len(await _audit(env, w.tok("ta"))) == len(before)


@pytest.mark.parametrize("name", ["k", "x" * 100, "Ключ ноутбука"])
async def test_007_ac7_name_boundaries_are_accepted(api_env: ApiEnv, name: str) -> None:
    env = api_env
    w, agent = await _agent_world(env)

    r = await _issue(env, w.tok("ta"), agent.id, {"name": name})

    assert r.status_code == 201
    assert r.json()["key"]["name"] == name


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"expires_in_days": 30},
        {"name": None},
        {"name": 5},
        {"name": "k", "expires_in_days": "30"},
        {"name": "k", "expires_in_days": 1.5},
        {"name": "k", "expires_in_days": None},
        {"name": "k", "user_id": "x"},
        {"name": "k", "secret": "gtk_x"},
    ],
)
async def test_007_ac7_bad_body_is_422(api_env: ApiEnv, body: dict[str, Any]) -> None:
    env = api_env
    w, agent = await _agent_world(env)

    r = await _issue(env, w.tok("ta"), agent.id, body)

    assert (r.status_code, code_of(r)) == (422, "validation_error")
    assert await _rows(env, agent.id) == []


@pytest.mark.parametrize("who", ["ba", "usr"])
async def test_007_ac7_ba_and_user_get_403_no_keys_no_events(api_env: ApiEnv, who: str) -> None:
    env = api_env
    w, agent = await _agent_world(env)
    key = await make_key(env, agent, created_by=await _ta_row(env, w), created_at=env.clock.now())
    before = await _audit(env, w.tok("ta"))

    calls = [
        ("GET", keys_url(agent.id), None),
        ("POST", keys_url(agent.id), {"name": "k"}),
        ("POST", keys_url(agent.id), {}),  # 403 раньше разбора тела
        ("POST", revoke_url(agent.id, key.id), None),
    ]
    for method, url, body in calls:
        r = await send(env, w.tok(who), method, url, body)
        assert (r.status_code, code_of(r)) == (403, "forbidden"), method + " " + url

    rows = await _rows(env, agent.id)
    assert [str(r.id) for r in rows] == [str(key.id)]
    assert rows[0].revoked_at is None
    assert len(await _audit(env, w.tok("ta"))) == len(before)


async def test_007_ac7_agent_with_ba_role_cannot_manage_keys(api_env: ApiEnv) -> None:
    """Агент с ролью ``business_admin`` (сессия добавлена напрямую: вход по паролю агенту закрыт)
    не выпускает, не отзывает и не читает ключи. Вариант «по Bearer-ключу» — R7-T12."""
    env = api_env
    w, agent = await _agent_world(env)
    agent_ba = await make_agent(env, "agent.ba", "business_admin", workspace=w.ws)
    token = await _forge_session(env, agent_ba)
    key = await make_key(env, agent, created_by=await _ta_row(env, w), created_at=env.clock.now())

    for method, url, body in (
        ("GET", keys_url(agent.id), None),
        ("POST", keys_url(agent.id), {"name": "k"}),
        ("POST", revoke_url(agent.id, key.id), None),
    ):
        r = await send(env, token, method, url, body)
        assert (r.status_code, code_of(r)) == (403, "forbidden")
    assert len(await _rows(env, agent.id)) == 1


async def test_007_ac7_user_without_role_gets_403_no_role(api_env: ApiEnv) -> None:
    env = api_env
    w, agent = await _agent_world(env)
    for method, url, body in (
        ("GET", keys_url(agent.id), None),
        ("POST", keys_url(agent.id), {"name": "k"}),
        ("POST", revoke_url(agent.id, uuid.uuid4()), None),
    ):
        r = await send(env, w.tok("norole"), method, url, body)
        assert (r.status_code, code_of(r)) == (403, "no_role")
    assert await _rows(env, agent.id) == []


async def test_007_ac7_ta_with_one_time_password_gets_403(api_env: ApiEnv) -> None:
    env = api_env
    w, agent = await _agent_world(env)
    _, (token,) = await seed(env, w.ws, "tech_admin", must_change_password=True)

    for method, url, body in (
        ("GET", keys_url(agent.id), None),
        ("POST", keys_url(agent.id), {"name": "k"}),
        ("POST", revoke_url(agent.id, uuid.uuid4()), None),
    ):
        r = await send(env, token, method, url, body)
        assert (r.status_code, code_of(r)) == (403, "password_change_required")
    assert await _rows(env, agent.id) == []


async def test_007_ac7_without_cookie_is_401(api_env: ApiEnv) -> None:
    env = api_env
    w, agent = await _agent_world(env)
    for method, url, body in (
        ("GET", keys_url(agent.id), None),
        ("POST", keys_url(agent.id), {"name": "k"}),
        ("POST", revoke_url(agent.id, uuid.uuid4()), None),
    ):
        r = await send(env, None, method, url, body)
        assert (r.status_code, code_of(r)) == (401, "not_authenticated")
    assert await _rows(env, agent.id) == []


async def test_007_ac7_bearer_header_does_not_open_admin_routes_before_t12(
    api_env: ApiEnv,
) -> None:
    """Секрет ключа не даёт доступа к управлению ключами (ни до, ни после R7-T12)."""
    env = api_env
    w, agent = await _agent_world(env)
    key = await make_key(env, agent, created_by=await _ta_row(env, w), created_at=env.clock.now())

    r = await env.client.post(keys_url(agent.id), json={"name": "k"}, headers=bearer(key.secret))

    assert r.status_code in (401, 403)
    assert len(await _rows(env, agent.id)) == 1


async def test_007_ac7_foreign_origin_is_403_origin_mismatch(api_env: ApiEnv) -> None:
    env = api_env
    w, agent = await _agent_world(env)
    key = await make_key(env, agent, created_by=await _ta_row(env, w), created_at=env.clock.now())
    headers = {**env.auth(w.tok("ta")), "Origin": "http://evil.example"}

    issue = await env.client.post(keys_url(agent.id), json={"name": "k"}, headers=headers)
    revoke = await env.client.post(revoke_url(agent.id, key.id), headers=headers)

    for r in (issue, revoke):
        assert (r.status_code, code_of(r)) == (403, "origin_mismatch")
    (row,) = await _rows(env, agent.id)
    assert row.revoked_at is None


# --- 404: чужое ------------------------------------------------------------------------------


async def test_007_fr5_unknown_and_foreign_workspace_agent_is_404(api_env: ApiEnv) -> None:
    env = api_env
    w, agent = await _agent_world(env)
    other_ws = await new_workspace(env)
    foreign = await make_agent(env, "agent.far", "user", workspace=other_ws)
    foreign_ta, _ = await seed(env, other_ws, "tech_admin", login="far.ta")
    foreign_key = await make_key(env, foreign, created_by=foreign_ta, created_at=env.clock.now())
    own = await _issue(env, w.tok("ta"), agent.id)  # свой агент доступен (маршрут существует)
    assert own.status_code == 201

    for target in (uuid.uuid4(), foreign.id):
        for method, url, body in (
            ("GET", keys_url(target), None),
            ("POST", keys_url(target), {"name": "k"}),
            ("POST", revoke_url(target, foreign_key.id), None),
        ):
            r = await send(env, w.tok("ta"), method, url, body)
            assert (r.status_code, code_of(r)) == (404, "not_found"), method
    (row,) = await _rows(env, foreign.id)
    assert row.revoked_at is None
    assert len(await _key_events(env, w.ws.id, "user.api_key_issued")) == 1  # только свой


async def test_007_fr9_revoke_unknown_or_other_agents_key_is_404(api_env: ApiEnv) -> None:
    env = api_env
    w, agent = await _agent_world(env)
    other = await make_agent(env, "agent.o", "user", workspace=w.ws)
    ta = await _ta_row(env, w)
    others_key = await make_key(env, other, created_by=ta, created_at=env.clock.now())
    own = await _issue(env, w.tok("ta"), agent.id)  # маршрут существует
    assert own.status_code == 201

    unknown = await send(env, w.tok("ta"), "POST", revoke_url(agent.id, uuid.uuid4()))
    crossed = await send(env, w.tok("ta"), "POST", revoke_url(agent.id, others_key.id))
    bad_id = await send(env, w.tok("ta"), "POST", revoke_url(agent.id, "not-a-uuid"))

    assert (unknown.status_code, code_of(unknown)) == (404, "not_found")
    assert (crossed.status_code, code_of(crossed)) == (404, "not_found")
    assert bad_id.status_code in (404, 422)
    (row,) = await _rows(env, other.id)
    assert row.revoked_at is None
    assert await _key_events(env, w.ws.id, "user.api_key_revoked") == []


async def test_007_fr5_list_for_human_is_empty_page(api_env: ApiEnv) -> None:
    env = api_env
    w, _ = await _agent_world(env)

    r = await send(env, w.tok("ta"), "GET", keys_url(w.uid("usr")))

    assert r.status_code == 200
    assert r.json()["items"] == []
    assert r.json()["has_next"] is False


# --- AC-8: перечень --------------------------------------------------------------------------


async def test_007_ac8_listing_fields_and_states(api_env: ApiEnv) -> None:
    env = api_env
    w, agent = await _agent_world(env)
    ta = await _ta_row(env, w)
    now = env.clock.now()
    used_at = CLOCK  # 10:00 по Москве = 07:00Z
    active = await make_key(
        env,
        agent,
        created_by=ta,
        name="used",
        created_at=now - timedelta(days=3),
        last_used_at=used_at,
    )
    short = await make_key(
        env,
        agent,
        created_by=ta,
        name="short",
        created_at=now - timedelta(days=2),
        ttl=timedelta(minutes=30) + timedelta(days=2),
    )
    revoked = await make_key(
        env,
        agent,
        created_by=ta,
        name="gone",
        created_at=now - timedelta(days=1),
        revoked_at=now - timedelta(hours=1),
    )

    r = await send(env, w.tok("ta"), "GET", keys_url(agent.id))

    assert r.status_code == 200, "перечень не вернул 200"
    items = r.json()["items"]
    assert [i["name"] for i in items] == ["gone", "short", "used"]  # created_at DESC
    by_id = {i["id"]: i for i in items}
    for i in items:
        assert set(i) == KEY_FIELDS
        assert i["created_by"]["id"] == str(w.uid("ta"))
        assert "secret" not in i and "secret_digest" not in i
    assert by_id[str(active.id)]["state"] == "active"
    assert parse(by_id[str(active.id)]["last_used_at"]) == used_at
    assert by_id[str(short.id)]["state"] == "active"
    assert by_id[str(short.id)]["last_used_at"] is None
    assert by_id[str(revoked.id)]["state"] == "revoked"
    assert by_id[str(revoked.id)]["revoked_at"] is not None
    assert parse(by_id[str(active.id)]["expires_at"]) == now - timedelta(days=3) + timedelta(
        days=90
    )
    assert active.secret not in r.text, "секрет в перечне"

    env.clock.set(FIXED_NOW + timedelta(hours=1))  # срок «short» (+30 мин) прошёл; сессия жива
    later = await send(env, w.tok("ta"), "GET", keys_url(agent.id))
    assert later.status_code == 200
    states = {i["name"]: i["state"] for i in later.json()["items"]}
    assert states == {"used": "active", "short": "expired", "gone": "revoked"}


async def test_007_ac8_expired_by_date_and_revoked_wins_over_expired(api_env: ApiEnv) -> None:
    env = api_env
    w, agent = await _agent_world(env)
    ta = await _ta_row(env, w)
    now = env.clock.now()
    old = now - timedelta(days=200)
    await make_key(env, agent, created_by=ta, name="old", created_at=old)
    await make_key(
        env,
        agent,
        created_by=ta,
        name="old-revoked",
        created_at=old + timedelta(seconds=1),
        revoked_at=old + timedelta(days=1),
    )

    r = await send(env, w.tok("ta"), "GET", keys_url(agent.id))

    states = {i["name"]: i["state"] for i in r.json()["items"]}
    assert states == {"old": "expired", "old-revoked": "revoked"}


async def test_007_ac8_pagination(api_env: ApiEnv) -> None:
    env = api_env
    w, agent = await _agent_world(env)
    ta = await _ta_row(env, w)
    now = env.clock.now()
    for n in range(5):
        await make_key(
            env, agent, created_by=ta, name=f"k{n}", created_at=now - timedelta(hours=10 - n)
        )

    p1 = await send(env, w.tok("ta"), "GET", f"{keys_url(agent.id)}?page=1&page_size=2")
    p2 = await send(env, w.tok("ta"), "GET", f"{keys_url(agent.id)}?page=2&page_size=2")
    p3 = await send(env, w.tok("ta"), "GET", f"{keys_url(agent.id)}?page=3&page_size=2")

    assert [i["name"] for i in p1.json()["items"]] == ["k4", "k3"]
    assert [i["name"] for i in p2.json()["items"]] == ["k2", "k1"]
    assert [i["name"] for i in p3.json()["items"]] == ["k0"]
    assert (p1.json()["has_next"], p2.json()["has_next"], p3.json()["has_next"]) == (
        True,
        True,
        False,
    )
    assert p1.json()["page"] == 1 and p1.json()["page_size"] == 2


@pytest.mark.parametrize("query", ["page=0", "page_size=0", "page_size=101", "page=x"])
async def test_007_ac8_bad_pagination_is_422(api_env: ApiEnv, query: str) -> None:
    env = api_env
    w, agent = await _agent_world(env)

    r = await send(env, w.tok("ta"), "GET", f"{keys_url(agent.id)}?{query}")

    assert (r.status_code, code_of(r)) == (422, "validation_error")


async def test_007_ac8_listing_does_not_cross_agents(api_env: ApiEnv) -> None:
    env = api_env
    w, agent = await _agent_world(env)
    other = await make_agent(env, "agent.o", "user", workspace=w.ws)
    ta = await _ta_row(env, w)
    await make_key(env, other, created_by=ta, name="other", created_at=env.clock.now())
    await make_key(env, agent, created_by=ta, name="mine", created_at=env.clock.now())

    r = await send(env, w.tok("ta"), "GET", keys_url(agent.id))

    assert [i["name"] for i in r.json()["items"]] == ["mine"]


# --- AC-9: отзыв -----------------------------------------------------------------------------


async def test_007_ac9_revoke_is_204_one_event_and_idempotent(api_env: ApiEnv) -> None:
    env = api_env
    w, agent = await _agent_world(env)
    issued = await _issue(env, w.tok("ta"), agent.id, {"name": "claude-laptop"})
    key_id = issued.json()["key"]["id"]
    before = await _audit(env, w.tok("ta"))

    first = await send(env, w.tok("ta"), "POST", revoke_url(agent.id, key_id))

    assert first.status_code == 204
    assert first.content == b""
    after = await _audit(env, w.tok("ta"))
    seen = {e["id"] for e in before}
    new = [e for e in after if e["id"] not in seen]
    assert [e["action"] for e in new] == ["user.api_key_revoked"]
    assert new[0]["actor"]["id"] == str(w.uid("ta"))
    assert new[0]["entity_id"] == str(agent.id)
    assert new[0]["details"]["api_key_id"] == key_id
    (row,) = await _rows(env, agent.id)
    assert row.revoked_at == env.clock.now()
    assert row.revoked_by == w.uid("ta")

    again = await send(env, w.tok("ta"), "POST", revoke_url(agent.id, key_id))

    assert again.status_code == 204
    assert len(await _audit(env, w.tok("ta"))) == len(after)
    assert len(await _key_events(env, w.ws.id, "user.api_key_revoked")) == 1
    (row2,) = await _rows(env, agent.id)
    assert row2.revoked_at == row.revoked_at  # повтор не сдвигает время

    listing = await send(env, w.tok("ta"), "GET", keys_url(agent.id))
    assert [i["state"] for i in listing.json()["items"]] == ["revoked"]


async def test_007_ac9_revoke_expired_key_is_204_without_event(api_env: ApiEnv) -> None:
    env = api_env
    w, agent = await _agent_world(env)
    ta = await _ta_row(env, w)
    old = await make_key(
        env, agent, created_by=ta, created_at=env.clock.now() - timedelta(days=200)
    )

    r = await send(env, w.tok("ta"), "POST", revoke_url(agent.id, old.id))

    assert r.status_code == 204
    assert await _key_events(env, w.ws.id, "user.api_key_revoked") == []
    (row,) = await _rows(env, agent.id)
    assert row.revoked_at is None


async def test_007_ac9_revoke_other_key_leaves_siblings_active(api_env: ApiEnv) -> None:
    env = api_env
    w, agent = await _agent_world(env)
    ta = await _ta_row(env, w)
    k1 = await make_key(env, agent, created_by=ta, name="k1", created_at=env.clock.now())
    k2 = await make_key(env, agent, created_by=ta, name="k2", created_at=env.clock.now())

    r = await send(env, w.tok("ta"), "POST", revoke_url(agent.id, k1.id))

    assert r.status_code == 204
    rows = {str(x.id): x for x in await _rows(env, agent.id)}
    assert rows[str(k1.id)].revoked_at is not None
    assert rows[str(k2.id)].revoked_at is None


# --- AC-11: срок -----------------------------------------------------------------------------


@pytest.mark.parametrize("days", [-1, 0, 366])
async def test_007_ac11_bad_ttl_is_422_nothing_created(api_env: ApiEnv, days: int) -> None:
    env = api_env
    w, agent = await _agent_world(env)
    before = await _audit(env, w.tok("ta"))

    r = await _issue(env, w.tok("ta"), agent.id, {"name": "k", "expires_in_days": days})

    assert (r.status_code, code_of(r)) == (422, "validation_error")
    assert await _rows(env, agent.id) == []
    assert len(await _audit(env, w.tok("ta"))) == len(before)


@pytest.mark.parametrize("days", [1, 365])
async def test_007_ac11_ttl_boundaries_are_accepted(api_env: ApiEnv, days: int) -> None:
    env = api_env
    w, agent = await _agent_world(env)

    r = await _issue(env, w.tok("ta"), agent.id, {"name": "k", "expires_in_days": days})

    assert r.status_code == 201
    assert parse(r.json()["key"]["expires_at"]) == env.clock.now() + timedelta(days=days)


async def test_007_ac11_default_ttl_is_90_days(api_env: ApiEnv) -> None:
    env = api_env
    w, agent = await _agent_world(env)

    r = await send(env, w.tok("ta"), "POST", keys_url(agent.id), {"name": "k"})

    assert r.status_code == 201
    assert parse(r.json()["key"]["expires_at"]) == env.clock.now() + timedelta(days=90)
    (row,) = await _rows(env, agent.id)
    assert row.expires_at == env.clock.now() + timedelta(days=90)


# --- AC-12: лимит ----------------------------------------------------------------------------


async def test_007_ac12_sixth_active_key_is_422_then_revoke_frees_slot(api_env: ApiEnv) -> None:
    env = api_env
    w, agent = await _agent_world(env)
    ta = await _ta_row(env, w)
    now = env.clock.now()
    for n in range(4):
        r = await _issue(env, w.tok("ta"), agent.id, {"name": f"k{n}"})
        assert r.status_code == 201
    # истёкший и отозванный не считаются действующими
    await make_key(env, agent, created_by=ta, name="old", created_at=now - timedelta(days=200))
    await make_key(env, agent, created_by=ta, name="rev", created_at=now, revoked_at=now)
    fifth = await _issue(env, w.tok("ta"), agent.id, {"name": "k4"})
    assert fifth.status_code == 201
    before = await _audit(env, w.tok("ta"))
    count = len(await _rows(env, agent.id))

    sixth = await _issue(env, w.tok("ta"), agent.id, {"name": "k5"})

    assert (sixth.status_code, code_of(sixth)) == (422, "api_key_limit_reached")
    assert "secret" not in sixth.text
    assert len(await _rows(env, agent.id)) == count
    assert len(await _audit(env, w.tok("ta"))) == len(before)

    rv = await send(env, w.tok("ta"), "POST", revoke_url(agent.id, fifth.json()["key"]["id"]))
    assert rv.status_code == 204
    retry = await _issue(env, w.tok("ta"), agent.id, {"name": "k5"})
    assert retry.status_code == 201


async def test_007_ac12_limit_is_per_agent(api_env: ApiEnv) -> None:
    env = api_env
    w, agent = await _agent_world(env)
    other = await make_agent(env, "agent.o", "user", workspace=w.ws)
    for n in range(5):
        assert (await _issue(env, w.tok("ta"), agent.id, {"name": f"k{n}"})).status_code == 201

    r = await _issue(env, w.tok("ta"), other.id, {"name": "first"})

    assert r.status_code == 201


# --- помощники -------------------------------------------------------------------------------


async def _ta_row(env: ApiEnv, w: ApiWorld) -> Any:
    return w.people["ta"].user


async def _forge_session(env: ApiEnv, user: Any) -> str:
    from app.core.secrets import ensure_secret_key
    from app.domain.auth.sessions import SessionStore

    store = SessionStore(
        ensure_secret_key(env.settings),
        idle_timeout=env.settings.session_idle_timeout,
        absolute_timeout=env.settings.session_absolute_timeout,
    )
    async with env.sessionmaker() as session:
        token = await store.create(
            session, user_id=user.id, workspace_id=user.workspace_id, now=FIXED_NOW
        )
        await session.commit()
    return str(token)
