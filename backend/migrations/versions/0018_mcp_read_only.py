"""Read-only флаг персональных MCP-токенов (спека 032).

Существующие ``gtrk_`` остаются с полным доступом (``false``). OAuth read-only живёт в
``oauth_grant.scope`` (``mcp:read`` без ``mcp``), столбец гранта не меняется.

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "api_token",
        sa.Column("read_only", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("api_token", "read_only", server_default=None)


def downgrade() -> None:
    op.drop_column("api_token", "read_only")
