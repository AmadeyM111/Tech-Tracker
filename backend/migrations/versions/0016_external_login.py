"""Внешний вход (spec 029, ADR-0026): ``external_identity``, ``oauth_login_state``.

Аддитивно, кроме двух смягчений: ``app_user.password_hash`` допускает NULL (учётная запись,
созданная провайдером, без пароля), а CHECK ``oauth_attempt.scope`` получает значение
``external_ip`` (лимит по IP для входа через провайдера). Существующие данные не меняются.
Downgrade: удаляет таблицы и строки ``external_ip``, возвращает CHECK; ``NOT NULL`` на
``password_hash`` возвращается только если нет учётных записей без пароля (иначе миграция
останавливается с понятной ошибкой, данные не теряются).

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("app_user", "password_hash", existing_type=sa.Text(), nullable=True)

    op.create_table(
        "external_identity",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_subject", sa.String(length=255), nullable=False),
        sa.Column("email_at_link", sa.String(length=254), nullable=True),
        sa.Column("email_verified_by_provider", sa.Boolean(), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unlinked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "provider IN ('yandex', 'vk', 'google')",
            name=op.f("ck_external_identity_provider_valid"),
        ),
        sa.CheckConstraint(
            "char_length(provider_subject) >= 1",
            name=op.f("ck_external_identity_subject_not_empty"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_external_identity_user_id_app_user"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_external_identity")),
    )
    op.create_index(op.f("ix_external_identity_user_id"), "external_identity", ["user_id"])
    op.create_index(
        "uq_external_identity_subject_active",
        "external_identity",
        ["provider", "provider_subject"],
        unique=True,
        postgresql_where=sa.text("unlinked_at IS NULL"),
    )
    op.create_index(
        "uq_external_identity_user_provider_active",
        "external_identity",
        ["user_id", "provider"],
        unique=True,
        postgresql_where=sa.text("unlinked_at IS NULL"),
    )

    op.create_table(
        "oauth_login_state",
        sa.Column("state_hash", sa.LargeBinary(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("verifier", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("remember", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "provider IN ('yandex', 'vk', 'google')",
            name=op.f("ck_oauth_login_state_provider_valid"),
        ),
        sa.CheckConstraint(
            "purpose IN ('login', 'link')", name=op.f("ck_oauth_login_state_purpose_valid")
        ),
        sa.CheckConstraint(
            "octet_length(state_hash) = 32", name=op.f("ck_oauth_login_state_state_hash_length")
        ),
        sa.CheckConstraint(
            "(purpose = 'link') = (user_id IS NOT NULL)",
            name=op.f("ck_oauth_login_state_link_has_user"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_oauth_login_state_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("state_hash", name=op.f("pk_oauth_login_state")),
    )
    op.create_index(op.f("ix_oauth_login_state_expires_at"), "oauth_login_state", ["expires_at"])

    op.drop_constraint(op.f("ck_oauth_attempt_scope_valid"), "oauth_attempt", type_="check")
    op.create_check_constraint(
        op.f("ck_oauth_attempt_scope_valid"),
        "oauth_attempt",
        "scope IN ('register_ip','token_ip','external_ip')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_oauth_attempt_scope_valid"), "oauth_attempt", type_="check")
    op.execute("DELETE FROM oauth_attempt WHERE scope = 'external_ip'")
    op.create_check_constraint(
        op.f("ck_oauth_attempt_scope_valid"),
        "oauth_attempt",
        "scope IN ('register_ip','token_ip')",
    )
    op.drop_index(op.f("ix_oauth_login_state_expires_at"), table_name="oauth_login_state")
    op.drop_table("oauth_login_state")
    op.drop_index("uq_external_identity_user_provider_active", table_name="external_identity")
    op.drop_index("uq_external_identity_subject_active", table_name="external_identity")
    op.drop_index(op.f("ix_external_identity_user_id"), table_name="external_identity")
    op.drop_table("external_identity")
    nopass = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM app_user WHERE password_hash IS NULL"))
        .scalar_one()
    )
    if nopass:
        raise RuntimeError(
            "downgrade 0016 невозможен: есть учётные записи без пароля (вход через провайдера)"
        )
    op.alter_column("app_user", "password_hash", existing_type=sa.Text(), nullable=False)
