"""Реестр инструментов MCP по доменам (ADR-0018, PN-10): задачи, проекты, комментарии."""

from app.api.mcp.registry import ToolRegistry
from app.api.mcp.tools.comments import comment_tools
from app.api.mcp.tools.projects import project_tools
from app.api.mcp.tools.tasks import task_tools


def default_registry() -> ToolRegistry:
    return ToolRegistry([*task_tools(), *project_tools(), *comment_tools()])
