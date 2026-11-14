"""Упрощённый вход, этап (а): «Запомнить меня» и способ входа в сессии (spec 029, ADR-0026).

Аддитивно: два столбца ``user_session`` со значениями по умолчанию (у существующих сессий —
``remember = false``, ``auth_method = 'password'``). CHECK допускает будущие способы входа из
спеки 029, чтобы следующие этапы не меняли схему. Downgrade снимает CHECK и столбцы.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_session",
        sa.Column("remember", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "user_session",
        sa.Column("auth_method", sa.Text(), nullable=False, server_default="password"),
    )
    op.create_check_constraint(
        "auth_method_valid",
        "user_session",
        "auth_method IN ('password', 'magic_link', 'yandex', 'vk', 'google')",
    )


def downgrade() -> None:
    op.drop_constraint("auth_method_valid", "user_session", type_="check")
    op.drop_column("user_session", "auth_method")
    op.drop_column("user_session", "remember")
