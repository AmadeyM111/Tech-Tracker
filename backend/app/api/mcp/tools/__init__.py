"""Инструменты MCP по доменам (M20-T08). Пока пустой реестр: инструменты добавляются задачей T08."""

from app.api.mcp.registry import ToolRegistry


def default_registry() -> ToolRegistry:
    return ToolRegistry()
