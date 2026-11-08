# Plan: Замер нормативов для «Сводки» и карточки задачи

- **Spec:** ./spec.md (статус APPROVED, ответы владельца 2026-11-08)
- **Статус:** DRAFT
- **Объём прохода:** вариант (а) решения оркестратора: замер трёх строк — «Сводка»: плитки и список
  с фильтрами; карточка задачи. Счётчик уведомлений — отдельным отчётом после 012 (T-05).

## 1. Подход
Генератор, харнесс и отчёт живут в `feat/r2-perf` и не зависят от «Сводки»: генератор и харнесс
работают с любой версией API. Замер проводится на локальном слиянии `feat/r2-perf` с `fff9338`
(«Сводка», T-03, спека 008) в ветке `measure/016-local`, которая не пушится. Генератор детерминирован:
одинаковый seed даёт одинаковый набор строк, включая id, хеши паролей и метки времени, поэтому
`gtrack export` двух запусков совпадает (AC-1). Стенд — отдельный compose-оверрайд с лимитами
`cpus`/`mem_limit`; основной `docker-compose.yml` не меняется.

## 2. Решения
| Решение | Выбрано | Отвергнутые альтернативы | Почему |
|---|---|---|---|
| Генератор | Новый модуль `domain/ops/load.py` | Расширить `domain/ops/demo.py` | Демо: 30 задач, `uuid4()`, случайные пароли и хеши, события. Для AC-1 нужна полная детерминированность и масштаб 50 000 |
| id строк | UUID из `random.Random(seed)` (`version=4`) | `uuid4()`, `uuid5` | `uuid4` недетерминирован; `uuid5` потребовал бы отдельного пространства имён без выигрыша |
| Метки времени | Константа `ANCHOR = 2026-11-08T09:00Z`, `created_at` идёт назад от него | `utcnow()` | Без константы «сегодня» и срок при повторном запуске разойдутся |
| Пароли и хеши | Пароль = производный от `seed` и логина (SHA-256), соль Argon2 = производная от `seed` и логина, `hash_secret` (`argon2.low_level`) | Случайный пароль, файл как в demo | Хеш Argon2 в `app_user.password_hash` попадает в архив; случайная соль сломает AC-1. Пароль известен по seed, поэтому `load-data` отказывает при `ENV=production` (код 1) |
| Аудит-события | Не пишутся | `record_event` как в demo | Массовая синтетика; события проектов и задач и так не пишутся (D-55). Для пользователей добавляет только шум и недетерминированные `id` |
| Уведомления | Не генерируются | Генерировать | Таблицы уведомлений нет (012/T-05 не слита) |
| Пользователи | 12 строк: 1 ТА, 2 БА, 9 «Пользователь»; плюс первый ТА из `bootstrap` | 12 сверх | Совпадает с демо-схемой; тестовый пользователь `load.user1` — участник всех проектов (худший случай для «Сводки») |
| Состав объёма | `--tasks N` = всего задач, из них подзадачи `N // 10`; 8 проектов | Отдельный параметр подзадач | Соответствует формулировке «50 000 задач с подзадачами» |
| Отказ в непустую систему | Код 2: есть проекты, задачи или пользователи сверх первого ТА | Проверка только задач | Повторяет `demo-data` (FR-1) |
| Харнесс | `domain/ops/load_measure.py`: асинхронный httpx; CLI — тонкая обёртка | Логика в CLI | Слои AGENTS: CLI не содержит бизнес-логики; модуль тестируется без процесса |
| Выборка | `--samples S` = замеров на **каждого** клиента на операцию; итого `clients × S` на операцию (по умолчанию 5 × 100 = 500 ≥ 100) | `S` — итого на операцию | Удовлетворяет «≥ 100», p95 точнее |
| Прогрев | 10 раундов всех операций одним клиентом до замера; размер страницы 50 | Без прогрева | ТЗ §5: «кэш прогрет, 50 элементов на странице» |
| Перцентили | nearest-rank: p50, p95, max | Интерполяция | Простая воспроизводимая формула |
| Вердикт карточки | Каждый из двух запросов карточки (`/tasks/{id}`, `/comments`) против 200 мс | Суммарное время карточки | Строже; совпадает с построчной таблицей FR-2. Вложения не реализованы (см. §8) |
| Операции | Кортеж `OPERATIONS` в модуле (имя, путь, бюджет p95, подбор параметров) | Жёстко в коде | Счётчик уведомлений и вложения добавляются строкой, без переделки |
| Авторизация харнесса | `POST /api/v1/auth/login` на каждого клиента; логин и пароль из параметров или `GT_LOAD_LOGIN` / `GT_LOAD_PASSWORD` | Пароль в аргументах по умолчанию | Не хранить секреты в репозитории и истории shell |
| httpx | Перенос из dev в runtime, версия `>=0.28` | Новая зависимость | Уже транзитивная через `mcp`; вес нулевой. Правка `tests/arch/test_dependencies_allowlist.py` |
| CI (FR-4) | Тест `backend/tests/load/test_load_smoke.py` в существующем job `backend` (`pytest backend/tests`) | Новый job в `ci.yml` | Не трогаем `.github` (задача: без лишней правки CI) |
| Стенд | `deploy/compose.load.yml`: `COOKIE_SECURE=false`, `ENV=local`, `cpus: "3"`, `mem_limit: 6g` на api и db, порт API на `127.0.0.1` | Правка `docker-compose.yml` | Основной compose не меняется; `COOKIE_SECURE=true` не даёт httpx отправить cookie по http |

