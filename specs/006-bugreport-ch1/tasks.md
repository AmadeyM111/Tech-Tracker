# Tasks: Баг-репорт «Ч1»: показ пароля, три приоритета, обязательные поля, подзадачи подряд, прогресс, ссылка на родителя (spec 006)

Статусы: TODO | IN_PROGRESS | DONE | BLOCKED. Статусы ведёт оркестратор.

## Общие условия для всех задач R6

- Источник истины — `specs/006-bugreport-ch1/spec.md` v0.2 (дельта к 001…005). Интерфейсы и
  решения — `specs/006-bugreport-ch1/plan.md` (разделы указаны в задачах). Ссылки без префикса
  ведут на 006 (`AC-12` = 006/AC-12), на другие спецификации — с префиксом (`004/AC-25`).
  Решения плана — `PD-n`, допущения spec — `D-n`. Если задача противоречит spec или plan,
  вернуть `PLAN_ISSUE` и ничего не додумывать.
- **Рамки файлов.** Менять только файлы из поля «Файлы». Проверка:
  `python scripts/task_scope.py R6-Tnn` из корня (выход 0). `docs/api/openapi.json` и
  `frontend/src/shared/api/schema.d.ts` меняются только перегенерацией `bash scripts/gen-api.sh`
  и только в задачах, где это сказано.
- **Новых файлов в `frontend/src` не создавать** (белый список
  `backend/tests/infra/test_frontend_scaffold.py::test_t21_src_files_only_expected`; plan PD-3,
  RK-10). Новые файлы в `frontend/tests` и `backend/tests` разрешены. Новая миграция —
  только `backend/migrations/versions/0007_three_priorities.py`.
- **Не трогать:** `frontend/package.json`, `frontend/package-lock.json`, `backend/pyproject.toml`
  (новых зависимостей нет), `CLAUDE.md`, `AGENTS.md`, `docs/STATE.md`, `docs/brief/**`,
  `specs/006-bugreport-ch1/spec.md`. `specs/001-pilot-r1/spec.md` и
  `specs/004-no-board-create/spec.md` меняет только R6-T16.
- **Строки интерфейса — только из `frontend/src/shared/i18n/ru.ts`** (NFR-2). Ключи — plan §4.10.
- **CSS** (`frontend/src/shared/ui/ui.css`): цвета только `var(--…)`, новых `font-size` нет
  (`tests/shared/theme.test.ts`, `tests/shared/typography.test.ts`).
- **БД.** Деструктивные операции — только в тестовой БД `*_test`. Тома Docker (`pgdata`,
  `appdata`) не удалять. Окружение — AGENTS.md, «Команды»: БД разработки
  `docker compose -p gostracker-dev -f docker-compose.yml -f deploy/compose.dev.yml up -d db`,
  `export TEST_DATABASE_URL=postgresql+asyncpg://tracker:tracker@localhost:5432/tracker_test`.
- **Время в тестах** (NFR-6, plan §5): бэкенд — фикстура `fixed_clock` и `fixed_clock.set(...)`;
  фронтенд — `vi.setSystemTime(...)` и `vi.stubEnv("TZ", "UTC")`. Реальная дата и пояс машины
  не должны влиять на результат.
- **Тесты** пишет test-writer, исполнитель их не меняет. Новые тесты: бэкенд — `test_006_acN_*`,
  фронтенд — `006_acN_*`. Тест снятого поведения переписывается на критерий 006 (AC в имени или
  в комментарии), а не удаляется; assert-ы не ослабляются (NFR-5, plan §6.2). Поле «Старые
  тесты → AC» сверяет ревьюер.
- **Команды.**
  - «Проверки фронтенда» = `cd frontend && npm run lint && npm run typecheck && npx vitest run`.
  - «Проверки бэкенда» = `source .venv/bin/activate && ruff check backend && ruff format --check backend && mypy --config-file backend/pyproject.toml backend/app && pytest -q backend/tests`.
  - «Бэкенд не тронут» = `git diff --stat HEAD -- backend docs/api frontend/src/shared/api/schema.d.ts` пуст.
  - «Фронтенд не тронут» = `git diff --stat HEAD -- frontend/src` пуст (кроме перегенерированного `schema.d.ts`, если задача его меняет).
- **Коммиты** делает оркестратор (без `git push`), по plan §8: R6-T04 + R6-T05 — один коммит,
  R6-T07 + R6-T08 — один коммит, остальные — по одному. R6-T13 не коммитится раньше R6-T10 и
  R6-T11, R6-T14 — раньше R6-T12.

Порядок и критический путь: R6-T01 → R6-T02; R6-T03; R6-T04 → R6-T05; R6-T06 (первые шесть —
независимые, ранний выпуск); затем R6-T07 → R6-T08 → R6-T09 → R6-T10 → R6-T11 → R6-T13 →
R6-T15 → R6-T17. Ветка R6-T10 → R6-T12 → R6-T14 идёт параллельно R6-T11/R6-T13. R6-T16 — после
R6-T14. Задачи, меняющие `TaskPage.tsx` (R6-T03, R6-T05, R6-T08, R6-T12) и
`CreateTaskForm.tsx` (R6-T08…R6-T11), выполнять последовательно.

---

## R6-T01 — `TextField`: кнопка показа пароля (компонент, иконки, стили)
- **Статус:** DONE
- **AC:** AC-3, AC-6 (иконки), AC-9, AC-10 — на уровне компонента; NFR-3 (статически: размер, токены)
- **Файлы:** `frontend/src/shared/ui/TextField.tsx`, `frontend/src/shared/ui/Icon.tsx`, `frontend/src/shared/ui/ui.css`;
  тесты: `frontend/tests/shared/TextField.test.tsx` (новый), `frontend/tests/shared/reveal-css.test.ts` (новый)
- **Зависит от:** —
- **Описание:** По plan §4.4 и PD-17 добавить в `TextField` необязательный проп
  `reveal?: { label; shown; onToggle }`. Только при `type="password"` и заданном `reveal`:
  поле и кнопка в `div.ui-input-row`; кнопка `button[type=button].ui-reveal` сразу после поля,
  `aria-pressed`, `aria-label={reveal.label}`, `disabled` как у поля, первый дочерний —
  `<Icon name={shown ? "eye-off" : "eye"} />`; у поля `type = shown ? "text" : "password"`.
  `autoComplete`, `autoCapitalize`, `spellCheck`, подпись и подсказка от `shown` не зависят.
  Без `reveal` разметка прежняя. В `Icon.tsx` — имена `eye`, `eye-off` (разные рисунки). В
  `ui.css` — `.ui-input-row`, `.ui-input-row input`, `.ui-reveal` (plan §4.4), без цветов и
  `font-size`. Экраны в этой задаче не меняются.
  Test-writer: рендер `TextField` с управляемым `shown` (обёртка с `useState`): нажатие мышью,
  Enter и Space вызывают `onToggle`, `type` меняется, значение сохраняется, фокус на кнопке,
  имя постоянное; `disabled` поля → кнопка `disabled`; атрибуты поля и `aria-describedby`
  подсказки одинаковы в обоих режимах; иконки в двух режимах различаются (`innerHTML` svg);
  без `reveal` кнопки нет. `reveal-css.test.ts`: у `.ui-reveal` `min-width` и `min-height` ≥
  24px, в новых правилах нет цветов вне `var(--…)` и нет `font-size`.
