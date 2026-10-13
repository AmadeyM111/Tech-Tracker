#!/usr/bin/env bash
# Каркас OSS-трекера: AGENTS.md, документы проекта, OSS-обвязка, скелет backend/frontend.
# Запуск из пустой папки проекта:  bash install-tracker.sh
set -euo pipefail

put() {  # put <путь>  (содержимое из stdin), не перезаписывает существующее
  if [ -e "$1" ]; then echo "  пропуск (уже есть): $1"; cat >/dev/null; else
    mkdir -p "$(dirname "$1")"; cat > "$1"; echo "  создан: $1"; fi
}

echo "Каталоги:"
mkdir -p docs/brief docs/research docs/adr specs/_templates \
         backend/app/api backend/app/core backend/app/domain backend/tests \
         frontend scripts .github/ISSUE_TEMPLATE
echo "  ok"

echo "Файлы:"

put AGENTS.md <<'EOF'
# AGENTS.md — OSS-трекер (задачи, проекты, воронка продаж, цели)

Инструкции для кодовых агентов. Правила обязательны, команды проверяй запуском.

## Команды

```bash
# первичная установка
python3 -m venv .venv && source .venv/bin/activate
pip install -e "backend[dev]"
docker compose up -d db                 # PostgreSQL на localhost:5432

# разработка
uvicorn app.main:app --reload --app-dir backend     # API на :8000, /docs — Swagger
cd frontend && npm run dev                          # фронт на :5173

# проверки — ОБЯЗАТЕЛЬНЫ перед тем, как считать задачу сделанной
bash scripts/check.sh                   # линтер + типы + тесты, backend и frontend
pytest -q backend/tests                 # только backend-тесты
ruff check backend && ruff format --check backend
cd frontend && npm run lint && npm run typecheck && npm test

# миграции (любое изменение модели = новая миграция)
alembic -c backend/alembic.ini revision --autogenerate -m "<описание>"
alembic -c backend/alembic.ini upgrade head
```

## Структура

```
backend/app/
  api/        HTTP-слой: роутеры, схемы запросов/ответов, зависимости
  domain/     бизнес-логика и модели: tasks, boards, deals, projects, users
  core/       конфиг, БД, аутентификация, общие утилиты
backend/tests/      тесты (pytest + httpx AsyncClient)
frontend/src/
  features/   фичи по доменам: tasks, boards, deals
  shared/     UI-кит, api-клиент, хуки
docs/         ТЗ, решения, состояние проекта (см. «Где что искать»)
specs/        спецификации по SDD: spec.md, plan.md, tasks.md
```

## Архитектурные правила

- **Слои не смешиваются.** Роутер принимает запрос, валидирует, вызывает сервис из
  `domain/`, возвращает схему. Бизнес-логики и запросов к БД в роутерах нет.
- **Мультиарендность.** Каждая доменная сущность принадлежит `workspace_id`.
  Любой запрос к БД фильтруется по рабочему пространству текущего пользователя.
  Запрос без такого фильтра — ошибка, даже если тест проходит.
- **Права.** Проверка прав — в сервисном слое, а не в UI. Фронт прячет кнопку,
  бэкенд обязан вернуть 403 сам.
- **Миграции.** Изменил модель — создай миграцию Alembic в том же коммите.
  Правка существующих применённых миграций запрещена.
- **API.** REST, версионирование `/api/v1`. Схемы — Pydantic. Ответ с ошибкой —
  единый формат `{"detail": ..., "code": ...}`. Ломающие изменения API требуют
  записи в `docs/adr/`.
- **Время.** В БД и API только UTC, ISO 8601. Часовой пояс — забота фронта.
- **Деньги** (суммы сделок) — целое число копеек/центов плюс код валюты.
  Никаких float.
- **Удаление** — мягкое (`deleted_at`), данные по сделкам и задачам не теряем.
- **Аудит.** Изменения сделок, стадий воронки и прав пишутся в журнал аудита.

## Фронтенд

- TypeScript strict, `any` запрещён. Серверное состояние — через TanStack Query,
  локальное — через хуки; глобальный стор только с обоснованием в ADR.
- Типы API генерируются из OpenAPI, руками не дублируются.
- Компоненты без запросов к API напрямую: данные приходят из хуков `features/*/api`.

