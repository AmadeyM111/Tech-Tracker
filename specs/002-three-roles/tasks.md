# Tasks: Три роли — упразднение роли «Смешанная» (spec 002)

Статусы: TODO | IN_PROGRESS | DONE | BLOCKED. Статусы ведёт оркестратор.

## Общие условия для всех задач R3

- Источник истины — `specs/002-three-roles/spec.md` (дельта к `specs/001-pilot-r1/spec.md`);
  интерфейсы и решения — `specs/002-three-roles/plan.md` (разделы указаны в задачах). Ссылки
  без префикса — на 002 (`AC-13` = 002/AC-13), ссылки на 001 — с префиксом (`001/AC-43`).
  Если задача противоречит spec или plan — вернуть `PLAN_ISSUE`, ничего не додумывать.
- Окружение: Python 3.12, команды из корня репозитория после `source .venv/bin/activate`.
  Тестовая БД:
  `docker compose -p gostracker-dev -f docker-compose.yml -f deploy/compose.dev.yml up -d db`,
  `export TEST_DATABASE_URL=postgresql+asyncpg://tracker:tracker@localhost:5432/tracker_test`.
  Деструктивные операции с БД разрешены только в `*_test`. Тома Docker не удалять.
- Фронтенд: Node `^22.12 || ^24 || >=26`, команды `cd frontend && npm run lint && npm run typecheck && npm test`.
- Тесты и фикстуры (`backend/tests/**`, `frontend/tests/**`) пишет test-writer, исполнитель их
  не меняет. Задача с пометкой **«только тесты»** не меняет код поставки: если тест красный на
  текущем коде, это `PLAN_ISSUE` (код молча не правится).
- **Рамки файлов.** Менять только файлы из поля «Файлы». Файлы в группе `(+ …)` разрешены, только
  если указанное там условие выполняется. Проверка — `python scripts/task_scope.py R3-Tnn`
  (выход 0). `docs/api/openapi.json` и `frontend/src/shared/api/schema.d.ts` меняются **только**
  через `bash scripts/gen-api.sh` и только в задачах, где это сказано.
- **Запрещено трогать** (чужие незакоммиченные правки или запрет владельца): `CLAUDE.md`,
  `docs/STATE.md`, `docs/adr/0005-project-no-deadline.md`, `docs/adr/0009-permissions-refinement.md`,
  `docs/glossary.md`, `docs/open-questions.md`, `docs/reviews/**`,
  `backend/tests/infra/test_stack_first_run.py`, а также `specs/001-pilot-r1/*`. Нужные в них
  правки перечислены в plan §11.
- **NFR-3: старые тесты.** Тест 001 нельзя удалить или ослабить, пока ему не сопоставлен AC 002.
  Разрешены три действия (plan §6.2): (а) заменить актора (`sm` → `ba3`, `sm_m` → `ba2`, СМ как
  администратор → второй ТА) при тех же assert-ах; (б) обратить ожидание там, где 002 меняет
  правило, с указанием AC 002 в docstring; (в) удалить дубликат нового теста `test_002_*`, назвав
  удалённый тест в docstring заменителя. Каждая задача перечисляет свои старые тесты в поле
  «Старые тесты → AC 002». Ревьюер сверяет это поле с diff.
- Новые тесты на критерии 002 называются `test_002_acN_*`. Часы — `FixedClock` (`FIXED_NOW`),
  seed — фиксированный, Argon2 — дешёвые параметры из `tests/conftest.py`. Логины синтетические.
- «Линтер чистый» = `ruff check backend && ruff format --check backend && mypy --config-file backend/pyproject.toml backend/app`.
- Каждая задача закрывается зелёным `bash scripts/check.sh` (backend, alembic check, frontend).

Порядок и критический путь: R3-T01 → R3-T02 → R3-T03 → R3-T04 → R3-T07 → R3-T11 → R3-T13 →
R3-T16 → R3-T17. Параллельно с ним можно выполнять R3-T05, R3-T06, R3-T08, R3-T09, R3-T10,
R3-T12, R3-T14, R3-T15, когда закрыты их зависимости.

---

## R3-T01 — БА управляет любым проектом (правка, участники, владение, удаление)
- **Статус:** DONE (2 попытки ревью, reviews/R3-T01-1.md, R3-T01-2.md)
- **AC:** AC-11, AC-12, AC-16, AC-17, AC-18, AC-19; FR-8, FR-11, FR-12; NFR-1 (возможности БА в `GET /me`, plan D-1)
- **Файлы:** `backend/app/domain/access/roles.py`, `backend/app/domain/access/policy.py`;
  тесты: `backend/tests/roles002_support.py` (новый), `backend/tests/api/test_ba_projects_002.py` (новый),
  `backend/tests/unit/test_policy.py`, `backend/tests/unit/test_role_matrix.py`,
  `backend/tests/api/test_deps_gates.py`, `backend/tests/api/test_sessions.py`,
  `backend/tests/domain/test_projects_service.py`, `backend/tests/domain/test_project_members_service.py`,
  `backend/tests/api/test_projects.py`, `backend/tests/api/test_project_members.py`
  (+ `backend/tests/api/test_audit.py` — только если тест опирается на «БА-не владелец → 403» при передаче владения)
- **Зависит от:** —
- **Описание:** По plan §4.1 добавить `Capability.PROJECT_MANAGE_ANY` в `_BUSINESS_ADMIN_CAPS`.
  По plan §4.2 `can_manage_project(a, p) = a.can(Capability.PROJECT_MANAGE_ANY)` и
  `can_add_member(a, p, user_id) = can_manage_members(a, p)`; сигнатуры не менять. Ветки и строку
  `Role.MIXED` пока **не трогать** (удаляются в R3-T11). Обновить docstring изменённых функций и
  комментарий у `PROJECT_MANAGE_ANY`. Сервисы проектов и участников не меняются.
  Test-writer: `roles002_support.make_world_002(env) -> World002` строит фикстуру spec §6 для
  API-тестов: пространство; `ta1`, `ta2`; `ba.owner` (владелец и участник P), `ba.member`,
  `ba.out`, `u1`, `u2` и `u3` (П, не участник); задачи T1 и T1.1, T3 и T3.1; комментарии c1, c2, c3;
  токены сессий. Фикстура доопределяется параметрами для AC-12 (P2), AC-17 (`ba.blocked`,
  `ba.free`) и AC-18 (`nr`, три варианта роли владельца; смена роли — через
  `PUT /admin/users/{id}/role` от `ta1`). Тесты `test_002_ac11…ac19_*` повторяют шаги AC
  буквально, с проверкой «данные не изменены, новых записей журнала нет» при отказах.
- **Старые тесты → AC 002:** `unit/test_policy.py`: `test_ac48_can_manage_project_and_members`,
  `test_ac73_can_add_member` — БА любой проект, себя добавляет → AC-11, AC-12;
  `unit/test_role_matrix.py`: БА с `PROJECT_MANAGE_ANY` → FR-8;
  `api/test_deps_gates.py` (таблица `PROJECT_MANAGE_ANY` += `business_admin`),
  `api/test_sessions.py` (`EXPECTED_CAPABILITIES["business_admin"]` += `project_manage_any`) → D-1;
  `domain/test_projects_service.py`: `test_ac48_non_owner_cannot_delete`,
  `test_ac52_owner_transfers_to_ba_member_and_loses_manage`, `test_ac52_ac72_transfer_by_non_manager_is_403`,
  `test_d46_no_change_still_checks_permissions`, `test_p11_5_forbidden_precedes_recipient_check` —
  для БА «403» → выполнено, 403 остаётся для П, ТА, без роли → AC-12, AC-16, AC-17;
  `domain/test_project_members_service.py`: `test_ac54_ba_cannot_add_self`,
  `test_ac73_ac54_others_cannot_add`, `test_ac73_ac54_others_cannot_remove_other_member`,
  `test_d46_add_existing_member_still_checks_permissions` → AC-11, AC-16;
  `api/test_projects.py`: `test_ac52_owner_transfers_to_member_ba_and_loses_delete_right`,
  `test_ac52_non_owner_roles_get_403_on_transfer`, `test_ac48_other_roles_get_403_on_delete`,
  `test_ac110_other_roles_get_403_and_project_is_untouched` → AC-12, AC-16;
  `api/test_project_members.py`: `test_ac54_ba_non_member_adding_himself_is_403`,
  `test_fr15_ac54_ba_member_not_owner_adding_other_is_403`, `test_ac73_non_managers_cannot_remove_others`
  → AC-11, AC-16. Тесты с `sm`/`sm_m` в этой задаче не меняются (R3-T05).