- **Старые тесты → AC:** нет (`create-button.test.ts`, `icons.test.tsx`, `theme.test.ts`,
  `typography.test.ts` должны остаться зелёными без правок).
- **Готово, когда:** `cd frontend && npx vitest run tests/shared tests/app/icons.test.tsx` зелёный;
  проверки фронтенда зелёные; бэкенд не тронут; `python scripts/task_scope.py R6-T01` → 0.
- **Попытки:** 1 (APPROVE)

## R6-T02 — «Глазок» на экране входа и в окне смены пароля
- **Статус:** DONE
- **AC:** AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-8, AC-9, AC-10; FR-1…FR-7, D-6, D-7
- **Файлы:** `frontend/src/features/auth/LoginPage.tsx`, `frontend/src/features/auth/ChangePasswordPage.tsx`,
  `frontend/src/shared/i18n/ru.ts`;
  тесты: `frontend/tests/features/auth/LoginPage.test.tsx`, `frontend/tests/features/auth/ChangePasswordPage.test.tsx`,
  `frontend/tests/app/password-modal.test.tsx`, `frontend/tests/features/admin/UsersPage.test.tsx`,
  `frontend/tests/features/auth/helpers.tsx` (общие помощники pressKey/revealButtons)
  (+ `frontend/tests/app/start-screen.test.tsx`, `frontend/tests/app/welcome.test.tsx`,
  `frontend/tests/shared/i18n.test.ts` — только если тест перечисляет все кнопки экрана или
  ключи словаря: дополнить кнопками показа, не ослабляя)
- **Зависит от:** R6-T01
- **Описание:** По plan §4.4 и PD-17: `LoginPage` — состояние `shown` для «Пароль», проп
  `reveal` с `t("auth.show_password")`; `ChangePasswordPage` — три состояния и ключи
  `auth.show_current_password`, `auth.show_new_password`, `auth.show_confirm_password`. В
  начале каждого `onSubmit` (до проверок) все состояния — `false`. Поле «Логин» без кнопки.
  Ключи и тексты — plan §4.10. Ловушку Tab окна не менять (кнопки уже попадают в селектор).
  Test-writer: AC-1 (ровно одна кнопка у «Пароль», `type=button`, `aria-pressed=false`, у
  «Логин» нет, на экране ровно две кнопки). AC-2 (три кнопки, три разных имени из словаря;
  `/admin/users` у ТА: в создании и сбросе пароля кнопок показа нет). AC-3 на `/login`
  (`Secret-Pass-123`, мышь, Enter, Space). AC-4. AC-5 (нажатия кнопки не шлют вход; при
  показанном пароле Enter в поле — ровно один запрос с паролем). AC-6 (порядок Tab на
  `/login`; в окне — полный круг и Shift+Tab; первый дочерний — `svg[aria-hidden]`). AC-7
  (401 на входе; 422 `invalid_current_password` и `password_too_common` в окне: поля скрыты,
  значения сохранены, сообщение). AC-8 (успешная смена → выход → `/login` скрыт; повторный
  монтаж `/login` — скрыт). AC-9 (задержанный ответ: кнопки `disabled`; в окне — и при выходе).
  AC-10 (атрибуты и подсказка «Не менее 12 символов» при показе; число вызовов `fetch` не
  растёт от нажатий).
- **Старые тесты → AC:** тесты, перечисляющие кнопки `/login` или окна смены пароля, и обход
  Tab в `password-modal.test.tsx` дополняются кнопками показа → AC-1, AC-6 (точное перечисление
  сохраняется, а не заменяется на «не меньше»).
- **Готово, когда:** `cd frontend && npx vitest run tests/features/auth tests/app tests/features/admin tests/shared`
  зелёный; проверки фронтенда зелёные; бэкенд не тронут; `python scripts/task_scope.py R6-T02` → 0.
- **Попытки:** 1 (APPROVE)

## R6-T03 — Ссылка «Родительская задача» в карточке подзадачи
- **Статус:** DONE
- **AC:** AC-47, AC-48, AC-49, AC-50, AC-51; FR-32…FR-37
- **Файлы:** `frontend/src/features/tasks/TaskPage.tsx`, `frontend/src/shared/i18n/ru.ts`;
  тесты: `frontend/tests/features/tasks/ParentLink.test.tsx` (новый),
  `frontend/tests/features/tasks/taskpage-helpers.tsx` (только добавить помощники: карточка
  подзадачи, маршрут `GET /tasks/{parent}`)
- **Зависит от:** —
- **Описание:** По plan §4.8 и PD-1: в `TaskCard` при `task.parent_id !== null` —
  `useQuery({ queryKey: ["tasks", "parent", task.parent_id], queryFn: () => getTask(parentId),
  retry: false, refetchOnWindowFocus: false })`; в `dl.ui-props` сразу после «Проект» — `dt`
  `t("tasks.parent_label")` и `dd[data-field="parent"]` со ссылкой `/tasks/{parent_id}`, текст
  — название родителя или `t("tasks.parent_open")`, пока нет данных или при ошибке. Ошибка этого
  запроса в `ErrorAlert` карточки не попадает. У задачи без родителя строки нет. Новые ключи —
  plan §4.10.
  Test-writer: AC-47 (порядок строк `dt`: «Проект», затем «Родительская задача»; доступное имя
  ссылки «Отчёт за квартал», `href`). AC-48 (клик → путь родителя, активный элемент — `h1`;
  «Назад» → карточка подзадачи; маршрутизатор с историей, как в `create-task-button.test.tsx`).
  AC-49 (задержанный ответ, 500, сеть: «Открыть родительскую задачу», тот же `href`, нет
  `role=alert`, остальная карточка есть). AC-50. AC-51 (тик опроса карточки подзадачи → 404 →
  «Не найдено»; переход на родителя с ответом 404 → «Не найдено»; ни одной ссылки без текста).
- **Старые тесты → AC:** нет (`TaskPage.test.tsx`, `SubtaskList.test.tsx` зелёные без правок;
  при необходимости — только маршрут родителя в `cardRoutes`, RK-8).
