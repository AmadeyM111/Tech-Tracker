"""Самостоятельная регистрация: имена, ``self_registered``, ``registration_request/attempt``.

Spec 019, plan 019 §4.1, RG-21. Литералы вместо импорта кода приложения. Только добавления:
``app_user.first_name/last_name`` (NULL), ``app_user.self_registered`` (NOT NULL, DEFAULT false),
таблицы заявок и попыток (хеши, без FK). Downgrade удаляет всё созданное.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("app_user", sa.Column("first_name", sa.String(length=100), nullable=True))
    op.add_column("app_user", sa.Column("last_name", sa.String(length=100), nullable=True))
    op.add_column(
        "app_user",
        sa.Column("self_registered", sa.Boolean(), server_default=sa.false(), nullable=False),
    )

    op.create_table(
        "registration_request",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("login", sa.String(length=64), nullable=False),
        sa.Column("login_display", sa.String(length=64), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            'lower(email COLLATE "C") = email', name=op.f("ck_registration_request_email_lower")
        ),
        sa.CheckConstraint(
            "octet_length(token_hash) = 32",
            name=op.f("ck_registration_request_token_hash_length"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_registration_request")),
        sa.UniqueConstraint("email", name=op.f("uq_registration_request_email")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_registration_request_token_hash")),
    )
    op.create_index(
        op.f("ix_registration_request_expires_at"),
        "registration_request",
        ["expires_at"],
        unique=False,
    )

    op.create_table(
        "registration_attempt",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("key_hash", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "scope IN ('request_ip','confirm_ip','confirm_token')",
            name=op.f("ck_registration_attempt_scope_valid"),
        ),
        sa.CheckConstraint(
            "octet_length(key_hash) = 32", name=op.f("ck_registration_attempt_key_hash_length")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_registration_attempt")),
    )
    op.create_index(
        "ix_registration_attempt_scope_key_hash_created_at",
        "registration_attempt",
        ["scope", "key_hash", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_registration_attempt_created_at"),
        "registration_attempt",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("registration_attempt")
    op.drop_table("registration_request")
    op.drop_column("app_user", "self_registered")
    op.drop_column("app_user", "last_name")
    op.drop_column("app_user", "first_name")
