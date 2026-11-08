"""N12-T02: кто получает уведомления (spec 012 FR-1, FR-3, FR-8; AC-1…AC-4).

Действия — по HTTP, проверка — по таблице ``notification`` (API списка — N12-T03).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, update

from app.domain.notifications.models import Notification
from app.domain.users.models import AppUser
from tests.conftest import ApiEnv
from tests.factories import make_project, make_project_member, make_user, make_workspace


@dataclass
class World:
    env: ApiEnv
    owner: Any  # БА, владелец проекта
    u2: Any
    u3: Any
    u4: Any
    outsider: Any
    project: Any
    tok: dict[str, str]


async def _users(env: ApiEnv) -> World:
    async with env.sessionmaker() as s:
        ws = await make_workspace(s)
        owner = await make_user(s, role="business_admin", workspace=ws)
        u2 = await make_user(s, role="user", workspace=ws)
        u3 = await make_user(s, role="user", workspace=ws)
        u4 = await make_user(s, role="user", workspace=ws)
        outsider = await make_user(s, role="user", workspace=ws)
        project = await make_project(s, workspace_id=ws.id, owner_id=owner.id)
        for u in (u2, u3, u4):
            await make_project_member(s, project_id=project.id, user_id=u.id, workspace_id=ws.id)
        await s.commit()
    tok = {
        "owner": await env.login_ok(owner),
        "u2": await env.login_ok(u2),
        "u3": await env.login_ok(u3),
    }
    return World(env, owner, u2, u3, u4, outsider, project, tok)


async def _notes(env: ApiEnv) -> list[tuple[str, Any]]:
    async with env.sessionmaker() as s:
        rows = (await s.execute(select(Notification.kind, Notification.recipient_id))).all()
    return sorted((r.kind, r.recipient_id) for r in rows)


async def _create_task(w: World, assignee: Any) -> str:
    r = await w.env.client.post(
        f"/api/v1/projects/{w.project.id}/tasks",
        json={
            "title": "Задача",
            "description": "Описание",
            "due_date": "2026-12-01",
            "assignee_id": str(assignee.id),
        },
        headers=w.env.auth(w.tok["owner"]),
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def _patch(w: World, who: str, task_id: str, **body: Any) -> None:
    r = await w.env.client.patch(
        f"/api/v1/tasks/{task_id}", json=body, headers=w.env.auth(w.tok[who])
    )
    assert r.status_code == 200, r.text


async def _comment(w: World, who: str, task_id: str, body: str) -> str:
    r = await w.env.client.post(
        f"/api/v1/tasks/{task_id}/comments", json={"body": body}, headers=w.env.auth(w.tok[who])
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def test_012_ac1_assignment_and_reassignment(api_env: ApiEnv) -> None:
    w = await _users(api_env)
    task = await _create_task(w, w.u2)
    assert await _notes(api_env) == [("assigned", w.u2.id)]
    await _patch(w, "owner", task, assignee_id=str(w.u3.id))
    assert await _notes(api_env) == sorted([("assigned", w.u2.id), ("assigned", w.u3.id)])


async def test_012_ac1_review_requested_once_and_returned(api_env: ApiEnv) -> None:
    w = await _users(api_env)
    task = await _create_task(w, w.u2)
    await _patch(w, "u2", task, status="review")
    # автор задачи и владелец проекта — один человек: одно уведомление (FR-8, Q-5)
    assert ("review_requested", w.owner.id) in await _notes(api_env)
    assert [n for n in await _notes(api_env) if n[0] == "review_requested"] == [
        ("review_requested", w.owner.id)
    ]
    await _patch(w, "owner", task, status="in_progress")
    assert ("review_returned", w.u2.id) in await _notes(api_env)


async def test_012_ac1_board_move_to_review_notifies(api_env: ApiEnv) -> None:
    w = await _users(api_env)
    task = await _create_task(w, w.u2)
    r = await api_env.client.post(
        f"/api/v1/tasks/{task}/move",
        json={"status": "review", "before_task_id": None, "after_task_id": None},
        headers=api_env.auth(w.tok["u2"]),
    )
    assert r.status_code == 204, r.text
    assert ("review_requested", w.owner.id) in await _notes(api_env)


async def test_012_ac1_ac4_comment_and_mention_one_each(api_env: ApiEnv) -> None:
    w = await _users(api_env)
    task = await _create_task(w, w.u2)
    await _comment(w, "u3", task, f"@{w.u2.login} глянь, пожалуйста")
    notes = await _notes(api_env)
    assert ("mentioned", w.u2.id) in notes
    assert ("commented", w.u2.id) not in notes, "упомянутому — одно уведомление (AC-4)"
    assert ("commented", w.owner.id) in notes, "автор задачи — новый комментарий"
    assert all(r != w.u3.id for _k, r in notes), "автор комментария себя не уведомляет"


async def test_012_ac2_mention_only_active_members(api_env: ApiEnv) -> None:
    w = await _users(api_env)
    task = await _create_task(w, w.u2)
    await api_env.execute(update(AppUser).where(AppUser.id == w.u4.id).values(is_blocked=True))
    await _comment(
        w, "u3", task, f"@{w.outsider.login} @{w.u4.login} @{w.u3.login} x@{w.u2.login}.ru"
    )
    notes = await _notes(api_env)
    assert not [n for n in notes if n[0] == "mentioned"]


async def test_012_ac3_edit_notifies_only_new_mentions_and_delete_hides(api_env: ApiEnv) -> None:
    w = await _users(api_env)
    task = await _create_task(w, w.u3)
    cid = await _comment(w, "u2", task, f"@{w.owner.login} привет")
    r = await api_env.client.patch(
        f"/api/v1/comments/{cid}",
        json={"body": f"@{w.owner.login} и @{w.u4.login} привет"},
        headers=api_env.auth(w.tok["u2"]),
    )
    assert r.status_code == 200, r.text
    mentioned = [n for n in await _notes(api_env) if n[0] == "mentioned"]
    assert sorted(mentioned) == sorted([("mentioned", w.owner.id), ("mentioned", w.u4.id)])
