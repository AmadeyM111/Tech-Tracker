"""Alembic: асинхронное окружение миграций (plan §4.2, D-26).

URL БД: ключ ``-x dburl=...``; если не задан — ``get_settings().database_url``.
"""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

import app.domain.registry  # noqa: F401  (регистрирует модели в Base.metadata)
from app.core.config import get_settings
from app.core.models import Base

config = context.config
target_metadata = Base.metadata


def _database_url() -> str:
    url = context.get_x_argument(as_dictionary=True).get("dburl")
    return url if url else get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    # Серверный lock_timeout (plan §4.12) рассчитан на запросы приложения; миграция ждёт блокировку.
    connection.execute(text("SET lock_timeout = 0"))
    connection.commit()  # SET - сессионный; транзакцию закрываем, чтобы alembic вёл свою
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_database_url(), hide_parameters=True, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_do_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
