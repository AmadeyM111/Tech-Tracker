"""Схемы раздела «Система» для ТА (spec 009 FR-6): состояние резервных копий без путей."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class BackupStatusOut(BaseModel):
    """Последняя успешная копия, последний запуск и признак «устарела» (plan PB-6)."""

    model_config = ConfigDict(from_attributes=True)

    last_success_at: datetime | None
    last_success_size_bytes: int | None
    last_run_at: datetime | None
    last_run_status: Literal["ok", "failed"] | None
    stale: bool
    stale_after_hours: int
