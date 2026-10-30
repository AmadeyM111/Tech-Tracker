"""Агенты и ключи API: app_user.is_agent, таблица api_key, domain_event.api_key_id.

Spec 007 FR-1, FR-6, FR-30, NFR-7; plan 007 §4.1, PD-1, PD-9. В ``api_key`` хранится только
SHA-256 секрета. Триггеры неизменяемости ``domain_event`` на ``ADD COLUMN`` без значения по
умолчанию не влияют. Downgrade в обратном порядке: ключи и признак агента теряются (ADR-0015).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENT_FK = "fk_domain_event_api_key_id_api_key"


def _fk(column: str, target: str, name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column],
        [target],
        name=op.f(name),
        ondelete="RESTRICT",
        deferrable=True,
        initially="IMMEDIATE",
    )


def upgrade() -> None:
    op.add_column(
        "app_user",
        sa.Column("is_agent", sa.Boolean(), server_default=sa.false(), nullable=False),
    )

    op.create_table(
        "api_key",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("secret_digest", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.Uuid(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rate_window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rate_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 100", name=op.f("ck_api_key_name_length")
        ),
        sa.CheckConstraint(
            "octet_length(secret_digest) = 32", name=op.f("ck_api_key_digest_length")
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name=op.f("ck_api_key_expires_after_created")
        ),
        sa.CheckConstraint("rate_count >= 0", name=op.f("ck_api_key_rate_count_nonnegative")),
        sa.CheckConstraint(
            "(revoked_at IS NULL) = (revoked_by IS NULL)", name=op.f("ck_api_key_revoked_pair")
        ),
        _fk("workspace_id", "workspace.id", "fk_api_key_workspace_id_workspace"),
        _fk("user_id", "app_user.id", "fk_api_key_user_id_app_user"),
        _fk("created_by", "app_user.id", "fk_api_key_created_by_app_user"),
        _fk("revoked_by", "app_user.id", "fk_api_key_revoked_by_app_user"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_key")),
        sa.UniqueConstraint("secret_digest", name=op.f("uq_api_key_secret_digest")),
    )
    op.create_index(op.f("ix_api_key_workspace_id_user_id"), "api_key", ["workspace_id", "user_id"])

    op.add_column("domain_event", sa.Column("api_key_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f(_EVENT_FK),
        "domain_event",
        "api_key",
        ["api_key_id"],
        ["id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="IMMEDIATE",
    )


def downgrade() -> None:
    op.drop_constraint(op.f(_EVENT_FK), "domain_event", type_="foreignkey")
    op.drop_column("domain_event", "api_key_id")
    op.drop_index(op.f("ix_api_key_workspace_id_user_id"), table_name="api_key")
    op.drop_table("api_key")
    op.drop_column("app_user", "is_agent")
