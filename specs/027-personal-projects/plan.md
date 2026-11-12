# Plan: Личные проекты «Пользователя» (027)

- **Статус:** APPROVED 2026-11-11 (спека и ADR-0024 одобрены владельцем). Этапы: spec.md раздел 8а.
- **Дата:** 2026-11-11

## 1. Архитектурное решение
Глобальная роль не меняется. Управляющие права владельца-«Пользователя» выражаются через проверку «актор — владелец проекта» в `domain/access/policy.py`, а не через новую роль или новую возможность. Право создания проекта получает `USER` через `ROLE_CAPABILITIES`. Схема БД не меняется.

## 2. Изменения по модулям
| Модуль | Изменение | Связь с FR |
|---|---|---|
| `backend/app/domain/access/roles.py` | `Role.USER` получает `Capability.PROJECT_CREATE` | FR-1 |
| `backend/app/domain/access/policy.py` | `ProjectFacts.actor_is_owner`; функция `is_project_admin(a, p) = a.role is BA and actor_is_member or (a.role is USER and p.actor_is_owner)`; её применение в `can_manage_project`, `can_manage_members`, `can_change_assignee`, `can_edit_task_fully`, `can_delete_comment`, `is_own_project`; `can_create_task` для назначения другому | FR-2, FR-3 |
| `backend/app/domain/projects/queries.py` | `load_project_facts` вычисляет `actor_is_owner` (тот же запрос, без доп. выборки) | FR-2 |
| `backend/app/domain/projects/members.py` | `add_member` принимает логин или email (точное совпадение, email в нижнем регистре); ответ `recipient_not_found` для незарегистрированного; ограничение частоты (Q-7) | FR-4 |
| `backend/app/domain/access/recipients.py` | владелец-«Пользователь» допустим, если проект его собственный | FR-9 |
| `backend/app/domain/users/directory.py` | для «Пользователя» фильтр `EXISTS` общего проекта (включая себя); для БА без изменений | FR-5 |
| `backend/app/domain/projects/service.py` | передача владения: только участник с ролью «Пользователь» или БА (FR-7); удаление владельцем (FR-8) | FR-7, FR-8 |
| `backend/app/api/v1/schemas/projects.py` | тело добавления участника: `{login}` или `{email}` вместо `user_id` (с переходом: `user_id` остаётся для БА до смены клиента) | FR-4 |
| `backend/app/api/mcp/tools/projects.py` | новый инструмент `create_project` | FR-11 |
| `backend/app/api/mcp/server.py` | без изменений логики; список инструментов зависит от `PROJECT_CREATE` | FR-11 |
| `frontend/src/features/projects/*` | кнопка «Создать проект» для «Пользователя»; поле «логин или email» в участниках для владельца; скрытие BA-только контролов | FR-1, FR-4 |
| `docs/api/openapi.json`, `frontend/src/shared/api/schema.d.ts` | перегенерация после изменения контракта | FR-4 |

## 3. Миграции
Не нужны. Используются: `project.owner_id`, PK `project_member (project_id, user_id)`, индекс `project_member.user_id`, уникальный `app_user.email`. Если Q-4 даст лимиты, счётчик — запрос `COUNT`, без колонки.

## 4. Аудит
Существующие события: `project.created`, `member.added`, `member.removed`, передача владения, удаление проекта. Добавляется только актор-«Пользователь» в поле `actor` (уже пишется). Новых типов событий и миграции журнала нет.

## 5. Тесты (по каждому пути, см. AC)
- Unit: `tests/unit/test_policy.py` (матрица «владелец-П / участник-П / БА» по каждой функции), `test_role_matrix.py` (новая строка `PROJECT_CREATE`), `test_recipients.py` (владелец-П).
- API: `tests/api/test_projects.py` (создание U), `test_project_members.py` (добавление по логину и email, `recipient_not_found`, лимит), `test_project_task_list.py`, `test_board.py`, `test_comments.py`, `test_activity.py`, `test_attachments*.py` — отказ для не-владельца-П и успех для владельца-П.
- Справочник: `test_directory*` — общий проект, без общего, БА без изменений.
- MCP: `test_m20_t08_mcp_tools.py` — число инструментов для «Пользователя» и `create_project`; регрессия по БА.
- Существующие тесты, которые фиксируют «создание проекта — только БА» и «П не видит справочник», обновляются явно и перечисляются в PR.

## 6. Риски
- Пропущенный путь, где проверка `role is BUSINESS_ADMIN` осталась без `is_project_admin` (вложения, комментарии, вложенные подзадачи). Смягчение: поиск по `Capability.PROJECT_MANAGE_ANY`, `TASK_ASSIGN_OTHERS`, `role is Role.BUSINESS_ADMIN` в `backend/app` и тест отказа на каждом пути.
- Перебор аккаунтов через добавление по email (Q-7).
- Изменение контракта `POST /projects/{id}/members` — клиенты и MCP должны обновиться в одном PR.

## 7. Порядок работ
1. Утверждение ADR-0024 и ответы на Q-1…Q-10 владельцем.
2. Правка спек 001 и 002 (по таблице из spec.md раздела 7) отдельным PR.
3. Реализация по задачам tasks.md, каждая с тестами отказа.
