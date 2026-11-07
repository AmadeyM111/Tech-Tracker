"""MCP-доступ агентов: ``api_token`` и ``domain_event.client_name``.

ADR-0018, plan M20 §3 (PN-1, PN-6). Аддитивно: существующие строки и миграции не меняются.
Литералы вместо импорта кода приложения. Токен в БД не хранится: ``token_hash`` — SHA-256
(32 байта). Downgrade удаляет всё созданное.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_token",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 64", name=op.f("ck_api_token_name_length")
        ),
        sa.CheckConstraint(
            "octet_length(token_hash) = 32", name=op.f("ck_api_token_token_hash_length")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspace.id"],
            name=op.f("fk_api_token_workspace_id_workspace"),
            ondelete="RESTRICT",
            deferrable=True,
            initially="IMMEDIATE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_api_token_user_id_app_user"),
            ondelete="CASCADE",
            deferrable=True,
            initially="IMMEDIATE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_token")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_api_token_token_hash")),
    )
    op.create_index(op.f("ix_api_token_workspace_id"), "api_token", ["workspace_id"], unique=False)
    op.create_index(
        "ix_api_token_user_id_active",
        "api_token",
        ["user_id"],
        unique=False,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    op.add_column("domain_event", sa.Column("client_name", sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f("ck_domain_event_client_name_length"),
        "domain_event",
        "client_name IS NULL OR char_length(client_name) BETWEEN 1 AND 64",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_domain_event_client_name_length"), "domain_event", type_="check")
    op.drop_column("domain_event", "client_name")
    op.drop_index("ix_api_token_user_id_active", table_name="api_token")
    op.drop_index(op.f("ix_api_token_workspace_id"), table_name="api_token")
    op.drop_table("api_token")
