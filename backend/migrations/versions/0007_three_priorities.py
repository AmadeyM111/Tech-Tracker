"""Три приоритета задачи: low / medium / high, перенос base -> medium.

Spec 006 FR-8…FR-11, FR-13; plan 006 PD-5. Перенос данных и пересоздание CHECK идут в той же
транзакции, что и отметка версии (env.py без transaction_per_migration): любой сбой откатывает
всё (NFR-4). Литералы вместо импорта перечислений приложения. ``updated_at`` не меняется
(сырой SQL, триггеров у ``task`` нет), журнал ``domain_event`` не пишется. Мягко удалённые
строки обновляются тем же ``UPDATE``. Downgrade: ``low`` и ``medium`` -> ``base``, ``high``
без изменений.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "ck_task_priority_valid"
_PRIORITIES_006 = "priority IN ('low','medium','high')"
_PRIORITIES_005 = "priority IN ('base','high')"


def upgrade() -> None:
    op.execute("LOCK TABLE task IN ACCESS EXCLUSIVE MODE")
    op.drop_constraint(op.f(_CHECK), "task", type_="check")
    op.execute("UPDATE task SET priority = 'medium' WHERE priority = 'base'")
    op.create_check_constraint(op.f(_CHECK), "task", _PRIORITIES_006)


def downgrade() -> None:
    op.execute("LOCK TABLE task IN ACCESS EXCLUSIVE MODE")
    op.drop_constraint(op.f(_CHECK), "task", type_="check")
    op.execute("UPDATE task SET priority = 'base' WHERE priority IN ('low', 'medium')")
    op.create_check_constraint(op.f(_CHECK), "task", _PRIORITIES_005)
