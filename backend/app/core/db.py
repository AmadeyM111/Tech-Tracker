"""Слой БД: движок и сессия на запрос (plan §4.2, D-3)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.core.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    """Создаёт асинхронный движок (asyncpg). Соединение не открывается до первого запроса.

    ``hide_parameters=True`` — значения параметров не попадают в текст исключений и логи.
    """
    return create_async_engine(
        settings.database_url,
        hide_parameters=True,
        pool_pre_ping=True,
    )


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """Сессия на запрос: одна транзакция, откат при исключении, COMMIT в конце запроса.

    Единственное место фиксации транзакции в ``app/**`` (сервисы ``commit()`` не вызывают).
    Транзакцию открывает и закрывает ``session.begin()``: при выходе без исключения — COMMIT,
    с исключением — ROLLBACK.

    Подключать только через ``DbSession`` (ниже); ``Depends(get_db)`` вне этого модуля
    запрещён. Причины: при ``scope="request"`` (умолчание ``Depends``) COMMIT выполняется
    после отправки ответа, и при сбое клиент уже получил 200; смешение ``Depends(get_db)`` и
    ``DbSession`` в одном запросе даёт две сессии и две транзакции.
    """
    sessionmaker = request.app.state.sessionmaker
    async with sessionmaker() as session, session.begin():
        yield session


# Единственная точка подключения сессии: COMMIT выполняется до отправки ответа клиенту.
DbSession = Annotated[AsyncSession, Depends(get_db, scope="function")]
