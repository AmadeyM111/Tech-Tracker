"""Три роли: снятие роли «Смешанная», запись в журнал от «системы», CHECK role_valid.

Spec 002 FR-2, FR-13…FR-17; plan 002 D-5…D-11. Роль и журнал меняются в той же транзакции,
что и отметка версии (env.py без transaction_per_migration): любой сбой откатывает всё (FR-17).
Литералы вместо импорта перечислений приложения (D-6). Downgrade возвращает только CHECK с четырьмя
значениями; роли бывших «Смешанных» и журнал не трогает (D-10, spec 002 §7).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "ck_workspace_member_role_valid"
_ROLES_002 = "role IN ('tech_admin','business_admin','user')"
_ROLES_001 = "role IN ('tech_admin','business_admin','mixed','user')"


def upgrade() -> None:
    # D-9: самые сильные блокировки сразу, без повышения внутри транзакции
    op.execute("LOCK TABLE workspace_member IN ACCESS EXCLUSIVE MODE")
    op.execute("LOCK TABLE app_user IN SHARE MODE")
    # План: всем бывшим «Смешанным» - NULL; активным - tech_admin, если в их пространстве нет
    # активного ТА (FR-16; «активный» = роль tech_admin и NOT is_blocked; одноразовый пароль
    # не мешает)
    op.execute(
        """
        CREATE TEMP TABLE gt_0006_mixed ON COMMIT DROP AS
        SELECT m.workspace_id, m.user_id, u.login,
               CASE WHEN NOT u.is_blocked AND NOT EXISTS (
                        SELECT 1 FROM workspace_member t JOIN app_user tu ON tu.id = t.user_id
                        WHERE t.workspace_id = m.workspace_id
                          AND t.role = 'tech_admin' AND NOT tu.is_blocked)
                    THEN 'tech_admin' END AS new_role
        FROM workspace_member m JOIN app_user u ON u.id = m.user_id
        WHERE m.role = 'mixed'
        """
    )
    op.execute(
        """
        UPDATE workspace_member m SET role = c.new_role, updated_at = now()
        FROM gt_0006_mixed c
        WHERE m.workspace_id = c.workspace_id AND m.user_id = c.user_id
        """
    )
    # FR-15: ровно одна запись на бывшего «Смешанного», как у set_role (001/FR-41); автор «система»
    op.execute(
        """
        INSERT INTO domain_event (workspace_id, occurred_at, actor_id, entity_type, entity_id,
                                  action, changed_fields, project_id, deal_id, in_audit,
                                  changes, details)
        SELECT c.workspace_id, now(), NULL, 'user', c.user_id,
               CASE WHEN c.new_role IS NULL THEN 'user.role_removed'
                    ELSE 'user.role_changed' END,
               '{}'::text[], NULL, NULL, true, NULL,
               jsonb_build_object('role_from', 'mixed', 'role_to', c.new_role)
        FROM gt_0006_mixed c
        ORDER BY c.workspace_id, c.login, c.user_id
        """
    )
    # FR-2: после снятия ролей (иначе новый CHECK не пройдёт проверку строк)
    op.drop_constraint(op.f(_CHECK), "workspace_member", type_="check")
    op.create_check_constraint(op.f(_CHECK), "workspace_member", _ROLES_002)


def downgrade() -> None:
    # D-10: роли бывших «Смешанных» не восстанавливаются, журнал не меняется (spec 002 §7)
    op.drop_constraint(op.f(_CHECK), "workspace_member", type_="check")
    op.create_check_constraint(op.f(_CHECK), "workspace_member", _ROLES_001)
