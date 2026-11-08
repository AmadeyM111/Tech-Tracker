# Plan: Роли БД и защита журнала (010)

- **Spec:** ./spec.md (APPROVED 2026-11-08)
- **Статус:** APPROVED

## 1. Подход
Модуль `core/db_roles.py`: пароль рабочей роли (файл секрета), SCRAM-верификатор, идемпотентное
создание роли и выдача прав, URL API под рабочей ролью. `gtrack bootstrap` под владельцем (DSN
`DATABASE_URL`) после миграций вызывает `ensure_app_role` под той же advisory-блокировкой. Lifespan API
строит движок по `app_database_url(settings)`. Схема БД не меняется.

## 2. Решения
| Решение | Выбрано | Отвергнутые | Почему |
|---|---|---|---|
| PR-1 Владелец | `POSTGRES_USER` (как сейчас) | новая роль-владелец + `REASSIGN OWNED` | без переноса владения и простоя; процесс API всё равно без привилегий (Q-1) |
| PR-2 Где создаётся роль | `gtrack bootstrap` | миграция alembic | роль — объект кластера, пароль — секрет установки; миграции переносимы между стендами |
| PR-3 Пароль на сервер | `ALTER ROLE … PASSWORD 'SCRAM-SHA-256$…'` (верификатор считается в Python) | открытый пароль в SQL | открытый текст не попадает в `log_statement`/`pg_stat_statements` |
| PR-4 Права | `GRANT` на все таблицы при каждом bootstrap, затем `REVOKE` лишнего у `domain_event`, `alembic_version` | `ALTER DEFAULT PRIVILEGES` | явно и повторяемо; новые таблицы получают права при следующем старте |
| PR-5 Выключатель | `DB_APP_ROLE` (compose: `gtrack_app`); пусто + `ENV=production` → отказ старта API | всегда включено | разработка и тесты без ролей кластера |
| PR-6 CLI-команды | под `DATABASE_URL` | под рабочей ролью | операторские, нужны права владельца (restore, import) |

## 3. Файлы
- `backend/app/core/config.py` — `db_app_role`.
- `backend/app/core/db_roles.py` — новый.
- `backend/app/cli/commands/bootstrap.py` — вызов после миграций.
- `backend/app/main.py` — движок API по рабочей роли, FR-7.
- `docker-compose.yml` — `DB_APP_ROLE: ${DB_APP_ROLE:-gtrack_app}` у api.
- `README.md` — раздел «Переход на рабочую роль БД».
- Тесты: `backend/tests/unit/test_010_scram.py`, `backend/tests/db/test_010_app_role.py`,
  `backend/tests/api/test_010_api_runs_as_app_role.py`, `backend/tests/cli/test_010_bootstrap_role.py`.

## 4. Интерфейсы
```python
APP_PASSWORD_FILE = "db_app_password"
def ensure_app_password(settings: Settings) -> str: ...          # создаёт файл 0600 при отсутствии
def scram_verifier(password: str, *, salt: bytes | None = None, iterations: int = 4096) -> str: ...
async def ensure_app_role(conn: AsyncConnection, role: str, verifier: str) -> None: ...
def app_database_url(settings: Settings) -> str: ...              # DATABASE_URL с user=role, password=файл
```
Имя роли проверяется регуляркой `[a-z_][a-z0-9_]{0,62}` (идентификатор без кавычек).

## 5. Трассировка
| AC | Тест |
|---|---|
| AC-1, AC-2, AC-3, AC-5 | `db/test_010_app_role.py` (уникальная роль на тест, удаляется) |
| AC-4 | `api/test_010_api_runs_as_app_role.py` (committed, движок под ролью) |
| AC-6 | `cli/test_010_bootstrap_role.py`, `unit/test_010_scram.py` |
| AC-7 | `unit/test_010_scram.py` (lifespan) |
| AC-8 | вручную, стенд |

## 6. Зависимости
Новых нет (`hashlib`, `hmac`, `secrets`).

## 7. Риски
- Роли общие для кластера: тестовые роли получают уникальные имена и удаляются в фикстуре.
- `REVOKE` на `domain_event` зависит от того, что `PUBLIC` не имеет прав на таблицы (по умолчанию так).
