# Plan: Упоминания и уведомления (012)

- **Spec:** ./spec.md (APPROVED 2026-11-08) · **Статус:** APPROVED

## 1. Подход
Таблицы `comment_mention` и `notification` (миграция `0013`, `down_revision="0012"`). Домен
`domain/notifications/`: `mentions.py` (разбор `@логин`, чистая функция), `producer.py` (правила FR-3,
вызывается из сервисов задач и комментариев в той же транзакции), `queries.py` (список, счётчик с
фильтром актуального членства и неудалённых сущностей), `due.py` (FR-4). CLI `gtrack notify-due`.
Роутер `api/v1/notifications.py`. Фронт: значок в `Sidebar`, страница `/notifications`, подсказка `@`.

## 2. Решения
| Решение | Выбрано | Отвергнутые | Почему |
|---|---|---|---|
| PN-1 Где создавать | явные вызовы `producer` из `tasks/service.py`, `comments/service.py` | триггеры БД; разбор `domain_event` | прозрачно, в одной транзакции (NFR-2), тестируемо |
| PN-2 Повторы | `UNIQUE (recipient_id, kind, task_id, dedup_key)`; `dedup_key` = id события/комментария или `due:<дата>:<порог>` | проверка перед вставкой | гонки и повторный запуск безопасны (`ON CONFLICT DO NOTHING`) |
| PN-3 Видимость | фильтр в запросе: получатель — участник проекта сейчас, задача и проект не удалены, комментарий не удалён | удаление строк при выходе из проекта | возвращение в проект возвращает историю; без фоновых задач |
| PN-4 Счётчик | `COUNT(*) WHERE read_at IS NULL` + PN-3, индекс `(recipient_id, read_at, created_at)` | денормализованный счётчик | p95 ≤ 200 мс достижим индексом |
| PN-5 Упоминание | регулярка `(?<![\w.@])@([a-z0-9_.-]{2,32})` по `login` (нижний регистр) | markdown-разбор | e-mail не совпадает (AC-2) |

## 3. Файлы
`backend/app/domain/notifications/*`, `backend/migrations/versions/0013_notifications.py`,
`backend/app/domain/{tasks,comments}/service.py`, `backend/app/api/v1/notifications.py`, `schemas/notifications.py`,
`backend/app/cli/commands/notify_due.py`, `backend/app/cli/main.py`, `deploy/backup/` → `deploy/timers/` (таймер `notify-due`),
`frontend/src/features/notifications/*`, `app/router.tsx`, `features/comments/Comments.tsx`, `shared/i18n/ru.ts`, `docs/data-model.md`.

## 4. Трассировка
| AC | Тест |
|---|---|
| AC-1, AC-4 | `backend/tests/domain/test_012_producer.py` (таблица событий) |
| AC-2, AC-3 | `backend/tests/unit/test_012_mentions.py`, `backend/tests/api/test_012_mentions.py` |
| AC-5 | `backend/tests/cli/test_012_notify_due.py` (FixedClock, граница МСК) |
| AC-6, AC-7 | `backend/tests/api/test_012_notifications.py` |
| AC-8 | `frontend/tests/features/notifications/*.test.tsx` |

## 5. Зависимости
Новых нет. **Оценка:** ~4 дня.

## 6. Изменения по ревью (2026-11-08)
- «Срок прошёл» — для сроков от «сегодня − 30 дней» до вчера (FR-4).
- Получатели — только роли `user` и `business_admin` (ТА уведомлений не получает, FR-7).
- Перенос на доске: статус «до» читается под блокировкой колонок; комментарий — исполнитель/автор
  перечитываются после блокировки задачи.
- `@логин.`/`@логин-`: проверяются оба варианта (с концевым символом и без).
