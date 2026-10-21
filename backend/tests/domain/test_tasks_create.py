"""T74: создание задачи и подзадачи (plan §11.4, §11.5, §4.5, §10.2, §10.4; D-46, D-51, D-52, D-55).

AC-8, AC-9, AC-24, AC-47, AC-49, AC-56, AC-61, AC-68 (формат срока), AC-74 (исполнитель),
AC-106, AC-108, AC-109; FR-18...FR-21, FR-28a; заметки ревью T69/T70/T73.

Ожидаемый интерфейс (все функции ``async``, ``commit()`` не вызывают)::

    app.domain.tasks.context
        @dataclass(frozen=True) TaskContext(project: ProjectFacts, task: TaskFacts,
                                            task_id: UUID, status: TaskStatus,
                                            position: int | None)
        load_task_context(db, actor, task_id, *, lock_project: Literal["share"] | None = None)
            -> TaskContext        # NotFound (404): нет, мягко удалена, чужой ws, проект удалён
    app.domain.tasks.service
        UNSET                     # сентинел «исполнитель не передан»
        @dataclass(frozen=True) TaskCreateData(title: str, description: str = "",
            assignee: UUID | None | Unset = UNSET, due_date: date | None = None,
            priority: TaskPriority | str = "medium")
        create_task(db, actor, project_id, data: TaskCreateData) -> UUID
        create_subtask(db, actor, parent_id, data: TaskCreateData) -> UUID

Ошибки: NotFound (404), Forbidden (403), Unprocessable (422): ``validation_error``,
``subtask_depth_exceeded``, коды получателя (``user_not_found``, ``user_blocked``,
``recipient_wrong_role``, ``not_project_member``). Порядок: проект/родитель 404 -> FOR SHARE
проекта -> права 403 -> (для подзадачи) глубина 422 -> получатель 422 -> вставка.
Событий не пишут (D-55).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.domain.access.policy import ProjectFacts, TaskFacts
from tests.factories import make_project, make_task, make_user, make_workspace
from tests.projects_support import (
    LONG_DESC_10000,
    LONG_NAME_255,
    World,
    actor_of,
    add_member_row,
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


@pytest.fixture
def svc() -> Any:
    import app.domain.tasks.service as module

    return module


@pytest.fixture
def ctx_mod() -> Any:
    import app.domain.tasks.context as module

    return module


def _data(svc: Any, title: str = "Задача", **kw: Any) -> Any:
    return svc.TaskCreateData(title=title, **kw)


async def _count_tasks(db: AsyncSession, project_id: uuid.UUID) -> int:
    await db.flush()
    return int(
        (
            await db.execute(
                text("SELECT count(*) FROM task WHERE project_id = :p").bindparams(p=project_id)
            )
        ).scalar_one()
    )


async def _parent(
    db: AsyncSession, w: World, *, assignee: uuid.UUID | None, created_by: uuid.UUID | None = None
) -> uuid.UUID:
    row = await make_task(
        db,
        project_id=w.project_id,
        workspace_id=w.ws.id,
        created_by=created_by or w.ba.id,
        assignee_id=assignee,
    )
    await db.commit()
    return row.id


# --- load_task_context -----------------------------------------------------------------------


async def test_p10_4_load_task_context_returns_facts(db: AsyncSession, ctx_mod: Any) -> None:
    w = await make_world(db)
    row = await make_task(
        db,
        project_id=w.project_id,
        workspace_id=w.ws.id,
        created_by=w.ba.id,
        assignee_id=w.usr.id,
        status="review",
        position=4096,
    )
    sub = await make_task(
        db,
        project_id=w.project_id,
        workspace_id=w.ws.id,
        created_by=w.ba2.id,
        parent_id=row.id,
    )
    await db.commit()
    c = await ctx_mod.load_task_context(db, actor_of(w.usr), row.id)
    assert c.project == ProjectFacts(
        project_id=w.project_id, owner_id=w.ba.id, actor_is_member=True
    )
    assert c.task == TaskFacts(created_by=w.ba.id, assignee_id=w.usr.id, parent_id=None)
    assert c.task_id == row.id
    assert str(c.status) == "review"
    assert c.position == 4096
    s = await ctx_mod.load_task_context(db, actor_of(w.ba3), sub.id)
    assert s.project.actor_is_member is False  # БА не участник: факты — как есть
    assert s.task == TaskFacts(created_by=w.ba2.id, assignee_id=None, parent_id=row.id)
    assert s.position is None


async def test_fr13_load_task_context_404_unknown_deleted_foreign_deleted_project(
    db: AsyncSession, ctx_mod: Any
) -> None:
    w = await make_world(db)
    other_ws = await make_workspace(db)
    other_owner = await make_user(db, workspace=other_ws, role="business_admin", login="o.ba")
    foreign_project = await make_project(db, workspace_id=other_ws.id, owner_id=other_owner.id)
    foreign = await make_task(
        db, project_id=foreign_project.id, workspace_id=other_ws.id, created_by=other_owner.id
    )
    deleted = await make_task(
        db,
        project_id=w.project_id,
        workspace_id=w.ws.id,
        created_by=w.ba.id,
        deleted_at=datetime(2026, 1, 1),
    )
    dead_project = await make_project(
        db, workspace_id=w.ws.id, owner_id=w.ba.id, name="Удалён", deleted_at=datetime(2026, 1, 1)
    )
    in_dead = await make_task(
        db, project_id=dead_project.id, workspace_id=w.ws.id, created_by=w.ba.id
    )
    await db.commit()
    for tid in (uuid.uuid4(), foreign.id, deleted.id, in_dead.id):
        for lock in (None, "share"):
            await not_found(
                db, ctx_mod.load_task_context(db, actor_of(w.ba), tid, lock_project=lock)
            )


async def test_p10_2_load_task_context_share_lock_sql(db: AsyncSession, ctx_mod: Any) -> None:
    w = await make_world(db)
    tid = await _parent(db, w, assignee=None)
    with capture_sql(db) as seen:
        await ctx_mod.load_task_context(db, actor_of(w.ba), tid, lock_project="share")
    locking = [s for s in seen if "for share" in s.lower()]
    assert locking, seen
    assert any("project" in s.lower() for s in locking)
    with capture_sql(db) as seen2:
        await ctx_mod.load_task_context(db, actor_of(w.ba), tid)
    assert not [s for s in seen2 if "for share" in s.lower() or "for update" in s.lower()], seen2


@pytest.mark.committed
async def test_p10_2_load_task_context_share_lock_conflicts(
    committed: async_sessionmaker[AsyncSession], ctx_mod: Any
) -> None:
    """FOR SHARE на проекте: конфликтует с FOR NO KEY UPDATE, совместим с FOR SHARE."""
    async with committed() as setup:
        w = await make_world(setup)
        tid = await _parent(setup, w, assignee=None)

    async def nowait(mode: str) -> None:
        async with committed() as s:
            await s.execute(
                text(f"SELECT 1 FROM project WHERE id = :p {mode} NOWAIT").bindparams(  # noqa: S608
                    p=w.project_id
                )
            )
            await s.rollback()

    async with committed() as holder:
        await ctx_mod.load_task_context(holder, actor_of(w.ba), tid, lock_project="share")
        with pytest.raises(DBAPIError, match="lock"):
            await nowait("FOR NO KEY UPDATE")
        await nowait("FOR SHARE")
        await holder.rollback()
    await nowait("FOR NO KEY UPDATE")


# --- create_task: исполнитель и права -------------------------------------------------------


async def test_ac109_user_without_assignee_gets_self(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    tid = await svc.create_task(db, actor_of(w.usr), w.project_id, _data(svc))
    assert isinstance(tid, uuid.UUID)
    row = await task_row(db, tid)
    assert row.assignee_id == w.usr.id
    assert row.created_by == w.usr.id


async def test_ac109_user_explicit_null_is_403(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    await forbidden(
        db, svc.create_task(db, actor_of(w.usr), w.project_id, _data(svc, assignee=None))
    )
    assert await _count_tasks(db, w.project_id) == 0


async def test_ac9_user_assigns_self_ok_other_403(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    tid = await svc.create_task(db, actor_of(w.usr), w.project_id, _data(svc, assignee=w.usr.id))
    assert (await task_row(db, tid)).assignee_id == w.usr.id
    await db.commit()  # rollback в forbidden() не должен стереть созданную задачу
    await forbidden(
        db, svc.create_task(db, actor_of(w.usr), w.project_id, _data(svc, assignee=w.ba2.id))
    )
    assert await _count_tasks(db, w.project_id) == 1


@pytest.mark.parametrize("who", ["ba", "ba3"])
async def test_ac56_ba_owner_and_ba_member_without_assignee_gets_null(
    db: AsyncSession, svc: Any, who: str
) -> None:
    w = await make_world(db)
    await add_member_row(db, w, w.project_id, w.ba3)
    await db.commit()
    actor = actor_of(getattr(w, who))
    for data in (_data(svc), _data(svc, assignee=None)):
        tid = await svc.create_task(db, actor, w.project_id, data)
        row = await task_row(db, tid)
        assert row.assignee_id is None
        assert row.created_by == actor.user_id


@pytest.mark.parametrize("who", ["ba", "ba3", "ba2"])
async def test_br1_ba_members_assign_project_member(db: AsyncSession, svc: Any, who: str) -> None:
    w = await make_world(db)
    await add_member_row(db, w, w.project_id, w.ba3)
    await db.commit()
    tid = await svc.create_task(
        db, actor_of(getattr(w, who)), w.project_id, _data(svc, assignee=w.usr.id)
    )
    assert (await task_row(db, tid)).assignee_id == w.usr.id


async def test_ac56_assignee_not_member_is_422(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    await fails(
        db,
        svc.create_task(db, actor_of(w.ba), w.project_id, _data(svc, assignee=w.usr2.id)),
        "not_project_member",
    )
    assert await _count_tasks(db, w.project_id) == 0


async def _recipient_cases(db: AsyncSession, w: World) -> list[tuple[uuid.UUID, str]]:
    other_ws = await make_workspace(db)
    foreigner = await make_user(db, workspace=other_ws, role="user", login="f.usr")
    blocked_member = await make_user(
        db, workspace=w.ws, role="user", login="w.blockedm", blocked=True
    )
    await add_member_row(db, w, w.project_id, blocked_member)
    await add_member_row(db, w, w.project_id, w.ta)  # ТА участник строкой — всё равно 422
    await add_member_row(db, w, w.project_id, w.norole)
    await db.commit()
    return [
        (w.usr2.id, "not_project_member"),
        (w.ba3.id, "not_project_member"),
        (w.ta.id, "recipient_wrong_role"),
        (w.norole.id, "recipient_wrong_role"),
        (w.blocked.id, "user_blocked"),
        (blocked_member.id, "user_blocked"),
        (foreigner.id, "user_not_found"),
        (uuid.uuid4(), "user_not_found"),
    ]


async def test_ac74_ac56_create_task_recipient_codes(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    cases = await _recipient_cases(db, w)
    for target, code in cases:
        await fails(
            db,
            svc.create_task(db, actor_of(w.ba), w.project_id, _data(svc, assignee=target)),
            code,
        )
    assert await _count_tasks(db, w.project_id) == 0


async def test_ac74_create_subtask_recipient_codes(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    cases = await _recipient_cases(db, w)
    parent = await _parent(db, w, assignee=w.usr.id)
    for target, code in cases:
        await fails(
            db,
            svc.create_subtask(db, actor_of(w.ba), parent, _data(svc, assignee=target)),
            code,
        )
    assert await _count_tasks(db, w.project_id) == 1


async def test_ac106_ba_not_member_is_403(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    for data in (_data(svc), _data(svc, assignee=w.ba3.id), _data(svc, assignee=w.usr.id)):
        await forbidden(db, svc.create_task(db, actor_of(w.ba3), w.project_id, data))
    assert await _count_tasks(db, w.project_id) == 0


@pytest.mark.parametrize("who", ["usr2", "ta", "norole"])
async def test_ac106_non_member_or_no_business_access_is_403(
    db: AsyncSession, svc: Any, who: str
) -> None:
    """Параметр ``sm`` (прежде СМ-не-участник) удалён: дословно дублировал БА-не-участника
    ``ba3`` из ``test_ac106_ba_not_member_is_403`` выше (002/AC-15, NFR-3 (в))."""
    w = await make_world(db)
    user = getattr(w, who)
    await forbidden(
        db, svc.create_task(db, actor_of(user), w.project_id, _data(svc, assignee=user.id))
    )
    assert await _count_tasks(db, w.project_id) == 0


async def test_fr13_create_task_project_404_unknown_deleted_foreign(
    db: AsyncSession, svc: Any
) -> None:
    w = await make_world(db)
    other_ws = await make_workspace(db)
    other_owner = await make_user(db, workspace=other_ws, role="business_admin", login="o.ba")
    foreign = await make_project(db, workspace_id=other_ws.id, owner_id=other_owner.id)
    dead = await make_project(
        db, workspace_id=w.ws.id, owner_id=w.ba.id, name="Удалён", deleted_at=datetime(2026, 1, 1)
    )
    await db.commit()
    for pid in (uuid.uuid4(), foreign.id, dead.id):
        await not_found(db, svc.create_task(db, actor_of(w.ba), pid, _data(svc)))


async def test_p4_5_order_404_then_403_then_422_recipient(db: AsyncSession, svc: Any) -> None:
    """Проект 404 раньше прав 403; права 403 раньше получателя 422."""
    w = await make_world(db)
    # ba3 не участник и назначает несуществующего: 403, а не 422 user_not_found
    await forbidden(
        db, svc.create_task(db, actor_of(w.ba3), w.project_id, _data(svc, assignee=uuid.uuid4()))
    )
    # «Пользователь» -> другому, который к тому же не участник: 403, а не 422
    await forbidden(
        db, svc.create_task(db, actor_of(w.usr), w.project_id, _data(svc, assignee=w.usr2.id))
    )
    # неизвестный проект и неизвестный получатель: 404
    await not_found(
        db,
        svc.create_task(db, actor_of(w.ba), uuid.uuid4(), _data(svc, assignee=uuid.uuid4())),
    )


async def test_p10_2_create_task_lock_order(db: AsyncSession, svc: Any) -> None:
    """§10.2: проект FOR SHARE (п.2) -> получатель FOR SHARE (п.3) -> колонка (п.4) -> вставка."""
    w = await make_world(db)
    with capture_sql(db) as seen:
        await svc.create_task(db, actor_of(w.ba), w.project_id, _data(svc, assignee=w.usr.id))
    low = [s.lower() for s in seen]

    def first(pred: Any) -> int:
        for i, s in enumerate(low):
            if pred(s):
                return i
        raise AssertionError(f"нет запроса: {seen}")

    project_lock = first(lambda s: "for share" in s and "from project" in s and "app_user" not in s)
    recipient_lock = first(lambda s: "for share" in s and "workspace_member" in s)
    column_lock = first(lambda s: "pg_advisory_xact_lock" in s)
    insert = first(lambda s: s.lstrip().startswith("insert into task"))
    assert project_lock < recipient_lock < column_lock < insert


async def test_p10_2_forbidden_create_takes_no_recipient_lock_and_inserts_nothing(
    db: AsyncSession, svc: Any
) -> None:
    from app.core.errors import Forbidden

    w = await make_world(db)
    with capture_sql(db) as seen, pytest.raises(Forbidden):
        await svc.create_task(db, actor_of(w.ba3), w.project_id, _data(svc, assignee=w.usr.id))
    low = [s.lower() for s in seen]
    assert not [s for s in low if "workspace_member" in s and "for share" in s], seen
    assert not [s for s in low if s.lstrip().startswith("insert into task")], seen
    await db.rollback()


# --- create_task: вставка ---------------------------------------------------------------------


async def test_ac24_ac49_fr28a_insert_defaults(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    tid = await svc.create_task(db, actor_of(w.ba), w.project_id, _data(svc, "Новая"))
    row = await task_row(db, tid)
    assert row.status == "todo"  # AC-24
    assert row.priority == "medium"  # AC-49, 006/AC-12
    assert row.position == 1024  # пустая колонка
    assert row.title == "Новая"
    assert row.description == ""
    assert row.due_date is None
    assert row.assignee_id is None
    assert row.parent_id is None
    assert row.created_by == w.ba.id
    assert row.workspace_id == w.ws.id
    assert row.project_id == w.project_id
    assert row.deleted_at is None
    assert row.created_at is not None
    assert row.updated_at is not None


async def test_ac49_priority_high_saved_invalid_422(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    tid = await svc.create_task(
        db, actor_of(w.ba), w.project_id, _data(svc, priority="high", due_date=date(2026, 10, 20))
    )
    row = await task_row(db, tid)
    assert row.priority == "high"
    assert row.due_date == date(2026, 10, 20)
    await db.commit()
    for bad in ("urgent", "", "HIGH", "base", 1):
        await fails(
            db,
            svc.create_task(db, actor_of(w.ba), w.project_id, _data(svc, priority=bad)),
            "validation_error",
        )
    assert await _count_tasks(db, w.project_id) == 1


async def test_ac61_new_task_is_last_in_first_column(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    pid = w.project_id
    ws = w.ws.id
    other = await make_project(db, workspace_id=ws, owner_id=w.ba.id, name="Другой")
    await make_task(db, project_id=pid, workspace_id=ws, created_by=w.ba.id, position=1024)
    await make_task(db, project_id=pid, workspace_id=ws, created_by=w.ba.id, position=2048)
    # не учитываются: другие колонки, удалённые, подзадачи, другой проект
    await make_task(
        db, project_id=pid, workspace_id=ws, created_by=w.ba.id, status="done", position=90000
    )
    await make_task(
        db,
        project_id=pid,
        workspace_id=ws,
        created_by=w.ba.id,
        position=80000,
        deleted_at=datetime(2026, 1, 1),
    )
    await make_task(db, project_id=other.id, workspace_id=ws, created_by=w.ba.id, position=70000)
    await db.commit()
    a = await svc.create_task(db, actor_of(w.ba), pid, _data(svc, "A"))
    b = await svc.create_task(db, actor_of(w.ba), pid, _data(svc, "B"))
    assert (await task_row(db, a)).position == 3072
    assert (await task_row(db, b)).position == 4096


# --- create_task: границы входных данных ---------------------------------------------------------


async def test_ac108_create_task_boundaries_ok(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    tid = await svc.create_task(
        db,
        actor_of(w.ba),
        w.project_id,
        _data(svc, LONG_NAME_255, description=LONG_DESC_10000),
    )
    row = await task_row(db, tid)
    assert row.title == LONG_NAME_255
    assert row.description == LONG_DESC_10000
    one = await svc.create_task(db, actor_of(w.ba), w.project_id, _data(svc, "x"))
    assert (await task_row(db, one)).title == "x"


async def test_d52_title_stored_as_entered(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    tid = await svc.create_task(
        db, actor_of(w.ba), w.project_id, _data(svc, "  Задача <b>1</b>  ", description=" \n d ")
    )
    row = await task_row(db, tid)
    assert row.title == "  Задача <b>1</b>  "
    assert row.description == " \n d "


_BAD_INPUTS: list[dict[str, Any]] = [
    {"title": ""},
    {"title": "   "},
    {"title": "\t\n  "},
    {"title": "Я" * 256},
    {"title": "a\x00b"},
    {"title": "ok", "description": "д" * 10_001},
    {"title": "ok", "description": "a\x00b"},
    {"title": "ok", "due_date": datetime(2026, 10, 20, 0, 0)},  # AC-68/D-51: не дата-время
    {"title": "ok", "due_date": 20261020},
    {"title": "ok", "due_date": "2026-10-20T00:00:00"},
    {"title": "ok", "due_date": "2026-02-30"},
]


@pytest.mark.parametrize("bad", _BAD_INPUTS, ids=[f"bad{i}" for i in range(len(_BAD_INPUTS))])
async def test_ac108_ac68_create_task_invalid_input_is_422(
    db: AsyncSession, svc: Any, bad: dict[str, Any]
) -> None:
    w = await make_world(db)
    await fails(
        db,
        svc.create_task(db, actor_of(w.ba), w.project_id, svc.TaskCreateData(**bad)),
        "validation_error",
    )
    assert await _count_tasks(db, w.project_id) == 0


@pytest.mark.parametrize("bad", _BAD_INPUTS, ids=[f"bad{i}" for i in range(len(_BAD_INPUTS))])
async def test_ac108_ac68_create_subtask_invalid_input_is_422(
    db: AsyncSession, svc: Any, bad: dict[str, Any]
) -> None:
    w = await make_world(db)
    parent = await _parent(db, w, assignee=None)
    await fails(
        db,
        svc.create_subtask(db, actor_of(w.ba), parent, svc.TaskCreateData(**bad)),
        "validation_error",
    )
    assert await _count_tasks(db, w.project_id) == 1


# --- create_subtask ----------------------------------------------------------------------------


async def test_fr21_subtask_insert(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    parent = await _parent(db, w, assignee=w.usr.id)
    sid = await svc.create_subtask(
        db,
        actor_of(w.ba),
        parent,
        _data(
            svc,
            LONG_NAME_255,
            description=LONG_DESC_10000,
            assignee=w.ba2.id,
            due_date=date(2026, 11, 1),
            priority="high",
        ),
    )
    assert isinstance(sid, uuid.UUID)
    assert sid != parent
    row = await task_row(db, sid)
    assert row.parent_id == parent
    assert row.position is None  # CHECK position_top_level
    assert row.status == "todo"
    assert row.priority == "high"
    assert row.due_date == date(2026, 11, 1)
    assert row.title == LONG_NAME_255
    assert row.description == LONG_DESC_10000
    assert row.assignee_id == w.ba2.id
    assert row.created_by == w.ba.id
    assert row.workspace_id == w.ws.id
    assert row.project_id == w.project_id  # проект родителя
    assert row.deleted_at is None
    # родитель не тронут, колонка доски не изменилась
    assert (await task_row(db, parent)).position == 1024


async def test_ac109_subtask_defaults_by_role(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    await add_member_row(db, w, w.project_id, w.ba3)
    await db.commit()
    parent = await _parent(db, w, assignee=w.usr.id)
    # исполнитель родителя без исполнителя в данных -> он сам
    sid = await svc.create_subtask(db, actor_of(w.usr), parent, _data(svc))
    assert (await task_row(db, sid)).assignee_id == w.usr.id
    # БА-владелец и БА-участник -> None
    for who in (w.ba, w.ba3):
        sid = await svc.create_subtask(db, actor_of(who), parent, _data(svc))
        assert (await task_row(db, sid)).assignee_id is None
        sid = await svc.create_subtask(db, actor_of(who), parent, _data(svc, assignee=None))
        assert (await task_row(db, sid)).assignee_id is None


async def test_ac47_sc20_assignee_subtask_self_ok_other_403(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    parent = await _parent(db, w, assignee=w.usr.id)  # БА поставил Пользователю
    sid = await svc.create_subtask(db, actor_of(w.usr), parent, _data(svc, assignee=w.usr.id))
    assert (await task_row(db, sid)).assignee_id == w.usr.id
    await db.commit()
    await forbidden(
        db, svc.create_subtask(db, actor_of(w.usr), parent, _data(svc, assignee=w.ba2.id))
    )
    await forbidden(db, svc.create_subtask(db, actor_of(w.usr), parent, _data(svc, assignee=None)))
    assert await _count_tasks(db, w.project_id) == 2  # родитель + одна подзадача


async def test_ac47_user_not_assignee_of_parent_is_403(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    for assignee in (None, w.ba2.id):
        parent = await _parent(db, w, assignee=assignee)
        await forbidden(
            db, svc.create_subtask(db, actor_of(w.usr), parent, _data(svc, assignee=w.usr.id))
        )


async def test_fr19_user_own_task_subtask_for_self(db: AsyncSession, svc: Any) -> None:
    """Своя задача (автор и исполнитель): подзадача себе — да (can_edit_task_fully)."""
    w = await make_world(db)
    own = await svc.create_task(db, actor_of(w.usr), w.project_id, _data(svc))
    sid = await svc.create_subtask(db, actor_of(w.usr), own, _data(svc))
    assert (await task_row(db, sid)).assignee_id == w.usr.id


async def test_t70_ba_member_not_owner_subtask_rules(db: AsyncSession, svc: Any) -> None:
    """Обращён по 002/AC-13 (FR-9): БА-участник, не владелец, создаёт подзадачу к чужой задаче
    (себе, другому, без исполнителя), к своей и к назначенной ему; не участник (002/AC-15) - 403."""
    w = await make_world(db)
    foreign_task = await _parent(db, w, assignee=w.usr.id)  # автор — владелец
    await forbidden(
        db, svc.create_subtask(db, actor_of(w.ba3), foreign_task, _data(svc, assignee=w.ba3.id))
    )
    await forbidden(db, svc.create_subtask(db, actor_of(w.ba3), foreign_task, _data(svc)))
    sid = await svc.create_subtask(db, actor_of(w.ba2), foreign_task, _data(svc, assignee=w.ba2.id))
    assert (await task_row(db, sid)).assignee_id == w.ba2.id
    sid = await svc.create_subtask(db, actor_of(w.ba2), foreign_task, _data(svc))
    row = await task_row(db, sid)
    assert (row.parent_id, row.assignee_id) == (foreign_task, None)
    own = await _parent(db, w, assignee=w.ba2.id, created_by=w.ba2.id)
    sid = await svc.create_subtask(db, actor_of(w.ba2), own, _data(svc, assignee=w.usr.id))
    assert (await task_row(db, sid)).assignee_id == w.usr.id
    assigned = await _parent(db, w, assignee=w.ba2.id)  # автор — владелец, исполнитель — ba2
    sid = await svc.create_subtask(db, actor_of(w.ba2), assigned, _data(svc, assignee=w.usr.id))
    assert (await task_row(db, sid)).parent_id == assigned


async def test_ac106_subtask_non_member_is_403(db: AsyncSession, svc: Any) -> None:
    """Актор ``sm`` (прежде СМ-не-участник) удалён из перечня: дублировал ``ba3`` (002/AC-15)."""
    w = await make_world(db)
    parent = await _parent(db, w, assignee=w.ba3.id)
    for who in (w.ba3, w.usr2, w.ta, w.norole):
        await forbidden(
            db, svc.create_subtask(db, actor_of(who), parent, _data(svc, assignee=who.id))
        )
    assert await _count_tasks(db, w.project_id) == 1


async def test_ac8_subtask_of_subtask_is_422(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    parent = await _parent(db, w, assignee=None)
    sub = await svc.create_subtask(db, actor_of(w.ba), parent, _data(svc))
    await db.commit()
    before = await _count_tasks(db, w.project_id)
    await fails(
        db,
        svc.create_subtask(db, actor_of(w.ba), sub, _data(svc)),
        "subtask_depth_exceeded",
    )
    assert await _count_tasks(db, w.project_id) == before


async def test_ac8_order_403_before_depth_and_depth_before_recipient(
    db: AsyncSession, svc: Any
) -> None:
    w = await make_world(db)
    parent = await _parent(db, w, assignee=None)
    sub = await make_task(
        db,
        project_id=w.project_id,
        workspace_id=w.ws.id,
        created_by=w.ba.id,
        parent_id=parent,
        assignee_id=w.ba2.id,
    )
    await db.commit()
    # usr не исполнитель подзадачи и не автор: права 403 раньше глубины 422
    await forbidden(
        db, svc.create_subtask(db, actor_of(w.usr), sub.id, _data(svc, assignee=w.usr.id))
    )
    # владелец: глубина 422 раньше получателя (несуществующий исполнитель)
    await fails(
        db,
        svc.create_subtask(db, actor_of(w.ba), sub.id, _data(svc, assignee=uuid.uuid4())),
        "subtask_depth_exceeded",
    )


async def test_fr13_subtask_parent_404_unknown_deleted_foreign(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    other_ws = await make_workspace(db)
    other_owner = await make_user(db, workspace=other_ws, role="business_admin", login="o.ba")
    foreign_project = await make_project(db, workspace_id=other_ws.id, owner_id=other_owner.id)
    foreign = await make_task(
        db, project_id=foreign_project.id, workspace_id=other_ws.id, created_by=other_owner.id
    )
    deleted = await make_task(
        db,
        project_id=w.project_id,
        workspace_id=w.ws.id,
        created_by=w.ba.id,
        deleted_at=datetime(2026, 1, 1),
    )
    dead_project = await make_project(
        db, workspace_id=w.ws.id, owner_id=w.ba.id, name="Удалён", deleted_at=datetime(2026, 1, 1)
    )
    in_dead = await make_task(
        db, project_id=dead_project.id, workspace_id=w.ws.id, created_by=w.ba.id
    )
    await db.commit()
    for pid in (uuid.uuid4(), foreign.id, deleted.id, in_dead.id):
        await not_found(db, svc.create_subtask(db, actor_of(w.ba), pid, _data(svc)))


async def test_p10_2_create_subtask_lock_order(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    parent = await _parent(db, w, assignee=w.usr.id)
    with capture_sql(db) as seen:
        await svc.create_subtask(db, actor_of(w.ba), parent, _data(svc, assignee=w.usr.id))
    low = [s.lower() for s in seen]

    def first(pred: Any) -> int:
        for i, s in enumerate(low):
            if pred(s):
                return i
        raise AssertionError(f"нет запроса: {seen}")

    project_lock = first(lambda s: "for share" in s and "project" in s and "app_user" not in s)
    recipient_lock = first(lambda s: "for share" in s and "workspace_member" in s)
    insert = first(lambda s: s.lstrip().startswith("insert into task"))
    assert project_lock < recipient_lock < insert


# --- события (D-55) и инварианты ----------------------------------------------------------------


async def test_d55_create_writes_no_events(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    before = len(await events(db, w.ws.id))
    t = await svc.create_task(db, actor_of(w.ba), w.project_id, _data(svc, assignee=w.usr.id))
    await svc.create_subtask(db, actor_of(w.ba), t, _data(svc, assignee=w.usr.id))
    assert len(await events(db, w.ws.id)) == before == 0


async def test_t69_review_service_keeps_workspace_and_project_of_parent(
    db: AsyncSession, svc: Any
) -> None:
    """Инвариант сервиса: подзадача — того же workspace и проекта, что родитель; id != parent_id."""
    w = await make_world(db)
    second = await make_project(db, workspace_id=w.ws.id, owner_id=w.ba.id, name="Второй")
    await add_member_row(db, w, second.id, w.ba)
    await db.commit()
    t = await svc.create_task(db, actor_of(w.ba), second.id, _data(svc))
    s = await svc.create_subtask(db, actor_of(w.ba), t, _data(svc))
    row, parent = await task_row(db, s), await task_row(db, t)
    assert row.project_id == parent.project_id == second.id
    assert row.workspace_id == parent.workspace_id == w.ws.id
    assert row.parent_id == t != s


async def test_t69_review_assignee_must_be_member_of_parent_project(
    db: AsyncSession, svc: Any
) -> None:
    """Участник другого проекта не годится исполнителем подзадачи (§4.5)."""
    w = await make_world(db)
    second = await make_project(db, workspace_id=w.ws.id, owner_id=w.ba.id, name="Второй")
    await add_member_row(db, w, second.id, w.usr2)
    await db.commit()
    parent = await _parent(db, w, assignee=None)
    await fails(
        db,
        svc.create_subtask(db, actor_of(w.ba), parent, _data(svc, assignee=w.usr2.id)),
        "not_project_member",
    )


async def test_t70_review_owner_without_member_row_can_be_assignee(
    db: AsyncSession, svc: Any
) -> None:
    """Владелец всегда участник (ревью T70 п.2): строки членства нет, исполнителем быть может."""
    w = await make_world(db)
    lonely = await make_project(db, workspace_id=w.ws.id, owner_id=w.ba3.id, name="Без строки")
    await db.commit()
    assert w.ba3.id not in await member_ids(db, lonely.id)
    tid = await svc.create_task(db, actor_of(w.ba3), lonely.id, _data(svc, assignee=w.ba3.id))
    assert (await task_row(db, tid)).assignee_id == w.ba3.id


# --- конкурентность -----------------------------------------------------------------------------


@pytest.mark.committed
async def test_ac61_parallel_creates_get_unique_positions(
    committed: async_sessionmaker[AsyncSession], svc: Any
) -> None:
    async with committed() as setup:
        w = await make_world(setup)
    go = asyncio.Event()
    n = 6

    async def run(i: int) -> uuid.UUID:
        async with committed() as s:
            await go.wait()
            tid = await svc.create_task(s, actor_of(w.ba), w.project_id, _data(svc, f"t{i}"))
            await s.commit()
            return tid  # type: ignore[no-any-return]

    jobs = [asyncio.ensure_future(run(i)) for i in range(n)]
    await asyncio.sleep(0)
    go.set()
    ids = await asyncio.wait_for(asyncio.gather(*jobs), timeout=20)
    assert len(set(ids)) == n
    async with committed() as s:
        rows = await s.execute(
            text(
                "SELECT position FROM task WHERE project_id = :p AND status = 'todo' "
                "AND parent_id IS NULL ORDER BY position"
            ).bindparams(p=w.project_id)
        )
        positions = [r.position for r in rows]
    assert positions == [1024 * k for k in range(1, n + 1)]


@pytest.mark.committed
async def test_p10_2_create_waits_for_member_removal_then_422(
    committed: async_sessionmaker[AsyncSession], svc: Any
) -> None:
    import app.domain.projects.members as members
    from app.core.errors import AppError

    async with committed() as setup:
        w = await make_world(setup)
    holder = committed()
    try:
        await members.remove_member(holder, actor_of(w.ba), w.project_id, w.usr.id)  # без commit

        async def create() -> None:
            async with committed() as s:
                try:
                    await svc.create_task(
                        s, actor_of(w.ba), w.project_id, _data(svc, assignee=w.usr.id)
                    )
                finally:
                    await s.rollback()

        job = asyncio.ensure_future(create())
        done, _ = await asyncio.wait({job}, timeout=0.5)
        assert not done, "create_task не ждёт блокировку проекта (§10.2 п.2)"
        await holder.commit()
    finally:
        await holder.close()
    with pytest.raises(AppError) as info:
        await asyncio.wait_for(job, timeout=10)
    assert info.value.status_code == 422
    assert str(info.value.code) == "not_project_member"
    async with committed() as s:
        assert await _count_tasks(s, w.project_id) == 0


@pytest.mark.committed
async def test_p10_2_member_removal_waits_for_uncommitted_create_and_clears_assignee(
    committed: async_sessionmaker[AsyncSession], svc: Any
) -> None:
    import app.domain.projects.members as members

    async with committed() as setup:
        w = await make_world(setup)
    holder = committed()
    try:
        tid = await svc.create_task(
            holder, actor_of(w.ba), w.project_id, _data(svc, assignee=w.usr.id)
        )  # без commit: держит FOR SHARE проекта

        async def remove() -> None:
            async with committed() as s:
                await members.remove_member(s, actor_of(w.ba), w.project_id, w.usr.id)
                await s.commit()

        job = asyncio.ensure_future(remove())
        done, _ = await asyncio.wait({job}, timeout=0.5)
        assert not done, "исключение участника не дождалось FOR SHARE создания (§10.2 п.1/п.2)"
        await holder.commit()
    finally:
        await holder.close()
    await asyncio.wait_for(job, timeout=10)
    async with committed() as s:
        assert w.usr.id not in await member_ids(s, w.project_id)
        assert (await task_row(s, tid)).assignee_id is None  # исполнитель снят (FR-15a)


@pytest.mark.committed
async def test_p10_2_create_and_member_removal_race_has_no_deadlock_or_orphan_assignee(
    committed: async_sessionmaker[AsyncSession], svc: Any
) -> None:
    import app.domain.projects.members as members
    from app.core.errors import AppError

    async with committed() as setup:
        w = await make_world(setup)
    go = asyncio.Event()

    async def run(factory: Any) -> Any:
        async with committed() as s:
            await go.wait()
            try:
                result = await factory(s)
                await s.commit()
            except AppError as exc:
                await s.rollback()
                return str(exc.code)
            return result

    create = asyncio.ensure_future(
        run(
            lambda s: svc.create_task(
                s, actor_of(w.ba), w.project_id, _data(svc, assignee=w.usr.id)
            )
        )
    )
    remove = asyncio.ensure_future(
        run(lambda s: members.remove_member(s, actor_of(w.ba), w.project_id, w.usr.id))
    )
    await asyncio.sleep(0)
    go.set()
    created, _removed = await asyncio.wait_for(asyncio.gather(create, remove), timeout=20)
    async with committed() as s:
        assert w.usr.id not in await member_ids(s, w.project_id)
        orphans = (
            await s.execute(
                text(
                    "SELECT count(*) FROM task WHERE project_id = :p AND assignee_id = :u"
                ).bindparams(p=w.project_id, u=w.usr.id)
            )
        ).scalar_one()
        assert orphans == 0
        total = await _count_tasks(s, w.project_id)
    if isinstance(created, uuid.UUID):  # создание раньше исключения: задача без исполнителя
        assert total == 1
    else:  # исключение раньше создания
        assert created == "not_project_member"
        assert total == 0