- **Готово, когда:** `pytest -q backend/tests/api/test_ba_projects_002.py backend/tests/unit/test_policy.py backend/tests/unit/test_role_matrix.py backend/tests/api/test_deps_gates.py backend/tests/api/test_sessions.py backend/tests/domain/test_projects_service.py backend/tests/domain/test_project_members_service.py backend/tests/api/test_projects.py backend/tests/api/test_project_members.py backend/tests/api/test_audit.py`
  зелёный; `bash scripts/check.sh` зелёный; `python scripts/task_scope.py R3-T01` → 0.
- **Попытки:** 0

## R3-T02 — БА-участник удаляет любые комментарии проекта
- **Статус:** DONE (1 попытка, reviews/R3-T02-1.md)
- **AC:** AC-13 (удаление c1), AC-15 (удаление c1 неучастником — 403); FR-9 (комментарии), FR-10
- **Файлы:** `backend/app/domain/access/policy.py`;
  тесты: `backend/tests/roles002_support.py`, `backend/tests/api/test_ba_tasks_002.py` (новый),
  `backend/tests/unit/test_policy.py`, `backend/tests/domain/test_comments_service.py`,
  `backend/tests/api/test_comments.py`
- **Зависит от:** R3-T01
- **Описание:** По plan §4.2 (переходная форма):
  `can_delete_comment(a, p, author_id) = BUSINESS_ACCESS and p.actor_is_member and (author_id == a.user_id or a.role in (Role.BUSINESS_ADMIN, Role.MIXED))`.
  `can_edit_comment` не меняется: правит только автор (FR-9). Создать
  `api/test_ba_tasks_002.py` с тестами комментариев из AC-13 (`ba.member` удаляет c1 → 204,
  комментарий удалён мягко) и AC-15 (`ba.out` удаляет c1 → 403, данные не изменены; после
  самодобавления читает комментарии T1 → 200). `ba.member` не может править c1 (автор `u1`) → 403.
- **Старые тесты → AC 002:** `unit/test_policy.py::test_ac103_can_delete_comment`,
  `::test_oi127_ba_member_not_owner_foreign_comment_not_deletable` → БА-участник удаляет → AC-13;
  `domain/test_comments_service.py::test_ac58_ba_non_owner_member_cannot_delete_foreign_403` →
  обращение → AC-13; `::test_s11_5_list_permissions_per_actor` (флаг `delete` у БА-участника) →
  AC-13; `api/test_comments.py` — только тесты, где БА-не владелец получал 403 на удаление чужого
  комментария → AC-13. Тесты с `sm`/`sm_m` не меняются (R3-T06, R3-T07).
- **Готово, когда:** `pytest -q backend/tests/api/test_ba_tasks_002.py backend/tests/unit/test_policy.py backend/tests/domain/test_comments_service.py backend/tests/api/test_comments.py`
  зелёный; `bash scripts/check.sh` зелёный; `python scripts/task_scope.py R3-T02` → 0.
- **Попытки:** 0

## R3-T03 — БА-участник правит, переназначает и удаляет любые задачи проекта
- **Статус:** DONE (1 попытка, reviews/R3-T03-1.md)
- **AC:** AC-13, AC-14, AC-15; FR-9, FR-10, 001/FR-5 (переназначение задач заблокированного)
- **Файлы:** `backend/app/domain/access/policy.py`;
  тесты: `backend/tests/roles002_support.py`, `backend/tests/api/test_ba_tasks_002.py`,
  `backend/tests/unit/test_policy.py`, `backend/tests/domain/test_tasks_update_delete.py`,
  `backend/tests/domain/test_tasks_create.py`, `backend/tests/domain/test_tasks_move.py`,
  `backend/tests/domain/test_tasks_queries.py`, `backend/tests/api/test_tasks.py`,
  `backend/tests/api/test_subtasks.py`, `backend/tests/api/test_task_permissions.py`,
  `backend/tests/api/test_reassign_blocked.py`, `backend/tests/api/test_board_move.py`,
  `backend/tests/api/test_soft_delete.py`
  (+ `backend/tests/api/test_task_recipients.py`, `backend/tests/api/test_project_task_list.py`, `backend/tests/api/test_board.py`, `backend/tests/api/test_personal_tasks.py` — только если их тест опирается на «БА-участник, не владелец, не может править/переназначать/удалять/переносить чужую задачу»)
- **Зависит от:** R3-T02
- **Описание:** По plan §4.2: `is_own_project(a, p)` — БА: `p.actor_is_member`, СМ: как было
  (участник), иначе `False`. `can_edit_task_fully` — БА: `p.actor_is_member`, П и СМ без
  изменений. `can_change_assignee`, `can_delete_task`, `can_create_subtask`,
  `can_change_task_status` не меняются: они наследуют новый смысл. Переписать docstring модуля:
  правило OI-127 (а) и D-54 отменены (002 §5.3 п.3), БА действует по участию. Дописать в
  `api/test_ba_tasks_002.py` сценарии AC-13 (целиком, включая удаление T3 с T3.1 и c3 → 404),
  AC-14 и AC-15 (целиком) шаг за шагом по spec.
- **Старые тесты → AC 002:** `unit/test_policy.py::test_oi127_*` (5 тестов) → обратить: БА-участник
  правит, удаляет, переназначает чужое → AC-13, AC-14; `domain/test_tasks_update_delete.py`:
  `test_ac48_ba_not_owner_cannot_change_foreign_or_assigned_tasks`,
  `test_ac48_ba_not_owner_edits_own_task_but_not_assignee`, `test_ac99_ba_not_owner_cannot_delete_foreign_task`,
  `test_ac43_ba_not_owner_403_sm_member_ok_on_blocked_assignee_task` (часть про БА) → AC-13, AC-14;
  `test_t74_*`, `test_t75_*` — гонки сохраняют смысл, где «переназначает владелец» допустимо
  заменить на БА-участника без ослабления assert-ов; `domain/test_tasks_create.py::test_t70_ba_member_not_owner_subtask_rules`
  → AC-13; `domain/test_tasks_move.py::test_ac48_ba_not_owner_moves_only_own_task` → AC-13;
  `domain/test_tasks_queries.py::test_fr19_permissions_member_ba_not_owner_not_assignee_nothing`,
  `::test_fr19_permissions_ba_non_owner_own_task_edit_no_reassign`,
  `::test_fr19_permission_flags_match_service_outcomes_matrix` (строки БА-участника) → AC-13;
  `api/test_tasks.py` (тесты, где `ba2` получал 403 на правку или смену исполнителя чужой задачи) → AC-13;
  `api/test_subtasks.py::test_t74_review_6_ba_member_not_owner_subtask_formula` → AC-13;
  `api/test_task_permissions.py::test_ac99_mixed_member_deletes_foreign_task_ba_member_cannot`
  (часть «БА не может») → AC-13; `api/test_reassign_blocked.py::test_ac43_ba_member_not_owner_gets_403_mixed_member_reassigns`
  → БА-участник переназначает, `u2` — 403 → AC-14 (здесь же `sm_m` → `ba2`);
  `api/test_board_move.py::test_fr19b_ba_member_non_owner_moves_own_assigned_task_only` → AC-13;
  `api/test_soft_delete.py::test_ac99_*` (удаляющие `usr`, `ba`, `ba2` вместо `sm_m`) → AC-13.
  Прочие тесты с `sm`/`sm_m` не меняются (R3-T06, R3-T07).
