"""MCP-инструменты слоя знаний (спека 037, CD-08, CD-09)."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.mcp.registry import ToolSpec
from app.api.mcp.tools.base import make_tool
from app.core.pagination import Page, PageParams
from app.domain.access.roles import Actor, Capability
from app.domain.knowledge import service as knowledge

BA = Capability.BUSINESS_ACCESS


class ListKnowledgeArgs(PageParams):
    scope: Literal["space", "project"] | None = None
    project_id: UUID | None = None


class GetKnowledgeArgs(BaseModel):
    knowledge_id: UUID


class UpsertKnowledgeArgs(BaseModel):
    scope: str | None = None
    project_id: UUID | None = None
    type: str | None = None
    title: str | None = None
    body: str | None = None
    confirmed_with: str | None = None
    commit: bool = False
    knowledge_id: UUID | None = None


class KnowledgeItem(BaseModel):
    id: UUID
    scope: str
    project_id: UUID | None
    type: str
    title: str
    body: str
    confirmed_with: str | None
    confirmed_by: UUID
    client_name: str | None
    created_at: str


async def _list(db: AsyncSession, actor: Actor, args: ListKnowledgeArgs) -> dict[str, Any]:
    items, has_next = await knowledge.list_knowledge(
        db, actor, args, scope=args.scope, project_id=args.project_id
    )
    page = Page[KnowledgeItem](
        items=[KnowledgeItem.model_validate(knowledge.as_dict(item)) for item in items],
        page=args.page,
        page_size=args.page_size,
        has_next=has_next,
    )
    return page.model_dump(mode="json")


async def _get(db: AsyncSession, actor: Actor, args: GetKnowledgeArgs) -> dict[str, Any]:
    view = await knowledge.get_knowledge(db, actor, args.knowledge_id)
    return knowledge.as_dict(view)


async def _upsert(db: AsyncSession, actor: Actor, args: UpsertKnowledgeArgs) -> dict[str, Any]:
    return await knowledge.upsert_knowledge(
        db,
        actor,
        scope=args.scope,
        project_id=args.project_id,
        kind=args.type,
        title=args.title,
        body=args.body,
        confirmed_with=args.confirmed_with,
        commit=args.commit,
        knowledge_id=args.knowledge_id,
    )


def knowledge_tools() -> list[ToolSpec]:
    return [
        make_tool(
            "list_knowledge",
            "Записи знаний: слой пространства и свои проекты.",
            ListKnowledgeArgs,
            BA,
            _list,
        ),
        make_tool(
            "get_knowledge",
            "Одна запись знания по id.",
            GetKnowledgeArgs,
            BA,
            _get,
        ),
        make_tool(
            "upsert_knowledge",
            "Решение, причина или договорённость. Без commit записей нет.",
            UpsertKnowledgeArgs,
            BA,
            _upsert,
            write=True,
        ),
    ]
