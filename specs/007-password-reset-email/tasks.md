# Tasks: Самостоятельный сброс пароля по email с экрана входа (spec 007)

Статусы: TODO | IN_PROGRESS | DONE | BLOCKED. Статусы ведёт оркестратор.

## Общие условия для всех задач R7

- Источник истины — `specs/007-password-reset-email/spec.md` v0.1 (APPROVED). Интерфейсы и решения —
  `specs/007-password-reset-email/plan.md`: решения `PR-n` (§2), интерфейсы §4, трассировка §6, вопросы `Q-n` (§9).
  Если задача противоречит spec или plan, вернуть `PLAN_ISSUE` и ничего не додумывать.
- **ID задач с префиксом `R7-`**: `T01…` уже заняты в `specs/001-pilot-r1/tasks.md`, а `scripts/task_scope.py`
  требует уникальный ID.
- **Рамки файлов.** Менять только файлы из поля «Файлы». Проверка: `python scripts/task_scope.py R7-Tnn` из корня
  (выход 0). `docs/api/openapi.json` и `frontend/src/shared/api/schema.d.ts` меняются только командой
  `source .venv/bin/activate && bash scripts/gen-api.sh` и только в задачах, где это сказано.
- **Не трогать:** `backend/pyproject.toml`, `frontend/package.json`, `frontend/package-lock.json` (новых
  зависимостей нет, NFR-5), `CLAUDE.md`, `AGENTS.md`, `docs/STATE.md`, `docs/adr/**`, `docs/brief/**`,
  `specs/007-password-reset-email/spec.md`, применённые миграции `0001…0007`.
- **Слои (AGENTS.md).** Роутер: схема → один вызов сервиса `domain/` → схема ответа. Запросов к БД в роутерах нет.
  `commit()` в `app/**` запрещён. `commit_durably` в этой фиче не используется. Ошибки — только подклассы
  `AppError` (формат `{"detail","code"}`).
- **Секреты (NFR-1).** Токен, его хеш, пароль, email и текст письма не попадают в логи, тексты исключений и
  ответы API. Исключение — `email` в ответах `/admin/users*`. В логах — только тип исключения.
- **Сложность (ruff):** `max-complexity=16`, `max-branches=16`, `max-args=10`, `max-statements=34`. Длинные
  функции дробить на приватные помощники (plan §4.3).
- **Строки интерфейса** — только из `frontend/src/shared/i18n/ru.ts` (ключи — plan §4.7). Кириллица в
  `frontend/src` вне словаря запрещена (сканер AC-98). Код и комментарии — на английском во фронтенде; в бэкенде
  следовать языку окружения файла (там русский). Письмо — по-русски.
- **Новые файлы в `frontend/src`** допускаются только перечисленные в задачах. Каждый новый файл добавляется в
  белый список `backend/tests/infra/test_frontend_scaffold.py::test_t21_src_files_only_expected` в той же задаче.
- **БД.** Деструктивные операции — только в тестовой БД `*_test`:
  `export TEST_DATABASE_URL=postgresql+asyncpg://tracker:tracker@localhost:5432/tracker_test`. Тома Docker не удалять.
- **Время в тестах:** бэкенд — фикстура `fixed_clock` (`advance`, `set`), фронтенд — `vi.setSystemTime`.
- **SMTP в тестах** только подменённый (`tests/mail_support.py::RecordingMailer`, фикстура `reset_api_env`,
  `monkeypatch` для `smtplib.SMTP`). Сеть не используется.
- **Тесты** пишет test-writer, исполнитель их не меняет. Новые тесты: бэкенд — `test_007_acN_*` (или
  `test_007_<тема>_*` для FR без AC), фронтенд — `007_acN_*`. Существующие assert-ы не ослабляются, только
  дополняются (списки маршрутов, голова миграций, белые списки).
- **Команды.**
  - «Линт бэкенда» = `source .venv/bin/activate && ruff check backend && ruff format --check backend && mypy --config-file backend/pyproject.toml backend/app`.
  - «Линт фронтенда» = `cd frontend && npm run lint && npm run typecheck`.
- **Коммиты** делает оркестратор (Conventional Commits, без `git push`).

Порядок и критический путь:
R7-T01 → R7-T02 → R7-T04 → R7-T07 → R7-T08 → R7-T09 → R7-T11 → R7-T12 → R7-T13 → R7-T16 → R7-T17 → R7-T18 → R7-T21.
Параллельно: R7-T03 (после T02); R7-T05 (после T01); R7-T06 (после T01, T02, T05) → R7-T10 → R7-T19 → R7-T20;
R7-T14 (после T01); R7-T15 (после T05, до T16 и T19). Задачи, которые перегенерируют API (T10, T11, T12) и меняют
`test_openapi.py`, выполнять последовательно. Задачи, которые меняют `router.tsx` (T17, T18), `UsersPage.tsx`
(T19, T20) и `test_frontend_scaffold.py` (T17, T18, T20), тоже последовательно.

---