- **Готово, когда:** `pytest -q backend/tests/api/test_ba_tasks_002.py backend/tests/unit/test_policy.py backend/tests/domain/test_tasks_update_delete.py backend/tests/domain/test_tasks_create.py backend/tests/domain/test_tasks_move.py backend/tests/domain/test_tasks_queries.py backend/tests/api/test_tasks.py backend/tests/api/test_subtasks.py backend/tests/api/test_task_permissions.py backend/tests/api/test_reassign_blocked.py backend/tests/api/test_board_move.py backend/tests/api/test_soft_delete.py`
  зелёный; `bash scripts/check.sh` зелёный; `python scripts/task_scope.py R3-T03` → 0.
- **Попытки:** 0

## R3-T04 — Несколько ТА и последний администратор (только тесты)
- **Статус:** DONE (2 попытки ревью, reviews/R3-T04-1.md, R3-T04-2.md)
- **AC:** AC-3, AC-4, AC-5, AC-6, AC-7, AC-8, AC-9, AC-10; FR-3, FR-5, FR-6, FR-7
- **Файлы:** тесты: `backend/tests/api/test_tech_admins_002.py` (новый),
  `backend/tests/api/test_tech_admin_races_002.py` (новый), `backend/tests/api/test_admin_roles.py`,
  `backend/tests/api/test_admin_users.py`, `backend/tests/api/test_audit.py`,
  `backend/tests/api/test_e2e_accounts.py`, `backend/tests/api/test_role_change_effect.py`,
  `backend/tests/domain/test_user_admin_service.py`
  (+ `backend/tests/admin_support.py` — только добавить вспомогательные функции; `role_mixed` и `'mixed'` в нём не трогать до R3-T11)
- **Зависит от:** R3-T03
- **Описание:** Только тесты. Код ТА уже выполняет FR-7 (plan §4.4). Если тест красный —
  `PLAN_ISSUE`. `test_tech_admins_002.py` — AC-3…AC-9 по шагам spec (журнал: число записей и
  поля `action`, `actor`, `details.role_from/role_to`). `test_tech_admin_races_002.py` —
  AC-10 (а)–(г), `@pytest.mark.committed`, каждый сценарий ≥ 20 повторов. В каждом повторе
  фикстура восстанавливается: `ta1`, `ta2` — роль `tech_admin`, `is_blocked = false`, сессии
  удалены и созданы заново. Запросы идут одновременно (`asyncio.gather`), как в
  `test_ac78_parallel_requests_never_leave_zero_active_admins`. Проверки повтора: ровно один
  успех; второй — код из AC (а, б: 422 `last_account_admin`; в: 403 или 401; г: 403) либо 503
  `service_busy` с `Retry-After`; ровно один активный ТА; прирост журнала ровно 1, запись о
  выполненном действии. В остальных файлах убрать СМ как администратора учётных записей.
- **Старые тесты → AC 002:** `api/test_admin_roles.py::test_fr12_ta_and_mixed_may_change_own_role`
  → ТА при втором активном ТА меняет свою роль на БА → AC-4, AC-7;
  `::test_ac78_last_admin_may_switch_between_admin_roles` → удалить ветку «ТА → mixed», заменители
  `test_002_ac6_*` и (в R3-T11) `test_002_ac24_*`; `::test_ac78_parallel_requests_never_leave_zero_active_admins`
  → СМ → второй ТА → AC-10; `::test_ac26_non_admins_cannot_assign_roles_including_self` → без
  `mixed` в наборе админов → AC-5; `api/test_admin_users.py::test_fr42_mixed_role_has_access_to_admin_section`
  → удалить, заменитель `test_002_ac3_*`; `::test_ac2_get_user_returns_admin_view` → цель с ролью
  `business_admin` → AC-3; тело `{"role": "mixed"}` в гейт-тесте → `{"role": "user"}` (проверка 403
  не меняется) → AC-5; `api/test_audit.py::test_t18_roles_tech_admin_and_mixed_can_view`,
  `::test_t18_filter_entity_type_and_actor_id` → второй ТА → AC-3, AC-5;
  `api/test_e2e_accounts.py::test_ac64_ta_scenario_one_entry_per_action_without_password_values`
  → второй активный ТА, смена своей роли на БА → AC-4 (001/AC-64 по 002 §9);
  `api/test_role_change_effect.py` (`changer_role="mixed"`, `test_t77_ac77_…_mixed_reassigns`) →
  роль меняет только ТА, переназначает БА-участник → AC-14 (001/AC-76, AC-77 по 002 §9);
  `domain/test_user_admin_service.py`: `test_ac26_tech_admin_and_mixed_can_run_account_actions`
  → два ТА → AC-3; `test_ac78_last_admin_may_become_mixed` → удалить, заменители `test_002_ac6_*`
  и `test_002_ac24_*`; `test_ac78_with_second_active_admin_first_may_remove_own_role`,
  `test_ac78_concurrent_mutual_demotion_leaves_one_admin`, `test_t16_review_three_admins_six_concurrent_actions_no_deadlock`,
  `test_ac26_self_assignment_is_allowed_and_audited`, `test_fr67_set_role_does_not_touch_sessions_or_other_users`,
  `test_ac21_foreign_workspace_user_is_404_for_every_action`, `test_ac67_*`,
  `test_ac39_ac44_ac45_non_account_admins_get_403_on_every_account_action` → СМ → ТА, assert-ы те же
  → AC-3, AC-5, AC-7, AC-10.
- **Готово, когда:** `pytest -q backend/tests/api/test_tech_admins_002.py backend/tests/api/test_tech_admin_races_002.py backend/tests/api/test_admin_roles.py backend/tests/api/test_admin_users.py backend/tests/api/test_audit.py backend/tests/api/test_e2e_accounts.py backend/tests/api/test_role_change_effect.py backend/tests/domain/test_user_admin_service.py`
  зелёный; `git diff --stat -- backend/app` пуст; `bash scripts/check.sh` зелёный;
  `python scripts/task_scope.py R3-T04` → 0.
- **Попытки:** 0

## R3-T05 — Тесты без СМ: проекты, участники, изоляция (только тесты)
- **Статус:** DONE (1 попытка, reviews/R3-T05-1.md; соответствие старых и новых имён тестов — там же)
- **AC:** AC-11, AC-12, AC-15, AC-17, AC-19 (замена актора СМ → БА); FR-1
- **Файлы:** тесты: `backend/tests/domain/test_projects_service.py`,
  `backend/tests/domain/test_project_members_service.py`, `backend/tests/api/test_projects.py`,
  `backend/tests/api/test_project_members.py`, `backend/tests/api/test_workspace_isolation.py`,
  `backend/tests/api/test_not_found_vs_forbidden.py`
- **Зависит от:** R3-T01
- **Описание:** Только тесты. Убрать из перечисленных файлов использование СМ: `w.sm`/`"sm"` →
  `ba3` (БА, не участник), `w.sm_m`/`"sm_m"` → `ba2` (БА-участник), пользователи с ролью
  `"mixed"` → `business_admin`. СМ-администратор второго пространства (`test_workspace_isolation.py`)
  → `tech_admin`. Тест, ставший дубликатом `test_002_*` из R3-T01, удаляется с пометкой (общие
  условия, NFR-3). Перечни ролей «БА и СМ» становятся «БА».
- **Старые тесты → AC 002:** `domain/test_projects_service.py`: `test_ac110_sm_not_member_updates_any_project`,
  `test_ac72_sm_not_member_transfers_when_owner_blocked`, `test_ac52_sm_transfers_to_sm_member`
  (→ «БА передаёт участнику-БА»), `test_ac55_ba_and_sm_see_all…`, `test_d45_get_project_by_ba_sm_member_user`,
  `test_fr14_*`, `test_fr13_*`, `test_fr16_*`, `test_ac65_second_transfer…`,
  `test_p10_2_transfer_ownership_serializes_with_member_removal` → AC-11, AC-12, AC-15, AC-17;
  `domain/test_project_members_service.py`: `test_ac73_sm_not_member_adds_other_and_self`,
  `test_ac73_sm_not_member_removes_member`, `test_ac73_owner_ba_adds_member_of_each_business_role`
  (без роли `mixed`), `test_d46_*`, `test_ac53_*`, `test_fr13_*`, `test_d45_list_members_who_can_view`,
  `test_p10_2_*` → AC-11, AC-19; `api/test_projects.py`: `test_ac48_mixed_non_member_can_delete`,
  `test_ac52_ac72_mixed_non_member_transfers_even_if_owner_blocked`,
  `test_ac52_transfer_to_mixed_member_is_allowed` (→ участнику-БА), `test_ac51_mixed_creates_project_as_owner_and_member`,
  `test_ac55_fr17_ba_and_sm_see_all…`, `test_fr17_order…`, `test_ac21_list…`,
  `test_ac110_partial_patch…`, `test_ac48_owner_deletes…` → AC-12, AC-15, AC-17;
  `api/test_project_members.py`: `test_ac73_mixed_non_member_adds_other_user_and_himself`,
  `test_ac73_mixed_non_member_removes_member`, `test_fr15_ac54_mixed_non_member_adding_himself_is_204`,
  `test_d45_members_visible_to_ba_sm…`, `test_ac55_*`, `test_ac53_*`, `test_fr15a_*` → AC-11, AC-19;
  `api/test_workspace_isolation.py`, `api/test_not_found_vs_forbidden.py` (`sm`, `sm_m` в перечнях)
  → AC-15 и 001/AC-21 (изоляция, не поведение СМ).
