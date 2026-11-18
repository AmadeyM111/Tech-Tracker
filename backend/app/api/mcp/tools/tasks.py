"""Инструменты задач и подзадач для MCP (ADR-0018, PN-10, PN-11).

Аргументы и ответы — схемы REST (``app.api.v1.schemas.tasks``), маппинг полей — те же функции
(``create_data``/``patch_data``), поэтому правила ввода совпадают с веб-интерфейсом. Права
проверяют доменные сервисы; гейт ``BUSINESS_ACCESS`` — в реестре (PN-11).
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field
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
from app.core.clock import today_msk
from app.core.errors import ErrorCode, Unprocessable
from app.core.pagination import Page, PageParams
from app.domain.access.roles import Actor, Capability
from app.domain.comments import service as comments
from app.domain.tasks import queries, service
from app.domain.tasks.entity_draft import EntityDraft, parse_entities


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


class ProposeEntitiesArgs(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    commit: bool = False
    project_id: UUID | None = None


class EntityDraftOut(BaseModel):
    type: Literal["task", "incident", "note"]
    title: str
    project_id: UUID | None = None
    existing_task_id: UUID | None = None


class CommittedEntity(BaseModel):
    type: Literal["task", "incident", "note"]
    task_id: UUID | None = None
    comment_id: UUID | None = None


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


def _dump_draft(item: EntityDraft) -> dict[str, Any]:
    return EntityDraftOut(
        type=item.type,
        title=item.title,
        project_id=item.project_id,
        existing_task_id=item.existing_task_id,
    ).model_dump(mode="json")


def _project_of(item: EntityDraft, default: UUID | None) -> UUID:
    pid = item.project_id or default
    if pid is None:
        raise Unprocessable("Нужен project_id", code=ErrorCode.entity_parse_error)
    return pid


async def _commit_one(
    db: AsyncSession, actor: Actor, item: EntityDraft, default_project: UUID | None
) -> dict[str, Any]:
    if item.type == "note" and item.existing_task_id is not None:
        view = await comments.create_comment(db, actor, item.existing_task_id, item.title)
        return CommittedEntity(
            type="note", task_id=item.existing_task_id, comment_id=view.id
        ).model_dump(mode="json")
    data = service.TaskCreateData(
        title=item.title,
        description=item.title,
        due_date=today_msk(),
    )
    task_id = await service.create_task(db, actor, _project_of(item, default_project), data)
    comment_id = None
    if item.type == "incident":
        comment = await comments.create_comment(db, actor, task_id, "блокер")
        comment_id = comment.id
    return CommittedEntity(type=item.type, task_id=task_id, comment_id=comment_id).model_dump(
        mode="json"
    )


async def _propose(db: AsyncSession, actor: Actor, args: ProposeEntitiesArgs) -> dict[str, Any]:
    drafts = parse_entities(args.text)
    dumped = [_dump_draft(item) for item in drafts]
    if not args.commit:
        return {"drafts": dumped, "committed": []}
    for item in drafts:
        if item.type == "note" and item.existing_task_id is not None:
            continue
        _project_of(item, args.project_id)
    committed = [await _commit_one(db, actor, item, args.project_id) for item in drafts]
    return {"drafts": dumped, "committed": committed}


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
            write=True,
        ),
        make_tool(
            "create_subtask",
            "Создать подзадачу у задачи верхнего уровня.",
            CreateSubtaskArgs,
            BA,
            _create_sub,
            write=True,
        ),
        make_tool(
            "update_task",
            "Изменить поля задачи; передавайте только меняемые поля.",
            UpdateTaskArgs,
            BA,
            _update,
            write=True,
        ),
        make_tool(
            "propose_entities",
            "Черновик сущностей из текста. Без commit записей нет.",
            ProposeEntitiesArgs,
            BA,
            _propose,
            write=True,
        ),
    ]
