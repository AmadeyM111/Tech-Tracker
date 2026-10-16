"""T75: изменение и удаление задач (plan §11.4, §11.5, §10.2, §4.5; D-46, D-55, D-56).

AC-7 (родитель закрывается при незакрытых подзадачах), AC-42, AC-43, AC-46, AC-47, AC-48,
AC-50, AC-99, AC-103, AC-108 (границы), FR-19, FR-19a, FR-19b, FR-20, FR-28a, OI-127;
заметки ревью T73/T74 (перечитывание в ``load_task_context``, блокировка строки задачи).

Ожидаемый интерфейс ``app.domain.tasks.service`` (``async``, ``commit()`` не вызывают)::

    @dataclass(frozen=True) TaskPatch(title=UNSET, description=UNSET, assignee_id=UNSET,
                                      due_date=UNSET, priority=UNSET, status=UNSET)
        # UNSET (тот же сентинел, что у TaskCreateData) = «поле не передано»;
        # assignee_id=None = «снять исполнителя»; due_date=None = «снять срок»;
        # status: TaskStatus | str; priority: TaskPriority | str
    update_task(db, actor, task_id, patch: TaskPatch) -> None
    delete_task(db, actor, task_id) -> None

Порядок: контекст (404, FOR SHARE проекта) -> реально меняющиеся поля (D-46) -> права по полям
(403, атомарно) -> входные данные (422 ``validation_error``) -> получатель (422 коды
получателя) -> запись; смена статуса верхнего уровня — в конец целевой колонки (FR-28a);
у подзадачи позиции нет. ``delete_task``: 404 -> ``can_delete_task`` (403) -> строка задачи
FOR NO KEY UPDATE -> одно ``deleted_at``/``deleted_batch_id`` у задачи, её неудалённых
подзадач и неудалённых комментариев задачи и подзадач. События не пишутся (D-55).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from tests.factories import make_comment, make_project, make_user, make_workspace
from tests.projects_support import (
    LONG_DESC_10000,
    LONG_NAME_255,
    World,
    actor_of,
    add_member_row,
    capture_sql,
    comment_row,
    events,
    fails,
    forbidden,
    make_world,
    member_ids,
    not_found,
    task_row,
)
from tests.tasks_support import column, mk_task

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from tests.factories import UserRow


@pytest.fixture
def svc() -> Any:
    import app.domain.tasks.service as module

    return module


def _patch(svc: Any, **kw: Any) -> Any:
    return svc.TaskPatch(**kw)


async def _own(db: AsyncSession, w: World, user: UserRow, **kw: Any) -> uuid.UUID:
    """«Своя» задача: автор и исполнитель — ``user``."""
    return await mk_task(db, w, created_by=user.id, assignee_id=user.id, **kw)


async def _snapshot(db: AsyncSession, task_id: uuid.UUID) -> tuple[Any, ...]:
    r = await task_row(db, task_id)
    return (
        r.title,
        r.description,
        r.due_date,
        r.priority,
        r.status,
        r.assignee_id,
        r.position,
        r.updated_at,
        r.deleted_at,
    )


# --- 404 и контекст ---------------------------------------------------------------------------


async def test_fr13_update_404_unknown_deleted_foreign_deleted_project(
    db: AsyncSession, svc: Any
) -> None:
    w = await make_world(db)
    other_ws = await make_workspace(db)
    other_owner = await make_user(db, workspace=other_ws, role="business_admin", login="o.ba")
    other_project = await make_project(db, workspace_id=other_ws.id, owner_id=other_owner.id)
    from tests.factories import make_task

    foreign = await make_task(
        db, project_id=other_project.id, workspace_id=other_ws.id, created_by=other_owner.id
    )
    deleted = await mk_task(db, w, deleted_at=datetime(2026, 1, 1))
    dead_project = await make_project(
        db, workspace_id=w.ws.id, owner_id=w.ba.id, deleted_at=datetime(2026, 1, 1)
    )
    in_dead = await mk_task(db, w, project_id=dead_project.id)
    await db.commit()
    for tid in (uuid.uuid4(), foreign.id, deleted, in_dead):
        for who in (w.ba, w.sm, w.ta):  # 404 раньше 403
            await not_found(db, svc.update_task(db, actor_of(who), tid, _patch(svc, title="Х")))
            await not_found(db, svc.delete_task(db, actor_of(who), tid))


async def test_p10_2_update_and_delete_lock_project_share(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    tid = await mk_task(db, w)
    with capture_sql(db) as seen:
        await svc.update_task(db, actor_of(w.ba), tid, _patch(svc, title="Новое"))
    assert any("for share" in s.lower() and "from project" in s.lower() for s in seen), seen
    with capture_sql(db) as seen2:
        await svc.delete_task(db, actor_of(w.ba), tid)
    assert any("for share" in s.lower() and "from project" in s.lower() for s in seen2), seen2


# --- права по полям ---------------------------------------------------------------------------


_EDIT_FIELDS: list[dict[str, Any]] = [
    {"title": "Новое название"},
    {"description": "Новое описание"},
    {"due_date": date(2027, 1, 31)},
    {"priority": "high"},
]


async def test_ac46_user_edits_own_task_all_fields_and_status(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    tid = await _own(db, w, w.usr)
    await svc.update_task(
        db,
        actor_of(w.usr),
        tid,
        _patch(
            svc,
            title="Новое",
            description="Описание",
            due_date=date(2027, 2, 1),
            priority="high",
            status="in_progress",
        ),
    )
    r = await task_row(db, tid)
    assert (r.title, r.description, r.due_date, r.priority, r.status) == (
        "Новое",
        "Описание",
        date(2027, 2, 1),
        "high",
        "in_progress",
    )
    assert r.assignee_id == w.usr.id


async def test_ac46_user_cannot_change_assignee_even_of_own_task(
    db: AsyncSession, svc: Any
) -> None:
    w = await make_world(db)
    tid = await _own(db, w, w.usr)
    before = await _snapshot(db, tid)
    for target in (w.ba2.id, None, w.ba.id):
        await forbidden(
            db, svc.update_task(db, actor_of(w.usr), tid, _patch(svc, assignee_id=target))
        )
    assert await _snapshot(db, tid) == before


async def test_ac46_owner_ba_changes_assignee_in_own_project(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    tid = await _own(db, w, w.usr)
    await svc.update_task(db, actor_of(w.ba), tid, _patch(svc, assignee_id=w.ba2.id))
    assert (await task_row(db, tid)).assignee_id == w.ba2.id
    await svc.update_task(db, actor_of(w.ba), tid, _patch(svc, assignee_id=None))
    assert (await task_row(db, tid)).assignee_id is None


@pytest.mark.parametrize("fields", _EDIT_FIELDS, ids=lambda f: next(iter(f)))
async def test_ac47_assignee_cannot_edit_other_fields_of_assigned_task(
    db: AsyncSession, svc: Any, fields: dict[str, Any]
) -> None:
    w = await make_world(db)
    tid = await mk_task(db, w, assignee_id=w.usr.id)  # автор ba, исполнитель usr
    before = await _snapshot(db, tid)
    await forbidden(db, svc.update_task(db, actor_of(w.usr), tid, _patch(svc, **fields)))
    assert await _snapshot(db, tid) == before


async def test_ac47_assignee_changes_status_of_assigned_task(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    tid = await mk_task(db, w, assignee_id=w.usr.id)
    await svc.update_task(db, actor_of(w.usr), tid, _patch(svc, status="review"))
    r = await task_row(db, tid)
    assert r.status == "review"
    assert r.title == "Задача"


async def test_ac47_mixed_patch_with_forbidden_field_changes_nothing(
    db: AsyncSession, svc: Any
) -> None:
    """Атомарность: status разрешён, title — нет => 403 и статус тоже не изменился."""
    w = await make_world(db)
    tid = await mk_task(db, w, assignee_id=w.usr.id)
    before = await _snapshot(db, tid)
    await forbidden(
        db,
        svc.update_task(db, actor_of(w.usr), tid, _patch(svc, status="done", title="Чужое")),
    )
    assert await _snapshot(db, tid) == before
    await forbidden(
        db,
        svc.update_task(db, actor_of(w.usr), tid, _patch(svc, status="done", assignee_id=None)),
    )
    assert await _snapshot(db, tid) == before


async def test_ac47_user_not_assignee_not_author_is_403(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    tid = await mk_task(db, w, assignee_id=w.ba2.id)
    before = await _snapshot(db, tid)
    for fields in ({"status": "done"}, {"title": "Х"}, {"assignee_id": w.usr.id}):
        await forbidden(db, svc.update_task(db, actor_of(w.usr), tid, _patch(svc, **fields)))
    assert await _snapshot(db, tid) == before


async def test_ac42_user_cannot_reassign_task_of_blocked_assignee(
    db: AsyncSession, svc: Any
) -> None:
    w = await make_world(db)
    blocked_member = await make_user(
        db, workspace=w.ws, role="user", login="w.blockedm", blocked=True
    )
    await add_member_row(db, w, w.project_id, blocked_member)
    tid = await mk_task(db, w, assignee_id=blocked_member.id)
    await forbidden(
        db, svc.update_task(db, actor_of(w.usr), tid, _patch(svc, assignee_id=w.usr.id))
    )
    # владелец-БА переназначает: исполнитель изменён, задача не удалена (AC-42)
    await svc.update_task(db, actor_of(w.ba), tid, _patch(svc, assignee_id=w.usr.id))
    r = await task_row(db, tid)
    assert r.assignee_id == w.usr.id
    assert r.deleted_at is None


async def test_ac43_ba_not_owner_403_sm_member_ok_on_blocked_assignee_task(
    db: AsyncSession, svc: Any
) -> None:
    """Обращён по 002/AC-14 (FR-9, 001/FR-5): БА-участник не владелец переназначает задачу
    заблокированного исполнителя; СМ-участник - тоже (СМ уйдёт в R3-T07); «Пользователь» - 403."""
    w = await make_world(db)
    blocked_member = await make_user(
        db, workspace=w.ws, role="user", login="w.blockedm", blocked=True
    )
    await add_member_row(db, w, w.project_id, blocked_member)
    await add_member_row(db, w, w.project_id, w.sm)
    tid = await mk_task(db, w, assignee_id=blocked_member.id)
    await forbidden(
        db, svc.update_task(db, actor_of(w.usr), tid, _patch(svc, assignee_id=w.usr.id))
    )
    assert (await task_row(db, tid)).assignee_id == blocked_member.id
    await svc.update_task(db, actor_of(w.ba2), tid, _patch(svc, assignee_id=w.usr.id))
    assert (await task_row(db, tid)).assignee_id == w.usr.id
    await svc.update_task(db, actor_of(w.sm), tid, _patch(svc, assignee_id=w.ba2.id))
    assert (await task_row(db, tid)).assignee_id == w.ba2.id


async def test_ac48_ba_not_owner_cannot_change_foreign_or_assigned_tasks(
    db: AsyncSession, svc: Any
) -> None:
    """Обращён по 002/AC-13 (FR-9): БА-участник не владелец меняет поля чужих задач, задач,
    созданных им для другого или без исполнителя; не участник (002/AC-15) - 403, без изменений."""
    w = await make_world(db)
    foreign = await mk_task(db, w, assignee_id=w.usr.id)  # автор ba
    for_other = await mk_task(db, w, created_by=w.ba2.id, assignee_id=w.usr.id)
    unassigned = await mk_task(db, w, created_by=w.ba2.id, assignee_id=None)
    reassigned = await mk_task(db, w, created_by=w.ba2.id, assignee_id=w.usr.id)
    for i, tid in enumerate((foreign, for_other, unassigned, reassigned)):
        await svc.update_task(
            db,
            actor_of(w.ba2),
            tid,
            _patch(svc, title=f"Х{i}", status="done", priority="high"),
        )
        r = await task_row(db, tid)
        assert (r.title, r.status, r.priority) == (f"Х{i}", "done", "high")
    await db.commit()
    outsider = await make_user(db, workspace=w.ws, role="business_admin", login="w.ba.outsider")
    for tid in (foreign, for_other, unassigned, reassigned):
        before = await _snapshot(db, tid)
        for fields in ({"title": "Y"}, {"status": "review"}, {"priority": "base"}):
            await forbidden(db, svc.update_task(db, actor_of(outsider), tid, _patch(svc, **fields)))
        assert await _snapshot(db, tid) == before


async def test_ac48_ba_not_owner_edits_own_task_but_not_assignee(
    db: AsyncSession, svc: Any
) -> None:
    """Обращён по 002/AC-13, AC-14 (FR-9): БА-участник не владелец правит поля своей задачи и
    меняет исполнителя (другой, снятие, владелец)."""
    w = await make_world(db)
    tid = await mk_task(db, w, created_by=w.ba2.id, assignee_id=w.ba2.id)
    await svc.update_task(
        db,
        actor_of(w.ba2),
        tid,
        _patch(
            svc,
            title="Своя",
            description="д",
            due_date=date(2027, 3, 3),
            priority="high",
            status="done",
        ),
    )
    r = await task_row(db, tid)
    assert (r.title, r.description, r.due_date, r.priority, r.status) == (
        "Своя",
        "д",
        date(2027, 3, 3),
        "high",
        "done",
    )
    for target in (w.usr.id, None, w.ba.id):
        await svc.update_task(db, actor_of(w.ba2), tid, _patch(svc, assignee_id=target))
        assert (await task_row(db, tid)).assignee_id == target


async def test_ac48_owner_ba_changes_any_task_incl_foreign_author(
    db: AsyncSession, svc: Any
) -> None:
    w = await make_world(db)
    tid = await mk_task(db, w, created_by=w.ba2.id, assignee_id=w.usr.id)
    await svc.update_task(
        db, actor_of(w.ba), tid, _patch(svc, title="Владелец", status="review", priority="high")
    )
    r = await task_row(db, tid)
    assert (r.title, r.status, r.priority) == ("Владелец", "review", "high")


async def test_ac103_sm_member_changes_fields_and_assignee_non_member_403(
    db: AsyncSession, svc: Any
) -> None:
    w = await make_world(db)
    tid = await mk_task(db, w, assignee_id=w.usr.id)
    before = await _snapshot(db, tid)
    for fields in ({"title": "СМ"}, {"assignee_id": w.ba2.id}, {"status": "done"}):
        await forbidden(db, svc.update_task(db, actor_of(w.sm), tid, _patch(svc, **fields)))
    assert await _snapshot(db, tid) == before
    await add_member_row(db, w, w.project_id, w.sm)  # добавил себя в проект и повторил
    await db.commit()
    await svc.update_task(
        db, actor_of(w.sm), tid, _patch(svc, title="СМ", assignee_id=w.ba2.id, status="review")
    )
    r = await task_row(db, tid)
    assert (r.title, r.assignee_id, r.status) == ("СМ", w.ba2.id, "review")


@pytest.mark.parametrize("who", ["ta", "norole", "usr2", "ba3"])
async def test_fr19_no_rights_actors_get_403(db: AsyncSession, svc: Any, who: str) -> None:
    w = await make_world(db)
    tid = await mk_task(db, w, assignee_id=w.usr.id)
    before = await _snapshot(db, tid)
    actor = actor_of(getattr(w, who))
    for fields in ({"title": "Х"}, {"status": "done"}, {"assignee_id": None}):
        await forbidden(db, svc.update_task(db, actor, tid, _patch(svc, **fields)))
    assert await _snapshot(db, tid) == before


async def test_fr19_403_comes_before_422_validation(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    tid = await mk_task(db, w, assignee_id=w.usr.id)
    await forbidden(db, svc.update_task(db, actor_of(w.usr), tid, _patch(svc, title="")))


# --- D-46: повтор без изменений ---------------------------------------------------------------


async def test_d46_unchanged_fields_need_no_rights_and_change_nothing(
    db: AsyncSession, svc: Any, fixed_clock: Any
) -> None:
    w = await make_world(db)
    tid = await mk_task(
        db, w, assignee_id=w.usr.id, title="Т", due_date=date(2027, 1, 1), priority="high"
    )
    before = await _snapshot(db, tid)
    fixed_clock.advance(timedelta(minutes=5))
    # исполнитель присылает форму целиком: title/description/due/priority/assignee — как есть
    await svc.update_task(
        db,
        actor_of(w.usr),
        tid,
        _patch(
            svc,
            title="Т",
            description="",
            due_date=date(2027, 1, 1),
            priority="high",
            assignee_id=w.usr.id,
            status="todo",
        ),
    )
    assert await _snapshot(db, tid) == before  # в том числе updated_at и position


async def test_d46_form_with_unchanged_fields_and_new_status_is_allowed_for_assignee(
    db: AsyncSession, svc: Any
) -> None:
    w = await make_world(db)
    tid = await mk_task(db, w, assignee_id=w.usr.id, title="Т")
    await svc.update_task(
        db,
        actor_of(w.usr),
        tid,
        _patch(svc, title="Т", assignee_id=w.usr.id, status="in_progress"),
    )
    r = await task_row(db, tid)
    assert (r.title, r.assignee_id, r.status) == ("Т", w.usr.id, "in_progress")


async def test_d46_real_change_updates_updated_at(
    db: AsyncSession, svc: Any, fixed_clock: Any
) -> None:
    w = await make_world(db)
    tid = await mk_task(db, w)
    fixed_clock.advance(timedelta(minutes=5))
    await svc.update_task(db, actor_of(w.ba), tid, _patch(svc, title="Другое"))
    r = await task_row(db, tid)
    assert r.updated_at == fixed_clock.now()


async def test_d46_same_status_does_not_move_task_to_end(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    first = await mk_task(db, w, position=1024)
    last = await mk_task(db, w, position=2048)
    await svc.update_task(db, actor_of(w.ba), first, _patch(svc, status="todo"))
    assert await column(db, w.project_id, "todo") == [first, last]
    assert (await task_row(db, first)).position == 1024


# --- исполнитель: получатель ------------------------------------------------------------------


async def test_ac50_update_assignee_recipient_codes(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    other_ws = await make_workspace(db)
    foreigner = await make_user(db, workspace=other_ws, role="user", login="f.usr")
    blocked_member = await make_user(
        db, workspace=w.ws, role="user", login="w.blockedm", blocked=True
    )
    await add_member_row(db, w, w.project_id, blocked_member)
    await add_member_row(db, w, w.project_id, w.ta)
    await add_member_row(db, w, w.project_id, w.norole)
    tid = await mk_task(db, w, assignee_id=w.usr.id)
    cases = [
        (w.usr2.id, "not_project_member"),
        (w.sm.id, "not_project_member"),
        (w.ta.id, "recipient_wrong_role"),
        (w.norole.id, "recipient_wrong_role"),
        (w.blocked.id, "user_blocked"),
        (blocked_member.id, "user_blocked"),
        (foreigner.id, "user_not_found"),
        (uuid.uuid4(), "user_not_found"),
    ]
    before = await _snapshot(db, tid)
    for target, code in cases:
        await fails(
            db,
            svc.update_task(db, actor_of(w.ba), tid, _patch(svc, assignee_id=target)),
            code,
        )
    assert await _snapshot(db, tid) == before


async def test_fr20_422_recipient_rolls_back_other_fields_of_same_patch(
    db: AsyncSession, svc: Any
) -> None:
    w = await make_world(db)
    tid = await mk_task(db, w, assignee_id=w.usr.id)
    before = await _snapshot(db, tid)
    await fails(
        db,
        svc.update_task(db, actor_of(w.ba), tid, _patch(svc, title="Новое", assignee_id=w.usr2.id)),
        "not_project_member",
    )
    assert await _snapshot(db, tid) == before


@pytest.mark.parametrize("who", ["ba", "sm"])
async def test_fr20_ba_sm_may_clear_assignee(db: AsyncSession, svc: Any, who: str) -> None:
    w = await make_world(db)
    await add_member_row(db, w, w.project_id, w.sm)
    tid = await mk_task(db, w, assignee_id=w.usr.id)
    await svc.update_task(db, actor_of(getattr(w, who)), tid, _patch(svc, assignee_id=None))
    assert (await task_row(db, tid)).assignee_id is None


async def test_fr20_user_cannot_set_null_assignee(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    tid = await _own(db, w, w.usr)
    await forbidden(db, svc.update_task(db, actor_of(w.usr), tid, _patch(svc, assignee_id=None)))
    assert (await task_row(db, tid)).assignee_id == w.usr.id


async def test_t70_review_owner_without_member_row_can_be_assignee(
    db: AsyncSession, svc: Any
) -> None:
    w = await make_world(db)
    tid = await mk_task(db, w, assignee_id=w.usr.id)
    await db.execute(
        text("DELETE FROM project_member WHERE project_id = :p AND user_id = :u").bindparams(
            p=w.project_id, u=w.ba.id
        )
    )
    await db.commit()
    await svc.update_task(db, actor_of(w.ba), tid, _patch(svc, assignee_id=w.ba.id))
    assert (await task_row(db, tid)).assignee_id == w.ba.id


# --- AC-50: после исключения участника ---------------------------------------------------------


async def test_ac50_removed_member_tasks_reassigned_by_owner(db: AsyncSession, svc: Any) -> None:
    import app.domain.projects.members as members

    w = await make_world(db)
    t1 = await mk_task(db, w, assignee_id=w.usr.id)
    t2 = await mk_task(db, w, assignee_id=w.usr.id)
    gone = await mk_task(
        db, w, assignee_id=w.usr.id, deleted_at=datetime(2026, 1, 1), deleted_batch_id=uuid.uuid4()
    )
    await members.remove_member(db, actor_of(w.ba), w.project_id, w.usr.id)
    await db.commit()
    for tid in (t1, t2, gone):
        assert (await task_row(db, tid)).assignee_id is None
    # исключённый получает отказ
    await forbidden(db, svc.update_task(db, actor_of(w.usr), t1, _patch(svc, status="done")))
    await forbidden(db, svc.delete_task(db, actor_of(w.usr), t1))
    # исключённого назначить нельзя; другого участника — можно
    await fails(
        db,
        svc.update_task(db, actor_of(w.ba), t1, _patch(svc, assignee_id=w.usr.id)),
        "not_project_member",
    )
    await svc.update_task(db, actor_of(w.ba), t1, _patch(svc, assignee_id=w.ba2.id))
    assert (await task_row(db, t1)).assignee_id == w.ba2.id
    assert (await task_row(db, t2)).assignee_id is None


# --- статус и колонки -------------------------------------------------------------------------


async def test_ac81_status_change_goes_to_end_of_target_column(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    a, b, c = [await mk_task(db, w, status="in_progress", position=1024 * i) for i in (1, 2, 3)]
    mover = await mk_task(db, w, position=1024)
    other = await mk_task(db, w, position=2048)
    await svc.update_task(db, actor_of(w.ba), mover, _patch(svc, status="in_progress"))
    assert await column(db, w.project_id, "in_progress") == [a, b, c, mover]
    r = await task_row(db, mover)
    assert (r.status, r.position) == ("in_progress", 3072 + 1024)
    assert (await task_row(db, other)).position == 2048  # соседи не тронуты
    assert (await task_row(db, c)).position == 3072


async def test_ac81_assignee_status_change_also_goes_to_end(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    d = await mk_task(db, w, status="done", position=5000)
    mover = await mk_task(db, w, assignee_id=w.usr.id, position=1024)
    await svc.update_task(db, actor_of(w.usr), mover, _patch(svc, status="done"))
    assert await column(db, w.project_id, "done") == [d, mover]


async def test_fr21_subtask_status_change_keeps_position_null(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    parent = await mk_task(db, w, position=1024)
    other = await mk_task(db, w, status="done", position=2048)
    sub = await mk_task(db, w, parent_id=parent, assignee_id=w.usr.id)
    await svc.update_task(db, actor_of(w.usr), sub, _patch(svc, status="done"))
    r = await task_row(db, sub)
    assert (r.status, r.position) == ("done", None)
    assert await column(db, w.project_id, "done") == [other]  # подзадачи нет на доске
    assert (await task_row(db, parent)).position == 1024


async def test_fr21_subtask_fields_edit_by_owner(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    parent = await mk_task(db, w)
    sub = await mk_task(db, w, parent_id=parent)
    await svc.update_task(
        db, actor_of(w.ba), sub, _patch(svc, title="Под", priority="high", assignee_id=w.usr.id)
    )
    r = await task_row(db, sub)
    assert (r.title, r.priority, r.assignee_id, r.position) == ("Под", "high", w.usr.id, None)


async def test_ac7_parent_can_be_closed_with_unclosed_subtasks(db: AsyncSession, svc: Any) -> None:
    """AC-7 (OI-19): родитель в «Готово» при незакрытых подзадачах — изменение сохранено."""
    w = await make_world(db)
    parent = await mk_task(db, w)
    open_sub = await mk_task(db, w, parent_id=parent)
    review_sub = await mk_task(db, w, parent_id=parent, status="review")
    await svc.update_task(db, actor_of(w.ba), parent, _patch(svc, status="done"))
    assert (await task_row(db, parent)).status == "done"
    assert (await task_row(db, open_sub)).status == "todo"  # подзадачи не закрываются каскадом
    assert (await task_row(db, review_sub)).status == "review"


async def test_ac7_subtasks_can_be_closed_and_deleted_ones_do_not_matter(
    db: AsyncSession, svc: Any
) -> None:
    w = await make_world(db)
    parent = await mk_task(db, w)
    s1 = await mk_task(db, w, parent_id=parent)
    deleted_sub = await mk_task(
        db, w, parent_id=parent, deleted_at=datetime(2026, 1, 1), deleted_batch_id=uuid.uuid4()
    )
    await svc.update_task(db, actor_of(w.ba), s1, _patch(svc, status="done"))
    await svc.update_task(db, actor_of(w.ba), parent, _patch(svc, status="done"))
    assert (await task_row(db, s1)).status == "done"
    assert (await task_row(db, parent)).status == "done"
    assert (await task_row(db, deleted_sub)).status == "todo"


# --- границы входных данных -------------------------------------------------------------------


async def test_ac108_update_boundaries_ok(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    tid = await mk_task(db, w, due_date=date(2027, 1, 1))
    await svc.update_task(
        db,
        actor_of(w.ba),
        tid,
        _patch(svc, title=LONG_NAME_255, description=LONG_DESC_10000, due_date=None),
    )
    r = await task_row(db, tid)
    assert r.title == LONG_NAME_255
    assert r.description == LONG_DESC_10000
    assert r.due_date is None
    await svc.update_task(db, actor_of(w.ba), tid, _patch(svc, title="Я", description=""))
    r = await task_row(db, tid)
    assert (r.title, r.description) == ("Я", "")


@pytest.mark.parametrize(
    "fields",
    [
        {"title": ""},
        {"title": "   "},
        {"title": "Я" * 256},
        {"title": "a\x00b"},
        {"description": "д" * 10_001},
        {"description": "a\x00b"},
        {"due_date": datetime(2027, 1, 1, 12, 0)},
        {"due_date": "2027-13-45"},
        {"priority": "urgent"},
        {"priority": ""},
        {"status": "archived"},
        {"status": ""},
    ],
    ids=lambda f: f"{next(iter(f))}={str(next(iter(f.values())))[:12]!r}",
)
async def test_ac108_update_invalid_input_is_422_and_changes_nothing(
    db: AsyncSession, svc: Any, fields: dict[str, Any]
) -> None:
    w = await make_world(db)
    tid = await mk_task(db, w, assignee_id=w.usr.id)
    before = await _snapshot(db, tid)
    await fails(
        db, svc.update_task(db, actor_of(w.ba), tid, _patch(svc, **fields)), "validation_error"
    )
    assert await _snapshot(db, tid) == before


async def test_ac108_one_invalid_field_rejects_whole_patch(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    tid = await mk_task(db, w)
    before = await _snapshot(db, tid)
    await fails(
        db,
        svc.update_task(db, actor_of(w.ba), tid, _patch(svc, status="done", title="")),
        "validation_error",
    )
    assert await _snapshot(db, tid) == before


async def test_d55_update_and_delete_write_no_events(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    tid = await mk_task(db, w)
    await svc.update_task(
        db, actor_of(w.ba), tid, _patch(svc, title="Х", status="done", assignee_id=w.usr.id)
    )
    await svc.delete_task(db, actor_of(w.ba), tid)
    assert await events(db, w.ws.id) == []


async def test_t69_review_update_keeps_workspace_project_and_author(
    db: AsyncSession, svc: Any
) -> None:
    w = await make_world(db)
    tid = await mk_task(db, w, created_by=w.ba2.id)
    await svc.update_task(db, actor_of(w.ba), tid, _patch(svc, title="Н", status="review"))
    r = await task_row(db, tid)
    assert (r.workspace_id, r.project_id, r.created_by, r.parent_id) == (
        w.ws.id,
        w.project_id,
        w.ba2.id,
        None,
    )


# --- delete_task: права -----------------------------------------------------------------------


async def test_ac99_user_deletes_own_task(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    tid = await _own(db, w, w.usr)
    assert await svc.delete_task(db, actor_of(w.usr), tid) is None
    r = await task_row(db, tid)
    assert r.deleted_at is not None
    assert r.deleted_batch_id is not None
    await db.commit()  # иначе rollback в not_found() откатит удаление
    await not_found(db, svc.delete_task(db, actor_of(w.usr), tid))  # повтор -> 404
    await not_found(db, svc.update_task(db, actor_of(w.ba), tid, _patch(svc, title="Х")))


async def test_ac99_assignee_of_foreign_task_cannot_delete(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    tid = await mk_task(db, w, assignee_id=w.usr.id)
    await forbidden(db, svc.delete_task(db, actor_of(w.usr), tid))
    assert (await task_row(db, tid)).deleted_at is None


async def test_ac99_ba_not_owner_cannot_delete_foreign_task(db: AsyncSession, svc: Any) -> None:
    """Обращён по 002/AC-13 (FR-9): БА-участник не владелец удаляет чужую задачу, задачу, созданную
    им для другого, и без исполнителя; не участник (002/AC-15) - 403, задача цела."""
    w = await make_world(db)
    foreign = await mk_task(db, w, assignee_id=w.usr.id)
    for_other = await mk_task(db, w, created_by=w.ba2.id, assignee_id=w.usr.id)
    unassigned = await mk_task(db, w, created_by=w.ba2.id)
    outsider = await make_user(db, workspace=w.ws, role="business_admin", login="w.ba.outsider")
    for tid in (foreign, for_other, unassigned):
        await forbidden(db, svc.delete_task(db, actor_of(outsider), tid))
        assert (await task_row(db, tid)).deleted_at is None
    for tid in (foreign, for_other, unassigned):
        await svc.delete_task(db, actor_of(w.ba2), tid)
        assert (await task_row(db, tid)).deleted_at is not None


async def test_ac48_ba_not_owner_deletes_own_task(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    tid = await mk_task(db, w, created_by=w.ba2.id, assignee_id=w.ba2.id)
    await svc.delete_task(db, actor_of(w.ba2), tid)
    assert (await task_row(db, tid)).deleted_at is not None
    await not_found(db, svc.delete_task(db, actor_of(w.ba2), tid))


async def test_ac99_sm_member_deletes_foreign_task_non_member_403(
    db: AsyncSession, svc: Any
) -> None:
    w = await make_world(db)
    tid = await mk_task(db, w, assignee_id=w.usr.id)
    await forbidden(db, svc.delete_task(db, actor_of(w.sm), tid))
    await add_member_row(db, w, w.project_id, w.sm)
    await db.commit()
    await svc.delete_task(db, actor_of(w.sm), tid)
    assert (await task_row(db, tid)).deleted_at is not None


async def test_ac99_owner_ba_deletes_any_task(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    tid = await mk_task(db, w, created_by=w.ba2.id, assignee_id=w.usr.id)
    await svc.delete_task(db, actor_of(w.ba), tid)
    assert (await task_row(db, tid)).deleted_at is not None


@pytest.mark.parametrize("who", ["ta", "norole", "usr2", "ba3"])
async def test_fr19_delete_no_rights_actors_get_403(db: AsyncSession, svc: Any, who: str) -> None:
    w = await make_world(db)
    tid = await mk_task(db, w, assignee_id=w.usr.id)
    await forbidden(db, svc.delete_task(db, actor_of(getattr(w, who)), tid))
    assert (await task_row(db, tid)).deleted_at is None


# --- delete_task: каскад D-56 -----------------------------------------------------------------


async def test_d56_delete_task_cascades_to_subtasks_and_comments_with_one_batch(
    db: AsyncSession, svc: Any, fixed_clock: Any
) -> None:
    w = await make_world(db)
    early = datetime(2026, 1, 1, tzinfo=fixed_clock.now().tzinfo)
    old_batch = uuid.uuid4()
    parent = await mk_task(db, w, assignee_id=w.usr.id)
    sub1 = await mk_task(db, w, parent_id=parent)
    sub2 = await mk_task(db, w, parent_id=parent, assignee_id=w.usr.id)
    old_sub = await mk_task(db, w, parent_id=parent, deleted_at=early, deleted_batch_id=old_batch)
    c_under_old_sub = await make_comment(
        db, task_id=old_sub, workspace_id=w.ws.id, created_by=w.ba.id
    )  # неудалённый комментарий под УЖЕ удалённой подзадачей
    c_parent = await make_comment(db, task_id=parent, workspace_id=w.ws.id, created_by=w.ba.id)
    c_sub = await make_comment(db, task_id=sub1, workspace_id=w.ws.id, created_by=w.usr.id)
    c_old = await make_comment(
        db,
        task_id=parent,
        workspace_id=w.ws.id,
        created_by=w.ba.id,
        deleted_at=early,
        deleted_batch_id=old_batch,
    )
    # чужие: другая задача, её подзадача и комментарии, подзадача этой же задачи не затронута
    other = await mk_task(db, w)
    other_sub = await mk_task(db, w, parent_id=other)
    c_other = await make_comment(db, task_id=other, workspace_id=w.ws.id, created_by=w.ba.id)
    c_other_sub = await make_comment(
        db, task_id=other_sub, workspace_id=w.ws.id, created_by=w.ba.id
    )
    await db.commit()
    fixed_clock.advance(timedelta(minutes=5))
    now = fixed_clock.now()

    assert await svc.delete_task(db, actor_of(w.ba), parent) is None

    root = await task_row(db, parent)
    assert root.deleted_at == now
    batch = root.deleted_batch_id
    assert batch is not None
    assert batch != old_batch
    for tid in (sub1, sub2):
        r = await task_row(db, tid)
        assert (r.deleted_at, r.deleted_batch_id) == (now, batch)
    for cid in (c_parent.id, c_sub.id):
        r = await comment_row(db, cid)
        assert (r.deleted_at, r.deleted_batch_id) == (now, batch)
    # уже удалённое не перезаписывается
    r = await task_row(db, old_sub)
    assert (r.deleted_at, r.deleted_batch_id) == (early, old_batch)
    r = await comment_row(db, c_old.id)
    assert (r.deleted_at, r.deleted_batch_id) == (early, old_batch)
    # ранее удалённая подзадача — «ранее удалённое»: её комментарий не получает новый пакет
    r = await comment_row(db, c_under_old_sub.id)
    assert (r.deleted_at, r.deleted_batch_id) == (None, None)
    # другие задачи целы
    for tid in (other, other_sub):
        assert (await task_row(db, tid)).deleted_at is None
    for cid in (c_other.id, c_other_sub.id):
        assert (await comment_row(db, cid)).deleted_at is None
    assert await events(db, w.ws.id) == []
    # повторное удаление и обращение к подзадаче — 404
    await db.commit()  # иначе rollback в not_found() откатит удаление
    await not_found(db, svc.delete_task(db, actor_of(w.ba), parent))
    await not_found(db, svc.update_task(db, actor_of(w.ba), sub1, _patch(svc, title="Х")))


async def test_ac99_delete_subtask_keeps_parent_and_siblings(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    parent = await mk_task(db, w)
    sub = await mk_task(db, w, parent_id=parent, created_by=w.usr.id, assignee_id=w.usr.id)
    sibling = await mk_task(db, w, parent_id=parent)
    c = await make_comment(db, task_id=sub, workspace_id=w.ws.id, created_by=w.usr.id)
    c_parent = await make_comment(db, task_id=parent, workspace_id=w.ws.id, created_by=w.ba.id)
    await db.commit()
    await svc.delete_task(db, actor_of(w.usr), sub)  # своя подзадача пользователя
    r = await task_row(db, sub)
    assert r.deleted_at is not None
    assert (await comment_row(db, c.id)).deleted_batch_id == r.deleted_batch_id
    assert (await task_row(db, parent)).deleted_at is None
    assert (await task_row(db, sibling)).deleted_at is None
    assert (await comment_row(db, c_parent.id)).deleted_at is None


async def test_d56_delete_does_not_touch_other_columns_positions(
    db: AsyncSession, svc: Any
) -> None:
    w = await make_world(db)
    a = await mk_task(db, w, position=1024)
    b = await mk_task(db, w, position=2048)
    c = await mk_task(db, w, position=3072)
    await svc.delete_task(db, actor_of(w.ba), b)
    assert await column(db, w.project_id, "todo") == [a, c]
    assert (await task_row(db, a)).position == 1024
    assert (await task_row(db, c)).position == 3072


async def test_t74_review_delete_locks_task_row_for_no_key_update(
    db: AsyncSession, svc: Any
) -> None:
    w = await make_world(db)
    tid = await mk_task(db, w)
    with capture_sql(db) as seen:
        await svc.delete_task(db, actor_of(w.ba), tid)
    low = [s.lower() for s in seen]
    assert any("from task" in s and "for no key update" in s for s in low), seen


# --- гонки (committed) ------------------------------------------------------------------------


def _data(svc: Any, **kw: Any) -> Any:
    return svc.TaskCreateData(title="Подзадача", **kw)


@pytest.mark.committed
@pytest.mark.parametrize("op", ["create_subtask", "update_status"])
async def test_t74_review_reread_after_project_lock_sees_reassignment(
    committed: async_sessionmaker[AsyncSession], svc: Any, op: str
) -> None:
    """Другая сессия под FOR NO KEY UPDATE проекта меняет исполнителя родителя и фиксирует:
    операция бывшего исполнителя («Пользователь»), ждавшая FOR SHARE, перечитывает факты
    задачи после блокировки и получает 403 (мутант «убрать перечитывание» выживал)."""
    from app.core.errors import Forbidden

    async with committed() as setup:
        w = await make_world(setup)
        parent = await mk_task(setup, w, assignee_id=w.usr.id)
    holder = committed()
    try:
        await holder.execute(
            text("SELECT 1 FROM project WHERE id = :p FOR NO KEY UPDATE").bindparams(p=w.project_id)
        )
        await holder.execute(
            text("UPDATE task SET assignee_id = :a WHERE id = :t").bindparams(a=w.ba2.id, t=parent)
        )

        async def job() -> None:
            async with committed() as s:
                try:
                    if op == "create_subtask":
                        await svc.create_subtask(
                            s, actor_of(w.usr), parent, _data(svc, assignee=w.usr.id)
                        )
                    else:
                        await svc.update_task(
                            s, actor_of(w.usr), parent, svc.TaskPatch(status="done")
                        )
                    await s.commit()
                finally:
                    await s.rollback()

        task = asyncio.ensure_future(job())
        done, _ = await asyncio.wait({task}, timeout=0.5)
        assert not done, "операция не дождалась блокировки проекта"
        await holder.commit()
    finally:
        await holder.close()
    with pytest.raises(Forbidden):
        await asyncio.wait_for(task, timeout=10)
    async with committed() as s:
        r = await task_row(s, parent)
        assert (r.status, r.assignee_id) == ("todo", w.ba2.id)
        count = (
            await s.execute(
                text("SELECT count(*) FROM task WHERE parent_id = :t").bindparams(t=parent)
            )
        ).scalar_one()
        assert count == 0


async def _orphans(s: AsyncSession, project_id: uuid.UUID) -> int:
    return int(
        (
            await s.execute(
                text(
                    "SELECT count(*) FROM task c JOIN task p ON p.id = c.parent_id "
                    "WHERE c.project_id = :pr AND c.deleted_at IS NULL AND p.deleted_at IS NOT NULL"
                ).bindparams(pr=project_id)
            )
        ).scalar_one()
    )


@pytest.mark.committed
async def test_t74_review_create_subtask_waits_for_uncommitted_parent_delete(
    committed: async_sessionmaker[AsyncSession], svc: Any
) -> None:
    """Порядок 1: удаление родителя не зафиксировано — create_subtask ждёт строку родителя
    (FOR SHARE), после фиксации получает 404; неудалённой подзадачи под удалённым нет."""
    from app.core.errors import NotFound

    async with committed() as setup:
        w = await make_world(setup)
        parent = await mk_task(setup, w)
    holder = committed()
    try:
        await svc.delete_task(holder, actor_of(w.ba), parent)  # без commit

        async def job() -> None:
            async with committed() as s:
                try:
                    await svc.create_subtask(s, actor_of(w.ba), parent, _data(svc))
                    await s.commit()
                finally:
                    await s.rollback()

        task = asyncio.ensure_future(job())
        done, _ = await asyncio.wait({task}, timeout=0.5)
        assert not done, "create_subtask не ждёт строку удаляемого родителя"
        await holder.commit()
    finally:
        await holder.close()
    with pytest.raises(NotFound):
        await asyncio.wait_for(task, timeout=10)
    async with committed() as s:
        assert await _orphans(s, w.project_id) == 0
        assert (await task_row(s, parent)).deleted_at is not None


@pytest.mark.committed
async def test_t74_review_delete_waits_for_uncommitted_subtask_and_cascades_it(
    committed: async_sessionmaker[AsyncSession], svc: Any
) -> None:
    """Порядок 2: подзадача создана, но не зафиксирована — delete_task ждёт (строка задачи
    FOR NO KEY UPDATE против FOR SHARE создателя) и затем удаляет и её тем же пакетом."""
    async with committed() as setup:
        w = await make_world(setup)
        parent = await mk_task(setup, w)
    holder = committed()
    try:
        sub = await svc.create_subtask(holder, actor_of(w.ba), parent, _data(svc))  # без commit

        async def job() -> None:
            async with committed() as s:
                await svc.delete_task(s, actor_of(w.ba), parent)
                await s.commit()

        task = asyncio.ensure_future(job())
        done, _ = await asyncio.wait({task}, timeout=0.5)
        assert not done, "delete_task не ждёт создателя подзадачи (строка задачи не блокируется)"
        await holder.commit()
    finally:
        await holder.close()
    await asyncio.wait_for(task, timeout=10)
    async with committed() as s:
        p, c = await task_row(s, parent), await task_row(s, sub)
        assert p.deleted_at is not None
        assert (c.deleted_at, c.deleted_batch_id) == (p.deleted_at, p.deleted_batch_id)
        assert await _orphans(s, w.project_id) == 0


@pytest.mark.committed
async def test_t74_review_delete_vs_create_subtask_race_leaves_no_orphans(
    committed: async_sessionmaker[AsyncSession], svc: Any
) -> None:
    from app.core.errors import AppError

    async with committed() as setup:
        w = await make_world(setup)
        parents = [await mk_task(setup, w) for _ in range(8)]
    go = asyncio.Event()

    async def run(factory: Any) -> Any:
        async with committed() as s:
            await go.wait()
            try:
                await factory(s)
                await s.commit()
            except AppError as exc:
                await s.rollback()
                return str(exc.code)
            return "ok"

    jobs = []
    for p in parents:
        jobs.append(run(lambda s, p=p: svc.delete_task(s, actor_of(w.ba), p)))
        jobs.append(run(lambda s, p=p: svc.create_subtask(s, actor_of(w.ba), p, _data(svc))))
    futures = [asyncio.ensure_future(j) for j in jobs]
    await asyncio.sleep(0)
    go.set()
    results = await asyncio.wait_for(asyncio.gather(*futures, return_exceptions=True), timeout=30)
    assert all(r in ("ok", "not_found") for r in results), results
    async with committed() as s:
        assert await _orphans(s, w.project_id) == 0


@pytest.mark.committed
async def test_p10_2_update_assignee_waits_for_member_removal_then_422(
    committed: async_sessionmaker[AsyncSession], svc: Any
) -> None:
    """Исключение участника без фиксации блокирует проект: назначение ждёт и затем
    получает 422 not_project_member (получатель проверяется после блокировки)."""
    import app.domain.projects.members as members
    from app.core.errors import Unprocessable

    async with committed() as setup:
        w = await make_world(setup)
        tid = await mk_task(setup, w, assignee_id=None)
    holder = committed()
    try:
        await members.remove_member(holder, actor_of(w.ba), w.project_id, w.usr.id)  # без commit

        async def job() -> None:
            async with committed() as s:
                try:
                    await svc.update_task(
                        s, actor_of(w.ba), tid, svc.TaskPatch(assignee_id=w.usr.id)
                    )
                    await s.commit()
                finally:
                    await s.rollback()

        task = asyncio.ensure_future(job())
        done, _ = await asyncio.wait({task}, timeout=0.5)
        assert not done
        await holder.commit()
    finally:
        await holder.close()
    with pytest.raises(Unprocessable) as info:
        await asyncio.wait_for(task, timeout=10)
    assert str(info.value.code) == "not_project_member"
    async with committed() as s:
        assert w.usr.id not in await member_ids(s, w.project_id)
        assert (await task_row(s, tid)).assignee_id is None


# --- ревью T75, попытка 2 ---------------------------------------------------------------------


@pytest.mark.parametrize("who", ["usr2", "ba3", "sm", "ta", "norole"])
async def test_d46_non_participant_gets_403_even_for_empty_or_same_value_patch(
    db: AsyncSession, svc: Any, who: str
) -> None:
    """D-46: «права и 404 как обычно» — доступ к содержимому проверяется до «ничего не менять»."""
    w = await make_world(db)
    tid = await mk_task(db, w, assignee_id=w.usr.id, title="Т")
    before = await _snapshot(db, tid)
    actor = actor_of(getattr(w, who))
    for patch in (
        _patch(svc),
        _patch(svc, title="Т", status="todo", assignee_id=w.usr.id),
    ):
        await forbidden(db, svc.update_task(db, actor, tid, patch))
    assert await _snapshot(db, tid) == before


@pytest.mark.parametrize("what", ["title", "subtask_status"])
@pytest.mark.committed
async def test_p10_2_update_waits_for_uncommitted_delete_then_404(
    committed: async_sessionmaker[AsyncSession], svc: Any, what: str
) -> None:
    """Удаление не зафиксировано: update ждёт строку, затем 404; в удалённую строку не пишет."""
    from app.core.errors import NotFound

    async with committed() as setup:
        w = await make_world(setup)
        parent = await mk_task(setup, w)
        target = parent if what == "title" else await mk_task(setup, w, parent_id=parent)
    holder = committed()
    try:
        await svc.delete_task(holder, actor_of(w.ba), target)  # без commit
        patch = svc.TaskPatch(title="Новое") if what == "title" else svc.TaskPatch(status="done")

        async def job() -> None:
            async with committed() as s:
                try:
                    await svc.update_task(s, actor_of(w.ba), target, patch)
                    await s.commit()
                finally:
                    await s.rollback()

        task = asyncio.ensure_future(job())
        done, _ = await asyncio.wait({task}, timeout=0.5)
        assert not done, "update_task не ждёт блокировку строки задачи"
        await holder.commit()
    finally:
        await holder.close()
    with pytest.raises(NotFound):
        await asyncio.wait_for(task, timeout=10)
    async with committed() as s:
        r = await task_row(s, target)
        assert r.deleted_at is not None
        assert (r.title, r.status) == ("Задача", "todo")


async def test_p10_2_update_locks_task_row_for_no_key_update(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    tid = await mk_task(db, w)
    sub = await mk_task(db, w, parent_id=tid)
    for target, patch in ((tid, _patch(svc, title="Н")), (sub, _patch(svc, status="done"))):
        with capture_sql(db) as seen:
            await svc.update_task(db, actor_of(w.ba), target, patch)
        assert any("from task" in s.lower() and "for no key update" in s.lower() for s in seen)


async def test_t75_review_stale_identity_map_object_does_not_grant_rights(
    db: AsyncSession, svc: Any
) -> None:
    """Объект задачи в сессии устарел (исполнитель сменён вне ORM): права и сравнение —
    по актуальной строке (``populate_existing``), «бывший исполнитель» получает 403."""
    from app.domain.tasks.models import Task

    w = await make_world(db)
    tid = await mk_task(db, w, assignee_id=w.usr.id)
    stale = await db.get(Task, tid)
    assert stale is not None and stale.assignee_id == w.usr.id
    await db.execute(
        text("UPDATE task SET assignee_id = :a WHERE id = :t").bindparams(a=w.ba2.id, t=tid)
    )
    await db.commit()
    await forbidden(db, svc.update_task(db, actor_of(w.usr), tid, _patch(svc, status="done")))
    assert (await task_row(db, tid)).status == "todo"
    # и сравнение «поле не изменилось» идёт по актуальной строке
    await svc.update_task(db, actor_of(w.ba), tid, _patch(svc, assignee_id=w.usr.id))
    assert (await task_row(db, tid)).assignee_id == w.usr.id


# --- ревью T75, попытка 3: пересчёт после блокировки строки -----------------------------------


async def _waiting_job(committed: Any, holder_commit: Any, run: Any, *, timeout: float = 10) -> Any:
    """Запускает ``run(session)`` во второй сессии, проверяет, что она ждёт, фиксирует holder."""

    async def job() -> None:
        async with committed() as s:
            try:
                await run(s)
                await s.commit()
            finally:
                await s.rollback()

    task = asyncio.ensure_future(job())
    done, _ = await asyncio.wait({task}, timeout=0.5)
    assert not done, "update_task не ждёт блокировку строки задачи"
    await holder_commit()
    return await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=timeout)


@pytest.mark.committed
async def test_t75_review_user_title_update_after_owner_reassign_is_403(
    committed: async_sessionmaker[AsyncSession], svc: Any
) -> None:
    """Владелец (не зафиксировано) меняет title и исполнителя своей-задачи Пользователя;
    запрос Пользователя ждёт строку, затем права пересчитываются: 403, итог — «Владелец»."""
    from app.core.errors import Forbidden

    async with committed() as setup:
        w = await make_world(setup)
        tid = await mk_task(setup, w, created_by=w.usr.id, assignee_id=w.usr.id)
    holder = committed()
    try:
        await svc.update_task(
            holder,
            actor_of(w.ba),
            tid,
            svc.TaskPatch(title="Владелец", assignee_id=w.ba2.id),
        )  # без commit
        (outcome,) = await _waiting_job(
            committed,
            holder.commit,
            lambda s: svc.update_task(s, actor_of(w.usr), tid, svc.TaskPatch(title="Пользователь")),
        )
    finally:
        await holder.close()
    assert isinstance(outcome, Forbidden), outcome
    async with committed() as s:
        r = await task_row(s, tid)
        assert (r.title, r.assignee_id) == ("Владелец", w.ba2.id)


@pytest.mark.committed
async def test_t75_review_user_title_update_first_then_owner_reassign_both_apply(
    committed: async_sessionmaker[AsyncSession], svc: Any
) -> None:
    """Другой порядок: Пользователь фиксирует первым, владелец ждёт и затем применяет своё."""
    async with committed() as setup:
        w = await make_world(setup)
        tid = await mk_task(setup, w, created_by=w.usr.id, assignee_id=w.usr.id)
    holder = committed()
    try:
        await svc.update_task(holder, actor_of(w.usr), tid, svc.TaskPatch(title="Пользователь"))
        (outcome,) = await _waiting_job(
            committed,
            holder.commit,
            lambda s: svc.update_task(
                s,
                actor_of(w.ba),
                tid,
                svc.TaskPatch(title="Владелец", assignee_id=w.ba2.id),
            ),
        )
    finally:
        await holder.close()
    assert outcome is None, outcome
    async with committed() as s:
        r = await task_row(s, tid)
        assert (r.title, r.assignee_id) == ("Владелец", w.ba2.id)


@pytest.mark.committed
async def test_t75_review_assignee_status_change_after_reassign_is_403_and_nothing_moves(
    committed: async_sessionmaker[AsyncSession], svc: Any
) -> None:
    from app.core.errors import Forbidden

    async with committed() as setup:
        w = await make_world(setup)
        tid = await mk_task(setup, w, assignee_id=w.usr.id, position=1024)
        other = await mk_task(setup, w, status="done", position=2048)
    holder = committed()
    try:
        await svc.update_task(holder, actor_of(w.ba), tid, svc.TaskPatch(assignee_id=w.ba2.id))
        (outcome,) = await _waiting_job(
            committed,
            holder.commit,
            lambda s: svc.update_task(s, actor_of(w.usr), tid, svc.TaskPatch(status="done")),
        )
    finally:
        await holder.close()
    assert isinstance(outcome, Forbidden), outcome
    async with committed() as s:
        r = await task_row(s, tid)
        assert (r.status, r.position, r.assignee_id) == ("todo", 1024, w.ba2.id)
        assert await column(s, w.project_id, "done") == [other]


@pytest.mark.committed
async def test_t75_review_assignee_removed_concurrently_status_change_rejected(
    committed: async_sessionmaker[AsyncSession], svc: Any
) -> None:
    import app.domain.projects.members as members
    from app.core.errors import AppError

    async with committed() as setup:
        w = await make_world(setup)
        tid = await mk_task(setup, w, assignee_id=w.usr.id, position=1024)
    holder = committed()
    try:
        await members.remove_member(holder, actor_of(w.ba), w.project_id, w.usr.id)  # без commit
        (outcome,) = await _waiting_job(
            committed,
            holder.commit,
            lambda s: svc.update_task(s, actor_of(w.usr), tid, svc.TaskPatch(status="done")),
        )
    finally:
        await holder.close()
    assert isinstance(outcome, AppError), outcome
    assert outcome.status_code == 403, outcome
    async with committed() as s:
        r = await task_row(s, tid)
        assert (r.status, r.position, r.assignee_id) == ("todo", 1024, None)
        assert w.usr.id not in await member_ids(s, w.project_id)


@pytest.mark.committed
async def test_t75_review_two_updates_of_same_field_last_wins_updated_at_monotonic(
    committed: async_sessionmaker[AsyncSession], svc: Any
) -> None:
    async with committed() as setup:
        w = await make_world(setup)
        tid = await mk_task(setup, w)
    holder = committed()
    try:
        await svc.update_task(holder, actor_of(w.ba), tid, svc.TaskPatch(title="Первый"))
        first_updated = (await task_row(holder, tid)).updated_at
        (outcome,) = await _waiting_job(
            committed,
            holder.commit,
            lambda s: svc.update_task(s, actor_of(w.ba), tid, svc.TaskPatch(title="Второй")),
        )
    finally:
        await holder.close()
    assert outcome is None, outcome
    async with committed() as s:
        r = await task_row(s, tid)
        assert r.title == "Второй"
        assert r.updated_at >= first_updated


@pytest.mark.committed
async def test_t75_review_many_parallel_updates_no_deadlock_no_5xx(
    committed: async_sessionmaker[AsyncSession], svc: Any
) -> None:
    async with committed() as setup:
        w = await make_world(setup)
        tid = await mk_task(setup, w, assignee_id=w.usr.id)
        sub = await mk_task(setup, w, parent_id=tid)
    go = asyncio.Event()

    async def run(actor: Any, target: uuid.UUID, **fields: Any) -> Any:
        async with committed() as s:
            await go.wait()
            try:
                await svc.update_task(s, actor, target, svc.TaskPatch(**fields))
                await s.commit()
            except Exception as exc:
                await s.rollback()
                return exc
            return None

    owner, assignee = actor_of(w.ba), actor_of(w.usr)
    futures = [
        asyncio.ensure_future(c)
        for c in (
            run(owner, tid, title="А"),
            run(owner, tid, status="review"),
            run(owner, tid, status="done"),
            run(assignee, tid, status="in_progress"),
            run(owner, tid, assignee_id=w.ba2.id),
            run(owner, sub, status="done"),
            run(owner, sub, title="Подзадача"),
            run(owner, tid, priority="high"),
        )
    ]
    await asyncio.sleep(0)
    go.set()
    outcomes = await asyncio.wait_for(asyncio.gather(*futures), timeout=30)
    from app.core.errors import AppError

    for o in outcomes:
        assert o is None or (isinstance(o, AppError) and o.status_code == 403), outcomes
    async with committed() as s:
        r = await task_row(s, tid)
        assert r.position is not None and r.deleted_at is None


# --- ревью T75, финал: выжившие мутанты -------------------------------------------------------


@pytest.mark.committed
async def test_t75_review_create_subtask_rechecks_rights_after_owner_reassign(
    committed: async_sessionmaker[AsyncSession], svc: Any
) -> None:
    """Владелец (не зафиксировано) переназначает родителя; бывший исполнитель-Пользователь,
    ждавший строку, получает 403 по перечитанным фактам, подзадача не создаётся."""
    from app.core.errors import Forbidden

    async with committed() as setup:
        w = await make_world(setup)
        parent = await mk_task(setup, w, assignee_id=w.usr.id)
    holder = committed()
    try:
        await svc.update_task(holder, actor_of(w.ba), parent, svc.TaskPatch(assignee_id=w.ba2.id))
        (outcome,) = await _waiting_job(
            committed,
            holder.commit,
            lambda s: svc.create_subtask(
                s, actor_of(w.usr), parent, svc.TaskCreateData(title="Под", assignee=w.usr.id)
            ),
        )
    finally:
        await holder.close()
    assert isinstance(outcome, Forbidden), outcome
    async with committed() as s:
        assert (await task_row(s, parent)).assignee_id == w.ba2.id
        count = (
            await s.execute(
                text("SELECT count(*) FROM task WHERE parent_id = :t").bindparams(t=parent)
            )
        ).scalar_one()
        assert count == 0


async def test_d46_full_form_with_unchanged_blocked_assignee_is_ok(
    db: AsyncSession, svc: Any
) -> None:
    """AC-43/D-46: неизменный заблокированный исполнитель не проверяется как получатель."""
    w = await make_world(db)
    blocked_member = await make_user(
        db, workspace=w.ws, role="user", login="w.blockedm", blocked=True
    )
    await add_member_row(db, w, w.project_id, blocked_member)
    tid = await mk_task(db, w, assignee_id=blocked_member.id, title="T")
    await svc.update_task(
        db,
        actor_of(w.ba),
        tid,
        _patch(svc, title="T2", assignee_id=blocked_member.id, status="in_progress"),
    )
    r = await task_row(db, tid)
    assert (r.title, r.assignee_id, r.status) == ("T2", blocked_member.id, "in_progress")


@pytest.mark.committed
async def test_t75_review_recipient_error_after_concurrent_reassign_is_not_swallowed(
    committed: async_sessionmaker[AsyncSession], svc: Any
) -> None:
    """Исполнитель заблокирован; A шлёт форму с ним же, пока B (не зафиксировано) назначает
    ``usr``. После фиксации «заблокированный» для A — уже новый получатель: 422 user_blocked."""
    from app.core.errors import AppError

    async with committed() as setup:
        w = await make_world(setup)
        blocked_member = await make_user(
            setup, workspace=w.ws, role="user", login="w.blockedm", blocked=True
        )
        await add_member_row(setup, w, w.project_id, blocked_member)
        await add_member_row(setup, w, w.project_id, w.sm)
        await setup.commit()
        tid = await mk_task(setup, w, assignee_id=blocked_member.id, title="T")
    holder = committed()
    try:
        await svc.update_task(holder, actor_of(w.sm), tid, svc.TaskPatch(assignee_id=w.usr.id))
        (outcome,) = await _waiting_job(
            committed,
            holder.commit,
            lambda s: svc.update_task(
                s,
                actor_of(w.ba),
                tid,
                svc.TaskPatch(title="T3", assignee_id=blocked_member.id),
            ),
        )
    finally:
        await holder.close()
    assert isinstance(outcome, AppError), outcome
    assert (outcome.status_code, str(outcome.code)) == (422, "user_blocked"), outcome
    async with committed() as s:
        r = await task_row(s, tid)
        assert (r.title, r.assignee_id) == ("T", w.usr.id)