- **Готово, когда:** `pytest -q backend/tests/domain/test_projects_service.py backend/tests/domain/test_project_members_service.py backend/tests/api/test_projects.py backend/tests/api/test_project_members.py backend/tests/api/test_workspace_isolation.py backend/tests/api/test_not_found_vs_forbidden.py`
  зелёный; `git grep -n -E '"sm"|"sm_m"|w\.sm\b|w\.sm_m\b|Role\.MIXED|"mixed"' -- backend/tests/domain/test_projects_service.py backend/tests/domain/test_project_members_service.py backend/tests/api/test_projects.py backend/tests/api/test_project_members.py backend/tests/api/test_workspace_isolation.py backend/tests/api/test_not_found_vs_forbidden.py`
  пусто; `bash scripts/check.sh` зелёный; `python scripts/task_scope.py R3-T05` → 0.
- **Попытки:** 0

## R3-T06 — Тесты без СМ: задачи, доска, комментарии через API (только тесты)
- **Статус:** DONE (1 попытка, reviews/R3-T06-1.md; соответствие старых и новых имён тестов — там же)
- **AC:** AC-13, AC-15 (замена актора СМ → БА); FR-1
- **Файлы:** тесты: `backend/tests/api/test_tasks.py`, `backend/tests/api/test_subtasks.py`,
  `backend/tests/api/test_task_permissions.py`, `backend/tests/api/test_board.py`,
  `backend/tests/api/test_board_move.py`, `backend/tests/api/test_comments.py`,
  `backend/tests/api/test_personal_tasks.py`, `backend/tests/api/test_project_task_list.py`
- **Зависит от:** R3-T03
- **Описание:** Только тесты, правила те же, что в R3-T05: `sm` → `ba3`, `sm_m` → `ba2`, роли
  `"mixed"` → `business_admin`. Тесты, ставшие дубликатами `test_002_*` из R3-T02/T03,
  удаляются с пометкой. Если из перечня ролей участника убран `sm_m`, а `ba2` в нём уже есть, это
  не ослабление: роль упразднена.
- **Старые тесты → AC 002:** `api/test_tasks.py::test_ac103_sm_non_member_becomes_member_and_creates`
  → `ba3` → AC-15; `::test_ac109_ac56_ba_and_sm_without_assignee…` → БА → AC-13;
  `api/test_subtasks.py::test_owner_and_mixed_member_create_subtask_with_any_assignee` → `ba2` →
  AC-13; `api/test_task_permissions.py::test_ac103_mixed_non_member_adds_himself_and_then_changes_foreign_task`
  → `ba3` → AC-15; `::test_ac99_mixed_member_deletes_foreign_task_ba_member_cannot` → `ba2` →
  AC-13; `api/test_board.py::test_member_roles_can_read_board`, `::test_board_non_member_is_403_for_ba_sm_user`
  → AC-13, AC-15; `api/test_board_move.py::test_move_allowed_for_owner_and_mixed_member_on_any_task`,
  `::test_move_non_member_is_403_and_task_unchanged` → AC-13, AC-15;
  `api/test_comments.py::test_ac103_sm_becomes_able_after_membership` → `ba3` → AC-15;
  `::test_ac58_owner_ba_and_sm_member_delete_foreign` → `ba2` → AC-13;
  `api/test_personal_tasks.py::test_ac6_each_member_sees_exactly_own_assigned_tasks` (`sm_m` в
  плане исполнителей → `ba2`) → 001/AC-6 (не поведение СМ);
  `api/test_project_task_list.py` (параметры `sm_m`, `sm`) → AC-13, AC-15.
- **Готово, когда:** `pytest -q backend/tests/api/test_tasks.py backend/tests/api/test_subtasks.py backend/tests/api/test_task_permissions.py backend/tests/api/test_board.py backend/tests/api/test_board_move.py backend/tests/api/test_comments.py backend/tests/api/test_personal_tasks.py backend/tests/api/test_project_task_list.py`
  зелёный; `git grep -n -E '"sm"|"sm_m"|w\.sm\b|w\.sm_m\b|Role\.MIXED|"mixed"' -- backend/tests/api/test_tasks.py backend/tests/api/test_subtasks.py backend/tests/api/test_task_permissions.py backend/tests/api/test_board.py backend/tests/api/test_board_move.py backend/tests/api/test_comments.py backend/tests/api/test_personal_tasks.py backend/tests/api/test_project_task_list.py`
  пусто (имя `test_fr23_list_of_other_tasks_comments_not_mixed` — не о роли, не трогать);
  `bash scripts/check.sh` зелёный; `python scripts/task_scope.py R3-T06` → 0.
- **Попытки:** 0

## R3-T07 — Тесты без СМ: задачи и комментарии (domain), справочник, гарды, отображаемый логин (только тесты)
- **Статус:** TODO
- **AC:** AC-13, AC-14, AC-15, AC-25 (справочник без СМ); FR-1, FR-19
- **Файлы:** тесты: `backend/tests/domain/test_tasks_update_delete.py`,
  `backend/tests/domain/test_tasks_create.py`, `backend/tests/domain/test_tasks_move.py`,
  `backend/tests/domain/test_tasks_queries.py`, `backend/tests/domain/test_comments_service.py`,
  `backend/tests/domain/test_directory.py`, `backend/tests/api/test_users_directory.py`,
  `backend/tests/api/test_route_guards.py`, `backend/tests/api/test_login_display.py`
- **Зависит от:** R3-T03, R3-T04
- **Описание:** Только тесты. В domain-тестах: `w.sm` → `w.ba3`, `w.sm_m`/СМ-участник →
  `w.ba2` (если «мир» не содержит СМ-участника, участником делается `ba3` через
  `add_member_row`). Справочник (`test_directory.py`, `test_users_directory.py`): ожидаемые
  роли — `business_admin` и `user`, пользователи `mixed` из данных убираются, параметр
  `("mixed", Role.MIXED)` удаляется. `test_route_guards.py`: `new_user(role="mixed")` →
  `business_admin`, параметр `mixed_one_time_password` удаляется (`ta_one_time_password`
  остаётся). `test_login_display.py` (001/AC-129): учётная запись `Mixed.Admin` заменяется
  ТА `Admin.Main` (создание учётных записей, журнал) и БА (проекты, задачи, комментарии);
  проверки показа логинов сохраняются все. Ложные совпадения со словом `mixed` («mixed case»,
  `json_invalid_mixed`) не трогать.
