"""T76: карточка задачи и списки (plan §11.4, §11.5; D-46, D-56, D-62).

AC-6, AC-7 (прогресс), AC-11, AC-18, AC-22 (фильтры и пагинация), AC-43, AC-80,
FR-17, FR-22, FR-26, FR-27 (SC-10: фильтры только исполнитель и статус), FR-47.

Ожидаемый интерфейс ``app.domain.tasks.queries`` (``async``, только чтение)::

    get_task(db, actor, task_id) -> TaskView
    list_project_tasks(db, actor, project_id, params: PageParams, *,
                       assignee_id: UUID | None, status: TaskStatus | None)
        -> tuple[list[TaskListItem], bool]            # (items, has_next), как list_projects
    list_my_tasks(db, actor, params: PageParams) -> tuple[list[TaskListItem], bool]

    TaskView: id, project (.id, .name), parent_id, title, description, status, priority,
              due_date, assignee: UserRef | None, author: UserRef, position,
              subtasks: list[TaskBrief],
              progress: int | None, created_at, updated_at,
              permissions (.edit, .change_status, .change_assignee, .delete, .create_subtask)
    TaskBrief: id, title, status, priority, due_date, assignee: UserRef | None
    TaskListItem: id, project (.id, .name), parent_id, title, status, priority, due_date,
                  assignee: UserRef | None, created_at     (поля description нет)

Ошибки (``AppError``): 404 ``not_found`` (раньше 403), 403 ``forbidden``.
Порядок ``get_task``: 404 -> ``can_read_project_content`` (403). Права ``permissions`` —
из policy: ``create_subtask`` = ``can_create_subtask(actor, p, parent, actor.user_id)``.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest

from app.core.pagination import PageParams
from tests.factories import make_project, make_task, make_user, make_workspace
from tests.projects_support import (
    World,
    actor_of,
    add_member_row,
    capture_sql,
    fails,
    forbidden,
    make_world,
    not_found,
    task_row,
)
from tests.tasks_support import mk_task

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

T0 = datetime(2026, 3, 1, 12, 0, 0)
GONE = datetime(2026, 1, 1)


@pytest.fixture
def q() -> Any:
    import app.domain.tasks.queries as module

    return module


def _p(page: int = 1, size: int = 50) -> PageParams:
    return PageParams(page=page, page_size=size)


async def _sub(db: AsyncSession, w: World, parent: uuid.UUID, **kw: Any) -> uuid.UUID:
    return await mk_task(db, w, parent_id=parent, **kw)


async def _project_tasks(
    q: Any, db: AsyncSession, w: World, who: Any = None, **kw: Any
) -> tuple[list[Any], bool]:
    kw.setdefault("assignee_id", None)
    kw.setdefault("status", None)
    params = kw.pop("params", _p())
    return await q.list_project_tasks(db, actor_of(who or w.ba), w.project_id, params, **kw)


# --- get_task: 404 раньше 403 ----------------------------------------------------------------


async def test_fr13_get_task_404_unknown_deleted_foreign_deleted_project(
    db: AsyncSession, q: Any
) -> None:
    w = await make_world(db)
    other_ws = await make_workspace(db)
    other_owner = await make_user(db, workspace=other_ws, role="business_admin", login="o.ba")
    other_project = await make_project(db, workspace_id=other_ws.id, owner_id=other_owner.id)
    foreign = await make_task(
        db, project_id=other_project.id, workspace_id=other_ws.id, created_by=other_owner.id
    )
    deleted = await mk_task(db, w, deleted_at=GONE)
    dead_project = await make_project(db, workspace_id=w.ws.id, owner_id=w.ba.id, deleted_at=GONE)
    in_dead = await mk_task(db, w, project_id=dead_project.id)
    await db.commit()
    for tid in (uuid.uuid4(), foreign.id, deleted, in_dead):
        for who in (w.ba, w.sm, w.ta, w.norole):  # 404 раньше 403
            await not_found(db, q.get_task(db, actor_of(who), tid))


@pytest.mark.parametrize("who", ["ta", "norole", "usr2", "sm", "ba3"])
async def test_fr26_get_task_403_for_non_member_ta_and_no_role(
    db: AsyncSession, q: Any, who: str
) -> None:
    w = await make_world(db)
    tid = await mk_task(db, w)
    await forbidden(db, q.get_task(db, actor_of(getattr(w, who)), tid))


async def test_fr26_get_task_member_of_other_project_forbidden(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    other = await make_project(db, workspace_id=w.ws.id, owner_id=w.ba2.id)
    await add_member_row(db, w, other.id, w.usr2)
    tid = await mk_task(db, w)
    await db.commit()
    await forbidden(db, q.get_task(db, actor_of(w.usr2), tid))


# --- get_task: поля ----------------------------------------------------------------------------


async def test_ac6_get_task_card_fields(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    tid = await mk_task(
        db,
        w,
        created_by=w.ba2.id,
        assignee_id=w.usr.id,
        title="Заголовок",
        description="Описание задачи",
        status="review",
        priority="high",
        due_date=date(2026, 12, 31),
        created_at=T0,
        updated_at=T0 + timedelta(hours=1),
        position=2048,
    )
    for who in (w.ba, w.usr, w.ba2):
        v = await q.get_task(db, actor_of(who), tid)
        assert v.id == tid
        assert v.project.id == w.project_id
        assert v.project.name == "Основной"
        assert v.parent_id is None
        assert v.title == "Заголовок"
        assert v.description == "Описание задачи"
        assert str(v.status) == "review"
        assert str(v.priority) == "high"
        assert v.due_date == date(2026, 12, 31)
        assert (v.author.id, v.author.login) == (w.ba2.id, "w.ba2")
        assert v.assignee is not None
        assert (v.assignee.id, v.assignee.login) == (w.usr.id, "w.usr")
        assert v.position == 2048
        row = await task_row(db, tid)
        assert v.created_at == row.created_at
        assert v.updated_at == row.updated_at
        assert v.subtasks == []
        assert v.progress is None


async def test_ac6_get_task_without_assignee_and_due_date(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    tid = await mk_task(db, w)
    v = await q.get_task(db, actor_of(w.ba), tid)
    assert v.assignee is None
    assert v.due_date is None


async def test_fr21_get_subtask_has_parent_and_no_position(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    parent = await mk_task(db, w, title="Родитель")
    sub = await _sub(db, w, parent, title="Подзадача", assignee_id=w.usr.id)
    v = await q.get_task(db, actor_of(w.ba), sub)
    assert v.parent_id == parent
    assert v.position is None
    assert v.project.id == w.project_id
    assert v.subtasks == []
    assert v.progress is None


async def test_ac80_get_parent_lists_subtasks_ordered_with_assignees(
    db: AsyncSession, q: Any
) -> None:
    w = await make_world(db)
    parent = await mk_task(db, w)
    same = T0 + timedelta(minutes=5)
    s_late = await _sub(db, w, parent, title="late", created_at=T0 + timedelta(hours=1))
    s_early = await _sub(
        db,
        w,
        parent,
        title="early",
        created_at=T0,
        assignee_id=w.usr.id,
        priority="high",
        status="done",
        due_date=date(2026, 5, 5),
    )
    s_a = await _sub(db, w, parent, title="a", created_at=same)
    s_b = await _sub(db, w, parent, title="b", created_at=same)
    expected_tie = sorted([s_a, s_b])
    v = await q.get_task(db, actor_of(w.ba), parent)
    ids = [s.id for s in v.subtasks]
    assert ids == [s_early, *expected_tie, s_late]
    first = v.subtasks[0]
    assert first.title == "early"
    assert str(first.status) == "done"
    assert str(first.priority) == "high"
    assert first.due_date == date(2026, 5, 5)
    assert first.assignee is not None
    assert (first.assignee.id, first.assignee.login) == (w.usr.id, "w.usr")
    assert v.subtasks[-1].assignee is None


async def test_ac18_deleted_subtasks_not_in_card_and_progress(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    parent = await mk_task(db, w)
    await _sub(db, w, parent, status="done")
    await _sub(db, w, parent, status="todo")
    await _sub(db, w, parent, status="done", deleted_at=GONE, deleted_batch_id=uuid.uuid4())
    v = await q.get_task(db, actor_of(w.ba), parent)
    assert len(v.subtasks) == 2
    assert v.progress == 50


# --- progress --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([], None),
        (["todo"], 0),
        (["done"], 100),
        (["done", "todo", "todo"], 33),
        (["done", "done", "todo"], 66),
        (["done", "in_progress", "review", "todo"], 25),
        (["done"] * 7 + ["todo"] * 3, 70),
    ],
)
async def test_ac7_progress_floor_percent_of_done_subtasks(
    db: AsyncSession, q: Any, statuses: list[str], expected: int | None
) -> None:
    w = await make_world(db)
    parent = await mk_task(db, w)
    for s in statuses:
        await _sub(db, w, parent, status=s)
    v = await q.get_task(db, actor_of(w.ba), parent)
    assert v.progress == expected


async def test_ac7_only_deleted_subtasks_progress_none(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    parent = await mk_task(db, w)
    await _sub(db, w, parent, status="done", deleted_at=GONE, deleted_batch_id=uuid.uuid4())
    v = await q.get_task(db, actor_of(w.ba), parent)
    assert v.subtasks == []
    assert v.progress is None


async def test_ac7_other_parents_subtasks_do_not_leak(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    p1 = await mk_task(db, w)
    p2 = await mk_task(db, w)
    await _sub(db, w, p1, status="done")
    await _sub(db, w, p2, status="todo")
    await _sub(db, w, p2, status="todo")
    v1 = await q.get_task(db, actor_of(w.ba), p1)
    v2 = await q.get_task(db, actor_of(w.ba), p2)
    assert (len(v1.subtasks), v1.progress) == (1, 100)
    assert (len(v2.subtasks), v2.progress) == (2, 0)


# --- число запросов (D-62, заметка T73 п.6) ------------------------------------------------------


async def test_d62_get_task_query_count_independent_of_subtask_count(
    db: AsyncSession, q: Any
) -> None:
    w = await make_world(db)
    one = await mk_task(db, w)
    many = await mk_task(db, w)
    await _sub(db, w, one, assignee_id=w.usr.id, status="done")
    users = [w.usr, w.ba2, w.ba, w.sm]
    for i in range(30):
        await _sub(
            db,
            w,
            many,
            assignee_id=users[i % 4].id,
            created_by=users[(i + 1) % 4].id,
            status="done" if i % 3 == 0 else "todo",
        )
    actor = actor_of(w.ba)
    with capture_sql(db) as seen_one:
        v1 = await q.get_task(db, actor, one)
    with capture_sql(db) as seen_many:
        v30 = await q.get_task(db, actor, many)
    assert len(v1.subtasks) == 1
    assert len(v30.subtasks) == 30
    one = [s for s in seen_one if "SAVEPOINT" not in s.upper()]
    many = [s for s in seen_many if "SAVEPOINT" not in s.upper()]
    assert len(one) == len(many), (len(one), len(many))
    assert len(many) <= 8


# --- исполнитель заблокирован / без роли (AC-43) -----------------------------------------------


async def test_ac43_blocked_and_no_role_assignee_still_shown(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    t_blocked = await mk_task(db, w, assignee_id=w.blocked.id)
    t_norole = await mk_task(db, w, assignee_id=w.norole.id)
    parent = await mk_task(db, w)
    sub = await _sub(db, w, parent, assignee_id=w.blocked.id)
    v = await q.get_task(db, actor_of(w.ba), t_blocked)
    assert v.assignee is not None
    assert (v.assignee.id, v.assignee.login) == (w.blocked.id, "w.blocked")
    v = await q.get_task(db, actor_of(w.ba), t_norole)
    assert v.assignee is not None
    assert (v.assignee.id, v.assignee.login) == (w.norole.id, "w.norole")
    v = await q.get_task(db, actor_of(w.ba), parent)
    assert [s.id for s in v.subtasks] == [sub]
    assert v.subtasks[0].assignee is not None
    assert v.subtasks[0].assignee.login == "w.blocked"


async def test_ac43_blocked_assignee_found_by_assignee_filter(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    t = await mk_task(db, w, assignee_id=w.blocked.id)
    await mk_task(db, w, assignee_id=w.usr.id)
    items, _ = await _project_tasks(q, db, w, assignee_id=w.blocked.id)
    assert [i.id for i in items] == [t]
    assert items[0].assignee is not None
    assert items[0].assignee.login == "w.blocked"


# --- permissions -----------------------------------------------------------------------------


def _perms(v: Any) -> tuple[bool, bool, bool, bool, bool]:
    p = v.permissions
    return (p.edit, p.change_status, p.change_assignee, p.delete, p.create_subtask)


async def test_fr19_permissions_owner_ba_on_foreign_task(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    tid = await mk_task(db, w, created_by=w.ba2.id, assignee_id=w.usr.id)
    v = await q.get_task(db, actor_of(w.ba), tid)
    assert _perms(v) == (True, True, True, True, True)


async def test_fr19b_permissions_assignee_user_only_status_and_subtask(
    db: AsyncSession, q: Any
) -> None:
    w = await make_world(db)
    tid = await mk_task(db, w, created_by=w.ba.id, assignee_id=w.usr.id)
    v = await q.get_task(db, actor_of(w.usr), tid)
    assert _perms(v) == (False, True, False, False, True)


async def test_fr19_permissions_user_own_task_full_but_no_reassign(
    db: AsyncSession, q: Any
) -> None:
    w = await make_world(db)
    tid = await mk_task(db, w, created_by=w.usr.id, assignee_id=w.usr.id)
    v = await q.get_task(db, actor_of(w.usr), tid)
    assert _perms(v) == (True, True, False, True, True)


async def test_fr19_permissions_member_ba_not_owner_not_assignee_nothing(
    db: AsyncSession, q: Any
) -> None:
    w = await make_world(db)
    tid = await mk_task(db, w, created_by=w.ba.id, assignee_id=w.usr.id)
    v = await q.get_task(db, actor_of(w.ba2), tid)
    assert _perms(v) == (False, False, False, False, False)


async def test_fr19_permissions_user_member_not_assignee_nothing(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    tid = await mk_task(db, w, created_by=w.ba.id, assignee_id=None)
    v = await q.get_task(db, actor_of(w.usr), tid)
    assert _perms(v) == (False, False, False, False, False)


async def test_fr19_permissions_mixed_member_everything(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    await add_member_row(db, w, w.project_id, w.sm)
    await db.commit()
    tid = await mk_task(db, w, created_by=w.ba.id, assignee_id=w.usr.id)
    v = await q.get_task(db, actor_of(w.sm), tid)
    assert _perms(v) == (True, True, True, True, True)


async def test_fr19_permissions_ba_non_owner_own_task_edit_no_reassign(
    db: AsyncSession, q: Any
) -> None:
    """OI-127 (а): БА-участник правит «свою» задачу, исполнителя не меняет."""
    w = await make_world(db)
    tid = await mk_task(db, w, created_by=w.ba2.id, assignee_id=w.ba2.id)
    v = await q.get_task(db, actor_of(w.ba2), tid)
    assert _perms(v) == (True, True, False, True, True)


async def test_fr19_permissions_for_subtask_use_subtask_facts(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    parent = await mk_task(db, w, created_by=w.ba.id, assignee_id=None)
    sub = await _sub(db, w, parent, created_by=w.ba.id, assignee_id=w.usr.id)
    v = await q.get_task(db, actor_of(w.usr), sub)
    assert _perms(v) == (False, True, False, False, False)  # create_subtask: глубина 1


# --- list_project_tasks: доступ ----------------------------------------------------------------


async def test_fr13_list_project_404(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    other_ws = await make_workspace(db)
    other_owner = await make_user(db, workspace=other_ws, role="business_admin", login="o2.ba")
    foreign = await make_project(db, workspace_id=other_ws.id, owner_id=other_owner.id)
    dead = await make_project(db, workspace_id=w.ws.id, owner_id=w.ba.id, deleted_at=GONE)
    await db.commit()
    for pid in (uuid.uuid4(), foreign.id, dead.id):
        for who in (w.ba, w.ta, w.norole):
            await not_found(
                db,
                q.list_project_tasks(db, actor_of(who), pid, _p(), assignee_id=None, status=None),
            )


@pytest.mark.parametrize("who", ["ta", "norole", "usr2", "sm", "ba3"])
async def test_fr26_list_project_403_non_member_ta_no_role(
    db: AsyncSession, q: Any, who: str
) -> None:
    w = await make_world(db)
    await mk_task(db, w)
    await forbidden(
        db,
        q.list_project_tasks(
            db, actor_of(getattr(w, who)), w.project_id, _p(), assignee_id=None, status=None
        ),
    )


@pytest.mark.parametrize("who", ["ba", "ba2", "usr"])
async def test_fr26_list_project_members_see_all_tasks(db: AsyncSession, q: Any, who: str) -> None:
    w = await make_world(db)
    t1 = await mk_task(db, w, assignee_id=w.usr.id)
    t2 = await mk_task(db, w, assignee_id=None)
    items, has_next = await _project_tasks(q, db, w, getattr(w, who))
    assert {i.id for i in items} == {t1, t2}
    assert has_next is False


# --- list_project_tasks: состав, фильтры, порядок ---------------------------------------------


async def test_ac80_list_includes_subtasks_with_parent_id(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    parent = await mk_task(db, w, created_at=T0)
    sub = await _sub(db, w, parent, created_at=T0 + timedelta(minutes=1), assignee_id=w.usr.id)
    items, _ = await _project_tasks(q, db, w)
    by_id = {i.id: i for i in items}
    assert set(by_id) == {parent, sub}
    assert by_id[parent].parent_id is None
    assert by_id[sub].parent_id == parent
    assert [i.id for i in items] == [sub, parent]


async def test_ac18_deleted_tasks_and_subtasks_not_listed(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    alive = await mk_task(db, w)
    await mk_task(db, w, deleted_at=GONE, deleted_batch_id=uuid.uuid4())
    sub_alive = await _sub(db, w, alive)
    await _sub(db, w, alive, deleted_at=GONE, deleted_batch_id=uuid.uuid4())
    items, _ = await _project_tasks(q, db, w)
    assert {i.id for i in items} == {alive, sub_alive}


async def test_ac21_foreign_projects_do_not_leak(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    mine = await mk_task(db, w)
    other = await make_project(db, workspace_id=w.ws.id, owner_id=w.ba.id, name="Второй")
    await mk_task(db, w, project_id=other.id)
    other_ws = await make_workspace(db)
    ow = await make_user(db, workspace=other_ws, role="business_admin", login="o3.ba")
    op = await make_project(db, workspace_id=other_ws.id, owner_id=ow.id)
    await make_task(db, project_id=op.id, workspace_id=other_ws.id, created_by=ow.id)
    await db.commit()
    items, _ = await _project_tasks(q, db, w)
    assert [i.id for i in items] == [mine]


async def test_fr27_filter_by_assignee(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    a = await mk_task(db, w, assignee_id=w.usr.id)
    await mk_task(db, w, assignee_id=w.ba2.id)
    await mk_task(db, w, assignee_id=None)
    items, _ = await _project_tasks(q, db, w, assignee_id=w.usr.id)
    assert [i.id for i in items] == [a]


async def test_fr27_filter_by_status(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    await mk_task(db, w, status="todo")
    r = await mk_task(db, w, status="review")
    sub_review = await _sub(db, w, r, status="review")
    items, _ = await _project_tasks(q, db, w, status="review")
    assert {i.id for i in items} == {r, sub_review}


async def test_fr27_filters_combine_with_and(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    hit = await mk_task(db, w, assignee_id=w.usr.id, status="done")
    await mk_task(db, w, assignee_id=w.usr.id, status="todo")
    await mk_task(db, w, assignee_id=w.ba2.id, status="done")
    items, _ = await _project_tasks(q, db, w, assignee_id=w.usr.id, status="done")
    assert [i.id for i in items] == [hit]


async def test_fr27_no_filters_returns_all(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    ids = {
        await mk_task(db, w, assignee_id=a, status=s)
        for a, s in [(None, "todo"), (w.usr.id, "done"), (w.ba2.id, "review")]
    }
    items, _ = await _project_tasks(q, db, w, assignee_id=None, status=None)
    assert {i.id for i in items} == ids


async def test_fr27_status_accepts_enum_value(db: AsyncSession, q: Any) -> None:
    from app.domain.tasks.models import TaskStatus

    w = await make_world(db)
    t = await mk_task(db, w, status="in_progress")
    await mk_task(db, w, status="todo")
    items, _ = await _project_tasks(q, db, w, status=TaskStatus.IN_PROGRESS)
    assert [i.id for i in items] == [t]


async def test_fr26_list_order_created_desc_then_id_desc(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    old = await mk_task(db, w, created_at=T0)
    new = await mk_task(db, w, created_at=T0 + timedelta(days=1))
    tied = [
        await mk_task(db, w, created_at=T0 + timedelta(hours=1), title=f"t{i}") for i in range(4)
    ]
    items, _ = await _project_tasks(q, db, w)
    assert [i.id for i in items] == [new, *sorted(tied, reverse=True), old]


async def test_fr26_list_item_fields_and_no_description(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    tid = await mk_task(
        db,
        w,
        title="Элемент",
        description="секрет",
        status="in_progress",
        priority="high",
        due_date=date(2026, 8, 8),
        assignee_id=w.usr.id,
        created_at=T0,
    )
    items, _ = await _project_tasks(q, db, w)
    (it,) = items
    assert it.id == tid
    assert (it.project.id, it.project.name) == (w.project_id, "Основной")
    assert it.parent_id is None
    assert it.title == "Элемент"
    assert str(it.status) == "in_progress"
    assert str(it.priority) == "high"
    assert it.due_date == date(2026, 8, 8)
    assert it.assignee is not None
    assert (it.assignee.id, it.assignee.login) == (w.usr.id, "w.usr")
    row = await task_row(db, tid)
    assert it.created_at == row.created_at
    assert not hasattr(it, "description")


# --- пагинация --------------------------------------------------------------------------------


async def _seed_n(db: AsyncSession, w: World, n: int) -> list[uuid.UUID]:
    """n задач, от старой к новой (created_at возрастает)."""
    return [await mk_task(db, w, created_at=T0 + timedelta(minutes=i)) for i in range(n)]


async def test_fr47_project_pagination_pages_and_has_next(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    ids = await _seed_n(db, w, 5)
    newest_first = list(reversed(ids))
    p1, n1 = await _project_tasks(q, db, w, params=_p(1, 2))
    p2, n2 = await _project_tasks(q, db, w, params=_p(2, 2))
    p3, n3 = await _project_tasks(q, db, w, params=_p(3, 2))
    assert [i.id for i in p1] == newest_first[0:2] and n1 is True
    assert [i.id for i in p2] == newest_first[2:4] and n2 is True
    assert [i.id for i in p3] == newest_first[4:5] and n3 is False


async def test_fr47_project_boundary_exactly_page_size_has_no_next(
    db: AsyncSession, q: Any
) -> None:
    w = await make_world(db)
    await _seed_n(db, w, 3)
    items, has_next = await _project_tasks(q, db, w, params=_p(1, 3))
    assert len(items) == 3
    assert has_next is False
    items, has_next = await _project_tasks(q, db, w, params=_p(1, 2))
    assert (len(items), has_next) == (2, True)


async def test_fr47_project_page_beyond_end_is_empty(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    await _seed_n(db, w, 3)
    items, has_next = await _project_tasks(q, db, w, params=_p(9, 2))
    assert items == []
    assert has_next is False


async def test_fr47_project_pages_with_equal_created_at_do_not_overlap(
    db: AsyncSession, q: Any
) -> None:
    w = await make_world(db)
    ids = [await mk_task(db, w, created_at=T0) for _ in range(5)]
    seen: list[uuid.UUID] = []
    for page in (1, 2, 3):
        items, _ = await _project_tasks(q, db, w, params=_p(page, 2))
        seen.extend(i.id for i in items)
    assert seen == sorted(ids, reverse=True)


async def test_fr47_filters_apply_before_pagination(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    hits = [
        await mk_task(db, w, assignee_id=w.usr.id, created_at=T0 + timedelta(minutes=i))
        for i in range(3)
    ]
    for i in range(3):
        await mk_task(db, w, assignee_id=w.ba2.id, created_at=T0 + timedelta(hours=1, minutes=i))
    items, has_next = await _project_tasks(q, db, w, assignee_id=w.usr.id, params=_p(2, 2))
    assert [i.id for i in items] == [hits[0]]
    assert has_next is False


# --- list_my_tasks ----------------------------------------------------------------------------


async def _my(q: Any, db: AsyncSession, who: Any, params: PageParams | None = None) -> Any:
    return await q.list_my_tasks(db, actor_of(who), params or _p())


async def test_fr26_my_tasks_only_own_assignments_with_subtasks(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    mine = await mk_task(db, w, assignee_id=w.usr.id)
    parent = await mk_task(db, w, assignee_id=None)
    my_sub = await _sub(db, w, parent, assignee_id=w.usr.id)
    await mk_task(db, w, assignee_id=w.ba2.id)
    await mk_task(db, w, assignee_id=None)
    items, has_next = await _my(q, db, w.usr)
    assert {i.id for i in items} == {mine, my_sub}
    assert has_next is False
    by_id = {i.id: i for i in items}
    assert by_id[my_sub].parent_id == parent
    assert by_id[mine].project.name == "Основной"
    assert by_id[mine].assignee is not None
    assert by_id[mine].assignee.id == w.usr.id


async def test_ac18_my_tasks_exclude_deleted_task_and_deleted_project(
    db: AsyncSession, q: Any
) -> None:
    w = await make_world(db)
    alive = await mk_task(db, w, assignee_id=w.usr.id)
    await mk_task(db, w, assignee_id=w.usr.id, deleted_at=GONE, deleted_batch_id=uuid.uuid4())
    dead = await make_project(db, workspace_id=w.ws.id, owner_id=w.ba.id, deleted_at=GONE)
    await add_member_row(db, w, dead.id, w.usr)
    await mk_task(db, w, project_id=dead.id, assignee_id=w.usr.id)
    await db.commit()
    items, _ = await _my(q, db, w.usr)
    assert [i.id for i in items] == [alive]


async def test_fr15a_my_tasks_hidden_when_actor_no_longer_member(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    other = await make_project(db, workspace_id=w.ws.id, owner_id=w.ba.id, name="Чужой")
    await db.commit()
    stale = await mk_task(db, w, project_id=other.id, assignee_id=w.usr.id)  # usr не участник
    visible = await mk_task(db, w, assignee_id=w.usr.id)
    items, _ = await _my(q, db, w.usr)
    assert [i.id for i in items] == [visible]
    assert stale not in {i.id for i in items}


async def test_fr26_my_tasks_across_projects_and_ba_owner(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    second = await make_project(db, workspace_id=w.ws.id, owner_id=w.ba2.id, name="Второй")
    await add_member_row(db, w, second.id, w.ba2)
    await db.commit()
    t1 = await mk_task(db, w, assignee_id=w.ba2.id)
    t2 = await mk_task(db, w, project_id=second.id, assignee_id=w.ba2.id)
    items, _ = await _my(q, db, w.ba2)
    assert {i.id for i in items} == {t1, t2}
    assert {i.project.name for i in items} == {"Основной", "Второй"}


async def test_fr26_my_tasks_order_due_date_nulls_last_then_id(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    later = await mk_task(db, w, assignee_id=w.usr.id, due_date=date(2026, 9, 1))
    sooner = await mk_task(db, w, assignee_id=w.usr.id, due_date=date(2026, 6, 1))
    same = [await mk_task(db, w, assignee_id=w.usr.id, due_date=date(2026, 7, 1)) for _ in range(3)]
    none_ = [await mk_task(db, w, assignee_id=w.usr.id, due_date=None) for _ in range(3)]
    items, _ = await _my(q, db, w.usr)
    assert [i.id for i in items] == [sooner, *sorted(same), later, *sorted(none_)]


async def test_fr47_my_tasks_pagination(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    ids = [
        await mk_task(db, w, assignee_id=w.usr.id, due_date=date(2026, 6, 1) + timedelta(days=i))
        for i in range(5)
    ]
    p1, n1 = await _my(q, db, w.usr, _p(1, 2))
    p2, n2 = await _my(q, db, w.usr, _p(2, 2))
    p3, n3 = await _my(q, db, w.usr, _p(3, 2))
    p4, n4 = await _my(q, db, w.usr, _p(4, 2))
    assert [i.id for i in p1] == ids[0:2] and n1 is True
    assert [i.id for i in p2] == ids[2:4] and n2 is True
    assert [i.id for i in p3] == ids[4:5] and n3 is False
    assert p4 == [] and n4 is False
    exact, has_next = await _my(q, db, w.usr, _p(1, 5))
    assert len(exact) == 5
    assert has_next is False


async def test_ac75_my_tasks_ta_and_no_role_strict_403(db: AsyncSession, q: Any) -> None:
    """AC-75: ТА и без роли — строго 403, даже при сохранившихся участии и назначенной задаче."""
    w = await make_world(db)
    await add_member_row(db, w, w.project_id, w.ta)
    await add_member_row(db, w, w.project_id, w.norole)
    await mk_task(db, w, assignee_id=w.ta.id)
    await mk_task(db, w, assignee_id=w.norole.id)
    for who in (w.ta, w.norole):
        await forbidden(db, q.list_my_tasks(db, actor_of(who), _p()))


async def test_fr26_my_tasks_empty(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    items, has_next = await _my(q, db, w.usr)
    assert items == []
    assert has_next is False


# --- get_task не пишет и не меняет данные ------------------------------------------------------


async def test_get_task_is_read_only(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    tid = await mk_task(db, w, assignee_id=w.usr.id)
    before = await task_row(db, tid)
    with capture_sql(db) as seen:
        await q.get_task(db, actor_of(w.ba), tid)
    assert not any(s.lstrip().lower().startswith(("update", "insert", "delete")) for s in seen)
    assert not any("for update" in s.lower() or "for share" in s.lower() for s in seen)
    after = await task_row(db, tid)
    assert (after.updated_at, after.position) == (before.updated_at, before.position)


async def test_get_task_forbidden_checked_after_404_with_exc_code(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    tid = await mk_task(db, w)
    exc = await fails(db, q.get_task(db, actor_of(w.usr2), tid), "forbidden", status=403)
    assert exc.status_code == 403


# --- T76 попытка 2: матрица флагов, изоляция, description, AC-22 --------------


async def _passes(db: AsyncSession, awaitable: Any) -> bool:
    from app.core.errors import AppError

    try:
        await awaitable
    except AppError:
        await db.rollback()
        return False
    await db.rollback()  # данные подготовки зафиксированы commit() в mk_task
    return True


async def test_fr19_permission_flags_match_service_outcomes_matrix(
    db: AsyncSession, q: Any
) -> None:
    import app.domain.tasks.service as svc

    w = await make_world(db)
    await add_member_row(db, w, w.project_id, w.sm)
    await db.commit()
    combos = [
        (w.ba.id, w.usr.id),
        (w.usr.id, w.usr.id),
        (w.ba.id, None),
        (w.ba2.id, w.ba.id),
        (w.ba.id, w.ba.id),
        (w.ba2.id, w.ba2.id),
        (w.sm.id, w.sm.id),
    ]
    for created_by, assignee in combos:
        tid = await mk_task(db, w, created_by=created_by, assignee_id=assignee)
        target = w.ba.id if assignee == w.ba2.id else w.ba2.id
        for who in (w.ba, w.ba2, w.usr, w.sm):
            actor = actor_of(who)
            perms = (await q.get_task(db, actor, tid)).permissions
            new_sub = svc.TaskCreateData(title="s", assignee=who.id)
            ctx = (created_by, assignee, who.login)
            assert perms.create_subtask == await _passes(
                db, svc.create_subtask(db, actor, tid, new_sub)
            ), ("create_subtask", ctx)
            assert perms.edit == await _passes(
                db, svc.update_task(db, actor, tid, svc.TaskPatch(title="Новый"))
            ), ("edit", ctx)
            assert perms.change_status == await _passes(
                db, svc.update_task(db, actor, tid, svc.TaskPatch(status="in_progress"))
            ), ("change_status", ctx)
            assert perms.change_assignee == await _passes(
                db, svc.update_task(db, actor, tid, svc.TaskPatch(assignee_id=target))
            ), ("change_assignee", ctx)
            assert perms.delete == await _passes(db, svc.delete_task(db, actor, tid)), (
                "delete",
                ctx,
            )


async def test_fr21_subtask_card_create_subtask_false_for_every_role(
    db: AsyncSession, q: Any
) -> None:
    import app.domain.tasks.service as svc

    w = await make_world(db)
    await add_member_row(db, w, w.project_id, w.sm)
    await db.commit()
    parent = await mk_task(db, w, created_by=w.ba.id, assignee_id=w.usr.id)
    sub = await _sub(db, w, parent, created_by=w.ba.id, assignee_id=w.usr.id)
    for who in (w.ba, w.ba2, w.usr, w.sm):
        actor = actor_of(who)
        v = await q.get_task(db, actor, sub)
        assert v.permissions.create_subtask is False
        ok = await _passes(
            db, svc.create_subtask(db, actor, sub, svc.TaskCreateData(title="x", assignee=who.id))
        )
        assert ok is False


_RE_TABLE = re.compile(r"\b(?:from|join)\s+(?:task|project)\b", re.IGNORECASE)


async def test_fr13_every_task_and_project_select_is_workspace_scoped(
    db: AsyncSession, q: Any
) -> None:
    w = await make_world(db)
    parent = await mk_task(db, w, assignee_id=w.usr.id)
    await _sub(db, w, parent, assignee_id=w.usr.id)
    actor = actor_of(w.usr)
    seen: list[str] = []
    with capture_sql(db) as s1:
        await q.get_task(db, actor, parent)
    seen += s1
    with capture_sql(db) as s2:
        await q.list_project_tasks(db, actor, w.project_id, _p(), assignee_id=None, status=None)
    seen += s2
    with capture_sql(db) as s3:
        await q.list_my_tasks(db, actor, _p())
    seen += s3
    scoped = [s for s in seen if s.lstrip().upper().startswith("SELECT") and _RE_TABLE.search(s)]
    assert scoped
    for stmt in scoped:
        assert "workspace_id" in stmt, stmt


async def test_fr26_lists_do_not_select_task_description(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    await mk_task(db, w, assignee_id=w.usr.id, description="длинное описание")
    actor = actor_of(w.usr)
    with capture_sql(db) as s1:
        await q.list_project_tasks(db, actor, w.project_id, _p(), assignee_id=None, status=None)
    with capture_sql(db) as s2:
        await q.list_my_tasks(db, actor, _p())
    for stmt in [*s1, *s2]:
        if "FROM task" in stmt or "JOIN task" in stmt:
            head = stmt.split(" FROM ")[0]
            assert "task.description" not in head, stmt


async def test_ac22_default_page_size_50_with_51_tasks(db: AsyncSession, q: Any) -> None:
    w = await make_world(db)
    ids = [
        await mk_task(db, w, assignee_id=w.usr.id, created_at=T0 + timedelta(minutes=i))
        for i in range(51)
    ]
    newest_first = list(reversed(ids))
    actor = actor_of(w.usr)
    first, n1 = await q.list_project_tasks(
        db, actor, w.project_id, PageParams(), assignee_id=None, status=None
    )
    second, n2 = await q.list_project_tasks(
        db, actor, w.project_id, PageParams(page=2), assignee_id=None, status=None
    )
    assert [i.id for i in first] == newest_first[:50] and n1 is True
    assert [i.id for i in second] == newest_first[50:] and n2 is False
    mine, n3 = await q.list_my_tasks(db, actor, PageParams())
    assert len(mine) == 50 and n3 is True
    mine2, n4 = await q.list_my_tasks(db, actor, PageParams(page=2))
    assert len(mine2) == 1 and n4 is False


async def _foreign_user(db: AsyncSession, login: str) -> Any:
    other_ws = await make_workspace(db)
    user = await make_user(db, workspace=other_ws, role="user", login=login)
    await db.commit()
    return user


def _is_domain_error(exc: BaseException) -> bool:
    return isinstance(exc, RuntimeError) and "UserRef missing" in str(exc)


async def test_invariant_foreign_assignee_in_card_is_explicit_error(
    db: AsyncSession, q: Any
) -> None:
    w = await make_world(db)
    ghost = await _foreign_user(db, "ghost.a")
    tid = await mk_task(db, w, assignee_id=ghost.id)
    with pytest.raises(Exception) as info:  # noqa: PT011
        await q.get_task(db, actor_of(w.ba), tid)
    assert not isinstance(info.value, KeyError)
    assert _is_domain_error(info.value), repr(info.value)
    await db.rollback()


async def test_invariant_foreign_author_and_subtask_assignee_are_explicit_errors(
    db: AsyncSession, q: Any
) -> None:
    w = await make_world(db)
    ghost = await _foreign_user(db, "ghost.b")
    t_author = await mk_task(db, w, created_by=ghost.id)
    parent = await mk_task(db, w)
    await _sub(db, w, parent, assignee_id=ghost.id)
    for tid in (t_author, parent):
        with pytest.raises(Exception) as info:  # noqa: PT011
            await q.get_task(db, actor_of(w.ba), tid)
        assert not isinstance(info.value, KeyError)
        assert _is_domain_error(info.value), repr(info.value)
        await db.rollback()


async def test_invariant_foreign_assignee_in_lists_is_explicit_error(
    db: AsyncSession, q: Any
) -> None:
    w = await make_world(db)
    ghost = await _foreign_user(db, "ghost.c")
    await mk_task(db, w, assignee_id=ghost.id)
    with pytest.raises(Exception) as info:  # noqa: PT011
        await _project_tasks(q, db, w)
    assert not isinstance(info.value, KeyError)
    assert _is_domain_error(info.value), repr(info.value)
    await db.rollback()
