"""Общая фикстура spec 002 §6 для API-тестов критериев AC-11...AC-19 (R3-T01). Не тест-модуль.

``make_world_002(env)`` строит одно рабочее пространство:

* ``ta1``, ``ta2`` - активные ТА; ``ba.owner`` - БА, владелец и участник P; ``ba.member`` - БА,
  участник P без своих задач; ``ba.out`` - БА, не участник P; ``u1``, ``u2`` - П, участники P;
  ``u3`` - П, не участник P;
* задачи P: T1 (автор ``ba.owner``, исполнитель ``u1``) с подзадачей T1.1 (автор ``ba.owner``,
  исполнитель ``u2``); T3 (автор и исполнитель ``u1``) с подзадачей T3.1 (автор и исполнитель
  ``u1``); комментарии c1 (автор ``u1``) и c2 (автор ``u2``) к T1, c3 (автор ``u1``) к T3;
* токены действующих сессий всех пользователей.

Параметры дополняют фикстуру: ``with_p2`` (AC-12: проект P2 с T5, подзадачей и комментарием),
``with_ba_extra`` (AC-17: ``ba.blocked`` - участник P, заблокирован; ``ba.free`` - не участник),
``with_nr`` (AC-18: ``nr`` - участник P, роль снята через ``PUT /admin/users/{id}/role`` от
``ta1``), ``owner_role`` (AC-18: роль ``ba.owner`` после создания - ``None``/``"user"``/
``"tech_admin"``/``...``, смена тем же API; по умолчанию не меняется).

Данные тестов фиксируются коммитами отдельных сессий, как в ``projects_api_support``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from tests.admin_support import ADMIN_USERS, new_workspace, seed
from tests.factories import make_comment, make_project, make_project_member, make_task
from tests.projects_api_support import (
    Person,
    add_project,
    code_of,
    error,
    event_count,
    members_url,
    pj,
    rows,
    send,
    set_blocked,
)

if TYPE_CHECKING:
    from tests.conftest import ApiEnv
    from tests.factories import WorkspaceRow

__all__ = [
    "World002",
    "code_of",
    "error",
    "make_world_002",
    "members_url",
    "owner_url",
    "pj",
    "send",
    "snapshot",
]

_UNCHANGED: Any = object()


@dataclass
class World002:
    ws: WorkspaceRow
    people: dict[str, Person]
    project_id: uuid.UUID
    tasks: dict[str, uuid.UUID] = field(default_factory=dict)  # T1, T1.1, T3, T3.1 (+ T5, T5.1)
    comments: dict[str, uuid.UUID] = field(default_factory=dict)  # c1, c2, c3 (+ c5)
    p2_id: uuid.UUID | None = None

    def tok(self, who: str) -> str:
        return self.people[who].token

    def uid(self, who: str) -> uuid.UUID:
        return self.people[who].user.id

    def login(self, who: str) -> str:
        return self.people[who].user.login


def owner_url(project_id: uuid.UUID | str) -> str:
    return f"{pj(project_id)}/owner"


async def set_role_via_api(env: ApiEnv, w: World002, who: str, role: str | None) -> None:
    """Смена роли ``who`` через ``PUT /admin/users/{id}/role`` от ``ta1`` (AC-18)."""
    r = await send(env, w.tok("ta1"), "PUT", f"{ADMIN_USERS}/{w.uid(who)}/role", {"role": role})
    assert r.status_code == 200, r.text


async def make_world_002(
    env: ApiEnv,
    *,
    with_p2: bool = False,
    with_ba_extra: bool = False,
    with_nr: bool = False,
    owner_role: Any = _UNCHANGED,
) -> World002:
    ws = await new_workspace(env)
    spec: list[tuple[str, str]] = [
        ("ta1", "tech_admin"),
        ("ta2", "tech_admin"),
        ("ba.owner", "business_admin"),
        ("ba.member", "business_admin"),
        ("ba.out", "business_admin"),
        ("u1", "user"),
        ("u2", "user"),
        ("u3", "user"),
    ]
    people: dict[str, Person] = {}
    for name, role in spec:
        user, (token,) = await seed(env, ws, role, login=f"w002.{name}")
        people[name] = Person(user, token)
    if with_ba_extra:
        user, (token,) = await seed(env, ws, "business_admin", login="w002.ba.blocked")
        people["ba.blocked"] = Person(user, token)
        user, (token,) = await seed(env, ws, "business_admin", login="w002.ba.free")
        people["ba.free"] = Person(user, token)
    if with_nr:
        user, (token,) = await seed(env, ws, "business_admin", login="w002.nr")
        people["nr"] = Person(user, token)

    members = ["ba.member", "u1", "u2"]
    if with_ba_extra:
        members.append("ba.blocked")
    if with_nr:
        members.append("nr")
    project_id = await add_project(
        env,
        ws,
        people["ba.owner"].user,
        name="P",
        members=members,
        people=people,
    )
    w = World002(ws=ws, people=people, project_id=project_id)

    owner, u1, u2 = w.uid("ba.owner"), w.uid("u1"), w.uid("u2")
    async with env.sessionmaker() as session:
        t1 = await make_task(
            session,
            project_id=project_id,
            workspace_id=ws.id,
            created_by=owner,
            assignee_id=u1,
            title="T1",
            position=1024,
        )
        t11 = await make_task(
            session,
            project_id=project_id,
            workspace_id=ws.id,
            created_by=owner,
            assignee_id=u2,
            parent_id=t1.id,
            title="T1.1",
        )
        t3 = await make_task(
            session,
            project_id=project_id,
            workspace_id=ws.id,
            created_by=u1,
            assignee_id=u1,
            title="T3",
            position=2048,
        )
        t31 = await make_task(
            session,
            project_id=project_id,
            workspace_id=ws.id,
            created_by=u1,
            assignee_id=u1,
            parent_id=t3.id,
            title="T3.1",
        )
        c1 = await make_comment(session, task_id=t1.id, workspace_id=ws.id, created_by=u1)
        c2 = await make_comment(session, task_id=t1.id, workspace_id=ws.id, created_by=u2)
        c3 = await make_comment(session, task_id=t3.id, workspace_id=ws.id, created_by=u1)
        w.tasks = {"T1": t1.id, "T1.1": t11.id, "T3": t3.id, "T3.1": t31.id}
        w.comments = {"c1": c1.id, "c2": c2.id, "c3": c3.id}
        if with_p2:
            p2 = await make_project(session, workspace_id=ws.id, owner_id=owner, name="P2")
            for user_id in (owner, u1):
                await make_project_member(
                    session,
                    project_id=p2.id,
                    user_id=user_id,
                    workspace_id=ws.id,
                    created_by=owner,
                )
            t5 = await make_task(
                session,
                project_id=p2.id,
                workspace_id=ws.id,
                created_by=owner,
                assignee_id=u1,
                title="T5",
            )
            t51 = await make_task(
                session,
                project_id=p2.id,
                workspace_id=ws.id,
                created_by=owner,
                assignee_id=u1,
                parent_id=t5.id,
                title="T5.1",
            )
            c5 = await make_comment(session, task_id=t5.id, workspace_id=ws.id, created_by=u1)
            w.p2_id = p2.id
            w.tasks.update({"T5": t5.id, "T5.1": t51.id})
            w.comments["c5"] = c5.id
        await session.commit()

    if with_ba_extra:
        await set_blocked(env, w.uid("ba.blocked"))
    if with_nr:
        await set_role_via_api(env, w, "nr", None)
    if owner_role is not _UNCHANGED:
        await set_role_via_api(env, w, "ba.owner", owner_role)
    return w


async def snapshot(env: ApiEnv, w: World002) -> dict[str, Any]:
    """Состояние данных для проверки «данные не изменены, новых записей журнала нет»."""
    project = await rows(
        env,
        "SELECT name, description, owner_id, deleted_at FROM project WHERE id = :p",
        p=w.project_id,
    )
    members = await rows(
        env, "SELECT user_id FROM project_member WHERE project_id = :p", p=w.project_id
    )
    tasks = await rows(
        env,
        "SELECT id, parent_id, title, description, status, priority, due_date, assignee_id, "
        "deleted_at FROM task WHERE project_id = :p ORDER BY title, id",
        p=w.project_id,
    )
    comments = await rows(
        env,
        "SELECT c.id, c.body, c.deleted_at FROM comment c JOIN task t ON t.id = c.task_id "
        "WHERE t.project_id = :p ORDER BY c.id",
        p=w.project_id,
    )
    return {
        "project": [tuple(r) for r in project],
        "members": sorted(str(r[0]) for r in members),
        "tasks": [tuple(r) for r in tasks],
        "comments": [tuple(r) for r in comments],
        "events": await event_count(env, w.ws.id),
    }
