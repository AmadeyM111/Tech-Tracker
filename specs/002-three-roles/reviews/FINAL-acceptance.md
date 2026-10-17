# Финальная приёмка фичи 002 «Три роли» — ACCEPT WITH REMARKS

Блокирующих проблем нет. Код (коммиты 85e362c…c88642a) соответствует spec 002 v0.2 и plan; продуктовый diff прочитан целиком, побочных изменений нет; `mixed` остался только в `AuditPage.tsx:61` и `ru.ts:66` (D-14), в миграции 0006 и в тестах истории. Ревьюер: reviewer, 2026-10-17. Полный backend-pytest и `check.sh` не запускались (указание владельца).

## Прогоны
- Backend, тесты по ролям/миграциям/демо/OpenAPI + `test_docs_static`, `test_frontend_api_types`, `test_api_image_static` (70 файлов): 3118 passed, 0 failed; `db/test_three_roles_*`, `unit/test_no_mixed_role`, `cli/test_openapi*` 69 passed; AC-10 ещё два прогона подряд — passed. ruff, format (209 файлов), mypy (91 файл) чисто; `alembic check` на `tracker_test` — без расхождений, head = 0006.
- Frontend (node v24.22.0): lint, typecheck чисто; `npm test` целиком 34 файла / 839 passed; сборка проходит.
- Обновление копий обеих рабочих БД (`gostracker`, `gostracker-web`): дамп → временные `*_test` → `upgrade head` → повтор → `check`: rc=0, повтор ничего не меняет, проекты/задачи/комментарии/участники/учётные записи побайтно совпадают, сессии сохранены. После проверок `tracker_test` на 0006; временные БД, дампы, копия репозитория удалены; рабочие стеки не менялись.
- Видимость «роль × данные» повторена одноразовым тестом: ТА — 403 на бизнес-данные (BR-2); БА-неучастник видит список и карточку без содержимого; П-неучастник не видит проект; «без роли» — только вход/выход/смена пароля; `manage_accounts`, `view_audit`, `assign_roles` только у ТА; FR-69 держат AC-6…AC-10.

## Покрытие AC (подробная таблица — в вердикте ревьюера; ✔ — Given/When/Then сверены с кодом теста)
AC-1 ✔ `cli/test_openapi_roles`, `unit/test_role_matrix`; AC-2 `db/test_identity_models`, `test_three_roles_upgrade`; AC-3…AC-9 `api/test_tech_admins_002`; AC-10 ✔ `api/test_tech_admin_races_002` (20 повторов × 4 сценария); AC-11/12/16/18/19 `api/test_ba_projects_002`; AC-13/14/15 `api/test_ba_tasks_002`; AC-17 ✔; AC-20/21/22 ✔ `db/test_three_roles_upgrade`, `test_three_roles_after_upgrade`; AC-23/25/26 `test_three_roles_after_upgrade`; AC-24 ✔ `api/test_role_values_002`, `test_admin_roles`; AC-27 — ручной, за владельцем (автоматические проверки пункта чек-листа и vitest `002_fr9/fr20/fr21`); AC-28 `cli/test_demo_data` (инфра); AC-29 ✔ (сбой посреди обновления); AC-30 ✔ `db/test_three_roles_demo_upgrade` (инфра). FR-1…FR-22, NFR-1…NFR-5 покрыты; NFR-4 неприменим. Принятые отступления: время записей миграции проверяется окном (П-4), у `m1` в AC-22 постоянный пароль (П-5), шаг `u2` в AC-14 — на свежей фикстуре (дословно по spec он пуст по D-46), подзадача другому участнику — два шага (UI).