- **Старые тесты → AC 002:** `domain/test_tasks_update_delete.py`: `test_ac103_sm_member_changes_fields_and_assignee_non_member_403`,
  `test_ac99_sm_member_deletes_foreign_task_non_member_403`, `test_fr20_ba_sm_may_clear_assignee`,
  `test_ac47_mixed_patch_with_forbidden_field_changes_nothing` (→ П с запрещённым полем, тот же
  инвариант «ничего не изменилось»), `test_ac50_update_assignee_recipient_codes`,
  `test_fr13_update_404…`, `test_t75_review_recipient_error_after_concurrent_reassign_is_not_swallowed`,
  `test_ac43_…` (часть СМ) → AC-13, AC-14, AC-15; `domain/test_tasks_create.py`:
  `test_ac56_ba_sm_without_assignee_gets_null`, `test_br1_ba_sm_assign_project_member`,
  `test_ac109_subtask_defaults_by_role`, `test_ac106_subtask_non_member_is_403`,
  `test_p10_4_load_task_context_returns_facts` → AC-13, AC-15; `domain/test_tasks_move.py::test_ac103_sm_member_moves_non_member_403`
  → AC-13, AC-15; `domain/test_tasks_queries.py::test_fr19_permissions_mixed_member_everything` →
  «БА-участник — всё» (дубликат R3-T03 удаляется с пометкой), `test_fr13_*`, `test_d62_*`,
  `test_fr19_permission_flags_match_service_outcomes_matrix`, `test_fr21_subtask_card_create_subtask_false_for_every_role`
  → AC-13; `domain/test_comments_service.py`: `test_ac103_sm_*`, `test_fr23_edit_sm_author_non_member_403`,
  `test_fr23_delete_other_workspace_404`, `test_s11_5_list_permissions_per_actor` → AC-13, AC-15;
  `domain/test_directory.py`, `api/test_users_directory.py` (`mixed` в справочнике) → AC-25;
  `api/test_route_guards.py` → FR-1 (общие гарды, не поведение СМ);
  `api/test_login_display.py::test_ac129_*` → 001/AC-129 по 002 §9.
- **Готово, когда:** `pytest -q backend/tests/domain/test_tasks_update_delete.py backend/tests/domain/test_tasks_create.py backend/tests/domain/test_tasks_move.py backend/tests/domain/test_tasks_queries.py backend/tests/domain/test_comments_service.py backend/tests/domain/test_directory.py backend/tests/api/test_users_directory.py backend/tests/api/test_route_guards.py backend/tests/api/test_login_display.py`
  зелёный; `git grep -n -E 'w\.sm\b|w\.sm_m\b|"sm"|"sm_m"|Role\.MIXED|role="mixed"|"mixed"' -- backend/tests/domain/test_tasks_update_delete.py backend/tests/domain/test_tasks_create.py backend/tests/domain/test_tasks_move.py backend/tests/domain/test_tasks_queries.py backend/tests/domain/test_comments_service.py backend/tests/domain/test_directory.py backend/tests/api/test_users_directory.py backend/tests/api/test_route_guards.py backend/tests/api/test_login_display.py` пусто;
  `bash scripts/check.sh` зелёный; `python scripts/task_scope.py R3-T07` → 0.
- **Попытки:** 0

## R3-T08 — Демо-данные: `demo.ba4` вместо `demo.mixed`
- **Статус:** TODO
- **AC:** AC-28 (*инфра*); FR-22; 001/AC-131 (тест переведён по 002 §9)
- **Файлы:** `backend/app/domain/ops/demo.py`;
  тесты: `backend/tests/cli/test_demo_data.py`, `backend/tests/db/test_login_display_upgrade.py`
- **Зависит от:** —
- **Описание:** По plan §4.7 и D-13: константа `_ALL_PROJECTS_BA: Final = "demo.ba4"`; в `_USERS`
  кортеж `("demo.mixed", "mixed")` заменяется на `("demo.ba4", "business_admin")` **на том же
  месте** (второй элемент); в построении членства `logins = (owner, other_ba, _ALL_PROJECTS_BA, *users)`.
  `load_demo_data` должна читать `_USERS` и `_ALL_PROJECTS_BA` из модуля во время вызова (не
  копировать при импорте), иначе тест AC-30 (R3-T15) не сможет их подменить. Остальное без
  изменений. `cli/test_demo_data.py::test_002_ac28_*`: 13 учётных записей (первый ТА, `demo.ta`,
  `demo.ba1`…`demo.ba4`, `demo.user1`…`demo.user7`); нет `demo.mixed` и роли `mixed`; в событиях
  `user.role_assigned` нет `mixed`; `demo.ba4` — БА, участник обоих проектов, не владелец.
  `db/test_login_display_upgrade.py`: актор для списка учётных записей и журнала — первый ТА
  `admin` вместо `demo.mixed`.
- **Старые тесты → AC 002:** `cli/test_demo_data.py::test_fr49_thirteen_accounts_with_roles`
  (`mixed: 1` → `business_admin: 4`), `::test_fr49_projects_members_owner_row` (`demo.mixed` →
  `demo.ba4`), прочие тесты файла с `demo.mixed` в ожиданиях → AC-28;
  `db/test_login_display_upgrade.py::test_ac131_upgrade_keeps_logins_passwords_data_and_makes_case_variants_taken`
  — актор `admin`; проверки «журнал не изменился», логины и пароли сохраняются → 001/AC-131 по
  002 §9, AC-21.
- **Готово, когда:** `pytest -q backend/tests/cli/test_demo_data.py backend/tests/db/test_login_display_upgrade.py`
  зелёный; `git grep -n mixed -- backend/app/domain/ops/demo.py backend/tests/cli/test_demo_data.py backend/tests/db/test_login_display_upgrade.py`
  находит только отрицательные проверки AC-28 («нет `mixed`»); `bash scripts/check.sh` зелёный;
  `python scripts/task_scope.py R3-T08` → 0.
- **Попытки:** 0

## R3-T09 — Фронтенд: выбор роли из трёх, «Смешанная роль» только в журнале
- **Статус:** TODO
- **AC:** AC-27 (автоматическая часть: выбор роли и журнал); FR-20, FR-21
- **Файлы:** `frontend/src/features/admin/UsersPage.tsx`;
  тесты: `frontend/tests/features/admin/UsersPage.test.tsx`, `frontend/tests/features/admin/helpers.tsx`,
  `frontend/tests/features/admin/AuditPage.test.tsx`
- **Зависит от:** —
- **Описание:** По plan §4.9: `ROLES = ["tech_admin", "business_admin", "user"]`; выбор роли —
  «Без роли» и три роли с прежними названиями. `AuditPage.tsx` и `shared/i18n/ru.ts` **не
  менять** (D-14). Тесты: варианты выбора — `["", "business_admin", "tech_admin", "user"]`;
  сценарий «назначить mixed» → «назначить business_admin»; в `AuditPage.test.tsx` явный тест
  `002_fr20_*`: записи `role_assigned` (новая `mixed`), `role_changed` (`user` → `mixed`),
  `role_removed` (прежняя `mixed`) показывают «Смешанная роль», и в тексте строки нет `mixed`.
- **Старые тесты → AC 002:** `UsersPage.test.tsx` (ожидание опций с `mixed`, сценарий назначения
  `mixed`) → AC-27, FR-21; `admin/helpers.tsx` (комментарий о перечне ролей) — без изменения
  проверок; `AuditPage.test.tsx` — существующие проверки `mixed` сохраняются (FR-20).
- **Готово, когда:** `cd frontend && npm run lint && npm run typecheck && npm test -- tests/features/admin`
  зелёный; `bash scripts/check.sh` зелёный; `python scripts/task_scope.py R3-T09` → 0.
- **Попытки:** 0

## R3-T10 — Фронтенд: владельцы и выбор исполнителя — только БА
- **Статус:** TODO
- **AC:** AC-17 (кандидаты во владельцы), AC-27 (автоматическая часть: элементы управления у БА); FR-9, FR-11, FR-21
- **Файлы:** `frontend/src/features/projects/ProjectPage.tsx`, `frontend/src/features/tasks/TaskList.tsx`,
  `frontend/src/features/tasks/CreateTaskForm.tsx`;
  тесты: `frontend/tests/features/projects/ProjectPage.test.tsx`, `frontend/tests/features/projects/helpers.tsx`,
  `frontend/tests/features/tasks/CreateTaskForm.test.tsx`, `frontend/tests/features/tasks/TaskList.test.tsx`,
  `frontend/tests/features/tasks/helpers.tsx`, `frontend/tests/features/tasks/taskpage-helpers.tsx`,
  `frontend/tests/features/boards/BoardCreate.test.tsx`, `frontend/tests/shared/UserPicker.test.tsx`
