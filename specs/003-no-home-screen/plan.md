# Plan: Без «Главной» — стартовый экран по роли, «Выйти» в боковом меню

- **Spec:** ./spec.md v0.2 (APPROVED, утверждена владельцем 2026-10-18)
- **Статус:** DRAFT
- **Правка 2026-10-18:** по ревью `reviews/R4-T04-1.md` добавлены D-12 (свежесть профиля
  `useSession`), R-8 (профиль в кэше до 5 с), обновлены §3, §4.2 и примечание к R4-T06.
- **Правка 2026-10-18:** по ревью `reviews/R4-T06-1.md` в D-6 и §4.4 записано: `onUnauthenticated`
  тоже передаёт `focusHeadingState(stateRef.current)`. Описано, какие переносы состояния
  защитные и тестами не наблюдаются (мутации M6, M7).
- **Правка 2026-10-18:** по финальной приёмке (`reviews/FINAL-acceptance.md`, остаток п. 1 и 3)
  в §9 записаны П-6 (`GuestOnly` и индикатор FR-6) и решения к сведению владельца (фокус при
  «Назад», ошибка выхода на экранах ТА). Поведение кода не меняется.
- **Основа:** код ветки `feat/r1.0-foundation` на коммите `e43d435`; `context.md` этой папки.
  Файлы 001 и 002 этот план не правит, кроме docs-задачи R4-T09 (spec 003, раздел 10).
- **Нумерация:** решения — `D-1…` (снаружи — `003/D-1`), задачи — `R4-T01…`. Новые тесты
  vitest называются `003_acN_*` (так их не спутать с тестами 001 и 004).
- **Порядок фич:** 003, затем 004 (004/Q-7). Боковое меню из этого плана (`Sidebar`, §4.3) —
  точка расширения для кнопки «Задача» (004).

## 1. Подход

Меняется только фронтенд, и в основном один файл — `frontend/src/app/router.tsx`. Правило
стартового экрана (FR-3) — чистая функция `startPath(profile)`. Маршрут `/` и все неизвестные
пути показывают компонент `StartRedirect`: он проверяет сессию (`GET /me`) и делает
`<Navigate replace>` на стартовый экран. Формы входа и смены пароля по-прежнему ведут на `/`:
`/` перечитывает профиль и решает по FR-3 (в ответе входа возможностей нет, NFR-1). Боковое
меню становится общим компонентом `Sidebar` (навигация «Меню» и кнопка «Выйти» внизу) и
показывается на всех экранах с ролью, включая экраны ТА и экраны отказа. Для этого
`AdminScreen`, `BusinessScreen` и `HomeLink` заменяет один `RoleScreen`. Фокус на заголовке
после входа и смены пароля передаётся через состояние перехода роутера `{ focusHeading: true }`.
Состояние сохраняется при перенаправлениях, и целевой экран ставит фокус на свой `h1`.

Работа идёт в четыре этапа. После каждой задачи полный прогон vitest зелёный:
1. Каркас без изменения поведения (R4-T01): `startPath` и unit-тесты.
2. Боковое меню (R4-T02, R4-T03): сначала на бизнес-экранах, затем на экранах ТА и экранах
   отказа. «На главную» исчезает из разметки.
3. Удаление «Главной» (R4-T04): `/` и неизвестные пути перенаправляют. Одновременно
   переписываются тесты, которые открывали `/` (spec, раздел 9). Затем фокус (R4-T05, R4-T06)
   и уборка мёртвого кода (R4-T07).
4. Сквозные проверки, документы и приёмка (R4-T08…R4-T11).

## 2. Решения