- **Готово, когда:** `cd frontend && npx vitest run tests/features/tasks` зелёный; проверки
  фронтенда зелёные; бэкенд не тронут; `python scripts/task_scope.py R6-T03` → 0.
- **Попытки:** 1 (APPROVE; желательное: тест AC-50 не ловит лишний GET /tasks/null при enabled:true, retry без паузы — отложено)

## R6-T04 — Подзадачи подряд: тест воспроизведения (только тесты)
- **Статус:** DONE
- **AC:** AC-36, AC-37 (написание; исполнение — R6-T05); NFR-5
- **Файлы:** тесты: `frontend/tests/features/tasks/SubtaskSequence.test.tsx` (новый)
  (+ `frontend/tests/features/tasks/taskpage-helpers.tsx` — только добавить помощники)
- **Зависит от:** —
- **Описание:** **Только тесты; код поставки не меняется.** В отличие от общего правила,
  красный тест здесь ожидаем: он воспроизводит ошибку п. 6. Test-writer пишет по spec AC-36 и
  AC-37 сценарии на карточке задачи с правом создания подзадач (сеть подменена: каждый
  `POST /tasks/{id}/subtasks` → 201, каждое `GET /tasks/{id}` возвращает накопленные подзадачи):
  AC-36 («Шаг 1» Enter, «Шаг 2» кнопкой, «Шаг 3» Enter; ровно три `POST` с этими названиями;
  три подзадачи; поле пусто и в фокусе после каждого; ни на одном шаге нет `role=alert` и
  текста `errorMessage("validation_error")`). AC-37 — три варианта: тик опроса 15 с между 2-й и
  3-й; перечитывание после создания задержано, следующее название вводится и отправляется до
  его ответа; пользователь с правом правки изменил название задачи и не сохранил (название
  остаётся в поле). Исполнитель (test-writer) запускает тест на текущем коде и прикладывает
  отчёт: какие тесты красные и почему (по сообщению ассерта и при необходимости — по коду
  `SubtaskList.tsx`/`TaskPage.tsx`), с проверкой гипотез plan §9, RK-1. Если ни один тест не
  красный — отчёт `NOT_REPRODUCED` (план Б RK-1), тесты остаются регрессионными.
- **Старые тесты → AC:** нет.
- **Готово, когда:** `cd frontend && npx vitest run tests/features/tasks/SubtaskSequence.test.tsx`
  выполнен, отчёт содержит список красных и зелёных тестов и диагноз (или `NOT_REPRODUCED`);
  `npm run lint && npm run typecheck` зелёные; `git diff --stat HEAD -- frontend/src backend` пуст;
  `python scripts/task_scope.py R6-T04` → 0. Коммит — вместе с R6-T05.
- **Попытки:** 1 (воспроизведено: 4 красных на HEAD)

## R6-T05 — Подзадачи подряд: исправление и сообщения формы подзадачи
- **Статус:** DONE
- **AC:** AC-36, AC-37 (зелёные), AC-38, AC-39, AC-40; FR-26…FR-29, D-8
- **Файлы:** `frontend/src/features/tasks/SubtaskList.tsx`, `frontend/src/features/tasks/TaskPage.tsx`,
  `frontend/src/shared/ui/ErrorAlert.tsx`, `frontend/src/shared/i18n/ru.ts`;
  тесты: `frontend/tests/features/tasks/SubtaskList.test.tsx`, `frontend/tests/features/tasks/taskpage-helpers.tsx`
  (+ `frontend/tests/features/tasks/TaskPage.test.tsx` — только если тест опирался на ошибку
  формы подзадачи в общей области карточки)
- **Зависит от:** R6-T04 (отчёт), R6-T03 (общий файл `TaskPage.tsx`)
- **Описание:** По plan §4.5 (`FieldError`), §4.9 и PD-16, с учётом диагноза R6-T04:
  `ErrorAlert.tsx` — экспорт `FieldError({ id, message })`. `SubtaskList({ task, onCreated })`
  без пропса `alert`: своё сообщение в секции «Подзадачи», поле с `aria-invalid` и
  `aria-describedby`; проверки до отправки (пусто/пробелы, длина > 255) с текстами plan §4.10;
  `busy` — только на время `POST`; после 201 поле пустое, фокус в поле, сообщение снято, затем
  `void onCreated()`; ошибка сервера — `errorMessage(code)` в секции, название сохраняется.
  `TaskPage.tsx` — `SubtaskList` без `alert`. Если диагноз R6-T04 указывает на причину вне
  этого описания — `PLAN_ISSUE` с диагнозом, код не менять наугад.
  Test-writer: AC-38 (`""`, `"   "`: запроса нет, одно `role=alert` внутри
  `section[data-section="subtasks"]`, связка поля, в общей области карточки сообщения нет;
  затем «Шаг» → сообщение исчезло, подзадача создана). AC-39 (256 → сообщение, запроса нет;
  255 → запрос). AC-40 (403 `forbidden`, 422 `subtask_depth_exceeded`, 503 `service_busy`, сеть:
  одно сообщение `errorMessage(code)` в секции, «Шаг» сохранён, повтор шлёт новый запрос;
  задержанный ответ + три отправки → один запрос).
- **Старые тесты → AC:** `SubtaskList.test.tsx`: пустое название → `validation_error` в общей
  области → AC-38; ошибки сервера в общей области → AC-40; контракт `taskpage-helpers.tsx`
  («пустое название → `errorMessage("validation_error")`», «не более одного `role=alert`» для
  формы подзадачи) → FR-27, FR-28 (RK-7).
- **Готово, когда:** `cd frontend && npx vitest run tests/features/tasks` зелёный, включая
  `SubtaskSequence.test.tsx` из R6-T04 без правок; проверки фронтенда зелёные; бэкенд не тронут;
  `python scripts/task_scope.py R6-T05` → 0.
- **Попытки:** 1 (APPROVE совместно с T04; желательное: setTitle("") после 201 стирает уже введённое следующее название — отложено, см. отчёт ревьюера)

## R6-T06 — Прогресс с весами 100/50/0 (бэкенд)
- **Статус:** TODO
- **AC:** AC-43, AC-44, AC-45, AC-46; FR-30, FR-31
- **Файлы:** `backend/app/domain/tasks/progress.py`, `backend/app/domain/tasks/queries.py`,
  `backend/app/domain/boards/service.py`;
  тесты: `backend/tests/unit/test_progress.py`, `backend/tests/api/test_progress_006.py` (новый),
  `backend/tests/api/test_tasks.py`, `frontend/tests/features/tasks/progress-006.test.tsx` (новый)
  (+ `backend/tests/api/test_board.py`, `backend/tests/api/test_board_move.py`,
  `backend/tests/api/test_subtasks.py`, `backend/tests/domain/test_tasks_queries.py`,
  `backend/tests/cli/test_demo_data.py` — только ожидаемые значения прогресса)
