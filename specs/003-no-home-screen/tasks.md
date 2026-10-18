# Tasks: Без «Главной» — стартовый экран по роли, «Выйти» в боковом меню (spec 003)

Статусы: TODO | IN_PROGRESS | DONE | BLOCKED. Статусы ведёт оркестратор.

## Общие условия для всех задач R4

- Источник истины — `specs/003-no-home-screen/spec.md` v0.2 (дельта к 001 и 002). Интерфейсы
  и решения — `specs/003-no-home-screen/plan.md` (разделы указаны в задачах). Ссылки без
  префикса ведут на 003 (`AC-13` = 003/AC-13), ссылки на другие спецификации пишутся с
  префиксом (`001/FR-10`). Если задача противоречит spec или plan, вернуть `PLAN_ISSUE` и
  ничего не додумывать.
- **Только фронтенд.** Код меняется в `frontend/src`, тесты — в `frontend/tests`. Не трогать:
  `backend/**`, `docs/api/**`, `frontend/src/shared/api/schema.d.ts`, `frontend/package.json`,
  `frontend/package-lock.json` (новых зависимостей нет), `CLAUDE.md`, `docs/STATE.md`,
  `specs/002-three-roles/*`. `specs/001-pilot-r1/*` меняет только R4-T09.
- **Новых файлов в `frontend/src` не создавать** (plan D-7): белый список
  `backend/tests/infra/test_frontend_scaffold.py` их запрещает. Новый код — в существующих
  модулях из поля «Файлы». Новые файлы в `frontend/tests` разрешены.
- Окружение: Node `^22.12 || ^24 || >=26`. Команды выполняются из `frontend/`:
  `npx vitest run <файлы>`, `npm run lint`, `npm run typecheck`. Полный `npx vitest run`
  разрешён и быстрый (около 10–20 с).
- Тесты и фикстуры (`frontend/tests/**`) пишет test-writer, исполнитель их не меняет. Задача
  с пометкой **«только тесты»** не меняет код поставки. Если тест красный на текущем коде,
  это `PLAN_ISSUE`, код молча не правится.
- **Старые тесты (NFR-5).** Тест удаляемого поведения не удаляется и не ослабляется без
  замены. Разрешено (plan §6.2): (а) переписать его на критерий 003 в том же файле, с AC в
  имени (`003_acN_*`) или в комментарии; (б) удалить дубликат нового теста `003_*`, назвав
  удалённый тест в комментарии заменителя. Каждая задача перечисляет свои старые тесты в поле
  «Старые тесты → AC». Ревьюер сверяет это поле с diff.
- Новые тесты называются `003_acN_*`. Фикстуры профилей — plan §5 (`meWith`, `installFetch`
  из `frontend/tests/features/admin/helpers.tsx`). Строки интерфейса берутся только из
  `ru.ts`, в тестах — через `ru[...]`.
- **Рамки файлов.** Менять только файлы из поля «Файлы». Файлы в группе `(+ …)` разрешены,
  только если выполняется указанное там условие. Проверка — `python scripts/task_scope.py R4-Tnn`
  из корня репозитория (выход 0). Перед R4-T01 оркестратор коммитит `spec.md`, `plan.md` и
  `tasks.md` фич 003 и 004 (plan §8, R-5).
- «Проверки фронтенда» = `cd frontend && npm run lint && npm run typecheck && npx vitest run`
  (весь набор зелёный). «Бэкенд не тронут» = `git diff --stat e43d435 -- backend docs/api frontend/src/shared/api/schema.d.ts`
  пуст (plan D-9).
- Линтер `eslint-plugin-react-hooks` 7: без `setState` в теле эффекта и без чтения `ref` при
  рендере (plan §8, R-4). Сканер `tests/shared/i18n.test.ts`: без латиницы в видимых
  атрибутах и тексте JSX, без кириллицы в `src` вне `shared/i18n`.

Порядок и критический путь: R4-T02 → R4-T03 → R4-T04 → R4-T05 → R4-T06 → R4-T07 → R4-T08 →
R4-T09 → R4-T11. R4-T01 выполняется до R4-T04 (лучше первым). R4-T10 можно выполнять
параллельно после R4-T08.

