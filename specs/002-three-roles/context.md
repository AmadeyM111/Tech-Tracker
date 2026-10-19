# Контекст: удаление роли «Смешанная» (scout, 2026-10-16)

Правка поверх `specs/001-pilot-r1/` (spec v0.17 DRAFT, plan.md, tasks.md). Последняя миграция — `0005`.

## Backend
- `backend/app/domain/access/roles.py`: `Role.MIXED` :22; `ROLE_CAPABILITIES` :59–63 (MIXED = TA ∪ BA ∪ `PROJECT_MANAGE_ANY`); `ACCOUNT_ADMIN_ROLES = {TECH_ADMIN, MIXED}` :67; `PROJECT_MANAGE_ANY` :34, :61.
- CHECK `role_valid`: `domain/workspaces/models.py:29–31`; миграция `migrations/versions/0001_identity.py:76–78` (`ck_workspace_member_role_valid`).
- `domain/access/policy.py`: `is_own_project` :42, `can_view_project` :49, `can_edit_task_fully` :66, `can_change_assignee` :115, `can_delete_comment`; логика владения/удаления/архива размазана — проверять при правке.
- `domain/projects/queries.py:178` (`not in (BUSINESS_ADMIN, MIXED)`); `domain/users/directory.py:26–28`; `domain/access/recipients.py` (через `ROLE_CAPABILITIES`).
- FR-69: `domain/users/service.py` :64 `_ADMIN_ROLE_VALUES`, :95, :232–240 `ensure_account_admin_remains` (422 `last_account_admin`), :488–489. Аудит смены роли :492–510 (`USER_ROLE_*`, `record_event`, `UserEventDetails(role_from, role_to)`).
- API: `api/v1/schemas/admin.py:27,55` (типизировано `Role`); docstring с СМ: `schemas/common.py:28`, `api/v1/users.py:34`, `projects.py:46,100`, `comments.py:82`, `schemas/tasks.py:52`, `domain/tasks/service.py:94`.
- Демо: `domain/ops/demo.py:50` (`demo.mixed`), :212. Bootstrap ТА: `domain/system/bootstrap.py:166` (mixed не использует).
- Миграции: шаблон `0006_<slug>.py`, `down_revision="0005"`. Миграции аудит НЕ пишут (аудит только в сервисном слое); 0005 делает UPDATE данных + `op.create_check_constraint`.

## Frontend
- `shared/i18n/ru.ts:66` (`admin.role.mixed`); `features/admin/UsersPage.tsx:24,45,118`; `AuditPage.tsx:61`; `tasks/TaskList.tsx:112,137` (`canPickAssignee`); `projects/ProjectPage.tsx:52` (`OWNER_ROLES`); `shared/api/schema.d.ts:1085` (генерируется).
- Генерация: `gostracker openapi --out docs/api/openapi.json` → `cd frontend && npm run gen:api`.

## Тесты
- backend/tests: 48 файлов (api 21, domain 9, db 4, infra 4, unit 4, cli 1, корень 5: `factories.py:29`, `admin_support.py`, `projects_*_support.py`, `tasks_api_support.py`). Ключевые: `unit/test_role_matrix.py`, `unit/test_policy.py`, `unit/test_recipients.py`, `api/test_admin_roles.py`, `api/test_role_change_effect.py`, `api/test_deps_gates.py`, `db/test_migrations.py`, `db/test_identity_models.py`, `db/test_login_display_upgrade.py`, `cli/test_demo_data.py`, `domain/test_user_admin_service.py`; `infra/test_stack_first_run.py` (чужая незакоммиченная правка!), `test_compose_static.py`.
- frontend/tests: 14 файлов (admin 3, tasks 4, projects 2, boards 2, app 2, shared 1).

## Документы
- `specs/001-pilot-r1/spec.md`: FR-8 :381, FR-12 :406, FR-68 :414, FR-69 (~:418), FR-66 :387, FR-14a/14b/14c/15/15a/16/17 :453–496, FR-19/19a/20/23 :535–591, FR-42 :698, данные :840, матрица :862/:919, сокращения :941, BR-1/BR-11/BR-13, AC-11/26/44/45/52/72/73/76–78/99/103/109/110/113/129/130 и др.
- `plan.md`: :16, :345, :453–475 (§11.5), :504–520, :658 (SQL `role IN ('tech_admin','mixed')`), :870, :1606 (D-63), :1681–1695, :1761–1767, :2009.
- `tasks.md`: :844–860, :875, :900, :997, :1261, :1292, :1674, :1696, :2091, :2120, :2249–2255.
- `docs/adr/0003-mixed-role.md` (весь), `docs/adr/0009-permissions-refinement.md` :14–59 (**чужая незакоммиченная правка**), `docs/glossary.md` :21–36 (**чужая правка**), `docs/data-model.md:70`, `docs/api/openapi.json` :1113, :465, `docs/open-questions.md` (**чужая правка**), `docs/acceptance/mvp-demo.md`, `docs/brief/vision.md`.

## Окружение
Python 3.12, `source .venv/bin/activate`; тестовая БД `TEST_DATABASE_URL=...tracker_test`; проверка `bash scripts/check.sh`; `python scripts/task_scope.py T<NN>`.
