"""Прогресс подзадач, чистая функция (plan 006 §4.3, PD-10; spec 006 FR-30, AC-43).

Интерфейс: ``app.domain.tasks.progress.progress(*, done, in_work, total) -> int | None``
= ``(100*done + 50*in_work) // total``; ``None`` при ``total == 0``.
"""

from __future__ import annotations

import inspect

import pytest

from app.domain.tasks.progress import progress


def test_ac43_no_subtasks_progress_is_none_not_zero() -> None:
    """FR-30: нет подзадач (total=0) - None, а не 0."""
    assert progress(done=0, in_work=0, total=0) is None


def test_pd10_counters_are_keyword_only() -> None:
    """PD-10: ключевые аргументы исключают перепутывание счётчиков."""
    params = inspect.signature(progress).parameters
    assert list(params) == ["done", "in_work", "total"]
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in params.values())
    with pytest.raises(TypeError):
        progress(1, 0, 3)  # type: ignore[misc]


@pytest.mark.parametrize(
    ("done", "in_work", "total", "expected"),
    [
        # таблица AC-43 (todo ×N -> 0 в счётчиках не участвует)
        (0, 0, 3, 0),  # К выполнению ×3
        (0, 1, 3, 16),  # В работе, К выполнению ×2
        (0, 1, 3, 16),  # На проверке, К выполнению ×2
        (1, 0, 3, 33),  # Выполнена, К выполнению ×2
        (1, 2, 3, 66),  # В работе, На проверке, Выполнена
        (2, 1, 3, 83),  # Выполнена ×2, На проверке
        (0, 3, 3, 50),  # В работе ×3
        (1, 1, 2, 75),  # На проверке, Выполнена
        (0, 1, 1, 50),  # одна подзадача на проверке
        (3, 0, 3, 100),  # Выполнена ×3
        # округление вниз
        (1, 0, 7, 14),
        (6, 0, 7, 85),
        (199, 0, 200, 99),
        (0, 1, 1000, 0),
    ],
)
def test_ac43_weights_100_50_0_floor(done: int, in_work: int, total: int, expected: int) -> None:
    result = progress(done=done, in_work=in_work, total=total)
    assert result == expected
    assert isinstance(result, int)
    assert not isinstance(result, bool)


def test_fr30_zero_with_subtasks_is_zero_not_none() -> None:
    """Есть подзадачи, все «К выполнению» - 0 (отличается от None)."""
    result = progress(done=0, in_work=0, total=5)
    assert result == 0
    assert result is not None
