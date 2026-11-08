# Tasks: Замер нормативов для «Сводки» и карточки задачи

Статусы: TODO | IN_PROGRESS | DONE | BLOCKED. Статусы ведёт оркестратор.

Общие условия: тестовая БД — `TEST_DATABASE_URL=postgresql+asyncpg://tracker:tracker@127.0.0.1:55440/tracker_test`
(отдельный контейнер `gt-perf-test-pg`); pytest — `pytest -q backend/tests`; линтер и типы — по AGENTS.md.

## T01 — Plan и tasks
- **Статус:** DONE
- **AC:** —
- **Файлы:** `specs/016-load-measurement/plan.md`, `specs/016-load-measurement/tasks.md`
- **Зависит от:** —
- **Описание:** короткий план и список задач по spec 016 с решениями (детерминизм, харнесс, стенд).
- **Готово, когда:** файлы закоммичены и запушены в `origin/feat/r2-perf` (fast-forward).
- **Попытки:** 1

## T02 — Генератор `load-data`: модуль и тесты AC-1, AC-2
- **Статус:** TODO
- **AC:** AC-1, AC-2 (FR-1, NFR-2)
- **Файлы:** `backend/app/domain/ops/load.py`, `backend/tests/cli/test_load_data.py`
- **Зависит от:** T01
- **Описание:** детерминированный генератор: 12 пользователей, 8 проектов, 50 000 задач (включая подзадачи), комментарии; id, хеши и метки времени из seed; отказ `LoadDataRefused` при непустой системе. Тесты: два запуска с одним seed дают одинаковый `build_payload` без `exported_at`; непустая система → отказ.
- **Готово, когда:** `pytest -q backend/tests/cli/test_load_data.py` зелёный на `*_test`.
- **Попытки:** 0

## T03 — Команда `gtrack load-data`
- **Статус:** TODO
- **AC:** AC-2 (FR-1)
- **Файлы:** `backend/app/cli/commands/load_data.py`, `backend/app/cli/main.py`
- **Зависит от:** T02
- **Описание:** подкоманда `load-data --tasks N --seed S`. Коды: 0 — успех; 2 — отказ (непустая система); 1 — ошибка БД, конфигурации, `ENV=production`. В stdout — `ключ=значение`.
- **Готово, когда:** `gtrack load-data --help` работает; тест кода 2 проходит.
- **Попытки:** 0

## T04 — Харнесс `load-measure`: модуль и тесты
- **Статус:** TODO
- **AC:** AC-3 (FR-2), основа для FR-4
- **Файлы:** `backend/app/domain/ops/load_measure.py`, `backend/app/cli/commands/load_measure.py`, `backend/app/cli/main.py`, `backend/tests/domain/test_load_measure.py`, `backend/pyproject.toml`, `backend/tests/arch/test_dependencies_allowlist.py`
- **Зависит от:** T01
- **Описание:** `OPERATIONS` как конфиг (плитки, список с фильтрами, задача, комментарии); прогрев 10 раундов; `clients` параллельных httpx-клиентов с логином; nearest-rank p50/p95/max; non-2xx → код 1. httpx переносится в runtime (allowlist).
- **Готово, когда:** тесты перцентилей и отказа при non-2xx зелёные; allowlist-тест зелёный.
- **Попытки:** 0

## T05 — Смоук для CI (FR-4)
- **Статус:** TODO
- **AC:** AC-4 (FR-4)
- **Файлы:** `backend/tests/load/test_load_smoke.py`
- **Зависит от:** T02, T04
- **Описание:** 500 задач, 10 замеров на клиента, in-process ASGI-транспорт, без порогов; код 0. Пропускается с явной причиной, если в приложении нет маршрутов «Сводки» (до слияния 008).
- **Готово, когда:** тест зелёный в feat/r2-perf (пропуск с причиной) и в measure/016-local (полный прогон).
- **Попытки:** 0

## T06 — Стенд: compose-оверрайд
- **Статус:** TODO
- **AC:** NFR-1
- **Файлы:** `deploy/compose.load.yml`
- **Зависит от:** —
- **Описание:** `cpus: "3"`, `mem_limit: 6g` на api и db; `COOKIE_SECURE=false`, `ENV=local`; порт API на `127.0.0.1`. Основной `docker-compose.yml` не меняется.
- **Готово, когда:** `docker compose -p gtperf -f docker-compose.yml -f deploy/compose.load.yml config` проходит.
- **Попытки:** 0

## T07 — Слияние для замера (локально, не пушить)
- **Статус:** TODO
- **AC:** AC-3
- **Файлы:** — (ветка `measure/016-local`)
- **Зависит от:** T02–T06
- **Описание:** `measure/016-local` от `feat/r2-perf`, влить `fff9338`; минимальные конфликты решать только для замера.
- **Готово, когда:** ветка собрана, `pytest` по `load` и `cli/test_load_data.py` зелёный.
- **Попытки:** 0

## T08 — Замер на стенде и отчёт
- **Статус:** TODO
- **AC:** AC-3 (FR-3)
- **Файлы:** `docs/acceptance/load-2026-11-08.md`
- **Зависит от:** T07
- **Описание:** `load-data --tasks 50000 --seed 16`, прогрев, `load-measure --clients 5 --samples 100`; отчёт: железо, версии, хеши, таблица p95, вердикты. Счётчик уведомлений — «отложено до 012»; вложения — «не реализовано».
- **Готово, когда:** отчёт в `feat/r2-perf`; стенд удалён (`down -v`).
- **Попытки:** 0

## T09 — Проверки и push
- **Статус:** TODO
- **AC:** —
- **Файлы:** —
- **Зависит от:** T02–T05, T08
- **Описание:** `ruff check backend`, `ruff format --check backend`, `mypy --config-file backend/pyproject.toml backend/app`, pytest новых тестов; по возможности `bash scripts/check.sh` с логом. Push: `git push origin feat/r2-perf` (без force).
- **Готово, когда:** коды выхода 0 (или зафиксированные отличия); push fast-forward.
- **Попытки:** 0