## R7-T01 — Миграция 0008 и модели: `app_user.email`, `password_reset_token`, `password_reset_attempt`
- **Статус:** DONE
- **AC:** NFR-4; основа для AC-1, AC-5, AC-10
- **Файлы:** `backend/migrations/versions/0008_password_reset_email.py` (новый), `backend/app/domain/users/models.py`, `backend/app/domain/auth/models.py`;
  тесты: `backend/tests/db/test_007_schema.py` (новый), `backend/tests/upgrade002_support.py`, `backend/tests/db/test_migrations.py`, `backend/tests/factories.py`
- **Зависит от:** —
- **Описание:** По plan §4.1 и PR-1: в `AppUser` — `email: Mapped[str | None] = mapped_column(String(254), unique=True, nullable=True)`
  и `CheckConstraint('lower(email COLLATE "C") = email', name="email_lower")`. В `auth/models.py` — модели
  `PasswordResetToken` и `PasswordResetAttempt` (поля, CHECK, FK `ON DELETE CASCADE`, индексы — §4.1, время
  через `utcnow`). Миграция `0008` по образцу `0007_three_priorities.py` (docstring со ссылкой на spec 007,
  `revision="0008"`, `down_revision="0007"`, без импорта `app.*`), downgrade удаляет всё созданное. Голова
  `"0007"` → `"0008"` в `upgrade002_support.py:67` и в `test_migrations.py` (строки ~962, 996, 1010, 1060).
  `make_user` получает необязательный `email: str | None = None` (пишется как передан).
  Test-writer: upgrade 0007→0008→downgrade→upgrade; колонки, типы, nullable; `UNIQUE` (два одинаковых адреса —
  ошибка, два NULL — можно); CHECK отвергает `A@x.ru`; удаление пользователя каскадно удаляет его токены;
  CHECK длины `token_hash`/`key_hash` и `scope`.
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/db/test_007_schema.py backend/tests/db/test_migrations.py backend/tests/db/test_identity_models.py backend/tests/cli/test_export_import.py` зелёный;
  `alembic -c backend/alembic.ini upgrade head && alembic -c backend/alembic.ini check` на `*_test` БД чисты; «Линт бэкенда» чист
- **Попытки:** 1

## R7-T02 — Ошибки и настройки SMTP
- **Статус:** DONE
- **AC:** FR-3 (настройки), основа для AC-1 (409), AC-2 (404), AC-7 (400)
- **Файлы:** `backend/app/core/errors.py`, `backend/app/core/config.py`;
  тесты: `backend/tests/unit/test_config.py`, `backend/tests/unit/test_007_errors.py` (новый)
- **Зависит от:** —
- **Описание:** По plan §4.2: классы `FeatureDisabled` (404 `feature_disabled`), `ResetTokenInvalid` (400
  `reset_token_invalid`), `EmailTaken` (409 `email_taken`) и член `ErrorCode.email_invalid` (раздел `# [007]`).
  В `Settings` — `smtp_host`, `smtp_port=587`, `smtp_user`, `smtp_password: SecretStr | None`, `smtp_from`,
  `smtp_starttls=True`, `public_base_url`. Пустые строки и строки из одних пробелов → `None` (валидатор
  `mode="before"`). `public_base_url` проверяется по `^https?://[^/\s]+$`. Свойство `password_reset_enabled`.
  `model_validator(mode="after")`: задан `smtp_host`, но нет `smtp_from` или `public_base_url` → `ValueError` с
  именем недостающего поля, без значений.
  Test-writer: умолчания (функция выключена); чтение переменных окружения `SMTP_*`/`PUBLIC_BASE_URL`; `""→None`;
  Fail Fast; `smtp_password` маскируется в `repr`; ответы API нового класса ошибки имеют формат `{"detail","code"}` и
  нужный статус (по образцу `backend/tests/api/test_errors.py`).
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/unit/test_config.py backend/tests/unit/test_007_errors.py backend/tests/api/test_errors.py` зелёный; «Линт бэкенда» чист
- **Попытки:** 1

## R7-T03 — Переменные окружения поставки: `.env.example`, `docker-compose.yml`
- **Статус:** DONE
- **AC:** FR-3
- **Файлы:** `.env.example`, `docker-compose.yml`, `deploy/dev.env.example`;
  тесты: `backend/tests/infra/test_compose_static.py`
- **Зависит от:** R7-T02
- **Описание:** В `api.environment` добавить `SMTP_HOST: ${SMTP_HOST:-}`, `SMTP_PORT: ${SMTP_PORT:-587}`,
  `SMTP_USER: ${SMTP_USER:-}`, `SMTP_PASSWORD: ${SMTP_PASSWORD:-}`, `SMTP_FROM: ${SMTP_FROM:-}`,
  `SMTP_STARTTLS: ${SMTP_STARTTLS:-true}`, `PUBLIC_BASE_URL: ${PUBLIC_BASE_URL:-}`. В `.env.example` — эти
  переменные закомментированными, с русским комментарием: без `SMTP_HOST` сброс по email выключен;
  `PUBLIC_BASE_URL` обязателен при `SMTP_HOST` (например `https://tracker.example.ru`); `SMTP_PASSWORD` не
  коммитить. В `deploy/dev.env.example` — закомментированный пример (по умолчанию функция в dev выключена).
  Test-writer: compose-переменные берутся из `.env` с умолчаниями как выше; `SMTP_PASSWORD` — только ссылка `${…}`
  (существующий `test_nfr9_compose_has_no_secrets_or_placeholders` зелёный); `.env.example` содержит все семь имён
  закомментированными.
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/infra/test_compose_static.py backend/tests/unit/test_config.py` зелёный
- **Попытки:** 2

## R7-T04 — SMTP-адаптер и шаблон письма
- **Статус:** DONE
- **AC:** AC-5 (содержимое письма), NFR-2 (неблокирующая отправка), NFR-3 (один шаблон), NFR-5, NFR-6
- **Файлы:** `backend/app/core/mail.py` (новый), `backend/app/domain/auth/reset_mail.py` (новый);
  тесты: `backend/tests/mail_support.py` (новый), `backend/tests/unit/test_007_mail.py` (новый), `backend/tests/unit/test_007_reset_mail.py` (новый)
- **Зависит от:** R7-T02
- **Описание:** По plan §4.2 и PR-12: `MailMessage` (поля `to`/`body` без `repr`), протокол `Mailer`, `SmtpMailer`
  (stdlib `smtplib.SMTP(host, port, timeout=10)`, `starttls(context=ssl.create_default_context())` при
  `smtp_starttls`, `login` при `smtp_user`, `send_message(EmailMessage)` с `From=smtp_from`, `To`, `Subject`,
  тело `text/plain; charset=utf-8`), `async deliver(mailer, message)` (`asyncio.to_thread`, любое `Exception` → `warning`
  в логгер `app.mail` только с `type(exc).__name__`). `reset_mail.build_reset_mail(to=, link=, ttl=)` — тексты из
  plan §4.3. В `tests/mail_support.py` — `RecordingMailer` (§4.6).
  Test-writer: подменённый `smtplib.SMTP` фиксирует вызовы (STARTTLS вкл/выкл, login только при `smtp_user`,
  адресаты, тема); `deliver` при исключении не бросает, а `caplog` содержит только имя типа, без адреса и тела;
  письмо содержит ссылку, «30 минут», «если это были не вы, ничего не делайте», и не содержит переданного логина
  (передать его в окружение теста и проверить отсутствие).
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/unit/test_007_mail.py backend/tests/unit/test_007_reset_mail.py backend/tests/arch` зелёный; «Линт бэкенда» чист
- **Попытки:** 1

