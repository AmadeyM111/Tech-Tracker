"""Модель ``backup_run`` — журнал запусков ``gtrack backup`` (spec 009 FR-4, plan PB-5).

Глобальная таблица без ``workspace_id`` (как ``app_user``): копия снимается со всей БД, а не с
пространства. Содержимого копии, путей и секретов в строке нет — только метаданные запуска.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, UUIDPkMixin


class BackupRunStatus(StrEnum):
    OK = "ok"
    FAILED = "failed"


class BackupRun(UUIDPkMixin, Base):
    __tablename__ = "backup_run"
    __table_args__ = (
        CheckConstraint("status IN ('ok','failed')", name="status_valid"),
        CheckConstraint("finished_at >= started_at", name="finished_after_started"),
        CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="size_non_negative"),
        CheckConstraint("(status = 'ok') = (error_code IS NULL)", name="error_code_iff_failed"),
    )

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    schema_revision: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)


# Статус для ТА: последний запуск и последний успешный — по времени окончания.
Index("ix_backup_run_finished_at", BackupRun.finished_at.desc())
Index(
    "ix_backup_run_ok_finished_at",
    BackupRun.finished_at.desc(),
    postgresql_where=text("status = 'ok'"),
)