| ID | Решение | Выбрано | Отвергнутые альтернативы | Почему |
|---|---|---|---|---|
| D-1 | Где правило FR-3 | Чистая функция `startPath` в `router.tsx` (экспорт для unit-теста) | (а) логика в каждом охраннике; (б) отдельный модуль `app/startPath.ts` | Одно правило для `/`, неизвестных путей, `/login` и `/change-password`. Вариант (б) запрещён тестом `backend/tests/infra/test_frontend_scaffold.py::test_t21_src_files_only_expected` (белый список файлов `frontend/src`); его правка противоречит AC-33 (D-7) |
| D-2 | Куда ведут формы входа и смены пароля | Как сейчас — на `/` (`replace`). `StartRedirect` на `/` перечитывает `GET /me` и ведёт по FR-3 | (а) форма сама запрашивает `/me` и вычисляет путь; (б) решение по ответу входа | (б) невозможно: в ответе входа нет возможностей (NFR-1). (а) повторяет код `SessionGate` (ожидание, ошибки, 401/403) в двух формах. С D-2 `LoginPage.test.tsx` и `ChangePasswordPage.test.tsx` по пути не меняются (spec, раздел 9, «в зависимости от решений plan»). Цена — промежуточный рендер `/` с индикатором проверки сессии, это допускает FR-6 |
| D-3 | Неизвестные пути | `<Route path="*">` показывает `StartRedirect` на месте, без перехода на `/` | Оставить `<Navigate to="/">` | FR-7: при ошибке проверки сессии адрес не меняется. Так меньше записей истории (FR-8) |
| D-4 | Экраны с ролью | Один `RoleScreen(capability)`: `SessionGate` → оболочка `ui-shell` → `Sidebar` → содержимое или `ErrorAlert(forbidden)` | Оставить `AdminScreen`/`BusinessScreen` и добавить меню в каждый | FR-10, FR-11, FR-14 требуют одинаковое меню везде. Один компонент — одна разметка и одни тесты |
| D-5 | Разметка бокового меню | Как у нынешней `Home`: `div.ui-sidebar > nav[aria-label="Меню"] + button[type=button][data-action="logout"]`, затем `ErrorAlert` ошибки выхода | (а) кнопка внутри `nav`; (б) сообщение об ошибке выхода в содержимом экрана | FR-10: «оформлена так же, как сейчас на Главной». Стили `.ui-sidebar button` (прижатие к низу) уже есть. Сообщение — `p[role=alert][tabindex=-1]`: Tab на нём не останавливается, поэтому «Выйти» остаётся последним элементом меню в последовательности Tab (AC-19, AC-30). В содержимом экрана сообщение могло бы дублировать алерты экрана. `data-action="logout"` нужен 004, чтобы прижимать к низу только «Выйти» |
| D-6 | Фокус на заголовке после входа и смены пароля (FR-15, FR-16) | Состояние перехода `FOCUS_HEADING_STATE = { focusHeading: true }`. Его передают `LoginPage` и `ChangePasswordPage` (уже передаёт). `StartRedirect`, редирект `SessionGate` и обработчики клиента `onNoRole` и `onUnauthenticated` переносят его дальше (`focusHeadingState(stateRef.current)`; принятое отклонение R4-T06, `reviews/R4-T06-1.md`). Экраны `UsersPage`, `AuditPage`, `NoRolePage` ставят фокус на `h1` хуком `useFocusHeadingOnArrival`. `ProjectsPage` и так ставит фокус на заголовок при каждом открытии | (а) фокус на `h1` при каждом открытии всех экранов; (б) флаг на уровне модуля | (а) меняет поведение «Роль не назначена» вне FR-15 (FR-17, раздел 6 spec) и экранов ТА при переходе по меню. (б) — общее состояние между рендерами и тестами. Перенос через `onNoRole` обязателен: при `403 no_role` клиент (`client.ts`, `redirectOnce`) переходит на `/no-role` раньше, чем `SessionGate` отрисует `<Navigate>` (§4.4). То же при 401 (`onUnauthenticated`) и 403 `password_change_required` (`onPasswordChangeRequired`). Поэтому перенос состояния в `<Navigate>` `SessionGate` защитный и тестами напрямую не наблюдается (мутации M6, M7 в `reviews/R4-T06-1.md`) |
| D-7 | Новые файлы в `frontend/src` | Не создаются. Новый код — в существующих модулях (`router.tsx`, `features/auth/session.ts`) | Новые модули и строка в белом списке `test_frontend_scaffold.py` | AC-33: в `backend/` изменений нет, тесты бэкенда не меняются. Новые файлы тестов в `frontend/tests` разрешены |
| D-8 | Мёртвый код | Удалить `Home`, `Root`, `HomeLink`, ключи `app.home_title`, `app.home_link`, правила `.ui-home-link` (3 блока), иконку `home` | Оставить неиспользуемым | NFR-2 (строк нет в словаре), чистота кода. Тесты `theme.test.ts` (блок T92) и `typography.test.ts` (строка `.ui-home-link`) переписываются вместе со стилем |
| D-9 | Основа сравнения для AC-33 | Коммит `e43d435` (начало фичи), а не `main` | `main` | Ветка `feat/r1.0-foundation` уже отличается от `main` всем бэкендом 001/002 (`git diff --stat main -- backend` — 217 файлов). Буквальное сравнение с `main` невыполнимо (§9, П-1) |
| D-10 | Старые тесты удаляемого поведения (NFR-5) | Переписываются в тот же файл и проверяют критерий 003, в имени или комментарии указан AC. Удаление — только дубликата нового теста, с названием удалённого теста в комментарии заменителя | Удалить файлы `home-link.test.tsx`, `welcome.test.tsx` | NFR-5, CLAUDE.md. Таблица §6.2 |
| D-11 | Индикатор при перенаправлении | `StartRedirect` пока ждёт `/me`, показывает только `p[role=status]` («Проверка сессии…»), как сейчас `SessionGate` | — | FR-6, FR-9: ни данных, ни запросов разделов |
| D-12 | Свежесть профиля в кэше (принятое отклонение по итогам R4-T04, ревью `reviews/R4-T04-1.md`) | `useSession(staleTime = SESSION_FRESH_MS)`, `SESSION_FRESH_MS = 5_000` (5 с) в `router.tsx`. `SessionGate`, `GuestOnly`, `NeedsSession` берут значение по умолчанию. `ForcedPasswordChange` вызывает `useSession(0)` и решает только по ответу, полученному после монтирования (флаг `fresh`) | (а) `staleTime: 0` везде, как было до R4-T04; (б) передавать профиль из `StartRedirect` в целевой экран через `state` перехода; (в) `staleTime: Infinity` с ручной инвалидацией | После `StartRedirect` (`SessionGate` → `<Navigate>`) целевой экран монтирует свой `useQuery` с тем же ключом. При (а) уходит второй `GET /me`, а AC-36 требует «ровно один сетевой запрос» (так же AC-3, AC-35 по счётчикам). (б) — профиль в истории браузера и второй источник истины рядом с кэшем. (в) — устаревший профиль живёт до перезагрузки, если пропущена инвалидация. 5 с перекрывают цепочку переходов и не держат профиль долго (R-8). `ForcedPasswordChange` читает профиль заново: на `/change-password` попадают по 403 `password_change_required` (`onPasswordChangeRequired`), и в кэше может лежать «свежий» профиль без флага. По нему экран увёл бы на стартовый экран, тот снова получил бы 403, и начался бы цикл переходов. Проверка: мутацию `SESSION_FRESH_MS = 0` ловит тест AC-36 (число запросов); ветку `useSession(0)` — тест `start-screen.test.tsx::003_ac7_*` «в кэше свежий профиль без флага, `GET /me` отвечает 403 `password_change_required` → модальное окно `/change-password`, без цикла» |

## 3. Затрагиваемые модули и файлы

Код (только `frontend/src`):
- `frontend/src/app/router.tsx` — изменяется: `startPath`, `StartRedirect`, `Sidebar`,
  `RoleScreen`. Удаляются `Home`, `Root`, `HomeLink`, `AdminScreen`, `BusinessScreen`.
  `GuestOnly` и `ForcedPasswordChange` ведут по `startPath`. `useSession` получает
  `staleTime` (`SESSION_FRESH_MS`, D-12). `useClientHandlers.onNoRole` и `onUnauthenticated`
  переносят состояние фокуса (R4-T01…R4-T04, R4-T06).