## R7-T05 — Каталог событий: смена email и сброс пароля
- **Статус:** DONE
- **AC:** FR-2 (журнал), FR-15, часть AC-12
- **Файлы:** `backend/app/domain/events/catalog.py`;
  тесты: `backend/tests/unit/test_event_catalog.py`
- **Зависит от:** —
- **Описание:** Добавить `USER_EMAIL_CHANGED="user.email_changed"`, `USER_PASSWORD_RESET_REQUESTED=
  "user.password_reset_requested"`, `USER_PASSWORD_RESET_COMPLETED="user.password_reset_completed"`, все три —
  `_USER_AUDITED` (plan PR-4; имена ждут подтверждения Q-1). В тесте расширить `USER_ACTIONS` этими тремя
  значениями. Остальные проверки не меняются.
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/unit/test_event_catalog.py backend/tests/db/test_event_log.py` зелёный; «Линт бэкенда» чист
- **Попытки:** 1

## R7-T06 — Домен пользователей: нормализация email, `create_user(email=)`, `set_email`
- **Статус:** DONE
- **AC:** AC-1 (домен), FR-1, FR-2
- **Файлы:** `backend/app/domain/users/email.py` (новый), `backend/app/domain/users/service.py`;
  тесты: `backend/tests/domain/test_007_user_email.py` (новый)
- **Зависит от:** R7-T01, R7-T02, R7-T05
- **Описание:** По plan §4.3 и PR-1/PR-3: `normalize_email`. `UserAccount`/`_Target` получают `email`,
  его читают `_load_target`, `list_accounts` (`load_only` + `AppUser.email`) и `create_user`. `create_user(...,
  email: str | None = None)`: порядок `login_invalid → login_taken → email_invalid (422) → email_taken (409) →
  политика пароля`, вставка в `db.begin_nested()`, `IntegrityError` по `uq_app_user_email` → `EmailTaken`. Новый
  `set_email(db, actor, user_id, email, /)` (порядок проверок — §4.3; то же значение — без события; событие
  `user.email_changed` без `changed_fields`/`details`). Сессии пользователя не трогаются.
  Test-writer: `A@x.ru` и `a@X.ru` → `EmailTaken`; `None` и `""` допустимы у нескольких пользователей; значение
  хранится как `a@x.ru`; невалидные (`"a"`, `"a@"`, `"a b@x"`, 255 символов) → 422 `email_invalid`; очистка;
  повтор того же значения не пишет событие; не-ТА → 403; чужое пространство → 404; занятость адреса
  пользователем другого пространства → 409; адрес заблокированного пользователя тоже занят (PR-2).
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/domain/test_007_user_email.py backend/tests/domain/test_user_admin_service.py` зелёный; «Линт бэкенда» чист
- **Попытки:** 1

## R7-T07 — Лимиты частоты запросов сброса
- **Статус:** DONE
- **AC:** AC-10 (домен), FR-9
- **Файлы:** `backend/app/domain/auth/reset_limits.py` (новый);
  тесты: `backend/tests/domain/test_007_reset_limits.py` (новый)
