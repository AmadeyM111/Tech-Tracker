"""Отображаемый логин: app_user.login_display и CHECK согласованности с ключом (D-66, FR-73a).

``login`` остаётся ключом (вход, уникальность, поиск, сортировка); ``login_display`` — написание
при создании. Существующие строки получают ``login_display = login`` (как до обновления).
Downgrade теряет написание (R-M10).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "ck_app_user_login_display_lower"


def upgrade() -> None:
    op.add_column("app_user", sa.Column("login_display", sa.String(length=64), nullable=True))
    op.execute("UPDATE app_user SET login_display = login")
    op.alter_column("app_user", "login_display", existing_type=sa.String(length=64), nullable=False)
    op.create_check_constraint(op.f(_CHECK), "app_user", 'lower(login_display COLLATE "C") = login')


def downgrade() -> None:
    op.drop_constraint(op.f(_CHECK), "app_user", type_="check")
    op.drop_column("app_user", "login_display")
