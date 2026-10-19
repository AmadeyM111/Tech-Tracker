"""T73: прогресс подзадач, чистая функция (plan §4.8/progress.py; FR-22, AC-7).

Ожидаемый интерфейс: ``app.domain.tasks.progress.progress(done: int, total: int) -> int | None``.
"""

from __future__ import annotations

import pytest

from app.domain.tasks.progress import progress


def test_ac7_no_subtasks_progress_is_none_not_zero() -> None:
    """FR-22: нет подзадач (0/0) — None, а не 0."""
    assert progress(0, 0) is None


def test_ac7_one_of_three_done_is_33_rounded_down() -> None:
    """AC-7: 1 из 3 — 33 (округление вниз)."""
    assert progress(1, 3) == 33


@pytest.mark.parametrize(
    ("done", "total", "expected"),
    [
        (2, 3, 66),
        (3, 3, 100),
        (0, 4, 0),
        (1, 1, 100),
        (1, 7, 14),
        (6, 7, 85),
        (199, 200, 99),
        (1, 1000, 0),
    ],
)
def test_fr22_floor_percent(done: int, total: int, expected: int) -> None:
    result = progress(done, total)
    assert result == expected
    assert isinstance(result, int)
    assert not isinstance(result, bool)


def test_fr22_zero_done_with_subtasks_is_zero_not_none() -> None:
    """Есть подзадачи, ни одна не готова — 0 (отличается от None)."""
    result = progress(0, 5)
    assert result == 0
    assert result is not None