## Тесты

- Каждый сценарий API: успех, 401/403, валидация, граничный случай.
- Тесты не ходят в интернет и не зависят от порядка выполнения.
- БД для тестов — отдельная, поднимается фикстурой и откатывается транзакцией.
- Фикстуры-фабрики вместо копипасты объектов.

## Открытый исходный код

- Язык кода, комментариев, имён веток и коммитов — английский.
  Документация в `docs/` — русский, `README.md` — двуязычный.
- Коммиты: Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`).
- Лицензия — см. `LICENSE`. Зависимости с несовместимой лицензией (GPL в ядро)
  не добавлять; сомнительные случаи — в ADR.
- Любая новая зависимость обосновывается в плане задачи: зачем, альтернативы, вес.
- Секреты только в `.env` (есть `.env.example`), в репозиторий не коммитятся.
  Тестовые данные синтетические, без реальных клиентов и сотрудников.

## Чего не делать

- Не выполнять `git push` и не трогать чужие ветки.
- Не ослаблять тесты и проверки прав, чтобы прогон стал зелёным.
- Не менять `docs/brief/*` — это вход, а не рабочий документ.
- Не запускать деструктивные операции с БД вне тестового окружения
  (`drop`, `truncate`, удаление томов).
- Не добавлять телеметрию, аналитику и внешние вызовы без явного решения в ADR.

## Где что искать

- Исходное ТЗ и рамки MVP: `docs/brief/` (только чтение)
- Состояние проекта: `docs/STATE.md`
- Принятые решения: `docs/adr/`
- Термины домена: `docs/glossary.md`
- Спецификация текущей работы: `specs/<активная папка>/spec.md` — источник истины

При противоречии ТЗ и спецификации остановись и спроси, не выбирай сам.
EOF

put docs/brief/vision.md <<'EOF'
# Задача (исходное ТЗ)

Создать Open Source трекер для удобной работы внутри команды в огромной корпорации
с воронкой продаж клиентов, ведением проектов, целями команды и задачами сотрудников.

Существующие закрытые аналоги: Kaiten, Pyrus, Битрикс24, EvaTeam, Yandex Tracker, Weeek.

---
Файл не редактируется: это вход. Все уточнения — в specs/*/spec.md и docs/adr/.
EOF

put docs/brief/scope-mvp.md <<'EOF'
# Рамки первого релиза

Решение принято 2026-10-13, см. docs/adr/0002-scope-mvp.md.

## В MVP
- **Задачи и доски:** рабочие пространства, проекты, задачи, канбан-доски и колонки,
  статусы, исполнители, сроки, комментарии, вложения.
- **Воронка продаж:** клиенты и контакты, сделки, стадии воронки, сумма и валюта
  сделки, связь сделки с проектом, перенос сделки между стадиями.
- **Минимум прав:** роли владельца, участника и наблюдателя внутри рабочего
  пространства. Без этого воронку нельзя показывать в корпорации.

## Не в MVP (бэклог)
- Цели команды и OKR с прогрессом.
- SSO (LDAP/SAML/OIDC), SCIM, полноценная ролевая модель, журнал аудита для всего.
- Отчёты и дашборды, автоматизации и правила, импорт из аналогов,
  мобильные приложения, вебхуки и публичный API для интеграций.

## Критерии готовности MVP
Заполнить при написании spec.md: сколько пользователей, объём данных, время отклика,
сценарии, которые команда должна пройти без обходных путей.
EOF

put docs/research/competitors.md <<'EOF'
# Разбор аналогов

Цель: не копировать, а понять, какие сущности и связи обязательны, а что лишнее.
Заполняется по публичной документации продуктов; ставьте ссылки и дату проверки.

| Продукт | Задачи и доски | Воронка продаж | Цели/OKR | Связь сделка→проект | Права и SSO | Чем примечателен | Источник, дата |
|---|---|---|---|---|---|---|---|
| Kaiten |  |  |  |  |  |  |  |
| Pyrus |  |  |  |  |  |  |  |
| Битрикс24 |  |  |  |  |  |  |  |
| EvaTeam |  |  |  |  |  |  |  |
| Yandex Tracker |  |  |  |  |  |  |  |
| Weeek |  |  |  |  |  |  |  |