- **Зависит от:** R7-T01
- **Описание:** По plan §4.3 и PR-7: `limit_key_hash`, `register_request(db, key, *, email, ip, now) -> bool`.
  Чистка строк старше окна, `pg_advisory_xact_lock` (своё пространство ключей двухключевой формы, отличное от
  `0x75736572` в `users/service.py`) по ключам в порядке email→ip, подсчёт, вставка только при допуске. Открытые
  email и IP в БД не пишутся.
  Test-writer (часы — `fixed_clock`): 3 допуска и отказ на 4-м по одному email; через 61 минуту снова допуск;
  10 разных email с одного IP → 11-й отказ; другой IP не затронут; `ip=None` — только лимит email; отклонённые
  строк не добавляют; в `password_reset_attempt.key_hash` нет байтов открытого email.
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/domain/test_007_reset_limits.py` зелёный; «Линт бэкенда» чист
- **Попытки:** 1

## R7-T08 — Домен: `request_reset`, политика сброса в `lifespan`
- **Статус:** DONE
- **AC:** AC-5 (токен хранится хешем, письмо собрано), AC-6 (отзыв прежних токенов), AC-11 (заблокированный без письма), FR-6, FR-7, FR-8, FR-15 (`requested`)
- **Файлы:** `backend/app/domain/auth/password_reset.py` (новый), `backend/app/main.py`,
  `backend/app/domain/auth/reset_limits.py` (правка по PR-21: `email: str | None`); тесты: `backend/tests/domain/test_007_request_reset.py` (новый),
  `backend/tests/domain/test_007_reset_limits.py` (добавить случай `email=None`)
- **Зависит от:** R7-T04, R7-T05, R7-T06, R7-T07
- **Описание:** По plan §4.3, §4.5, PR-2, PR-5, PR-19: `TOKEN_TTL`, `ResetPolicy`, `new_token`, `token_hash`,
  `reset_link`, `request_reset(...) -> MailMessage | None`. `policy is None` → `FeatureDisabled`. Поиск
  пользователя по нормализованному email среди активных (не заблокирован, есть `workspace_member`; workspace —
  первое членство, как в `auth/service.py:login`). При найденном пользователе: удаление его неиспользованных
  токенов, вставка нового, событие `user.password_reset_requested` (`actor_id=None`), письмо через
  `build_reset_mail`. В `main.py:_lifespan` — `state.mailer` и `state.password_reset_policy` (§4.5).
  Test-writer: активный пользователь → `MailMessage` со ссылкой `<base>/password-reset/confirm#token=<t>`, в БД
  `token_hash == sha256(t)`, `expires_at == now + 30 мин`, одно событие; повторный запрос удаляет прежний токен;
  неизвестный email, невалидный email, заблокированный, без членства, превышен лимит → `None`, токенов и событий нет;
  `policy=None` → `FeatureDisabled`; `create_app` без SMTP даёт `state.password_reset_policy is None`, с SMTP —
  `ResetPolicy`, а `repr` не содержит ключ.
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/domain/test_007_request_reset.py backend/tests/api/test_auth_login.py` зелёный; «Линт бэкенда» чист
- **Попытки:** 2

## R7-T09 — Домен: `confirm_reset`
- **Статус:** DONE
- **AC:** AC-7, AC-8, AC-9, AC-11 (домен), FR-11…FR-14, FR-15 (`completed`)
- **Файлы:** `backend/app/domain/auth/password_reset.py`, `backend/app/domain/auth/service.py`;
  тесты: `backend/tests/domain/test_007_confirm_reset.py` (новый)
- **Зависит от:** R7-T08
- **Описание:** По plan §4.3, PR-15, PR-16, PR-20: `confirm_reset(...)`. В `auth/service.py` только переименовать
  `_remove_initial_admin_file_after_commit` в публичный `remove_initial_admin_file_after_commit` (обновить вызов
  внутри файла) и вызвать его из `confirm_reset` последним действием (вид логина — как `Actor.login` в
  `change_own_password`). Поглощение токена — условный `UPDATE … WHERE used_at IS NULL AND expires_at > now
  RETURNING`. Пользователь — `UPDATE … WHERE NOT is_blocked`. Остальные неиспользованные токены удаляются,
  `sessions.delete_all_for_user`, событие `user.password_reset_completed` (`actor_id=user_id`, workspace как в T08).
  Test-writer: успех (хеш сменился, `used_at` задан, сессии удалены, `must_change_password=false`, в том числе
  если было `true`; `failed_login_count=0`, `login_locked_until=None`; одно событие); повтор → `ResetTokenInvalid`;
  через 30 мин → `ResetTokenInvalid` и пароль прежний; 11 символов / частый пароль → `Unprocessable` с кодом, а
  токен остаётся неиспользованным; заблокирован после выдачи → `ResetTokenInvalid`; токен не-ASCII или
  случайный → `ResetTokenInvalid`; `policy=None` → `FeatureDisabled`; текст исключений не содержит токен и пароль.
  Существующие тесты `change_own_password` проходят.
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/domain/test_007_confirm_reset.py backend/tests/domain/test_auth_service.py backend/tests/api/test_password_change.py` зелёный; «Линт бэкенда» чист
- **Попытки:** 1