- `frontend/src/features/auth/session.ts` — изменяется: `FOCUS_HEADING_STATE`,
  `focusHeadingState`, `useFocusHeadingOnArrival` (R4-T05).
- `frontend/src/features/auth/LoginPage.tsx` — переход на `/` с `state: FOCUS_HEADING_STATE`
  (R4-T05).
- `frontend/src/features/admin/UsersPage.tsx`, `frontend/src/features/admin/AuditPage.tsx`,
  `frontend/src/features/auth/NoRolePage.tsx` — `h1` с `tabIndex={-1}` и `ref`, хук фокуса
  (R4-T05, R4-T06).
- `frontend/src/shared/i18n/ru.ts` — `+ app.menu_label` «Меню» (R4-T02);
  `- app.home_title`, `- app.home_link` (R4-T07).
- `frontend/src/shared/ui/ui.css` — удаление `.ui-home-link`, `.ui-home-link:hover`,
  `.ui-home-link:focus-visible` (R4-T07).
- `frontend/src/shared/ui/Icon.tsx` — удаление иконки `home` из `IconName` и `PATHS` (R4-T07).
- **Не меняются:** `ChangePasswordPage.tsx` (уже переходит на `/` с `{ focusHeading: true }`),
  `ProjectsPage.tsx` (уже ставит фокус на `h1`), `useLogout.ts` (FR-13 уже выполняется),
  `client.ts`, `App.tsx`, `providers.tsx`, `package.json`.

Тесты (`frontend/tests`): новые — `app/startPath.test.ts`, `app/sidebar.test.tsx`,
`app/start-screen.test.tsx`, `app/focus-heading.test.tsx`; переписываются — §6.2.

Документы: `specs/001-pilot-r1/spec.md`, `specs/001-pilot-r1/tasks.md` (R4-T09),
`docs/acceptance/mvp-demo.md` (R4-T10).

**Не трогаются:** `backend/**`, `docs/api/**`, `frontend/src/shared/api/schema.d.ts`,
`frontend/package.json`, `frontend/package-lock.json`.

## 4. Интерфейсы

### 4.1. Правило стартового экрана (`router.tsx`, R4-T01)

```ts
type Capability = MeResponse["capabilities"][number];

/** Стартовые экраны 003/FR-3. `/no-role` здесь не возвращается: профиль без роли отвечает 403 `no_role`, и туда ведёт `redirectFor`. */
export type StartPath = "/change-password" | "/projects" | "/admin/users" | "/admin/audit";

/** 003/FR-3, п. 1, 3–6, по профилю `GET /me`. Чистая функция, без запросов. */
export function startPath(profile: Pick<MeResponse, "must_change_password" | "capabilities">): StartPath;
// must_change_password            → "/change-password"
// иначе business_access           → "/projects"
// иначе manage_accounts           → "/admin/users"
// иначе view_audit                → "/admin/audit"
// иначе                           → "/admin/users"   (там отказ по FR-14)
```
FR-3, п. 2 («нет роли») выполняется до `startPath`: `GET /me` отвечает 403 `no_role`, а
`redirectFor` ведёт на `/no-role`. Поле `MeResponse.role` в схеме не допускает `null`.

### 4.2. Перенаправление (`router.tsx`, R4-T04)

```tsx
/** `/` и любые пути без экрана (FR-1, FR-6…FR-9): только проверка сессии и `<Navigate replace>`. */
function StartRedirect({ insideMain }: { insideMain: boolean }): JSX.Element;
//   <SessionGate insideMain={insideMain}>
//     {(profile) => <Navigate to={startPath(profile)} replace state={focusHeadingState(location.state)} />}
//   </SessionGate>
//   401 / 403 password_change_required / 403 no_role — как сейчас (redirectFor, replace).
//   5xx и сеть — ErrorAlert + «Повторить», адрес не меняется, меню нет (FR-7, AC-8).

<Route path="/" element={<StartRedirect insideMain={insideMain} />} />
<Route path="*" element={<StartRedirect insideMain={insideMain} />} />   // D-3

function GuestOnly(...)            // session.data !== undefined → <Navigate to={startPath(session.data)} replace />
function ForcedPasswordChange()    // useSession(0), решение только по ответу после монтирования (D-12)
                                   // !must_change_password → <Navigate to={startPath(session.data)} replace />
                                   // 403 password_change_required → модальное окно (PasswordModal)
                                   // ошибка, не являющаяся редиректом, — как сейчас: redirectFor(error) ?? "/"

/** Профиль сессии, общий ключ ["auth", "me"] (D-12). */
const SESSION_FRESH_MS = 5_000;
function useSession(staleTime: number = SESSION_FRESH_MS): UseQueryResult<MeResponse, Error>;
//   useQuery({ queryKey: SESSION_KEY, queryFn: me, retry: false, refetchOnWindowFocus: false, staleTime })
//   SessionGate, GuestOnly, NeedsSession — по умолчанию (5 с); ForcedPasswordChange — useSession(0).
```
Свежесть профиля (D-12, R-8). Профиль, полученный не раньше чем 5 с назад, не
запрашивается заново, когда монтируется следующий экран. Поэтому цепочка `/` →
`StartRedirect` → стартовый экран стоит один `GET /me` (AC-36). Свежим бывает только ответ с
данными: у запроса без данных (только ошибка 401/403/5xx/сеть) TanStack Query считает
данные устаревшими и запрашивает их снова при монтировании. Ошибка после ранее полученных
данных не обновляет `dataUpdatedAt`: свежесть считается от времени последнего успешного
ответа. Кэш очищается (`queryClient.clear()`) при входе (`LoginPage`), выходе (`useLogout`),
успешной смене пароля и 401 на неё (`ChangePasswordPage`) и при любом 401 (`onUnauthenticated`
в `useClientHandlers`, кроме `/login`).

До R4-T06 `StartRedirect`, `GuestOnly` и `ForcedPasswordChange` передают `location.state` в
`Navigate` как есть. Начиная с R4-T06 все три передают только `focusHeadingState(location.state)`.

### 4.3. Боковое меню и экраны (`router.tsx`, R4-T02, R4-T03)

