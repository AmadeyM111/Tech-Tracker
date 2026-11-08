# Финальная приёмка фичи 007 «ИИ-агент как участник трекера» — ACCEPT WITH REMARKS

Блокирующих замечаний нет. Ручные AC-37, AC-46, AC-48 и пуш ждут владельца. Ревьюер: reviewer (opus), 2026-10-31, база сравнения `f7f19cf..HEAD` (22 коммита, по коммиту на задачу; совмещены T05+T06, T19+T20, T21+T22, T24+T25).

## Прогоны (по указанию владельца без `scripts/check.sh`, Docker-тестов T27 и стековых тестов web)
| Команда | Результат |
|---|---|
| `DOCKER_HOST=unix:///nonexistent/docker.sock pytest -q -p no:cacheprovider -rs backend/tests` | **4484 passed, 115 skipped, 0 failed**, 8 мин 17 с. Пропуски: 81 — нужен `GT_INFRA_STACK=1`, 30 — Docker недоступен, 4 — замер NFR-2 вне CI (`GT_PERF=1`); CI-смоук AC-48 выполнился |
| `ruff check --no-cache backend`, `ruff format --check backend`, `mypy …/backend/app` | чисто (245 файлов, 98 файлов) |
| `alembic check` / `alembic current` | «No new upgrade operations detected» / `0008 (head)` |
| frontend `lint`, `typecheck`, `npm test`, `build` | 0 / 0 / 55 файлов, 1456 тестов / built; `dist` в git нет |
| `test_api_compat_007` + `test_route_guards` + `test_dependencies_allowlist` | 90 passed |
| `test_docs_static` | 246 passed |
| `bash scripts/gen-api.sh` | `docs/api`, `schema.d.ts` без дифа; `gostracker openapi` ×2 побайтно совпадает |
| стековые тесты web, Docker-тесты T27, `scripts/check.sh` | не выполнялись (решение владельца); компоненты check.sh выполнены по отдельности |

## Мутации (одноразовые копии): убиты 20 из 20
Не проверяется `is_blocked`; первый из двух `Authorization`; откат на cookie при недействительном ключе; `delete_*` в `AGENT_OPERATIONS`; снят гейт `require_agent_scope`; лимит 121; `commit_durably` после разбора 401/429; нет `api_key_id` в событиях комментария/`task.updated`; перенос внутри колонки пишет событие; нет маски `gtk_` в логах; секрет в `details`; `expires_at >= now`; БА по ключу видит все проекты; `can_delete_comment` без проверки ключа; `last_used_at` сверх лимита; блокировка не отзывает ключи; нет `comment.deleted`; вход агента без проверки `is_agent` (в API-файле выжил — у агента случайный пароль; убит доменным тестом `test_007_ac1_agent_with_known_password_cannot_login`).

## Покрытие AC
Все автоматические AC сопоставлены зелёным тестам:
AC-1…AC-3 (`test_agent_accounts_*`), AC-4/AC-5/AC-13…AC-15/AC-17 (`test_api_key_auth_api_007`), AC-6…AC-12 (`test_api_keys_admin_007`, `test_api_keys_service_007`), AC-16/AC-18…AC-21 (`test_agent_reads_007`), AC-22…AC-32/AC-34 (`test_agent_writes_007`), AC-33 (`test_agent_scope_007`, 14 действий и обход всех 42 маршрутов), AC-35/AC-43/AC-49…AC-53/FR-42 (`test_agent_events_007`), AC-36 (`test_agent_flag_007`), AC-38/AC-39 (`test_api_key_leaks_007`, `test_logging`, MCP-тесты), AC-40 (API и доменные), AC-41 (`test_api_key_secret_007`), AC-42…AC-45 (`test_agent_mcp_tools_007`, протокол/транспорт/stdio), AC-47 (`test_api_compat_007`, `test_route_guards` без правок), FR-31/FR-40 (фронтенд-тесты).
**Ручные / вне CI, передаются владельцу:** AC-37 (браузер), AC-46 (Claude Code по `docs/agents.md`), AC-48 (`GT_PERF=1 pytest -q backend/tests/perf/test_api_key_overhead_007.py -s`; тесты делают `DROP SCHEMA` в `*_test` — не запускать параллельно). Каждый — ровно один `- [ ]` в `docs/acceptance/mvp-demo.md`. FR-39 — документ (проверяется AC-46).
З-1 решён владельцем 2026-10-30 (spec v0.3 FR-42, v0.4 Q-11…Q-13).

## AC-47: сверка изменённых существующих тестов
Удалённых и переименованных тестов нет; новых безусловных skip/xfail/only нет; из 56 удалённых строк каждая просмотрена — все правки это дополнения по plan §6.2 и вердиктам ревью (точные списки событий вместо «пусто»; `priority` в whitelist, недопустимое поле → `position`; `api_key_id` и FK `api_key` в перечнях схемы; `is_agent` в точных наборах полей; снимки миграций без новых столбцов; строки новых маршрутов в `test_openapi*.py`; разбивка `test_logging.py::test_access_log_has_no_headers_or_bodies` на два запроса — вынужденное исключение FR-17). Из «Проверены и не меняются» ни один тест не изменён. Зависимости: `package.json`/`package-lock.json` без дифа; `pyproject.toml` — только `[project.scripts] gostracker-mcp`.