## R7-T10 — Admin API: email при создании, `PUT /admin/users/{id}/email`, email в `AdminUser`
- **Статус:** DONE
- **AC:** AC-1 (API), AC-14 (бэкенд: `email` в списке), FR-2
- **Файлы:** `backend/app/api/v1/schemas/admin.py`, `backend/app/api/v1/admin_users.py`; + `backend/tests/admin_support.py` (только `ADMIN_VIEW_FIELDS`: добавить `email`; решение владельца, уточнение плана, зафиксировано оркестратором по замечанию test-writer), `backend/tests/cli/test_openapi.py` (BODY_ROUTES_400).
  `docs/api/openapi.json`, `frontend/src/shared/api/schema.d.ts` (только `bash scripts/gen-api.sh`);
  тесты: `backend/tests/api/test_007_admin_email.py` (новый), `backend/tests/cli/test_openapi.py`
- **Зависит от:** R7-T06
- **Описание:** По plan §4.4: `AdminUser.email: str | None` (docstring «семь полей»), `CreateUserRequest.email:
  str | None = None` (`max_length=254`), `SetEmailRequest {email: str | None}` (`extra="forbid"`). Маршрут
  `PUT /{user_id}/email` → `service.set_email`, ответ `AdminUser`, `responses=error_responses(400, 404, 422) |
  error_response(409, "Email уже используется (code: email_taken)")`. В `test_openapi.py::BODY_ROUTES_400` добавить
  `("PUT", "/api/v1/admin/users/{user_id}/email")`. Перегенерировать API.
  Test-writer: AC-1 через HTTP (409 `email_taken` на `a@X.ru`, пустой и `null` допустимы, 422 `email_invalid`);
  403 для БА/Пользователя/без роли; 401 без входа; 404 чужой id; список и `GET` отдают `email`; событие
  `user.email_changed` в `GET /audit` без значения адреса.
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/api/test_007_admin_email.py backend/tests/api/test_admin_users.py backend/tests/cli/test_openapi.py backend/tests/cli/test_openapi_roles.py backend/tests/infra/test_frontend_api_types.py backend/tests/api/test_route_guards.py` зелёный; «Линт бэкенда» чист
- **Попытки:** 2

## R7-T11 — Публичный API: `GET …/status`, `POST …/request`
- **Статус:** DONE
- **AC:** AC-2 (бэкенд), AC-4, AC-5 (через HTTP), AC-10 (через HTTP), AC-11 (запрос), FR-6, NFR-2
- **Файлы:** `backend/app/api/v1/password_reset.py` (новый), `backend/app/api/v1/schemas/password_reset.py` (новый), `backend/app/api/v1/__init__.py`;
  `docs/api/openapi.json`, `frontend/src/shared/api/schema.d.ts` (только `bash scripts/gen-api.sh`);
  тесты: `backend/tests/conftest.py` (фикстура `reset_api_env`, plan §4.6), `backend/tests/api/test_007_password_reset_api.py` (новый), `backend/tests/api/test_route_guards.py`, `backend/tests/cli/test_openapi.py`
- **Зависит от:** R7-T08, R7-T10
- **Описание:** По plan §4.4, PR-6, PR-8, PR-9, PR-19: роутер `prefix="/auth/password-reset"`, `tags=["auth"]`;
  `password_reset_status` → `PasswordResetStatus {enabled}` (по `app.state.password_reset_policy is not None`);
  `request_password_reset(body, request, db: DbSession, background: BackgroundTasks)` → `request_reset(...,
  client_ip=request.client.host if request.client else None, now=utcnow())`; при письме —
  `background.add_task(deliver, request.app.state.mailer, message)`; ответ 200 `PasswordResetAccepted` с текстом FR-6.
  Подключить в `api/v1/__init__.py`. `PUBLIC` в `test_route_guards.py` и `public` в `test_openapi.py::test_d33_*`
  += `("GET", "/api/v1/auth/password-reset/status")`, `("POST", "/api/v1/auth/password-reset/request")`,
  `("POST", "/api/v1/auth/password-reset/confirm")`. `BODY_ROUTES_400` += оба POST (confirm появится в T12, его можно
  добавить в обе структуры уже сейчас). Перегенерировать API.
  Test-writer: AC-2 (`api_env` без SMTP: request → 404 `feature_disabled`, status → `enabled:false`); AC-4 (plan §6);
  AC-5 через `reset_api_env`; AC-10 через HTTP (4 одинаковых ответа, 3 письма); AC-11 (заблокированный — 0 писем);
  чужой `Origin` → 403 `origin_mismatch`; лишнее поле → 422; ответ без `Set-Cookie`.
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/api/test_007_password_reset_api.py backend/tests/api/test_route_guards.py backend/tests/api/test_deps_gates.py backend/tests/cli/test_openapi.py backend/tests/infra/test_frontend_api_types.py` зелёный (тесты T12 в этом файле допускаются как `xfail`, если test-writer написал их заранее); «Линт бэкенда» чист
- **Попытки:** 2

