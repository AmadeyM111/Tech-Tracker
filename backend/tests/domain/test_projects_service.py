"""T71: сервис и выборки проектов (plan §11.4, §11.5, §10.2, §10.4; D-45, D-46, D-52, D-55, D-56).

AC-48, AC-50...AC-55, AC-65, AC-72, AC-108, AC-110; FR-14, FR-14a, FR-14c, FR-16, FR-17, FR-41.

Ожидаемый интерфейс (MVP, plan §10.4 без ``set_archived`` и фильтра статуса). Все функции
``async``, первые аргументы ``db: AsyncSession, actor: Actor``, ``commit()`` не вызывают::

    app.domain.projects.queries
        load_project_facts(db, actor, project_id, *, lock: Literal["update", "share"] | None = None)
            -> app.domain.access.policy.ProjectFacts     # NotFound (404): нет, удалён, чужой ws
        list_projects(db, actor, params: PageParams) -> tuple[list[ProjectListRow], bool]
            # ProjectListRow: id, name, owner (id, login), task_count
        get_project(db, actor, project_id) -> ProjectView          # NotFound 404, Forbidden 403
    app.domain.projects.service
        @dataclass(frozen=True) ProjectPatch(name: str | None = None,
                                             description: str | None = None)
        create_project(db, actor, *, name: str, description: str = "") -> ProjectView
        update_project(db, actor, project_id, *, changes: ProjectPatch) -> ProjectView
        transfer_ownership(db, actor, project_id, *, new_owner_id: UUID) -> ProjectView
        delete_project(db, actor, project_id) -> None
    ProjectView: id, name, description, owner (id, login), task_count, is_member, created_at,
        updated_at, permissions (manage, manage_members, create_task, remove_self).

Ошибки: Forbidden (403), NotFound (404), Unprocessable (422; ``validation_error`` для длин и
пустого названия, коды получателя из ``check_recipient``).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.pagination import PageParams
from app.domain.access.policy import ProjectFacts
from tests.factories import (
    make_comment,
    make_project,
    make_project_member,
    make_task,
    make_user,
    make_workspace,
)
from tests.projects_support import (
    LONG_DESC_10000,
    LONG_NAME_255,
    World,
    actor_of,
    capture_sql,
    events,
    fails,
    forbidden,
    make_world,
    member_ids,
    not_found,
    project_row,
    task_row,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.core.clock import FixedClock


@pytest.fixture
def queries() -> Any:
    import app.domain.projects.queries as module

    return module


@pytest.fixture
def svc() -> Any:
    import app.domain.projects.service as module

    return module


def _patch(svc: Any, **kw: Any) -> Any:
    return svc.ProjectPatch(**kw)


async def _count_projects(db: AsyncSession, ws_id: uuid.UUID) -> int:
    await db.flush()
    return int(
        (
            await db.execute(
                text("SELECT count(*) FROM project WHERE workspace_id = :w").bindparams(w=ws_id)
            )
        ).scalar_one()
    )


# --- load_project_facts ----------------------------------------------------------------------


async def test_fr14_load_project_facts_returns_owner_and_membership(
    db: AsyncSession, queries: Any
) -> None:
    w = await make_world(db)
    f = await queries.load_project_facts(db, actor_of(w.ba), w.project_id)
    assert f == ProjectFacts(project_id=w.project_id, owner_id=w.ba.id, actor_is_member=True)
    f = await queries.load_project_facts(db, actor_of(w.usr), w.project_id)
    assert f == ProjectFacts(project_id=w.project_id, owner_id=w.ba.id, actor_is_member=True)
    f = await queries.load_project_facts(db, actor_of(w.sm), w.project_id)
    assert f.actor_is_member is False
    assert f.owner_id == w.ba.id


async def test_t70_review_owner_is_always_member_in_facts(db: AsyncSession, queries: Any) -> None:
    """Заметка ревью T70 п.2: владелец проекта всегда участник, даже без строки членства."""
    w = await make_world(db)
    lonely = await make_project(db, workspace_id=w.ws.id, owner_id=w.ba3.id, name="Без строки")
    await db.commit()
    f = await queries.load_project_facts(db, actor_of(w.ba3), lonely.id)
    assert f.owner_id == w.ba3.id
    assert f.actor_is_member is True


async def test_fr13_load_project_facts_404_unknown_deleted_foreign(
    db: AsyncSession, queries: Any, fixed_clock: FixedClock
) -> None:
    w = await make_world(db)
    other_ws = await make_workspace(db)
    other_owner = await make_user(db, workspace=other_ws, role="business_admin")
    foreign = await make_project(db, workspace_id=other_ws.id, owner_id=other_owner.id)
    deleted = await make_project(
        db,
        workspace_id=w.ws.id,
        owner_id=w.ba.id,
        deleted_at=fixed_clock.now(),
        deleted_batch_id=uuid.uuid4(),
    )
    await db.commit()
    for pid in (uuid.uuid4(), foreign.id, deleted.id):
        await not_found(db, queries.load_project_facts(db, actor_of(w.ba), pid))


async def test_t71_load_project_facts_is_single_query(db: AsyncSession, queries: Any) -> None:
    w = await make_world(db)
    with capture_sql(db) as seen:
        await queries.load_project_facts(db, actor_of(w.usr), w.project_id)
    selects = [s for s in seen if s.lstrip().lower().startswith("select")]
    assert len(selects) == 1, selects
    assert " for no key update" not in selects[0].lower()
    assert " for share" not in selects[0].lower()


@pytest.mark.parametrize(
    ("lock", "needle"), [("update", "for no key update"), ("share", "for share")]
)
async def test_p10_2_load_project_facts_lock_sql(
    db: AsyncSession, queries: Any, lock: str, needle: str
) -> None:
    w = await make_world(db)
    with capture_sql(db) as seen:
        await queries.load_project_facts(db, actor_of(w.ba), w.project_id, lock=lock)
    locking = [s for s in seen if needle in s.lower()]
    assert locking, seen
    assert any("project" in s.lower() for s in locking)


@pytest.mark.parametrize(
    ("lock", "conflicting", "compatible"),
    [
        ("update", "FOR SHARE", None),
        ("update", "FOR NO KEY UPDATE", None),
        ("share", "FOR NO KEY UPDATE", "FOR SHARE"),
    ],
)
@pytest.mark.committed
async def test_p10_2_load_project_facts_lock_conflicts(
    committed: async_sessionmaker[AsyncSession],
    queries: Any,
    lock: str,
    conflicting: str,
    compatible: str | None,
) -> None:
    """update = FOR NO KEY UPDATE (п.1), share = FOR SHARE (п.2): проверка конфликтов NOWAIT."""
    async with committed() as setup:
        w = await make_world(setup)
        await setup.commit()

    async def nowait(mode: str) -> None:
        async with committed() as s:
            await s.execute(
                text(f"SELECT 1 FROM project WHERE id = :p {mode} NOWAIT").bindparams(  # noqa: S608
                    p=w.project_id
                )
            )
            await s.rollback()

    async with committed() as holder:
        await queries.load_project_facts(holder, actor_of(w.ba), w.project_id, lock=lock)
        with pytest.raises(DBAPIError, match="lock"):
            await nowait(conflicting)
        if compatible is not None:
            await nowait(compatible)
        await holder.rollback()
    await nowait(conflicting)


@pytest.mark.committed
async def test_p10_2_load_project_facts_without_lock_does_not_lock(
    committed: async_sessionmaker[AsyncSession], queries: Any
) -> None:
    async with committed() as setup:
        w = await make_world(setup)
        await setup.commit()
    async with committed() as holder:
        await queries.load_project_facts(holder, actor_of(w.ba), w.project_id)
        async with committed() as other:
            await other.execute(
                text("SELECT 1 FROM project WHERE id = :p FOR UPDATE NOWAIT").bindparams(
                    p=w.project_id
                )
            )
            await other.rollback()
        await holder.rollback()


# --- create_project --------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["business_admin", "mixed"])
async def test_ac51_create_project_owner_and_member_are_actor(
    db: AsyncSession, svc: Any, role: str
) -> None:
    ws = await make_workspace(db)
    user = await make_user(db, workspace=ws, role=role, login=f"cr.{role}")
    await db.commit()
    view = await svc.create_project(db, actor_of(user), name="Новый проект")
    await db.commit()
    assert view.name == "Новый проект"
    assert view.description == ""
    assert view.owner.id == user.id
    assert view.owner.login == user.login
    assert view.is_member is True
    assert view.task_count == 0
    row = await project_row(db, view.id)
    assert row.workspace_id == ws.id
    assert row.owner_id == user.id
    assert row.created_by == user.id
    assert row.deleted_at is None
    assert await member_ids(db, view.id) == {user.id}
    m = (
        await db.execute(
            text(
                "SELECT workspace_id, created_by FROM project_member WHERE project_id = :p"
            ).bindparams(p=view.id)
        )
    ).one()
    assert m.workspace_id == ws.id
    assert m.created_by == user.id
    assert await events(db, ws.id) == []  # D-55: событий ленты нет, передачи владения нет


@pytest.mark.parametrize("role", ["user", "tech_admin", None])
async def test_ac75_create_project_requires_project_create_capability(
    db: AsyncSession, svc: Any, role: str | None
) -> None:
    ws = await make_workspace(db)
    user = await make_user(db, workspace=ws, role=role, login=f"nocr.{role or 'none'}")
    await db.commit()
    await forbidden(db, svc.create_project(db, actor_of(user), name="Нельзя"))
    assert await _count_projects(db, ws.id) == 0


async def test_ac108_create_project_boundaries_ok(db: AsyncSession, svc: Any) -> None:
    ws = await make_workspace(db)
    user = await make_user(db, workspace=ws, role="business_admin")
    await db.commit()
    view = await svc.create_project(
        db, actor_of(user), name=LONG_NAME_255, description=LONG_DESC_10000
    )
    row = await project_row(db, view.id)
    assert row.name == LONG_NAME_255
    assert row.description == LONG_DESC_10000
    one = await svc.create_project(db, actor_of(user), name="x")
    assert one.name == "x"


@pytest.mark.parametrize(
    ("name", "description"),
    [
        ("Я" * 256, ""),
        ("Нормальное", "д" * 10_001),
        ("", ""),
        ("   \t\n ", ""),
    ],
    ids=["name-256", "description-10001", "name-empty", "name-whitespace-d52"],
)
async def test_ac108_create_project_invalid_is_422(
    db: AsyncSession, svc: Any, name: str, description: str
) -> None:
    ws = await make_workspace(db)
    user = await make_user(db, workspace=ws, role="business_admin")
    await db.commit()
    await fails(
        db,
        svc.create_project(db, actor_of(user), name=name, description=description),
        "validation_error",
    )
    assert await _count_projects(db, ws.id) == 0
    assert await events(db, ws.id) == []


async def test_d52_name_is_stored_as_entered_without_trim(db: AsyncSession, svc: Any) -> None:
    ws = await make_workspace(db)
    user = await make_user(db, workspace=ws, role="business_admin")
    await db.commit()
    view = await svc.create_project(db, actor_of(user), name="  Пробелы по краям  ")
    assert (await project_row(db, view.id)).name == "  Пробелы по краям  "


# --- update_project --------------------------------------------------------------------------


async def test_ac110_owner_ba_updates_name_and_description(
    db: AsyncSession, svc: Any, fixed_clock: FixedClock
) -> None:
    w = await make_world(db)
    fixed_clock.advance(timedelta(hours=1))
    view = await svc.update_project(
        db, actor_of(w.ba), w.project_id, changes=_patch(svc, name="Новое", description="Описание")
    )
    assert (view.name, view.description) == ("Новое", "Описание")
    row = await project_row(db, w.project_id)
    assert (row.name, row.description) == ("Новое", "Описание")
    assert row.updated_at == fixed_clock.now()
    assert row.owner_id == w.ba.id
    assert await events(db, w.ws.id) == []  # D-55: project.updated не пишется


async def test_ac110_sm_not_member_updates_any_project(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    view = await svc.update_project(
        db, actor_of(w.sm), w.project_id, changes=_patch(svc, name="СМ")
    )
    assert view.name == "СМ"
    assert (await project_row(db, w.project_id)).description == ""  # не переданное не тронуто


@pytest.mark.parametrize("who", ["ba2", "usr", "ba3", "usr2", "ta", "norole"])
async def test_ac110_other_roles_get_403_and_project_unchanged(
    db: AsyncSession, svc: Any, who: str
) -> None:
    w = await make_world(db)
    await forbidden(
        db,
        svc.update_project(
            db, actor_of(getattr(w, who)), w.project_id, changes=_patch(svc, name="Z")
        ),
    )
    row = await project_row(db, w.project_id)
    assert row.name == "Основной"


async def test_ac110_update_foreign_or_deleted_is_404(
    db: AsyncSession, svc: Any, fixed_clock: FixedClock
) -> None:
    w = await make_world(db)
    await db.execute(
        text("UPDATE project SET deleted_at = :t, deleted_batch_id = :b WHERE id = :p").bindparams(
            t=fixed_clock.now(), b=uuid.uuid4(), p=w.project_id
        )
    )
    await db.commit()
    await not_found(
        db, svc.update_project(db, actor_of(w.ba), w.project_id, changes=_patch(svc, name="Z"))
    )
    await not_found(
        db, svc.update_project(db, actor_of(w.ba), uuid.uuid4(), changes=_patch(svc, name="Z"))
    )


async def test_d46_update_without_changes_does_nothing(
    db: AsyncSession, svc: Any, fixed_clock: FixedClock
) -> None:
    w = await make_world(db)
    before = await project_row(db, w.project_id)
    fixed_clock.advance(timedelta(hours=2))
    for patch in (
        _patch(svc),
        _patch(svc, name="Основной"),
        _patch(svc, name="Основной", description=""),
    ):
        view = await svc.update_project(db, actor_of(w.ba), w.project_id, changes=patch)
        assert view.name == "Основной"
    after = await project_row(db, w.project_id)
    assert after.updated_at == before.updated_at
    assert (after.name, after.description) == (before.name, before.description)
    assert await events(db, w.ws.id) == []


async def test_d46_no_change_still_checks_permissions(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    await forbidden(
        db,
        svc.update_project(db, actor_of(w.ba2), w.project_id, changes=_patch(svc, name="Основной")),
    )


async def test_ac108_update_boundaries(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    view = await svc.update_project(
        db,
        actor_of(w.ba),
        w.project_id,
        changes=_patch(svc, name=LONG_NAME_255, description=LONG_DESC_10000),
    )
    assert len(view.name) == 255
    assert len(view.description) == 10_000
    await db.commit()
    for patch in (
        _patch(svc, name="Я" * 256),
        _patch(svc, description="д" * 10_001),
        _patch(svc, name=""),
        _patch(svc, name="  "),
    ):
        await fails(
            db,
            svc.update_project(db, actor_of(w.ba), w.project_id, changes=patch),
            "validation_error",
        )
    row = await project_row(db, w.project_id)
    assert row.name == LONG_NAME_255  # данные не изменены


# --- transfer_ownership ----------------------------------------------------------------------


async def _transfer_world(db: AsyncSession) -> World:
    """БА-владелец; участники: ba2 (БА), usr (П), sm2 (СМ); не участник: ba3."""
    w = await make_world(db)
    sm2 = await make_user(db, workspace=w.ws, role="mixed", login="w.sm2")
    await make_project_member(
        db, project_id=w.project_id, user_id=sm2.id, workspace_id=w.ws.id, created_by=w.ba.id
    )
    w.sm2 = sm2  # type: ignore[attr-defined]
    await db.commit()
    return w


async def test_ac52_owner_transfers_to_ba_member_and_loses_manage(
    db: AsyncSession, svc: Any
) -> None:
    w = await _transfer_world(db)
    view = await svc.transfer_ownership(db, actor_of(w.ba), w.project_id, new_owner_id=w.ba2.id)
    assert view.owner.id == w.ba2.id
    assert view.owner.login == w.ba2.login
    assert (await project_row(db, w.project_id)).owner_id == w.ba2.id
    assert await member_ids(db, w.project_id) >= {w.ba.id, w.ba2.id}  # бывший владелец остаётся
    await db.commit()
    await forbidden(db, svc.delete_project(db, actor_of(w.ba), w.project_id))
    await forbidden(
        db, svc.update_project(db, actor_of(w.ba), w.project_id, changes=_patch(svc, name="x"))
    )


async def test_ac52_sm_transfers_to_sm_member(db: AsyncSession, svc: Any) -> None:
    w = await _transfer_world(db)
    view = await svc.transfer_ownership(
        db,
        actor_of(w.sm),
        w.project_id,
        new_owner_id=w.sm2.id,  # type: ignore[attr-defined]
    )
    assert view.owner.id == w.sm2.id  # type: ignore[attr-defined]


async def test_ac72_sm_not_member_transfers_when_owner_blocked(db: AsyncSession, svc: Any) -> None:
    w = await _transfer_world(db)
    await db.execute(
        text("UPDATE app_user SET is_blocked = true WHERE id = :u").bindparams(u=w.ba.id)
    )
    await db.commit()
    view = await svc.transfer_ownership(db, actor_of(w.sm), w.project_id, new_owner_id=w.ba2.id)
    assert view.owner.id == w.ba2.id


@pytest.mark.parametrize("who", ["ba2", "usr", "ba3", "ta", "norole"])
async def test_ac52_ac72_transfer_by_non_manager_is_403(
    db: AsyncSession, svc: Any, who: str
) -> None:
    w = await _transfer_world(db)
    await forbidden(
        db,
        svc.transfer_ownership(db, actor_of(getattr(w, who)), w.project_id, new_owner_id=w.ba2.id),
    )
    assert (await project_row(db, w.project_id)).owner_id == w.ba.id
    assert await events(db, w.ws.id) == []


async def test_p11_5_forbidden_precedes_recipient_check(db: AsyncSession, svc: Any) -> None:
    w = await _transfer_world(db)
    await forbidden(
        db, svc.transfer_ownership(db, actor_of(w.ba2), w.project_id, new_owner_id=w.usr.id)
    )


async def test_ac52_transfer_to_user_role_is_422(db: AsyncSession, svc: Any) -> None:
    w = await _transfer_world(db)
    await fails(
        db,
        svc.transfer_ownership(db, actor_of(w.ba), w.project_id, new_owner_id=w.usr.id),
        "recipient_wrong_role",
    )
    assert (await project_row(db, w.project_id)).owner_id == w.ba.id
    assert await events(db, w.ws.id) == []


async def test_ac74_transfer_recipient_codes(db: AsyncSession, svc: Any) -> None:
    w = await _transfer_world(db)
    blocked_member = await make_user(
        db, workspace=w.ws, role="business_admin", login="w.blockedba", blocked=True
    )
    await make_project_member(
        db, project_id=w.project_id, user_id=blocked_member.id, workspace_id=w.ws.id
    )
    ta_member = await make_user(db, workspace=w.ws, role="tech_admin", login="w.tamember")
    await make_project_member(
        db, project_id=w.project_id, user_id=ta_member.id, workspace_id=w.ws.id
    )
    foreign_ws = await make_workspace(db)
    foreign = await make_user(db, workspace=foreign_ws, role="business_admin", login="w.foreign")
    await db.commit()
    cases = [
        (w.ba3.id, "not_project_member"),
        (blocked_member.id, "user_blocked"),
        (ta_member.id, "recipient_wrong_role"),
        (w.norole.id, "recipient_wrong_role"),
        (foreign.id, "user_not_found"),
        (uuid.uuid4(), "user_not_found"),
    ]
    for user_id, code in cases:
        await fails(
            db,
            svc.transfer_ownership(db, actor_of(w.ba), w.project_id, new_owner_id=user_id),
            code,
        )
    assert (await project_row(db, w.project_id)).owner_id == w.ba.id
    assert await events(db, w.ws.id) == []
    assert w.ba3.id not in await member_ids(db, w.project_id)  # в участники не добавляется


async def test_d46_transfer_to_current_owner_is_noop_without_event(
    db: AsyncSession, svc: Any, fixed_clock: FixedClock
) -> None:
    w = await _transfer_world(db)
    before = await project_row(db, w.project_id)
    fixed_clock.advance(timedelta(hours=1))
    view = await svc.transfer_ownership(db, actor_of(w.ba), w.project_id, new_owner_id=w.ba.id)
    assert view.owner.id == w.ba.id
    assert (await project_row(db, w.project_id)).updated_at == before.updated_at
    assert await events(db, w.ws.id) == []


async def test_ac65_transfer_writes_audit_event_with_owner_change(
    db: AsyncSession, svc: Any
) -> None:
    w = await _transfer_world(db)
    await svc.transfer_ownership(db, actor_of(w.ba), w.project_id, new_owner_id=w.ba2.id)
    rows = await events(db, w.ws.id)
    assert len(rows) == 1
    ev = rows[0]
    assert ev.action == "project.ownership_transferred"
    assert ev.entity_type == "project"
    assert ev.entity_id == w.project_id
    assert ev.project_id == w.project_id
    assert ev.actor_id == w.ba.id
    assert ev.in_audit is True
    assert ev.workspace_id == w.ws.id
    assert list(ev.changed_fields) == ["owner_id"]
    assert len(ev.changes) == 1
    change = ev.changes[0]
    assert change["field"] == "owner_id"
    assert {k: str(v) for k, v in change["old"].items()} == {
        "id": str(w.ba.id),
        "login": w.ba.login,
    }
    assert {k: str(v) for k, v in change["new"].items()} == {
        "id": str(w.ba2.id),
        "login": w.ba2.login,
    }
    dump = repr(tuple(ev))
    assert "Основной" not in dump  # название проекта в журнал не попадает (AC-65)


async def test_ac65_second_transfer_writes_second_event_only_on_change(
    db: AsyncSession, svc: Any
) -> None:
    w = await _transfer_world(db)
    await svc.transfer_ownership(db, actor_of(w.sm), w.project_id, new_owner_id=w.ba2.id)
    await svc.transfer_ownership(db, actor_of(w.sm), w.project_id, new_owner_id=w.ba2.id)
    await svc.transfer_ownership(db, actor_of(w.sm), w.project_id, new_owner_id=w.ba.id)
    rows = await events(db, w.ws.id)
    assert [r.action for r in rows] == ["project.ownership_transferred"] * 2
    assert rows[0].actor_id == w.sm.id


async def test_p10_2_transfer_locks_project_before_recipient(db: AsyncSession, svc: Any) -> None:
    w = await _transfer_world(db)
    with capture_sql(db) as seen:
        await svc.transfer_ownership(db, actor_of(w.ba), w.project_id, new_owner_id=w.ba2.id)
    low = [s.lower() for s in seen]
    project_lock = next(
        i for i, s in enumerate(low) if "for no key update" in s and "from project" in s
    )
    recipient_lock = next(
        i
        for i, s in enumerate(low)
        if "for share" in s and ("app_user" in s or "workspace_member" in s)
    )
    assert project_lock < recipient_lock  # §10.2: п.1 раньше п.3


async def test_fr13_transfer_foreign_or_unknown_project_is_404(db: AsyncSession, svc: Any) -> None:
    w = await _transfer_world(db)
    other = await make_workspace(db)
    other_owner = await make_user(db, workspace=other, role="business_admin")
    foreign = await make_project(db, workspace_id=other.id, owner_id=other_owner.id)
    await db.commit()
    for pid in (uuid.uuid4(), foreign.id):
        await not_found(db, svc.transfer_ownership(db, actor_of(w.sm), pid, new_owner_id=w.ba2.id))


# --- delete_project --------------------------------------------------------------------------


async def _tree(db: AsyncSession, w: World, fixed_clock: FixedClock) -> dict[str, Any]:
    """Проект с задачей, подзадачей, комментариями, уже удалёнными объектами и чужим проектом."""
    ws_id = w.ws.id
    t1 = await make_task(db, project_id=w.project_id, workspace_id=ws_id, created_by=w.ba.id)
    sub = await make_task(
        db, project_id=w.project_id, workspace_id=ws_id, created_by=w.ba.id, parent_id=t1.id
    )
    c1 = await make_comment(db, task_id=t1.id, workspace_id=ws_id, created_by=w.ba.id)
    c_sub = await make_comment(db, task_id=sub.id, workspace_id=ws_id, created_by=w.ba.id)
    early = fixed_clock.now() - timedelta(days=3)
    old_batch = uuid.uuid4()
    t_old = await make_task(
        db,
        project_id=w.project_id,
        workspace_id=ws_id,
        created_by=w.ba.id,
        deleted_at=early,
        deleted_batch_id=old_batch,
    )
    c_old_of_old = await make_comment(
        db,
        task_id=t_old.id,
        workspace_id=ws_id,
        created_by=w.ba.id,
        deleted_at=early,
        deleted_batch_id=old_batch,
    )
    c_old = await make_comment(
        db,
        task_id=t1.id,
        workspace_id=ws_id,
        created_by=w.ba.id,
        deleted_at=early,
        deleted_batch_id=old_batch,
    )
    sub_old = await make_task(
        db,
        project_id=w.project_id,
        workspace_id=ws_id,
        created_by=w.ba.id,
        parent_id=t1.id,
        deleted_at=early,
        deleted_batch_id=old_batch,
    )
    other = await make_project(db, workspace_id=ws_id, owner_id=w.ba.id, name="Другой")
    t_other = await make_task(db, project_id=other.id, workspace_id=ws_id, created_by=w.ba.id)
    c_other = await make_comment(db, task_id=t_other.id, workspace_id=ws_id, created_by=w.ba.id)
    await db.commit()
    return {
        "live": [t1.id, sub.id],
        "live_comments": [c1.id, c_sub.id],
        "old_tasks": [t_old.id, sub_old.id],
        "old_comments": [c_old_of_old.id, c_old.id],
        "early": early,
        "old_batch": old_batch,
        "other": other.id,
        "t_other": t_other.id,
        "c_other": c_other.id,
    }


@pytest.mark.parametrize("who", ["ba", "sm"])
async def test_ac48_owner_ba_and_sm_delete_project_softly(
    db: AsyncSession, svc: Any, fixed_clock: FixedClock, who: str
) -> None:
    w = await make_world(db)
    tree = await _tree(db, w, fixed_clock)
    fixed_clock.advance(timedelta(minutes=5))
    now = fixed_clock.now()
    result = await svc.delete_project(db, actor_of(getattr(w, who)), w.project_id)
    assert result is None

    proj = await project_row(db, w.project_id)  # строка на месте (мягкое удаление)
    assert proj.deleted_at == now
    batch = proj.deleted_batch_id
    assert batch is not None
    for tid in tree["live"]:
        row = await task_row(db, tid)
        assert (row.deleted_at, row.deleted_batch_id) == (now, batch)
    from tests.projects_support import comment_row

    for cid in tree["live_comments"]:
        row = await comment_row(db, cid)
        assert (row.deleted_at, row.deleted_batch_id) == (now, batch)
    # уже удалённые не перезаписываются
    for tid in tree["old_tasks"]:
        row = await task_row(db, tid)
        assert (row.deleted_at, row.deleted_batch_id) == (tree["early"], tree["old_batch"])
    for cid in tree["old_comments"]:
        row = await comment_row(db, cid)
        assert (row.deleted_at, row.deleted_batch_id) == (tree["early"], tree["old_batch"])
    # другой проект не тронут
    other = await project_row(db, tree["other"])
    assert other.deleted_at is None
    assert (await task_row(db, tree["t_other"])).deleted_at is None
    assert (await comment_row(db, tree["c_other"])).deleted_at is None
    assert await events(db, w.ws.id) == []  # D-55


@pytest.mark.parametrize("who", ["ba2", "usr", "ba3", "usr2", "ta", "norole"])
async def test_ac48_non_owner_cannot_delete(db: AsyncSession, svc: Any, who: str) -> None:
    w = await make_world(db)
    await forbidden(db, svc.delete_project(db, actor_of(getattr(w, who)), w.project_id))
    assert (await project_row(db, w.project_id)).deleted_at is None


async def test_fr16_delete_twice_is_404_and_project_disappears(
    db: AsyncSession, svc: Any, queries: Any
) -> None:
    w = await make_world(db)
    await svc.delete_project(db, actor_of(w.ba), w.project_id)
    await db.commit()
    await not_found(db, svc.delete_project(db, actor_of(w.ba), w.project_id))
    await not_found(db, queries.get_project(db, actor_of(w.ba), w.project_id))
    items, has_next = await queries.list_projects(db, actor_of(w.ba), PageParams())
    assert items == [] and has_next is False


async def test_fr16_delete_foreign_project_is_404(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    other = await make_workspace(db)
    sm_other = await make_user(db, workspace=other, role="mixed")
    await db.commit()
    await not_found(db, svc.delete_project(db, actor_of(sm_other), w.project_id))
    assert (await project_row(db, w.project_id)).deleted_at is None


async def test_d56_delete_takes_project_lock_first(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    with capture_sql(db) as seen:
        await svc.delete_project(db, actor_of(w.ba), w.project_id)
    assert any("for no key update" in s.lower() and "from project" in s.lower() for s in seen)


# --- list_projects ---------------------------------------------------------------------------


async def _list_world(db: AsyncSession) -> World:
    w = await make_world(db)  # проект «Основной», владелец ba, участники ba, ba2, usr
    ws_id = w.ws.id
    p_alpha = await make_project(db, workspace_id=ws_id, owner_id=w.ba2.id, name="alpha")
    p_beta = await make_project(db, workspace_id=ws_id, owner_id=w.ba.id, name="Beta")
    p_gamma = await make_project(db, workspace_id=ws_id, owner_id=w.sm.id, name="gamma")
    await make_project_member(
        db, project_id=p_beta.id, user_id=w.usr.id, workspace_id=ws_id, created_by=w.ba.id
    )
    # задачи: верхнего уровня, подзадача, удалённая — считается только неудалённая верхнего уровня
    t1 = await make_task(db, project_id=p_beta.id, workspace_id=ws_id, created_by=w.ba.id)
    await make_task(db, project_id=p_beta.id, workspace_id=ws_id, created_by=w.ba.id)
    await make_task(
        db, project_id=p_beta.id, workspace_id=ws_id, created_by=w.ba.id, parent_id=t1.id
    )
    await make_task(
        db,
        project_id=p_beta.id,
        workspace_id=ws_id,
        created_by=w.ba.id,
        deleted_at=t1_deleted(),
        deleted_batch_id=uuid.uuid4(),
    )
    deleted_p = await make_project(
        db,
        workspace_id=ws_id,
        owner_id=w.ba.id,
        name="aaa-deleted",
        deleted_at=t1_deleted(),
        deleted_batch_id=uuid.uuid4(),
    )
    await make_project_member(
        db, project_id=deleted_p.id, user_id=w.usr.id, workspace_id=ws_id, created_by=w.ba.id
    )
    other_ws = await make_workspace(db)
    other_owner = await make_user(db, workspace=other_ws, role="business_admin")
    await make_project(db, workspace_id=other_ws.id, owner_id=other_owner.id, name="Чужой")
    await db.commit()
    w.alpha, w.beta, w.gamma = p_alpha.id, p_beta.id, p_gamma.id  # type: ignore[attr-defined]
    return w


def t1_deleted() -> Any:
    from datetime import UTC, datetime

    return datetime(2026, 10, 1, tzinfo=UTC)


async def test_ac55_ba_and_sm_see_all_undeleted_projects_ordered_by_lower_name(
    db: AsyncSession, queries: Any
) -> None:
    w = await _list_world(db)
    for who in (w.ba3, w.sm, w.ba):  # ba3 не участвует ни в одном
        items, has_next = await queries.list_projects(db, actor_of(who), PageParams())
        assert has_next is False
        assert [i.name for i in items] == ["alpha", "Beta", "gamma", "Основной"]
        assert items[1].task_count == 2
        assert items[1].owner.id == w.ba.id
        assert items[1].owner.login == w.ba.login
        assert items[0].owner.id == w.ba2.id
        assert items[0].task_count == 0


async def test_ac55_user_sees_only_projects_where_member(db: AsyncSession, queries: Any) -> None:
    w = await _list_world(db)
    items, _ = await queries.list_projects(db, actor_of(w.usr), PageParams())
    assert [i.name for i in items] == ["Beta", "Основной"]
    items, _ = await queries.list_projects(db, actor_of(w.usr2), PageParams())
    assert items == []


async def test_ac55_list_has_no_content_fields(db: AsyncSession, queries: Any) -> None:
    w = await _list_world(db)
    items, _ = await queries.list_projects(db, actor_of(w.ba), PageParams())
    for item in items:
        assert not hasattr(item, "tasks")
        assert not hasattr(item, "comments")


async def test_ac22_list_projects_ties_broken_by_id_and_paginated(
    db: AsyncSession, queries: Any
) -> None:
    ws = await make_workspace(db)
    owner = await make_user(db, workspace=ws, role="business_admin")
    ids = []
    for name in ("Same", "same", "SAME"):
        ids.append((await make_project(db, workspace_id=ws.id, owner_id=owner.id, name=name)).id)
    for i in range(3):
        await make_project(db, workspace_id=ws.id, owner_id=owner.id, name=f"zz{i}")
    await db.commit()
    actor = actor_of(owner)
    page1, n1 = await queries.list_projects(db, actor, PageParams(page=1, page_size=4))
    page2, n2 = await queries.list_projects(db, actor, PageParams(page=2, page_size=4))
    assert (len(page1), n1, len(page2), n2) == (4, True, 2, False)
    assert [i.id for i in page1[:3]] == sorted(ids)  # одинаковый lower(name) -> по id
    assert [i.name for i in page1[3:] + page2] == ["zz0", "zz1", "zz2"]


# --- get_project -----------------------------------------------------------------------------


async def test_d45_get_project_by_ba_sm_member_user(db: AsyncSession, queries: Any) -> None:
    w = await _list_world(db)
    for who in (w.ba, w.sm, w.ba3, w.usr):
        view = await queries.get_project(db, actor_of(who), w.beta)  # type: ignore[attr-defined]
        assert view.id == w.beta  # type: ignore[attr-defined]
        assert view.name == "Beta"
        assert view.owner.id == w.ba.id
        assert view.task_count == 2


@pytest.mark.parametrize("who", ["usr2", "ta", "norole"])
async def test_d45_get_project_forbidden_for_non_member_user_ta_norole(
    db: AsyncSession, queries: Any, who: str
) -> None:
    w = await make_world(db)
    await forbidden(db, queries.get_project(db, actor_of(getattr(w, who)), w.project_id))


async def test_d45_get_project_foreign_workspace_is_404(db: AsyncSession, queries: Any) -> None:
    w = await make_world(db)
    other = await make_workspace(db)
    other_ba = await make_user(db, workspace=other, role="business_admin")
    await db.commit()
    await not_found(db, queries.get_project(db, actor_of(other_ba), w.project_id))
    await not_found(db, queries.get_project(db, actor_of(w.ba), uuid.uuid4()))


@pytest.mark.parametrize(
    ("who", "is_member", "manage", "manage_members", "create_task", "remove_self"),
    [
        ("ba", True, True, True, True, False),
        ("ba2", True, False, False, True, True),
        ("usr", True, False, False, True, True),
        ("sm", False, True, True, False, False),
        ("ba3", False, False, False, False, False),
    ],
)
async def test_p11_4_get_project_permissions_from_policy(
    db: AsyncSession,
    queries: Any,
    who: str,
    is_member: bool,
    manage: bool,
    manage_members: bool,
    create_task: bool,
    remove_self: bool,
) -> None:
    w = await make_world(db)
    view = await queries.get_project(db, actor_of(getattr(w, who)), w.project_id)
    assert view.is_member is is_member
    perms = view.permissions
    assert perms.manage is manage
    assert perms.manage_members is manage_members
    assert perms.create_task is create_task
    assert perms.remove_self is remove_self


async def test_p11_4_get_project_fields(db: AsyncSession, queries: Any) -> None:
    w = await make_world(db)
    view = await queries.get_project(db, actor_of(w.ba), w.project_id)
    row = await project_row(db, w.project_id)
    assert view.description == row.description
    assert view.created_at == row.created_at
    assert view.updated_at == row.updated_at
    assert view.task_count == 0


async def test_d56_task_count_excludes_deleted_and_subtasks(
    db: AsyncSession, queries: Any, fixed_clock: FixedClock
) -> None:
    w = await make_world(db)
    ws_id = w.ws.id
    t = await make_task(db, project_id=w.project_id, workspace_id=ws_id, created_by=w.ba.id)
    await make_task(
        db, project_id=w.project_id, workspace_id=ws_id, created_by=w.ba.id, parent_id=t.id
    )
    await make_task(
        db,
        project_id=w.project_id,
        workspace_id=ws_id,
        created_by=w.ba.id,
        deleted_at=fixed_clock.now(),
        deleted_batch_id=uuid.uuid4(),
    )
    await db.commit()
    assert (await queries.get_project(db, actor_of(w.ba), w.project_id)).task_count == 1


# --- гонки: удаление проекта и изменение состава (D-56, §10.2 п.1) -----------------------------


@pytest.mark.committed
async def test_p10_2_delete_project_waits_for_concurrent_member_change(
    committed: async_sessionmaker[AsyncSession], svc: Any
) -> None:
    import app.domain.projects.members as members

    async with committed() as setup:
        w = await make_world(setup)
    holder = committed()
    try:
        await members.add_member(holder, actor_of(w.ba), w.project_id, w.usr2.id)  # без commit

        async def delete() -> None:
            async with committed() as s:
                await svc.delete_project(s, actor_of(w.ba), w.project_id)
                await s.commit()

        task = asyncio.ensure_future(delete())
        done, _ = await asyncio.wait({task}, timeout=0.5)
        assert not done, "удаление проекта не дождалось блокировки проекта (§10.2 п.1)"
        await holder.commit()
    finally:
        await holder.close()
    await asyncio.wait_for(task, timeout=10)
    async with committed() as s:
        assert w.usr2.id in await member_ids(s, w.project_id)
        assert (await project_row(s, w.project_id)).deleted_at is not None


@pytest.mark.committed
async def test_p10_2_add_member_after_concurrent_delete_is_404(
    committed: async_sessionmaker[AsyncSession], svc: Any
) -> None:
    import app.domain.projects.members as members
    from app.core.errors import NotFound

    async with committed() as setup:
        w = await make_world(setup)
    holder = committed()
    try:
        await svc.delete_project(holder, actor_of(w.ba), w.project_id)  # без commit

        async def add() -> None:
            async with committed() as s:
                try:
                    await members.add_member(s, actor_of(w.ba), w.project_id, w.usr2.id)
                finally:
                    await s.rollback()

        task = asyncio.ensure_future(add())
        done, _ = await asyncio.wait({task}, timeout=0.5)
        assert not done, "add_member не ждёт блокировку проекта"
        await holder.commit()
    finally:
        await holder.close()
    with pytest.raises(NotFound):
        await asyncio.wait_for(task, timeout=10)
    async with committed() as s:
        assert w.usr2.id not in await member_ids(s, w.project_id)


@pytest.mark.committed
async def test_p10_2_transfer_ownership_serializes_with_member_removal(
    committed: async_sessionmaker[AsyncSession], svc: Any
) -> None:
    """Исключение нового владельца параллельно с передачей ему владения не оставляет
    проект с владельцем-неучастником: либо передача, либо исключение (422)."""
    import app.domain.projects.members as members
    from app.core.errors import AppError

    async with committed() as setup:
        w = await make_world(setup)
    go = asyncio.Event()

    async def run(coro_factory: Any) -> str:
        async with committed() as s:
            await go.wait()
            try:
                await coro_factory(s)
                await s.commit()
            except AppError as exc:
                await s.rollback()
                return str(exc.code)
            return "ok"

    jobs = [
        asyncio.ensure_future(
            run(
                lambda s: svc.transfer_ownership(
                    s, actor_of(w.ba), w.project_id, new_owner_id=w.ba2.id
                )
            )
        ),
        asyncio.ensure_future(
            run(lambda s: members.remove_member(s, actor_of(w.sm), w.project_id, w.ba2.id))
        ),
    ]
    await asyncio.sleep(0)
    go.set()
    results = await asyncio.gather(*jobs)
    async with committed() as s:
        row = await project_row(s, w.project_id)
        assert row.owner_id in await member_ids(s, w.project_id)  # владелец — участник
    # serial A: передача -> исключение = [ok, owner_cannot_be_removed];
    # serial B: исключение -> передача = [ok, not_project_member]
    assert sorted(results) in (
        ["ok", "owner_cannot_be_removed"],
        ["not_project_member", "ok"],
    ), results