## 3. Затрагиваемые модули и файлы
- `specs/016-load-measurement/plan.md`, `tasks.md` — новые.
- `backend/app/domain/ops/load.py` — новый: детерминированный генератор, `load_synthetic_data`, `LoadReport`, `LoadDataRefused`.
- `backend/app/cli/commands/load_data.py` — новый: `gtrack load-data --tasks N --seed S`.
- `backend/app/domain/ops/load_measure.py` — новый: `OPERATIONS`, `percentile`, `measure(...)`, отчёт в виде строк.
- `backend/app/cli/commands/load_measure.py` — новый: `gtrack load-measure`.
- `backend/app/cli/main.py` — регистрация двух подкоманд.
- `backend/pyproject.toml` — httpx переносится в runtime.
- `backend/tests/arch/test_dependencies_allowlist.py` — httpx в `BACKEND_RUNTIME`, из `BACKEND_DEV` убрать.
- `backend/tests/cli/test_load_data.py` — AC-1, AC-2.
- `backend/tests/domain/test_load_measure.py` — перцентили, конфигурация операций.
- `backend/tests/load/test_load_smoke.py` — FR-4 (CI).
- `deploy/compose.load.yml` — новый стенд.
- `docs/acceptance/load-2026-11-08.md` — отчёт (FR-3), после замера.

## 4. Интерфейсы
```python
# domain/ops/load.py
ANCHOR: Final = datetime(2026, 11, 8, 9, 0, tzinfo=UTC)
LOAD_TEST_LOGIN: Final = "load.user1"

class LoadDataRefused(Exception): ...        # код 2
def derive_password(seed: int, login: str) -> str: ...
async def load_synthetic_data(sessionmaker, settings, *, seed: int, tasks: int) -> LoadReport: ...

@dataclass(frozen=True)
class LoadReport:
    users: int; projects: int; tasks: int; subtasks: int; comments: int

# domain/ops/load_measure.py
@dataclass(frozen=True)
class Operation:
    name: str                 # подпись строки отчёта
    path: str                 # шаблон пути, например "/api/v1/tasks/{task_id}"
    budget_p95_ms: int        # норматив
    kind: Literal["tiles", "list", "task", "comments"]

OPERATIONS: Final[tuple[Operation, ...]]
def percentile(values: Sequence[float], q: float) -> float: ...   # nearest-rank
async def measure(*, base_url, login, password, clients, samples, warmup_rounds,
                  transport=None) -> MeasureResult
```

