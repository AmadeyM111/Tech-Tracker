"""Общие помощники тестов API проектов и участников (T72). Не тест-модуль.

Мир: одно пространство, пользователи всех ролей с действующими сессиями (токены), проект
``project_id`` с владельцем ``ba``; плюс второе пространство (``make_foreign``).
Данные фиксируются отдельными сессиями с ``commit`` (как ``admin_support.seed``).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from tests.admin_support import code_of, new_workspace, seed
from tests.factories import (
    UserRow,
    WorkspaceRow,
    make_comment,
    make_project,
    make_project_member,
    make_task,
)

if TYPE_CHECKING:
    import httpx

    from tests.conftest import ApiEnv

PROJECTS = "/api/v1/projects"
AUDIT = "/api/v1/admin/audit"
SOME_ID = "6f9619ff-8b86-4d11-b42d-00c04fc964ff"

DETAIL_FIELDS = {
    "id",
    "name",
    "description",
    "owner",
    "task_count",
    "is_member",
    "created_at",
    "updated_at",
    "permissions",
}
PERMISSION_FIELDS = {"manage", "manage_members", "create_task", "remove_self"}
LIST_ITEM_FIELDS = {"id", "name", "owner", "task_count"}
MEMBER_FIELDS = {"user", "role", "is_blocked", "is_owner"}
PAGE_FIELDS = {"items", "page", "page_size", "has_next"}
USER_REF_FIELDS = {"id", "login"}

NAME_255 = "Я" * 255
DESC_10000 = "д" * 10_000

__all__ = [
    "PROJECTS",
    "ApiWorld",
    "Person",
    "code_of",
    "make_api_world",
    "make_foreign",
    "send",
]


@dataclass
class Person:
    user: UserRow
    token: str


@dataclass
class ApiWorld:
    """Роли: ``ta``, ``sm`` (СМ, не участник), ``sm_m`` (СМ, участник), ``ba`` (владелец),
    ``ba2`` (БА, участник), ``ba3`` (БА, не участник), ``usr`` (П, участник), ``usr2`` (П, не
    участник), ``norole`` (без роли), ``otp`` (П с одноразовым паролем, не участник),
    ``blocked`` (П, заблокирован, не участник)."""

    ws: WorkspaceRow
    people: dict[str, Person]
    project_id: uuid.UUID
    project_name: str = "Основной"
    extra: dict[str, Any] = field(default_factory=dict)

    def tok(self, who: str) -> str:
        return self.people[who].token

    def uid(self, who: str) -> uuid.UUID:
        return self.people[who].user.id

    def login(self, who: str) -> str:
        return self.people[who].user.login


_SPEC: list[tuple[str, str | None, dict[str, Any]]] = [
    ("ta", "tech_admin", {}),
    ("sm", "mixed", {}),
    ("sm_m", "mixed", {}),
    ("ba", "business_admin", {}),
    ("ba2", "business_admin", {}),
    ("ba3", "business_admin", {}),
    ("usr", "user", {}),
    ("usr2", "user", {}),
    ("norole", None, {}),
    ("otp", "user", {"must_change_password": True}),
    ("blocked", "user", {"blocked": True}),
]
MEMBERS = ("ba", "ba2", "sm_m", "usr")


async def make_api_world(env: ApiEnv) -> ApiWorld:
    ws = await new_workspace(env)
    people: dict[str, Person] = {}
    for name, role, kw in _SPEC:
        user, (token,) = await seed(env, ws, role, login=f"w.{name}", **kw)
        people[name] = Person(user, token)
    project_id = await add_project(
        env, ws, people["ba"].user, name="Основной", members=MEMBERS, people=people
    )
    return ApiWorld(ws=ws, people=people, project_id=project_id)


async def add_project(
    env: ApiEnv,
    ws: WorkspaceRow,
    owner: UserRow,
    *,
    name: str,
    members: tuple[str, ...] | list[str] = (),
    people: dict[str, Person] | None = None,
    owner_is_member: bool = True,
    deleted: bool = False,
) -> uuid.UUID:
    """Проект напрямую через фабрики; владелец получает строку участника (если не отключено)."""
    async with env.sessionmaker() as session:
        extra: dict[str, Any] = {}
        if deleted:
            from app.core.clock import utcnow

            extra = {"deleted_at": utcnow(), "deleted_batch_id": uuid.uuid4()}
        project = await make_project(
            session, workspace_id=ws.id, owner_id=owner.id, name=name, **extra
        )
        users = [people[m].user for m in members] if people else []
        ids = {u.id for u in users}
        if owner_is_member:
            ids.add(owner.id)
        for user_id in ids:
            await make_project_member(
                session,
                project_id=project.id,
                user_id=user_id,
                workspace_id=ws.id,
                created_by=owner.id,
            )
        await session.commit()
    return project.id


async def add_member_row(
    env: ApiEnv, w: ApiWorld, user: UserRow, project_id: uuid.UUID | None = None
) -> None:
    async with env.sessionmaker() as session:
        await make_project_member(
            session,
            project_id=project_id or w.project_id,
            user_id=user.id,
            workspace_id=w.ws.id,
            created_by=w.uid("ba"),
        )
        await session.commit()


async def add_task(
    env: ApiEnv,
    w: ApiWorld,
    *,
    assignee: uuid.UUID | None = None,
    parent_id: uuid.UUID | None = None,
    deleted: bool = False,
    project_id: uuid.UUID | None = None,
    with_comment: bool = False,
) -> uuid.UUID:
    async with env.sessionmaker() as session:
        extra: dict[str, Any] = {}
        if deleted:
            from app.core.clock import utcnow

            extra = {"deleted_at": utcnow(), "deleted_batch_id": uuid.uuid4()}
        task = await make_task(
            session,
            project_id=project_id or w.project_id,
            workspace_id=w.ws.id,
            created_by=w.uid("ba"),
            parent_id=parent_id,
            assignee_id=assignee,
            **extra,
        )
        if with_comment:
            await make_comment(
                session, task_id=task.id, workspace_id=w.ws.id, created_by=w.uid("ba")
            )
        await session.commit()
    return task.id


async def rows(env: ApiEnv, sql: str, **params: Any) -> list[Any]:
    result = await env.execute(text(sql).bindparams(**params))
    return list(result) if result is not None else []


async def member_ids(env: ApiEnv, project_id: uuid.UUID) -> set[uuid.UUID]:
    found = await rows(
        env, "SELECT user_id FROM project_member WHERE project_id = :p", p=project_id
    )
    return {r[0] for r in found}


async def project_db(env: ApiEnv, project_id: uuid.UUID) -> Any:
    found = await rows(env, "SELECT * FROM project WHERE id = :p", p=uuid.UUID(str(project_id)))
    assert len(found) == 1
    return found[0]


async def set_blocked(env: ApiEnv, user_id: uuid.UUID) -> None:
    await rows(env, "UPDATE app_user SET is_blocked = true WHERE id = :u", u=user_id)


async def event_count(env: ApiEnv, workspace_id: uuid.UUID) -> int:
    found = await rows(
        env, "SELECT count(*) FROM domain_event WHERE workspace_id = :w", w=workspace_id
    )
    return int(found[0][0])


@dataclass
class Foreign:
    ws: WorkspaceRow
    ba: UserRow
    ba_token: str
    usr: UserRow
    project_id: uuid.UUID


async def make_foreign(env: ApiEnv) -> Foreign:
    """Второе пространство: БА-владелец, «Пользователь»-участник, проект."""
    ws = await new_workspace(env)
    ba, (ba_token,) = await seed(env, ws, "business_admin", login="f.ba")
    usr, _ = await seed(env, ws, "user", login="f.usr")
    people = {"usr": Person(usr, "")}
    project_id = await add_project(env, ws, ba, name="Чужой-проект", members=["usr"], people=people)
    return Foreign(ws=ws, ba=ba, ba_token=ba_token, usr=usr, project_id=project_id)


async def send(
    env: ApiEnv,
    token: str | None,
    method: str,
    url: str,
    body: Any = None,
    *,
    raw: bytes | None = None,
) -> httpx.Response:
    """Запрос с cookie сессии; ``body`` — JSON; ``raw`` — сырое тело (битый JSON)."""
    headers = env.auth(token) if token else {}
    kwargs: dict[str, Any] = {}
    if raw is not None:
        kwargs["content"] = raw
        headers = {**headers, "Content-Type": "application/json"}
    elif body is not None:
        kwargs["json"] = body
    return await env.client.request(method, url, headers=headers, **kwargs)


def pj(project_id: uuid.UUID | str) -> str:
    return f"{PROJECTS}/{project_id}"


def members_url(project_id: uuid.UUID | str, user_id: uuid.UUID | str | None = None) -> str:
    base = f"{PROJECTS}/{project_id}/members"
    return base if user_id is None else f"{base}/{user_id}"


def error(response: httpx.Response) -> tuple[int, str]:
    return response.status_code, code_of(response)


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)