---

## R4-T01 — Правило стартового экрана `startPath` (FR-3)
- **Статус:** DONE
- **AC:** FR-3 (правило для AC-1…AC-3, AC-35, AC-36; на экранах — R4-T04)
- **Файлы:** `frontend/src/app/router.tsx`; тесты: `frontend/tests/app/startPath.test.ts` (новый)
- **Зависит от:** —
- **Описание:** По plan §4.1 добавить в `router.tsx` экспортируемые тип `StartPath` и чистую
  функцию `startPath(profile)`. Порядок: флаг `must_change_password` → `/change-password`;
  `business_access` → `/projects`; `manage_accounts` → `/admin/users`; `view_audit` →
  `/admin/audit`; иначе `/admin/users`. Функцию пока никто не вызывает, поведение
  приложения не меняется. Test-writer: таблица случаев `BA`, `U`, `TA`, `AUD`, `NOCAP`, профиль
  только с `manage_accounts`, профиль с флагом (с возможностями и без). Возможности в
  произвольном порядке, лишние возможности (`crm_read`, `project_manage_any`) на результат не
  влияют.
- **Старые тесты → AC:** нет.
- **Готово, когда:** `cd frontend && npx vitest run tests/app/startPath.test.ts` зелёный;
  проверки фронтенда зелёные; бэкенд не тронут; `python scripts/task_scope.py R4-T01` → 0.
- **Попытки:** 1

## R4-T02 — Боковое меню «Меню» с кнопкой «Выйти» на бизнес-экранах
- **Статус:** DONE
- **AC:** AC-19, AC-22 (`BA` на `/projects`), AC-23, AC-24, AC-25, AC-29 (`BA`), AC-30 (`BA`);
  FR-10, FR-13, NFR-2, NFR-3
- **Файлы:** `frontend/src/app/router.tsx`, `frontend/src/shared/i18n/ru.ts`;
  тесты: `frontend/tests/app/sidebar.test.tsx` (новый)
- **Зависит от:** —
- **Описание:** По plan §4.3 создать в `router.tsx` компонент `Sidebar({ profile })`:
  `div.ui-sidebar` > `nav` с `aria-label={t("app.menu_label")}` и `MenuItems`, затем
  `button[type=button][data-action="logout"]` с `Icon name="logout"` и `t("auth.logout")`,
  затем `ErrorAlert` ошибки выхода. Выход — существующий `useLogout(alert)` без изменений.
  `BusinessScreen` на разрешённом экране показывает `<Sidebar>` вместо
  `<nav className="ui-sidebar">`. `Home` тоже показывает `<Sidebar>` (её `ErrorAlert` и кнопка
  уходят в `Sidebar`). `AdminScreen`, `HomeLink` и экраны отказа в этой задаче не меняются. В
  `ru.ts` добавить `"app.menu_label": "Меню"`.
  Test-writer (`sidebar.test.tsx`): AC-19 для `BA` и `U` на `/projects`,
  `/projects/:id` (карточка 404), `/tasks/:id` (404), `/my-tasks`. AC-22 (`BA`, `/projects`:
  один `POST /api/v1/auth/logout`, путь `/login`, значение-«маяк» из кэша удалено). AC-23
  (401), AC-24 (500 и сеть: путь прежний, одно сообщение, кнопка доступна, повтор шлёт второй
  запрос), AC-25 (отложенный ответ: кнопка `disabled`, второй клик запрос не шлёт). AC-29
  (`getByRole("navigation", { name: "Меню" })`, имя отличается от
  `ru["admin.pagination_label"]`; кнопка `type="button"`). AC-30 для `BA` на `/projects`:
  tabbable-элементы (без `tabindex="-1"` и `disabled`) в порядке документа — ссылки меню,
  «Выйти», первый элемент формы создания проекта.
- **Старые тесты → AC:** нет. `navigation.test.tsx`, `icons.test.tsx`,
  `AuditPage.test.tsx::home_has_typed_logout_button…` (на `/` одна кнопка) остаются зелёными
  без правок. Если нет — `PLAN_ISSUE`.