- **Зависит от:** —
- **Описание:** По plan §4.3 и PD-10: `progress(*, done, in_work, total)`; `get_task` считает
  `in_work` по статусам `in_progress` и `review`; агрегат Доски добавляет
  `count().filter(status IN ('in_progress','review'))`. API и OpenAPI не меняются. Фронтенд-код
  не меняется (только тесты).
  Test-writer: `test_progress.py` — таблица AC-43 через счётчики и `None` при `total=0`.
  `test_progress_006.py` (подзадачи пишутся напрямую в БД через `mk`): AC-43 — каждая строка
  таблицы в карточке; AC-44 — удаление подзадач (75 → 100 → `null`), без подзадач `null`,
  Доска = карточка для каждой строки; AC-45 API — закрытие родителя с «На проверке» → 200.
  `progress-006.test.tsx`: AC-45 (карточка: «Выполнена» + «На проверке» → смена статуса на
  «Выполнена» показывает предупреждение; все «Выполнена» — нет), AC-46 («66%» в карточке и на
  Доске, `null` → «Нет подзадач»).
- **Старые тесты → AC:** `test_progress.py` (позиционные вызовы) → AC-43;
  `test_tasks.py::test_ac7_progress_floor_deleted_excluded_and_review_not_closed` → AC-43, AC-45
  («На проверке» даёт 50, закрытой не считается); значения в тестах Доски и запросов → AC-43,
  AC-44.
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/unit/test_progress.py backend/tests/api/test_progress_006.py backend/tests/api/test_tasks.py backend/tests/api/test_board.py backend/tests/domain/test_tasks_queries.py`
  зелёный; `cd frontend && npx vitest run tests/features/tasks/progress-006.test.tsx` зелёный;
  проверки бэкенда и фронтенда зелёные; `git diff --stat HEAD -- docs/api frontend/src` пуст;
  `python scripts/task_scope.py R6-T06` → 0.
- **Попытки:** 0

## R6-T07 — Три приоритета: модель, миграция 0007, умолчания, демо, OpenAPI (бэкенд)
- **Статус:** TODO
- **AC:** AC-12, AC-13, AC-14, AC-15, AC-17, AC-18, AC-54; FR-8…FR-11, FR-13; NFR-4
- **Файлы:** `backend/app/domain/tasks/models.py`, `backend/migrations/versions/0007_three_priorities.py` (новый),
  `backend/app/domain/tasks/service.py`, `backend/app/api/v1/schemas/tasks.py`, `backend/app/domain/ops/demo.py`;
  тесты: `backend/tests/api/test_priority_006.py` (новый), `backend/tests/db/test_priority_upgrade_006.py` (новый),
  `backend/tests/factories.py`, `backend/tests/upgrade002_support.py`, `backend/tests/db/test_three_roles_demo_upgrade.py`,
  `backend/tests/db/test_r11_models.py`, `backend/tests/cli/test_demo_data.py`, `backend/tests/api/test_tasks.py`,
  `backend/tests/api/test_subtasks.py`, `backend/tests/domain/test_tasks_create.py`, `backend/tests/domain/test_tasks_update_delete.py`
  (+ `backend/tests/db/test_three_roles_upgrade.py`, `backend/tests/db/test_three_roles_after_upgrade.py`,
  `backend/tests/db/test_login_display_upgrade.py` — только если падают из-за 0007, по plan PD-18)
- **Зависит от:** R6-T06 (общие тестовые файлы)
- **Описание:** Пять файлов кода — минимальная сквозная единица: перечисление приоритета
  используется моделью, схемами, сервисом и демо, и не может поменяться в части из них (plan
  PD-4, PD-19). По plan §4.1: `TaskPriority` `LOW/MEDIUM/HIGH`, CHECK; миграция 0007 по PD-5
  (одна транзакция, блокировка, без `updated_at`, откат `low/medium → base`); умолчание
  `MEDIUM` в `TaskCreate`, `TaskUpdate` (default_factory), `TaskCreateData`, текст ошибки
  `_validate`; `demo.py` — константа `_REGULAR_PRIORITY` вместо `TaskPriority.BASE.value` в
  задачах и подзадачах. Затем `bash scripts/gen-api.sh`. Тестовые помощники — PD-18.
  **Фронтенд после этой задачи не проходит `typecheck` — это ожидаемо; коммит только вместе с
  R6-T08.**
  Test-writer: `test_priority_006.py` (фиксированные часы `CLOCK`, тело `FULL` с описанием и
  сроком, чтобы тесты не зависели от R6-T13): AC-12 (без приоритета → `medium`; `low`, `high`
  сохранены; `base`, `urgent`, `""` → 422, задача не создана; подзадача только с названием →
  `medium`; подзадача с `base` → 422), AC-13, AC-18 (`app.openapi()`: перечисление `TaskPriority`
  = `[low, medium, high]`, `default` у `TaskCreate.priority` = `medium`).
  `test_priority_upgrade_006.py` (`committed`, alembic подпроцессом, plan §5): AC-14 (head →
  `downgrade 0006` → строки `base`/`high`, в т.ч. мягко удалённые, подзадачи; снимок всех
  столбцов → `upgrade head` → `base→medium`, `high→high`, `low` нет, число строк и остальные
  столбцы побайтно, вставка `base`/`normal` → `23514`, записей `domain_event` не прибавилось);
  AC-15 (строки `low/medium/high` → `downgrade 0006` → `base, base, high`, CHECK принимает только
  `base`/`high` → `upgrade head` без ошибок, бывшие `base` → `medium`); AC-54 (сбой
  `install_failure(on="version")` при upgrade и при downgrade → данные и CHECK как до шага,
  версия прежняя; после `remove_failure` шаг проходит). `test_demo_data.py`: AC-17 (только
  `medium`/`high`, число `high` = прежнему при `seed=1`, счётчики 001/FR-49).
- **Старые тесты → AC:** все строки plan §6.2 с задачей R6-T07 (`base` → `medium`, множество
  `TaskPriority`, допустимые/недопустимые значения CHECK, перечисление в OpenAPI → AC-12, AC-14,
  AC-18; помощники 002 → PD-18).
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/api/test_priority_006.py backend/tests/db backend/tests/cli/test_demo_data.py backend/tests/api/test_tasks.py backend/tests/api/test_subtasks.py backend/tests/domain backend/tests/infra/test_frontend_api_types.py`
  зелёный; проверки бэкенда зелёные (весь `pytest -q backend/tests`);
  `env DATABASE_URL=$TEST_DATABASE_URL ENV=test alembic -c backend/alembic.ini check` без
  расхождений; `bash scripts/gen-api.sh` повторно не меняет файлы; `git diff --stat HEAD -- frontend/src`
  показывает только `schema.d.ts`; `python scripts/task_scope.py R6-T07` → 0.
