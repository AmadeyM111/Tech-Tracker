"""Согласие на обработку ПДн: версия и время согласия (спека 021, ADR-0027).

Аддитивно: у существующих пользователей столбцы ``NULL`` («согласия нет»); при включённой функции
им показывается экран подтверждения. Столбцы заявки на регистрацию переносят согласие в
``app_user`` при подтверждении email. Downgrade снимает столбцы.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("app_user", sa.Column("pdn_consent_version", sa.Text(), nullable=True))
    op.add_column(
        "app_user", sa.Column("pdn_consented_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "registration_request", sa.Column("pdn_consent_version", sa.Text(), nullable=True)
    )
    op.add_column(
        "registration_request",
        sa.Column("pdn_consent_at", sa.DateTime(timezone=True), nullable=True),
    )
    # состояние входа через провайдера (0016): отмеченное до перехода согласие
    op.add_column("oauth_login_state", sa.Column("pdn_consent_version", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("oauth_login_state", "pdn_consent_version")
    op.drop_column("registration_request", "pdn_consent_at")
    op.drop_column("registration_request", "pdn_consent_version")
    op.drop_column("app_user", "pdn_consented_at")
    op.drop_column("app_user", "pdn_consent_version")
