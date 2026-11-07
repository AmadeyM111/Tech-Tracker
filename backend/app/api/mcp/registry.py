"""Реестр инструментов MCP (ADR-0018, PN-10, PN-11).

Инструмент объявляет возможность (``Capability``), которую требует его сервис. ``tools/list``
показывает только инструменты, доступные роли владельца токена (FR-6); вызов недоступного —
ошибка ``forbidden`` (FR-5). Проверки объектных прав остаются в доменных сервисах.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.access.roles import ROLE_CAPABILITIES, Actor, Capability, Role

ToolHandler = Callable[[AsyncSession, Actor, dict[str, Any]], Awaitable[Any]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    capability: Capability
    handler: ToolHandler


class ToolRegistry:
    def __init__(self, tools: Iterable[ToolSpec] = ()) -> None:
        self._tools: dict[str, ToolSpec] = {}
        for spec in tools:
            self.add(spec)

    def add(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"инструмент {spec.name!r} уже зарегистрирован")  # Fail Fast
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def allowed(self, role: Role | None, spec: ToolSpec) -> bool:
        return role is not None and spec.capability in ROLE_CAPABILITIES[role]

    def visible_for(self, role: Role | None) -> list[ToolSpec]:
        return [spec for spec in self._tools.values() if self.allowed(role, spec)]