## R7-T12 — Публичный API: `POST …/confirm`
- **Статус:** DONE
- **AC:** AC-6, AC-7, AC-8, AC-9, AC-11 (через HTTP), FR-11
- **Файлы:** `backend/app/api/v1/password_reset.py`, `backend/app/api/v1/schemas/password_reset.py`;
  `docs/api/openapi.json`, `frontend/src/shared/api/schema.d.ts` (только `bash scripts/gen-api.sh`);
  тесты: `backend/tests/api/test_007_password_reset_api.py`, `backend/tests/cli/test_openapi.py`
- **Зависит от:** R7-T09, R7-T11
- **Описание:** `PasswordResetConfirm {token: SecretStr (max_length=128), new_password: Password}` с
  `_require_encodable` для обоих полей и `extra="forbid"`. `confirm_password_reset(body, request, db)` →
  `confirm_reset(...)` → 204. `responses`: `error_responses(400, 403, 422)` со стандартным описанием 400
  (`test_t68_*`) + `error_response(404, "Функция отключена (code: feature_disabled)")`; `reset_token_invalid`
  описан в docstring. Перегенерировать API.
  Test-writer: AC-6…AC-9, AC-11 по plan §6 (токены берутся из `env.app.state.mailer.sent`); вход новым паролем
  даёт 200, старым — 401; без SMTP → 404 `feature_disabled`; пустое тело → 422; битый JSON → 400 `bad_request`.
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/api/test_007_password_reset_api.py backend/tests/api/test_route_guards.py backend/tests/cli/test_openapi.py backend/tests/infra/test_frontend_api_types.py` зелёный без `xfail`; «Линт бэкенда» чист
- **Попытки:** 1

## R7-T13 — Аудит и утечки: сквозной сценарий
- **Статус:** DONE
- **AC:** AC-12, NFR-1, FR-15
- **Файлы:** тесты: `backend/tests/api/test_007_password_reset_leaks.py` (новый); код — только если тест выявит утечку: `backend/app/domain/auth/password_reset.py` или `backend/app/core/mail.py` (указать причину в отчёте)
- **Зависит от:** R7-T12
- **Описание:** По образцу `backend/tests/api/test_password_leaks.py`: `caplog.set_level(DEBUG)`, сценарий
  request → confirm (в том числе с ошибками 400/422) → login → `GET /api/v1/audit` от ТА. Проверить: в
  `caplog.text`, в телах и заголовках всех ответов (кроме ответа админке со своим email) нет токена, пароля,
  email и `sha256(token).hex()`; в `domain_event` два события по plan §6 (AC-12) без значений; при ошибке
  SMTP (подменённый `Mailer`, который бросает исключение с email в тексте) в логе только имя типа.
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/api/test_007_password_reset_leaks.py backend/tests/api/test_password_leaks.py` зелёный; «Линт бэкенда» чист
- **Попытки:** 1

## R7-T14 — Экспорт/импорт: без `email` и служебных таблиц сброса
- **Статус:** DONE
- **AC:** spec §7 и §8 п.4, ADR-0017 «Последствия» (отдельного AC нет — plan Q-9)
- **Файлы:** `backend/app/domain/ops/archive.py`, `backend/app/domain/ops/export.py`, `backend/app/domain/ops/importer.py`;
  тесты: `backend/tests/cli/test_export_import.py`
- **Зависит от:** R7-T01
- **Описание:** По plan PR-14: `EXCLUDED_TABLES` += `"password_reset_token"`, `"password_reset_attempt"`;
  `EXCLUDED_COLUMNS: Final[Mapping[str, frozenset[str]]] = {"app_user": frozenset({"email"})}`;
  `exported_columns(table: sa.Table) -> list[sa.Column[Any]]`. `export._read_table` выбирает
  `select(*exported_columns(table))`, `importer._decode_table` сверяет `set(row)` с именами
  `exported_columns(table)`. `AUTO_TABLES` начинается с `"password_reset_token", "password_reset_attempt"`.
  Docstring `archive.py` дополнить строкой про исключения.
  Test-writer: пользователь с email и выданным токеном → в `data.json` у `app_user` нет ключа `email`, нет таблиц
  `password_reset_token`/`password_reset_attempt`; импорт в пустую систему → `email IS NULL`; цикл
  export→import→export идентичен; архив с лишним ключом `email` → `ImportRefused`; импорт проходит, когда у
  первого ТА системы-приёмника есть токен сброса.
- **Готово, когда:** `source .venv/bin/activate && pytest -q backend/tests/cli/test_export_import.py backend/tests/cli/test_demo_data.py` зелёный; «Линт бэкенда» чист
- **Попытки:** 1

## R7-T15 — Фронтенд: ключи i18n и подписи действий аудита
- **Статус:** DONE
- **AC:** NFR-3; основа для AC-2, AC-3, AC-13, AC-14; FR-15 (подписи в журнале)
- **Файлы:** `frontend/src/shared/i18n/ru.ts`, `frontend/src/features/admin/AuditPage.tsx`;
  тесты: `frontend/tests/shared/i18n.test.ts`, `frontend/tests/features/admin/AuditPage.test.tsx`
