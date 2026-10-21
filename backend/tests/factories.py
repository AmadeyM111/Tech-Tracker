"""Фабрики тестовых данных (T06, plan §4.3).

Фабрики пишут строки через Core ``Table`` из ``Base.metadata`` (имена классов моделей не
фиксируются контрактом, имена таблиц и столбцов — фиксируются). Работают поверх сессии ``db``
(фикстура conftest): вставка идёт во внешнюю транзакцию теста и откатывается.

Данные синтетические; логины детерминированы счётчиком процесса. Хеш пароля: если модуль
``app.core.security.passwords`` существует — Argon2id с дешёвыми параметрами
(``time_cost=1, memory_cost_kib=1024, parallelism=1``), иначе — готовый ``password_hash``
или фиксированная строка-заглушка (проверка пароля с ней невозможна).
"""

from __future__ import annotations

import itertools
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING

from app.core.clock import utcnow

if TYPE_CHECKING:
    from sqlalchemy import Table
    from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_PASSWORD = "correct-horse-battery-staple"
PLACEHOLDER_HASH = "$argon2id$v=19$m=1024,t=1,p=1$c3ludGhldGljc2FsdA$c3ludGhldGljaGFzaC1ub3QtcmVhbA"
ROLES = ("tech_admin", "business_admin", "user")

_login_counter = itertools.count(1)


@dataclass(frozen=True)
class WorkspaceRow:
    id: uuid.UUID
    created_at: datetime


@dataclass(frozen=True)
class UserRow:
    id: uuid.UUID
    login: str
    password: str
    password_hash: str
    workspace_id: uuid.UUID
    role: str | None
    is_blocked: bool
    must_change_password: bool


def get_table(name: str) -> Table:
    """Таблица из ``Base.metadata`` после импорта реестра моделей; понятная ошибка, если нет."""
    import app.domain.registry  # noqa: F401
    from app.core.models import Base

    assert name in Base.metadata.tables, (
        f"таблица {name!r} не объявлена в Base.metadata (модели не реализованы или не "
        f"импортируются из app.domain.registry)"
    )
    table: Table = Base.metadata.tables[name]
    return table


def next_login(prefix: str = "user") -> str:
    """Валидный по FR-73 логин: ``user0001``, ``user0002``, …"""
    return f"{prefix}{next(_login_counter):04d}"


def _hash_password(password: str) -> str:
    try:
        from app.core.security.passwords import PasswordHasher
    except ImportError:
        return PLACEHOLDER_HASH
    hasher = PasswordHasher(time_cost=1, memory_cost_kib=1024, parallelism=1)
    result: str = hasher.hash(password)
    return result


async def make_workspace(db: AsyncSession, *, id: uuid.UUID | None = None) -> WorkspaceRow:
    now = utcnow()
    ws_id = id or uuid.uuid4()
    await db.execute(
        get_table("workspace").insert().values(id=ws_id, created_at=now, updated_at=now)
    )
    return WorkspaceRow(id=ws_id, created_at=now)


async def make_user(
    db: AsyncSession,
    *,
    workspace: WorkspaceRow | None = None,
    login: str | None = None,
    role: str | None = None,
    password: str = DEFAULT_PASSWORD,
    password_hash: str | None = None,
    blocked: bool = False,
    must_change_password: bool = False,
) -> UserRow:
    """Пользователь + строка ``workspace_member`` (роль ``None`` = «без роли», FR-66).

    Если ``workspace`` не передан, создаётся новое пространство.

    Логин (D-66, FR-73a): допускается смешанный регистр. В столбец ``login`` (ключ) пишется
    ``login.lower()``, в ``login_display`` — написание как передано; ``UserRow.login`` — написание
    (им же тест входит и сверяет ответы API).
    """
    ws = workspace or await make_workspace(db)
    now = utcnow()
    user_id = uuid.uuid4()
    the_hash = password_hash or _hash_password(password)
    the_login = login or next_login()
    await db.execute(
        get_table("app_user")
        .insert()
        .values(
            id=user_id,
            login=the_login.lower(),
            login_display=the_login,
            password_hash=the_hash,
            must_change_password=must_change_password,
            is_blocked=blocked,
            blocked_at=now if blocked else None,
            failed_login_count=0,
            login_locked_until=None,
            password_changed_at=now,
            created_at=now,
            updated_at=now,
            created_by=None,
        )
    )
    await db.execute(
        get_table("workspace_member")
        .insert()
        .values(
            workspace_id=ws.id,
            user_id=user_id,
            role=role,
            created_at=now,
            updated_at=now,
            created_by=None,
        )
    )
    return UserRow(
        id=user_id,
        login=the_login,
        password=password,
        password_hash=the_hash,
        workspace_id=ws.id,
        role=role,
        is_blocked=blocked,
        must_change_password=must_change_password,
    )


