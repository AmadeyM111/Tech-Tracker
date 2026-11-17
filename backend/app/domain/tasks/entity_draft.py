"""Разбор черновика сущностей из текста (спека 035, CD-06)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from app.core.errors import ErrorCode, Unprocessable
from app.domain.tasks.service import TITLE_MAX

EntityTypeName = Literal["task", "incident", "note"]
_TYPES = frozenset({"task", "incident", "note"})
_LINE = re.compile(
    r"^(task|incident|note)\s*:\s*(.+)$",
    re.IGNORECASE,
)
_UUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


@dataclass(frozen=True)
class EntityDraft:
    type: EntityTypeName
    title: str
    project_id: UUID | None
    existing_task_id: UUID | None


def _parse_error(detail: str) -> Unprocessable:
    return Unprocessable(detail, code=ErrorCode.entity_parse_error)


def _as_uuid(value: Any, field: str) -> UUID | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    if not _UUID.fullmatch(text):
        raise _parse_error(f"{field}: ожидался UUID")
    return UUID(text)


def _title(value: Any) -> str:
    if not isinstance(value, str):
        raise _parse_error("title: строка 1–255")
    title = value.strip()
    if not title or len(title) > TITLE_MAX:
        raise _parse_error("title: строка 1–255")
    return title


def _type_of(value: Any) -> EntityTypeName:
    if not isinstance(value, str) or value.strip().lower() not in _TYPES:
        raise _parse_error("type: task, incident или note")
    return value.strip().lower()  # type: ignore[return-value]


def _from_obj(raw: Any) -> EntityDraft:
    if not isinstance(raw, dict):
        raise _parse_error("элемент черновика — объект")
    return EntityDraft(
        type=_type_of(raw.get("type")),
        title=_title(raw.get("title")),
        project_id=_as_uuid(raw.get("project_id"), "project_id"),
        existing_task_id=_as_uuid(raw.get("existing_task_id"), "existing_task_id"),
    )


def _split_line_title(rest: str) -> tuple[str, UUID | None, UUID | None]:
    project_id: UUID | None = None
    existing: UUID | None = None
    title = rest
    if " | " in rest:
        title, extras = rest.split(" | ", 1)
        for part in extras.split("|"):
            piece = part.strip()
            if piece.startswith("project_id="):
                project_id = _as_uuid(piece[len("project_id=") :], "project_id")
            elif piece.startswith("existing_task_id="):
                existing = _as_uuid(piece[len("existing_task_id=") :], "existing_task_id")
            elif piece:
                raise _parse_error(f"неизвестное поле: {piece}")
    return title, project_id, existing


def parse_entities(text: str) -> list[EntityDraft]:
    """JSON-массив или строки ``task:`` / ``incident:`` / ``note:``. Пусто — ошибка."""
    raw = text.strip()
    if not raw:
        raise _parse_error("текст пуст")
    items: list[EntityDraft]
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise _parse_error("некорректный JSON") from exc
        if not isinstance(parsed, list):
            raise _parse_error("ожидался JSON-массив")
        items = [_from_obj(row) for row in parsed]
    else:
        items = []
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            match = _LINE.fullmatch(stripped)
            if match is None:
                raise _parse_error(f"строка не разобрана: {stripped[:80]}")
            title, project_id, existing = _split_line_title(match.group(2))
            items.append(
                EntityDraft(
                    type=_type_of(match.group(1)),
                    title=_title(title),
                    project_id=project_id,
                    existing_task_id=existing,
                )
            )
    if not items:
        raise _parse_error("нет сущностей")
    return items
