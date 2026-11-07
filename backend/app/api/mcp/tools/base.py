"""Общая сборка инструмента MCP: аргументы — pydantic-модель, схема для клиента — её JSON Schema."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.mcp.registry import ToolSpec
from app.domain.access.roles import Actor, Capability


def make_tool[ArgsT: BaseModel](
    name: str,
    description: str,
    args: type[ArgsT],
    capability: Capability,
    run: Callable[[AsyncSession, Actor, ArgsT], Awaitable[Any]],
) -> ToolSpec:
    async def handler(db: AsyncSession, actor: Actor, raw: dict[str, Any]) -> Any:
        return await run(db, actor, args.model_validate(raw))

    return ToolSpec(
        name=name,
        description=description,
        input_schema=args.model_json_schema(),
        capability=capability,
        handler=handler,
    )
