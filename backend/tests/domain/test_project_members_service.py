"""T71: участники проекта (plan §11.4, §10.2 п.1/п.3, §10.4 members; D-46, D-47, D-55).

AC-50, AC-53, AC-54, AC-73, AC-74; FR-15, FR-15a, FR-70.

Ожидаемый интерфейс, модуль ``app.domain.projects.members`` (все функции ``async``, ``commit()``
не вызывают)::

    list_members(db, actor, project_id, params: PageParams)
        -> tuple[list[ProjectMemberRow], bool]
        # ProjectMemberRow: user (id, login), role (Role | None), is_blocked, is_owner
        # NotFound 404 (нет / удалён / чужой ws), Forbidden 403 (not can_view_project)
    add_member(db, actor, project_id, user_id) -> None
    remove_member(db, actor, project_id, user_id) -> None

Ошибки: Forbidden 403, NotFound 404, Unprocessable 422 (коды check_recipient,
``owner_cannot_be_removed``). События (в т.ч. ленты) не пишутся (D-55).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from app.core.errors import AppError
from app.core.pagination import PageParams
from tests.factories import (
    make_project,
    make_project_member,
    make_task,
    make_user,
    make_workspace,
)
from tests.projects_support import (
    World,
    actor_of,
    capture_sql,
    events,
    fails,
    forbidden,
    make_world,
    member_ids,
    not_found,
    task_row,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.core.clock import FixedClock


@pytest.fixture
def members() -> Any:
    import app.domain.projects.members as module

    return module


async def _member_row(db: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID) -> Any:
    await db.flush()
    return (
        await db.execute(
            text("SELECT * FROM project_member WHERE project_id = :p AND user_id = :u").bindparams(
                p=project_id, u=user_id
            )
        )
    ).one_or_none()


# --- add_member ------------------------------------------------------------------------------


async def test_ac73_owner_ba_adds_member_of_each_business_role(
    db: AsyncSession, members: Any
) -> None:
    w = await make_world(db)
    for user in (w.ba3, w.usr2):
        result = await members.add_member(db, actor_of(w.ba), w.project_id, user.id)
        assert result is None
        row = await _member_row(db, w.project_id, user.id)
        assert row is not None
        assert row.workspace_id == w.ws.id  # проект и участник одного пространства
        assert row.created_by == w.ba.id
    assert await events(db, w.ws.id) == []  # D-55: member.added не пишется


async def test_ac73_ba_not_member_adds_other_and_self(db: AsyncSession, members: Any) -> None:
    """002/AC-11, AC-19: БА, не участник (ba3), добавляет другого и самого себя."""
    w = await make_world(db)
    await members.add_member(db, actor_of(w.ba3), w.project_id, w.usr2.id)
    await members.add_member(db, actor_of(w.ba3), w.project_id, w.ba3.id)
    assert {w.usr2.id, w.ba3.id} <= await member_ids(db, w.project_id)


@pytest.mark.parametrize("who", ["ba2", "ba3"])
async def test_002_ac11_ba_non_owner_adds_member(db: AsyncSession, members: Any, who: str) -> None:
    """002/AC-11 (FR-8): БА (участник не владелец и не участник) добавляет участника;
    раньше 403 (test_ac73_ac54_others_cannot_add)."""
    w = await make_world(db)
    await members.add_member(db, actor_of(getattr(w, who)), w.project_id, w.usr2.id)
    assert w.usr2.id in await member_ids(db, w.project_id)
    assert await events(db, w.ws.id) == []


@pytest.mark.parametrize("who", ["usr", "usr2", "ta", "norole"])
async def test_ac73_ac54_others_cannot_add(db: AsyncSession, members: Any, who: str) -> None:
    """002/AC-16: запрет остаётся для П, ТА, без роли."""
    w = await make_world(db)
    before = await member_ids(db, w.project_id)
    await forbidden(db, members.add_member(db, actor_of(getattr(w, who)), w.project_id, w.ba3.id))
    assert await member_ids(db, w.project_id) == before


async def test_ac54_ba_can_add_self(db: AsyncSession, members: Any) -> None:
    """Ожидание обращено по 002/AC-11 (FR-8, AC-19): запрет 001/FR-15 снят, БА добавляет себя
    (владелец - как no-op, будучи участником; не участник - становится участником)."""
    w = await make_world(db)
    other = await make_project(db, workspace_id=w.ws.id, owner_id=w.ba2.id, name="Чужой БА")
    await db.commit()
    assert await members.add_member(db, actor_of(w.ba), w.project_id, w.ba.id) is None
    await members.add_member(db, actor_of(w.ba3), other.id, w.ba3.id)
    assert w.ba3.id in await member_ids(db, other.id)
    assert w.ba.id in await member_ids(db, w.project_id)


async def test_ac74_add_recipient_codes(db: AsyncSession, members: Any) -> None:
    w = await make_world(db)
    foreign_ws = await make_workspace(db)
    foreign = await make_user(db, workspace=foreign_ws, role="user", login="w.foreign")
    await db.commit()
    cases = [
        (w.ta.id, "recipient_wrong_role"),  # ТА (AC-74)
        (w.norole.id, "recipient_wrong_role"),  # без роли (OI-102)
        (w.blocked.id, "user_blocked"),
        (foreign.id, "user_not_found"),  # чужое пространство (инвариант ревью T69)
        (uuid.uuid4(), "user_not_found"),
    ]
    before = await member_ids(db, w.project_id)
    for user_id, code in cases:
        await fails(db, members.add_member(db, actor_of(w.ba), w.project_id, user_id), code)
    assert await member_ids(db, w.project_id) == before
    assert await events(db, w.ws.id) == []


async def test_d46_add_existing_member_is_noop(db: AsyncSession, members: Any) -> None:
    w = await make_world(db)
    before = await _member_row(db, w.project_id, w.usr.id)
    await members.add_member(db, actor_of(w.ba), w.project_id, w.usr.id)
    await members.add_member(db, actor_of(w.ba3), w.project_id, w.usr.id)
    after = await _member_row(db, w.project_id, w.usr.id)
    assert (after.created_at, after.created_by) == (before.created_at, before.created_by)
    assert len(await member_ids(db, w.project_id)) == 3
    assert await events(db, w.ws.id) == []


async def test_d46_add_existing_member_still_checks_permissions(
    db: AsyncSession, members: Any
) -> None:
    w = await make_world(db)
    # ba2 (БА) заменён на usr (П): 002/AC-16, у БА 403 больше нет (AC-11)
    await forbidden(db, members.add_member(db, actor_of(w.usr), w.project_id, w.usr.id))
    await forbidden(db, members.add_member(db, actor_of(w.ta), w.project_id, w.usr.id))


async def test_d46_add_existing_member_who_got_blocked_is_422(
    db: AsyncSession, members: Any
) -> None:
    w = await make_world(db)
    await db.execute(
        text("UPDATE app_user SET is_blocked = true WHERE id = :u").bindparams(u=w.usr.id)
    )
    await db.commit()
    await fails(db, members.add_member(db, actor_of(w.ba), w.project_id, w.usr.id), "user_blocked")


async def test_fr13_add_member_foreign_deleted_unknown_project_is_404(
    db: AsyncSession, members: Any, fixed_clock: FixedClock
) -> None:
    w = await make_world(db)
    other = await make_workspace(db)
    other_ba = await make_user(db, workspace=other, role="business_admin")
    deleted = await make_project(
        db,
        workspace_id=w.ws.id,
        owner_id=w.ba.id,
        deleted_at=fixed_clock.now(),
        deleted_batch_id=uuid.uuid4(),
    )
    await db.commit()
    await not_found(db, members.add_member(db, actor_of(other_ba), w.project_id, other_ba.id))
    await not_found(db, members.add_member(db, actor_of(w.ba), deleted.id, w.usr2.id))
    await not_found(db, members.add_member(db, actor_of(w.ba), uuid.uuid4(), w.usr2.id))


async def test_p10_2_add_member_locks_project_before_recipient(
    db: AsyncSession, members: Any
) -> None:
    w = await make_world(db)
    with capture_sql(db) as seen:
        await members.add_member(db, actor_of(w.ba), w.project_id, w.usr2.id)
    low = [s.lower() for s in seen]
    project_lock = next(
        i for i, s in enumerate(low) if "for no key update" in s and "from project" in s
    )
    recipient_lock = next(
        i
        for i, s in enumerate(low)
        if "for share" in s and ("app_user" in s or "workspace_member" in s)
    )
    assert project_lock < recipient_lock


# --- remove_member ---------------------------------------------------------------------------


async def test_ac73_owner_ba_removes_member(db: AsyncSession, members: Any) -> None:
    w = await make_world(db)
    assert await members.remove_member(db, actor_of(w.ba), w.project_id, w.usr.id) is None
    assert w.usr.id not in await member_ids(db, w.project_id)
    assert await events(db, w.ws.id) == []  # D-55


async def test_ac73_ba_not_member_removes_member(db: AsyncSession, members: Any) -> None:
    """002/AC-11, AC-19: БА, не участник (ba3), исключает участника-БА (ba2)."""
    w = await make_world(db)
    await members.remove_member(db, actor_of(w.ba3), w.project_id, w.ba2.id)
    assert w.ba2.id not in await member_ids(db, w.project_id)


@pytest.mark.parametrize("who", ["ba3", "ba2"])
async def test_002_ac11_ba_non_owner_removes_other_member(
    db: AsyncSession, members: Any, who: str
) -> None:
    """002/AC-11 (FR-8): БА не владелец исключает другого участника (ранее 403)."""
    w = await make_world(db)
    await members.remove_member(db, actor_of(getattr(w, who)), w.project_id, w.usr.id)
    assert w.usr.id not in await member_ids(db, w.project_id)
    assert await events(db, w.ws.id) == []  # D-55


@pytest.mark.parametrize("who", ["usr", "ta", "norole"])
async def test_ac73_ac54_others_cannot_remove_other_member(
    db: AsyncSession, members: Any, who: str
) -> None:
    """002/AC-16: запрет остаётся для П, ТА, без роли."""
    w = await make_world(db)
    target = w.ba2
    before = await member_ids(db, w.project_id)
    await forbidden(
        db, members.remove_member(db, actor_of(getattr(w, who)), w.project_id, target.id)
    )
    assert await member_ids(db, w.project_id) == before


@pytest.mark.parametrize("who", ["ba2", "usr"])
async def test_ac53_fr15a_member_removes_self(db: AsyncSession, members: Any, who: str) -> None:
    w = await make_world(db)
    me = getattr(w, who)
    await members.remove_member(db, actor_of(me), w.project_id, me.id)
    assert me.id not in await member_ids(db, w.project_id)


async def test_ac53_remove_owner_is_422_for_everyone(db: AsyncSession, members: Any) -> None:
    w = await make_world(db)
    for actor in (w.ba, w.ba2, w.ba3):  # владелец и (002/AC-19) любой БА
        exc = await fails(
            db,
            members.remove_member(db, actor_of(actor), w.project_id, w.ba.id),
            "owner_cannot_be_removed",
        )
        assert "владение" in exc.detail  # пояснение «сначала передайте владение»
    assert w.ba.id in await member_ids(db, w.project_id)
    assert await events(db, w.ws.id) == []


async def test_ac53_after_transfer_former_owner_can_be_removed(
    db: AsyncSession, members: Any
) -> None:
    import app.domain.projects.service as svc

    w = await make_world(db)
    await svc.transfer_ownership(db, actor_of(w.ba), w.project_id, new_owner_id=w.ba2.id)
    await members.remove_member(db, actor_of(w.ba2), w.project_id, w.ba.id)
    assert w.ba.id not in await member_ids(db, w.project_id)
    await fails(
        db,
        members.remove_member(db, actor_of(w.ba3), w.project_id, w.ba2.id),
        "owner_cannot_be_removed",
    )


async def test_p11_4_remove_non_member_is_404(db: AsyncSession, members: Any) -> None:
    w = await make_world(db)
    await not_found(db, members.remove_member(db, actor_of(w.ba), w.project_id, w.usr2.id))
    await not_found(db, members.remove_member(db, actor_of(w.ba), w.project_id, uuid.uuid4()))
    # порядок §11.4: «цель не участник» (404) раньше проверки прав (403); 002/AC-16: актор - П
    await not_found(db, members.remove_member(db, actor_of(w.usr), w.project_id, w.usr2.id))


async def test_fr13_remove_member_foreign_or_deleted_project_is_404(
    db: AsyncSession, members: Any, fixed_clock: FixedClock
) -> None:
    w = await make_world(db)
    other = await make_workspace(db)
    other_ba = await make_user(db, workspace=other, role="business_admin")
    await db.commit()
    await not_found(db, members.remove_member(db, actor_of(other_ba), w.project_id, w.usr.id))
    await db.execute(
        text("UPDATE project SET deleted_at = :t, deleted_batch_id = :b WHERE id = :p").bindparams(
            t=fixed_clock.now(), b=uuid.uuid4(), p=w.project_id
        )
    )
    await db.commit()
    await not_found(db, members.remove_member(db, actor_of(w.ba), w.project_id, w.usr.id))
    assert w.usr.id in await member_ids(db, w.project_id)


async def test_fr15a_blocked_member_can_be_removed(db: AsyncSession, members: Any) -> None:
    w = await make_world(db)
    await add_blocked_member(db, w)
    await members.remove_member(db, actor_of(w.ba), w.project_id, w.blocked.id)
    assert w.blocked.id not in await member_ids(db, w.project_id)


async def add_blocked_member(db: AsyncSession, w: World) -> None:
    await make_project_member(
        db, project_id=w.project_id, user_id=w.blocked.id, workspace_id=w.ws.id
    )
    await db.commit()


async def test_ac50_q7_remove_clears_assignee_everywhere_in_project(
    db: AsyncSession, members: Any, fixed_clock: FixedClock
) -> None:
    w = await make_world(db)
    ws_id = w.ws.id
    deleted = {"deleted_at": fixed_clock.now(), "deleted_batch_id": uuid.uuid4()}
    top = await make_task(
        db, project_id=w.project_id, workspace_id=ws_id, created_by=w.ba.id, assignee_id=w.usr.id
    )
    sub = await make_task(
        db,
        project_id=w.project_id,
        workspace_id=ws_id,
        created_by=w.ba.id,
        assignee_id=w.usr.id,
        parent_id=top.id,
    )
    soft_deleted = await make_task(
        db,
        project_id=w.project_id,
        workspace_id=ws_id,
        created_by=w.ba.id,
        assignee_id=w.usr.id,
        **deleted,
    )
    deleted_sub = await make_task(
        db,
        project_id=w.project_id,
        workspace_id=ws_id,
        created_by=w.ba.id,
        assignee_id=w.usr.id,
        parent_id=top.id,
        **deleted,
    )
    other_assignee = await make_task(
        db, project_id=w.project_id, workspace_id=ws_id, created_by=w.ba.id, assignee_id=w.ba2.id
    )
    no_assignee = await make_task(
        db, project_id=w.project_id, workspace_id=ws_id, created_by=w.usr.id
    )
    other_project = await make_project(db, workspace_id=ws_id, owner_id=w.ba.id, name="Второй")
    await make_project_member(db, project_id=other_project.id, user_id=w.usr.id, workspace_id=ws_id)
    elsewhere = await make_task(
        db,
        project_id=other_project.id,
        workspace_id=ws_id,
        created_by=w.ba.id,
        assignee_id=w.usr.id,
    )
    await db.commit()

    await members.remove_member(db, actor_of(w.ba), w.project_id, w.usr.id)

    for t in (top, sub, soft_deleted, deleted_sub):
        assert (await task_row(db, t.id)).assignee_id is None
    assert (await task_row(db, other_assignee.id)).assignee_id == w.ba2.id
    assert (await task_row(db, no_assignee.id)).assignee_id is None
    assert (await task_row(db, no_assignee.id)).created_by == w.usr.id  # автор не меняется
    assert (await task_row(db, elsewhere.id)).assignee_id == w.usr.id  # другой проект
    # задачи остаются в проекте, не удаляются и не восстанавливаются
    assert (await task_row(db, top.id)).deleted_at is None
    assert (await task_row(db, soft_deleted.id)).deleted_at == deleted["deleted_at"]
    assert await events(db, ws_id) == []  # task.unassigned_member_removed не пишется (D-55)


async def test_ac50_self_remove_also_clears_assignee(db: AsyncSession, members: Any) -> None:
    w = await make_world(db)
    t = await make_task(
        db,
        project_id=w.project_id,
        workspace_id=w.ws.id,
        created_by=w.ba.id,
        assignee_id=w.ba2.id,
    )
    await db.commit()
    await members.remove_member(db, actor_of(w.ba2), w.project_id, w.ba2.id)
    assert (await task_row(db, t.id)).assignee_id is None


async def test_p10_2_remove_member_locks_project(db: AsyncSession, members: Any) -> None:
    w = await make_world(db)
    with capture_sql(db) as seen:
        await members.remove_member(db, actor_of(w.ba), w.project_id, w.usr.id)
    assert any("for no key update" in s.lower() and "from project" in s.lower() for s in seen)


async def test_d46_remove_twice_second_is_404(db: AsyncSession, members: Any) -> None:
    w = await make_world(db)
    await members.remove_member(db, actor_of(w.ba), w.project_id, w.usr.id)
    await not_found(db, members.remove_member(db, actor_of(w.ba), w.project_id, w.usr.id))


# --- list_members ----------------------------------------------------------------------------


async def test_d45_list_members_order_flags_and_roles(db: AsyncSession, members: Any) -> None:
    w = await make_world(db)
    await add_blocked_member(db, w)
    norole_member = await make_user(db, workspace=w.ws, role=None, login="w.norole.member")
    await make_project_member(
        db, project_id=w.project_id, user_id=norole_member.id, workspace_id=w.ws.id
    )
    other = await make_project(db, workspace_id=w.ws.id, owner_id=w.ba2.id, name="Другой")
    await make_project_member(db, project_id=other.id, user_id=w.usr2.id, workspace_id=w.ws.id)
    await db.commit()

    rows, has_next = await members.list_members(db, actor_of(w.ba), w.project_id, PageParams())
    assert has_next is False
    assert [r.user.login for r in rows] == [
        "w.ba",
        "w.ba2",
        "w.blocked",
        "w.norole.member",
        "w.usr",
    ]
    by_login = {r.user.login: r for r in rows}
    assert by_login["w.ba"].user.id == w.ba.id
    assert by_login["w.ba"].is_owner is True
    assert by_login["w.ba2"].is_owner is False
    assert by_login["w.ba"].role == "business_admin"
    assert by_login["w.usr"].role == "user"
    assert by_login["w.blocked"].is_blocked is True
    assert by_login["w.usr"].is_blocked is False
    assert by_login["w.norole.member"].role is None


async def test_d45_list_members_who_can_view(db: AsyncSession, members: Any) -> None:
    w = await make_world(db)
    for who in (w.ba, w.ba2, w.ba3, w.usr):  # БА — любой проект; П — участник
        rows, _ = await members.list_members(db, actor_of(who), w.project_id, PageParams())
        assert len(rows) == 3
    for who in (w.usr2, w.ta, w.norole):
        await forbidden(db, members.list_members(db, actor_of(who), w.project_id, PageParams()))


async def test_d45_list_members_404_foreign_deleted(
    db: AsyncSession, members: Any, fixed_clock: FixedClock
) -> None:
    w = await make_world(db)
    other = await make_workspace(db)
    other_ba = await make_user(db, workspace=other, role="business_admin")
    await db.commit()
    await not_found(db, members.list_members(db, actor_of(other_ba), w.project_id, PageParams()))
    await not_found(db, members.list_members(db, actor_of(w.ba), uuid.uuid4(), PageParams()))


async def test_ac22_list_members_paginated(db: AsyncSession, members: Any) -> None:
    w = await make_world(db)
    p1, n1 = await members.list_members(
        db, actor_of(w.ba), w.project_id, PageParams(page=1, page_size=2)
    )
    p2, n2 = await members.list_members(
        db, actor_of(w.ba), w.project_id, PageParams(page=2, page_size=2)
    )
    assert [r.user.login for r in p1] == ["w.ba", "w.ba2"]
    assert n1 is True
    assert [r.user.login for r in p2] == ["w.usr"]
    assert n2 is False


# --- гонки (committed): блокировка проекта сериализует изменения состава ----------------------


async def _blocked_until_commit(task: asyncio.Future[Any], what: str) -> None:
    done, _ = await asyncio.wait({task}, timeout=0.5)
    assert not done, f"{what} не ждёт блокировку проекта (FOR NO KEY UPDATE, §10.2 п.1)"


@pytest.mark.committed
async def test_p10_2_second_add_member_waits_for_first(
    committed: async_sessionmaker[AsyncSession], members: Any
) -> None:
    async with committed() as setup:
        w = await make_world(setup)
    holder = committed()
    try:
        await members.add_member(holder, actor_of(w.ba), w.project_id, w.usr2.id)  # без commit

        async def second() -> None:
            async with committed() as s:
                await members.add_member(s, actor_of(w.ba2), w.project_id, w.ba3.id)
                await s.commit()

        task = asyncio.ensure_future(second())
        await _blocked_until_commit(task, "второй add_member")
        await holder.commit()
    finally:
        await holder.close()
    await asyncio.wait_for(task, timeout=10)
    async with committed() as s:
        assert {w.usr2.id, w.ba3.id} <= await member_ids(s, w.project_id)


@pytest.mark.committed
async def test_p10_2_parallel_add_same_member_is_idempotent(
    committed: async_sessionmaker[AsyncSession], members: Any
) -> None:
    async with committed() as setup:
        w = await make_world(setup)
    go = asyncio.Event()

    async def add(actor_user: Any) -> str:
        async with committed() as s:
            await go.wait()
            try:
                await members.add_member(s, actor_of(actor_user), w.project_id, w.usr2.id)
                await s.commit()
            except AppError as exc:  # ошибка целостности (DBAPIError) проваливает тест
                await s.rollback()
                return str(exc.code)
            return "ok"

    jobs = [asyncio.ensure_future(add(w.ba)), asyncio.ensure_future(add(w.ba3))]
    await asyncio.sleep(0)
    go.set()
    assert await asyncio.gather(*jobs) == ["ok", "ok"]
    async with committed() as s:
        rows = (
            await s.execute(
                text(
                    "SELECT count(*) FROM project_member WHERE project_id=:p AND user_id=:u"
                ).bindparams(p=w.project_id, u=w.usr2.id)
            )
        ).scalar_one()
        assert rows == 1


@pytest.mark.committed
async def test_p10_2_remove_member_waits_and_add_after_remove_wins(
    committed: async_sessionmaker[AsyncSession], members: Any
) -> None:
    """remove (держит проект) -> add того же пользователя ждёт и выполняется после."""
    async with committed() as setup:
        w = await make_world(setup)
    holder = committed()
    try:
        await members.remove_member(holder, actor_of(w.ba), w.project_id, w.usr.id)

        async def add() -> None:
            async with committed() as s:
                await members.add_member(s, actor_of(w.ba), w.project_id, w.usr.id)
                await s.commit()

        task = asyncio.ensure_future(add())
        await _blocked_until_commit(task, "add_member")
        await holder.commit()
    finally:
        await holder.close()
    await asyncio.wait_for(task, timeout=10)
    async with committed() as s:
        assert w.usr.id in await member_ids(s, w.project_id)


@pytest.mark.committed
async def test_p10_2_remove_waits_for_concurrent_add_and_clears_new_member_assignee(
    committed: async_sessionmaker[AsyncSession], members: Any
) -> None:
    """Исключение и добавление одного пользователя сериализованы: итог — не участник и
    не исполнитель, без ошибок целостности (задача с исполнителем создана заранее)."""
    async with committed() as setup:
        w = await make_world(setup)
        t = await make_task(
            setup,
            project_id=w.project_id,
            workspace_id=w.ws.id,
            created_by=w.ba.id,
            assignee_id=w.usr.id,
        )
        await setup.commit()
    holder = committed()
    try:
        await members.add_member(
            holder, actor_of(w.ba), w.project_id, w.usr.id
        )  # no-op, но с блокировкой

        async def remove() -> None:
            async with committed() as s:
                await members.remove_member(s, actor_of(w.ba), w.project_id, w.usr.id)
                await s.commit()

        task = asyncio.ensure_future(remove())
        await _blocked_until_commit(task, "remove_member")
        await holder.commit()
    finally:
        await holder.close()
    await asyncio.wait_for(task, timeout=10)
    async with committed() as s:
        assert w.usr.id not in await member_ids(s, w.project_id)
        assert (await task_row(s, t.id)).assignee_id is None
