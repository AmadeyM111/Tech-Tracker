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

    Фиксация транзакции запроса выполняется здесь (сервисы ``commit()`` не вызывают; единственное
    исключение — ``commit_durably`` ниже). Выход без исключения — COMMIT, с исключением —
    ROLLBACK. Транзакция открывается явно в начале запроса; если сервис зафиксировал её раньше
    через ``commit_durably``, следующая операция автоматически начнёт новую, а откат на
    исключении и итоговый COMMIT по-прежнему относятся к текущей транзакции.

    Подключать только через ``DbSession`` (ниже); ``Depends(get_db)`` вне этого модуля
    запрещён. Причины: при ``scope="request"`` (умолчание ``Depends``) COMMIT выполняется
    после отправки ответа, и при сбое клиент уже получил 200; смешение ``Depends(get_db)`` и
    ``DbSession`` в одном запросе даёт две сессии и две транзакции.
    """
    sessionmaker = request.app.state.sessionmaker
    async with sessionmaker() as session:
        await session.begin()
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


async def commit_durably(session: AsyncSession) -> None:
    """Фиксирует транзакцию запроса до броска исключения (plan §4.1, исключение T11).

    Единственный санкционированный способ зафиксировать транзакцию внутри запроса (``app/**``);
    разрешён только в ``domain/auth/service.py`` и ``api/deps.py`` (AST-тест).
    Причина: ``get_db`` откатывает транзакцию на любом исключении, а отказ входа — это
    исключение (``InvalidCredentials``), поэтому счётчик неудачных попыток и
    ``login_locked_until`` (FR-61) без явной фиксации терялись бы вместе с откатом, и блокировка
    через API не срабатывала бы. Вызывается в двух случаях: (1) на ветках отказа непосредственно
    перед ``raise``; (2) до медленной проверки пароля (``verify``), чтобы занятый слот попытки
    был виден параллельным запросам (FR-61). В обоих случаях в транзакции не должно быть ничего,
    что нельзя зафиксировать. Третий случай (T16a, ``api/deps.py:get_actor``): сразу после
    ``SessionStore.resolve``, чтобы освободить строку ``user_session`` до обработчика (иначе
    deadlock с админ-действием над работающим пользователем) и не потерять обновление
    активности / удаление истёкшей сессии при 4xx/401. Прямой ``commit()`` в сервисах запрещён
    (AST-тест).
    """
    await session.commit()


# Единственная точка подключения сессии: COMMIT выполняется до отправки ответа клиенту.
DbSession = Annotated[AsyncSession, Depends(get_db, scope="function")]
