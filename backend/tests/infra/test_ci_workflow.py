"""T27: CI workflow GitHub Actions и локальная проверка (NFR-10, N-6).

Статический разбор ``.github/workflows/ci.yml``, ``scripts/check.sh`` и ``backend/pyproject.toml``.
Сам CI не запускается (первый прогон проверяет человек после push).
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.infra_static

REPO = Path(__file__).resolve().parents[3]
WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"


@pytest.fixture(scope="module")
def raw() -> str:
    assert WORKFLOW.is_file(), "нет .github/workflows/ci.yml"
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def wf(raw: str) -> dict[Any, Any]:
    data = yaml.safe_load(raw)
    assert isinstance(data, dict)
    return data


@pytest.fixture(scope="module")
def jobs(wf: dict[Any, Any]) -> dict[str, dict[str, Any]]:
    j = wf.get("jobs")
    assert isinstance(j, dict)
    return j


def _job(jobs: dict[str, dict[str, Any]], name: str) -> dict[str, Any]:
    assert name in jobs, f"нет задания {name}; есть: {sorted(jobs)}"
    return jobs[name]


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    steps = job.get("steps")
    assert isinstance(steps, list) and steps
    return steps


def _runs(job: dict[str, Any]) -> list[str]:
    return [str(s["run"]) for s in _steps(job) if "run" in s]


def _runs_text(job: dict[str, Any]) -> str:
    return "\n".join(_runs(job))


def _uses(job: dict[str, Any]) -> list[str]:
    return [str(s["uses"]) for s in _steps(job) if "uses" in s]


def _job_text(job: dict[str, Any]) -> str:
    return yaml.safe_dump(job, allow_unicode=True)


# --- общие свойства ------------------------------------------------------------------------


def test_nfr10_workflow_parses_and_has_four_jobs(jobs: dict[str, dict[str, Any]]) -> None:
    assert {"backend", "frontend", "contract", "infra"} <= set(jobs)


def _triggers(wf: dict[Any, Any]) -> dict[str, Any]:
    triggers = wf.get("on", wf.get(True))  # YAML 1.1: ключ ``on`` разбирается как True
    assert isinstance(triggers, dict), "on: должен быть отображением с push и pull_request"
    return triggers


def test_nfr10_triggers_push_and_pull_request(wf: dict[Any, Any]) -> None:
    assert {"push", "pull_request"} <= set(_triggers(wf))


def test_nfr10_push_only_main_so_pull_requests_do_not_run_twice(wf: dict[Any, Any]) -> None:
    push = _triggers(wf)["push"]
    assert isinstance(push, dict), "push без фильтра ветвей даёт двойной прогон PR"
    assert push.get("branches") == ["main"], push
    assert not set(push) - {"branches"}, push


def test_nfr10_pull_request_has_no_filters(wf: dict[Any, Any]) -> None:
    pr = _triggers(wf)["pull_request"]
    assert not pr, f"pull_request без фильтров (любые ветви и типы), получено {pr!r}"


def test_nfr10_no_pull_request_target(raw: str) -> None:
    assert "pull_request_target" not in raw


def test_nfr10_permissions_contents_read_only(wf: dict[Any, Any]) -> None:
    assert wf.get("permissions") == {"contents": "read"}


def test_nfr10_concurrency_declared(wf: dict[Any, Any]) -> None:
    conc = wf.get("concurrency")
    assert isinstance(conc, dict) and conc.get("group")
    group = str(conc["group"])
    assert "github.ref" in group and "github.workflow" in group, group


def test_nfr10_concurrency_never_cancels_main(wf: dict[Any, Any]) -> None:
    cancel = wf["concurrency"].get("cancel-in-progress")
    assert isinstance(cancel, str), "cancel-in-progress: true отменяет и прогон main"
    normalized = re.sub(r"\s+", "", cancel)
    assert normalized == "${{github.ref!='refs/heads/main'}}", cancel


def test_n6_no_secrets_other_than_github_token(raw: str) -> None:
    names = set(re.findall(r"secrets\.([A-Za-z0-9_]+)", raw))
    assert names <= {"GITHUB_TOKEN"}, f"в workflow секреты: {sorted(names)}"


def test_n6_workflow_never_pushes(raw: str) -> None:
    assert not re.search(r"\bgit\s+push\b", raw)


def test_nfr10_actions_pinned_to_versions(jobs: dict[str, dict[str, Any]]) -> None:
    refs = [u for job in jobs.values() for u in _uses(job)]
    assert refs, "нет ни одного uses:"
    for ref in refs:
        if ref.startswith("./") or ref.startswith("docker://"):
            continue
        assert "@" in ref, f"action без версии: {ref}"
        version = ref.split("@", 1)[1]
        assert version not in {"main", "master", "latest", "HEAD"}, f"плавающая ссылка: {ref}"
        assert re.fullmatch(r"v?\d+(\.\d+){0,2}|[0-9a-f]{40}", version), (
            f"версия {version!r}: {ref}"
        )


# --- backend -------------------------------------------------------------------------------


def test_nfr10_backend_job_python_postgres_install(jobs: dict[str, dict[str, Any]]) -> None:
    job = _job(jobs, "backend")
    text = _job_text(job)
    assert re.search(r"python-version:\s*['\"]?3\.12", text)
    services = job.get("services") or {}
    assert any(
        str(s.get("image")) == "postgres:16" for s in services.values() if isinstance(s, dict)
    ), "нужен сервис postgres:16"
    assert re.search(r"pip install -e [\"']?backend\[dev\][\"']?", _runs_text(job))


def test_nfr10_backend_job_lint_types(jobs: dict[str, dict[str, Any]]) -> None:
    runs = _runs_text(_job(jobs, "backend"))
    assert re.search(r"ruff check\b[^\n]*--no-cache|ruff --no-cache[^\n]*check", runs), (
        "ruff check без --no-cache (открытый вопрос T20)"
    )
    assert re.search(r"ruff format --check\b", runs)
    assert re.search(r"mypy\b[^\n]*backend/app", runs)


def test_nfr10_backend_job_migrations_and_check_on_test_db(
    jobs: dict[str, dict[str, Any]],
) -> None:
    job = _job(jobs, "backend")
    runs = _runs_text(job)
    up = re.search(r"alembic\b[^\n]*\bupgrade head", runs)
    chk = re.search(r"alembic\b[^\n]*\bcheck\b", runs)
    assert up and chk, "нужны alembic upgrade head и alembic check"
    assert up.start() < chk.start()
    assert re.search(r"/tracker_test\b", _job_text(job)), "миграции/тесты не на БД *_test"


def test_nfr10_backend_job_pytest_excludes_infra_stack(jobs: dict[str, dict[str, Any]]) -> None:
    runs = _runs_text(_job(jobs, "backend"))
    line = next((ln for ln in runs.splitlines() if re.search(r"\bpytest\b", ln)), None)
    assert line, "нет запуска pytest"
    assert re.search(r"not\s+infra_stack", line), line
    assert "backend/tests" in runs or "backend" in line


# --- frontend ------------------------------------------------------------------------------


def test_nfr10_frontend_job(jobs: dict[str, dict[str, Any]]) -> None:
    job = _job(jobs, "frontend")
    assert re.search(r"node-version:\s*['\"]?22", _job_text(job))
    runs = _runs_text(job)
    positions = []
    for needle in (
        r"npm ci\b",
        r"npm run lint\b",
        r"npm run typecheck\b",
        r"npm (run )?test\b",
        r"npm run build\b",
    ):
        m = re.search(needle, runs)
        assert m, f"в frontend нет шага {needle}"
        positions.append(m.start())
    assert positions[0] == min(positions), "npm ci должен идти первым"


# --- contract ------------------------------------------------------------------------------


def test_nfr10_contract_job_regenerates_and_diffs(jobs: dict[str, dict[str, Any]]) -> None:
    job = _job(jobs, "contract")
    runs = _runs_text(job)
    gen = re.search(r"scripts/gen-api\.sh", runs)
    diff = re.search(r"git diff --exit-code", runs)
    assert gen and diff and gen.start() < diff.start()
    assert "docs/api" in runs and "schema.d.ts" in runs, "diff должен охватывать оба артефакта"
    assert re.search(r"pip install -e [\"']?backend", runs), "gostracker openapi нужен пакет"
    assert re.search(r"npm (--prefix frontend |ci)", runs), "gen:api нужны зависимости фронтенда"


# --- infra ---------------------------------------------------------------------------------


def test_nfr10_infra_job_needs_backend_and_frontend(jobs: dict[str, dict[str, Any]]) -> None:
    needs = _job(jobs, "infra").get("needs")
    needs = [needs] if isinstance(needs, str) else list(needs or [])
    assert {"backend", "frontend"} <= set(needs)


def test_nfr10_infra_job_project_ports_and_order(jobs: dict[str, dict[str, Any]]) -> None:
    job = _job(jobs, "infra")
    text = _job_text(job)
    for token in ("gostracker-infratest", "18080", "18443"):
        assert token in text, token
    assert re.search(r"GT_INFRA_STACK['\"]?:\s*['\"]?1|GT_INFRA_STACK=1", text)
    steps = _steps(job)

    def index(pattern: str) -> int:
        for i, s in enumerate(steps):
            if re.search(pattern, str(s.get("run", ""))):
                return i
        raise AssertionError(f"нет шага {pattern!r}")

    up = index(
        r"compose\b[^\n]*\bup\b[^\n]*--build[^\n]*--wait|compose\b[^\n]*\bup\b[^\n]*--wait[^\n]*--build"
    )
    tests = index(r"pytest\b[^\n]*-m\s+[\"']?infra_stack")
    down = index(r"compose\b[^\n]*\bdown\b[^\n]*-v")
    assert up < tests < down
    assert "-p gostracker-infratest" in str(steps[up]["run"]) or "COMPOSE_PROJECT_NAME" in text


def test_nfr10_infra_job_logs_on_failure_and_always_down(jobs: dict[str, dict[str, Any]]) -> None:
    steps = _steps(_job(jobs, "infra"))
    logs = [s for s in steps if re.search(r"compose\b[^\n]*\blogs\b", str(s.get("run", "")))]
    assert logs, "нет шага docker compose logs"
    assert any(re.search(r"failure\(\)|always\(\)", str(s.get("if", ""))) for s in logs)
    down = [
        s for s in steps if re.search(r"compose\b[^\n]*\bdown\b[^\n]*-v", str(s.get("run", "")))
    ]
    assert down and all("always()" in str(s.get("if", "")) for s in down), (
        "down -v должен выполняться всегда (if: always())"
    )


# --- ruff закреплён, check.sh --------------------------------------------------------------


def test_t20_ruff_version_pinned_exactly_in_pyproject() -> None:
    data = tomllib.loads((REPO / "backend" / "pyproject.toml").read_text(encoding="utf-8"))
    dev = data["project"]["optional-dependencies"]["dev"]
    ruff = [d for d in dev if re.match(r"ruff\b", d)]
    assert len(ruff) == 1
    assert re.fullmatch(r"ruff==\d+\.\d+\.\d+", ruff[0].replace(" ", "")), ruff[0]


CHECK_SH = REPO / "scripts" / "check.sh"


def _check_sh_code() -> str:
    lines = CHECK_SH.read_text(encoding="utf-8").splitlines()
    return "\n".join(ln for ln in lines if not ln.lstrip().startswith("#"))


def test_nfr10_check_sh_has_alembic_check_and_frontend_build() -> None:
    text = _check_sh_code()
    assert re.search(r"alembic\b[^\n]*\bcheck\b", text), "в check.sh нет alembic check"
    assert re.search(r"npm run build\b", text), "в check.sh нет сборки фронтенда"


def test_nfr10_check_sh_actually_calls_alembic_check_function() -> None:
    """Не определение функции, а ВЫЗОВ ``run alembic_check`` (мутация «убрать вызов» красная)."""
    text = _check_sh_code()
    assert re.search(r"(?m)^\s*run\s+alembic_check\s*$", text), "нет вызова run alembic_check"


def test_nfr10_check_sh_ruff_check_without_cache() -> None:
    assert re.search(r"(?m)^\s*run\s+ruff\s+check\s+--no-cache\s+backend\s*$", _check_sh_code())


def test_nfr10_check_sh_db_guard_uses_python_assert_test_database_url() -> None:
    text = _check_sh_code()
    assert "assert_test_database_url" in text, "гард БД должен быть python-проверкой db_support"
    assert "tests.db_support" in text


# --- check.sh в изоляции: заглушки команд в PATH -------------------------------------------
# Интерфейс: ``bash scripts/check.sh`` читает TEST_DATABASE_URL; перед alembic вызывает
# ``python -c 'from tests.db_support import assert_test_database_url ...'`` (python берётся
# из PATH); при отказе печатает сообщение, не запускает alembic и завершается с rc != 0.

_STUB = """#!/bin/sh
echo "$(basename "$0") $*" >> "$STUB_LOG"
if [ "$(basename "$0")" = alembic ]; then
  echo "DATABASE_URL=$DATABASE_URL ENV=$ENV" >> "$STUB_LOG"