- **Попытки:** 0

## R6-T08 — Три приоритета во фронтенде
- **Статус:** TODO
- **AC:** AC-16; FR-9 (форма), FR-12; NFR-2 (часть AC-52: нет «Обычный» и `tasks.priority.base`)
- **Файлы:** `frontend/src/features/tasks/CreateTaskForm.tsx`, `frontend/src/features/tasks/TaskPage.tsx`,
  `frontend/src/shared/i18n/ru.ts`;
  тесты: `frontend/tests/features/tasks/priority-006.test.tsx` (новый), `frontend/tests/features/tasks/helpers.tsx`,
  `frontend/tests/features/boards/helpers.tsx`, `frontend/tests/features/tasks/taskpage-helpers.tsx`,
  `frontend/tests/features/tasks/CreateTaskForm.test.tsx`, `frontend/tests/features/tasks/TaskPage.test.tsx`,
  `frontend/tests/features/boards/BoardView.test.tsx`
  (+ `frontend/tests/features/tasks/TaskList.test.tsx`, `frontend/tests/features/tasks/CreateTaskDialog.test.tsx`,
  `frontend/tests/app/create-task-button.test.tsx`, `frontend/tests/shared/i18n.test.ts` — только замена `base` на `medium`)
- **Зависит от:** R6-T07
- **Описание:** `PRIORITIES = ["low", "medium", "high"]` в `CreateTaskForm.tsx` и `TaskPage.tsx`;
  умолчание и сброс после создания в форме вкладки — `"medium"`. В `ru.ts` — ключи
  `tasks.priority.low` «Низкий», `tasks.priority.medium` «Средний», `tasks.priority.high`
  «Высокий»; ключ `tasks.priority.base` удалить. Остальное в формах не менять (R6-T10).
  Test-writer: AC-16 (данные с `low`, `medium`, `high`: подписи в списке задач проекта, на
  Доске и в карточке; в форме вкладки и карточке ровно три варианта в порядке FR-8, в форме
  выбран «Средний»; текстов «Обычный» и «Базовый» нет на этих экранах; в словаре нет ключа
  `tasks.priority.base` и значения «Обычный»).
- **Старые тесты → AC:** все строки plan §6.2 с задачей R6-T08 → AC-16.
- **Готово, когда:** проверки фронтенда зелёные; проверки бэкенда зелёные (связка с R6-T07);
  `python scripts/task_scope.py R6-T08` → 0. Коммит R6-T07 + R6-T08 — один.
- **Попытки:** 0

## R6-T09 — Общие правила черновика задачи, участники проекта, пропсы `UserPicker`
- **Статус:** TODO
- **AC:** FR-19 (правила проверки), D-11 — на уровне функций; FR-25 (`listAllMembers`); NFR-3
  (атрибуты поля исполнителя)
- **Файлы:** `frontend/src/features/tasks/CreateTaskForm.tsx`, `frontend/src/features/projects/api.ts`,
  `frontend/src/shared/ui/UserPicker.tsx`, `frontend/src/shared/i18n/ru.ts`;
  тесты: `frontend/tests/features/tasks/draft-rules.test.ts` (новый), `frontend/tests/features/projects/api.test.ts`,
  `frontend/tests/shared/UserPicker.test.tsx`
- **Зависит от:** R6-T08
- **Описание:** По plan §4.5: в `CreateTaskForm.tsx` экспортировать `todayMsk`, `DraftField`,
  `DRAFT_FIELDS`, `DraftErrors`, `taskDraftErrors` (чистые функции; компоненты не менять). В
  `ru.ts` — пять ключей `tasks.error_*` (plan §4.10, строка R6-T09): функция возвращает
  `MessageKey`, и без ключей не пройдёт `typecheck`. В `projects/api.ts` —
  `listAllMembers(projectId)` (страницы по 100 до `has_next`, ошибка — `ApiError`). В
  `UserPicker` — необязательные `required`, `invalid`, `describedBy` → `aria-required`,
  `aria-invalid`, `aria-describedby` у combobox.
  Test-writer: `todayMsk` при `2026-10-19T21:30:00Z` и `TZ=UTC` → `2026-10-20`;
  `2026-10-20T20:59:59Z` → `2026-10-20`; `2026-10-20T21:00:00Z` → `2026-10-21`.
  `taskDraftErrors`: каждый ключ отдельно и вместе; `" \n\t "` — пусто; срок `""` →
  `error_due_required`, вчера → `error_due_past`, сегодня и позже — нет ошибки; `assigneeId`
  `null` → ошибка, `undefined` — не проверяется; отсутствующие ключи не проверяются.
  `listAllMembers`: две страницы, `page_size=100`, порядок; 500 → reject. `UserPicker`: атрибуты
  при пропсах и их отсутствие без пропсов.
- **Старые тесты → AC:** нет.
- **Готово, когда:** `cd frontend && npx vitest run tests/features/tasks/draft-rules.test.ts tests/features/projects tests/shared/UserPicker.test.tsx`
  зелёный; проверки фронтенда зелёные; бэкенд не тронут; `python scripts/task_scope.py R6-T09` → 0.
- **Попытки:** 0

## R6-T10 — Форма вкладки «Задачи»: обязательные поля, умолчания, сообщения у полей
- **Статус:** TODO
- **AC:** AC-28, AC-29, AC-30, AC-31, AC-32 (форма), AC-34 (без регрессии); FR-19, FR-21, FR-25, PD-12, PD-13
- **Файлы:** `frontend/src/features/tasks/CreateTaskForm.tsx`, `frontend/src/features/tasks/TaskList.tsx`,
  `frontend/src/features/projects/ProjectPage.tsx`, `frontend/src/app/router.tsx`,
  `frontend/src/shared/i18n/ru.ts`, `frontend/src/shared/ui/ui.css`;
  тесты: `frontend/tests/features/tasks/CreateTaskForm.test.tsx`, `frontend/tests/features/tasks/TaskList.test.tsx`,
  `frontend/tests/features/projects/ProjectPage.test.tsx`, `frontend/tests/shared/i18n.test.ts`
  (+ `frontend/tests/features/tasks/helpers.tsx`, `frontend/tests/features/projects/helpers.tsx` — только помощники)
