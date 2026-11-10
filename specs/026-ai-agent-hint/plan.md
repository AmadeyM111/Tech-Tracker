# Plan: Карточка «Подключить ИИ-агента» (026)

- **Spec:** ./spec.md (DRAFT) · **ADR:** 0024 (черновик)
- **Статус:** DRAFT

## 1. Подход
Закрытые подсказки хранятся в новой таблице `user_hint_dismissal(user_id, hint_key, dismissed_at)` (миграция `0014`, аддитивная).
`GET /me` получает поле `dismissed_hints` (один запрос по `user_id`); закрытие и возврат — `POST`/`DELETE
/api/v1/me/hints/{key}/dismiss`. Допустимые ключи — константа (`ai_agent`); остальное — 404. Фронт: компонент
`AiAgentHint` на «Сводке» читает `dismissed_hints` из уже загруженного профиля, закрывает оптимистично с откатом при
ошибке; кнопка возврата — в «Профиле». Таблица, а не столбец `app_user`, чтобы следующие подсказки не требовали миграций.

## 2. Решения
| Решение | Выбрано | Отвергнутые | Почему |
|---|---|---|---|
| PH-1 Хранение | таблица `user_hint_dismissal` | столбец `app_user.hints text[]`; `localStorage` | расширяемо без новых миграций; серверное состояние по ТЗ (T-13 F5) |
| PH-2 Чтение | поле в `GET /me` | отдельный `GET /me/hints` | нет лишнего запроса и мигания карточки при загрузке |
| PH-3 Идемпотентность | `INSERT … ON CONFLICT DO NOTHING`; `DELETE` без ошибки при отсутствии | 409 на повтор | повторные клики и гонки безопасны |
| PH-4 Ключи | белый список в коде | произвольные строки | нет мусора в таблице; 404 на неизвестный |
| PH-5 Аудит | не пишется | событие в `domain_event` | настройка интерфейса, не бизнес-данные |
| PH-6 Инструкция | решает Q-3 (рекомендация: блок на «Доступ для агентов») | внешняя ссылка | приложение не раздаёт `docs/` |

## 3. Затрагиваемые файлы
- `backend/migrations/versions/0014_user_hint_dismissal.py`, `backend/app/domain/users/hints.py` (модель, функции), `backend/app/domain/registry.py`, `docs/data-model.md`.
- `backend/app/api/v1/me.py`, `schemas/auth.py` (`MeResponse.dismissed_hints`), новый роутер `hints` (в `api/v1/__init__.py`).
- `docs/api/openapi.json`, `frontend/src/shared/api/schema.d.ts`.
- `frontend/src/features/overview/AiAgentHint.tsx` (новый), `SummaryPage.tsx`, `summary.css` (или `hints.css`), `frontend/src/features/auth/*` (тип профиля), `frontend/src/features/auth/ProfilePage.tsx` (кнопка возврата), `shared/i18n/ru.ts`.
- Тесты: `backend/tests/db/test_026_schema.py`, `backend/tests/api/test_026_hints.py`, `frontend/tests/features/overview/AiAgentHint.test.tsx`; обновить проверки голов миграций (как при 0011–0013: `test_migrations`, `test_007_schema` и др.).
- Документация: `docs/ai-integration.md` (если Q-3 — блок в приложении, текст берётся оттуда).

## 4. Интерфейсы
```python
HINT_KEYS: Final = frozenset({"ai_agent"})
async def dismissed_hints(db, user_id) -> list[str]: ...
async def dismiss_hint(db, user_id, key) -> None: ...   # ON CONFLICT DO NOTHING
async def restore_hint(db, user_id, key) -> None: ...
```
HTTP: `POST|DELETE /api/v1/me/hints/{key}/dismiss` → 204 | 401 | 404; `GET /api/v1/me` + `dismissed_hints: list[str]`.

## 5. Тестовая стратегия и трассировка
| AC | Тест |
|---|---|
| AC-2, AC-3, AC-5, AC-6 | `test_026_hints.py` (API) |
| AC-10 | `test_026_schema.py` + `test_migrations.py` (upgrade/downgrade) |
| AC-1, AC-4, AC-7, AC-8, AC-9 | `AiAgentHint.test.tsx`, словарь `ru.ts` |

## 6. Риски
- Поле в `GET /me` расширяет контракт ответа (аддитивно); клиенты MCP его не используют.
- Номер миграции `0014` может быть занят к моменту старта R3 — проверить REGISTRY и ветки.
- Текст карточки пока предложение; изменения текста после утверждения владельцем — только словарь.
