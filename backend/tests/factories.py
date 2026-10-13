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
from datetime import datetime
from typing import TYPE_CHECKING

from app.core.clock import utcnow

if TYPE_CHECKING:
    from sqlalchemy import Table
    from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_PASSWORD = "correct-horse-battery-staple"
PLACEHOLDER_HASH = "$argon2id$v=19$m=1024,t=1,p=1$c3ludGhldGljc2FsdA$c3ludGhldGljaGFzaC1ub3QtcmVhbA"
ROLES = ("tech_admin", "business_admin", "mixed", "user")

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
            login=the_login,
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