```tsx
/** Боковое меню 003/FR-10: пункты по возможностям, внизу «Выйти». Сетевых запросов не делает. */
function Sidebar({ profile }: { profile: MeResponse }): JSX.Element;
//   <div className="ui-sidebar">
//     <nav aria-label={t("app.menu_label")}>                       // «Меню», NFR-3
//       <MenuItems profile={profile} />                             // без изменений (NavLink + Icon)
//     </nav>
//     {/* 004: кнопка «Задача» встаёт здесь, между nav и «Выйти» */}
//     <button type="button" data-action="logout" disabled={logout.pending} onClick={() => void logout.run()}>
//       <Icon name="logout" />{t("auth.logout")}
//     </button>
//     <ErrorAlert message={alert.message} seq={alert.seq} />      // ошибка выхода (FR-13), D-5
//   </div>
//   alert = useAlertState(); logout = useLogout(alert)              // поведение FR-13 — useLogout без изменений

/** Экран с ролью: проверка сессии, оболочка с меню, содержимое или отказ (FR-10, FR-11, FR-14). */
function RoleScreen({ insideMain, capability, children }: {
  insideMain: boolean;
  capability: Capability;
  children: (profile: MeResponse) => ReactNode;
}): JSX.Element;
//   <SessionGate insideMain>
//     {(profile) => (
//       <Landmark insideMain shell>
//         <Sidebar profile={profile} />
//         {profile.capabilities.includes(capability)
//           ? children(profile)
//           : <ErrorAlert message={errorMessage("forbidden")} />}   // данных раздела не запрашивает
//       </Landmark>)}
//   </SessionGate>

// Маршруты:
// /admin/users  → RoleScreen capability="manage_accounts" → UsersPage
// /admin/audit  → RoleScreen capability="view_audit"      → AuditPage
// /projects, /projects/:projectId, /tasks/:taskId, /my-tasks → RoleScreen capability="business_access"
```
Порядок документа на экране: `div.ui-sidebar` (ссылки, «Выйти») → содержимое. Этот же порядок
задаёт последовательность Tab (NFR-3, AC-30). Стили не меняются: `.ui-shell > .ui-sidebar`,
`.ui-sidebar button { margin-top: auto }`, кнопки по умолчанию — светлая таблетка
(`--button-bg`, `--button-text`, `border-radius: 999px`).

Переходная форма (R4-T02): `BusinessScreen` для разрешённого экрана показывает `<Sidebar>`
вместо голого `<nav className="ui-sidebar">`. `Home` тоже показывает `<Sidebar>` (собственный
`ErrorAlert` и кнопка `Home` уходят в `Sidebar`). В R4-T03 вводится `RoleScreen`, а
`AdminScreen`, `BusinessScreen` и `HomeLink` удаляются.

### 4.4. Фокус на заголовке (`features/auth/session.ts`, R4-T05, R4-T06)

```ts
/** Состояние перехода: целевой экран ставит фокус на свой h1 (003/FR-15, FR-16). */
export const FOCUS_HEADING_STATE: { readonly focusHeading: true } = { focusHeading: true };

/** Возвращает FOCUS_HEADING_STATE, если в state есть focusHeading === true, иначе undefined. */
export function focusHeadingState(state: unknown): typeof FOCUS_HEADING_STATE | undefined;

/** Один раз после монтирования: если в location.state есть focusHeading — ref.current?.focus(). */
export function useFocusHeadingOnArrival(ref: RefObject<HTMLElement | null>): void;
```
Применение:
- `LoginPage.tsx` (R4-T05): при роли и без флага — `navigate("/", { replace: true, state: FOCUS_HEADING_STATE })`.
  Ветки `/change-password` и `/no-role` не меняются (AC-11).
- `UsersPage.tsx` (R4-T05), `AuditPage.tsx`, `NoRolePage.tsx` (R4-T06):
  `<h1 ref={headingRef} tabIndex={-1}>`, где `useFocusHeadingOnArrival(headingRef)`. Положительного
  `tabIndex` нет, поэтому заголовок не входит в последовательность Tab (AC-13, AC-15).
- `router.tsx` (R4-T06): `useClientHandlers` хранит `stateRef` рядом с `pathRef`, и
  `onNoRole: navigate("/no-role", { replace: true, state: focusHeadingState(stateRef.current) })`.
  `onUnauthenticated` (кроме `/login`) так же: `navigate("/login", { replace: true, state: focusHeadingState(stateRef.current) })`
  (принятое отклонение R4-T06, `reviews/R4-T06-1.md`). `onPasswordChangeRequired` состояние не передаёт.
  Редирект `SessionGate`: `<Navigate to={target} replace state={focusHeadingState(location.state)} />`.
  `StartRedirect`, `GuestOnly` и ветка «смена не нужна» в `ForcedPasswordChange` тоже передают
  `state={focusHeadingState(location.state)}`, а не `location.state` целиком.

Почему это нужно (последовательность для пользователя без роли после смены пароля):
`ChangePasswordPage` → `navigate("/", { state: { focusHeading: true } })` → `StartRedirect` →
`GET /me` 403 `no_role` → middleware клиента вызывает `onNoRole` раньше, чем `SessionGate`
отрисует `<Navigate>` → без переноса состояние теряется, и фокус остаётся на `body`.

Что наблюдают тесты (`reviews/R4-T06-1.md`). При 401, 403 `no_role` и 403
`password_change_required` обработчик клиента (`onUnauthenticated`, `onNoRole`,
`onPasswordChangeRequired`) переходит раньше, чем `SessionGate` отрисует `<Navigate>`.
Поэтому `state={focusHeadingState(...)}` в `<Navigate>` `SessionGate` — защитный перенос, и
тестами напрямую он не наблюдается (выжившие мутации M6, M7). Тест
`focus-heading.test.tsx::003_fr16_session_gate_redirect_forwards_only_focus_heading`
(`/admin/users`, `GET /me` 401) на деле проверяет `onUnauthenticated`, а не `SessionGate`.
Ветка ошибки `ForcedPasswordChange` (`redirectFor(error) ?? "/"`) при 401 тоже защитная:
раньше срабатывает `onUnauthenticated`. При 403 `no_role` на `/change-password` она ведёт сама,
потому что `onNoRole` на этом пути ничего не делает. Этот случай наблюдаем, но тестом пока не
покрыт (выжившая мутация M9; тест — в примечании к R4-T06 в `tasks.md`).

