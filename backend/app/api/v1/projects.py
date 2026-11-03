"""Проекты и участники: ``/api/v1/projects*`` (plan §11.4, FR-14…FR-17, FR-45a, D-45, D-52).

Гейт — router-level ``require_capability(BUSINESS_ACCESS)``: ТА и «без роли» получают 403 для
любого id. ``POST /projects`` дополнительно требует ``PROJECT_CREATE`` («Пользователь» — 403).
Объектные права и порядок 404 -> 403 -> 422 проверяет сервис ``app.domain.projects``;
обработчики вызывают его один раз на действие, транзакцию фиксирует ``DbSession``.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import get_active_actor, require_capability
from app.api.openapi import error_responses
from app.api.v1.schemas.activity import (
    ActivityActor,
    ActivityChange,
    ActivityEntity,
    ActivityItem,
)
from app.api.v1.schemas.projects import (
    MemberAdd,
    OwnerChange,
    ProjectCreate,
    ProjectDetail,
    ProjectListItem,
    ProjectMember,
    ProjectPatch,
)
from app.core.db import DbSession
from app.core.pagination import Page, PageParams
from app.domain.access.roles import Actor, Capability
from app.domain.activity import service as activity
from app.domain.projects import members, queries, service

router = APIRouter(
    prefix="/projects",
    tags=["projects"],
    dependencies=[Depends(require_capability(Capability.BUSINESS_ACCESS))],
    responses=error_responses(401, 403),
)

CurrentActor = Annotated[Actor, Depends(get_active_actor)]


@router.get("", response_model=Page[ProjectListItem], responses=error_responses(422))
async def list_projects(
    db: DbSession, actor: CurrentActor, params: Annotated[PageParams, Query()]
) -> Page[ProjectListItem]:
    """БА — все проекты пространства, «Пользователь» — где участник; по названию."""
    rows, has_next = await queries.list_projects(db, actor, params)
    return Page[ProjectListItem](
        items=[ProjectListItem.model_validate(row) for row in rows],
        page=params.page,
        page_size=params.page_size,
        has_next=has_next,
    )


@router.post(
    "",
    status_code=201,
    response_model=ProjectDetail,
    dependencies=[Depends(require_capability(Capability.PROJECT_CREATE))],
    responses=error_responses(400, 422),
)
async def create_project(body: ProjectCreate, db: DbSession, actor: CurrentActor) -> ProjectDetail:
    """Создаёт проект; создатель — владелец и участник (FR-14)."""
    view = await service.create_project(db, actor, name=body.name, description=body.description)
    return ProjectDetail.model_validate(view)


@router.get("/{project_id}", response_model=ProjectDetail, responses=error_responses(404, 422))
async def get_project(project_id: UUID, db: DbSession, actor: CurrentActor) -> ProjectDetail:
    """Карточка проекта; «Пользователь»-неучастник — 403 (D-45)."""
    return ProjectDetail.model_validate(await queries.get_project(db, actor, project_id))


@router.patch(
    "/{project_id}", response_model=ProjectDetail, responses=error_responses(400, 404, 422)
)
async def update_project(
    project_id: UUID, body: ProjectPatch, db: DbSession, actor: CurrentActor
) -> ProjectDetail:
    """Меняет название и/или описание; без реальных изменений ничего не пишет (D-46)."""
    view = await service.update_project(
        db,
        actor,
        project_id,
        changes=service.ProjectPatch(
            name=body.name if "name" in body.model_fields_set else None,
            description=body.description if "description" in body.model_fields_set else None,
        ),
    )
    return ProjectDetail.model_validate(view)


@router.put(
    "/{project_id}/owner", response_model=ProjectDetail, responses=error_responses(400, 404, 422)
)
async def change_owner(
    project_id: UUID, body: OwnerChange, db: DbSession, actor: CurrentActor
) -> ProjectDetail:
    """Передаёт владение участнику-БА (FR-14a); пишет событие аудита."""
    view = await service.transfer_ownership(db, actor, project_id, new_owner_id=body.user_id)
    return ProjectDetail.model_validate(view)


@router.delete(
    "/{project_id}",
    status_code=204,
    response_class=Response,
    responses=error_responses(404, 422),
)
async def delete_project(project_id: UUID, db: DbSession, actor: CurrentActor) -> Response:
    """Мягко удаляет проект с задачами и комментариями (D-56)."""
    await service.delete_project(db, actor, project_id)
    return Response(status_code=204)


@router.get(
    "/{project_id}/members",
    response_model=Page[ProjectMember],
    responses=error_responses(404, 422),
)
async def list_members(
    project_id: UUID, db: DbSession, actor: CurrentActor, params: Annotated[PageParams, Query()]
) -> Page[ProjectMember]:
    """Участники проекта по логину; видны всем, кто видит проект (D-45)."""
    rows, has_next = await members.list_members(db, actor, project_id, params)
    return Page[ProjectMember](
        items=[ProjectMember.model_validate(row) for row in rows],
        page=params.page,
        page_size=params.page_size,
        has_next=has_next,
    )


@router.get(
    "/{project_id}/activity",
    response_model=Page[ActivityItem],
    responses=error_responses(403, 404, 422),
)
async def project_activity(
    project_id: UUID, db: DbSession, actor: CurrentActor, params: Annotated[PageParams, Query()]
) -> Page[ActivityItem]:
    """Лента проекта, новые первыми; только участникам (FR-38, ADR-0015)."""
    rows, has_next = await activity.project_feed(db, actor, project_id, params)
    return Page[ActivityItem](
        items=[_activity_item(row) for row in rows],
        page=params.page,
        page_size=params.page_size,
        has_next=has_next,
    )


def _activity_item(row: activity.FeedRow) -> ActivityItem:
    actor = row.actor
    return ActivityItem(
        id=row.id,
        occurred_at=row.occurred_at,
        actor=ActivityActor(
            kind="user" if actor is not None else "system",
            id=None if actor is None else actor.id,
            login=None if actor is None else actor.login,
        ),
        action=row.action,
        entity=ActivityEntity(
            type=row.entity.type,
            id=row.entity.id,
            deleted=row.entity.deleted,
            title=row.entity.title,
        ),
        changed_fields=row.changed_fields,
        changes=None if row.changes is None else [ActivityChange(**c) for c in row.changes],
    )


@router.post(
    "/{project_id}/members",
    status_code=204,
    response_class=Response,
    responses=error_responses(400, 404, 422),
)
async def add_member(
    project_id: UUID, body: MemberAdd, db: DbSession, actor: CurrentActor
) -> Response:
    """Добавляет участника; уже участник — 204 без изменений (D-46)."""
    await members.add_member(db, actor, project_id, body.user_id)
    return Response(status_code=204)


@router.delete(
    "/{project_id}/members/{user_id}",
    status_code=204,
    response_class=Response,
    responses=error_responses(404, 422),
)
async def remove_member(
    project_id: UUID, user_id: UUID, db: DbSession, actor: CurrentActor
) -> Response:
    """Исключает участника или даёт выйти самому; владельца исключить нельзя (FR-15a)."""
    await members.remove_member(db, actor, project_id, user_id)
    return Response(status_code=204)
