# Финальная приёмка 003 «Без Главной» — ACCEPT WITH REMARKS
Блокирующих замечаний нет. Ручной AC-31 (Chromium, демо-данные, клавиатура) — за владельцем (`docs/acceptance/mvp-demo.md`, пункт 003/AC-31).
## Прогоны
- `git diff --stat e43d435 -- backend docs/api frontend/src/shared/api/schema.d.ts` — пусто; `frontend/package*.json` без изменений.
- frontend: lint, typecheck чисто; `npm test` — 38 файлов, 1044 passed.
- `pytest -q -m infra_static backend/tests/infra/test_docs_static.py backend/tests/infra/test_frontend_scaffold.py` — 290 passed.
- НЕ выполнялись: `bash scripts/check.sh` и полный `pytest -q backend/tests` (бэкенд не тронут; указание владельца).
- `git grep` по «Главная|На главную|home_title|home_link|ui-home-link|to="/"» в frontend/src — пусто (кроме разрешённого `redirectFor(error) ?? "/"`).
## Покрытие AC
AC-1…AC-30, AC-32, AC-35, AC-36 — зелёные тесты (таблица AC → тест в отчёте ревьюера; имена `003_acN_*` в start-screen, focus-heading, sidebar, home-link, navigation, welcome, password-modal, SessionGate, AuditPage, startPath, icons, theme, i18n); AC-31 — ручной; AC-33, AC-34 — частично (check.sh и полный backend-pytest не запускались).
## Отклонения от plan (записаны)
D-12 (`SESSION_FRESH_MS = 5 с`, `useSession(0)` в ForcedPasswordChange), R-8; `onUnauthenticated` с `focusHeadingState` (D-6, §4.4).
## Остаток (желательные)
1. GuestOnly показывает форму входа на время ответа /me при живой сессии (FR-6 буквально требует индикатор) — уточнить FR-6 или записать в plan §9 как П-6.
2. Тест `003_fr15_change_password_with_no_role_…` с FOREIGN state (мутация M14).
3. Фокус на h1 повторяется при «Назад»; ошибка выхода переживает переход между экранами ТА — к решению владельца.
4. Уборка тестов (ref/seen, дубль строки, /сменить пароль/i, префикс `003_` у ac16_*).
5. Коммиты 005 (справка на входе) попали в диапазон e43d435..HEAD, к 003 не относятся.
6. Переименовать `admin.home_*_link` (отдельно); пункт AC-31 не защищён тестом (AC-33 запрещает правку теста бэкенда).
