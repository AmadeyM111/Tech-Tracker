"""CHECK длины идентификатора сессии: user_session.id = HMAC-SHA256, 32 байта (D-13).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_user_session_id_length"


def upgrade() -> None:
    op.create_check_constraint(op.f(_CONSTRAINT), "user_session", "octet_length(id) = 32")


def downgrade() -> None:
    op.drop_constraint(op.f(_CONSTRAINT), "user_session", type_="check")