- **Готово, когда:** `cd frontend && npx vitest run tests/app/sidebar.test.tsx tests/app/navigation.test.tsx tests/app/icons.test.tsx tests/features/admin/AuditPage.test.tsx`
  зелёный; проверки фронтенда зелёные; бэкенд не тронут; `python scripts/task_scope.py R4-T02` → 0.
- **Попытки:** 1 (ревью: 3 круга, правки только тестов)
- **Примечание оркестратора (PLAN_ISSUE снят, 2026-10-18):** AC-30 для `BA` требует, чтобы первой tabbable-ссылкой на бизнес-экране не была «На главную». Поэтому в R4-T02 разрешено убрать `HomeLink` из ветки «разрешённый экран» `BusinessScreen` (без изменения `AdminScreen` для ТА, экранов отказа и самого `HomeLink`). Тесты не меняются.

## R4-T03 — Боковое меню на экранах ТА и экранах отказа; «На главную» убрана
- **Статус:** DONE
- **AC:** AC-20, AC-21, AC-22 (`TA` на `/admin/users`), AC-27, AC-28, AC-29 (`TA`), AC-30 (`TA`),
  AC-16 (ссылки на экранах ТА и экранах отказа); FR-2, FR-11, FR-14
- **Файлы:** `frontend/src/app/router.tsx`;
  тесты: `frontend/tests/app/sidebar.test.tsx`, `frontend/tests/app/home-link.test.tsx`,
  `frontend/tests/app/icons.test.tsx`, `frontend/tests/app/navigation.test.tsx`,
  `frontend/tests/features/admin/AuditPage.test.tsx`
  (+ `frontend/tests/features/admin/UsersPage.test.tsx` — только если проверка перечня кнопок
  экрана требует уточнить контейнер, без ослабления проверок)
- **Зависит от:** R4-T02
- **Описание:** По plan §4.3 ввести `RoleScreen({ insideMain, capability, children })`:
  `SessionGate` → `Landmark shell` → `Sidebar` → содержимое или
  `ErrorAlert(errorMessage("forbidden"))`. Маршруты `/admin/users` (`manage_accounts`),
  `/admin/audit` (`view_audit`) и четыре бизнес-маршрута (`business_access`) перевести на
  `RoleScreen`. Удалить `AdminScreen`, `BusinessScreen` и `HomeLink`. `Home` и маршрут `/`
  пока остаются (R4-T04). Ключ `app.home_link`, стиль `.ui-home-link` и иконку `home` не
  трогать (R4-T07).
  Test-writer: AC-20 (`TA` на обоих экранах ТА: ссылки по возможностям,
  `aria-current="page"` у текущей, переход по ссылке «Журнал аудита» — то же меню). AC-21
  (только `manage_accounts`). AC-22 для `TA`. AC-27 (`TA` на 4 бизнес-путях: путь прежний,
  `alert` forbidden, меню со ссылками ТА и «Выйти», ровно один запрос — `GET /me`). AC-28
  (`BA` и `U` на путях ТА: запросов `/admin/*` нет). AC-29 и AC-30 для `TA` на
  `/admin/users`.
- **Старые тесты → AC:** `tests/app/home-link.test.tsx` (весь файл) переписывается: «ссылки "На
  главную" и `a[href="/"]` нет» на тех же путях и экранах отказа → AC-16, AC-27, AC-28;
  `icons.test.tsx::%s: home link has an icon` → «ссылки меню и "Выйти" с иконками, иконки
  различны» → AC-20, шапка-контракт без «На главную»;
  `navigation.test.tsx::ac_fr10_%s_without_business_access_shows_forbidden` дополняется по
  AC-27 (меню ТА, «Выйти», нет «На главную»; проверка «один запрос» сохраняется);
  `AuditPage.test.tsx`, блок `links from admin screens to home` (`%s_has_link_to_home`) →
  «меню ТА и "Выйти"; `a[href="/"]` нет» → AC-20, AC-16.
- **Готово, когда:** `cd frontend && npx vitest run tests/app/sidebar.test.tsx tests/app/home-link.test.tsx tests/app/icons.test.tsx tests/app/navigation.test.tsx tests/features/admin`
  зелёный; `git grep -n -E "HomeLink|AdminScreen|BusinessScreen" -- frontend/src` пусто;
  проверки фронтенда зелёные; бэкенд не тронут; `python scripts/task_scope.py R4-T03` → 0.