- **Зависит от:** R7-T05
- **Описание:** Добавить все ключи из plan §4.7 (набор ключей фиксирован). В `AuditPage.ACTION_CODES` добавить
  `user.email_changed`, `user.password_reset_requested`, `user.password_reset_completed`. В
  `i18n.test.ts::API_CODES` добавить `feature_disabled`, `reset_token_invalid`, `email_taken`, `email_invalid`.
  Test-writer: новые `error.*` есть, на кириллице, попарно различны; три новых действия в журнале показываются
  русской подписью, а не кодом.
- **Готово, когда:** `cd frontend && npx vitest run tests/shared/i18n.test.ts tests/features/admin/AuditPage.test.tsx` зелёный; «Линт фронтенда» чист
- **Попытки:** 1

## R7-T16 — Фронтенд: API сброса и ссылка «Забыли пароль?» на `/login`
- **Статус:** DONE
- **AC:** AC-2 (фронт), AC-3 (ссылка), AC-15, FR-5, FR-17
- **Файлы:** `frontend/src/features/auth/api.ts`, `frontend/src/features/auth/LoginPage.tsx`;
  тесты: `frontend/tests/features/auth/LoginPage.test.tsx`, `frontend/tests/features/auth/api.test.ts`, `frontend/tests/features/auth/helpers.tsx`
- **Зависит от:** R7-T12, R7-T15
- **Описание:** В `api.ts` — `passwordResetStatus`, `requestPasswordReset`, `confirmPasswordReset` (plan §4.7, только
  через `getAppClient()`, типы из `schema.d.ts`). В `LoginPage` — запрос статуса (`useQuery`, ключ
  `["auth","password-reset-status"]`, `retry:false`, `refetchOnWindowFocus:false`) и `<Link to="/password-reset">`
  с текстом `auth.forgot_password` сразу после формы входа (под кнопкой «Войти»), до `section.ui-login-help`,
  только при `enabled === true`. Блок справки и форма не меняются. Моки `fetch` в `helpers.tsx` должны обслуживать
  `GET /api/v1/auth/password-reset/status`.
  Test-writer: `enabled:false`, ошибка и ожидание ответа → ссылки нет; `enabled:true` → ссылка с
  `href="/password-reset"`, расположена после кнопки «Войти» и до блока справки; существующие тесты 005
  (блок справки) зелёные без правок assert-ов; функции `api.ts` вызывают правильные пути и методы.
- **Готово, когда:** `cd frontend && npx vitest run tests/features/auth` зелёный; «Линт фронтенда» чист
- **Попытки:** 2

## R7-T17 — Фронтенд: экран запроса `/password-reset`
- **Статус:** DONE
- **AC:** AC-3, FR-5, FR-6 (текст ответа)
- **Файлы:** `frontend/src/features/auth/PasswordResetRequestPage.tsx` (новый), `frontend/src/app/router.tsx`;
  тесты: `frontend/tests/features/auth/PasswordResetRequestPage.test.tsx` (новый), `backend/tests/infra/test_frontend_scaffold.py`
- **Зависит от:** R7-T16
- **Описание:** По plan §4.7 и PR-17: экран с `h1` `auth.reset_request_title`, одним полем «Email» и кнопкой
  «Отправить ссылку». Повторная отправка блокируется, пока идёт запрос. Успех → `role="status"` с
  `auth.reset_request_sent`. Ошибка (`feature_disabled`, сеть, 422) → `ErrorAlert` с `errorMessage(code)`. Ссылка
  «Вернуться ко входу» → `/login`. Маршрут `/password-reset` в `AppRoutes` до `*`, без `GuestOnly`. Новый файл
  добавить в белый список `test_t21_src_files_only_expected`.
  Test-writer: на экране ровно одно поле ввода и кнопка «Отправить ссылку»; отправка вызывает
  `POST /api/v1/auth/password-reset/request` с `{email}`; текст успеха; `404 feature_disabled` → сообщение ошибки;
  при открытии `/password-reset` без сессии нет `GET /api/v1/me` и редиректа на `/login`.
- **Готово, когда:** `cd frontend && npx vitest run tests/features/auth tests/app` зелёный; `source .venv/bin/activate && pytest -q backend/tests/infra/test_frontend_scaffold.py` зелёный; «Линт фронтенда» чист
- **Попытки:** 2

## R7-T18 — Фронтенд: экран подтверждения `/password-reset/confirm`
- **Статус:** DONE
- **AC:** AC-13, AC-8 (фронт: без автовхода), FR-10, FR-13
- **Файлы:** `frontend/src/features/auth/PasswordResetConfirmPage.tsx` (новый), `frontend/src/app/router.tsx`;
  тесты: `frontend/tests/features/auth/PasswordResetConfirmPage.test.tsx` (новый), `backend/tests/infra/test_frontend_scaffold.py`
