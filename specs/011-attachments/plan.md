# Plan: Вложения к задачам (011)

- **Spec:** ./spec.md (APPROVED 2026-11-08; пометки **[Q-n]** подтверждены ответами)
- **Статус:** APPROVED

## 1. Подход
Модель `attachment` (миграция `0012`, `down_revision="0011"`), домен `domain/attachments/`:
`types.py` (чистое определение типа по расширению и сигнатуре), `storage.py` (потоковая запись во
временный файл в `DATA_DIR/attachments/`, sha256, атомарная публикация, удаление), `service.py`
(права, лимиты, события), `queries.py` (список, чтение для скачивания). Роутер `api/v1/attachments.py`.
Загрузка — сырое тело запроса (`request.stream()`), без multipart. Окончательное удаление —
`gtrack maintenance` (счётчики `attachments_purged`, `files_removed`, `orphan_files_removed`).
Экспорт/импорт — члены `files/<ключ>`.

## 2. Решения
| Решение | Выбрано | Отвергнутые | Почему |
|---|---|---|---|
| PA-1 Транспорт | `POST /tasks/{id}/attachments?name=…`, тело — файл | `multipart/form-data` | без новой зависимости `python-multipart`; потоковая запись |
| PA-2 Тип | расширение + сигнатура; OOXML — zip с `[Content_Types].xml`, без `vbaProject.bin`/`macroEnabled` | `Content-Type` клиента; libmagic | клиенту не верим; без нативных зависимостей |
| PA-3 Ключ | `uuid4().hex`, путь `attachments/<ключ[:2]>/<ключ>` | имя файла | обход путей невозможен (FR-5) |
| PA-4 Порядок | файл → `flush` строки → `commit`; при ошибке файл удаляется; сироты чистит maintenance | строка → файл | нет строки без файла (NFR-1) |
| PA-5 Отдача | `FileResponse` + заголовки FR-6; `inline` только картинки | `inline` по типу | SVG/HTML никогда не исполняются **[Q-1]** |
| PA-6 Диск | `shutil.disk_usage(DATA_DIR)` до приёма, порог `ATTACHMENTS_MIN_FREE_MB` **[Q-2]** | без проверки | R2-40 |
| PA-7 Кодировка текста | UTF-8 (+ cp1251 **[Q-3]**), без NUL | любая | защита от бинарников под `.txt` |

## 3. Файлы
- `backend/app/core/config.py` (`attachments_min_free_mb`), `backend/app/core/errors.py` (`storage_full`, `attachment_empty`).
- `backend/app/domain/attachments/{__init__,models,types,storage,service,queries}.py`; `domain/registry.py`; `domain/ops/archive.py` (импорт модели).
- `backend/migrations/versions/0012_attachments.py`; `docs/data-model.md`.
- `backend/app/api/v1/attachments.py`, `schemas/attachments.py`, `api/v1/__init__.py`; OpenAPI.
- `backend/app/domain/ops/maintenance.py` (очистка), `export.py`/`importer.py`/`archive.py` (`files/`).
- `frontend/src/features/attachments/{Attachments.tsx,api.ts}`, `features/tasks/TaskPage.tsx`, `shared/i18n/ru.ts`.

## 4. Интерфейсы
```python
class FileKind(StrEnum): PDF, DOCX, XLSX, PPTX, TXT, CSV, PNG, JPEG, GIF, WEBP
def detect_kind(name: str, head: bytes, path: Path) -> FileKind: ...   # Unprocessable(attachment_type_not_allowed)
async def store_stream(root: Path, chunks: AsyncIterator[bytes], *, max_bytes: int) -> StoredFile: ...
async def add_attachment(db, actor, task_id, *, name: str, chunks, settings) -> AttachmentView: ...
async def delete_attachment(db, actor, attachment_id) -> None: ...
async def list_attachments(db, actor, task_id) -> list[AttachmentView]: ...
async def open_attachment(db, actor, attachment_id, settings) -> tuple[AttachmentView, Path]: ...
```
HTTP: `GET/POST /api/v1/tasks/{task_id}/attachments`, `GET /api/v1/attachments/{id}/content`,
`DELETE /api/v1/attachments/{id}`.

## 5. Трассировка
| AC | Тест |
|---|---|
| AC-1…AC-7, AC-9 | `backend/tests/api/test_011_attachments.py` |
| AC-2 | `backend/tests/unit/test_011_types.py` (синтетические файлы, без реальных документов) |
| AC-7 (очистка) | `backend/tests/cli/test_011_maintenance.py` |
| AC-8 | API + аудит |
| AC-10 | `backend/tests/cli/test_export_import.py` (расширение круга) |
| AC-11 | `frontend/tests/features/attachments/Attachments.test.tsx` |

## 6. Зависимости
Новых нет (`zipfile`, `hashlib` из стандартной библиотеки).

## 7. Риски
- Zip-бомба в OOXML: читается только оглавление zip (`namelist`), содержимое не распаковывается.
- Экспорт большого тома: `files/` пишется потоково, в память не читается.