## Выводы
- Обязательный минимум сущностей:
- Чего не хватает во всех (наша возможность):
- Что сознательно не делаем:
EOF

put docs/glossary.md <<'EOF'
# Термины домена

Единый словарь: эти имена используются в коде, API и интерфейсе.
Код — на английском, интерфейс — на русском.

| Русский | English (код) | Значение |
|---|---|---|
| Рабочее пространство | workspace | Верхний контейнер: команда или подразделение. Граница данных и прав |
| Проект | project | Набор задач с целью и сроком |
| Задача | task | Единица работы: исполнитель, статус, срок |
| Доска | board | Канбан-представление задач проекта |
| Колонка | column | Стадия задачи на доске |
| Клиент | account | Компания-контрагент |
| Контакт | contact | Человек на стороне клиента |
| Сделка | deal | Потенциальная продажа: сумма, валюта, стадия |
| Стадия воронки | stage | Этап сделки в воронке |
| Воронка | pipeline | Упорядоченный набор стадий |
| Цель | objective | Цель команды (бэклог) |
| Ключевой результат | key result | Измеримый результат цели (бэклог) |
EOF

put docs/STATE.md <<'EOF'
# Состояние проекта

Обновляется после каждой завершённой задачи. Дата последнего обновления: 2026-10-13.

## Сейчас
Этап: инициализация. Кода нет, кроме скелета backend с эндпоинтом здоровья.

## Готовность по рамкам MVP
| Блок | Статус | Где код | Чего не хватает |
|---|---|---|---|
| Задачи и доски | нет | — | всё |
| Воронка продаж | нет | — | всё |
| Роли и права | нет | — | всё |
| Инфраструктура (БД, миграции, CI) | частично | backend/, docker-compose.yml | alembic, CI, тестовая БД |

## Ближайшие шаги
1. Заполнить docs/research/competitors.md — разбор аналогов.
2. `/sdd Модель данных и API рабочих пространств, проектов и задач` — первая спецификация.
3. Поднять CI: линтер, типы, тесты на каждый PR.

## Известные проблемы
—
EOF

put docs/adr/0001-stack.md <<'EOF'
# ADR-0001. Технологический стек

- **Дата:** 2026-10-13
- **Статус:** принято

## Решение
Backend: Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, PostgreSQL.
Frontend: React 18 + TypeScript + Vite, TanStack Query.
Запуск: Docker Compose; цель — self-hosted установка одной командой.

## Причины
- Низкий порог входа для контрибьюторов, большой пул разработчиков.
- FastAPI даёт OpenAPI из коробки: типы фронта генерируются из схемы.
- PostgreSQL закрывает требования к связям, транзакциям и отчётности.

## Альтернативы и почему отвергнуты
- **NestJS + Prisma:** один язык на бэке и фронте, но команда ближе к Python.
- **Django + HTMX:** быстрее до MVP и есть админка, но доски требуют богатого
  клиентского взаимодействия (drag-and-drop, живые обновления).
- **Go:** лучше по производительности и деплою, но выше порог входа для OSS-вклада.

## Последствия
- Нужен слой генерации TS-типов из OpenAPI.
- Два набора инструментов проверки (ruff/mypy и eslint/tsc) — закрыто scripts/check.sh.
EOF

put docs/adr/0002-scope-mvp.md <<'EOF'
# ADR-0002. Объём первого релиза

- **Дата:** 2026-10-13
- **Статус:** принято

## Решение
В MVP входят задачи с досками и воронка продаж, плюс минимальная ролевая модель.
Цели (OKR) и корпоративная обвязка (SSO, SCIM, аудит, отчёты) — в бэклог.

## Причины
- Задачи и доски — ядро: на них опираются и сделки, и будущие цели.
- Воронка продаж отличает трекер от обычного таск-менеджера и закрывает сценарий,
  ради которого в корпорации обычно держат отдельную CRM.
- SSO и аудит сильно удлиняют первый релиз, но не проверяют основную гипотезу.

## Последствия
- Модель данных сразу проектируется с `workspace_id`, чтобы позже добавить SSO
  и полноценные права без переписывания.
