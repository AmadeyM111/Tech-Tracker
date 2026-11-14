"""OAuth 2.1 для облачных MCP-клиентов: клиенты, гранты, коды, токены, лимиты (spec 028, ADR-0025).

Аддитивно; литералы вместо импорта кода приложения. Секреты — только SHA-256. Downgrade удаляет
пять таблиц в обратном порядке зависимостей.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "oauth_attempt",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("key_hash", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "scope IN ('register_ip','token_ip')", name=op.f("ck_oauth_attempt_scope_valid")
        ),
        sa.CheckConstraint(
            "octet_length(key_hash) = 32", name=op.f("ck_oauth_attempt_key_hash_length")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_attempt")),
    )
    op.create_index(
        op.f("ix_oauth_attempt_created_at"), "oauth_attempt", ["created_at"], unique=False
    )
    op.create_index(
        "ix_oauth_attempt_scope_key_hash_created_at",
        "oauth_attempt",
        ["scope", "key_hash", "created_at"],
        unique=False,
    )
    op.create_table(
        "oauth_client",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Text(), nullable=False),
        sa.Column("client_name", sa.Text(), nullable=True),
        sa.Column("redirect_uris", sa.ARRAY(sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "char_length(client_id) BETWEEN 16 AND 64",
            name=op.f("ck_oauth_client_client_id_length"),
        ),
        sa.CheckConstraint(
            "client_name IS NULL OR char_length(client_name) BETWEEN 1 AND 64",
            name=op.f("ck_oauth_client_client_name_length"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_client")),
        sa.UniqueConstraint("client_id", name=op.f("uq_oauth_client_client_id")),
    )
    op.create_index(
        op.f("ix_oauth_client_created_at"), "oauth_client", ["created_at"], unique=False
    )
    op.create_table(
        "oauth_grant",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["oauth_client.id"],
            name=op.f("fk_oauth_grant_client_id_oauth_client"),
            ondelete="CASCADE",
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_oauth_grant_user_id_app_user"),
            ondelete="CASCADE",
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspace.id"],
            name=op.f("fk_oauth_grant_workspace_id_workspace"),
            ondelete="RESTRICT",
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_grant")),
    )
    op.create_index(op.f("ix_oauth_grant_client_id"), "oauth_grant", ["client_id"], unique=False)
    op.create_index(
        "ix_oauth_grant_user_id_active",
        "oauth_grant",
        ["user_id"],
        unique=False,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        op.f("ix_oauth_grant_workspace_id"), "oauth_grant", ["workspace_id"], unique=False
    )
    op.create_table(
        "oauth_code",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("grant_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.LargeBinary(), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("code_challenge", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "octet_length(code_hash) = 32", name=op.f("ck_oauth_code_code_hash_length")
        ),
        sa.ForeignKeyConstraint(
            ["grant_id"],
            ["oauth_grant.id"],
            name=op.f("fk_oauth_code_grant_id_oauth_grant"),
            ondelete="CASCADE",
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_code")),
        sa.UniqueConstraint("code_hash", name=op.f("uq_oauth_code_code_hash")),
    )
    op.create_index(op.f("ix_oauth_code_expires_at"), "oauth_code", ["expires_at"], unique=False)
    op.create_index(op.f("ix_oauth_code_grant_id"), "oauth_code", ["grant_id"], unique=False)
    op.create_table(
        "oauth_token",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("grant_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('access','refresh')", name=op.f("ck_oauth_token_kind_valid")),
        sa.CheckConstraint(
            "octet_length(token_hash) = 32", name=op.f("ck_oauth_token_token_hash_length")
        ),
        sa.ForeignKeyConstraint(
            ["grant_id"],
            ["oauth_grant.id"],
            name=op.f("fk_oauth_token_grant_id_oauth_grant"),
            ondelete="CASCADE",
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_token")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_oauth_token_token_hash")),
    )
    op.create_index(op.f("ix_oauth_token_expires_at"), "oauth_token", ["expires_at"], unique=False)
    op.create_index(op.f("ix_oauth_token_grant_id"), "oauth_token", ["grant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_oauth_token_grant_id"), table_name="oauth_token")
    op.drop_index(op.f("ix_oauth_token_expires_at"), table_name="oauth_token")
    op.drop_table("oauth_token")
    op.drop_index(op.f("ix_oauth_code_grant_id"), table_name="oauth_code")
    op.drop_index(op.f("ix_oauth_code_expires_at"), table_name="oauth_code")
    op.drop_table("oauth_code")
    op.drop_index(op.f("ix_oauth_grant_workspace_id"), table_name="oauth_grant")
    op.drop_index(
        "ix_oauth_grant_user_id_active",
        table_name="oauth_grant",
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.drop_index(op.f("ix_oauth_grant_client_id"), table_name="oauth_grant")
    op.drop_table("oauth_grant")
    op.drop_index(op.f("ix_oauth_client_created_at"), table_name="oauth_client")
    op.drop_table("oauth_client")
    op.drop_index("ix_oauth_attempt_scope_key_hash_created_at", table_name="oauth_attempt")
    op.drop_index(op.f("ix_oauth_attempt_created_at"), table_name="oauth_attempt")
    op.drop_table("oauth_attempt")
