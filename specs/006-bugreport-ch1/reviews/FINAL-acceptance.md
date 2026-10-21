# Финальная приёмка фичи 006 «Баг-репорт Ч1» — ACCEPT WITH REMARKS

Блокирующих замечаний нет. Все автоматические AC spec 006 v0.2 закрыты зелёными тестами. Ручные AC-11, AC-35, AC-42, AC-55 ждут владельца. Ревьюер: reviewer, 2026-10-21 (R6-T17).

## Прогоны
- `bash scripts/check.sh` целиком не запускался: его `pytest` исполняет Docker-тесты (T27, `docker build`/`run`). Проверка шла по частям, Docker скрыт (`DOCKER_HOST` на несуществующий сокет), БД — `tracker_test`.
- ruff check, ruff format (215 файлов), mypy (91 файл): чисто.
- `alembic upgrade head && alembic check` на `tracker_test`: без расхождений.
- `pytest -q backend/tests -m "not infra_stack"`: 3754 passed, 30 skipped (Docker-тесты T27, к 006 не относятся), 81 deselected (infra_stack — их гоняет CI).
- Frontend: lint, typecheck, `npm test` (51 файл, 1383 теста), build — чисто.
- `test_dependencies_allowlist` 7 passed; `git diff 96c6d3b HEAD -- frontend/package.json frontend/package-lock.json backend/pyproject.toml` пуст (AC-53).
- `gen-api.sh` в копии HEAD: `openapi.json` и `schema.d.ts` совпадают побайтно (AC-18).
- Цикл миграции AC-54 (`test_priority_upgrade_006.py`, 3 теста) зелёный в составе pytest.
- R6-T04: `SubtaskSequence.test.tsx` на кодe 96c6d3b — 4 из 4 красные (воспроизведено: `busy` в `SubtaskList` держался до конца `await onCreated()`, фокус уходил на кнопку); на HEAD все зелёные.
- `git grep "base" / priority.base / Обычный` в `frontend/src` и `backend/app`: одно несвязанное совпадение (`backend/app/api/deps.py:51`, докстринг «Обычный запрос»); `base` остаётся только в миграциях 0004/0007 и ADR-0014.

## Покрытие AC
AC-1…AC-10 — `TextField`, `LoginPage`, `ChangePasswordPage`, `password-modal`, `UsersPage` (frontend); AC-12…AC-15, AC-17, AC-18, AC-54 — `test_priority_006.py`, `test_priority_upgrade_006.py`, `test_demo_data.py`; AC-16 — `priority-006.test.tsx`; AC-19…AC-25, AC-41 — `test_required_fields_006.py`; AC-26, AC-27 — `test_task_update_006.py`; AC-28…AC-34 — `CreateTaskForm.test.tsx`, `CreateTaskDialog(.Submit).test.tsx`, `draft-rules.test.ts`; AC-36…AC-40 — `SubtaskSequence.test.tsx`, `SubtaskList.test.tsx`; AC-43…AC-46 — `unit/test_progress.py`, `test_progress_006.py`, `progress-006.test.tsx`; AC-47…AC-51 — `ParentLink.test.tsx`; AC-52 — `i18n.test.ts`; AC-56 — `TaskPageRules006.test.tsx`.
Ручные (ждут владельца, пункты в `docs/acceptance/mvp-demo.md`): AC-11, AC-35, AC-42, AC-55.

## Сверка тестов с 96c6d3b (NFR-5)
Тестовых файлов не удалено (только `A`/`M`). Переименованные или переписанные тесты имеют заменители с теми же или более сильными проверками (создание БА без исполнителя → сам / `null` → 422; снятие исполнителя и срока перенесено на подзадачу; прогресс по таблице AC-43; сообщения формы подзадачи в секции; тела диалога `toStrictEqual`). Отпечатки 002 сравнивают `to_jsonb(t)` с приведением только `base → medium`. Подробная таблица — в отчёте ревьюера R6-T17 (сводка в истории сессии).

## Блокирующие замечания
Нет.

## Замечания и отложенные доработки
| # | Замечание | Серьёзность |
|---|---|---|
| 1 | `SubtaskList.tsx`: после 201 `setTitle("")` стирает название, которое пользователь успел ввести за время POST (поле не блокируется) | средняя |
| 2 | Карточка задачи: порядок фокуса при двух ошибках (описание → срок, а в DOM срок выше); нет `alert.clear()` в `onSave`; нет регрессионного теста опроса | низкая |
| 3 | Имена части тестов без префикса `006_` совпадают с номерами AC из 001/004/005 | низкая |
| 4 | Вернуть проверку 29 февраля в прошлом через подзадачу; доменный тест «подзадача только с названием» | низкая |
| 5 | Тесты формы: нет `vi.stubEnv("TZ","UTC")`, нет тестов «описание без trim» и «снятие старого alert»; `TaskPage.test.tsx` срок 2099-01-15 без заморозки | низкая |
| 6 | Диалог: нет «*» у «Названия задачи»; нет теста на участника без роли; нет статуса ошибки загрузки участников | низкая |
| 7 | Тест AC-50 не ловит лишний `GET /tasks/null`; `retry` без паузы | низкая |
| 8 | Докстринг `TaskUpdate`: уточнить порядок проверок | косметика |
| 9 | Шаблон п.6 в tasks.md R6-T17 ловит несвязанный `deps.py:51` | косметика |
| 10 | `scripts/check.sh` на машине с Docker запускает `docker build/run` (T27); нужен документированный способ запуска без Docker | низкая (процесс) |
| 11 | `CreateTaskForm.tsx`, `onSubmit`: `busy` держится до `await invalidateQueries` | низкая |

## SPEC_ISSUE (не блокирует)
- **001/AC-48** (`specs/001-pilot-r1/spec.md`, ~строки 1273–1275): сценарий «БА создал… задачу без исполнителя» противоречит 006/FR-17 (для задачи верхнего уровня исполнитель обязателен). Таблица 006 §9.1 строку AC-48 не покрывает; тест 001/AC-48 зелёный, потому что создаёт такую задачу напрямую в БД. Предложение: v0.20.1 — «старую задачу без исполнителя (006/FR-22) или подзадачу без исполнителя». Решает владелец.
- **Чек-лист AC-11**: пункт называет только «Показать пароль»; в окне смены пароля имена другие («Показать текущий / новый / повтор нового пароля», D-6). Дописать в чек-лист.

## Ручные проверки владельца
AC-11, AC-35, AC-42 (до выпуска обязательно: тест воспроизвёл вероятную причину, но буквальный симптом из репорта над статусом напрямую не показан), AC-55 — `docs/acceptance/mvp-demo.md`.
