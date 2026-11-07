"""M20-T04: имя клиента агента в журнале и ленте проекта (ADR-0018, PN-6, FR-7, AC-8)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select

from app.core.pagination import PageParams
from app.domain.access.roles import Actor, Role
from app.domain.activity import service as activity
from app.domain.events import client_context
from app.domain.events.catalog import EventAction
from app.domain.events.client_context import client_name_scope, current_client_name
from app.domain.events.models import DomainEvent
from app.domain.events.writer import record_event
from tests.factories import make_project, make_project_member, make_user, make_workspace

SESSION_ID = b"\x00" * 32


async def _project_with_owner(db: Any) -> tuple[Actor, uuid.UUID, uuid.UUID]:
    ws = await make_workspace(db)
    owner = await make_user(db, workspace=ws, role=Role.BUSINESS_ADMIN.value)
    project = await make_project(db, workspace_id=ws.id, owner_id=owner.id, name="P")
    await make_project_member(
        db, project_id=project.id, user_id=owner.id, workspace_id=ws.id, created_by=owner.id
    )
    actor = Actor(
        user_id=owner.id,
        workspace_id=ws.id,
        login=owner.login,
        role=Role.BUSINESS_ADMIN,
        must_change_password=False,
        session_id=SESSION_ID,
    )
    return actor, ws.id, project.id


async def _record_project_update(db: Any, actor: Actor, project_id: uuid.UUID) -> None:
    await record_event(
        db,
        workspace_id=actor.workspace_id,
        actor_id=actor.user_id,
        action=EventAction.PROJECT_UPDATED,
        entity_id=project_id,
        project_id=project_id,
        changed_fields=["name"],
    )


@pytest.mark.parametrize("bad", ["", "x" * 65, "bad\tname"])
def test_m20_client_name_check_rejects_bad_values(bad: str) -> None:
    with pytest.raises(ValueError):
        client_context.check_client_name(bad)
    with pytest.raises(ValueError), client_name_scope(bad):
        pass


def test_m20_client_name_scope_sets_and_restores() -> None:
    assert current_client_name() is None
    with client_name_scope("Claude Code"):
        assert current_client_name() == "Claude Code"
        with client_name_scope("Codex CLI"):
            assert current_client_name() == "Codex CLI"
        assert current_client_name() == "Claude Code"
    assert current_client_name() is None


async def test_m20_event_written_inside_scope_has_client_name(db: Any) -> None:
    actor, ws_id, project_id = await _project_with_owner(db)
    with client_name_scope("Claude Code на ноутбуке"):
        await _record_project_update(db, actor, project_id)
    await _record_project_update(db, actor, project_id)

    names = (
        (
            await db.execute(
                select(DomainEvent.client_name)
                .where(DomainEvent.workspace_id == ws_id)
                .order_by(DomainEvent.id)
            )
        )
        .scalars()
        .all()
    )
    assert names == ["Claude Code на ноутбуке", None]


async def test_m20_ac8_project_feed_shows_client_name(db: Any) -> None:
    actor, _ws_id, project_id = await _project_with_owner(db)
    with client_name_scope("Cursor"):
        await _record_project_update(db, actor, project_id)
    await _record_project_update(db, actor, project_id)

    rows, _has_next = await activity.project_feed(db, actor, project_id, PageParams())
    assert [row.via_client for row in rows] == [None, "Cursor"]
