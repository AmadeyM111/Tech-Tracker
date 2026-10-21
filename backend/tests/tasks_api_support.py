"""Общие помощники тестов API задач (T77). Не тест-модуль.

Мир и ``send`` — из ``projects_api_support`` (роли: ``ba`` владелец и участник, ``ba2`` БА-участник,
``ba3`` БА не участник, ``usr`` П-участник, ``usr2`` П
не участник, ``ta``, ``norole``, ``otp``, ``blocked``).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from tests.admin_support import seed
from tests.factories import make_comment, make_task
from tests.projects_api_support import (
    PAGE_FIELDS,
    USER_REF_FIELDS,
    ApiWorld,
    Person,
    add_member_row,
    add_project,
    code_of,
    error,
    make_api_world,
    make_foreign,
    pj,
    rows,
    send,
)

if TYPE_CHECKING:
    from tests.conftest import ApiEnv

__all__ = [
    "ALL_STATUSES",
    "BRIEF_FIELDS",
    "DETAIL_FIELDS",
    "LIST_FIELDS",
    "ME_TASKS",
    "PAGE_FIELDS",
    "PERM_FIELDS",
    "TASKS",
    "TASK_REQ",
    "USER_REF_FIELDS",
    "ApiWorld",
    "Person",
    "add_member_row",
    "add_project",
    "busy_database",
    "code_of",
    "comment_rows",
    "error",
    "extra_user",
    "hold_row",
    "make_api_world",
    "make_foreign",
    "mk",
    "pj",
    "project_tasks_url",
    "rows",
    "send",
    "task_db",
    "task_url",
]

TASKS = "/api/v1/tasks"
# 006/FR-15, FR-16: обязательные поля создания задачи верхнего уровня. Срок - «сегодня» по
# Москве при ``fixed_clock`` по умолчанию (2026-10-13T09:00Z); тесты со сдвигом часов берут свой.
TASK_REQ = {"description": "Описание", "due_date": "2026-10-13"}
ME_TASKS = "/api/v1/me/tasks"
ALL_STATUSES = ("todo", "in_progress", "review", "done")

DETAIL_FIELDS = {
    "id",
    "project",
    "parent_id",
    "title",
    "description",
    "status",
    "priority",
    "due_date",
    "assignee",
    "author",
    "position",
    "subtasks",
    "progress",
    "created_at",
    "updated_at",
    "permissions",
}
PERM_FIELDS = {"edit", "change_status", "change_assignee", "delete", "create_subtask"}
BRIEF_FIELDS = {"id", "title", "status", "priority", "due_date", "assignee"}
LIST_FIELDS = {
    "id",
    "project",
    "parent_id",
    "title",
    "status",
    "priority",
    "due_date",
    "assignee",
    "created_at",
}


def task_url(task_id: uuid.UUID | str) -> str:
    return f"{TASKS}/{task_id}"


def project_tasks_url(project_id: uuid.UUID | str, query: str = "") -> str:
    return f"/api/v1/projects/{project_id}/tasks{query}"


async def mk(
    env: ApiEnv,
    w: ApiWorld,
    *,
    by: str = "ba",
    assignee: str | uuid.UUID | None = None,
    parent: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    deleted: bool = False,
    comment: bool = False,
    **kw: Any,
) -> uuid.UUID:
    """Задача напрямую в БД: автор ``by`` (ключ мира), исполнитель — ключ мира или UUID."""
    values: dict[str, Any] = dict(kw)
    if deleted:
        from app.core.clock import utcnow

        values.setdefault("deleted_at", utcnow())
        values.setdefault("deleted_batch_id", uuid.uuid4())
    assignee_id = w.uid(assignee) if isinstance(assignee, str) else assignee
    async with env.sessionmaker() as session:
        row = await make_task(
            session,
            project_id=project_id or w.project_id,
            workspace_id=w.ws.id,
            created_by=w.uid(by),
            parent_id=parent,
            assignee_id=assignee_id,
            **values,
        )
        if comment:
            await make_comment(
                session, task_id=row.id, workspace_id=w.ws.id, created_by=w.uid("ba")
            )
        await session.commit()
    return row.id


async def task_db(env: ApiEnv, task_id: uuid.UUID | str) -> Any:
    found = await rows(env, "SELECT * FROM task WHERE id = :t", t=uuid.UUID(str(task_id)))
    assert len(found) == 1
    return found[0]


async def comment_rows(env: ApiEnv, task_id: uuid.UUID) -> list[Any]:
    return await rows(
        env, "SELECT id, deleted_at, deleted_batch_id FROM comment WHERE task_id = :t", t=task_id
    )


async def extra_user(
    env: ApiEnv,
    w: ApiWorld,
    role: str | None,
    login: str,
    *,
    member: bool = True,
    **kw: Any,
) -> Person:
    user, (token,) = await seed(env, w.ws, role, login=login, **kw)
    if member:
        await add_member_row(env, w, user)
    return Person(user, token)


def iso(value: date | datetime | None) -> str | None:
    return None if value is None else value.isoformat()


@asynccontextmanager
async def busy_database(env: ApiEnv) -> AsyncIterator[None]:
    """``lock_timeout = 300ms`` на уровне тестовой БД (только ``*_test``) на время блока."""
    engine = env.sessionmaker.kw["bind"]
    async with engine.connect() as conn:
        db_name = str((await conn.execute(text("SELECT current_database()"))).scalar_one())
    assert db_name.endswith("_test")
    quoted = '"' + db_name + '"'
    admin = engine.execution_options(isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f"ALTER DATABASE {quoted} SET lock_timeout = '300ms'"))
    await engine.dispose()  # новые соединения подхватят lock_timeout
    try:
        yield
    finally:
        async with admin.connect() as conn:
            await conn.execute(text(f"ALTER DATABASE {quoted} RESET lock_timeout"))
        await engine.dispose()


@asynccontextmanager
async def hold_row(env: ApiEnv, table: str, row_id: uuid.UUID) -> AsyncIterator[None]:
    """Вторая транзакция держит ``FOR UPDATE`` строки ``project``/``task`` до выхода из блока."""
    assert table in {"project", "task"}
    holder = env.sessionmaker()
    await holder.begin()
    await holder.execute(
        text(f"SELECT id FROM {table} WHERE id = :i FOR UPDATE").bindparams(i=row_id)
    )
    try:
        yield
    finally:
        await holder.rollback()
        await holder.close()