- **Зависит от:** R7-T17
- **Описание:** По plan §4.7 и PR-18: токен из `#token=` читается в ленивом инициализаторе `useState`, затем в
  `useEffect` `window.history.replaceState(window.history.state, "", pathname + search)`. Поля «Новый пароль» и
  «Повторите пароль» (`TextField` с `reveal`, подсказка `PASSWORD_MIN_LENGTH`, как в `ChangePasswordPage`),
  кнопка «Сохранить пароль». Несовпадение → `auth.password_mismatch` без запроса. Успех → `auth.reset_done` +
  ссылка «Войти» на `/login`. `reset_token_invalid` или нет токена → сообщение + ссылка на `/password-reset`.
  Ошибки 422 → `errorMessage(code)`. Маршрут до `*`, без `GuestOnly`; файл — в белый список.
  Test-writer: AC-13 по plan §6; отправка уходит с `{token:"abc", new_password}`; после 204 нет запроса
  `/api/v1/auth/login` и нет перехода, видна ссылка «Войти»; `reset_token_invalid` → ссылка на запрос новой ссылки;
  без фрагмента → сообщение о недействительной ссылке, форма не показана.
- **Готово, когда:** `cd frontend && npx vitest run tests/features/auth tests/app` зелёный; `source .venv/bin/activate && pytest -q backend/tests/infra/test_frontend_scaffold.py` зелёный; «Линт фронтенда» чист
- **Попытки:** 2

## R7-T19 — Фронтенд: email в `UsersPage` (колонка, метка, поле при создании)
- **Статус:** DONE
- **AC:** AC-14, AC-1 (фронт), FR-2 (создание), FR-16
- **Файлы:** `frontend/src/features/admin/api.ts`, `frontend/src/features/admin/UsersPage.tsx`;
  тесты: `frontend/tests/features/admin/UsersPage.test.tsx`, `frontend/tests/features/admin/api.test.ts`
- **Зависит от:** R7-T10, R7-T15
- **Описание:** `createUser` передаёт `email` (пустое поле → `null`); `setUserEmail(userId, email)` →
  `PUT /api/v1/admin/users/{user_id}/email`. В таблице колонка `data-field="email"`: адрес или метка
  `admin.users.email_missing`. В форме создания — необязательное поле `admin.users.email_label`
  (`type="email"`). Ошибки `email_taken`/`email_invalid` показываются тем же механизмом, что `login_taken`.
  Кнопки блокировки, сброса через администратора, ролей не меняются.
  Test-writer: `email:null` → «email не указан»; адрес показан; создание с email отправляет его; без email —
  `null`; 409 `email_taken` → сообщение; сброс через администратора работает как раньше (существующие тесты
  зелёные).
- **Готово, когда:** `cd frontend && npx vitest run tests/features/admin` зелёный; «Линт фронтенда» чист
- **Попытки:** 1

## R7-T20 — Фронтенд: диалог изменения и очистки email
- **Статус:** DONE
- **AC:** FR-2 (изменить/очистить), AC-1 (ошибка при изменении)
- **Файлы:** `frontend/src/features/admin/EmailDialog.tsx` (новый), `frontend/src/features/admin/UsersPage.tsx`;
  тесты: `frontend/tests/features/admin/EmailDialog.test.tsx` (новый), `frontend/tests/features/admin/UsersPage.test.tsx`, `backend/tests/infra/test_frontend_scaffold.py`
- **Зависит от:** R7-T19
- **Описание:** Кнопка «Изменить email» в строке (`aria-label` `admin.users.edit_email_aria`) открывает
  `EmailDialog` (модальный, по образцу `shared/ui/ConfirmDialog.tsx`: фокус, Esc, `aria-labelledby`), поле с
  текущим значением, подсказка `admin.users.email_dialog_hint`, кнопки «Сохранить»/«Отмена». Пустое поле → `null`.
  Успех обновляет строку (инвалидация запроса списка), ошибки `email_taken`/`email_invalid` — в диалоге, диалог
  не закрывается. Новый файл добавить в белый список.
  Test-writer: изменение отправляет `PUT` с новым значением; очистка отправляет `null` и показывает метку
  «email не указан»; 409 → сообщение в диалоге; «Отмена» не отправляет запрос.
- **Готово, когда:** `cd frontend && npx vitest run tests/features/admin` зелёный; `source .venv/bin/activate && pytest -q backend/tests/infra/test_frontend_scaffold.py` зелёный; «Линт фронтенда» чист
- **Попытки:** 1

## R7-T21 — Интеграция и полная проверка
- **Статус:** DONE
- **AC:** AC-15, NFR-6; итоговая сверка всех AC (plan §6)
- **Файлы:** тесты: `frontend/tests/features/auth/007_no_reset_link.test.tsx` (новый); код — только исправления, найденные прогоном, в файлах задач R7-T01…R7-T20 (перечислить в отчёте с причиной)
- **Зависит от:** R7-T03, R7-T13, R7-T14, R7-T18, R7-T20
- **Описание:** Test-writer: на `/change-password` (одноразовый пароль) и `/no-role` нет ссылки «Забыли пароль?» и
  нет запроса статуса сброса. Исполнитель: `bash scripts/gen-api.sh` не меняет файлы (идемпотентность);
  `bash scripts/check.sh` зелёный целиком (ruff, mypy, `alembic check`, все pytest, eslint, typecheck, vitest,
  build). Сверить трассировку plan §6: у каждого AC-1…AC-15 есть зелёный тест; результат — таблица в отчёте.
- **Готово, когда:** `bash scripts/check.sh` завершается с кодом 0; `git status --porcelain docs/api frontend/src/shared/api` пуст после `bash scripts/gen-api.sh`
- **Попытки:** 2