### 4.5. Словарь

| Ключ | Значение | Задача |
|---|---|---|
| `app.menu_label` | «Меню» | R4-T02 (добавить) |
| `app.home_title` | «Главная» | R4-T07 (удалить) |
| `app.home_link` | «На главную» | R4-T07 (удалить) |

Прочие строки уже есть: `auth.logout` «Выйти», `nav.projects`, `nav.my_tasks`,
`admin.home_users_link`, `admin.home_audit_link`, `error.forbidden`, `app.loading`,
`app.retry`. Ключи `admin.home_*_link` не переименовываются: «home» в имени — историческое,
переименование меняло бы тесты без пользы (spec, раздел 6: пункты меню не переименовываются).

## 5. Данные и эксперименты

ML-кода нет, seed не нужен. Тестовые данные — моки `fetch` (`installFetch`, `meWith` из
`frontend/tests/features/admin/helpers.tsx`). Фикстуры spec, раздел 5:
- `BA` = `meWith(["business_access","project_create","task_assign_others"], "business_admin")`;
- `U` = `meWith(["business_access"], "user")`;
- `TA` = `meWith(CAPS_ALL)` (`manage_accounts`, `assign_roles`, `view_audit`);
- `AUD` = `meWith(["view_audit"])`; `NOCAP` = `meWith([], "user")`;
- `NR` = `err(403,"no_role")`; `PWD` = `err(403,"password_change_required")`;
  `ANON` = `err(401,"not_authenticated")`.

Маршруты данных экранов в тестах: `GET /api/v1/projects`, `GET /api/v1/me/tasks`,
`GET /api/v1/admin/users`, `GET /api/v1/admin/audit` (`page([])`), карточки — 404. Тип перехода
истории проверяется через `useNavigationType()`, как в `renderRecorded` в
`tests/app/password-modal.test.tsx`. GPU не используется. Полный прогон vitest занимает около
10–20 с, smoke-режим не нужен.

## 6. Тестовая стратегия и трассировка

Уровни: unit (чистая функция), интеграционный vitest через `AppRoutes` и `MemoryRouter` с
подменой сети, статический (чтение `ui.css` и `ru.ts`), ручной (AC-31).

### 6.1. AC → реализация → тест

| AC | Где реализуется | Задача | Тест |
|---|---|---|---|
| AC-1, AC-2, AC-3 | `StartRedirect`, `startPath` | R4-T04 (правило — R4-T01) | `app/start-screen.test.tsx::003_ac1_*…003_ac3_*`; `app/startPath.test.ts` |
| AC-4, AC-5 | `StartRedirect` + `redirectFor`, маршрут `*` | R4-T04 | `app/start-screen.test.tsx::003_ac4_*`, `003_ac5_*` (6 фикстур × 3 пути) |
| AC-6 | `GuestOnly` → `startPath` | R4-T04 | `app/start-screen.test.tsx::003_ac6_*` |
| AC-7 | `ForcedPasswordChange` → `startPath` | R4-T04 | `app/start-screen.test.tsx::003_ac7_*` (в том числе ветка `useSession(0)`, D-12); `password-modal.test.tsx` (бывший `ac3_*`) |
| AC-8 | `SessionGate` (без изменений) на `/` | R4-T04 | `app/start-screen.test.tsx::003_ac8_*`; `SessionGate.test.tsx::me_%s_shows_alert…` (переписан) |
| AC-9 | `Navigate replace` | R4-T04 | `app/start-screen.test.tsx::003_ac9_*` (тип перехода REPLACE) |
| AC-10, AC-11 | `LoginPage` → `/` → `StartRedirect` | R4-T04 (пути), R4-T05 (состояние) | `app/start-screen.test.tsx::003_ac10_*`, `003_ac11_*`; `SessionGate.test.tsx::successful_login_clears_previous_users_cache` |
| AC-12 | `ChangePasswordPage` → `/` → `StartRedirect` | R4-T04 | `app/start-screen.test.tsx::003_ac12_*`; `password-modal.test.tsx` (бывшие `ac1_success_*`, `rv4_*`) |
| AC-13 | D-6: `ProjectsPage` (уже есть), `UsersPage`, `NoRolePage` | R4-T05 (`BA`, `U`, `TA`), R4-T06 (`NR`) | `app/focus-heading.test.tsx::003_ac13_*`; `password-modal.test.tsx` (бывший `rv3_*`) |
| AC-14 | без изменений (`ChangePasswordPage`, 401) | R4-T06 (тест) | `app/focus-heading.test.tsx::003_ac14_*` (шпион `console.error`) |
| AC-15 | D-6: `LoginPage` + `UsersPage` | R4-T05 | `app/focus-heading.test.tsx::003_ac15_*` |
| AC-16 | `RoleScreen` без `HomeLink`, `/` без экрана | R4-T03 (ссылки), R4-T08 (сквозная проверка) | `app/home-link.test.tsx::003_ac16_*` |
| AC-17 | без изменений экранов | R4-T08 | `app/home-link.test.tsx::003_ac17_*` |
| AC-18 | `ru.ts` | R4-T07 (словарь), R4-T08 (видимые строки) | `shared/i18n.test.ts::003_ac18_*`; `app/home-link.test.tsx::003_ac18_*` |
| AC-19 | `Sidebar` на бизнес-экранах | R4-T02 | `app/sidebar.test.tsx::003_ac19_*`; `icons.test.tsx` |
| AC-20, AC-21 | `RoleScreen` + `Sidebar` на экранах ТА | R4-T03 | `app/sidebar.test.tsx::003_ac20_*`, `003_ac21_*`; `icons.test.tsx`; `AuditPage.test.tsx` |
| AC-22 | `Sidebar` + `useLogout` | R4-T02 (`BA`), R4-T03 (`TA`) | `app/sidebar.test.tsx::003_ac22_*` |
| AC-23, AC-24, AC-25 | `useLogout` (без изменений) в `Sidebar` | R4-T02 | `app/sidebar.test.tsx::003_ac23_*…003_ac25_*` |
| AC-26 | нет ссылки (как сейчас) | R4-T04 (стартовые экраны), R4-T08 (все экраны) | `app/welcome.test.tsx` (переписан), `app/home-link.test.tsx::003_ac26_*` |
| AC-27, AC-28 | `RoleScreen`, ветка отказа | R4-T03 | `app/sidebar.test.tsx::003_ac27_*`, `003_ac28_*`; `navigation.test.tsx::ac_fr10_*` (дополнен) |
| AC-29 | `nav[aria-label]`, `button[type=button]` | R4-T02 (`BA`), R4-T03 (`TA`) | `app/sidebar.test.tsx::003_ac29_*` |
| AC-30 | порядок разметки `Sidebar` → содержимое | R4-T02, R4-T03 | `app/sidebar.test.tsx::003_ac30_*` (последовательность tabbable-элементов, без `tabindex="-1"`) |
| AC-31 *ручной* | — | R4-T10 (пункт чек-листа), R4-T11 (передача владельцу) | `docs/acceptance/mvp-demo.md`, пункт `003/AC-31` |
| AC-32 | без изменений (`NoRolePage`, `PasswordModal`) | R4-T08 | `app/home-link.test.tsx::003_ac32_*`; `password-modal.test.tsx` (как есть) |
| AC-33 | D-7, D-9 | R4-T11 | `git diff --stat e43d435 -- backend docs/api frontend/src/shared/api/schema.d.ts` пуст; `pytest -q backend/tests` |
| AC-34 | все задачи | R4-T11 | `npm run lint && npm run typecheck && npm test`; `bash scripts/check.sh`; сверка §6.2 |
| AC-35 | `startPath` п. 5, `RoleScreen` | R4-T04 (меню на `/admin/audit` — с R4-T03) | `app/start-screen.test.tsx::003_ac35_*`; `AuditPage.test.tsx` (бывший `home_shows_only_audit_link…`) |
| AC-36 | `startPath` п. 6, ветка отказа | R4-T04 | `app/start-screen.test.tsx::003_ac36_*`; `SessionGate.test.tsx` (бывший `me_200_with_role_shows_home_stub_not_blank`) |

