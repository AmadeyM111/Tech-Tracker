"""Пресеты фильтра по сроку и метка «Горит» (spec 008 FR-7, FR-8; plan PS-3, PS-5, PS-10).

«Сегодня» передаётся вызывающим (``today_msk()``, ADR-0007); функции чистые и не читают часы.
"""

from __future__ import annotations

from datetime import date, timedelta
from enum import StrEnum

from sqlalchemy import ColumnElement, and_

from app.domain.tasks.models import Task, TaskPriority, TaskStatus


class DuePreset(StrEnum):
    OVERDUE = "overdue"
    TODAY = "today"
    TOMORROW = "tomorrow"
    WEEK = "week"
    NONE = "none"


def week_end(today: date) -> date:
    """Воскресенье календарной недели (пн–вс), в которую входит ``today``."""
    return today + timedelta(days=6 - today.weekday())


def due_condition(preset: DuePreset, today: date) -> ColumnElement[bool]:
    """Условие SQL для пресета; «Просрочено» не включает завершённые задачи (Q-3)."""
    match preset:
        case DuePreset.OVERDUE:
            return and_(Task.due_date < today, Task.status != TaskStatus.DONE)
        case DuePreset.TODAY:
            return Task.due_date == today
        case DuePreset.TOMORROW:
            return Task.due_date == today + timedelta(days=1)
        case DuePreset.WEEK:
            return Task.due_date.between(today, week_end(today))
        case DuePreset.NONE:
            return Task.due_date.is_(None)


def range_condition(due_from: date | None, due_to: date | None) -> ColumnElement[bool]:
    """Диапазон срока «с / по» (spec 024 FR-3): границы включительно, каждая необязательна.

    Задачи без срока не попадают. Статус не учитывается: «done» входит в диапазон (Q-3).
    Хотя бы одна граница обязана быть задана (Fail Fast): без неё фильтра нет.
    """
    conditions: list[ColumnElement[bool]] = []
    if due_from is not None:
        conditions.append(Task.due_date >= due_from)
    if due_to is not None:
        conditions.append(Task.due_date <= due_to)
    if not conditions:
        raise ValueError("диапазон срока требует хотя бы одну границу")
    return and_(*conditions)


def is_hot(priority: str, due: date | None, status: str, today: date) -> bool:
    """«Горит»: высокий приоритет, срок сегодня или в прошлом, задача не завершена (FR-8)."""
    return (
        priority == TaskPriority.HIGH
        and due is not None
        and due <= today
        and status != TaskStatus.DONE
    )