- **Зависит от:** —
- **Описание:** По plan §4.9: `OWNER_ROLES = ["business_admin"]` (`ProjectPage.tsx`);
  `canPickAssignee = actorRole === "business_admin"` и комментарий (`TaskList.tsx`); комментарий
  в `CreateTaskForm.tsx`. Видимость управления задаётся `permissions.*` сервера и не меняется. Тест
  `002_fr21_*` закрепляет это: БА, не владелец, с `permissions.manage`/`manage_members` видит
  правку проекта, участников, передачу владения, удаление; с `permissions.edit`/`change_assignee`/`delete`
  — полную правку задачи, смену исполнителя, удаление. После задачи в `frontend/src` и
  `frontend/tests` нет значения `"mixed"` у полей типа `Role` (условие для R3-T11).
- **Старые тесты → AC 002:** `ProjectPage.test.tsx::ac52_candidates_are_unblocked_business_admins_and_mixed_from_members_not_users`
  → кандидаты — незаблокированные участники-БА (фикстура `mixed` → `business_admin`) → AC-17;
  `projects/helpers.tsx` (`M_ME`, `M_BLOCKED_MIXED` → `business_admin`) → AC-17, FR-21;
  `CreateTaskForm.test.tsx::fr20_mixed_role_also_gets_picker` → удалить, заменитель — тест «БА
  получает выбор исполнителя», П — нет (уже есть, FR-9); `TaskList.test.tsx`, `tasks/helpers.tsx`,
  `tasks/taskpage-helpers.tsx` (тип роли без `mixed`) → FR-9; `BoardCreate.test.tsx` (параметр
  `["mixed", BUSINESS]` удалить, `business_admin` остаётся) → FR-9; `shared/UserPicker.test.tsx`
  (фикстура `role: "mixed"` → `business_admin`) → FR-19.
- **Готово, когда:** `cd frontend && npm run lint && npm run typecheck && npm test` зелёный;
  `git grep -n mixed -- frontend/src frontend/tests` находит только `frontend/src/features/admin/AuditPage.tsx`,
  `frontend/src/shared/i18n/ru.ts`, `frontend/src/shared/api/schema.d.ts`,
  `frontend/tests/features/admin/AuditPage.test.tsx`; `bash scripts/check.sh` зелёный;
  `python scripts/task_scope.py R3-T10` → 0.
- **Попытки:** 0

## R3-T11 — Удалить роль `mixed` из домена и контракта API
- **Статус:** TODO
- **AC:** AC-1, AC-24; FR-1, FR-7 (обладатель права — только ТА), FR-18, FR-19, NFR-1
- **Файлы:** `backend/app/domain/access/roles.py`, `backend/app/domain/access/policy.py`,
  `backend/app/domain/projects/queries.py` (+ `backend/app/domain/access/recipients.py`, `backend/app/domain/users/directory.py` — только комментарии «БА, СМ» → «БА»);
  тесты: `backend/tests/factories.py`, `backend/tests/projects_support.py`,
  `backend/tests/projects_api_support.py`, `backend/tests/admin_support.py`,
  `backend/tests/unit/test_role_matrix.py`, `backend/tests/unit/test_policy.py`,
  `backend/tests/unit/test_recipients.py`, `backend/tests/api/test_deps_gates.py`,
  `backend/tests/api/test_sessions.py`, `backend/tests/api/test_admin_roles.py`,
  `backend/tests/api/test_e2e_accounts.py`, `backend/tests/api/test_role_values_002.py` (новый),
  `backend/tests/cli/test_openapi_roles.py` (новый);
  генерируемые: `docs/api/openapi.json`, `frontend/src/shared/api/schema.d.ts`
- **Зависит от:** R3-T04, R3-T05, R3-T06, R3-T07, R3-T08, R3-T09, R3-T10
- **Описание:** По plan §4.1, §4.2: удалить `Role.MIXED` и его строку в `ROLE_CAPABILITIES`;
  `ACCOUNT_ADMIN_ROLES = frozenset({Role.TECH_ADMIN})`; в `policy.py` удалить ветки `MIXED` и
  привести формулы к столбцу «Итог 002» (`can_view_project`, `is_own_project`,
  `can_edit_task_fully`, `can_delete_comment`); в `projects/queries.py::list_projects` —
  `if actor.role is not Role.BUSINESS_ADMIN`. `users/service.py` не трогать. Затем
  `bash scripts/gen-api.sh`: в `docs/api/openapi.json` `components.schemas.Role.enum` —
  ровно `["tech_admin", "business_admin", "user"]`. Тесты: из «миров» (`projects_support.py`,
  `projects_api_support.py`) убрать `sm`, `sm_m`; `factories.ROLES` — три роли;
  `admin_support.py` — убрать действие `role_mixed`, в SQL `active_admin_count` только
  `tech_admin`. `test_role_values_002.py` — AC-24 по шагам spec: `mixed`, `MIXED`, `admin`, `""`
  от `ta1` → 422 `validation_error`, роль `x` — П, журнал без новых записей; от `ba.owner` — 403;
  без сессии — 401. `test_openapi_roles.py` — AC-1: перечень `Role` в каждом поле из AC-1;
  `AuditEntry.details` — строки без `enum`; в `docs/api/openapi.json` нет `"mixed"`.
- **Старые тесты → AC 002:** `unit/test_role_matrix.py::test_br1_mixed_is_union_of_admin_roles_plus_manage_any`
  → удалить (роли нет), заменители `test_002_ac1_*` и проверка «три роли»;
  `::test_ac26_ac39_account_capabilities_only_ta_and_mixed`, `::test_fr69_account_admin_roles_is_tech_admin_and_mixed`,
  `::test_fr8_role_values_are_db_strings`, `::test_actor_*` → только ТА / три значения → AC-3,
  AC-5, FR-1, FR-7; `unit/test_policy.py` (`ROLES` без `MIXED`, таблицы без строк `MIXED`,
  `test_sc20_subtask_requires_membership`) → AC-13, AC-15; `unit/test_recipients.py` (`MIXED` в
  таблице) → AC-17, AC-18; `api/test_deps_gates.py` (`ALL_ROLES`, строки `mixed` в таблице
  возможностей, `test_fr67_*` со сменой на `mixed` → на `business_admin`, параметры `"mixed"`) →
  AC-3, AC-5, 001/AC-76 по 002 §9; `api/test_sessions.py` (`EXPECTED_CAPABILITIES["mixed"]`
  удалить, `test_fr67_me_reflects_role_change_without_relogin` → смена на `business_admin`) →
  FR-19; `api/test_admin_roles.py::test_fr12_every_role_value_can_be_assigned` (~стр. 102,
  параметр `"mixed"`) → параметры — три значения `tech_admin`, `business_admin`, `user` (200),
  `"mixed"` из параметров убрать и добавить отдельную проверку: `PUT …/role` с `"mixed"` → 422
  `validation_error`, роль цели не изменилась → AC-24, FR-1;
  `api/test_e2e_accounts.py::test_ac2_ta_creates_12_users_with_4_roles_each_logs_in_and_gets_role`
  (`ROLES` с `"mixed"`, `ROLES[i % 4]`, `Counter == {r: 3}`) → переименовать в
  `test_ac2_ta_creates_12_users_with_3_roles_…`, 12 пользователей по составу демо (1 ТА, 4 БА —
  как `demo.ba1`…`demo.ba4`, 7 П), `Counter == {"tech_admin": 1, "business_admin": 4, "user": 7}`,
  остальные шаги (вход, роль в ответе, журнал) без изменений → AC-24, FR-1, AC-28.
- **Готово, когда:** `pytest -q backend/tests` зелёный; `bash scripts/gen-api.sh` повторно не
  меняет файлы (`git diff --exit-code docs/api/openapi.json frontend/src/shared/api/schema.d.ts`
  после второго запуска); `cd frontend && npm run typecheck && npm test` зелёный;
  `git grep -n -E 'Role\.MIXED|ACCOUNT_ADMIN_ROLES.*MIXED' -- backend` пусто;
  `git grep -n -E '"sm"|"sm_m"|w\.sm\b|w\.sm_m\b|role="mixed"' -- backend/tests ':!backend/tests/db/test_identity_models.py' ':!backend/tests/db/test_migrations.py'`
  пусто (эти два файла вставляют `mixed` в БД сырым SQL и переводятся в R3-T13; `"mixed"` ещё
  остаётся в `db/test_event_log.py` — история, FR-20 — и в отрицательных проверках
  `test_role_values_002.py` и `cli/test_demo_data.py`); `bash scripts/check.sh` зелёный;
  `python scripts/task_scope.py R3-T11` → 0.
