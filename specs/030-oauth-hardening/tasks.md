# Tasks: усиление OAuth (030)

Статусы: TODO | IN_PROGRESS | DONE | BLOCKED. Статусы ведёт оркестратор. Spec APPROVED 2026-11-13.

## O30-T01 — allowlist redirect URI и потолок refresh
- **Статус:** DONE · **AC:** AC-1…AC-5 · **Оценка:** 0,5 дня
- **Файлы:** `backend/app/core/config.py`, `backend/app/domain/oauth/service.py`, `backend/app/api/v1/oauth.py`, `backend/tests/api/test_028_oauth.py`, `README.md`, `specs/028-mcp-oauth/spec.md`
- **Готово, когда:** `pytest -q backend/tests/api/test_028_oauth.py` зелёный; миграций нет.