- **Попытки:** 1 (ревью: 2 круга, правки только тестов)

## R4-T04 — «Главная» удалена: `/` и неизвестные пути ведут на стартовый экран
- **Статус:** DONE
- **AC:** AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-8, AC-9, AC-10 (пути и кэш), AC-11,
  AC-12, AC-35, AC-36, AC-26 (стартовые экраны); FR-1, FR-3…FR-9
- **Файлы:** `frontend/src/app/router.tsx`;
  тесты: `frontend/tests/app/start-screen.test.tsx` (новый), `frontend/tests/app/navigation.test.tsx`,
  `frontend/tests/app/icons.test.tsx`, `frontend/tests/app/welcome.test.tsx`,
  `frontend/tests/app/password-modal.test.tsx`, `frontend/tests/features/auth/SessionGate.test.tsx`,
  `frontend/tests/features/admin/AuditPage.test.tsx`, `frontend/tests/features/admin/helpers.tsx`
- **Зависит от:** R4-T01, R4-T03
- **Описание:** По plan §4.2 добавить `StartRedirect({ insideMain })` (`SessionGate` →
  `<Navigate to={startPath(profile)} replace state={location.state} />`) и показывать его на
  `/` и на `path="*"` (не `Navigate` на `/`, plan D-3). `GuestOnly` и ветка «смена не нужна» в
  `ForcedPasswordChange` ведут на `startPath(session.data)` с `replace`. Удалить `Home` и
  `Root`. `LoginPage.tsx`, `ChangePasswordPage.tsx` и `ru.ts` не менять (plan D-2; ключ
  `app.home_title` удаляет R4-T07). Комментарии в `router.tsx` про `"/"` и «home substrate»
  привести в соответствие.
  Test-writer (`start-screen.test.tsx`): AC-1…AC-9, AC-35, AC-36 по шагам spec. AC-5:
  6 фикстур × `/no/such/page`, `/another`, `/projects-x`. AC-8: 500 и сеть на `/`, затем
  «Повторить» с `BA` и с `TA`. AC-9: тип перехода через `useNavigationType`, REPLACE (как
  `renderRecorded` в `password-modal.test.tsx`). AC-3 и AC-35: счётчики запросов. AC-10 и AC-11
  через `AppRoutes` (`POST /api/v1/auth/login` → путь по профилю, `/login` не остался в
  истории, «маяк» кэша удалён). AC-12 (`BA`, `U`, `TA`, `NR`): `/me` перечитан после
  `POST /api/v1/auth/password`, все переходы REPLACE.
- **Старые тесты → AC:** по plan §6.2, строки задачи R4-T04:
  `navigation.test.tsx` (шапка-контракт и 5 тестов на `/`) → AC-1, AC-19, AC-20, AC-21;
  `icons.test.tsx::home: every sidebar link and the logout button…` → `/projects` → AC-19;
  `welcome.test.tsx` (2 теста) → стартовые экраны ролей → AC-26, AC-19;
  `password-modal.test.tsx` (`ac1_success_*`, `ac3_*`, `rv3_*`, `rv4_*`, шапка-контракт) →
  AC-12, AC-7, AC-13, AC-12; `SessionGate.test.tsx` (шапка и 9 тестов) → AC-36, AC-5, AC-6,
  AC-7, AC-12, AC-10, AC-4, AC-8; `AuditPage.test.tsx` (`home_links_follow_capabilities`,
  `home_shows_only_audit_link_with_only_view_audit`,
  `home_has_typed_logout_button_that_logs_out_clears_cache_and_goes_to_login` — кнопка внутри
  `.ui-sidebar`, `t103_home_has_no_change_password_link`) → AC-20, AC-36, AC-35, AC-22, AC-26;
  `admin/helpers.tsx` — текст контракта.
- **Готово, когда:** `cd frontend && npx vitest run tests/app tests/features/auth tests/features/admin`
  зелёный; `git grep -n -E "function (Home|Root)\b|<Navigate to=\"/\"" -- frontend/src/app/router.tsx`
  пусто (кроме `redirectFor(error) ?? "/"` в `ForcedPasswordChange`, plan §4.2); проверки
  фронтенда зелёные; бэкенд не тронут; `python scripts/task_scope.py R4-T04` → 0.