FR без отдельного AC: FR-9 проверяют AC-3, AC-27, AC-28, AC-35, AC-36 (счётчик запросов в
`installFetch`). FR-12 — AC-26. FR-17 — AC-32.

### 6.2. Старые тесты → AC 003 (NFR-5)

Правила для test-writer и ревьюера:
1. Тест, который проверял «Главную», «На главную» или переход на `/`, не удаляется без замены.
   Разрешено: (а) **переписать** тест на критерий 003 (другой путь или ожидание) в том же
   файле, указав AC в имени (`003_acN_*`) или в комментарии; (б) **удалить дубликат** нового
   теста `003_*`, назвав удалённый тест в комментарии заменителя.
2. Проверки, не связанные с «Главной» (кэш, 401, `aria-current`, иконки, тип кнопок), не
   ослабляются: они переносятся на новый экран.
3. Если тест падает по причине, не описанной в таблице, исполнитель возвращает `PLAN_ISSUE`.

| Файл (тесты) | Действие | AC | Задача |
|---|---|---|---|
| `tests/app/home-link.test.tsx` (весь файл: `ac_%s_home_link_is_styled`, `ac_%s_forbidden_home_link_is_styled`) | Файл переписывается на «ссылки "На главную" и `a[href="/"]` нет» на тех же путях и экранах отказа. Позже дописываются сквозные проверки | AC-16, AC-27, AC-28 (R4-T03); AC-16, AC-17, AC-18, AC-26, AC-32 (R4-T08) | R4-T03, R4-T08 |
| `tests/app/icons.test.tsx`: `%s: home link has an icon` | Становится «`%s`: ссылки меню и "Выйти" начинаются с иконки, иконки различны» | AC-20 | R4-T03 |
| `tests/app/icons.test.tsx`: `home: every sidebar link and the logout button start with an icon…` | Переносится на `/projects` с `business_access` и админскими возможностями: 4 ссылки и «Выйти» | AC-19 | R4-T04 |
| `tests/app/icons.test.tsx`: шапка-контракт (`.ui-home-link`) | Текст контракта без «На главную» | — | R4-T03 |
| `tests/app/navigation.test.tsx`: `ac_fr10_%s_without_business_access_shows_forbidden` | Дополняется: меню со ссылками ТА и «Выйти», ссылки «На главную» нет | AC-27 | R4-T03 |
| `tests/app/navigation.test.tsx`: шапка-контракт («`<nav>` на главной "/"»), `ac_stub_titles_are_distinct_and_differ_from_home`, `ac_menu_business_access_has_projects_and_my_tasks_on_home`, `ac_menu_tech_admin_without_business_access_has_only_admin_items`, `ac_menu_partial_admin_capabilities_as_in_r1_0`, `ac_menu_has_no_crm_labels_trash_search_mentions_items` | Те же проверки на стартовых экранах: `/projects` (`BA`, `U`, все возможности), `/admin/users` (`TA`, только `manage_accounts`). Заголовки `/projects` и `/my-tasks` различны, и ни один не «Главная» | AC-1, AC-19, AC-20, AC-21 | R4-T04 |
| `tests/app/welcome.test.tsx`: `ac_%s_home_has_no_change_password_link_and_no_welcome_block`, `ac_sidebar_has_no_change_password_but_keeps_menu_and_logout` | Открывается `/` и ожидается стартовый экран роли (`/admin/users` для ТА, `/projects` для БА и П). Проверки «нет ссылки "Сменить пароль", нет блока welcome» те же. Меню и «Выйти» — на `/projects` | AC-26, AC-19 | R4-T04 |
| `tests/app/password-modal.test.tsx`: `ac1_success_closes_dialog_goes_home_and_rereads_profile`, `ac3_not_forced_user_is_redirected_home_without_dialog`, `rv3_after_success_focus_is_on_home_heading_not_body`, `rv4_success_path_sequence_and_me_reread_after_post`, шапка-контракт | Профиль `U` → путь `/projects`, `h1` «Список проектов» (добавить маршрут `GET /api/v1/projects`). `rv3` — фокус на «Список проектов», `tabindex="-1"`. `rv4` — последовательность путей `/change-password` → (`/`) → `/projects`, все переходы REPLACE, `/me` перечитан после POST | AC-7, AC-12, AC-13 | R4-T04 |
| `tests/features/auth/SessionGate.test.tsx`: шапка-контракт, `me_200_with_role_shows_home_stub_not_blank`, `unknown_path_redirects_to_root_then_by_me`, `login_with_active_session_goes_home`, `t103_voluntary_change_password_redirects_home`, `change_password_with_role_lands_on_home`, `successful_login_clears_previous_users_cache`, `403_no_role_goes_to_no_role`, `unmount_of_app_routes_resets_handlers`, `me_%s_shows_alert_and_retry_button_refetches` | Фикстура `USER` (роль `user`, возможностей нет) по FR-3, п. 6 ведёт на `/admin/users` с отказом. Ожидания `"/"` → `"/admin/users"` + `alert` forbidden + один запрос. Неизвестный путь — сразу на стартовый экран. После «Повторить» — стартовый экран | AC-36, AC-5, AC-6, AC-7, AC-12, AC-10, AC-4, AC-8 | R4-T04 |
| `tests/features/admin/AuditPage.test.tsx`: блок `links from admin screens to home` (`%s_has_link_to_home`) | Становится «на экранах ТА — меню с "Учётными записями", "Журналом аудита" и "Выйти"; `a[href="/"]` нет» | AC-20, AC-16 | R4-T03 |
| `tests/features/admin/AuditPage.test.tsx`: `home_links_follow_capabilities`, `home_shows_only_audit_link_with_only_view_audit`, `home_has_typed_logout_button_that_logs_out_clears_cache_and_goes_to_login`, `t103_home_has_no_change_password_link` | Открывается `/`: ТА → `/admin/users`, ссылки по возможностям; пустые возможности → отказ без ссылок `/admin*`; `AUD` → `/admin/audit` только со ссылкой журнала. Кнопка выхода ищется **внутри `.ui-sidebar`** (на экране есть кнопки `UsersPage`): ровно одна, `type="button"`, выход, кэш очищен. Ссылки на `/change-password` нет | AC-20, AC-36, AC-35, AC-22, AC-26 | R4-T04 |
| `tests/features/admin/helpers.tsx`: комментарий-контракт про «Главную ("/")» | Текст: ссылки разделов — в боковом меню экранов с ролью | — | R4-T04 |
| `tests/shared/theme.test.ts`: блок `T92 .ui-home-link (pill link styled like buttons)` | Становится «003: "Выйти" в боковом меню — светлая таблетка»: `button` с `var(--button-bg)`, `var(--button-text)`, радиусом ≥ 16px; `.ui-sidebar button` с `margin-top: auto`; селектора `.ui-home-link` в `ui.css` нет. Проверка контраста `button-text`/`button-bg` уже есть в таблице пар | AC-19 (вид), NFR-2 | R4-T07 |
| `tests/shared/typography.test.ts`: строка `".ui-home-link": 14` в `OLD` | Удаляется вместе с селектором. Проверка «нет `font-size` вне таблицы» остаётся | — | R4-T07 |
| `tests/features/auth/LoginPage.test.tsx`, `tests/features/auth/ChangePasswordPage.test.tsx` | Не меняются: формы по-прежнему переходят на `/` (D-2) | — | — |
| `tests/features/admin/UsersPage.test.tsx` (~стр. 538), `tests/features/projects/ProjectPage.test.tsx` (~стр. 540) | Не меняются: «Выйти» — `button[type=button]` с текстом, и проверки проходят. Если нет — `PLAN_ISSUE` | — | R4-T02, R4-T03 |

