"""S08-T01: пресеты срока и «Горит» (spec 008 FR-7, FR-8; AC-6, AC-7, AC-8 — уровень функций)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.dialects import postgresql

from app.core.clock import today_msk
from app.domain.overview.due import DuePreset, due_condition, is_hot, week_end

MON = date(2026, 11, 9)


@pytest.mark.parametrize(
    ("today", "sunday"),
    [
        (MON, date(2026, 11, 15)),
        (date(2026, 11, 12), date(2026, 11, 15)),
        (date(2026, 11, 15), date(2026, 11, 15)),
    ],
    ids=["monday", "thursday", "sunday"],
)
def test_008_week_end_is_sunday(today: date, sunday: date) -> None:
    assert week_end(today) == sunday


def test_008_ac6_today_flips_at_moscow_midnight() -> None:
    assert today_msk(datetime(2026, 11, 9, 20, 59, 59, tzinfo=UTC)) == date(2026, 11, 9)
    assert today_msk(datetime(2026, 11, 9, 21, 0, 0, tzinfo=UTC)) == date(2026, 11, 10)


def _sql(preset: DuePreset) -> str:
    compiled = due_condition(preset, MON).compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    )
    return str(compiled)


def test_008_ac7_preset_sql() -> None:
    assert "task.due_date < '2026-11-09'" in _sql(DuePreset.OVERDUE)
    assert "task.status != 'done'" in _sql(DuePreset.OVERDUE)
    assert _sql(DuePreset.TODAY) == "task.due_date = '2026-11-09'"
    assert _sql(DuePreset.TOMORROW) == "task.due_date = '2026-11-10'"
    assert _sql(DuePreset.WEEK) == "task.due_date BETWEEN '2026-11-09' AND '2026-11-15'"
    assert _sql(DuePreset.NONE) == "task.due_date IS NULL"


@pytest.mark.parametrize(
    ("priority", "due", "status", "hot"),
    [
        ("high", MON - timedelta(days=1), "todo", True),
        ("high", MON, "in_progress", True),
        ("high", MON + timedelta(days=1), "todo", False),
        ("medium", MON - timedelta(days=1), "todo", False),
        ("high", MON - timedelta(days=1), "done", False),
        ("high", None, "todo", False),
    ],
    ids=["high-yesterday", "high-today", "high-tomorrow", "medium-yesterday", "done", "no-due"],
)
def test_008_ac8_hot(priority: str, due: date | None, status: str, hot: bool) -> None:
    assert is_hot(priority, due, status, MON) is hot