- **Попытки:** 1 (TEST_ISSUE снят; ревью: 2 круга, правки тестов и plan)

## R4-T05 — Фокус на заголовке стартового экрана после входа (`BA`, `U`, `TA`)
- **Статус:** DONE
- **AC:** AC-15, AC-13 (`BA`, `U`, `TA`), AC-10 (состояние перехода); FR-15, FR-16, NFR-3
- **Файлы:** `frontend/src/features/auth/session.ts`, `frontend/src/features/auth/LoginPage.tsx`,
  `frontend/src/features/admin/UsersPage.tsx`;
  тесты: `frontend/tests/app/focus-heading.test.tsx` (новый)
- **Зависит от:** R4-T04
- **Описание:** По plan §4.4 добавить в `session.ts` `FOCUS_HEADING_STATE`,
  `focusHeadingState(state)` и `useFocusHeadingOnArrival(ref)` (эффект один раз после
  монтирования: если `location.state?.focusHeading === true`, то `ref.current?.focus()`).
  `LoginPage`: в ветке «роль есть, флага нет» — `navigate("/", { replace: true, state: FOCUS_HEADING_STATE })`,
  остальные ветки без изменений. `UsersPage`: `<h1 ref={headingRef} tabIndex={-1}>` и хук. При
  обычном переходе по меню фокус не переносится. `ProjectsPage` уже ставит фокус на `h1`, её не
  трогать. `StartRedirect` уже передаёт состояние (R4-T04).
  Test-writer: AC-15 для `BA`, `U`, `TA` через `AppRoutes` (вход → стартовый экран →
  `document.activeElement` — его `h1`, не `body`, `tabindex="-1"`). AC-13 для `BA`, `U`, `TA`
  (принудительная смена → стартовый экран → фокус на `h1`). Переход «Учётные записи» по меню с
  `/admin/audit` фокус на `h1` не ставит.
- **Старые тесты → AC:** нет (`LoginPage.test.tsx` не меняется: путь `/` прежний).
- **Готово, когда:** `cd frontend && npx vitest run tests/app/focus-heading.test.tsx tests/features/auth tests/features/admin/UsersPage.test.tsx`
  зелёный; проверки фронтенда зелёные; бэкенд не тронут; `python scripts/task_scope.py R4-T05` → 0.
- **Попытки:** 1

## R4-T06 — Фокус после смены пароля у пользователя без роли и на «Журнале аудита»
- **Статус:** DONE
- **AC:** AC-13 (`NR`), AC-14, AC-15 (`AUD` — правило FR-16 для стартового экрана журнала); FR-15, FR-16
- **Файлы:** `frontend/src/features/auth/NoRolePage.tsx`, `frontend/src/features/admin/AuditPage.tsx`,
  `frontend/src/app/router.tsx`; тесты: `frontend/tests/app/focus-heading.test.tsx`
- **Зависит от:** R4-T05
- **Описание:** По plan §4.4: `NoRolePage` и `AuditPage` — `<h1 ref tabIndex={-1}>` и
  `useFocusHeadingOnArrival`. В `router.tsx`: `useClientHandlers` хранит `stateRef` текущего
  `location.state` (обновляется вместе с `pathRef`), `onNoRole` переходит на `/no-role` с
  `state: focusHeadingState(stateRef.current)`. Редирект `SessionGate` и `StartRedirect`
  передают `focusHeadingState(location.state)` вместо `location.state`. Остальное
  поведение `NoRolePage` не меняется (FR-17): меню нет, «Выйти» на месте.
  **Примечание по ревью R4-T04 (`reviews/R4-T04-1.md`, желательные 1 и 2; plan §4.2, §4.4, D-12):**
  (1) `GuestOnly` и ветка «смена не нужна» в `ForcedPasswordChange` сейчас передают в
  `<Navigate>` `state={state}` целиком. Заменить на `state={focusHeadingState(state)}`, как в
  `StartRedirect`. (2) Комментарий у `SESSION_FRESH_MS` в `router.tsx` («Errors are never
  "fresh", they are re-asked») уточнить. Свежим не бывает ответ без данных: запрос, у которого
  есть только ошибка, при монтировании повторяется. Свежесть считается от `dataUpdatedAt`
  последнего успешного ответа. Значения `SESSION_FRESH_MS` (5 с) и `useSession(0)` в
  `ForcedPasswordChange` не менять (D-12).
  Test-writer: AC-13 для `NR` (смена пароля → `/no-role` → фокус на «Роль не назначена»).
  AC-14 (401 на смену → `/login`, `console.error` не вызывался). `AUD`: вход →
  `/admin/audit` → фокус на «Журнал аудита». Прямое открытие `/no-role` без смены пароля
  фокус на `h1` не ставит.
