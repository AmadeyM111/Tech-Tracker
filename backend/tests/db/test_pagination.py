"""T15: постраничный вывод (plan §4.2 ``app.core.pagination``, D-34).

Покрытие: FR-47 (списочные ответы постраничны, 50 по умолчанию), AC-22 (51+ строк → 50
элементов и ``has_next``; фильтры сужают выборку), D-34 (``page``/``page_size`` 1…100,
ответ ``{items, page, page_size, has_next}``, ``has_next`` через ``LIMIT page_size + 1``,
без COUNT).

Публичный интерфейс: ``PageParams``, ``Page[T]``, ``paginate(db, stmt, params)`` ->
``(items, has_next)``. Данные — реальные строки ``app_user`` в откатываемой транзакции
(фикстура ``db``); выборки ограничены уникальным префиксом логина.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Annotated, Any

import httpx
import pytest
from fastapi import FastAPI, Query
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import event, func, select, text

from tests.factories import PLACEHOLDER_HASH, make_user, make_workspace

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.domain.users.models import AppUser

BIG_PAGE = 10**12  # offset ~1e14 — не помещается в int32, но помещается в bigint
HUGE_PAGE = 10**30  # не помещается и в bigint


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    login: str


def _prefix() -> str:
    return "pg" + uuid.uuid4().hex[:8] + "-"


async def _seed(
    db: AsyncSession, n: int, *, blocked_every: int = 0, prefix: str | None = None
) -> tuple[str, list[str]]:
    """n пользователей с логинами ``<prefix>000``…; возвращает (prefix, логины по возрастанию)."""
    pref = prefix or _prefix()
    ws = await make_workspace(db)
    logins = []
    for i in range(n):
        login = f"{pref}{i:03d}"
        await make_user(
            db,
            workspace=ws,
            login=login,
            password_hash=PLACEHOLDER_HASH,
            blocked=bool(blocked_every) and i % blocked_every == 0,
        )
        logins.append(login)
    return pref, logins


def _stmt(prefix: str) -> Any:
    from app.domain.users.models import AppUser

    return select(AppUser).where(AppUser.login.like(prefix + "%")).order_by(AppUser.login)


def _logins(rows: list[AppUser]) -> list[str]:
    return [r.login for r in rows]


@contextmanager
def _capture_sql(sync_conn: Any) -> Iterator[list[tuple[str, Any]]]:
    seen: list[tuple[str, Any]] = []

    def on_execute(conn: Any, cursor: Any, statement: str, parameters: Any, *a: Any) -> None:
        seen.append((statement, parameters))

    event.listen(sync_conn, "before_cursor_execute", on_execute)
    try:
        yield seen
    finally:
        event.remove(sync_conn, "before_cursor_execute", on_execute)


# --- PageParams -------------------------------------------------------------------------


def test_fr47_defaults_page1_size50() -> None:
    from app.core.pagination import PageParams

    p = PageParams()
    assert (p.page, p.page_size) == (1, 50)


@pytest.mark.parametrize(("page", "size"), [(1, 1), (1, 100), (7, 50), (BIG_PAGE, 100)])
def test_d34_boundaries_accepted(page: int, size: int) -> None:
    from app.core.pagination import PageParams

    p = PageParams(page=page, page_size=size)
    assert (p.page, p.page_size) == (page, size)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"page": 0},
        {"page": -1},
        {"page_size": 0},
        {"page_size": -1},
        {"page_size": 101},
        {"page": "1; DROP TABLE app_user"},
        {"page_size": "abc"},
        {"page": 1.5},
        {"page": HUGE_PAGE},
    ],
)
def test_d34_out_of_range_rejected(kwargs: dict[str, Any]) -> None:
    from app.core.pagination import PageParams

    with pytest.raises(ValidationError):
        PageParams(**kwargs)


def _params_app() -> FastAPI:
    from app.core.pagination import PageParams

    app = FastAPI()

    async def echo(params: Any) -> dict[str, int]:
        return {"page": params.page, "page_size": params.page_size}

    # аннотация задаётся явно: PageParams импортируется внутри функции (при future-аннотациях
    # строковую аннотацию FastAPI не разрешил бы)
    echo.__annotations__["params"] = Annotated[PageParams, Query()]
    app.add_api_route("/echo", echo, methods=["GET"])

    return app


async def _get(app: FastAPI, url: str, **params: Any) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        return await client.get(url, params=params)


async def test_fr47_query_defaults() -> None:
    r = await _get(_params_app(), "/echo")
    assert r.status_code == 200
    assert r.json() == {"page": 1, "page_size": 50}


async def test_d34_query_values_and_boundaries() -> None:
    app = _params_app()
    r = await _get(app, "/echo", page=3, page_size=100)
    assert (r.status_code, r.json()) == (200, {"page": 3, "page_size": 100})
    r = await _get(app, "/echo", page=1, page_size=1)
    assert (r.status_code, r.json()) == (200, {"page": 1, "page_size": 1})


@pytest.mark.parametrize(
    "params",
    [
        {"page": 0},
        {"page": -5},
        {"page_size": 0},
        {"page_size": 101},
        {"page": "abc"},
        {"page": "1;drop table app_user"},
        {"page": "1 OR 1=1"},
        {"page_size": "1.5"},
        {"page": HUGE_PAGE},
    ],
)
async def test_d34_query_out_of_range_is_422(params: dict[str, Any]) -> None:
    r = await _get(_params_app(), "/echo", **params)
    assert r.status_code == 422


# --- paginate ---------------------------------------------------------------------------


async def test_paginate_zero_rows(db: AsyncSession) -> None:
    from app.core.pagination import PageParams, paginate

    items, has_next = await paginate(db, _stmt(_prefix()), PageParams())
    assert items == []
    assert has_next is False


async def test_paginate_exactly_page_size_no_next(db: AsyncSession) -> None:
    from app.core.pagination import PageParams, paginate

    pref, logins = await _seed(db, 10)
    items, has_next = await paginate(db, _stmt(pref), PageParams(page=1, page_size=10))
    assert _logins(items) == logins
    assert has_next is False


async def test_paginate_page_size_plus_one_has_next_and_trims(db: AsyncSession) -> None:
    from app.core.pagination import PageParams, paginate

    pref, logins = await _seed(db, 11)
    items, has_next = await paginate(db, _stmt(pref), PageParams(page=1, page_size=10))
    assert has_next is True
    assert _logins(items) == logins[:10]  # лишняя (page_size+1-я) строка не возвращается


async def test_paginate_fewer_than_page_size(db: AsyncSession) -> None:
    from app.core.pagination import PageParams, paginate

    pref, logins = await _seed(db, 3)
    items, has_next = await paginate(db, _stmt(pref), PageParams(page=1, page_size=10))
    assert _logins(items) == logins
    assert has_next is False


async def test_ac22_51_rows_first_page_50_has_next(db: AsyncSession) -> None:
    from app.core.pagination import PageParams, paginate

    pref, logins = await _seed(db, 51)
    items, has_next = await paginate(db, _stmt(pref), PageParams())
    assert len(items) == 50
    assert has_next is True
    assert _logins(items) == logins[:50]


async def test_ac22_second_page_gives_remainder(db: AsyncSession) -> None:
    from app.core.pagination import PageParams, paginate

    pref, logins = await _seed(db, 51)
    items, has_next = await paginate(db, _stmt(pref), PageParams(page=2))
    assert _logins(items) == logins[50:]
    assert has_next is False


async def test_paginate_pages_are_disjoint_and_cover_all_in_order(db: AsyncSession) -> None:
    from app.core.pagination import PageParams, paginate

    pref, logins = await _seed(db, 23)
    collected: list[str] = []
    flags: list[bool] = []
    for page in (1, 2, 3):
        items, has_next = await paginate(db, _stmt(pref), PageParams(page=page, page_size=10))
        collected += _logins(items)
        flags.append(has_next)
    assert collected == logins
    assert flags == [True, True, False]


async def test_paginate_page_beyond_end_is_empty_not_error(db: AsyncSession) -> None:
    from app.core.pagination import PageParams, paginate

    pref, _ = await _seed(db, 5)
    items, has_next = await paginate(db, _stmt(pref), PageParams(page=9, page_size=10))
    assert items == []
    assert has_next is False


async def test_ac22_filters_narrow_selection_before_pagination(db: AsyncSession) -> None:
    from app.core.pagination import PageParams, paginate
    from app.domain.users.models import AppUser

    pref, logins = await _seed(db, 60, blocked_every=20)  # заблокированы 0, 20, 40
    stmt = _stmt(pref).where(AppUser.is_blocked.is_(True))
    items, has_next = await paginate(db, stmt, PageParams())
    assert _logins(items) == [logins[0], logins[20], logins[40]]
    assert has_next is False

    # has_next считается по отфильтрованной выборке: 3 строки, страница по 2
    items, has_next = await paginate(db, stmt, PageParams(page=1, page_size=2))
    assert _logins(items) == [logins[0], logins[20]]
    assert has_next is True
    items, has_next = await paginate(db, stmt, PageParams(page=2, page_size=2))
    assert _logins(items) == [logins[40]]
    assert has_next is False


async def test_paginate_returns_orm_entities(db: AsyncSession) -> None:
    from app.core.pagination import PageParams, paginate
    from app.domain.users.models import AppUser

    pref, _ = await _seed(db, 2)
    items, _ = await paginate(db, _stmt(pref), PageParams())
    assert len(items) == 2
    assert all(isinstance(i, AppUser) for i in items)


async def test_d34_no_count_single_select_with_bound_limit_offset(db: AsyncSession) -> None:
    from app.core.pagination import PageParams, paginate

    pref, _ = await _seed(db, 30)
    conn = await db.connection()
    with _capture_sql(conn.sync_connection) as seen:
        items, has_next = await paginate(db, _stmt(pref), PageParams(page=3, page_size=7))
    assert len(items) == 7
    assert has_next is True

    selects = [(s, p) for s, p in seen if s.lstrip().lower().startswith(("select", "with"))]
    assert len(selects) == 1, [s for s, _ in seen]
    statement, parameters = selects[0]
    lowered = statement.lower()
    assert "count(" not in lowered
    assert re.search(r"limit\s+\$\d+", lowered), statement  # привязанный параметр, не литерал
    assert re.search(r"offset\s+\$\d+", lowered), statement
    bound = list(parameters)
    assert 8 in bound  # LIMIT page_size + 1
    assert 14 in bound  # OFFSET (page - 1) * page_size
    assert 7 not in bound or 8 in bound  # не LIMIT page_size


async def test_d34_limit_is_page_size_plus_one_for_default(db: AsyncSession) -> None:
    from app.core.pagination import PageParams, paginate

    pref, _ = await _seed(db, 3)
    conn = await db.connection()
    with _capture_sql(conn.sync_connection) as seen:
        await paginate(db, _stmt(pref), PageParams())
    selects = [p for s, p in seen if s.lstrip().lower().startswith(("select", "with"))]
    assert len(selects) == 1
    assert 51 in list(selects[0])
    assert 0 in list(selects[0])


async def test_security_huge_page_fast_empty_no_overflow(db: AsyncSession) -> None:
    from app.core.pagination import PageParams, paginate

    pref, _ = await _seed(db, 5)
    items, has_next = await paginate(db, _stmt(pref), PageParams(page=BIG_PAGE, page_size=100))
    assert items == []
    assert has_next is False


async def test_security_injection_text_does_not_reach_sql(db: AsyncSession) -> None:
    from app.core.pagination import PageParams, paginate

    pref, logins = await _seed(db, 3)
    with pytest.raises(ValidationError):
        PageParams(page="1; DROP TABLE app_user; --")  # type: ignore[arg-type]
    items, _ = await paginate(db, _stmt(pref), PageParams())
    assert _logins(items) == logins
    exists = (await db.execute(text("SELECT to_regclass('public.app_user')"))).scalar()
    assert exists is not None


# --- Page[T] ----------------------------------------------------------------------------


def test_d34_page_generic_validates_items() -> None:
    from app.core.pagination import Page

    page = Page[int](items=[1, 2, 3], page=1, page_size=50, has_next=False)
    assert page.model_dump() == {"items": [1, 2, 3], "page": 1, "page_size": 50, "has_next": False}
    with pytest.raises(ValidationError):
        Page[int](items=["not-an-int"], page=1, page_size=50, has_next=False)
    with pytest.raises(ValidationError):
        Page[int](items=[1], page=1, page_size=50)  # type: ignore[call-arg]


async def test_d34_page_items_validated_from_orm_attributes(db: AsyncSession) -> None:
    from app.core.pagination import Page, PageParams, paginate

    pref, logins = await _seed(db, 3)
    rows, has_next = await paginate(db, _stmt(pref), PageParams(page=1, page_size=2))
    page = Page[UserOut](items=rows, page=1, page_size=2, has_next=has_next)  # type: ignore[arg-type]
    assert all(isinstance(i, UserOut) for i in page.items)
    assert [i.login for i in page.items] == logins[:2]
    assert page.has_next is True


async def test_ac22_http_response_shape_and_has_next(db: AsyncSession) -> None:
    from app.core.pagination import Page, PageParams, paginate

    pref, logins = await _seed(db, 51)
    app = FastAPI()

    async def list_users(params: Any) -> Page[UserOut]:
        rows, has_next = await paginate(db, _stmt(pref), params)
        return Page[UserOut](
            items=rows,  # type: ignore[arg-type]
            page=params.page,
            page_size=params.page_size,
            has_next=has_next,
        )

    list_users.__annotations__["params"] = Annotated[PageParams, Query()]
    app.add_api_route("/users", list_users, methods=["GET"], response_model=Page[UserOut])

    r = await _get(app, "/users")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"items", "page", "page_size", "has_next"}
    assert (body["page"], body["page_size"], body["has_next"]) == (1, 50, True)
    assert [i["login"] for i in body["items"]] == logins[:50]
    assert set(body["items"][0]) == {"id", "login"}

    r = await _get(app, "/users", page=2)
    body = r.json()
    assert (body["page"], body["page_size"], body["has_next"]) == (2, 50, False)
    assert [i["login"] for i in body["items"]] == logins[50:]

    r = await _get(app, "/users", page=BIG_PAGE, page_size=100)
    assert r.status_code == 200
    assert r.json()["items"] == []
    assert r.json()["has_next"] is False

    assert (await _get(app, "/users", page_size=101)).status_code == 422
    assert (await _get(app, "/users", page=HUGE_PAGE)).status_code == 422


async def test_sanity_seed_count(db: AsyncSession) -> None:
    """Страховка фикстуры: _seed действительно создаёт N строк (иначе тесты выше пусты)."""
    from app.domain.users.models import AppUser

    pref, _ = await _seed(db, 12)
    n = (
        await db.execute(
            select(func.count()).select_from(AppUser).where(AppUser.login.like(pref + "%"))
        )
    ).scalar()
    assert n == 12


async def test_t18_paginate_without_order_by_raises_value_error(db: AsyncSession) -> None:
    """Заметка ревью T15/T17: порядок страниц без ORDER BY не определён -> ``ValueError``.

    Исключение обязано возникнуть до обращения к БД (ни одного запроса не выполняется).
    """
    from app.core.pagination import PageParams, paginate
    from app.domain.users.models import AppUser

    stmt = select(AppUser).where(AppUser.login.like("any%"))
    conn = await db.connection()
    with _capture_sql(conn.sync_connection) as seen, pytest.raises(ValueError, match="ORDER BY"):
        await paginate(db, stmt, PageParams())
    assert seen == []
