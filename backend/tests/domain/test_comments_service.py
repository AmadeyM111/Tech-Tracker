"""T79: комментарии, сервис (plan D-28, D-55, D-56, D-60, §10.2 п.2, §11.4, §11.5).

AC-58, AC-103 (комментарии), FR-23 (без упоминаний, SC-6), SC-11.

Ожидаемый интерфейс ``app.domain.comments.service`` (``async``, ``commit()`` не вызывают)::

    create_comment(db, actor, task_id, body: str) -> CommentView
    edit_comment(db, actor, comment_id, body: str) -> CommentView
    delete_comment(db, actor, comment_id) -> None
    list_comments(db, actor, task_id, params: PageParams) -> tuple[list[CommentView], bool]
        # (items, has_next), как list_project_tasks

    CommentView: id, task_id, author: UserRef, body: str | None, is_deleted: bool,
                 created_at, edited_at: datetime | None, permissions (.edit, .delete)

Порядок: контекст/комментарий (404, раньше 403) -> участие и права (403) -> очистка и
проверка пустоты (422 ``validation_error``) -> запись. create/edit/delete берут FOR SHARE на
строке проекта (§10.2 п.2). Автор может править только свой (``can_edit_comment``) и только
оставаясь участником; удалять — ``can_delete_comment`` (автор, БА-владелец, СМ-участник).
Мягкое удаление: ``deleted_at`` и собственный ``deleted_batch_id``. События и упоминания не
пишутся (D-55, SC-6). Возвращаемое значение проверяется только в части ``id`` и в ``list``.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from app.core.pagination import PageParams
from tests.factories import make_comment, make_project, make_user, make_workspace
from tests.projects_support import (
    World,
    actor_of,
    add_member_row,
    capture_sql,
    comment_row,
    events,
    fails,
    forbidden,
    make_world,
    not_found,
    task_row,
)
from tests.tasks_support import mk_task

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
def svc() -> Any:
    import app.domain.comments.service as module

    return module


def _p(page: int = 1, size: int = 50) -> PageParams:
    return PageParams(page=page, page_size=size)


async def _comment(
    db: AsyncSession, w: World, task_id: uuid.UUID, author: Any, **kw: Any
) -> uuid.UUID:
    row = await make_comment(db, task_id=task_id, workspace_id=w.ws.id, created_by=author.id, **kw)
    await db.commit()
    return row.id


async def _setup(db: AsyncSession) -> tuple[World, uuid.UUID]:
    w = await make_world(db)
    tid = await mk_task(db, w, assignee_id=w.usr.id)
    return w, tid


async def _body(db: AsyncSession, cid: uuid.UUID) -> str:
    return str((await comment_row(db, cid)).body)


async def _count_comments(db: AsyncSession, task_id: uuid.UUID) -> int:
    await db.flush()
    r = await db.execute(
        text("SELECT count(*) FROM comment WHERE task_id = :t").bindparams(t=task_id)
    )
    return int(r.scalar_one())


# --- create_comment: успех ---------------------------------------------------------------------


@pytest.mark.parametrize("who", ["ba", "ba2", "usr"])
async def test_fr23_create_members_can_comment(db: AsyncSession, svc: Any, who: str) -> None:
    w, tid = await _setup(db)
    user = getattr(w, who)
    view = await svc.create_comment(db, actor_of(user), tid, "Первый комментарий")
    r = await comment_row(db, view.id)
    assert r.task_id == tid
    assert r.workspace_id == w.ws.id
    assert r.created_by == user.id
    assert r.body == "Первый комментарий"
    assert r.edited_at is None
    assert r.deleted_at is None
    assert r.deleted_batch_id is None


async def test_fr23_create_returns_view_of_stored_comment(
    db: AsyncSession, svc: Any, fixed_clock: Any
) -> None:
    w, tid = await _setup(db)
    view = await svc.create_comment(db, actor_of(w.usr), tid, "Текст")
    assert view.task_id == tid
    assert view.author.id == w.usr.id
    assert view.author.login == w.usr.login
    assert view.body == "Текст"
    assert view.is_deleted is False
    assert view.edited_at is None
    assert view.created_at == fixed_clock.now()
    assert view.permissions.edit is True
    assert view.permissions.delete is True


async def test_fr23_create_on_subtask_comments_subtask_only(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    sub = await mk_task(db, w, parent_id=tid, assignee_id=w.usr.id)
    view = await svc.create_comment(db, actor_of(w.usr), sub, "К подзадаче")
    assert (await comment_row(db, view.id)).task_id == sub
    assert await _count_comments(db, tid) == 0


async def test_ac103_sm_member_without_own_tasks_can_comment(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    await add_member_row(db, w, w.project_id, w.sm)
    await db.commit()
    view = await svc.create_comment(db, actor_of(w.sm), tid, "СМ пишет")
    assert (await comment_row(db, view.id)).created_by == w.sm.id


# --- create_comment: 404 -> 403 -> 422 -------------------------------------------------------


async def test_fr23_create_unknown_task_404(db: AsyncSession, svc: Any) -> None:
    w, _ = await _setup(db)
    await not_found(db, svc.create_comment(db, actor_of(w.ba), uuid.uuid4(), "x"))


async def test_fr23_create_deleted_task_404(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    tid = await mk_task(
        db, w, deleted_at=datetime(2026, 1, 1, tzinfo=UTC), deleted_batch_id=uuid.uuid4()
    )
    await not_found(db, svc.create_comment(db, actor_of(w.ba), tid, "x"))


async def test_fr23_create_task_of_deleted_project_404(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    await db.execute(
        text(
            "UPDATE project SET deleted_at = now(), deleted_batch_id = :b WHERE id = :p"
        ).bindparams(b=uuid.uuid4(), p=w.project_id)
    )
    await db.commit()
    await not_found(db, svc.create_comment(db, actor_of(w.ba), tid, "x"))


async def test_fr23_create_task_of_other_workspace_404(db: AsyncSession, svc: Any) -> None:
    w, _ = await _setup(db)
    ws2 = await make_workspace(db)
    owner2 = await make_user(db, workspace=ws2, role="business_admin", login="o2.ba")
    p2 = await make_project(db, workspace_id=ws2.id, owner_id=owner2.id, name="Чужой")
    from tests.factories import make_project_member, make_task

    await make_project_member(
        db, project_id=p2.id, user_id=owner2.id, workspace_id=ws2.id, created_by=owner2.id
    )
    t2 = await make_task(db, project_id=p2.id, workspace_id=ws2.id, created_by=owner2.id)
    await db.commit()
    await not_found(db, svc.create_comment(db, actor_of(w.ba), t2.id, "x"))
    assert await _count_comments(db, t2.id) == 0


@pytest.mark.parametrize("who", ["ta", "sm", "ba3", "usr2", "norole", "blocked"])
async def test_ac103_create_non_member_403(db: AsyncSession, svc: Any, who: str) -> None:
    w, tid = await _setup(db)
    await forbidden(db, svc.create_comment(db, actor_of(getattr(w, who)), tid, "x"))
    assert await _count_comments(db, tid) == 0


async def test_ac103_sm_non_member_403_then_member_ok(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    await forbidden(db, svc.create_comment(db, actor_of(w.sm), tid, "x"))
    await add_member_row(db, w, w.project_id, w.sm)
    await db.commit()
    await svc.create_comment(db, actor_of(w.sm), tid, "x")
    assert await _count_comments(db, tid) == 1


async def test_fr23_create_order_404_before_403_before_422(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    # 404 раньше 403 и 422 (пустое тело, не участник)
    await not_found(db, svc.create_comment(db, actor_of(w.usr2), uuid.uuid4(), ""))
    # 403 раньше 422
    await forbidden(db, svc.create_comment(db, actor_of(w.usr2), tid, ""))
    # участник — 422
    await fails(db, svc.create_comment(db, actor_of(w.usr), tid, ""), "validation_error")


@pytest.mark.parametrize(
    "body",
    ["", " ", "   \n\t  ", "<b></b>", "<script>alert(1)</script>", "<!-- c -->", " <br/> \n"],
)
async def test_ac58_create_empty_after_sanitize_422(db: AsyncSession, svc: Any, body: str) -> None:
    w, tid = await _setup(db)
    await fails(db, svc.create_comment(db, actor_of(w.usr), tid, body), "validation_error")
    assert await _count_comments(db, tid) == 0


# --- create_comment: очистка -------------------------------------------------------------------


async def test_ac58_create_stores_without_html(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    view = await svc.create_comment(
        db, actor_of(w.usr), tid, "Привет <b>мир</b><script>alert(1)</script>!<!-- x -->"
    )
    assert await _body(db, view.id) == "Привет мир!"
    assert view.body == "Привет мир!"


async def test_sc11_create_keeps_markdown_and_entities_as_typed(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    raw = "> цитата\n**жирный** a < b &lt;i&gt;"
    view = await svc.create_comment(db, actor_of(w.usr), tid, raw)
    assert await _body(db, view.id) == raw


async def test_ac58_create_ten_thousand_chars_stored(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    raw = "д" * 10_000
    view = await svc.create_comment(db, actor_of(w.usr), tid, raw)
    assert await _body(db, view.id) == raw


async def test_fr23_create_nul_422(db: AsyncSession, svc: Any) -> None:
    """NUL не хранится в PostgreSQL text: 422 validation_error, не 500."""
    w, tid = await _setup(db)
    await fails(db, svc.create_comment(db, actor_of(w.usr), tid, "a\x00b"), "validation_error")
    assert await _count_comments(db, tid) == 0


async def test_ac58_create_over_ten_thousand_chars_422(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    await fails(db, svc.create_comment(db, actor_of(w.usr), tid, "д" * 10_001), "validation_error")
    assert await _count_comments(db, tid) == 0


async def test_ac58_edit_over_ten_thousand_chars_422(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    cid = await _comment(db, w, tid, w.usr, body="было")
    await fails(db, svc.edit_comment(db, actor_of(w.usr), cid, "д" * 10_001), "validation_error")
    assert await _body(db, cid) == "было"


AMPERSAND_TEXTS = ["AT&T", "R&D", "Q&A", "x &y", "http://h/?a=1&b", "&x", "&", "a &", "x&", "&&"]


@pytest.mark.parametrize("raw", AMPERSAND_TEXTS)
async def test_sc11_create_keeps_ampersand_as_typed(db: AsyncSession, svc: Any, raw: str) -> None:
    w, tid = await _setup(db)
    view = await svc.create_comment(db, actor_of(w.usr), tid, raw)
    assert await _body(db, view.id) == raw
    assert view.body == raw


@pytest.mark.parametrize("raw", AMPERSAND_TEXTS)
async def test_sc11_edit_keeps_ampersand_as_typed(db: AsyncSession, svc: Any, raw: str) -> None:
    w, tid = await _setup(db)
    cid = await _comment(db, w, tid, w.usr)
    await svc.edit_comment(db, actor_of(w.usr), cid, raw)
    assert await _body(db, cid) == raw


# --- create_comment: блокировка, события -----------------------------------------------------


async def test_p10_2_create_edit_delete_lock_project_share(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    with capture_sql(db) as seen:
        view = await svc.create_comment(db, actor_of(w.usr), tid, "x")
    assert any("for share" in s.lower() and "from project" in s.lower() for s in seen), seen
    with capture_sql(db) as seen2:
        await svc.edit_comment(db, actor_of(w.usr), view.id, "y")
    assert any("for share" in s.lower() and "from project" in s.lower() for s in seen2), seen2
    with capture_sql(db) as seen3:
        await svc.delete_comment(db, actor_of(w.usr), view.id)
    assert any("for share" in s.lower() and "from project" in s.lower() for s in seen3), seen3


async def test_d55_no_events_and_no_mentions_written(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    before = len(await events(db, w.ws.id))
    view = await svc.create_comment(
        db, actor_of(w.usr), tid, f"привет @{w.ba.login} и @{w.usr.login}"
    )
    await svc.edit_comment(db, actor_of(w.usr), view.id, f"правка @{w.ba2.login}")
    await svc.delete_comment(db, actor_of(w.ba), view.id)
    assert len(await events(db, w.ws.id)) == before
    # упоминание остаётся обычным текстом (SC-6)
    assert await _body(db, view.id) == f"правка @{w.ba2.login}"
    tables = await db.execute(text("SELECT to_regclass('public.mention')"))
    if tables.scalar_one() is not None:
        n = await db.execute(text("SELECT count(*) FROM mention"))
        assert n.scalar_one() == 0


# --- edit_comment ------------------------------------------------------------------------------


async def test_ac58_edit_by_author_sets_body_and_edited_at(
    db: AsyncSession, svc: Any, fixed_clock: Any
) -> None:
    w, tid = await _setup(db)
    cid = await _comment(db, w, tid, w.usr, body="старый")
    created = (await comment_row(db, cid)).created_at
    fixed_clock.advance(timedelta(minutes=7))
    view = await svc.edit_comment(db, actor_of(w.usr), cid, "новый")
    r = await comment_row(db, cid)
    assert r.body == "новый"
    assert r.edited_at == fixed_clock.now()
    assert r.created_at == created
    assert r.created_by == w.usr.id
    assert r.deleted_at is None
    assert view.id == cid
    assert view.body == "новый"
    assert view.edited_at == fixed_clock.now()


async def test_ac58_edit_sanitizes_html(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    cid = await _comment(db, w, tid, w.usr)
    await svc.edit_comment(db, actor_of(w.usr), cid, "<i>курсив</i><style>x{}</style> &amp;")
    assert await _body(db, cid) == "курсив &amp;"


async def test_ac58_edit_second_time_moves_edited_at(
    db: AsyncSession, svc: Any, fixed_clock: Any
) -> None:
    w, tid = await _setup(db)
    cid = await _comment(db, w, tid, w.usr)
    await svc.edit_comment(db, actor_of(w.usr), cid, "раз")
    first = (await comment_row(db, cid)).edited_at
    fixed_clock.advance(timedelta(minutes=3))
    await svc.edit_comment(db, actor_of(w.usr), cid, "два")
    second = (await comment_row(db, cid)).edited_at
    assert first is not None
    assert second == first + timedelta(minutes=3)


@pytest.mark.parametrize("editor", ["ba", "ba2"])
async def test_ac58_edit_foreign_comment_403_even_for_ba(
    db: AsyncSession, svc: Any, editor: str
) -> None:
    """Править может только автор (can_edit_comment); БА-владелец только удаляет."""
    w, tid = await _setup(db)
    cid = await _comment(db, w, tid, w.usr, body="чужой")
    await forbidden(db, svc.edit_comment(db, actor_of(getattr(w, editor)), cid, "взлом"))
    r = await comment_row(db, cid)
    assert (r.body, r.edited_at) == ("чужой", None)


async def test_ac58_edit_foreign_by_user_403(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    cid = await _comment(db, w, tid, w.ba, body="от БА")
    await forbidden(db, svc.edit_comment(db, actor_of(w.usr), cid, "правка"))
    assert await _body(db, cid) == "от БА"


async def test_ac103_edit_foreign_by_sm_member_403(db: AsyncSession, svc: Any) -> None:
    """СМ удаляет любые комментарии, но править может только свои."""
    w, tid = await _setup(db)
    await add_member_row(db, w, w.project_id, w.sm)
    await db.commit()
    cid = await _comment(db, w, tid, w.usr, body="чужой")
    await forbidden(db, svc.edit_comment(db, actor_of(w.sm), cid, "правка"))
    assert await _body(db, cid) == "чужой"


async def test_fr23_edit_author_no_longer_member_403(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    cid = await _comment(db, w, tid, w.usr, body="было")
    await db.execute(
        text("DELETE FROM project_member WHERE project_id = :p AND user_id = :u").bindparams(
            p=w.project_id, u=w.usr.id
        )
    )
    await db.commit()
    await forbidden(db, svc.edit_comment(db, actor_of(w.usr), cid, "стало"))
    assert await _body(db, cid) == "было"


async def test_fr23_edit_sm_author_non_member_403(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    cid = await _comment(db, w, tid, w.sm, body="было")
    await forbidden(db, svc.edit_comment(db, actor_of(w.sm), cid, "стало"))


async def test_fr23_edit_unknown_comment_404(db: AsyncSession, svc: Any) -> None:
    w, _ = await _setup(db)
    await not_found(db, svc.edit_comment(db, actor_of(w.usr), uuid.uuid4(), "x"))


async def test_fr23_edit_deleted_comment_404(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    cid = await _comment(
        db,
        w,
        tid,
        w.usr,
        deleted_at=datetime(2026, 1, 1, tzinfo=UTC),
        deleted_batch_id=uuid.uuid4(),
    )
    await not_found(db, svc.edit_comment(db, actor_of(w.usr), cid, "x"))


async def test_fr23_edit_comment_of_deleted_task_404(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    tid = await mk_task(
        db, w, deleted_at=datetime(2026, 1, 1, tzinfo=UTC), deleted_batch_id=uuid.uuid4()
    )
    cid = await _comment(db, w, tid, w.usr)
    await not_found(db, svc.edit_comment(db, actor_of(w.usr), cid, "x"))


async def test_fr23_edit_comment_of_deleted_project_404(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    cid = await _comment(db, w, tid, w.usr)
    await db.execute(
        text(
            "UPDATE project SET deleted_at = now(), deleted_batch_id = :b WHERE id = :p"
        ).bindparams(b=uuid.uuid4(), p=w.project_id)
    )
    await db.commit()
    await not_found(db, svc.edit_comment(db, actor_of(w.usr), cid, "x"))


async def test_fr23_edit_other_workspace_404(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    cid = await _comment(db, w, tid, w.usr)
    ws2 = await make_workspace(db)
    stranger = await make_user(db, workspace=ws2, role="business_admin", login="x.ba")
    await db.commit()
    await not_found(db, svc.edit_comment(db, actor_of(stranger), cid, "x"))
    assert await _body(db, cid) == "Комментарий"


async def test_fr23_edit_order_404_403_422(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    cid = await _comment(db, w, tid, w.usr, body="было")
    await not_found(db, svc.edit_comment(db, actor_of(w.ba), uuid.uuid4(), ""))
    await forbidden(db, svc.edit_comment(db, actor_of(w.ba), cid, ""))
    await fails(db, svc.edit_comment(db, actor_of(w.usr), cid, ""), "validation_error")


@pytest.mark.parametrize("body", ["", "  \n ", "<b></b>", "<script>x</script>"])
async def test_ac58_edit_empty_after_sanitize_422_unchanged(
    db: AsyncSession, svc: Any, body: str
) -> None:
    w, tid = await _setup(db)
    cid = await _comment(db, w, tid, w.usr, body="было")
    await fails(db, svc.edit_comment(db, actor_of(w.usr), cid, body), "validation_error")
    r = await comment_row(db, cid)
    assert (r.body, r.edited_at) == ("было", None)


# --- delete_comment ----------------------------------------------------------------------------


async def test_ac58_author_deletes_own_soft_with_batch(
    db: AsyncSession, svc: Any, fixed_clock: Any
) -> None:
    w, tid = await _setup(db)
    cid = await _comment(db, w, tid, w.usr)
    other = await _comment(db, w, tid, w.ba)
    await svc.delete_comment(db, actor_of(w.usr), cid)
    r = await comment_row(db, cid)  # строка сохранена (мягкое удаление)
    assert r.deleted_at == fixed_clock.now()
    assert r.deleted_batch_id is not None
    assert (await comment_row(db, other)).deleted_at is None
    assert (await task_row(db, tid)).deleted_at is None


async def test_ac58_each_delete_gets_own_batch(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    c1 = await _comment(db, w, tid, w.usr)
    c2 = await _comment(db, w, tid, w.usr)
    await svc.delete_comment(db, actor_of(w.usr), c1)
    await svc.delete_comment(db, actor_of(w.usr), c2)
    b1 = (await comment_row(db, c1)).deleted_batch_id
    b2 = (await comment_row(db, c2)).deleted_batch_id
    assert b1 is not None
    assert b2 is not None
    assert b1 != b2


async def test_ac58_ba_owner_deletes_foreign_comment(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    cid = await _comment(db, w, tid, w.usr)
    await svc.delete_comment(db, actor_of(w.ba), cid)
    assert (await comment_row(db, cid)).deleted_at is not None


async def test_ac58_ba_non_owner_member_cannot_delete_foreign_403(
    db: AsyncSession, svc: Any
) -> None:
    w, tid = await _setup(db)
    cid = await _comment(db, w, tid, w.usr)
    await forbidden(db, svc.delete_comment(db, actor_of(w.ba2), cid))
    assert (await comment_row(db, cid)).deleted_at is None


async def test_ac58_ba_non_owner_deletes_own(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    cid = await _comment(db, w, tid, w.ba2)
    await svc.delete_comment(db, actor_of(w.ba2), cid)
    assert (await comment_row(db, cid)).deleted_at is not None


async def test_ac58_user_cannot_delete_foreign_403(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    cid = await _comment(db, w, tid, w.ba)
    await forbidden(db, svc.delete_comment(db, actor_of(w.usr), cid))
    assert (await comment_row(db, cid)).deleted_at is None


async def test_ac103_sm_member_deletes_foreign_comment(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    cid = await _comment(db, w, tid, w.usr)
    await forbidden(db, svc.delete_comment(db, actor_of(w.sm), cid))  # не участник
    assert (await comment_row(db, cid)).deleted_at is None
    await add_member_row(db, w, w.project_id, w.sm)  # СМ добавляет себя (FR-8, OI-71)
    await db.commit()
    await svc.delete_comment(db, actor_of(w.sm), cid)
    assert (await comment_row(db, cid)).deleted_at is not None


@pytest.mark.parametrize("who", ["ta", "ba3", "usr2", "norole", "blocked"])
async def test_ac103_delete_non_member_403(db: AsyncSession, svc: Any, who: str) -> None:
    w, tid = await _setup(db)
    cid = await _comment(db, w, tid, w.usr)
    await forbidden(db, svc.delete_comment(db, actor_of(getattr(w, who)), cid))
    assert (await comment_row(db, cid)).deleted_at is None


async def test_fr23_delete_author_no_longer_member_403(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    cid = await _comment(db, w, tid, w.usr)
    await db.execute(
        text("DELETE FROM project_member WHERE project_id = :p AND user_id = :u").bindparams(
            p=w.project_id, u=w.usr.id
        )
    )
    await db.commit()
    await forbidden(db, svc.delete_comment(db, actor_of(w.usr), cid))
    assert (await comment_row(db, cid)).deleted_at is None


async def test_fr23_delete_unknown_404(db: AsyncSession, svc: Any) -> None:
    w, _ = await _setup(db)
    await not_found(db, svc.delete_comment(db, actor_of(w.ba), uuid.uuid4()))


async def test_fr23_delete_twice_second_404(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    cid = await _comment(db, w, tid, w.usr)
    await svc.delete_comment(db, actor_of(w.usr), cid)
    await db.commit()
    first = await comment_row(db, cid)
    await not_found(db, svc.delete_comment(db, actor_of(w.usr), cid))
    again = await comment_row(db, cid)
    assert (again.deleted_at, again.deleted_batch_id) == (first.deleted_at, first.deleted_batch_id)


async def test_fr23_delete_404_before_403_non_member_unknown(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    cid = await _comment(
        db,
        w,
        tid,
        w.usr,
        deleted_at=datetime(2026, 1, 1, tzinfo=UTC),
        deleted_batch_id=uuid.uuid4(),
    )
    await not_found(db, svc.delete_comment(db, actor_of(w.usr2), cid))


async def test_fr23_delete_comment_of_deleted_task_or_project_404(
    db: AsyncSession, svc: Any
) -> None:
    w = await make_world(db)
    dead = await mk_task(
        db, w, deleted_at=datetime(2026, 1, 1, tzinfo=UTC), deleted_batch_id=uuid.uuid4()
    )
    c_dead = await _comment(db, w, dead, w.usr)
    await not_found(db, svc.delete_comment(db, actor_of(w.ba), c_dead))
    live = await mk_task(db, w)
    c_live = await _comment(db, w, live, w.usr)
    await db.execute(
        text(
            "UPDATE project SET deleted_at = now(), deleted_batch_id = :b WHERE id = :p"
        ).bindparams(b=uuid.uuid4(), p=w.project_id)
    )
    await db.commit()
    await not_found(db, svc.delete_comment(db, actor_of(w.ba), c_live))


async def test_fr23_delete_other_workspace_404(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    cid = await _comment(db, w, tid, w.usr)
    ws2 = await make_workspace(db)
    stranger = await make_user(db, workspace=ws2, role="mixed", login="x.sm")
    await db.commit()
    await not_found(db, svc.delete_comment(db, actor_of(stranger), cid))
    assert (await comment_row(db, cid)).deleted_at is None


# --- list_comments -----------------------------------------------------------------------------


async def test_fr23_list_empty_task(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    items, has_next = await svc.list_comments(db, actor_of(w.usr), tid, _p())
    assert items == []
    assert has_next is False


@pytest.mark.parametrize("who", ["ba", "ba2", "usr"])
async def test_fr23_list_members_see_all_comments(db: AsyncSession, svc: Any, who: str) -> None:
    w, tid = await _setup(db)
    c1 = await _comment(db, w, tid, w.usr)
    c2 = await _comment(db, w, tid, w.ba)
    items, _ = await svc.list_comments(db, actor_of(getattr(w, who)), tid, _p())
    assert {i.id for i in items} == {c1, c2}


async def test_fr23_list_order_created_at_then_id(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    t0 = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
    late = await _comment(db, w, tid, w.usr, created_at=t0 + timedelta(hours=2))
    tie_a = await _comment(db, w, tid, w.ba, created_at=t0 + timedelta(hours=1))
    tie_b = await _comment(db, w, tid, w.usr, created_at=t0 + timedelta(hours=1))
    early = await _comment(db, w, tid, w.ba, created_at=t0)
    items, _ = await svc.list_comments(db, actor_of(w.usr), tid, _p())
    first_tie = sorted([tie_a, tie_b])
    assert [i.id for i in items] == [early, *first_tie, late]


async def test_fr47_list_paginates(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    t0 = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
    ids = [
        await _comment(db, w, tid, w.usr, created_at=t0 + timedelta(minutes=i)) for i in range(5)
    ]
    p1, n1 = await svc.list_comments(db, actor_of(w.usr), tid, _p(1, 2))
    p2, n2 = await svc.list_comments(db, actor_of(w.usr), tid, _p(2, 2))
    p3, n3 = await svc.list_comments(db, actor_of(w.usr), tid, _p(3, 2))
    assert [i.id for i in p1] == ids[0:2]
    assert n1 is True
    assert [i.id for i in p2] == ids[2:4]
    assert n2 is True
    assert [i.id for i in p3] == ids[4:5]
    assert n3 is False


async def test_ac58_list_deleted_is_stub_with_author_and_time(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    t0 = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
    alive = await _comment(db, w, tid, w.ba, body="живой", created_at=t0)
    gone = await _comment(
        db,
        w,
        tid,
        w.usr,
        body="секрет",
        created_at=t0 + timedelta(minutes=1),
        deleted_at=datetime(2026, 4, 1, tzinfo=UTC),
        deleted_batch_id=uuid.uuid4(),
    )
    items, _ = await svc.list_comments(db, actor_of(w.ba), tid, _p())
    by_id = {i.id: i for i in items}
    assert set(by_id) == {alive, gone}
    stub = by_id[gone]
    assert stub.body is None
    assert stub.is_deleted is True
    assert stub.author.id == w.usr.id
    assert stub.author.login == w.usr.login
    assert stub.created_at == t0 + timedelta(minutes=1)
    assert stub.task_id == tid
    live = by_id[alive]
    assert live.body == "живой"
    assert live.is_deleted is False
    assert live.author.id == w.ba.id


async def test_ac58_list_after_service_delete_shows_stub(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    view = await svc.create_comment(db, actor_of(w.usr), tid, "будет удалён")
    await svc.delete_comment(db, actor_of(w.ba), view.id)
    items, _ = await svc.list_comments(db, actor_of(w.usr), tid, _p())
    assert [(i.id, i.body, i.is_deleted, i.author.id) for i in items] == [
        (view.id, None, True, w.usr.id)
    ]


async def test_ac58_list_shows_edited_at(db: AsyncSession, svc: Any, fixed_clock: Any) -> None:
    w, tid = await _setup(db)
    view = await svc.create_comment(db, actor_of(w.usr), tid, "один")
    fixed_clock.advance(timedelta(minutes=1))
    await svc.edit_comment(db, actor_of(w.usr), view.id, "два")
    items, _ = await svc.list_comments(db, actor_of(w.usr), tid, _p())
    assert len(items) == 1
    assert items[0].body == "два"
    assert items[0].edited_at == fixed_clock.now()


async def test_fr23_list_only_this_task_comments(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    sub = await mk_task(db, w, parent_id=tid)
    other = await mk_task(db, w)
    mine = await _comment(db, w, tid, w.usr)
    await _comment(db, w, sub, w.usr)
    await _comment(db, w, other, w.usr)
    items, _ = await svc.list_comments(db, actor_of(w.usr), tid, _p())
    assert [i.id for i in items] == [mine]


@pytest.mark.parametrize("who", ["ta", "sm", "ba3", "usr2", "norole", "blocked"])
async def test_ac103_list_non_member_403(db: AsyncSession, svc: Any, who: str) -> None:
    w, tid = await _setup(db)
    await _comment(db, w, tid, w.usr)
    await forbidden(db, svc.list_comments(db, actor_of(getattr(w, who)), tid, _p()))


async def test_ac103_list_sm_member_ok(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    cid = await _comment(db, w, tid, w.usr)
    await add_member_row(db, w, w.project_id, w.sm)
    await db.commit()
    items, _ = await svc.list_comments(db, actor_of(w.sm), tid, _p())
    assert [i.id for i in items] == [cid]


async def test_fr23_list_404_cases(db: AsyncSession, svc: Any) -> None:
    w = await make_world(db)
    await not_found(db, svc.list_comments(db, actor_of(w.usr2), uuid.uuid4(), _p()))
    dead = await mk_task(
        db, w, deleted_at=datetime(2026, 1, 1, tzinfo=UTC), deleted_batch_id=uuid.uuid4()
    )
    await _comment(db, w, dead, w.usr)
    await not_found(db, svc.list_comments(db, actor_of(w.usr), dead, _p()))
    live = await mk_task(db, w)
    await db.execute(
        text(
            "UPDATE project SET deleted_at = now(), deleted_batch_id = :b WHERE id = :p"
        ).bindparams(b=uuid.uuid4(), p=w.project_id)
    )
    await db.commit()
    await not_found(db, svc.list_comments(db, actor_of(w.ba), live, _p()))


async def test_fr23_list_other_workspace_404(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    await _comment(db, w, tid, w.usr)
    ws2 = await make_workspace(db)
    stranger = await make_user(db, workspace=ws2, role="business_admin", login="y.ba")
    await db.commit()
    await not_found(db, svc.list_comments(db, actor_of(stranger), tid, _p()))


async def test_fr23_list_404_before_403(db: AsyncSession, svc: Any) -> None:
    w, _ = await _setup(db)
    await not_found(db, svc.list_comments(db, actor_of(w.ta), uuid.uuid4(), _p()))


# --- permissions {edit, delete} -------------------------------------------------------------


async def test_s11_5_list_permissions_per_actor(db: AsyncSession, svc: Any) -> None:
    w, tid = await _setup(db)
    await add_member_row(db, w, w.project_id, w.sm)
    await db.commit()
    t0 = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
    by_usr = await _comment(db, w, tid, w.usr, created_at=t0)
    by_ba = await _comment(db, w, tid, w.ba, created_at=t0 + timedelta(minutes=1))
    by_ba2 = await _comment(db, w, tid, w.ba2, created_at=t0 + timedelta(minutes=2))

    async def perms(who: Any) -> dict[uuid.UUID, tuple[bool, bool]]:
        items, _ = await svc.list_comments(db, actor_of(who), tid, _p())
        return {i.id: (i.permissions.edit, i.permissions.delete) for i in items}

    # «Пользователь»: только свой
    assert await perms(w.usr) == {
        by_usr: (True, True),
        by_ba: (False, False),
        by_ba2: (False, False),
    }
    # БА-владелец: правит только свои, удаляет любые
    assert await perms(w.ba) == {
        by_usr: (False, True),
        by_ba: (True, True),
        by_ba2: (False, True),
    }
    # БА-участник не владелец: только свой
    assert await perms(w.ba2) == {
        by_usr: (False, False),
        by_ba: (False, False),
        by_ba2: (True, True),
    }
    # СМ-участник: удаляет любые (AC-103), правит только свои (своих нет)
    assert await perms(w.sm) == {
        by_usr: (False, True),
        by_ba: (False, True),
        by_ba2: (False, True),
    }


async def test_s11_5_permissions_consistent_with_actions(db: AsyncSession, svc: Any) -> None:
    """Если permissions.delete == False — delete_comment отвечает 403, иначе проходит."""
    w, tid = await _setup(db)
    cid = await _comment(db, w, tid, w.ba)
    items, _ = await svc.list_comments(db, actor_of(w.usr), tid, _p())
    assert items[0].permissions.delete is False
    await forbidden(db, svc.delete_comment(db, actor_of(w.usr), cid))
    items, _ = await svc.list_comments(db, actor_of(w.ba), tid, _p())
    assert items[0].permissions.delete is True
    await svc.delete_comment(db, actor_of(w.ba), cid)


# --- интеграция с delete_task (D-56) --------------------------------------------------------


async def test_d56_delete_task_hides_comments_from_comment_service(
    db: AsyncSession, svc: Any
) -> None:
    import app.domain.tasks.service as tasks_svc

    w, tid = await _setup(db)
    sub = await mk_task(db, w, parent_id=tid, assignee_id=w.usr.id)
    c_task = (await svc.create_comment(db, actor_of(w.usr), tid, "к задаче")).id
    c_sub = (await svc.create_comment(db, actor_of(w.usr), sub, "к подзадаче")).id
    await db.commit()
    await tasks_svc.delete_task(db, actor_of(w.ba), tid)
    t = await task_row(db, tid)
    for cid in (c_task, c_sub):
        r = await comment_row(db, cid)
        assert r.deleted_at is not None
        assert r.deleted_batch_id == t.deleted_batch_id
    await db.commit()
    await not_found(db, svc.list_comments(db, actor_of(w.ba), tid, _p()))
    await not_found(db, svc.create_comment(db, actor_of(w.ba), tid, "x"))
    await not_found(db, svc.edit_comment(db, actor_of(w.usr), c_task, "x"))
    await not_found(db, svc.delete_comment(db, actor_of(w.ba), c_sub))


async def test_d56_comment_deleted_before_task_keeps_own_batch(db: AsyncSession, svc: Any) -> None:
    import app.domain.tasks.service as tasks_svc

    w, tid = await _setup(db)
    own = (await svc.create_comment(db, actor_of(w.usr), tid, "раньше")).id
    await svc.delete_comment(db, actor_of(w.usr), own)
    own_batch = (await comment_row(db, own)).deleted_batch_id
    await db.commit()
    await tasks_svc.delete_task(db, actor_of(w.ba), tid)
    assert (await comment_row(db, own)).deleted_batch_id == own_batch
    assert (await task_row(db, tid)).deleted_batch_id != own_batch


# --- гонка create_comment <-> delete_task (D-56, §10.2) ---------------------------------------


async def _live_comments_under_deleted_tasks(db: AsyncSession, project_id: uuid.UUID) -> int:
    r = await db.execute(
        text(
            "SELECT count(*) FROM comment c JOIN task t ON t.id = c.task_id "
            "WHERE t.project_id = :p AND t.deleted_at IS NOT NULL AND c.deleted_at IS NULL"
        ).bindparams(p=project_id)
    )
    return int(r.scalar_one())


@pytest.mark.committed
@pytest.mark.parametrize("target", ["task", "subtask"])
async def test_d56_create_waits_for_uncommitted_delete_task_no_orphan_comment(
    committed: async_sessionmaker[AsyncSession], svc: Any, target: str
) -> None:
    """delete_task держит транзакцию без commit; create_comment параллельно. После фиксации
    нет живого комментария под удалённой задачей (create ждёт и получает 404, либо каскад)."""
    import app.domain.tasks.service as tasks_svc
    from app.core.errors import NotFound

    async with committed() as setup:
        w = await make_world(setup)
        parent = await mk_task(setup, w)
        sub = await mk_task(setup, w, parent_id=parent)
    commented = parent if target == "task" else sub
    holder = committed()
    try:
        await tasks_svc.delete_task(holder, actor_of(w.ba), parent)  # без commit

        async def job() -> str:
            async with committed() as s:
                try:
                    await svc.create_comment(s, actor_of(w.ba), commented, "x")
                    await s.commit()
                except NotFound:
                    await s.rollback()
                    return "not_found"
                return "ok"

        task = asyncio.ensure_future(job())
        await asyncio.wait({task}, timeout=0.5)
        await holder.commit()
    finally:
        await holder.close()
    await asyncio.wait_for(task, timeout=10)
    async with committed() as s:
        assert await _live_comments_under_deleted_tasks(s, w.project_id) == 0


@pytest.mark.committed
async def test_d56_delete_task_waits_for_uncommitted_comment_and_cascades_it(
    committed: async_sessionmaker[AsyncSession], svc: Any
) -> None:
    """Обратный порядок: комментарий создан, не зафиксирован; delete_task ждёт и удаляет его."""
    import app.domain.tasks.service as tasks_svc

    async with committed() as setup:
        w = await make_world(setup)
        parent = await mk_task(setup, w)
        sub = await mk_task(setup, w, parent_id=parent)
    holder = committed()
    try:
        c1 = (await svc.create_comment(holder, actor_of(w.ba), parent, "a")).id  # без commit
        c2 = (await svc.create_comment(holder, actor_of(w.ba), sub, "b")).id

        async def job() -> None:
            async with committed() as s:
                await tasks_svc.delete_task(s, actor_of(w.ba), parent)
                await s.commit()

        task = asyncio.ensure_future(job())
        await asyncio.wait({task}, timeout=0.5)
        await holder.commit()
    finally:
        await holder.close()
    await asyncio.wait_for(task, timeout=10)
    async with committed() as s:
        for cid in (c1, c2):
            assert (await comment_row(s, cid)).deleted_at is not None
        assert await _live_comments_under_deleted_tasks(s, w.project_id) == 0


@pytest.mark.committed
async def test_d56_create_comment_vs_delete_task_race_leaves_no_orphans(
    committed: async_sessionmaker[AsyncSession], svc: Any
) -> None:
    import app.domain.tasks.service as tasks_svc
    from app.core.errors import AppError

    async with committed() as setup:
        w = await make_world(setup)
        parents = [await mk_task(setup, w) for _ in range(8)]
        subs = [await mk_task(setup, w, parent_id=p) for p in parents]
    go = asyncio.Event()

    async def run(factory: Any) -> None:
        async with committed() as s:
            await go.wait()
            try:
                await factory(s)
                await s.commit()
            except AppError:
                await s.rollback()

    jobs = []
    for p, sb in zip(parents, subs, strict=True):
        jobs.append(run(lambda s, p=p: tasks_svc.delete_task(s, actor_of(w.ba), p)))
        jobs.append(run(lambda s, p=p: svc.create_comment(s, actor_of(w.ba), p, "x")))
        jobs.append(run(lambda s, sb=sb: svc.create_comment(s, actor_of(w.ba), sb, "y")))
    futures = [asyncio.ensure_future(j) for j in jobs]
    await asyncio.sleep(0)
    go.set()
    await asyncio.wait_for(asyncio.gather(*futures), timeout=30)
    async with committed() as s:
        assert await _live_comments_under_deleted_tasks(s, w.project_id) == 0