- **Старые тесты → AC:** нет.
- **Готово, когда:** `cd frontend && npx vitest run tests/app/focus-heading.test.tsx tests/app/password-modal.test.tsx tests/features/auth tests/features/admin/AuditPage.test.tsx`
  зелёный; проверки фронтенда зелёные; бэкенд не тронут; `python scripts/task_scope.py R4-T06` → 0.
- **Попытки:** 1 (TEST_ISSUE по фикстуре role:null снят)

## R4-T07 — Мёртвый код «Главной»: словарь, стиль ссылки, иконка
- **Статус:** TODO
- **AC:** AC-18 (словарь); NFR-2; plan D-8
- **Файлы:** `frontend/src/shared/i18n/ru.ts`, `frontend/src/shared/ui/ui.css`,
  `frontend/src/shared/ui/Icon.tsx`;
  тесты: `frontend/tests/shared/i18n.test.ts`, `frontend/tests/shared/theme.test.ts`,
  `frontend/tests/shared/typography.test.ts`
- **Зависит от:** R4-T04
- **Описание:** Удалить ключи `app.home_title` и `app.home_link` из `ru.ts` (комментарий в
  шапке словаря при необходимости поправить). Удалить из `ui.css` правила `.ui-home-link`,
  `.ui-home-link:hover`, `.ui-home-link:focus-visible` и упоминание «home link» в комментарии
  `.ui-icon`. Удалить `"home"` из `IconName` и `PATHS` в `Icon.tsx`. Перед удалением
  убедиться, что `git grep -n -E "home_title|home_link|ui-home-link|name=\"home\"" -- frontend/src`
  находит только удаляемые места.
  Test-writer: `i18n.test.ts::003_ac18_*` — среди значений словаря нет «Главная» и «На
  главную», ключей `app.home_title` и `app.home_link` нет, `app.menu_label` = «Меню».
- **Старые тесты → AC:** `theme.test.ts`, блок `T92 .ui-home-link (pill link styled like buttons)`
  → «003: "Выйти" в боковом меню — светлая таблетка» (`button` с `var(--button-bg)`,
  `var(--button-text)`, радиус ≥ 16px; `.ui-sidebar button` с `margin-top: auto`; селектора
  `.ui-home-link` нет) → AC-19, NFR-2; `typography.test.ts`, строка `".ui-home-link": 14` в
  `OLD` удаляется вместе с селектором (проверка «нет `font-size` вне таблицы» остаётся).
- **Готово, когда:** `cd frontend && npx vitest run tests/shared tests/app/icons.test.tsx`
  зелёный; `git grep -n -E "home_title|home_link|ui-home-link" -- frontend/src` пусто;
  проверки фронтенда зелёные; бэкенд не тронут; `python scripts/task_scope.py R4-T07` → 0.
- **Попытки:** 0

