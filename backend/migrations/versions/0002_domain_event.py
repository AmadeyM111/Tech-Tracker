"""Журнал событий: domain_event, индексы, триггеры append-only (plan §4.3, D-7, D-8).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FORBID_FUNCTION = "gt_forbid_event_mutation"


def upgrade() -> None:
    op.create_table(
        "domain_event",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column(
            "changed_fields",
            sa.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("deal_id", sa.Uuid(), nullable=True),
        sa.Column("in_audit", sa.Boolean(), nullable=False),
        sa.Column("changes", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("details", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspace.id"],
            name=op.f("fk_domain_event_workspace_id_workspace"),
            ondelete="RESTRICT",
            deferrable=True,
            initially="IMMEDIATE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["app_user.id"],
            name=op.f("fk_domain_event_actor_id_app_user"),
            ondelete="RESTRICT",
            deferrable=True,
            initially="IMMEDIATE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_domain_event")),
    )
    op.create_index(
        "ix_domain_event_workspace_id_project_id_id",
        "domain_event",
        ["workspace_id", "project_id", sa.text("id DESC")],
        postgresql_where=sa.text("project_id IS NOT NULL"),
    )
    op.create_index(
        "ix_domain_event_workspace_id_deal_id_id",
        "domain_event",
        ["workspace_id", "deal_id", sa.text("id DESC")],
        postgresql_where=sa.text("deal_id IS NOT NULL"),
    )
    op.create_index(
        "ix_domain_event_workspace_id_id_audit",
        "domain_event",
        ["workspace_id", sa.text("id DESC")],
        postgresql_where=sa.text("in_audit"),
    )
    op.create_index(
        "ix_domain_event_entity_type_entity_id",
        "domain_event",
        ["entity_type", "entity_id"],
    )

    # Append-only (D-8): любое изменение или удаление строки и TRUNCATE — исключение.
    op.execute(
        f"""
        CREATE FUNCTION {_FORBID_FUNCTION}() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'domain_event is append-only: % is forbidden', TG_OP
                USING ERRCODE = 'restrict_violation';
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_domain_event_forbid_update_delete
        BEFORE UPDATE OR DELETE ON domain_event
        FOR EACH ROW EXECUTE FUNCTION {_FORBID_FUNCTION}()
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_domain_event_forbid_truncate
        BEFORE TRUNCATE ON domain_event
        FOR EACH STATEMENT EXECUTE FUNCTION {_FORBID_FUNCTION}()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_domain_event_forbid_truncate ON domain_event")
    op.execute("DROP TRIGGER trg_domain_event_forbid_update_delete ON domain_event")
    op.execute(f"DROP FUNCTION {_FORBID_FUNCTION}()")
    op.drop_index("ix_domain_event_entity_type_entity_id", table_name="domain_event")
    op.drop_index("ix_domain_event_workspace_id_id_audit", table_name="domain_event")
    op.drop_index("ix_domain_event_workspace_id_deal_id_id", table_name="domain_event")
    op.drop_index("ix_domain_event_workspace_id_project_id_id", table_name="domain_event")
    op.drop_table("domain_event")