fi
exit 0
"""


def _run_check_sh(tmp_path: Path, url: str) -> tuple[int, str, str]:
    import os
    import subprocess
    import sys

    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("ruff", "mypy", "alembic", "pytest", "npm", "node"):
        stub = bindir / name
        stub.write_text(_STUB)
        stub.chmod(0o755)
    for name in ("python", "python3"):
        wrapper = bindir / name
        wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
        wrapper.chmod(0o755)
    log = tmp_path / "stub.log"
    log.write_text("")
    env = {
        **os.environ,
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "STUB_LOG": str(log),
        "TEST_DATABASE_URL": url,
    }
    res = subprocess.run(
        ["bash", str(CHECK_SH)], cwd=REPO, env=env, capture_output=True, text=True,
        timeout=120, check=False,
    )  # fmt: skip
    return res.returncode, res.stdout + res.stderr, log.read_text()


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://u:p@localhost:5432/tracker?application_name=x_test",
        "postgresql+asyncpg://u:p@localhost:5432/tracker_test?database=tracker",
        "postgresql+asyncpg://u:p@localhost:5432/tracker",
    ],
)
def test_nfr10_check_sh_refuses_unsafe_database_url(tmp_path: Path, url: str) -> None:
    rc, out, log = _run_check_sh(tmp_path, url)
    assert rc != 0
    assert "alembic" not in log, f"alembic запущен на небезопасном URL:\n{log}"
    assert "_test" in out, "нужно понятное сообщение про БД *_test"


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://u:p@localhost:5432/tracker_test",
        "postgresql+asyncpg://u:p@localhost:5432/tracker_t27_test",
    ],
)
def test_nfr10_check_sh_allows_test_database_url(tmp_path: Path, url: str) -> None:
    _rc, _out, log = _run_check_sh(tmp_path, url)
    assert re.search(r"(?m)^alembic .*\bupgrade head\b", log), log
    assert re.search(r"(?m)^alembic .*\bcheck\b", log), log
    assert f"DATABASE_URL={url} ENV=test" in log


def test_nfr10_check_sh_runs_ruff_check_with_no_cache(tmp_path: Path) -> None:
    _rc, _out, log = _run_check_sh(tmp_path, "postgresql+asyncpg://u:p@localhost:5432/x_test")
    assert re.search(r"(?m)^ruff check --no-cache\b", log), log