## 7. Зависимости

Новых пакетов нет (NFR-4). Используются `react-router-dom` 7 (`Navigate`, `useLocation`,
`useNavigationType`), `@tanstack/react-query` 5, vitest и Testing Library.

## 8. Риски

- **R-1. Гонка обработчика клиента и `<Navigate>`** (D-6, §4.4): без переноса состояния в
  `onNoRole` фокус для `NR` пропадает. Это проверяет AC-13 (`NR`) в R4-T06.
- **R-2. Объём переписывания тестов в R4-T04** — 7 файлов, один файл кода. Снижение риска:
  таблица §6.2 с действием для каждого теста, файлы тестов перечислены в задаче.
- **R-3. Промежуточный `/` в истории.** После входа и смены пароля путь проходит `/`
  (рендер индикатора), но запись заменяется (`replace`). AC-9 и AC-12 проверяют тип
  переходов, а не число рендеров.
- **R-4. Линтер `eslint-plugin-react-hooks` 7** запрещает `setState` в теле эффекта и чтение
  `ref` при рендере. `useFocusHeadingOnArrival` только вызывает `focus()` в эффекте.
- **R-5. Незакоммиченные `spec.md` 003 и 004** (`git status`). `scripts/task_scope.py`
  сравнивает с `HEAD` и сочтёт их выходом за рамки задачи. Перед R4-T01 оркестратор коммитит
  `spec.md`, `plan.md`, `tasks.md` обеих фич.
- **R-6. Экран отказа сразу после входа (`NOCAP`)** — сообщение «нет прав» берёт фокус
  (`ErrorAlert`), а не заголовок. Так задумано: заголовка у экрана отказа нет, FR-16 касается
  стартовых экранов с содержимым.
- **R-7. `/change-password` при 5xx** ведёт на `/` (как сейчас), где `SessionGate` показывает
  ошибку и «Повторить». Адрес меняется (§9, П-3).