Формат stdout `gtrack load-measure`: строки `ключ=значение`, по одной на операцию
(`operation=… n=… p50_ms=… p95_ms=… max_ms=… budget_p95_ms=… verdict=ok|exceeds`). Код 0, если все
запросы вернули 2xx; иначе 1. Пороги на код выхода не влияют (FR-4).

## 5. Данные и эксперименты
- Источник: синтетика генератора; NFR-2 — сети нет.
- Seed: явный (`--seed`, обязательный). Итоговый прогон — seed 16.
- Smoke для CI: 500 задач, 10 замеров на клиента (FR-4).
- Объём: 50 000 задач (45 000 верхнего уровня + 5 000 подзадач), 45 000 комментариев (среднее ~1 на задачу верхнего уровня).
- Статусы: todo 30 %, in_progress 30 %, review 15 %, done 25 %. Приоритеты: low 30 %, medium 50 %, high 20 %.
- Сроки: без срока 12 %; просрочено (−30…−1 дн) 15 %; сегодня 8 %; завтра 5 %; ближайшая неделя 20 %; позже 40 %.
- Пересчёт «сегодня» — по Europe/Moscow от `ANCHOR`, т.е. 2026-11-08.

## 6. Тестовая стратегия и трассировка
| AC | Где реализуется | Тест (уровень) |
|----|-----------------|----------------|
| AC-1 | `domain/ops/load.py` | `tests/cli/test_load_data.py::test_same_seed_same_export` (committed, интеграция с БД; тот же `build_payload`, что у `gtrack export`, без `exported_at`) |
| AC-2 | `cli/commands/load_data.py` | `tests/cli/test_load_data.py::test_nonempty_system_refused_exit_2` (committed) |
| FR-2 | `domain/ops/load_measure.py` | `tests/domain/test_load_measure.py` (перцентили, отбор операций, отказ при non-2xx) |
| FR-3 | `docs/acceptance/load-2026-11-08.md` | ручной замер на стенде (AC-3) |
| AC-4 / FR-4 | `tests/load/test_load_smoke.py` | pytest в CI-job `backend`; код 0, порогов нет |

Тестовая БД — `*_test`. Для локальных прогонов поднимается отдельный PG (`gt-perf-test-pg`, порт 55440, удаляется после работ).

## 7. Зависимости
- httpx — перенос из dev в runtime. Обоснование: харнесс — часть CLI `gtrack`, который ставится в образ; httpx уже входит через `mcp` (вес 0). Альтернатива (`urllib`) не даёт асинхронных параллельных клиентов без потоков и сложнее в тесте.

## 8. Риски и ограничения
- **Вложения:** `GET /tasks/{id}/attachments` отсутствует во всех ветках (011 не реализована). Строка не замеряется, помечается «не реализовано».
- **Счётчик уведомлений:** `GET /me/notifications` отсутствует (012/T-05). Строка не замеряется, в отчёте «отложено до 012».
- **FR-4 в feat/r2-perf:** маршрутов «Сводки» здесь нет, поэтому смоук-тест пропускается с явной причиной (`skipif`, проверка маршрутов приложения), а не скрыто. После слияния 008 в main пропуск исчезает.
- **Лимиты стенда:** `cpus` и `mem_limit` заданы на каждый сервис (api и db по 3 vCPU / 6 ГБ), как в брифе. Суммарная квота стенда при этом 6 vCPU / 12 ГБ, а не 3 / 6. Это отмечено в отчёте как ограничение методики.
- **Хост:** Docker Desktop VM в этом окружении: 18 vCPU, 8 ГБ памяти; клиент замера работает на хосте, чтобы не делить CPU с API.
- **Пароли синтетики** общеизвестны по seed: `load-data` отказывает при `ENV=production`.
- **Миграции:** в `fff9338` новых миграций нет (head = 0009), замер не требует миграции; если «Сводка» не уложится, см. шаг 6 брифа.
