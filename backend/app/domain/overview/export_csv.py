"""Формирование CSV выборки «Сводки» (spec 025 FR-3, FR-4; ADR-0023). Чистые функции, без БД.

UTF-8 с BOM, разделитель ``;``, CRLF, все поля в кавычках (``"`` внутри удваивается). Ячейка с
текстом, начинающимся с ``=``, ``+``, ``-``, ``@``, табуляции или ``\\r``, получает ведущий ``'``:
защита от формул Excel. Даты — ``ДД.ММ.ГГГГ`` и ``ДД.ММ.ГГГГ ЧЧ:ММ`` по Москве (ADR-0007).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final
from uuid import UUID

from app.core.clock import MOSCOW_TZ

HEADER: Final = (
    "Проект",
    "Задача",
    "Статус",
    "Приоритет",
    "Исполнитель",
    "Срок",
    "Создана",
    "Изменена",
    "Ссылка",
)
# Подписи — те же, что на экране «Сводки» (summary.tile.*, tasks.priority.*).
STATUS_LABELS: Final = {
    "todo": "Не начато",
    "in_progress": "В работе",
    "review": "На проверке",
    "done": "Готово",
}
PRIORITY_LABELS: Final = {"low": "Низкий", "medium": "Средний", "high": "Высокий"}
_FORMULA_START: Final = ("=", "+", "-", "@", "\t", "\r")
BOM: Final = "﻿"


@dataclass(frozen=True)
class ExportRow:
    task_id: UUID
    project: str
    title: str
    status: str
    priority: str
    assignee: str | None
    due_date: date | None
    created_at: datetime
    updated_at: datetime


def escape_cell(value: str) -> str:
    """Ведущий апостроф для текста, который Excel мог бы выполнить как формулу."""
    return "'" + value if value.startswith(_FORMULA_START) else value


def _moment(value: datetime) -> str:
    return value.astimezone(MOSCOW_TZ).strftime("%d.%m.%Y %H:%M")


def _link(base_url: str | None, task_id: UUID) -> str:
    return "" if not base_url else f"{base_url.rstrip('/')}/tasks/{task_id}"


def render_csv(rows: Sequence[ExportRow], *, base_url: str | None) -> bytes:
    """Файл целиком: BOM, строка заголовков, строки данных; пустая выборка — только заголовки."""
    out = io.StringIO(newline="")
    writer = csv.writer(out, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow(HEADER)
    for r in rows:
        writer.writerow(
            [
                escape_cell(r.project),
                escape_cell(r.title),
                STATUS_LABELS.get(r.status, r.status),
                PRIORITY_LABELS.get(r.priority, r.priority),
                "" if r.assignee is None else escape_cell(r.assignee),
                "" if r.due_date is None else r.due_date.strftime("%d.%m.%Y"),
                _moment(r.created_at),
                _moment(r.updated_at),
                _link(base_url, r.task_id),
            ]
        )
    return (BOM + out.getvalue()).encode("utf-8")
