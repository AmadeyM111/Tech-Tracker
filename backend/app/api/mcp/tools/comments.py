"""Инструменты комментариев для MCP: список и добавление (ADR-0018, PN-10)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.mcp.registry import ToolSpec
from app.api.mcp.tools.base import make_tool
from app.api.v1.schemas.comments import Comment, CommentCreate
from app.core.pagination import Page, PageParams
from app.domain.access.roles import Actor, Capability
from app.domain.comments import service


class ListCommentsArgs(PageParams):
    task_id: UUID


class AddCommentArgs(CommentCreate):
    task_id: UUID


async def _list(db: AsyncSession, actor: Actor, args: ListCommentsArgs) -> dict[str, Any]:
    views, has_next = await service.list_comments(db, actor, args.task_id, args)
    page = Page[Comment](
        items=[Comment.model_validate(view) for view in views],
        page=args.page,
        page_size=args.page_size,
        has_next=has_next,
    )
    return page.model_dump(mode="json")


async def _add(db: AsyncSession, actor: Actor, args: AddCommentArgs) -> dict[str, Any]:
    view = await service.create_comment(db, actor, args.task_id, args.body)
    return Comment.model_validate(view).model_dump(mode="json")


def comment_tools() -> list[ToolSpec]:
    return [
        make_tool(
            "list_comments",
            "Комментарии задачи по времени создания.",
            ListCommentsArgs,
            Capability.BUSINESS_ACCESS,
            _list,
        ),
        make_tool(
            "add_comment",
            "Добавить комментарий к задаче (участник проекта).",
            AddCommentArgs,
            Capability.BUSINESS_ACCESS,
            _add,
        ),
    ]
