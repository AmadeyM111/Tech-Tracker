"""Общие помощники доменных тестов проектов и участников (T71). Не тест-модуль.

Данные тестов фиксируются ``db.commit()`` (освобождает SAVEPOINT внешней транзакции), чтобы
откат после ошибки сервиса (``fails``) не стирал подготовленные строки.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import event, text

from app.domain.access.roles import Actor, Role
from tests.factories import (
    UserRow,
    WorkspaceRow,
    make_project,
    make_project_member,
    make_user,
    make_workspace,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

LONG_NAME_255 = "Я" * 255
LONG_DESC_10000 = "д" * 10_000


def actor_of(user: UserRow, *, role: str | None | object = ...) -> Actor:
    the_role = user.role if role is ... else role
    return Actor(
        user_id=user.id,
        workspace_id=user.workspace_id,
        login=user.login,
        role=Role(the_role) if the_role is not None else None,  # type: ignore[arg-type]
        must_change_password=False,
        session_id=b"\x01" * 32,
    )


async def fails(
    db: AsyncSession, awaitable: Awaitable[Any], code: str, *, status: int = 422
) -> BaseException:
    """Сервис бросает AppError с кодом; затем откат, как у ``get_db``."""
    from app.core.errors import AppError

    with pytest.raises(AppError) as info:
        await awaitable
    exc = info.value
    assert exc.status_code == status, (exc.status_code, exc.code)
    assert str(exc.code) == code
    await db.rollback()
    return exc


async def forbidden(db: AsyncSession, awaitable: Awaitable[Any]) -> None:
    await fails(db, awaitable, "forbidden", status=403)


async def not_found(db: AsyncSession, awaitable: Awaitable[Any]) -> None:
    await fails(db, awaitable, "not_found", status=404)


class World:
    """Одно пространство: пользователи всех ролей и проект, которым владеет ``ba``."""

    ws: WorkspaceRow
    ta: UserRow
    ba: UserRow  # БА, владелец проекта
    ba2: UserRow  # БА, участник, не владелец
    ba3: UserRow  # БА, не участник
    usr: UserRow  # «Пользователь», участник
    usr2: UserRow  # «Пользователь», не участник
    norole: UserRow
    blocked: UserRow  # «Пользователь», заблокирован, не участник
    project_id: uuid.UUID


async def make_world(db: AsyncSession) -> World:
    w = World()
    w.ws = await make_workspace(db)
    w.ta = await make_user(db, workspace=w.ws, role="tech_admin", login="w.ta")
    w.ba = await make_user(db, workspace=w.ws, role="business_admin", login="w.ba")
    w.ba2 = await make_user(db, workspace=w.ws, role="business_admin", login="w.ba2")
    w.ba3 = await make_user(db, workspace=w.ws, role="business_admin", login="w.ba3")
    w.usr = await make_user(db, workspace=w.ws, role="user", login="w.usr")
    w.usr2 = await make_user(db, workspace=w.ws, role="user", login="w.usr2")
    w.norole = await make_user(db, workspace=w.ws, role=None, login="w.norole")
    w.blocked = await make_user(db, workspace=w.ws, role="user", login="w.blocked", blocked=True)
    project = await make_project(db, workspace_id=w.ws.id, owner_id=w.ba.id, name="Основной")
    w.project_id = project.id
    for user in (w.ba, w.ba2, w.usr):
        await make_project_member(
            db, project_id=project.id, user_id=user.id, workspace_id=w.ws.id, created_by=w.ba.id
        )
    await db.commit()
    return w


async def add_member_row(db: AsyncSession, w: World, project_id: uuid.UUID, user: UserRow) -> None:
    await make_project_member(
        db, project_id=project_id, user_id=user.id, workspace_id=w.ws.id, created_by=w.ba.id
    )


async def member_ids(db: AsyncSession, project_id: uuid.UUID) -> set[uuid.UUID]:
    await db.flush()
    rows = await db.execute(
        text("SELECT user_id FROM project_member WHERE project_id = :p").bindparams(p=project_id)
    )
    return {r.user_id for r in rows}


async def project_row(db: AsyncSession, project_id: uuid.UUID) -> Any:
    await db.flush()
    row = (
        await db.execute(text("SELECT * FROM project WHERE id = :p").bindparams(p=project_id))
    ).one_or_none()
    assert row is not None
    return row


async def task_row(db: AsyncSession, task_id: uuid.UUID) -> Any:
    await db.flush()
    row = (
        await db.execute(text("SELECT * FROM task WHERE id = :t").bindparams(t=task_id))
    ).one_or_none()
    assert row is not None
    return row


async def comment_row(db: AsyncSession, comment_id: uuid.UUID) -> Any:
    await db.flush()
    row = (
        await db.execute(text("SELECT * FROM comment WHERE id = :c").bindparams(c=comment_id))
    ).one_or_none()
    assert row is not None
    return row


async def events(db: AsyncSession, workspace_id: uuid.UUID) -> list[Any]:
    await db.flush()
    rows = await db.execute(
        text("SELECT * FROM domain_event WHERE workspace_id = :w ORDER BY id").bindparams(
            w=workspace_id
        )
    )
    return list(rows)


@contextmanager
def capture_sql(db: AsyncSession) -> Iterator[list[str]]:
    """Тексты SQL, выполненные на соединении сессии (before_cursor_execute)."""
    conn = db.get_bind()
    seen: list[str] = []

    def on_execute(c: Any, cursor: Any, statement: str, *a: Any) -> None:
        seen.append(statement)

    event.listen(conn, "before_cursor_execute", on_execute)
    try:
        yield seen
    finally:
        event.remove(conn, "before_cursor_execute", on_execute)
