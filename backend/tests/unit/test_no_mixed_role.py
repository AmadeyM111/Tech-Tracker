"""R3-T12 (plan D-16): охрана от возврата роли `mixed` (spec 002 FR-1, FR-21, NFR-1)."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
APP_DIR = REPO_ROOT / "backend" / "app"
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"
OPENAPI_JSON = REPO_ROOT / "docs" / "api" / "openapi.json"
SCHEMA_DTS = FRONTEND_SRC / "shared" / "api" / "schema.d.ts"

# История журнала (D-14): единственные места фронтенда, где `mixed` законно.
FRONTEND_MIXED_ALLOWED = {
    "features/admin/AuditPage.tsx",
    "shared/i18n/ru.ts",
}

# mixed/смешан - без учёта регистра. Аббревиатура «СМ» - только заглавными: иначе
# ложные срабатывания на «см.» («смотри») в docstring и строках.
BACKEND_FORBIDDEN = re.compile(r"(?i:mixed|смешан)|\bСМ\b")
MIXED_WORD = re.compile(r"mixed", re.IGNORECASE)


def _hits(path: Path, pattern: re.Pattern[str]) -> list[str]:
    rel = path.relative_to(REPO_ROOT)
    out: list[str] = []
    for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if pattern.search(line):
            out.append(f"{rel}:{no}: {line.strip()[:120]}")
    return out


def _fail_message(title: str, hits: list[str]) -> str:
    return f"{title}:\n" + "\n".join(f"  {h}" for h in hits)


def test_fr1_backend_app_has_no_mixed_role_mentions() -> None:
    """FR-1, FR-21: в backend/app нет mixed/MIXED/СМ/«смешан»."""
    files = sorted(APP_DIR.rglob("*.py"))
    assert files, f"не найдены файлы в {APP_DIR}"
    hits = [h for f in files for h in _hits(f, BACKEND_FORBIDDEN)]
    assert not hits, _fail_message("упоминания смешанной роли в backend/app", hits)


def test_fr21_frontend_mixed_only_in_audit_history_files() -> None:
    """FR-21, D-14: `mixed` во frontend/src только в AuditPage.tsx и ru.ts."""
    files = sorted([*FRONTEND_SRC.rglob("*.ts"), *FRONTEND_SRC.rglob("*.tsx")])
    assert files, f"не найдены файлы в {FRONTEND_SRC}"
    hits: list[str] = []
    for f in files:
        if f.relative_to(FRONTEND_SRC).as_posix() in FRONTEND_MIXED_ALLOWED:
            continue
        hits.extend(_hits(f, MIXED_WORD))
    assert not hits, _fail_message("`mixed` вне файлов истории журнала во frontend/src", hits)


def test_frontend_allowed_files_still_exist() -> None:
    """Защита самого теста: список разрешённых файлов не устарел."""
    for rel in FRONTEND_MIXED_ALLOWED:
        assert (FRONTEND_SRC / rel).is_file(), f"нет файла {rel}: обновите список D-14"


def test_nfr1_generated_api_artifacts_have_no_mixed() -> None:
    """NFR-1, FR-1: в openapi.json и schema.d.ts нет `mixed`."""
    hits: list[str] = []
    for f in (OPENAPI_JSON, SCHEMA_DTS):
        assert f.is_file(), f"нет файла {f}"
        hits.extend(_hits(f, MIXED_WORD))
    assert not hits, _fail_message("`mixed` в сгенерированных артефактах API", hits)