## Желательные замечания (исправить до приёмки владельцем)
1. ADR-0013 и README: для стека `gostracker` команда `dc up -d --build --wait` завершится ошибкой (контейнер `web` не стартует: порт 80 занят `gostracker-web`); использовать `dc up -d --build --wait api` либо оговорить; имя дампа `~/gostracker-001.dump` одно на оба стека — нужны разные имена.
2. `docs/acceptance/mvp-demo.md` (пункт 002/AC-27): шаг 1 требует стек, обновлённый «с демо 001», а такого стека у владельца нет — достаточно любого обновлённого стека с историческими записями `mixed` (в журналах рабочих стеков уже есть: 2 в `gostracker`, 1 в `gostracker-web`), шаги 2–4 — на чистой демо-установке; «число задач» на странице проекта не показывается (только в списке проектов).
3. ADR-0013 «Откат»/«Правила»: для образа 001 писать `dc up -d --build --wait`; дописать, что `dc restart api` не пересобирает образ.
4. Файлы владельца: `docs/open-questions.md` вопрос 13 по существу решён 002/FR-9 и ADR-0013 (колонка «Решение» пуста); `docs/STATE.md` — раздел «Сейчас» устарел (spec v0.15, «T11 в работе»); `specs/002-three-roles/plan.md` — шапка и П-1 всё ещё говорят о статусе DRAFT.
5. Переименовать тесты с устаревшими именами: `domain/test_comments_service.py` `…_cannot_delete_foreign_403`; `domain/test_tasks_queries.py` `…_not_assignee_nothing`; `api/test_ba_tasks_002.py` `…_user_u1_…` (проверяется `u2`).

## Можно отложить
Пробелы тестов низкой серьёзности (AC-11: P в списке у `ba.out`; FR-19 для бывших СМ, ставших ТА, — только ответ входа; коды ошибок не везде; AC-30: снимок без `must_change_password`, нет `login_taken`; `skip_updated` по `user_id`; текстовые тесты ADR и чек-листа ловят не все мутации); mypy по `backend/tests/upgrade002_support.py` (4 ошибки, тесты в проектную проверку не входят); `comments.py:82` docstring «владелец проекта» неточен; уточнить AC-14 при следующей версии spec; решения владельца: R-3 (`project_manage_any` в `GET /me` у БА), R-9 (проверка ролей при старте API); чужие тестовые БД в dev-кластере (`tracker_t78/79/80/93_test`, `tracker_wb_test`).

## Последствия для рабочих стеков (SELECT и обновление копий БД)
`gostracker` (0005): `admin` — ТА, активен; `anton` — БА; `kristina` и `timofey` — `mixed`, активны, у `kristina` одноразовый пароль не сменён. После обновления `kristina` и `timofey` — «без роли», ТА никто не получит (`admin` активен, FR-16 не срабатывает); в журнал +2 записи `user.role_removed` от «системы» (6 → 8). `timofey` — владелец и единственный участник проекта «Lefine», за ним одна открытая задача: `anton` добавляет себя в «Lefine», принимает владение и переназначает задачу, либо `admin` назначает `timofey` роль БА.
`gostracker-web`: `Anton.Surikov` (`mixed`) станет «без роли», журнал 7 → 8; он владелец «AIQarus» и «Lefine»; `Timofey` (БА) — участник обоих и может принять владение, либо `admin` назначает `Anton.Surikov` роль БА (совмещать ТА и БА в одной учётной записи больше нельзя).
Оба образа `api` сейчас собраны из кода 001 (в нём `MIXED`, миграции до 0005): окна R-9 нет, перезапуск контейнеров безопасен.

## Что владельцу сделать вручную (по ADR-0013, из клона на c88642a)
1. Выбрать стек: `dc() { docker compose "$@"; }` (`gostracker`) или `dc() { docker compose -p gostracker-web "$@"; }` (`gostracker-web`).
2. Резервная копия с отдельным именем на каждый стек, проверить размер: `dc exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > ~/<стек>-001.dump`; `ls -l ~/<стек>-001.dump`.
3. Команда 2 ADR (выписать бывших СМ и ТА).
4. Обновить: `gostracker-web` — `dc up -d --build --wait`; `gostracker` — `dc up -d --build --wait api` (порт 80 занят).
5. Команда 3 ADR: версия 0006; по одной записи с `actor_id IS NULL` на каждого бывшего СМ; в `role_now` — `NULL`.
6. Назначить роли бывшим СМ (`admin`) и заменить владельцев проектов (любой БА).
7. Ручная проверка 002/AC-27 (`docs/acceptance/mvp-demo.md`).
8. Откат — только командой 4 ADR; роли `mixed` он не возвращает.

## Не подтверждено
Полный `pytest -q backend/tests` и `bash scripts/check.sh` целиком; инфра-тесты стека (`test_stack_first_run`, `test_api_image_build`, `test_stack_tls`, `test_compose_static`, `test_web_image`); повторный `gen-api.sh` (вместо него — `test_fr44_committed_openapi_json_matches_generation`, `test_frontend_api_types`); `task_scope.py` (даёт 1 из-за чужих правок в дереве); ручная часть AC-27; обновление настоящих стеков.