- **R-8. Профиль в кэше до 5 с** (D-12). В течение `SESSION_FRESH_MS` экраны решают по
  профилю из кэша и не перечитывают `GET /me`. Безопасность держится на `queryClient.clear()`
  при входе, выходе, успешной смене пароля и 401 (§4.2): профиль другого пользователя в кэше
  не остаётся, и его данные не показываются. При 403 `no_role` кэш не очищается
  (`onNoRole` только переходит на `/no-role`). Поэтому после снятия роли кнопка «Назад» может
  на миг показать экран прежней роли того же пользователя по профилю из кэша. Затем запрос
  экрана получает 403 `no_role`, и клиент ведёт на `/no-role`. Окно не больше 5 с, и сервер
  проверяет доступ сам. Если риск сочтут неприемлемым, нужно очищать `SESSION_KEY` в `onNoRole`
  (отдельная правка, вне 003). `ForcedPasswordChange` от этого риска защищён: он читает
  профиль заново (`useSession(0)`).

## 9. Противоречия и неполнота spec (не исправлены; на решение владельца или spec-writer)

- **П-1. AC-33: «сравнивается … с `main`».** Ветка уже отличается от `main` всем бэкендом
  001/002, поэтому буквальная проверка невыполнима. План сравнивает с началом фичи — `e43d435`
  (D-9). Предлагается уточнить AC-33 (и 004/AC-38): «с коммитом начала фичи».
- **П-2. Белый список файлов фронтенда в тесте бэкенда.**
  `backend/tests/infra/test_frontend_scaffold.py::test_t21_src_files_only_expected` падает на
  любом новом файле в `frontend/src`. Добавить строку в список — значит изменить тест бэкенда,
  что запрещает AC-33. План не создаёт файлов в `frontend/src` (D-7). Если владелец разрешит
  правку белого списка, `startPath` и `Sidebar` можно вынести в отдельные модули без
  изменения поведения.
- **П-3. FR-7 и `/change-password` при 5xx.** FR-6 включает `/change-password` только для
  пользователя, которому смена не нужна, а при 5xx это неизвестно. Код сейчас ведёт на `/`, и
  адрес меняется. AC-8 проверяет только `/`. План сохраняет нынешнее поведение. Если нужно
  «адрес не меняется» и на `/change-password`, это отдельная правка (`ForcedPasswordChange`
  показывает ошибку и «Повторить» на месте).
- **П-4. Запрос оркестратора о синхронизации подписей ролей в `test_docs_static.py`**
  противоречит AC-33 (тесты бэкенда не меняются). Проверка на `e43d435`: подписи «Тех-админ»
  и «Бизнес-админ» в `ru.ts`, `docs/acceptance/mvp-demo.md`, `README.md` и
  `backend/tests/infra/test_docs_static.py` уже совпадают,
  `pytest -q -m infra_static backend/tests/infra/test_docs_static.py` — 246 passed. Поэтому
  R4-T10 только сверяет. Тест бэкенда меняется только с разрешения владельца и вне критериев
  003.
- **П-5. FR-3, п. 2 («нет роли») по профилю.** `MeResponse.role` в OpenAPI не допускает `null`:
  без роли сервер отвечает 403 `no_role`. Пункт выполняется веткой `redirectFor`, а не
  `startPath` (§4.1). Противоречия нет, это уточнение.
- **П-6. FR-6 и `/login` при действующей сессии: форма входа на время ответа `/me`.**
  Буквально FR-6 требует, чтобы `/login` при живой сессии показывал только индикатор проверки
  сессии. `GuestOnly` (§4.2) ждёт ответа `GET /me` и всё это время показывает форму входа.
  Перенаправление по `startPath` начинается после ответа. Так было и до 003. AC-6 проверяет
  конечное состояние (путь стартового экрана, формы входа нет) и выполняется. Это принятое
  отклонение (или уточнение FR-6) по итогам финальной приёмки, `reviews/FINAL-acceptance.md`,
  остаток п. 1. Если владелец потребует буквального FR-6, нужна отдельная правка: `GuestOnly`
  показывает `p[role=status]` до ответа `/me`. Цена такой правки — индикатор у каждого гостя
  перед формой входа (ответ 401).

Решения к сведению владельца (не противоречат spec; финальная приёмка, остаток п. 3):
- **Фокус на `h1` повторяется при «Назад».** Состояние `{ focusHeading: true }` (D-6) хранится
  в записи истории. При возврате на эту запись кнопкой «Назад» `useFocusHeadingOnArrival`
  снова ставит фокус на заголовок. FR-15 и FR-16 этот случай не описывают. Если повтор
  нежелателен, состояние нужно гасить после фокуса (`navigate(…, { replace: true, state: undefined })`),
  это отдельная правка.
- **Сообщение об ошибке выхода (FR-13) переживает переход между экранами ТА.** `RoleScreen`
  на `/admin/users` и `/admin/audit` сохраняет один экземпляр `Sidebar` (то же дерево
  элементов), поэтому `useAlertState` в нём не сбрасывается при переходе по меню. Если сообщение
  должно исчезать при переходе, нужен сброс по `pathname`, это отдельная правка.

## 10. Связь с 001 (файлы 001 правит только R4-T09)

| 001 | Что устаревает | Правка (R4-T09) |
|---|---|---|
| spec 001, история версий | — | Запись v0.19: «стартовый экран и боковое меню — 003/FR-1…FR-17» |
| tasks 001, T81 | контракт «`<nav>` на главной "/"» | пометка «Пересмотрено 003: "/" только перенаправляет, меню — на каждом экране с ролью» |
| tasks 001, T92 | стиль ссылки «На главную» | пометка «Снято 003: ссылки и стиля `.ui-home-link` нет» |
| tasks 001, T100 | иконка «На главную» | пометка «Пересмотрено 003: иконка `home` удалена, иконки у пунктов меню и "Выйти" остаются» |
| tasks 001, T103 | после смены пароля путь `/` и фокус на заголовке «Главной» | пометка «Пересмотрено 003: стартовый экран по 003/FR-3, фокус на его заголовке (003/FR-15)» |
