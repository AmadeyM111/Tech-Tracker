"""Сервис проектов (plan §11.4, §11.5, §10.2; D-45, D-46, D-52, D-55, D-56).

Не вызывает ``commit()``: транзакцию запроса фиксирует ``get_db``. Порядок проверок: проект
(404) -> права (403) -> входные данные (422) -> получатель (422). Изменение проекта берёт
``FOR NO KEY UPDATE`` на его строке (§10.2 п.1) до любых записей. Событий ленты нет (D-55);
пишется только аудит ``project.ownership_transferred``. Время — ``utcnow()``, ``updated_at``
задаётся явно.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import select, update

from app.core.clock import utcnow
from app.core.errors import ErrorCode, Forbidden, Unprocessable
from app.domain.access.policy import can_manage_project
from app.domain.access.recipients import RecipientPurpose, check_recipient
from app.domain.access.roles import Actor, Capability
from app.domain.comments.models import Comment
from app.domain.events.catalog import EventAction
from app.domain.events.writer import FieldChange, record_event
from app.domain.projects.models import Project, ProjectMember
from app.domain.projects.queries import ProjectView, load_project_facts, project_view
from app.domain.tasks.models import Task
from app.domain.users.directory import load_recipient, user_refs

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

NAME_MAX = 255
DESCRIPTION_MAX = 10_000


@dataclass(frozen=True)
class ProjectPatch:
    """``None`` — поле не передано."""

    name: str | None = None
    description: str | None = None


def _validate_name(name: str) -> None:
    """Название: 1..255 символов, не из одних пробельных (D-52); хранится как введено."""
    if not name.strip() or len(name) > NAME_MAX:
        raise Unprocessable(
            "Название проекта: от 1 до 255 символов, не только пробелы",
            code=ErrorCode.validation_error,
        )


def _validate_description(description: str) -> None:
    if len(description) > DESCRIPTION_MAX:
        raise Unprocessable(
            "Описание проекта: не более 10000 символов", code=ErrorCode.validation_error
        )


async def create_project(
    db: AsyncSession, actor: Actor, *, name: str, description: str = ""
) -> ProjectView:
    if not actor.can(Capability.PROJECT_CREATE):
        raise Forbidden()
    _validate_name(name)
    _validate_description(description)
    project = Project(
        workspace_id=actor.workspace_id,
        name=name,
        description=description,
        owner_id=actor.user_id,
        created_by=actor.user_id,
    )
    db.add(project)
    await db.flush()
    db.add(
        ProjectMember(
            project_id=project.id,
            user_id=actor.user_id,
            workspace_id=actor.workspace_id,
            created_by=actor.user_id,
        )
    )
    await db.flush()
    facts = await load_project_facts(db, actor, project.id)
    return await project_view(db, actor, facts)


async def update_project(
    db: AsyncSession, actor: Actor, project_id: UUID, *, changes: ProjectPatch
) -> ProjectView:
    facts = await load_project_facts(db, actor, project_id, lock="update")
    if not can_manage_project(actor, facts):
        raise Forbidden()
    if changes.name is not None:
        _validate_name(changes.name)
    if changes.description is not None:
        _validate_description(changes.description)
    current = (
        await db.execute(select(Project.name, Project.description).where(Project.id == project_id))
    ).one()
    values: dict[str, str] = {}
    if changes.name is not None and changes.name != current.name:
        values["name"] = changes.name
    if changes.description is not None and changes.description != current.description:
        values["description"] = changes.description
    if values:  # без изменений ничего не пишем, updated_at не трогаем (D-46)
        await db.execute(
            update(Project).where(Project.id == project_id).values(**values, updated_at=utcnow())
        )
    return await project_view(db, actor, facts)


async def transfer_ownership(
    db: AsyncSession, actor: Actor, project_id: UUID, *, new_owner_id: UUID
) -> ProjectView:
    facts = await load_project_facts(db, actor, project_id, lock="update")
    if not can_manage_project(actor, facts):
        raise Forbidden()
    recipient = await load_recipient(db, actor.workspace_id, new_owner_id, lock=True)
    member_rows = await db.scalars(
        select(ProjectMember.user_id).where(ProjectMember.project_id == project_id)
    )
    # владелец всегда участник, даже без строки членства (ревью T70)
    members = frozenset(member_rows) | {facts.owner_id}
    check_recipient(recipient, RecipientPurpose.PROJECT_OWNER, project_member_ids=members)
    if new_owner_id == facts.owner_id:
        return await project_view(db, actor, facts)
    await db.execute(
        update(Project)
        .where(Project.id == project_id)
        .values(owner_id=new_owner_id, updated_at=utcnow())
    )
    refs = await user_refs(db, actor.workspace_id, [facts.owner_id, new_owner_id])
    old, new = refs[facts.owner_id], refs[new_owner_id]
    change: FieldChange = {
        "field": "owner_id",
        "old": {"id": str(old.id), "login": old.login},
        "new": {"id": str(new.id), "login": new.login},
    }
    await record_event(
        db,
        workspace_id=actor.workspace_id,
        actor_id=actor.user_id,
        action=EventAction.PROJECT_OWNERSHIP_TRANSFERRED,
        entity_id=project_id,
        project_id=project_id,
        changed_fields=["owner_id"],
        changes=[change],
    )
    return await project_view(db, actor, await load_project_facts(db, actor, project_id))


async def delete_project(db: AsyncSession, actor: Actor, project_id: UUID) -> None:
    """Мягкое удаление с каскадом D-56: одно ``deleted_at``/``deleted_batch_id`` на пакет."""
    facts = await load_project_facts(db, actor, project_id, lock="update")
    if not can_manage_project(actor, facts):
        raise Forbidden()
    now = utcnow()
    stamp = {"deleted_at": now, "deleted_batch_id": uuid4()}
    live_tasks = select(Task.id).where(Task.project_id == project_id, Task.deleted_at.is_(None))
    # комментарии — раньше задач: выборка живых задач проекта ещё не пуста
    await db.execute(
        update(Comment)
        .where(Comment.task_id.in_(live_tasks), Comment.deleted_at.is_(None))
        .values(**stamp)
    )
    await db.execute(
        update(Task).where(Task.project_id == project_id, Task.deleted_at.is_(None)).values(**stamp)
    )
    await db.execute(
        update(Project).where(Project.id == project_id).values(**stamp, updated_at=now)
    )