## R4-T08 — Сквозные проверки: нет «Главной», «На главную», «Сменить пароль»; экраны без меню прежние (только тесты)
- **Статус:** TODO
- **AC:** AC-16, AC-17, AC-18 (видимые строки), AC-26, AC-32; FR-1, FR-2, FR-12, FR-17
- **Файлы:** тесты: `frontend/tests/app/home-link.test.tsx`
- **Зависит от:** R4-T07
- **Описание:** Только тесты. Дописать в `home-link.test.tsx`: AC-16 — для `BA`, `U`, `TA`
  на каждом из `/projects`, `/projects/:id`, `/tasks/:id`, `/my-tasks`, `/admin/users`,
  `/admin/audit` (с экранами отказа) нет `a[href="/"]`, ссылки «На главную» и текста
  «Главная». AC-17 — `NR` на `/no-role`, `PWD` на `/change-password`, гость на `/login`:
  ссылок на `/` нет. AC-18 — все видимые текстовые узлы этих экранов есть среди значений `ru`
  (динамические данные фикстур исключаются явно). AC-26 — на каждом экране с меню нет
  ссылки или кнопки с именем, содержащим «Сменить пароль», и нет `a[href="/change-password"]`.
  AC-32 — на `/no-role` меню нет (`.ui-sidebar`, `navigation` «Меню»), «Выйти» выполняет выход
  как в AC-22. На `/change-password` «Выйти» внутри окна, подложка `aria-hidden`, ссылок нет.
  Если тест красный — `PLAN_ISSUE`.
- **Старые тесты → AC:** нет (файл уже переписан в R4-T03).
- **Готово, когда:** `cd frontend && npx vitest run tests/app/home-link.test.tsx` зелёный;
  `git diff --stat -- frontend/src` пуст; проверки фронтенда зелёные; бэкенд не тронут;
  `python scripts/task_scope.py R4-T08` → 0.
- **Попытки:** 0
- **Примечание оркестратора (R4-T04-2, желательное 1):** в `start-screen.test.tsx` AC-9 для неизвестных путей добавить проверку отсутствия промежуточного шага `/` (`steps().some(s => s.path === "/")` → false).
- **Примечание оркестратора (R4-T06-1):** добавить тест на ветку ошибки `ForcedPasswordChange` (`/change-password` с `focusHeading`, `/me` отвечает 403 `no_role` → `/no-role`, фокус на h1; мутация M9) и в AC-14 проверку активного элемента (поле логина, не h1).

## R4-T09 — Документы: spec 001 v0.19 и пометки в tasks 001 (T81, T92, T100, T103)
- **Статус:** TODO
- **AC:** spec 003, раздел 10 («Нужные правки», п. 1–2)
- **Файлы:** `specs/001-pilot-r1/spec.md`, `specs/001-pilot-r1/tasks.md`
- **Зависит от:** R4-T08
- **Описание:** В `specs/001-pilot-r1/spec.md`: в строке «Статус» первым указать «v0.19 от
  2026-10-18 — ссылка на дельту `specs/003-no-home-screen/spec.md` v0.2», в «Историю версий»
  перед v0.18 добавить пункт **v0.19 (2026-10-18)**: «Стартовый экран и боковое меню — дельта
  003 (утверждена владельцем 2026-10-18): страницы "Главная" нет; после входа и смены пароля —
  стартовый экран по 003/FR-3; "Выйти" — внизу бокового меню на всех экранах с ролью
  (003/FR-1…FR-17). Номера 001 не менялись; требования 001 текстом не правились». Текст
  требований 001 не менять. В `specs/001-pilot-r1/tasks.md` в задачи T81, T92, T100, T103
  добавить по строке `- **Пересмотрено:** …` по plan §10 (история не переписывается).
  Проверить, что T102 уже помечена как заменённая T103. Если нет, добавить такую же строку
  со ссылкой на 003.
- **Старые тесты → AC:** нет.
- **Готово, когда:** `git diff --stat` затрагивает только два файла; `git diff -- specs/001-pilot-r1/spec.md`
  показывает только строку статуса и новый пункт истории; бэкенд не тронут;
  `python scripts/task_scope.py R4-T09` → 0.
- **Попытки:** 0

## R4-T10 — Документы: пункт ручной проверки 003/AC-31 и сверка подписей ролей
- **Статус:** TODO
- **AC:** AC-31 (*ручной*: пункт чек-листа); NFR-2 (подписи ролей — как в словаре на `e43d435`)
- **Файлы:** `docs/acceptance/mvp-demo.md`
  (+ `README.md` — только если сверка найдёт подпись роли интерфейса, отличную от словаря интерфейса)