async def make_domain_event(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
    entity_type: str = "user",
    entity_id: uuid.UUID | None = None,
    action: str = "user.created",
    changed_fields: list[str] | None = None,
    project_id: uuid.UUID | None = None,
    deal_id: uuid.UUID | None = None,
    in_audit: bool = True,
    changes: list[dict[str, object]] | None = None,
    details: dict[str, object] | None = None,
    occurred_at: datetime | None = None,
) -> int:
    """Строка ``domain_event`` напрямую (в обход ``record_event``); возвращает ``id`` (T07).

    Для тестов представлений (лента, история, аудит) и проверок триггеров append-only.
    """
    result = await db.execute(
        get_table("domain_event")
        .insert()
        .values(
            workspace_id=workspace_id,
            occurred_at=occurred_at or utcnow(),
            actor_id=actor_id,
            entity_type=entity_type,
            entity_id=entity_id or uuid.uuid4(),
            action=action,
            changed_fields=changed_fields or [],
            project_id=project_id,
            deal_id=deal_id,
            in_audit=in_audit,
            changes=changes,
            details=details,
        )
        .returning(get_table("domain_event").c.id)
    )
    return int(result.scalar_one())


# --- MVP (T69, plan §11.6): проекты, участники, задачи, комментарии -----------------------

_UNSET: object = object()


@dataclass(frozen=True)
class ProjectRow:
    id: uuid.UUID
    workspace_id: uuid.UUID
    owner_id: uuid.UUID
    name: str


@dataclass(frozen=True)
class ProjectMemberRow:
    project_id: uuid.UUID
    user_id: uuid.UUID
    workspace_id: uuid.UUID


@dataclass(frozen=True)
class TaskRow:
    id: uuid.UUID
    project_id: uuid.UUID
    workspace_id: uuid.UUID
    parent_id: uuid.UUID | None
    position: int | None
    created_by: uuid.UUID


@dataclass(frozen=True)
class CommentRow:
    id: uuid.UUID
    task_id: uuid.UUID
    workspace_id: uuid.UUID


async def make_project(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    owner_id: uuid.UUID,
    name: str = "Проект",
    description: str = "",
    created_by: uuid.UUID | None | object = _UNSET,
    **extra: object,
) -> ProjectRow:
    """Строка ``project`` напрямую через Core; ``extra`` переопределяет/добавляет столбцы."""
    now = utcnow()
    project_id = uuid.uuid4()
    values: dict[str, object] = {
        "id": project_id,
        "workspace_id": workspace_id,
        "name": name,
        "description": description,
        "owner_id": owner_id,
        "created_by": owner_id if created_by is _UNSET else created_by,
        "created_at": now,
        "updated_at": now,
        "deleted_at": None,
        "deleted_batch_id": None,
    }
    values.update(extra)
    await db.execute(get_table("project").insert().values(**values))
    return ProjectRow(
        id=project_id, workspace_id=workspace_id, owner_id=owner_id, name=str(values["name"])
    )


async def make_project_member(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    created_by: uuid.UUID | None = None,
    **extra: object,
) -> ProjectMemberRow:
    now = utcnow()
    values: dict[str, object] = {
        "project_id": project_id,
        "user_id": user_id,
        "workspace_id": workspace_id,
        "created_by": created_by,
        "created_at": now,
        "updated_at": now,
    }
    values.update(extra)
    await db.execute(get_table("project_member").insert().values(**values))
    return ProjectMemberRow(project_id=project_id, user_id=user_id, workspace_id=workspace_id)


async def make_task(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    workspace_id: uuid.UUID,
    created_by: uuid.UUID,
    parent_id: uuid.UUID | None = None,
    title: str = "Задача",
    description: str = "",
    status: str = "todo",
    priority: str = "medium",
    due_date: date | None = None,
    assignee_id: uuid.UUID | None = None,
    position: int | None | object = _UNSET,
    **extra: object,
) -> TaskRow:
    """Строка ``task``. По умолчанию позиция 1024 у верхнего уровня и ``None`` у подзадачи."""
    now = utcnow()
    task_id = uuid.uuid4()
    pos: int | None = (
        (None if parent_id is not None else 1024) if position is _UNSET else position  # type: ignore[assignment]
    )
    values: dict[str, object] = {
        "id": task_id,
        "workspace_id": workspace_id,
        "project_id": project_id,
        "parent_id": parent_id,
        "title": title,
        "description": description,
        "status": status,
        "priority": priority,
        "due_date": due_date,
        "assignee_id": assignee_id,
        "position": pos,
        "created_by": created_by,
        "created_at": now,
        "updated_at": now,
        "deleted_at": None,
        "deleted_batch_id": None,
    }
    values.update(extra)
    await db.execute(get_table("task").insert().values(**values))
    return TaskRow(
        id=task_id,
        project_id=project_id,
        workspace_id=workspace_id,
        parent_id=parent_id,
        position=pos,
        created_by=created_by,
    )


async def make_comment(
    db: AsyncSession,
    *,
    task_id: uuid.UUID,
    workspace_id: uuid.UUID,
    created_by: uuid.UUID | None = None,
    body: str = "Комментарий",
    **extra: object,
) -> CommentRow:
    now = utcnow()
    comment_id = uuid.uuid4()
    values: dict[str, object] = {
        "id": comment_id,
        "workspace_id": workspace_id,
        "task_id": task_id,
        "body": body,
        "edited_at": None,
        "created_by": created_by,
        "created_at": now,
        "updated_at": now,
        "deleted_at": None,
        "deleted_batch_id": None,
    }
    values.update(extra)
    await db.execute(get_table("comment").insert().values(**values))
    return CommentRow(id=comment_id, task_id=task_id, workspace_id=workspace_id)
