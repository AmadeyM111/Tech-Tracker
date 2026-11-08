"""N12-T03: список, счётчик и прочтение уведомлений (spec 012 FR-5…FR-7; AC-3, AC-6, AC-7)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import delete, update

from app.domain.notifications.models import Notification
from app.domain.projects.models import ProjectMember
from tests.conftest import ApiEnv
from tests.domain.test_012_producer import _comment, _create_task, _users

LIST = "/api/v1/me/notifications"


async def _get(env: ApiEnv, token: str, url: str = LIST) -> Any:
    r = await env.client.get(url, headers=env.auth(token))
    assert r.status_code == 200, r.text
    return r.json()


async def test_012_ac6_list_count_and_read(api_env: ApiEnv) -> None:
    w = await _users(api_env)
    t1 = await _create_task(w, w.u2)
    t2 = await _create_task(w, w.u2)
    body = await _get(api_env, w.tok["u2"])
    assert body["unread"] == 2 and len(body["items"]) == 2
    first = body["items"][0]
    # часы теста стоят: время одинаковое, порядок внутри секунды — по id
    assert {i["task"]["id"] for i in body["items"]} == {t1, t2}
    assert first["kind"] == "assigned" and first["read"] is False
    assert first["actor"]["login"] == w.owner.login
    assert set(first) == {"id", "kind", "task", "project", "actor", "created_at", "read"}
    assert (await _get(api_env, w.tok["u2"], f"{LIST}/unread")) == {"unread": 2}

    r = await api_env.client.post(
        f"{LIST}/read", json={"ids": [first["id"]]}, headers=api_env.auth(w.tok["u2"])
    )
    assert r.status_code == 204
    assert (await _get(api_env, w.tok["u2"], f"{LIST}/unread"))["unread"] == 1
    r = await api_env.client.post(
        f"{LIST}/read", json={"all": True}, headers=api_env.auth(w.tok["u2"])
    )
    assert r.status_code == 204
    after = await _get(api_env, w.tok["u2"])
    assert after["unread"] == 0 and all(i["read"] for i in after["items"])


async def test_012_ac6_foreign_ids_are_ignored(api_env: ApiEnv) -> None:
    w = await _users(api_env)
    await _create_task(w, w.u2)
    theirs = (await _get(api_env, w.tok["u2"]))["items"][0]["id"]
    r = await api_env.client.post(
        f"{LIST}/read", json={"ids": [theirs]}, headers=api_env.auth(w.tok["u3"])
    )
    assert r.status_code == 204
    assert (await _get(api_env, w.tok["u2"], f"{LIST}/unread"))["unread"] == 1


async def test_012_mark_read_validation(api_env: ApiEnv) -> None:
    w = await _users(api_env)
    for body in ({}, {"ids": [], "all": True}, {"all": False}):
        r = await api_env.client.post(f"{LIST}/read", json=body, headers=api_env.auth(w.tok["u2"]))
        assert r.status_code == 422, body


async def test_012_ac7_removed_member_does_not_see_project_notifications(api_env: ApiEnv) -> None:
    w = await _users(api_env)
    await _create_task(w, w.u2)
    await api_env.execute(
        delete(ProjectMember).where(
            ProjectMember.project_id == w.project.id, ProjectMember.user_id == w.u2.id
        )
    )
    body = await _get(api_env, w.tok["u2"])
    assert body["items"] == [] and body["unread"] == 0


async def test_012_ac3_deleted_comment_hides_its_notifications(api_env: ApiEnv) -> None:
    w = await _users(api_env)
    task = await _create_task(w, w.u2)
    cid = await _comment(w, "u3", task, f"@{w.u2.login} глянь")
    kinds = [i["kind"] for i in (await _get(api_env, w.tok["u2"]))["items"]]
    assert "mentioned" in kinds
    r = await api_env.client.delete(f"/api/v1/comments/{cid}", headers=api_env.auth(w.tok["u3"]))
    assert r.status_code == 204, r.text
    kinds = [i["kind"] for i in (await _get(api_env, w.tok["u2"]))["items"]]
    assert "mentioned" not in kinds


async def test_012_only_last_90_days_are_listed(api_env: ApiEnv) -> None:
    w = await _users(api_env)
    await _create_task(w, w.u2)
    await api_env.execute(
        update(Notification).values(created_at=api_env.clock.now() - timedelta(days=91))
    )
    assert (await _get(api_env, w.tok["u2"]))["unread"] == 0


async def test_012_tech_admin_gets_403(api_env: ApiEnv) -> None:
    ta = await api_env.new_user(role="tech_admin")
    token = await api_env.login_ok(ta)
    for url in (LIST, f"{LIST}/unread"):
        assert (await api_env.client.get(url, headers=api_env.auth(token))).status_code == 403
    assert (await api_env.client.get(LIST)).status_code == 401