- **Зависит от:** R4-T08
- **Описание:** (1) В `docs/acceptance/mvp-demo.md` добавить незакрытый пункт
  `- [ ] 003/AC-31: …` со всеми шагами AC-31 на демо-учётных записях (`demo.ta` — UF-2,
  `demo.ba1` — UF-3; одноразовый пароль — новая учётная запись, созданная `demo.ta`): после
  входа ТА на «Учётных записях», БА на «Списке проектов», фокус виден на заголовке; ТА
  переходит в «Журнал аудита» через боковое меню; выход «Выйти» с клавиатуры (Enter и Space);
  фокус виден на пунктах меню и «Выйти»; после смены одноразового пароля фокус на заголовке
  стартового экрана. Пути в обратных кавычках — только существующие (их проверяет
  `test_t88_internal_links_and_paths_exist`). В пункте не упоминать `UF-3` вместе с
  `demo.ba2`: такие пункты проверяет `test_002_*` по правам БА. (2) Сверка подписей ролей
  (plan §9, П-4): значения `admin.role.tech_admin` («Тех-админ»), `admin.role.business_admin`
  («Бизнес-админ»), `admin.role.user` в `ru.ts` совпадают с подписями ролей **интерфейса** в
  `README.md` и `docs/acceptance/mvp-demo.md` («Техадминистратор» в глоссарии и ADR — термин,
  а не подпись, и не меняется). Расхождения исправить только в этих двух файлах.
  `backend/tests/infra/test_docs_static.py` **не менять** (AC-33). Если для синхронизации
  нужна правка этого теста — `PLAN_ISSUE` (решение владельца).
- **Старые тесты → AC:** нет.
- **Готово, когда:** `source .venv/bin/activate && pytest -q -m infra_static backend/tests/infra/test_docs_static.py`
  зелёный без правок теста; `git grep -n -E "Тех-Админ|Бизнес-Админ" -- README.md docs/acceptance`
  пусто; бэкенд не тронут; `python scripts/task_scope.py R4-T10` → 0.
- **Попытки:** 0

## R4-T11 — Финальная приёмка 003
- **Статус:** TODO
- **AC:** AC-33, AC-34; AC-31 (*ручной* — передаётся владельцу); сверка трассировки plan §6.1 и §6.2
- **Файлы:** нет (только проверки; найденные дефекты — новые задачи R4-Tnn по решению оркестратора)
- **Зависит от:** R4-T01…R4-T10
- **Описание:** Выполнить и приложить к отчёту итог:
  (1) `cd frontend && npm run lint && npm run typecheck && npm test`;
  (2) `bash scripts/check.sh` (тестовая БД — как в `specs/002-three-roles/tasks.md`, «Общие
  условия»: `docker compose -p gostracker-dev -f docker-compose.yml -f deploy/compose.dev.yml up -d db`,
  `TEST_DATABASE_URL=…/tracker_test`; тома не удалять);
  (3) AC-33: `git diff --stat e43d435 -- backend docs/api frontend/src/shared/api/schema.d.ts`
  пуст, `git diff e43d435 -- frontend/package.json` пуст;
  (4) AC-34/NFR-5: для каждого теста из plan §6.2 указать, где он теперь (новое имя или
  заменитель). Удалённых без замены нет;
  (5) `git grep -n -E "Главная|На главную|home_title|home_link|ui-home-link" -- frontend/src`
  пусто; `git grep -n 'to="/"' -- frontend/src` пусто;
  (6) каждый AC из plan §6.1 сопоставлен зелёному тесту (имя теста);
  (7) пункт `003/AC-31` есть в чек-листе. Ручную проверку в Chromium выполняет владелец.
- **Старые тесты → AC:** итоговая сверка (п. 4).
- **Готово, когда:** пп. 1–7 выполнены, отчёт содержит команды и их итог; ручная часть AC-31
  отмечена как ожидающая владельца.
- **Попытки:** 0

---

## Ручные AC (сводка)

| AC | Где проверяется | Задача |
|---|---|---|
| AC-31 | `docs/acceptance/mvp-demo.md`, пункт `003/AC-31`, Chromium + демо-данные, только клавиатура; автоматические части — AC-13, AC-15, AC-19, AC-20, AC-29, AC-30 | R4-T10, R4-T11 |