- **Зависит от:** R6-T09
- **Описание:** Основной код — `CreateTaskForm` по plan §4.6, PD-12, PD-13. `TaskList.tsx`,
  `ProjectPage.tsx`, `router.tsx` — только проброс `currentUser`/`currentLogin` (по одной-две
  строки; plan PD-14), там же `ProjectPage` заменяет локальную `listAllMembers` импортом из
  `projects/api.ts` (PD-15). В `ru.ts` — ключи plan §4.10 (строка R6-T10). В `ui.css` —
  `.ui-required` (PD-12). Форма продолжает работать со старым сервером: БА всегда шлёт
  `assignee_id`, все шлют описание и срок.
  Test-writer: AC-28 (`BA`, `2026-10-19T21:30:00Z`, `TZ=UTC`: срок `2026-10-20`, выбран `BA`,
  «Средний», пустые название и описание; у четырёх полей видимый `.ui-required` и
  `aria-required="true"`). AC-29 (`U`: нет combobox исполнителя, строка «Исполнитель: <логин>»,
  срок по Москве, «Средний»). AC-30 (пусто → два сообщения, связка, фокус на названии, запроса
  нет; очищенный срок; вчерашний срок; сброс исполнителя; нигде нет
  `errorMessage("validation_error")`). AC-31 (тело `{title:"Отчёт", description:"Собрать данные",
  due_date:"2026-10-20", priority:"medium", assignee_id:<BA>}`, один запрос; выбор `kuznetsov`
  → его id; после 201 — умолчания AC-28). AC-32 (422 `due_date_in_past` → сообщение у срока,
  значения сохранены, после смены срока — новый запрос). `i18n.test.ts`: `due_date_in_past` в
  `API_CODES` и `errorMessage` → «Срок не может быть раньше сегодняшнего дня».
- **Старые тесты → AC:** `CreateTaskForm.test.tsx` — пустые срок/описание по умолчанию,
  «описание и срок не отправляются, если пусты», «исполнитель не выбран у БА → нет ключа»,
  пустое название → `validation_error` в общей области → AC-28, AC-30, AC-31; `TaskList.test.tsx`,
  `ProjectPage.test.tsx` — создание с только названием → тела по AC-31.
- **Готово, когда:** `cd frontend && npx vitest run tests/features/tasks tests/features/projects tests/shared`
  зелёный; проверки фронтенда зелёные; бэкенд не тронут; `python scripts/task_scope.py R6-T10` → 0.
- **Попытки:** 0

## R6-T11 — Диалог «Новая задача» (004): описание, срок, исполнитель
- **Статус:** TODO
- **AC:** AC-32 (диалог), AC-33, AC-34 (диалог); FR-20, FR-21, FR-25; 004/AC-14, AC-22…AC-25, AC-28 в редакции spec 006 §9.2
- **Файлы:** `frontend/src/features/tasks/CreateTaskForm.tsx`, `frontend/src/app/router.tsx`;
  тесты: `frontend/tests/features/tasks/CreateTaskDialog.test.tsx`, `frontend/tests/features/tasks/CreateTaskDialogSubmit.test.tsx`,
  `frontend/tests/features/tasks/create-dialog-helpers.tsx`, `frontend/tests/app/create-task-button.test.tsx`
- **Зависит от:** R6-T10
- **Описание:** По plan §4.7, PD-13…PD-15: новые пропсы `currentUser`, `canPickAssignee`;
  поля «Описание задачи», «Срок выполнения» (умолчание `todayMsk()`), у БА — `UserPicker` по
  участникам выбранного проекта (`listAllMembers`, только для БА и выбранного проекта), у
  «Пользователя» — строка `tasks.assignee_fixed`; поля приоритета нет. Смена проекта →
  исполнитель снова текущий пользователь. Проверка до отправки — `taskDraftErrors` и сообщения у
  полей; «проект не выбран» — прежнее `errorMessage("validation_error")`. Тело без `priority`;
  у БА — `assignee_id`. 422 `due_date_in_past` → у поля срока. `DIALOG_FOCUSABLE` + `textarea`.
  В `router.tsx` (`Sidebar`) — передать пропсы. Остальное поведение 004 не трогать.
  Test-writer: AC-33 целиком (`BA`, `2026-10-19T21:30:00Z`, `TZ=UTC`: поля и обязательность;
  поля приоритета нет; смена проекта → `BA`; пустое описание; пустой и вчерашний срок; выбор
  `kuznetsov` → одно тело с названием, описанием, сроком и его id, без `priority`; `U` — строка
  и тело без `assignee_id`, ответ с исполнителем `U`). AC-32 в диалоге. AC-34 в диалоге
  (`UB`, не участник не предлагаются). Обход Tab по кругу включает описание.
- **Старые тесты → AC:** по spec 006 §9.2: 004/AC-14 (полей описания, срока, исполнителя нет) →
  AC-33; 004/AC-23 (пустое название → `validation_error`) → «Введите название задачи»
  (FR-19); 004/AC-25 (тело ровно `{ "title": "Отчёт" }`) → AC-33; 004/AC-22, AC-28 и прочие
  сценарии «только название» — дополняются описанием и сроком, смысл прежний.
- **Готово, когда:** `cd frontend && npx vitest run tests/features/tasks tests/app` зелёный;
  проверки фронтенда зелёные; бэкенд не тронут; `python scripts/task_scope.py R6-T11` → 0.
- **Попытки:** 0

## R6-T12 — Карточка задачи: нельзя снять исполнителя, срок и описание (FR-23); словарь 006
- **Статус:** TODO
- **AC:** AC-56; AC-52; FR-23 (интерфейс), NFR-2
- **Файлы:** `frontend/src/features/tasks/TaskPage.tsx`, `frontend/src/shared/i18n/ru.ts`;
  тесты: `frontend/tests/features/tasks/TaskPageRules006.test.tsx` (новый), `frontend/tests/features/tasks/TaskPage.test.tsx`,
  `frontend/tests/features/tasks/taskpage-helpers.tsx`, `frontend/tests/shared/i18n.test.ts`
- **Зависит от:** R6-T10 (функции и ключи), R6-T05 (общий файл)
- **Описание:** По plan §4.8 (FR-23) для задачи без родителя: нет `clear-assignee`; при
  сохранении — `taskDraftErrors` только для изменённых описания и срока, сообщения у полей,
  фокус на первое неверное, запроса нет, ввод сохраняется; 422 `due_date_in_past` от PATCH —
  у поля срока, без общего alert. У подзадачи — как раньше. Локальную `listAllMembers` заменить
  импортом (PD-15). В `ru.ts` — правки только если ключа не хватает (иначе файл не трогать).
  Test-writer: AC-56 целиком (системное время `2026-10-20T09:00:00Z`; кнопки сброса нет;
  очищенный срок, `2026-10-19`, описание `"   "` — запросов нет, сообщения и связка; 422
  `due_date_in_past` — у срока; старая задача без срока и описания — один PATCH только с
  названием; подзадача — кнопка сброса есть, очистка срока → `due_date: null`). AC-52
  (`i18n.test.ts::006_ac52_*`: все строки NFR-2 присутствуют с текстами spec, нет «Обычный» и
  `tasks.priority.base`, `errorMessage("due_date_in_past")` ≠ `error.unknown`).
