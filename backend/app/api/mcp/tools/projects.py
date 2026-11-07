"""Инструменты проектов для MCP: список и карточка (ADR-0018, PN-10). Изменения — вне R1."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.mcp.registry import ToolSpec
from app.api.mcp.tools.base import make_tool
from app.api.v1.schemas.projects import ProjectDetail, ProjectListItem
from app.core.pagination import Page, PageParams
from app.domain.access.roles import Actor, Capability
from app.domain.projects import queries


class ProjectIdArgs(BaseModel):
    project_id: UUID


async def _list(db: AsyncSession, actor: Actor, args: PageParams) -> dict[str, Any]:
    rows, has_next = await queries.list_projects(db, actor, args)
    page = Page[ProjectListItem](
        items=[ProjectListItem.model_validate(row) for row in rows],
        page=args.page,
        page_size=args.page_size,
        has_next=has_next,
    )
    return page.model_dump(mode="json")


async def _get(db: AsyncSession, actor: Actor, args: ProjectIdArgs) -> dict[str, Any]:
    view = await queries.get_project(db, actor, args.project_id)
    return ProjectDetail.model_validate(view).model_dump(mode="json")


def project_tools() -> list[ToolSpec]:
    return [
        make_tool(
            "list_projects",
            "Проекты: БА видит все, пользователь — где он участник.",
            PageParams,
            Capability.BUSINESS_ACCESS,
            _list,
        ),
        make_tool(
            "get_project",
            "Карточка проекта; для неучастника — отказ.",
            ProjectIdArgs,
            Capability.BUSINESS_ACCESS,
            _get,
        ),
    ]