- **Попытки:** 0

## R3-T12 — Тексты API и домена без «СМ»; охранный тест
- **Статус:** TODO
- **AC:** FR-1, FR-21 (название «Смешанная роль» только в журнале), NFR-1
- **Файлы:** `backend/app/api/v1/users.py`, `backend/app/api/v1/projects.py`,
  `backend/app/api/v1/comments.py`, `backend/app/api/v1/schemas/common.py`,
  `backend/app/api/v1/schemas/tasks.py`, `backend/app/domain/tasks/service.py`
  (во всех шести — только docstring и комментарии, код не меняется);
  тесты: `backend/tests/unit/test_no_mixed_role.py` (новый);
  генерируемые: `docs/api/openapi.json`, `frontend/src/shared/api/schema.d.ts`
- **Зависит от:** R3-T11
- **Описание:** Исключение из правила «1–3 файла кода»: правка только текста. В шести файлах
  заменить упоминания СМ по spec 002 §5.2: «БА/СМ/П» → «БА/П», «БА и СМ» → «БА», «СМ-участник»
  → «БА-участник», «участнику-БА/СМ» → «участнику-БА». Затем `bash scripts/gen-api.sh`.
  `test_no_mixed_role.py` (plan D-16): в `backend/app/**/*.py` нет `mixed`, `MIXED`, `\bСМ\b`,
  «смешан» (регистронезависимо); во `frontend/src/**/*.{ts,tsx}` слово `mixed` есть только в
  `features/admin/AuditPage.tsx` и `shared/i18n/ru.ts`; в `docs/api/openapi.json` и
  `frontend/src/shared/api/schema.d.ts` нет `mixed`.
- **Старые тесты → AC 002:** нет.
- **Готово, когда:** `pytest -q backend/tests/unit/test_no_mixed_role.py backend/tests/cli/test_openapi.py backend/tests/infra/test_frontend_api_types.py`
  зелёный; `bash scripts/check.sh` зелёный; `python scripts/task_scope.py R3-T12` → 0.
- **Попытки:** 0

## R3-T13 — Миграция 0006: снятие роли «Смешанная», журнал от «системы», CHECK
- **Статус:** TODO
- **AC:** AC-2, AC-20 (роли, данные, журнал), AC-21, AC-22 (роли и журнал, обе ветки), AC-29; FR-2, FR-13, FR-14, FR-15, FR-16, FR-17
- **Файлы:** `backend/migrations/versions/0006_three_roles.py` (новый), `backend/app/domain/workspaces/models.py`;
  тесты: `backend/tests/upgrade002_support.py` (новый), `backend/tests/db/test_three_roles_upgrade.py` (новый),
  `backend/tests/db/test_identity_models.py`, `backend/tests/db/test_migrations.py`
- **Зависит от:** R3-T08, R3-T11
- **Описание:** Миграция — ровно код plan §4.5 (литералы, D-6; блокировки, D-9; временная
  таблица, обновление ролей, `INSERT … SELECT` в `domain_event` с `ORDER BY`, затем замена CHECK
  через `op.f(_CHECK)`; `downgrade` — CHECK с четырьмя значениями, данные не трогать). Модель —
  plan §4.6. `env.py` не менять. `upgrade002_support.py` — функции из plan §5 (схема D-12;
  сбой — триггеры D-8). `test_three_roles_upgrade.py` (`@pytest.mark.committed`):
  `test_002_ac20_*` — фикстура AC-20; после `upgrade head` роли, данные (владение, членство,
  исполнитель, авторство, блокировка, одноразовый пароль, строки `user_session`) и журнал
  (N + 3: `user.role_removed`, `actor_id IS NULL`, `details = {"role_from": "mixed", "role_to": null}`,
  `in_audit`, одинаковое `occurred_at` в окне `[t0, t1]`, прежние N строк побайтно те же); запись
  миграции совпадает с записью `set_role` по полям из plan §4.5. `test_002_ac21_*` — без `mixed`
  записей нет; повторный `alembic upgrade head` и `run_bootstrap` после AC-20 ничего не меняют.
  `test_002_ac22_*` — обе ветки FR-16. `test_002_ac29_*` — сбой `on="version"` и `on="event"`:
  alembic завершается с ошибкой, `alembic_version` = `0005`, роли `mixed`, журнал N, вставка
  `mixed` проходит; после `remove_failure` повтор даёт результат AC-20.
  `test_identity_models.py::test_002_ac2_*`: `mixed`, `admin` → `23514`; три значения и `NULL` —
  приняты; текст CHECK в метаданных = `{r.value for r in Role}`. `test_migrations.py`: голова —
  `0006`, цепочка `0005 → 0006`; статическая проверка, что `env.py` не включает
  `transaction_per_migration`; downgrade `0005` → CHECK принимает `mixed` → `upgrade head`.
- **Старые тесты → AC 002:** `db/test_identity_models.py::test_fr66_four_roles_are_accepted` →
  три роли (переименовать `…_three_roles_…`), `mixed` — в параметры отклоняемых → AC-2;
  `::test_fr66_second_role_in_same_workspace_is_rejected`, `::test_d5_same_global_user_may_belong_to_another_workspace`
  (`role="mixed"` → `business_admin`, проверки UNIQUE и D-5 те же) → AC-2;
  `::test_t06_metadata_declares_login_and_role_checks` (текст CHECK) → AC-2;
  `db/test_migrations.py::test_t93_migration_0005_file_and_single_head` (`get_heads() == ["0005"]`
  → проверка файла 0005 остаётся, голова — `0006` в новом тесте `test_002_*`) → AC-21;
  `::test_t93_downgrade_0004_drops_column_and_check_keeps_rows_then_upgrade_backfills` (`mixed`
  в данных → `business_admin`, либо вставка `mixed` только в схеме ≤ 0005) → AC-29.
- **Готово, когда:** `pytest -q backend/tests/db/test_three_roles_upgrade.py backend/tests/db/test_identity_models.py backend/tests/db/test_migrations.py backend/tests/db/test_login_display_upgrade.py`
  зелёный; `bash scripts/check.sh` зелёный (включая `alembic upgrade head` + `alembic check`);
  `python scripts/task_scope.py R3-T13` → 0.
- **Попытки:** 0

## R3-T14 — Поведение API после обновления (только тесты)
- **Статус:** TODO
- **AC:** AC-20 (сессия S, вход, 403, смена пароля, `m3`), AC-22 (вход и действия новых ТА, передача PM), AC-23, AC-25, AC-26; FR-11, FR-14, FR-19, FR-20
- **Файлы:** тесты: `backend/tests/db/test_three_roles_after_upgrade.py` (новый)
  (+ `backend/tests/upgrade002_support.py` — только добавить вспомогательные функции)
- **Зависит от:** R3-T13
- **Описание:** Только тесты, `@pytest.mark.committed`, фикстуры через `upgrade002_support.py`
  (D-12). Шаги AC выполняются буквально через HTTP API после `upgrade head`:
  AC-20 — сессия S получает 403 `no_role` на список проектов, выход в S выполняется; вход `m1`
  прежним паролем → роль `null`, далее всё, кроме выхода и смены своего пароля, — 403, смена
  пароля выполняется; `m3` входит с одноразовым паролем, меняет его, далее 403.
  AC-22 — `m1` и `m3` (ТА) входят и создают учётную запись, `m1` получает 403 на список
  проектов; `ba.pm` передаёт PM себе. AC-23 — по шагам spec. AC-25 — ответы входа, `GET /me`,
  списка и карточки учётных записей, участников P, справочника; ни в одном ответе нет строки
  `mixed`. AC-26 — до обновления (в схеме 0005) фабрикой созданы три исторические записи с
  `mixed`; после обновления `ta1` читает журнал постранично (`page_size` меньше числа записей):
  все записи на месте, без пропусков и повторов, значения `mixed` как были.