- **Старые тесты → AC:** `TaskPage.test.tsx` — `clear-assignee` и `PATCH {assignee_id: null}`,
  очистка срока → `due_date: null` на задаче верхнего уровня → переносятся на карточку
  подзадачи (AC-56, последний пункт) или заменяются AC-56; контракт `taskpage-helpers.tsx` (кнопка
  сброса «видна, если исполнитель есть») уточняется: только у подзадачи.
- **Готово, когда:** `cd frontend && npx vitest run tests/features/tasks tests/shared` зелёный;
  проверки фронтенда зелёные; бэкенд не тронут; `python scripts/task_scope.py R6-T12` → 0.
- **Попытки:** 0

## R6-T13 — Сервер: обязательные поля при создании задачи, код `due_date_in_past`
- **Статус:** TODO
- **AC:** AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25, AC-41; FR-14…FR-18, FR-24, D-4, D-5
- **Файлы:** `backend/app/domain/tasks/service.py`, `backend/app/core/errors.py`, `backend/app/api/v1/schemas/tasks.py`;
  тесты: `backend/tests/api/test_required_fields_006.py` (новый), `backend/tests/api/test_tasks.py`,
  `backend/tests/api/test_ba_tasks_002.py`, `backend/tests/api/test_soft_delete.py`,
  `backend/tests/api/test_not_found_vs_forbidden.py`, `backend/tests/domain/test_tasks_create.py`,
  `backend/tests/api/test_errors.py`
  (+ `backend/tests/api/test_subtasks.py`, `backend/tests/api/test_task_recipients.py`,
  `backend/tests/api/test_workspace_isolation.py`, `backend/tests/api/test_db_busy_errors.py`,
  `backend/tests/domain/test_tasks_queries.py`, `backend/tests/domain/test_tasks_update_delete.py`,
  `backend/tests/domain/test_auth_service.py`, `backend/tests/cli/test_maintenance.py`,
  `backend/tests/tasks_api_support.py` — только дополнение тел создания обязательными полями и
  фиксированными часами)
- **Зависит от:** R6-T10, R6-T11 (формы уже шлют полные тела), R6-T07
- **Описание:** По plan §4.2, PD-6…PD-9: `ErrorCode.due_date_in_past`;
  `_effective_assignee(..., top_level=...)`; `_check_top_level` и его вызов в `create_task`
  после прав и `_validate`, до `_check_assignee`; `create_subtask` без изменений правил (кроме
  `top_level=False`). Схема `TaskCreate` не меняет поля и `required`; docstring описывает правила
  создания задачи и подзадачи и код `due_date_in_past`. Затем `bash scripts/gen-api.sh`.
  Test-writer (`CLOCK`, `FULL`; фикстуры spec §5 через `make_api_world`): AC-19, AC-20 (`UB`
  → `user_blocked`, `TA` → `recipient_wrong_role`, `U3` → `not_project_member` — коды сверить с
  существующими тестами получателей), AC-21, AC-22, AC-23 (три граничных момента), AC-24
  (`BA3`, `U3`, `TA` с `{title}` → 403; `BA1` в несуществующий проект → 404), AC-25, AC-41 (три
  `POST` подзадач подряд → 201, в карточке три).
- **Старые тесты → AC:** строки plan §6.2 с задачей R6-T13: создание `BA` без исполнителя →
  `null` → AC-19 (исполнитель — `BA`); `BA` с `null` → 201 → AC-20 (422); создание только с
  названием и сроки в прошлом в тестах формата (001/AC-68) → тела дополнены, часы установлены
  так, что срок не в прошлом (spec 9.1, строка AC-6/9/24/61/68); `test_errors.py` — каталог
  кодов дополнен `due_date_in_past`.
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/api/test_required_fields_006.py backend/tests/api backend/tests/domain`
  зелёный; проверки бэкенда зелёные; фронтенд не тронут (кроме перегенерированного `schema.d.ts`,
  изменения только в комментариях); `cd frontend && npm run typecheck` зелёный;
  `python scripts/task_scope.py R6-T13` → 0.
- **Попытки:** 0

## R6-T14 — Сервер: изменение задачи не снимает исполнителя и срок, не очищает описание (FR-23)
- **Статус:** TODO
- **AC:** AC-26, AC-27; FR-22, FR-23 (сервер), Q-2 б)
- **Файлы:** `backend/app/domain/tasks/service.py`, `backend/app/api/v1/schemas/tasks.py`;
  тесты: `backend/tests/api/test_task_update_006.py` (новый), `backend/tests/api/test_tasks.py`,
  `backend/tests/domain/test_tasks_update_delete.py`
  (+ `backend/tests/api/test_ba_tasks_002.py`, `backend/tests/api/test_task_permissions.py`,
  `backend/tests/api/test_reassign_blocked.py`, `backend/tests/api/test_project_members.py`,
  `backend/tests/api/test_personal_tasks.py` — только если тест снимал исполнителя или срок у
  задачи верхнего уровня изменением)
- **Зависит от:** R6-T12, R6-T13
- **Описание:** По plan §4.2 и PD-7: в `_authorize` после `_validate` — `_check_top_level(changed,
  today_msk())`, если `task.parent_id is None`. Проверяются только реально меняющиеся поля
  (`changed`); снятие исполнителя при исключении участника (сервис проектов) не трогать.
  Docstring `TaskUpdate` — правило FR-23 и код `due_date_in_past`; `bash scripts/gen-api.sh`.
  Test-writer: AC-26 (задача и вторая со сроком `2026-10-01` записаны в БД через `mk`: чтение,
  список, Доска — 200 и значения `null`/`""`; смена только статуса или названия — 200, срок не
  меняется). AC-27 целиком (каждое отдельным запросом; совмещённый запрос название + `null`
  срок → 422 и название прежнее; `2026-10-19` → `due_date_in_past`; `2026-10-20`, `2026-10-25`,
  исполнитель `U2`, описание «Другое» → 200; подзадача — снятия и прошлый срок → 200; исключение
  `U1` из проекта → исполнитель снят, затем смена статуса → 200).
- **Старые тесты → AC:** `test_tasks.py::test_patch_null_due_date_and_null_assignee_clear_the_values`
  → проверка переносится на подзадачу + AC-27; `test_ac68_d51_patch_*` с датами в прошлом →
  часы установлены раньше даты или подзадача; доменные тесты снятия в
  `test_tasks_update_delete.py` → AC-27.
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/api/test_task_update_006.py backend/tests/api backend/tests/domain`
  зелёный; проверки бэкенда и фронтенда зелёные; `python scripts/task_scope.py R6-T14` → 0.