- Цели в MVP не реализуются, но сущности задач и проектов не должны мешать их
  появлению: предусмотреть связь «задача → цель» на уровне модели данных.
EOF

put docs/adr/TEMPLATE.md <<'EOF'
# ADR-NNNN. <Название решения>

- **Дата:** YYYY-MM-DD
- **Статус:** предложено | принято | заменено ADR-NNNN

## Решение
Что решили, одним абзацем.

## Причины
Почему так.

## Альтернативы и почему отвергнуты
- …

## Последствия
Что это означает для кода и будущих задач.
EOF

put README.md <<'EOF'
# <project-name>

Open source трекер для команд: проекты и задачи на досках, воронка продаж,
цели команды. Самостоятельное размещение, без привязки к облаку вендора.

> Проект в начальной стадии. Текущее состояние — `docs/STATE.md`.

## Быстрый старт

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e "backend[dev]"
cp .env.example .env
docker compose up -d db
uvicorn app.main:app --reload --app-dir backend
```

API: http://localhost:8000/docs

## Документация
- Рамки первого релиза: `docs/brief/scope-mvp.md`
- Архитектурные решения: `docs/adr/`
- Термины: `docs/glossary.md`
- Как участвовать: `CONTRIBUTING.md`

## Лицензия
См. `LICENSE`.

---

# <project-name> (English)

Open source team tracker: projects and tasks on boards, sales pipeline, team goals.
Self-hosted. Early stage — see `docs/STATE.md`.
EOF

put CONTRIBUTING.md <<'EOF'
# Как участвовать

## Процесс
1. Обсудите задачу в issue до того, как писать код.
2. Ветка от `main`: `feat/<краткое-имя>`, `fix/<краткое-имя>`.
3. Коммиты — Conventional Commits, на английском: `feat: add deal stages`.
4. Перед PR: `bash scripts/check.sh` — должно быть зелёным.
5. В PR опишите, что сделано, и приложите ссылку на issue.

## Требования к коду
- Правила проекта — в `AGENTS.md`, они обязательны и для людей, и для агентов.
- Изменение модели данных = миграция Alembic в том же PR.
- Новая функциональность = тесты на успех, отказ в правах и валидацию.
- Архитектурное решение = ADR в `docs/adr/`.

## Использование ИИ-агентов
Приветствуется. Автор PR отвечает за результат: код, сгенерированный агентом,
должен быть прочитан, проверен тестами и понятен автору.
EOF

put SECURITY.md <<'EOF'
# Безопасность

О найденных уязвимостях сообщайте приватно: <security@example.org>.
Не открывайте публичный issue до исправления.

Срок первичного ответа — 3 рабочих дня.
EOF

put CODE_OF_CONDUCT.md <<'EOF'
# Кодекс поведения

Проект следует Contributor Covenant 2.1.
Нарушения сообщайте на <conduct@example.org>.
EOF

put LICENSE <<'EOF'
TODO: выберите лицензию до первой публикации.

Рекомендация для корпоративного OSS: Apache License 2.0 — разрешает коммерческое
использование и явно регулирует патенты, что важно для принятия в крупных компаниях.
Текст: https://www.apache.org/licenses/LICENSE-2.0.txt

Альтернативы: MIT (проще, без патентной оговорки),
AGPL-3.0 (защищает от закрытых SaaS-форков, но многие корпорации его не пропускают).
EOF

put .env.example <<'EOF'
DATABASE_URL=postgresql+asyncpg://tracker:tracker@localhost:5432/tracker
SECRET_KEY=change-me
ENV=local
EOF

put docker-compose.yml <<'EOF'
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_USER: tracker
      POSTGRES_PASSWORD: tracker
      POSTGRES_DB: tracker
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
volumes:
  pgdata:
EOF

put backend/pyproject.toml <<'EOF'
[project]
name = "tracker-backend"
version = "0.0.1"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "sqlalchemy>=2.0",
    "alembic>=1.13",
    "asyncpg>=0.30",
    "pydantic-settings>=2.6",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.24", "httpx>=0.28", "ruff>=0.7", "mypy>=1.13"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"

[tool.mypy]
strict = true
ignore_missing_imports = true
EOF

put backend/app/main.py <<'EOF'
"""Точка входа API."""

from fastapi import FastAPI

app = FastAPI(title="Tracker API", version="0.0.1")


@app.get("/api/v1/health")
async def health() -> dict[str, str]:
    """Проверка живости сервиса."""
    return {"status": "ok"}
EOF

put backend/tests/test_health.py <<'EOF'
from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_ok() -> None:
    response = TestClient(app).get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
EOF

put frontend/README.md <<'EOF'
# Frontend

Пока не инициализирован. Первый шаг (делается в рамках отдельной задачи SDD):

```bash
npm create vite@latest . -- --template react-ts
npm install @tanstack/react-query
```

Требования к коду — в `AGENTS.md`, раздел «Фронтенд».
EOF

put scripts/check.sh <<'EOF'
#!/usr/bin/env bash
# Полная проверка проекта. Должна быть зелёной перед каждым PR.
set -uo pipefail
status=0

run() { echo; echo "=== $* ==="; "$@" || status=1; }

run ruff check backend
run ruff format --check backend
run mypy backend/app
run pytest -q backend/tests

if [ -f frontend/package.json ]; then
  ( cd frontend && npm run lint && npm run typecheck && npm test ) || status=1
else
  echo; echo "=== frontend: ещё не инициализирован, пропуск ==="
fi

echo
[ $status -eq 0 ] && echo "ВСЁ ЗЕЛЁНОЕ" || echo "ЕСТЬ ОШИБКИ"
exit $status
EOF
chmod +x scripts/check.sh 2>/dev/null || true

put .github/PULL_REQUEST_TEMPLATE.md <<'EOF'
## Что сделано

## Связанный issue
Closes #

## Чеклист
- [ ] `bash scripts/check.sh` зелёный
- [ ] Изменения модели сопровождаются миграцией Alembic
- [ ] Добавлены тесты: успех, отказ в правах, валидация
- [ ] Запросы к БД фильтруются по `workspace_id`
- [ ] Архитектурное решение зафиксировано в `docs/adr/` (если применимо)
EOF

put .github/ISSUE_TEMPLATE/bug.yml <<'EOF'
name: Баг
description: Что-то работает не так
labels: [bug]
body:
  - type: textarea
    attributes: {label: Что произошло}
    validations: {required: true}
  - type: textarea
    attributes: {label: Шаги воспроизведения}
    validations: {required: true}
  - type: textarea
    attributes: {label: Ожидаемое поведение}
    validations: {required: true}
  - type: input
    attributes: {label: Версия и окружение}
EOF

put .github/ISSUE_TEMPLATE/feature.yml <<'EOF'
name: Доработка
description: Предложение по функциональности
labels: [enhancement]
body:
  - type: textarea
    attributes: {label: Задача пользователя, description: "Как <роль>, я хочу <действие>, чтобы <ценность>"}
    validations: {required: true}
  - type: textarea
    attributes: {label: Критерии приёмки, description: Given / When / Then}
    validations: {required: true}
  - type: textarea
    attributes: {label: Как это решают аналоги}
EOF

put .editorconfig <<'EOF'
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space

[*.py]
indent_size = 4

[*.{ts,tsx,js,json,yml,yaml,md}]
indent_size = 2
EOF

echo ".gitignore:"
touch .gitignore
for line in ".venv/" "__pycache__/" "*.pyc" ".env" ".env.*" "!.env.example" "node_modules/" "dist/" ".pytest_cache/" ".mypy_cache/" ".ruff_cache/" ".DS_Store" ".claude/settings.local.json"; do
  grep -qxF "$line" .gitignore || { echo "$line" >> .gitignore; echo "  + $line"; }
done

if [ ! -d .claude/agents ]; then
  echo
  echo "ВНИМАНИЕ: SDD-kit не установлен. Выполните в этой папке: bash install-sdd.sh"
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git init -q && echo "git: репозиторий создан"
fi

echo
echo "Готово. Дальше:"
echo "  1) выберите лицензию (LICENSE) и имя проекта (README.md)"
echo "  2) pip install -e 'backend[dev]' && bash scripts/check.sh"
echo "  3) claude → /sdd Модель данных и API рабочих пространств, проектов и задач"
