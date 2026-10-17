"""T35: справочник пользователей и загрузка получателей (plan §10.2 п.3, §10.4 directory, D-24).

AC-21 (только своё пространство), FR-13, FR-70 (факты получателя), D-24 (ILIKE с экранированием).

Ожидаемый интерфейс, модуль ``app.domain.users.directory`` (по заданию T35)::

    list_directory(db, actor: Actor, params: PageParams, *, q: str | None)
        -> tuple[list[DirectoryUser{id, login, role}], bool]   # (items, has_next)
        # пространство берётся из actor.workspace_id; PageParams(page=, page_size=)
    load_recipient(db, workspace_id, user_id, *, lock: bool) -> RecipientFacts
    user_refs(db, workspace_id, ids) -> dict[UUID, UserRef{id, login}]       # один SELECT

Нет сети; БД ``tracker_test``; данные откатываются (фикстура ``db``) либо чистая схема
(``committed``) в тесте блокировок.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError

from app.core.pagination import PageParams
from app.domain.access.recipients import RecipientFacts
from app.domain.access.roles import Actor, Role
from tests.factories import UserRow, make_user, make_workspace

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
def directory() -> Any:
    import app.domain.users.directory as module

    return module


def _actor(ws: Any) -> Actor:
    return Actor(
        user_id=uuid.uuid4(),
        workspace_id=ws.id,
        login="actor.biz",
        role=Role.BUSINESS_ADMIN,
        must_change_password=False,
        session_id=b"\x00" * 32,
    )


async def _page(
    directory: Any, db: AsyncSession, ws: Any, *, q: str | None, page: int, page_size: int
) -> tuple[list[Any], bool]:
    params = PageParams(page=page, page_size=page_size)
    items, has_next = await directory.list_directory(db, _actor(ws), params, q=q)
    return list(items), has_next


async def _list(directory: Any, db: AsyncSession, ws: Any, **kw: Any) -> list[Any]:
    kw.setdefault("q", None)
    kw.setdefault("page", 1)
    kw.setdefault("page_size", 100)
    items, has_next = await _page(directory, db, ws, **kw)
    assert isinstance(has_next, bool)
    return list(items)


def _logins(items: list[Any]) -> list[str]:
    return [i.login for i in items]


# --- list_directory --------------------------------------------------------------------------


async def test_ac21_directory_contains_only_unblocked_business_roles_of_own_workspace(
    db: AsyncSession, directory: Any
) -> None:
    ws = await make_workspace(db)
    other = await make_workspace(db)
    await make_user(db, workspace=ws, role="tech_admin", login="dir.ta")
    await make_user(db, workspace=ws, role=None, login="dir.norole")
    await make_user(db, workspace=ws, role="user", login="dir.blocked", blocked=True)
    await make_user(db, workspace=other, role="user", login="dir.foreign")
    ba = await make_user(db, workspace=ws, role="business_admin", login="dir.ba")
    usr = await make_user(db, workspace=ws, role="user", login="dir.user")

    items = await _list(directory, db, ws)

    assert _logins(items) == ["dir.ba", "dir.user"]
    assert [i.id for i in items] == [ba.id, usr.id]
    assert [Role(i.role) for i in items] == [Role.BUSINESS_ADMIN, Role.USER]


async def test_ac21_other_workspace_sees_only_its_own_users(
    db: AsyncSession, directory: Any
) -> None:
    ws1 = await make_workspace(db)
    ws2 = await make_workspace(db)
    await make_user(db, workspace=ws1, role="user", login="w1.user")
    await make_user(db, workspace=ws2, role="user", login="w2.user")
    assert _logins(await _list(directory, db, ws1)) == ["w1.user"]
    assert _logins(await _list(directory, db, ws2)) == ["w2.user"]


async def test_t35_directory_order_is_login_then_id(db: AsyncSession, directory: Any) -> None:
    ws = await make_workspace(db)
    for login in ("zeta.one", "alpha.two", "mid.three"):
        await make_user(db, workspace=ws, role="user", login=login)
    assert _logins(await _list(directory, db, ws)) == ["alpha.two", "mid.three", "zeta.one"]


async def test_t35_q_is_case_insensitive_substring_of_login(
    db: AsyncSession, directory: Any
) -> None:
    ws = await make_workspace(db)
    for login in ("ivan.petrov", "petr.ivanov", "olga.sidorova"):
        await make_user(db, workspace=ws, role="user", login=login)
    assert _logins(await _list(directory, db, ws, q="IVAN")) == ["ivan.petrov", "petr.ivanov"]
    assert _logins(await _list(directory, db, ws, q="sidor")) == ["olga.sidorova"]
    assert await _list(directory, db, ws, q="nomatch") == []


async def test_d24_q_underscore_is_literal_not_single_char_wildcard(
    db: AsyncSession, directory: Any
) -> None:
    ws = await make_workspace(db)
    for login in ("a_b", "axb", "a.b"):
        await make_user(db, workspace=ws, role="user", login=login)
    assert _logins(await _list(directory, db, ws, q="a_b")) == ["a_b"]


async def test_d24_q_percent_is_literal_not_mask(db: AsyncSession, directory: Any) -> None:
    """Логины не содержат ``%`` (FR-73): литерал не находит ничего; маска нашла бы все."""
    ws = await make_workspace(db)
    for login in ("axxb", "ab.cd", "plain"):
        await make_user(db, workspace=ws, role="user", login=login)
    assert await _list(directory, db, ws, q="%") == []
    assert await _list(directory, db, ws, q="a%b") == []


async def test_d24_q_backslash_is_literal(db: AsyncSession, directory: Any) -> None:
    """Без экранирования ``a\\b`` в LIKE совпал бы с ``ab``; одиночный ``\\`` ломал бы шаблон."""
    ws = await make_workspace(db)
    for login in ("ab.cd", "a_b", "plain"):
        await make_user(db, workspace=ws, role="user", login=login)
    assert await _list(directory, db, ws, q="a\\b") == []
    assert await _list(directory, db, ws, q="\\") == []
    assert await _list(directory, db, ws, q="x\\") == []


async def test_t35_pagination_page_size_and_has_next(db: AsyncSession, directory: Any) -> None:
    ws = await make_workspace(db)
    for i in range(5):
        await make_user(db, workspace=ws, role="user", login=f"pg.user{i}")

    p1, n1 = await _page(directory, db, ws, q=None, page=1, page_size=2)
    p2, n2 = await _page(directory, db, ws, q=None, page=2, page_size=2)
    p3, n3 = await _page(directory, db, ws, q=None, page=3, page_size=2)

    assert (_logins(p1), n1) == (["pg.user0", "pg.user1"], True)
    assert (_logins(p2), n2) == (["pg.user2", "pg.user3"], True)
    assert (_logins(p3), n3) == (["pg.user4"], False)


async def test_t35_pagination_exact_fit_has_no_next(db: AsyncSession, directory: Any) -> None:
    ws = await make_workspace(db)
    for i in range(2):
        await make_user(db, workspace=ws, role="user", login=f"ex.user{i}")
    items, has_next = await _page(directory, db, ws, q=None, page=1, page_size=2)
    assert len(items) == 2
    assert has_next is False


async def test_t35_directory_does_not_load_password_hash(db: AsyncSession, directory: Any) -> None:
    ws = await make_workspace(db)
    user = await make_user(db, workspace=ws, role="user", login="nohash.user")
    conn = db.get_bind()
    seen: list[str] = []

    def on_execute(c: Any, cursor: Any, statement: str, *a: Any) -> None:
        seen.append(statement)

    event.listen(conn, "before_cursor_execute", on_execute)
    try:
        items = await _list(directory, db, ws)
    finally:
        event.remove(conn, "before_cursor_execute", on_execute)

    assert _logins(items) == ["nohash.user"]
    selects = [s for s in seen if s.lstrip().lower().startswith("select")]
    assert selects, "справочник не выполнил SELECT"
    for statement in selects:
        assert "password_hash" not in statement
        assert "failed_login_count" not in statement
    for item in items:
        assert not hasattr(item, "password_hash")
        assert user.password_hash not in repr(item)


async def _capture_selects(db: AsyncSession, coro_factory: Any) -> tuple[Any, list[str]]:
    conn = db.get_bind()
    seen: list[str] = []

    def on_execute(c: Any, cursor: Any, statement: str, *a: Any) -> None:
        seen.append(statement)

    event.listen(conn, "before_cursor_execute", on_execute)
    try:
        result = await coro_factory()
    finally:
        event.remove(conn, "before_cursor_execute", on_execute)
    return result, [s for s in seen if s.lstrip().lower().startswith("select")]


async def test_t35_list_directory_is_one_select_with_role_join(
    db: AsyncSession, directory: Any
) -> None:
    """Список и роль — одним SELECT (JOIN workspace_member, role IN БА/П): нет гонки."""
    ws = await make_workspace(db)
    for i in range(3):
        await make_user(db, workspace=ws, role="user", login=f"one.u{i}")

    items, selects = await _capture_selects(db, lambda: _list(directory, db, ws))

    assert len(items) == 3
    assert len(selects) == 1, selects
    sql = " ".join(selects[0].lower().split())
    assert "workspace_member" in sql and "join" in sql
    assert "workspace_member.role in" in sql
    assert "password_hash" not in sql


async def test_t35_list_directory_role_is_consistent_with_membership_snapshot(
    db: AsyncSession, directory: Any
) -> None:
    """Роль в выдаче равна workspace_member.role; ТА и без роли в выдачу не попадают."""
    ws = await make_workspace(db)
    await make_user(db, workspace=ws, role="tech_admin", login="snap.ta")
    await make_user(db, workspace=ws, role=None, login="snap.none")
    await make_user(db, workspace=ws, role="business_admin", login="snap.ba")
    await make_user(db, workspace=ws, role="user", login="snap.user")

    items = await _list(directory, db, ws)
    rows = (
        await db.execute(
            text(
                "SELECT u.id, wm.role FROM app_user u JOIN workspace_member wm "
                "ON wm.user_id = u.id WHERE wm.workspace_id = :w"
            ).bindparams(w=ws.id)
        )
    ).all()
    member_role = {r.id: r.role for r in rows}

    assert _logins(items) == ["snap.ba", "snap.user"]
    for item in items:
        assert member_role[item.id] is not None
        assert Role(item.role) == Role(member_role[item.id])
        assert Role(item.role) is not Role.TECH_ADMIN


# --- load_recipient --------------------------------------------------------------------------


async def test_fr70_load_recipient_member_facts(db: AsyncSession, directory: Any) -> None:
    ws = await make_workspace(db)
    user = await make_user(db, workspace=ws, role="business_admin")

    facts = await directory.load_recipient(db, ws.id, user.id, lock=False)

    assert isinstance(facts, RecipientFacts)
    assert facts == RecipientFacts(
        user_id=user.id, in_workspace=True, is_blocked=False, role=Role.BUSINESS_ADMIN
    )


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        ("tech_admin", Role.TECH_ADMIN),
        ("user", Role.USER),
        (None, None),
    ],
)
async def test_fr70_load_recipient_role_comes_from_membership(
    db: AsyncSession, directory: Any, role: str | None, expected: Role | None
) -> None:
    ws = await make_workspace(db)
    user = await make_user(db, workspace=ws, role=role)
    facts = await directory.load_recipient(db, ws.id, user.id, lock=False)
    assert facts.in_workspace is True
    assert facts.role == expected


async def test_fr70_load_recipient_blocked_user(db: AsyncSession, directory: Any) -> None:
    ws = await make_workspace(db)
    user = await make_user(db, workspace=ws, role="user", blocked=True)
    facts = await directory.load_recipient(db, ws.id, user.id, lock=False)
    assert facts.in_workspace is True
    assert facts.is_blocked is True
    assert facts.role == Role.USER


async def test_ac21_load_recipient_foreign_workspace_is_not_in_workspace(
    db: AsyncSession, directory: Any
) -> None:
    ws = await make_workspace(db)
    other = await make_workspace(db)
    foreign = await make_user(db, workspace=other, role="user")
    facts = await directory.load_recipient(db, ws.id, foreign.id, lock=False)
    assert facts.user_id == foreign.id
    assert facts.in_workspace is False
    assert facts.role is None


async def test_fr70_load_recipient_unknown_user_is_not_in_workspace(
    db: AsyncSession, directory: Any
) -> None:
    ws = await make_workspace(db)
    unknown = uuid.uuid4()
    facts = await directory.load_recipient(db, ws.id, unknown, lock=True)
    assert facts.user_id == unknown
    assert facts.in_workspace is False
    assert facts.role is None


async def _nowait_lock(
    maker: async_sessionmaker[AsyncSession], table: str, col: str, v: Any, mode: str
) -> None:
    async with maker() as session:
        await session.execute(
            text(f"SELECT 1 FROM {table} WHERE {col} = :v FOR {mode} NOWAIT").bindparams(v=v)  # noqa: S608
        )
        await session.rollback()


async def _nowait_update(
    maker: async_sessionmaker[AsyncSession], table: str, col: str, v: Any
) -> None:
    await _nowait_lock(maker, table, col, v, "UPDATE")


@pytest.mark.parametrize("mode", ["UPDATE", "NO KEY UPDATE"])
@pytest.mark.parametrize(("table", "col"), [("app_user", "id"), ("workspace_member", "user_id")])
async def test_p10_2_load_recipient_lock_true_takes_share_lock(
    committed: async_sessionmaker[AsyncSession],
    directory: Any,
    table: str,
    col: str,
    mode: str,
) -> None:
    """lock=True: FOR SHARE на app_user и workspace_member; FOR [NO KEY] UPDATE NOWAIT падает.

    FOR KEY SHARE не конфликтует с FOR NO KEY UPDATE, поэтому вариант NO KEY UPDATE ловит его.
    """
    async with committed() as setup:
        ws = await make_workspace(setup)
        user: UserRow = await make_user(setup, workspace=ws, role="user")
        await setup.commit()

    async with committed() as holder:
        facts = await directory.load_recipient(holder, ws.id, user.id, lock=True)
        assert facts.in_workspace is True
        with pytest.raises(DBAPIError, match="could not obtain lock|lock"):
            await _nowait_lock(committed, table, col, user.id, mode)
        # другая транзакция с FOR SHARE проходит (блокировка именно разделяемая)
        await _nowait_lock(committed, table, col, user.id, "SHARE")
        await holder.rollback()
    # после освобождения блокировки строка снова доступна
    await _nowait_lock(committed, table, col, user.id, mode)


@pytest.mark.parametrize(("table", "col"), [("app_user", "id"), ("workspace_member", "user_id")])
async def test_p10_2_load_recipient_lock_false_does_not_lock(
    committed: async_sessionmaker[AsyncSession], directory: Any, table: str, col: str
) -> None:
    async with committed() as setup:
        ws = await make_workspace(setup)
        user = await make_user(setup, workspace=ws, role="user")
        await setup.commit()

    async with committed() as holder:
        await directory.load_recipient(holder, ws.id, user.id, lock=False)
        await _nowait_update(committed, table, col, user.id)  # не бросает
        await holder.rollback()


# --- user_refs -------------------------------------------------------------------------------


async def test_t35_user_refs_returns_id_and_login_in_one_query(
    db: AsyncSession, directory: Any
) -> None:
    ws = await make_workspace(db)
    users = [await make_user(db, workspace=ws, role="user", login=f"ref.u{i}") for i in range(4)]
    blocked = await make_user(db, workspace=ws, role=None, login="ref.blocked", blocked=True)
    ids = [u.id for u in users] + [blocked.id]
    conn = db.get_bind()
    seen: list[str] = []

    def on_execute(c: Any, cursor: Any, statement: str, *a: Any) -> None:
        seen.append(statement)

    event.listen(conn, "before_cursor_execute", on_execute)
    try:
        refs = await directory.user_refs(db, ws.id, ids)
    finally:
        event.remove(conn, "before_cursor_execute", on_execute)

    assert len(seen) == 1, seen
    assert "password_hash" not in seen[0]
    assert set(refs) == set(ids)
    for u in users + [blocked]:
        assert refs[u.id].id == u.id
        assert refs[u.id].login == u.login


async def test_t35_user_refs_skips_unknown_ids_and_accepts_empty(
    db: AsyncSession, directory: Any
) -> None:
    ws = await make_workspace(db)
    user = await make_user(db, workspace=ws, role="user", login="ref.known")
    refs = await directory.user_refs(db, ws.id, [user.id, uuid.uuid4()])
    assert list(refs) == [user.id]
    assert refs[user.id].login == "ref.known"
    assert await directory.user_refs(db, ws.id, []) == {}


async def test_ac21_user_refs_skips_ids_of_other_workspace(
    db: AsyncSession, directory: Any
) -> None:
    ws = await make_workspace(db)
    other = await make_workspace(db)
    mine = await make_user(db, workspace=ws, role="user", login="ref.mine")
    foreign = await make_user(db, workspace=other, role="user", login="ref.foreign")

    refs = await directory.user_refs(db, ws.id, [mine.id, foreign.id])

    assert list(refs) == [mine.id]
    assert foreign.id not in refs
    assert await directory.user_refs(db, other.id, [mine.id]) == {}