- **Старые тесты → AC 002:** нет.
- **Готово, когда:** `pytest -q backend/tests/db/test_three_roles_after_upgrade.py` зелёный;
  `git diff --stat -- backend/app backend/migrations` пуст; `bash scripts/check.sh` зелёный;
  `python scripts/task_scope.py R3-T14` → 0.
- **Попытки:** 0

## R3-T15 — Обновление установки с демо-данными (AC-30 *инфра*, только тесты)
- **Статус:** TODO
- **AC:** AC-30 (*инфра*); FR-13, FR-14, FR-15, FR-22
- **Файлы:** тесты: `backend/tests/db/test_three_roles_demo_upgrade.py` (новый)
  (+ `backend/tests/upgrade002_support.py` — только добавить вспомогательные функции)
- **Зависит от:** R3-T08, R3-T13
- **Описание:** Только тесты, `@pytest.mark.committed`. «Предыдущая версия» по plan D-13:
  `downgrade 0005`; `run_bootstrap` (первый ТА); `monkeypatch` в `app.domain.ops.demo`:
  `("demo.ba4", "business_admin")` → `("demo.mixed", "mixed")`, `_ALL_PROJECTS_BA` →
  `"demo.mixed"`; `load_demo_data(seed=1)`. Снимок: N записей журнала, md5 строк `project`,
  `task`, `comment` (как `_snapshot` в `db/test_login_display_upgrade.py`), пароли из
  `demo-passwords.txt`. Обновление — командой оператора `gostracker bootstrap`
  (`app.cli.main.main(["bootstrap"])` в отдельном потоке с окружением тестовой БД, по образцу
  `cli/test_bootstrap.py`). Проверки AC-30: `demo.mixed` без роли и участник обоих проектов;
  роли первого ТА и 11 демо-пользователей прежние; журнал N + 1 (`user.role_removed`, автор
  «система», `demo.mixed`); снимки проектов, задач и комментариев равны; логины в ответах API
  прежние, вход прежними паролями выполняется.
- **Старые тесты → AC 002:** нет.
- **Готово, когда:** `pytest -q backend/tests/db/test_three_roles_demo_upgrade.py` зелёный;
  `git diff --stat -- backend/app backend/migrations` пуст; `bash scripts/check.sh` зелёный;
  `python scripts/task_scope.py R3-T15` → 0.
- **Попытки:** 0

## R3-T16 — ADR-0013 и модель данных
- **Статус:** TODO
- **AC:** NFR-5; FR-2, FR-15 (описание в модели данных)
- **Файлы:** `docs/adr/0013-three-roles.md` (новый), `docs/adr/0003-mixed-role.md`,
  `docs/adr/0004-auth-pilot.md`, `docs/adr/0006-audit-r1.md`, `docs/adr/0012-mvp-task-tracker-first.md`,
  `docs/data-model.md`; тесты: `backend/tests/infra/test_docs_static.py`
- **Зависит от:** R3-T13
- **Описание:** По plan §4.10. ADR-0013 по `docs/adr/TEMPLATE.md` содержит все пункты spec §10
  (отличия 1–3 от ТЗ §4 по spec §5.3; несколько ТА без признака «первичный», Q-1; FR-7 и правила
  параллельных действий; замена владельца любым БА; запись миграции 0006 от «системы» — первое
  обновление, которое пишет в журнал; FR-16 и его последствия, Q-3; откат без восстановления
  ролей; риск Q-5). «Заменяет ADR-0003; уточняет ADR-0004, ADR-0005, ADR-0006, ADR-0009,
  ADR-0012». В ADR-0003 меняется только статус: «заменено ADR-0013 (2026-10-16)». В ADR-0004,
  0006, 0012 добавляется строка «Уточнено ADR-0013 …», исторический текст не меняется.
  ADR-0005 и ADR-0009 **не трогать** (plan §11). `docs/data-model.md` — по plan §4.10. Тесты
  `test_002_nfr5_*`: файл ADR-0013 есть, в нём «ADR-0003», «ТЗ §4», три отличия, «Q-5» или
  «аудит» состава участников, «0006»; в ADR-0003 статус «заменено ADR-0013»; в модели данных у
  роли нет `mixed`, есть строка миграции `0006`.
- **Старые тесты → AC 002:** `infra/test_docs_static.py::test_t93_data_model_documents_login_display_and_migration_0005`
  — ожидание вступления «0001–0005» → «0001–0006», остальные проверки без изменений → NFR-5.
- **Готово, когда:** `pytest -q -m infra_static backend/tests/infra/test_docs_static.py` зелёный;
  `bash scripts/check.sh` зелёный; `python scripts/task_scope.py R3-T16` → 0.
- **Попытки:** 0

## R3-T17 — README и чек-лист приёмки (AC-27 *ручной*)
- **Статус:** TODO
- **AC:** AC-27 (*ручной*: пункт чек-листа); FR-22 (README); FR-8, FR-9 (сценарий демо)
- **Файлы:** `README.md`, `docs/acceptance/mvp-demo.md`; тесты: `backend/tests/infra/test_docs_static.py`
- **Зависит от:** R3-T08, R3-T16
- **Описание:** README (русская и английская части): список демо-учётных записей —
  `demo.ta`, `demo.ba1`…`demo.ba4`, `demo.user1`…`demo.user7` (12); абзац о правах БА в сценарии
  демо переписать по FR-8/FR-9 (БА-участник правит и удаляет любые задачи проекта, БА передаёт
  владение любого проекта, получатель — участник с ролью БА); без «Смешанная роль»/«mixed role».
  `mvp-demo.md`: пункт UF-3 о правах БА переписать так же (на `demo.ba2` — участник, не владелец);
  добавить пункт `- [ ] 002/AC-27: …` со всеми шагами AC-27 на демо-учётных записях
  (`demo.ba4` или `demo.ba2` — участник, `demo.ba3` — не участник «Внедрение трекера»).
  Тесты: `test_002_ac27_*` — в чек-листе есть `- [ ]`-пункт с `002/AC-27` и названиями
  «Смешанная роль», «Без роли»; `test_002_fr22_*` — в README обеих частей есть `demo.ba4` и нет
  `demo.mixed`. Существующие проверки T88 и T99 остаются зелёными.
- **Старые тесты → AC 002:** нет (проверки T88/T99 не меняются).
- **Готово, когда:** `pytest -q -m infra_static backend/tests/infra/test_docs_static.py` зелёный;
  `git grep -n -i -E 'demo\.mixed|Смешанн|mixed role' -- README.md docs/acceptance/mvp-demo.md`
  находит только пункт 002/AC-27 (название в журнале); `bash scripts/check.sh` зелёный;
  `python scripts/task_scope.py R3-T17` → 0.
- **Попытки:** 0

---

## Инфраструктурные и ручные AC (сводка)

| AC | Категория | Где проверяется | Задача |
|---|---|---|---|
| AC-27 | *ручной* | `docs/acceptance/mvp-demo.md`, пункт `002/AC-27`, в браузере при приёмке; автоматические части — vitest | R3-T09, R3-T10, R3-T17 |
| AC-28 | *инфра* | `backend/tests/cli/test_demo_data.py::test_002_ac28_*` (команда оператора `demo-data` против тестовой БД, обычный прогон pytest) | R3-T08 |
| AC-30 | *инфра* | `backend/tests/db/test_three_roles_demo_upgrade.py::test_002_ac30_*` (предыдущее демо по plan D-13, обновление командой `gostracker bootstrap`; Docker не нужен) | R3-T15 |

## Документы, требующие разрешения владельца (не задачи)

Правки по spec §10 для этих файлов перечислены в plan §11 и вносятся только с разрешения
владельца: `docs/adr/0009-permissions-refinement.md`, `docs/glossary.md`,
`docs/open-questions.md`, `docs/adr/0005-project-no-deadline.md` (тоже чужая незакоммиченная
правка, plan §9 П-3), `docs/STATE.md` (отметка о завершении 002). Для `docs/reviews/`,
`backend/tests/infra/test_stack_first_run.py` и `CLAUDE.md` правок не требуется.
