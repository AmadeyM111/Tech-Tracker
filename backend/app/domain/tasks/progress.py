"""Прогресс по подзадачам (plan 006 §4.3, PD-10; FR-30, AC-43)."""

from __future__ import annotations


def progress(*, done: int, in_work: int, total: int) -> int | None:
    """006/FR-30: ⌊(100·done + 50·in_work) / total⌋; ``None``, если подзадач нет."""
    if total == 0:
        return None
    return (100 * done + 50 * in_work) // total
