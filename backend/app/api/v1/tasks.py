"""Задачи и подзадачи: ``/api/v1/projects/{id}/tasks``, ``/me/tasks``, ``/tasks*`` (plan §11.4).

Гейт — router-level ``require_capability(BUSINESS_ACCESS)``: ТА и «без роли» получают 403.
Порядок ошибок: гейты -> 422 схемы -> 404 -> 403 -> 422 домена; объектные права проверяет
домен ``app.domain.tasks``. Ответ изменяющих маршрутов — карточка, перечитанная в той же
транзакции; транзакцию фиксирует ``DbSession``. Маршрут переноса по доске — T78.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import get_active_actor, require_capability
from app.api.openapi import error_responses
from app.api.v1.schemas.tasks import (
    TaskCreate,
    TaskDetail,
    TaskListItem,
    TaskListQuery,
    TaskUpdate,
)
from app.core.db import DbSession
from app.core.pagination import Page, PageParams
from app.domain.access.roles import Actor, Capability
from app.domain.tasks import queries, service

router = APIRouter(
    tags=["tasks"],
    dependencies=[Depends(require_capability(Capability.BUSINESS_ACCESS))],
    responses=error_responses(401, 403),
)

CurrentActor = Annotated[Actor, Depends(get_active_actor)]


def _page(
    items: list[queries.TaskListItem], has_next: bool, params: PageParams
) -> Page[TaskListItem]:
    return Page[TaskListItem](
        items=[TaskListItem.model_validate(item) for item in items],
        page=params.page,
        page_size=params.page_size,
        has_next=has_next,
    )


def _create_data(body: TaskCreate) -> service.TaskCreateData:
    """«Исполнитель не передан» и «передан null» различаются по ``model_fields_set``."""
    return service.TaskCreateData(
        title=body.title,
        description=body.description,
        assignee=body.assignee_id if "assignee_id" in body.model_fields_set else service.UNSET,
        due_date=body.due_date,
        priority=body.priority,
    )


def _patch_data(body: TaskUpdate) -> service.TaskPatch:
    """Не переданное поле — ``UNSET``; ``null`` у ``assignee_id``/``due_date`` снимает значение."""
    given = body.model_fields_set

    def pick[T](name: str, value: T) -> T | service.Unset:
        return value if name in given else service.UNSET

    return service.TaskPatch(
        title=pick("title", body.title),
        description=pick("description", body.description),
        assignee_id=pick("assignee_id", body.assignee_id),
        due_date=pick("due_date", body.due_date),
        priority=pick("priority", body.priority),
        status=pick("status", body.status),
    )


@router.get(
    "/projects/{project_id}/tasks",
    response_model=Page[TaskListItem],
    responses=error_responses(404, 422),
)
async def list_project_tasks(
    project_id: UUID, db: DbSession, actor: CurrentActor, query: Annotated[TaskListQuery, Query()]
) -> Page[TaskListItem]:
    """Задачи и подзадачи проекта, новые сверху; фильтры исполнителя и статуса — через «И»."""
    items, has_next = await queries.list_project_tasks(
        db, actor, project_id, query, assignee_id=query.assignee_id, status=query.status
    )
    return _page(items, has_next, query)


@router.post(
    "/projects/{project_id}/tasks",
    status_code=201,
    response_model=TaskDetail,
    responses=error_responses(400, 404, 422),
)
async def create_task(
    project_id: UUID, body: TaskCreate, db: DbSession, actor: CurrentActor
) -> TaskDetail:
    """Создаёт задачу в конце колонки «К выполнению» (FR-18, FR-28a)."""
    task_id = await service.create_task(db, actor, project_id, _create_data(body))
    return TaskDetail.model_validate(await queries.get_task(db, actor, task_id))


@router.get("/me/tasks", response_model=Page[TaskListItem], responses=error_responses(422))
async def list_my_tasks(
    db: DbSession, actor: CurrentActor, params: Annotated[PageParams, Query()]
) -> Page[TaskListItem]:
    """Мои задачи и подзадачи (исполнитель — я), по сроку (FR-27)."""
    items, has_next = await queries.list_my_tasks(db, actor, params)
    return _page(items, has_next, params)


@router.get("/tasks/{task_id}", response_model=TaskDetail, responses=error_responses(404, 422))
async def get_task(task_id: UUID, db: DbSession, actor: CurrentActor) -> TaskDetail:
    """Карточка задачи с подзадачами, прогрессом и правами актора."""
    return TaskDetail.model_validate(await queries.get_task(db, actor, task_id))


@router.patch(
    "/tasks/{task_id}", response_model=TaskDetail, responses=error_responses(400, 404, 422)
)
async def update_task(
    task_id: UUID, body: TaskUpdate, db: DbSession, actor: CurrentActor
) -> TaskDetail:
    """Меняет переданные поля; права — по реально меняющимся (D-46), всё или ничего."""
    await service.update_task(db, actor, task_id, _patch_data(body))
    return TaskDetail.model_validate(await queries.get_task(db, actor, task_id))


@router.delete(
    "/tasks/{task_id}",
    status_code=204,
    response_class=Response,
    responses=error_responses(404, 422),
)
async def delete_task(task_id: UUID, db: DbSession, actor: CurrentActor) -> Response:
    """Мягко удаляет задачу с подзадачами и комментариями (D-56)."""
    await service.delete_task(db, actor, task_id)
    return Response(status_code=204)


@router.post(
    "/tasks/{task_id}/subtasks",
    status_code=201,
    response_model=TaskDetail,
    responses=error_responses(400, 404, 422),
)
async def create_subtask(
    task_id: UUID, body: TaskCreate, db: DbSession, actor: CurrentActor
) -> TaskDetail:
    """Создаёт подзадачу; родитель — задача верхнего уровня (FR-21)."""
    sub_id = await service.create_subtask(db, actor, task_id, _create_data(body))
    return TaskDetail.model_validate(await queries.get_task(db, actor, sub_id))
