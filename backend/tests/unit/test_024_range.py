"""D24-T01: условие диапазона «с / по» (spec 024 FR-1, FR-3; AC-1…AC-3, AC-5, уровень функций)."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.dialects import postgresql

from app.domain.overview.due import range_condition


def _sql(due_from: date | None, due_to: date | None) -> str:
    compiled = range_condition(due_from, due_to).compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    )
    return str(compiled)


def test_024_both_bounds_are_inclusive() -> None:
    sql = _sql(date(2026, 11, 16), date(2026, 11, 20))
    assert "task.due_date >= '2026-11-16'" in sql
    assert "task.due_date <= '2026-11-20'" in sql
    assert "AND" in sql


def test_024_only_from_is_open_upwards() -> None:
    sql = _sql(date(2026, 11, 16), None)
    assert sql == "task.due_date >= '2026-11-16'"


def test_024_only_to_is_open_downwards() -> None:
    sql = _sql(None, date(2026, 11, 20))
    assert sql == "task.due_date <= '2026-11-20'"


def test_024_no_bounds_is_a_programming_error() -> None:
    # Fail Fast: вызывающий обязан передать хотя бы одну границу (без неё фильтра нет).
    with pytest.raises(ValueError):
        range_condition(None, None)
