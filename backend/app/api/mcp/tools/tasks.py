"""Инструменты задач и подзадач для MCP (ADR-0018, PN-10, PN-11).

Аргументы и ответы — схемы REST (``app.api.v1.schemas.tasks``), маппинг полей — те же функции
(``create_data``/``patch_data``), поэтому правила ввода совпадают с веб-интерфейсом. Права
проверяют доменные сервисы; гейт ``BUSINESS_ACCESS`` — в реестре (PN-11).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.mcp.registry import ToolSpec
from app.api.mcp.tools.base import make_tool
from app.api.v1.schemas.tasks import (
    TaskCreate,
    TaskDetail,
    TaskListItem,
    TaskListQuery,
    TaskUpdate,
)
from app.api.v1.tasks import create_data, patch_data
from app.core.pagination import Page, PageParams
from app.domain.access.roles import Actor, Capability
from app.domain.tasks import queries, service


class TaskIdArgs(BaseModel):
    task_id: UUID


class ListMyTasksArgs(PageParams):
    pass


class ListProjectTasksArgs(TaskListQuery):
    project_id: UUID


class CreateTaskArgs(TaskCreate):
    project_id: UUID


class CreateSubtaskArgs(TaskCreate):
    task_id: UUID


class UpdateTaskArgs(TaskUpdate):
    task_id: UUID


def _page(items: list[queries.TaskListItem], has_next: bool, params: PageParams) -> dict[str, Any]:
    page = Page[TaskListItem](
        items=[TaskListItem.model_validate(item) for item in items],
        page=params.page,
        page_size=params.page_size,
        has_next=has_next,
    )
    return page.model_dump(mode="json")


async def _detail(db: AsyncSession, actor: Actor, task_id: UUID) -> dict[str, Any]:
    return TaskDetail.model_validate(await queries.get_task(db, actor, task_id)).model_dump(
        mode="json"
    )


async def _list_my(db: AsyncSession, actor: Actor, args: ListMyTasksArgs) -> dict[str, Any]:
    items, has_next = await queries.list_my_tasks(db, actor, args)
    return _page(items, has_next, args)


async def _list_project(
    db: AsyncSession, actor: Actor, args: ListProjectTasksArgs
) -> dict[str, Any]:
    items, has_next = await queries.list_project_tasks(
        db, actor, args.project_id, args, assignee_id=args.assignee_id, status=args.status
    )
    return _page(items, has_next, args)


async def _get(db: AsyncSession, actor: Actor, args: TaskIdArgs) -> dict[str, Any]:
    return await _detail(db, actor, args.task_id)


async def _create(db: AsyncSession, actor: Actor, args: CreateTaskArgs) -> dict[str, Any]:
    task_id = await service.create_task(db, actor, args.project_id, create_data(args))
    return await _detail(db, actor, task_id)


async def _create_sub(db: AsyncSession, actor: Actor, args: CreateSubtaskArgs) -> dict[str, Any]:
    sub_id = await service.create_subtask(db, actor, args.task_id, create_data(args))
    return await _detail(db, actor, sub_id)


async def _update(db: AsyncSession, actor: Actor, args: UpdateTaskArgs) -> dict[str, Any]:
    await service.update_task(db, actor, args.task_id, patch_data(args))
    return await _detail(db, actor, args.task_id)


BA = Capability.BUSINESS_ACCESS


def task_tools() -> list[ToolSpec]:
    return [
        make_tool(
            "list_my_tasks",
            "Мои задачи и подзадачи (я исполнитель), по сроку.",
            ListMyTasksArgs,
            BA,
            _list_my,
        ),
        make_tool(
            "list_project_tasks",
            "Задачи и подзадачи проекта; фильтры по исполнителю и статусу.",
            ListProjectTasksArgs,
            BA,
            _list_project,
        ),
        make_tool("get_task", "Карточка задачи с подзадачами и правами.", TaskIdArgs, BA, _get),
        make_tool(
            "create_task",
            "Создать задачу в проекте. Исполнителя другому может назначить только БА.",
            CreateTaskArgs,
            BA,
            _create,
        ),
        make_tool(
            "create_subtask",
            "Создать подзадачу у задачи верхнего уровня.",
            CreateSubtaskArgs,
            BA,
            _create_sub,
        ),
        make_tool(
            "update_task",
            "Изменить поля задачи; передавайте только меняемые поля.",
            UpdateTaskArgs,
            BA,
            _update,
        ),
    ]