## Задачи и попытки
T01 (2), T02 (2: TEST_ISSUE), T03 (1), T04 (1 + снятие PLAN_ISSUE по бюджету noqa), T05+T06 (1 + TEST_ISSUE), T07 (1 + TEST_ISSUE), T08 (1 + TEST_ISSUE), T09 (1 + TEST_ISSUE), T10 (1), T11 (1), T12 (1 + TEST_ISSUE), T13 (1), T14 (1), T15 (1), T16 (1 + правка по ревью), T17 (1), T18 (2: CHANGES_REQUESTED → APPROVE), T19+T20 (1), T21+T22 (1), T23 (1), T24+T25 (2: CHANGES_REQUESTED → исправлено, проверено), T26 (приёмка).

## Замечания (не блокируют)
1. Учёт попыток T01/T02 в `tasks.md` — исправлен оркестратором.
2. Таблица ADR-0020 не содержала п. 28–29 open-items — добавлено.
3. PD-4 в plan пишет `secrets.token_urlsafe(32)`, код — `generate_password()` (20 символов CSPRNG, ~119 бит) — текст plan выровнен.
4. `test_agent_scope_007.py:126-150` закрепляет имена `AGENT_OPERATIONS`, но не пару «метод + путь»; сейчас соответствие верное (проверено вручную) — закрепить тестом на будущее.
5. Косметика: строки «D-55 заменено 007/FR-42» в трёх доменных тестах стоят после первой инструкции (не докстринги); имена `test_ac36_*` без префикса `007_`; `docs/data-model.md:290` «в R1.0 пишется только `user`» неточно (было до фичи).

## Безопасность целиком («глазами атакующего»): дефектов не найдено
Гейт `require_agent_scope` на уровне приложения после `check_origin`, любой `Authorization` = запрос по ключу, вне перечня 403 до обработчика; единый оператор `UPDATE … RETURNING` для всех исходов (одинаковое тело 401); лимит атомарен с немедленным `commit_durably`; выпуск/отзыв/блокировка под `lock_for_account_change`; в БД только SHA-256, секрет один раз в ответе выпуска с `no-store`; в OpenAPI нет `gtk_`, дайджеста, `rate_*`; SQL только через SQLAlchemy; нет TODO/отладочных print; права людей (002/006) не изменились; правило plan §4.1 про `is_agent` соблюдено; откат 0008 безопасен (код 006 читает `action` как `str`; потеря ключей и признака описана в ADR-0020); MCP — только stdlib, без прокси и переадресаций, `http` только loopback, в stderr только имя инструмента и статус.

## Решения по open-items (29)
Ни один пункт не блокирует приёмку.
- **Принято как риск (ADR-0020):** 1 (откат часов — лишний отказ; при желании считать окно новым при `rate_window_start > now`), 2 (лимит раньше состояния учётной записи; через API недостижимо), 3 (битый JSON → 400 вне перечня), 4 (исключение AC-47 для `test_logging.py`), 11, 13, 15, 18, 19.
- **Закрыто:** 8 (исправлено в R7-T18), 17 (информационно), 20 (в spec v0.4 AC-23 все случаи — 422), 27(d) (ADR-0020 существует).
- **Решение владельца (spec v0.5):** 7/10 (`capabilities` в `/me` по ключу — рекомендую принять), 26 (AC-48: «участника P»), 27(a)–(c), закрепить пп. 1–3, 18–19.
- **Отдельные задачи:** 5, 9, 12, 14, 21 (UI: перечитывать `["admin"]` после блокировки и в `catch` выпуска), 22, 23, 24 (`AgentKeys.tsx`, общий форматтер времени), 28 (`test_t93` под «0001–0008»), 29 (`theme.test.ts`: пара `accent`/`surface-2`).
- **Ручные проверки владельцу:** 16, 25 (пункты есть в чек-листе).
- **Исправлено при приёмке:** 6 (текст plan PD-4).

## Что остаётся владельцу
1. Ручные AC-37, AC-46, AC-48 и остальные пункты раздела 7 `docs/acceptance/mvp-demo.md` (`nginx -t`, передача `Authorization` и журналы, схемы инструментов в Claude Code, окно ключа и скринридер, `gostracker-mcp`).
2. Стековые тесты web (`pytest -q -m infra_stack backend/tests/infra/test_web_hardening.py`, с `-k`) и `bash scripts/check.sh` — не выполнялись.
3. `git push` ветки `feat/r1.0-foundation` (22 новых локальных коммита); агенты не пушат.
4. Обновление рабочего стека по ADR-0020 («Порядок обновления»): резервная копия БД, `dc up -d --build --wait`, миграция `0008` при старте; тома `pgdata`/`appdata` не удалять; откат — только по ADR-0020 (с потерей ключей и признака агента).
5. Решения по spec v0.5 (пп. 26, 27(a)–(c), 7/10, 3, принятие рисков 1, 2, 15, 18, 19).
