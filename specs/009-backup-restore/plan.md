# Plan: Резервная копия и восстановление (009)

- **Spec:** ./spec.md (APPROVED 2026-11-08)
- **Статус:** APPROVED

## 1. Подход
Доменный модуль `domain/ops/backup.py` (снятие, проверка, ротация, восстановление) и
`domain/ops/backup_status.py` (чтение статуса). Внешние инструменты — `pg_dump`/`pg_restore`
через `subprocess` с паролем в `PGPASSWORD`. Архив — tar из трёх членов, собирается во временном
файле в `DIR`, проверяется и переименовывается атомарно. Журнал запусков — таблица `backup_run`
(миграция `0011`). CLI `gtrack backup`/`gtrack restore` — тонкие подкоманды. API статуса — роутер
`api/v1/admin_system.py` под гейтом `manage_accounts`. Плашка — в оболочке экранов ТА.

## 2. Решения
| Решение | Выбрано | Отвергнутые альтернативы | Почему |
|---|---|---|---|
| PB-1 Где снимать | `gtrack backup` в контейнере api, клиент PG16 в образе (PGDG) | скрипт хоста с `docker exec db` | решение D-1 (CLI), одна логика для всех установок; хостовой скрипт — временный |
| PB-2 Формат | один `.tar`: `db.dump`, `appdata.tar`, `manifest.json` | каталог файлов (`scripts/backup.sh`) | R2-25 «один архив», ротация по файлам |
| PB-3 Атомарность | `.gtrack-backup-<ts>.partial` → проверка → `os.replace` | запись сразу под итоговым именем | ротация и статус не видят незавершённые |
| PB-4 Согласованность | `pg_dump` (снимок транзакции) → затем tar `DATA_DIR` | блокировка записи | без остановки (R2-25); файл, загруженный между шагами, — сирота, его чистит maintenance |
| PB-5 `backup_run` | глобальная таблица без `workspace_id` (как `app_user`) | `workspace_id` | копия — всей БД, не пространства |
| PB-6 Порог | `stale`: нет `ok`, или `ok` старше 26 ч, или последний запуск `failed` | только возраст | упавший запуск виден сразу |
| PB-7 Права | `require_capability(MANAGE_ACCOUNTS)` | `VIEW_AUDIT` | эксплуатационная функция ТА, как учётные записи |
| PB-8 Restore | только в пустую БД и пустой `DATA_DIR` | DROP DATABASE | безопасно по умолчанию; поверх — `scripts/restore.sh` |
| PB-9 Настройки | `BACKUP_DIR=/backups`, `BACKUP_KEEP=14`, `BACKUP_STALE_HOURS=26` | хардкод | оператор меняет переменной |
| PB-10 Предупреждение bootstrap | только при неприменённых миграциях, порог 24 ч | всегда | не шумит на обычном старте |

## 3. Файлы
- `backend/app/core/config.py` — `backup_dir`, `backup_keep`, `backup_stale_hours`.
- `backend/app/domain/ops/backup.py`, `backup_status.py`, `backend/app/domain/ops/models.py` (`BackupRun`) — новые.
- `backend/app/domain/registry.py` — регистрация модели.
- `backend/migrations/versions/0011_backup_run.py` — новая (`down_revision="0009"`; перед слиянием с 019 → `"0010"`).
- `backend/app/cli/commands/backup.py`, `restore.py`, `backend/app/cli/main.py`; `bootstrap.py` (FR-9).
- `backend/app/api/v1/admin_system.py`, `schemas/admin_system.py`, `api/v1/__init__.py`; OpenAPI через `scripts/gen-api.sh`.
- `frontend/src/features/admin/BackupBanner.tsx`, `api.ts`, `app/router.tsx`, `shared/i18n/ru.ts`; плашка — один запрос при открытии экрана ТА, без опроса.
- `backend/Dockerfile` (postgresql-client-16), `deploy/backup/compose.backup.yml` (bind каталога хоста в `/backups`; поставляемый compose не меняется), `deploy/backup/*` (юниты хоста), `README.md`, `docs/data-model.md`, `docs/acceptance/backup-restore-drill.md`.
- `.github/workflows/ci.yml` — установка `postgresql-client-16` для интеграционных тестов.

## 4. Интерфейсы
```python
@dataclass(frozen=True)
class BackupResult: path: Path; size_bytes: int; schema_revision: str; same_device: bool; removed: int

def create_backup(settings: Settings, out_dir: Path, *, schema_revision: str, now: datetime,
                  keep: int, runner: Runner = run_tool) -> BackupResult: ...
def verify_backup(path: Path, *, runner: Runner = run_tool) -> Manifest: ...
def rotate(out_dir: Path, keep: int) -> list[Path]: ...
def restore_backup(settings: Settings, archive: Path, *, runner: Runner = run_tool) -> Manifest: ...
async def record_run(db, run: BackupRunRecord) -> None: ...
async def backup_status(db, *, now: datetime, stale_hours: int) -> BackupStatus: ...
```
`Runner = Callable[[list[str], Mapping[str,str], BinaryIO | None, BinaryIO | None], None]` — обёртка над
`subprocess.run(check=True)`; тесты подменяют её для AC-3 и AC-13.

HTTP: `GET /api/v1/admin/system/backup` →
`{last_success_at, last_success_size_bytes, last_run_at, last_run_status, stale, stale_after_hours}`.

## 5. Данные
Тесты — синтетические фабрики, БД `*_test`; `pg_dump` 16 должен быть в `PATH` (иначе интеграционные
тесты `skip` с причиной; в CI ставится пакет).

## 6. Трассировка
| AC | Где | Тест |
|---|---|---|
| AC-1, AC-2, AC-4, AC-6 | `backup.py` | `test_009_backup.py` (интеграция, pg_dump) |
| AC-3, AC-13 | `backup.py`, `Runner` | unit с подменой runner |
| AC-5 | `record_run` | интеграция |
| AC-7, AC-8 | `admin_system.py`, `backup_status.py` | API |
| AC-9, AC-10 | `restore_backup` | интеграция (отдельная БД `*_restore_test`) |
| AC-11 | `bootstrap.py` | CLI-тест |
| AC-12 | `BackupBanner.tsx` | vitest |
| AC-14 | — | протокол вручную |

## 7. Зависимости
Python — новых нет. Образ api: `postgresql-client-16` из apt.postgresql.org (ключ PGDG, только на
этапе сборки; NFR-3 о рантайме не нарушается). Альтернативы: копирование бинарников из `postgres:16`
(другая версия Debian, хрупко), клиент 15 из bookworm (не дампит сервер 16).

## 8. Риски
- Размер образа +~15 МБ. Сборка требует доступа к apt.postgresql.org.
- Bind-каталог хоста должен принадлежать uid 10001 — шаг в README.
- `same_device` внутри контейнера определяется по `st_dev` точек монтирования и может не распознать
  один физический диск за разными устройствами — это предупреждение, не гарантия.
