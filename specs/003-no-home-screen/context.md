# Контекст 003: убрать «Главную» (выжимка scout, 2026-10-17)

Код: `frontend/src/app/router.tsx` — `Home` (h1 «Главная», `focusHeading`, `.ui-sidebar` с `<nav>` и «Выйти»), `Root` на "/", `HomeLink` («На главную», `ui-home-link`) в `AdminScreen`, `MenuItems`, редиректы на "/" (ForcedPasswordChange, GuestOnly, `path="*"`). `LoginPage.tsx:44` и `ChangePasswordPage.tsx:49-51` (state.focusHeading) идут на "/". `NoRolePage.tsx` — кнопка «Выйти». i18n: `ru.ts` `app.home_title`, `app.home_link`. «Выйти» есть только на Главной (BusinessScreen-сайдбар без него).
Spec 001/002: слов «Главная/На главную» нет; FR-10 (меню по capabilities), FR-55/56, OI-6, OI-75 (без роли: вход, выход, смена пароля), AC-75, AC-98, AC-113, UF-2/UF-3. Docs: `mvp-demo.md:131` AC-98 без «Главной». Backend-тесты от Главной не зависят.
Frontend-тесты: tests/app/home-link, icons, navigation, welcome, password-modal; tests/features/auth/SessionGate, ChangePasswordPage, LoginPage.
Команды: `cd frontend && npm run lint && npm run typecheck && npm test`.
Решения владельца: ТА стартует на «Учётные записи»; «Выйти» и «Сменить пароль» — внизу бокового меню на всех экранах; короткий цикл SDD.
