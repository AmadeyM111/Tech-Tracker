"""MCP ingest_message и list_stuck_work (спека 034, ADR-0030)."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.mcp.registry import ToolSpec
from app.api.mcp.tools.base import make_tool
from app.core.pagination import Page, PageParams
from app.domain.access.roles import Actor, Capability
from app.domain.inbox import service as inbox
from app.domain.inbox.service import IngestResult


class IngestMessageArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    source: Literal["telegram"]
    external_id: str = Field(min_length=1, max_length=256)
    text: str = Field(min_length=1, max_length=10_000)
    task_id: UUID | None = None
    url: str | None = Field(default=None, max_length=2048)

    @field_validator("external_id")
    @classmethod
    def _external_id(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("Текст не может содержать нулевой символ")
        return value

    @field_validator("url")
    @classmethod
    def _url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class StuckItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    title: str
    status: str
    last_activity_at: Any
    due_date: Any
    overdue: bool
    blocked: bool | None
    open_dod: bool | None


class ListStuckArgs(PageParams):
    pass


def _ingest_dump(result: IngestResult) -> dict[str, Any]:
    return {
        "task_id": str(result.task_id),
        "comment_id": None if result.comment_id is None else str(result.comment_id),
        "source": result.source,
        "external_id": result.external_id,
        "url": result.url,
    }


async def _ingest(db: AsyncSession, actor: Actor, args: IngestMessageArgs) -> dict[str, Any]:
    result = await inbox.ingest_message(
        db,
        actor,
        project_id=args.project_id,
        source=args.source,
        external_id=args.external_id,
        text=args.text,
        task_id=args.task_id,
        url=args.url,
    )
    return _ingest_dump(result)


async def _stuck(db: AsyncSession, actor: Actor, args: ListStuckArgs) -> dict[str, Any]:
    items, has_next = await inbox.list_stuck_work(db, actor, args)
    page = Page[StuckItemOut](
        items=[StuckItemOut.model_validate(item) for item in items],
        page=args.page,
        page_size=args.page_size,
        has_next=has_next,
    )
    return page.model_dump(mode="json")


BA = Capability.BUSINESS_ACCESS


def inbox_tools() -> list[ToolSpec]:
    return [
        make_tool(
            "ingest_message",
            "Сообщение из Telegram: новая задача или комментарий. Повтор source+external_id "
            "не создаёт дубликат.",
            IngestMessageArgs,
            BA,
            _ingest,
            write=True,
        ),
        make_tool(
            "list_stuck_work",
            "Задачи в моих проектах без движения 48 часов, не done. Просрочка — поле overdue.",
            ListStuckArgs,
            BA,
            _stuck,
        ),
    ]