- **Попытки:** 0

## R6-T15 — Документы: модель данных, чек-лист приёмки, ADR-0014
- **Статус:** TODO
- **AC:** AC-11, AC-35, AC-42, AC-55 (*ручные*: пункты чек-листа); NFR-1 (документация); plan PD-20
- **Файлы:** `docs/data-model.md`, `docs/acceptance/mvp-demo.md`, `docs/adr/0014-task-rules-006.md` (новый)
- **Зависит от:** R6-T14, R6-T06
- **Описание:** По plan §11: строка `priority` в `docs/data-model.md`; в `mvp-demo.md` — UF-4
  (веса прогресса и «На проверке»), создание задач с обязательными полями (стр. 83–84),
  пункты `- [ ] 006/AC-11` (Chromium, только клавиатура, VoiceOver или NVDA: имя и
  «нажата/не нажата», контраст иконки ≥ 3:1), `006/AC-35` (демо, `demo.ba1`, исполнитель —
  другой участник, задача в его «Моих задачах»), `006/AC-42` (три подзадачи мышью и три
  клавиатурой у БА и у «Пользователя»-исполнителя), `006/AC-55` (пп. 1–8 баг-репорта на чистом
  стенде `docker compose up`). ADR-0014 по `docs/adr/TEMPLATE.md`: контекст (баг-репорт Ч1),
  решение (коды `low/medium/high`, миграция 0007, обязательные поля, FR-23,
  `due_date_in_past`), последствия (ломающие изменения API, внешних клиентов нет, D-1),
  альтернативы (псевдоним `base`, общий `validation_error`). Пути в обратных кавычках — только
  существующие.
- **Старые тесты → AC:** нет.
- **Готово, когда:** `source .venv/bin/activate && pytest -q -m infra_static backend/tests/infra/test_docs_static.py`
  зелёный без правок теста; в чек-листе по одному пункту `006/AC-11`, `006/AC-35`, `006/AC-42`,
  `006/AC-55`; код не тронут; `python scripts/task_scope.py R6-T15` → 0.
- **Попытки:** 0

## R6-T16 — Спецификации 001 (v0.20) и 004 (v0.3)
- **Статус:** TODO
- **AC:** spec 006, раздел 9.1 и 9.2
- **Файлы:** `specs/001-pilot-r1/spec.md`, `specs/004-no-board-create/spec.md`
- **Зависит от:** R6-T14
- **Описание:** В 001 — запись истории версий v0.20 «пп. 1–8 баг-репорта Ч1 — дельта
  006/FR-1…FR-37 (`specs/006-bugreport-ch1/spec.md` v0.2)» и правки мест по таблице 9.1 spec
  006 (FR-18, FR-18a, FR-19, FR-20, FR-22, BR-4, BR-11, Data Model, AC-7, AC-49, AC-56, AC-109,
  пометки OI-14, OI-18, OI-104, OI-19); места с пометкой «Не меняется» / «Без правки» не
  трогать; номера не менять. В 004 — v0.3 «диалог "Новая задача" — дельта 006/FR-20 (решение
  владельца по 006/Q-1 а)» и правки по таблице 9.2 (FR-8, FR-13, FR-14, FR-16, Q-10, AC-14,
  AC-23, AC-25, раздел 6). Тексты брать из spec 006 дословно, где они там даны.
- **Старые тесты → AC:** нет.
- **Готово, когда:** `git diff --stat` затрагивает только эти два файла; каждая строка таблиц
  9.1 и 9.2 с действием «изменить» отражена (сверка ревьюером по таблицам); код не тронут;
  `python scripts/task_scope.py R6-T16` → 0.
- **Попытки:** 0

## R6-T17 — Финальная приёмка 006
- **Статус:** TODO
- **AC:** AC-53; сверка plan §6.1 и §6.2; AC-11, AC-35, AC-42, AC-55 (*ручные* — передаются владельцу)
- **Файлы:** нет (только проверки; дефекты — новые задачи R6-Tnn по решению оркестратора)
- **Зависит от:** R6-T01…R6-T16
- **Описание:** Выполнить и приложить итог:
  (1) `bash scripts/check.sh` (тестовая БД — «Общие условия»; включает `alembic check`, весь
  `pytest`, фронтенд `lint`, `typecheck`, `test`, `build`);
  (2) AC-53: `git diff 96c6d3b -- frontend/package.json frontend/package-lock.json backend/pyproject.toml`
  пуст; `pytest -q backend/tests/arch/test_dependencies_allowlist.py` зелёный;
  (3) NFR-5: для каждого изменённого тестового файла (`git diff --stat 96c6d3b -- backend/tests frontend/tests`)
  — удалённые тесты названы с заменителем (имя), ассерты не ослаблены; сверка со строками plan §6.2;
  (4) каждый автоматический AC из plan §6.1 сопоставлен зелёному тесту (имя);
  (5) `bash scripts/gen-api.sh` не меняет файлы (AC-18);
  (6) `git grep -n -E "\"base\"|priority\.base|Обычный" -- frontend/src backend/app` пусто;
  (7) миграционный цикл AC-54 зелёный в составе `pytest`;
  (8) пункты `006/AC-11`, `006/AC-35`, `006/AC-42`, `006/AC-55` есть в чек-листе; их выполняет
  владелец (отмечаются как ожидающие);
  (9) отчёт R6-T04 (воспроизведено или `NOT_REPRODUCED`) приложен; при `NOT_REPRODUCED` AC-42
  помечен как обязательный ручной пункт перед выпуском.
- **Старые тесты → AC:** итоговая сверка (п. 3).
- **Готово, когда:** пп. 1–9 выполнены, отчёт содержит команды и их итог; ручные AC отмечены как
  ожидающие владельца.
- **Попытки:** 0

---

## Ручные AC (сводка)

| AC | Где проверяется | Задача |
|---|---|---|
| AC-11 | `docs/acceptance/mvp-demo.md`, пункт `006/AC-11`; Chromium, клавиатура, VoiceOver или NVDA | R6-T15, R6-T17 |
| AC-35 | `docs/acceptance/mvp-demo.md`, пункт `006/AC-35`; демо-данные | R6-T15, R6-T17 |
| AC-42 | `docs/acceptance/mvp-demo.md`, пункт `006/AC-42`; Chromium, демо, БА и «Пользователь» | R6-T15, R6-T17 |
| AC-55 | `docs/acceptance/mvp-demo.md`, пункт `006/AC-55`; чистый стенд `docker compose up` | R6-T15, R6-T17 |
