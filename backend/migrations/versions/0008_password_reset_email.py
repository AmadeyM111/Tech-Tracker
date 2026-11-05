"""Сброс пароля по email: ``app_user.email``, ``password_reset_token``, ``password_reset_attempt``.

Spec 007 (NFR-4), plan 007 §4.1, PR-1, PR-7. Литералы вместо импорта кода приложения. Колонка
``email`` допускает NULL (UNIQUE не конфликтует с NULL), CHECK требует нижний регистр
(``COLLATE "C"`` делает ``lower()`` ASCII-only). Токены и попытки хранят только хеши
(SHA-256 / HMAC-SHA256, 32 байта). Downgrade удаляет всё созданное.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("app_user", sa.Column("email", sa.String(length=254), nullable=True))
    op.create_unique_constraint(op.f("uq_app_user_email"), "app_user", ["email"])
    op.create_check_constraint(
        op.f("ck_app_user_email_lower"), "app_user", 'lower(email COLLATE "C") = email'
    )

    op.create_table(
        "password_reset_token",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "octet_length(token_hash) = 32", name=op.f("ck_password_reset_token_token_hash_length")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_password_reset_token_user_id_app_user"),
            ondelete="CASCADE",
            deferrable=True,
            initially="IMMEDIATE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_password_reset_token")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_password_reset_token_token_hash")),
    )
    op.create_index(
        op.f("ix_password_reset_token_user_id"), "password_reset_token", ["user_id"], unique=False
    )

    op.create_table(
        "password_reset_attempt",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("key_hash", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "scope IN ('email','ip')", name=op.f("ck_password_reset_attempt_scope_valid")
        ),
        sa.CheckConstraint(
            "octet_length(key_hash) = 32", name=op.f("ck_password_reset_attempt_key_hash_length")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_password_reset_attempt")),
    )
    op.create_index(
        "ix_password_reset_attempt_scope_key_hash_created_at",
        "password_reset_attempt",
        ["scope", "key_hash", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_password_reset_attempt_created_at"),
        "password_reset_attempt",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("password_reset_attempt")
    op.drop_table("password_reset_token")
    op.drop_constraint(op.f("ck_app_user_email_lower"), "app_user", type_="check")
    op.drop_constraint(op.f("uq_app_user_email"), "app_user", type_="unique")
    op.drop_column("app_user", "email")
