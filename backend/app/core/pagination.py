"""Постраничный вывод (plan §4.2, D-34, FR-47, AC-22).

``PageParams`` — параметры запроса ``?page&page_size``; ``Page[T]`` — формат ответа
``{items, page, page_size, has_next}``; ``paginate`` — один SELECT с
``LIMIT page_size + 1 OFFSET (page - 1) * page_size`` без COUNT.

Порядок сортировки — ответственность вызывающего: ``stmt`` обязан содержать ``order_by``
по уникальному ключу, иначе страницы могут пересекаться или терять строки.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import BigInteger, literal

if TYPE_CHECKING:
    from sqlalchemy import Select
    from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_PAGE_SIZE: Final = 50
MAX_PAGE_SIZE: Final = 100
# При page_size <= 100 OFFSET = (page - 1) * page_size < 10**17 < 2**63: помещается в bigint.
MAX_PAGE: Final = 10**15


class PageParams(BaseModel):
    """Параметры страницы; используется как ``Annotated[PageParams, Query()]``."""

    page: int = Field(1, ge=1, le=MAX_PAGE)
    page_size: int = Field(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)


class Page[T](BaseModel):
    """Ответ списочного эндпоинта; общего количества нет (D-34)."""

    model_config = ConfigDict(from_attributes=True)

    items: list[T]
    page: int
    page_size: int
    has_next: bool


async def paginate[R](
    db: AsyncSession, stmt: Select[R], params: PageParams
) -> tuple[list[R], bool]:
    """Выбрать страницу: ``LIMIT page_size + 1``; лишняя строка лишь задаёт ``has_next``.

    ``stmt`` — ``select(Entity)`` (одна сущность; несколько колонок типизация отвергает).
    Требования к вызывающему:

    * ``order_by`` обязателен (иначе ``ValueError``) и должен завершаться тай-брейкером
      по ``Entity.id``, иначе страницы пересекаются или теряют строки;
    * коллекции подгружаются только через ``selectinload`` (``joinedload`` коллекции
      не поддерживается при LIMIT/OFFSET);
    * фильтр по связи «один-ко-многим» — через ``EXISTS``, не через join (иначе дубли
      строк); безусловный ``unique()`` здесь не добавляется.
    """
    if not stmt._order_by_clauses:
        raise ValueError("paginate: у stmt нет ORDER BY, порядок страниц не определён")
    offset = (params.page - 1) * params.page_size
    paged = stmt.limit(params.page_size + 1).offset(literal(offset, BigInteger()))
    rows = list((await db.scalars(paged)).all())
    has_next = len(rows) > params.page_size
    return rows[: params.page_size], has_next
