"""Прогресс по подзадачам (plan §4.8/progress.py; FR-22, AC-7)."""

from __future__ import annotations


def progress(done: int, total: int) -> int | None:
    """Процент готовых подзадач, округление вниз; ``None``, если подзадач нет (FR-22)."""
    if total == 0:
        return None
    return done * 100 // total
