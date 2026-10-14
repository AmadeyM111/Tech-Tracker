"""T20: сборка и запуск образа API в изолированных контейнерах (маркер infra_stack).

Выполняется только при ``GT_INFRA_STACK=1`` и доступном Docker. Не использует compose-проект
``gostracker-dev``: образ ``gostracker-api:test``, контейнеры ``gt-t20-*``, своя сеть и тома.
Всё созданное удаляется в finally (``docker rm -f``, ``docker network rm``, ``docker volume rm``,
``docker rmi``). Покрывает FR-6, FR-48, NFR-4, D-19, D-21, AC-23 (контейнерная часть).

Запуск: ``GT_INFRA_STACK=1 pytest -q -m infra_stack backend/tests/infra/test_api_image_build.py``.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.infra_stack,
    pytest.mark.skipif(os.environ.get("GT_INFRA_STACK") != "1", reason="нужен GT_INFRA_STACK=1"),
]

IMAGE = "gostracker-api:test"
NETWORK = "gt-t20-net"
DB = "gt-t20-db"
API = "gt-t20-api"
API_NODB = "gt-t20-nodb"
API_STOP = "gt-t20-stop"
VOL_MAIN = "gt-t20-data"
VOL_STOP = "gt-t20-data-stop"
VOL_NODB = "gt-t20-data-nodb"
DB_PASSWORD = "T20dbPw-Zk39xQ7vLm"
DSN = f"postgresql+asyncpg://tracker:{DB_PASSWORD}@{DB}:5432/tracker"
NODB_PASSWORD = "T20nodbPw-Hr62yWc4Nb"
NODB_DSN = f"postgresql+asyncpg://tracker:{NODB_PASSWORD}@gt-t20-absent:5432/tracker"
BACKEND_DIR = Path(__file__).resolve().parents[2]
SECRETS = "/data/secrets"
PASSWORD_FILE = f"{SECRETS}/initial-admin-password.txt"
KEY_FILE = f"{SECRETS}/secret_key"


# --- помощники ---------------------------------------------------------------------------


def docker(
    *args: str, timeout: float = 120, check: bool = True
) -> subprocess.CompletedProcess[str]:
    res = subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout, check=False
    )
    if check and res.returncode != 0:
        raise AssertionError(
            f"docker {' '.join(args[:3])} -> rc={res.returncode}\n{res.stdout[-2000:]}\n"
            f"{res.stderr[-2000:]}"
        )
    return res


def in_image(*cmd: str) -> str:
    """Одноразовый контейнер из образа с обходом entrypoint."""
    return docker("run", "--rm", "--entrypoint", cmd[0], IMAGE, *cmd[1:], timeout=120).stdout


def exec_in(container: str, *cmd: str, check: bool = True) -> str:
    return docker("exec", container, *cmd, check=check).stdout


def logs(container: str) -> str:
    res = docker("logs", container, check=False)
    return res.stdout + res.stderr


def start_api(name: str, volume: str, dsn: str = DSN) -> None:
    docker(
        "run",
        "-d",
        "--name",
        name,
        "--network",
        NETWORK,
        "-v",
        f"{volume}:/data",
        "-e",
        f"DATABASE_URL={dsn}",
        "-e",
        "COOKIE_SECURE=true",
        "-e",
        "DATA_DIR=/data",
        "-e",
        "ARGON2_TIME_COST=1",
        "-e",
        "ARGON2_MEMORY_COST_KIB=1024",
        "-e",
        "ARGON2_PARALLELISM=1",
        IMAGE,
    )


def health_status(container: str) -> str:
    res = docker("inspect", "-f", "{{if .State.Health}}{{.State.Health.Status}}{{end}}", container)
    return res.stdout.strip()


def is_running(container: str) -> bool:
    return docker("inspect", "-f", "{{.State.Running}}", container).stdout.strip() == "true"


def wait_healthy(container: str, timeout: float = 60) -> float:
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if health_status(container) == "healthy":
            return time.monotonic() - start
        if not is_running(container):
            raise AssertionError(f"контейнер {container} остановился:\n{logs(container)[-3000:]}")
        time.sleep(1)
    raise AssertionError(
        f"{container} не стал healthy за {timeout:.0f} с "
        f"(status={health_status(container)})\n{logs(container)[-3000:]}"
    )


def remove_container(name: str) -> None:
    docker("rm", "-f", "-v", name, check=False)


def _cleanup() -> None:
    for c in (API, API_NODB, API_STOP, DB):
        remove_container(c)
    for v in (VOL_MAIN, VOL_STOP, VOL_NODB):
        docker("volume", "rm", "-f", v, check=False)
    docker("network", "rm", NETWORK, check=False)


# --- фикстуры ----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def stack() -> Iterator[None]:
    """Образ, сеть и БД; удаляются после модуля."""
    if subprocess.run(["docker", "info"], capture_output=True, check=False).returncode != 0:
        pytest.fail("Docker недоступен")
    _cleanup()
    try:
        docker("network", "create", NETWORK)
        build = docker("build", "-t", IMAGE, str(BACKEND_DIR), timeout=900, check=False)
        assert build.returncode == 0, f"docker build упал:\n{(build.stdout + build.stderr)[-3000:]}"
        docker(
            "run",
            "-d",
            "--name",
            DB,
            "--network",
            NETWORK,
            "-e",
            "POSTGRES_USER=tracker",
            "-e",
            f"POSTGRES_PASSWORD={DB_PASSWORD}",
            "-e",
            "POSTGRES_DB=tracker",
            "postgres:16",
        )
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            ready = docker("exec", DB, "pg_isready", "-U", "tracker", "-d", "tracker", check=False)
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise AssertionError("БД gt-t20-db не готова")
        yield
    finally:
        _cleanup()
        docker("rmi", "-f", IMAGE, check=False)


@pytest.fixture(scope="module")
def api(stack: None) -> Iterator[str]:
    """Работающий контейнер API на свежем томе (первый запуск)."""
    start_api(API, VOL_MAIN)
    try:
        yield API
    finally:
        remove_container(API)


# --- содержимое образа --------------------------------------------------------------------


def test_build_succeeds(stack: None) -> None:
    """D-21: ``docker build -t gostracker-api:test backend`` успешен (проверяется в фикстуре)."""
    out = docker("image", "inspect", "-f", "{{.Id}}", IMAGE).stdout.strip()
    assert out.startswith("sha256:")


def test_image_python_is_312(stack: None) -> None:
    """FR-48: Python 3.12.x."""
    out = in_image("python", "--version")
    assert re.match(r"Python 3\.12\.\d+", out.strip()), out


def test_image_runs_as_uid_10001(stack: None) -> None:
    """NFR-4, D-19: процесс по умолчанию — uid 10001."""
    assert in_image("id", "-u").strip() == "10001"


def test_image_gostracker_help_exit_0(stack: None) -> None:
    """D-21: CLI установлен и запускается (подпакеты попали в установку)."""
    res = docker("run", "--rm", "--entrypoint", "gostracker", IMAGE, "--help")
    assert "bootstrap" in res.stdout


def test_image_data_dir_owned_by_app_and_private(stack: None) -> None:
    """D-19: /data принадлежит 10001, режим не шире 0750."""
    uid, mode = in_image("stat", "-c", "%u %a", "/data").split()
    assert uid == "10001"
    assert int(mode, 8) & ~0o750 == 0, mode


def test_image_has_no_dev_artifacts_in_app(stack: None) -> None:
    """NFR-4: в /app нет .venv, tests, .git, .env."""
    names = set(in_image("ls", "-A", "/app").split())
    assert names, "пустой /app"
    assert not names & {".venv", "tests", ".git", ".env", "node_modules", "docs"}, names
    assert "alembic.ini" in names
    banned = {"Dockerfile", ".dockerignore"}
    assert not names & banned, names
    assert not [n for n in names if n.startswith(".env")], names


def test_image_app_has_no_bytecode_or_build_leftovers(stack: None) -> None:
    """NFR-4: в /app нет __pycache__, *.pyc, *.egg-info, build (исключения .dockerignore
    должны действовать на любой глубине, а не только в корне контекста)."""
    out = docker(
        "run",
        "--rm",
        "--entrypoint",
        "sh",
        IMAGE,
        "-c",
        "find /app \\( -name __pycache__ -o -name '*.pyc' -o -name '*.egg-info' "
        "-o \\( -name build -a -type d \\) \\)",
    ).stdout
    assert out.strip() == "", out


def test_image_dependencies(stack: None) -> None:
    """NFR-4: нет dev-зависимостей и телеметрии; argon2-cffi есть."""
    pkgs = {
        line.split("==")[0].split(" @ ")[0].lower().replace("_", "-")
        for line in in_image("pip", "list", "--format=freeze").splitlines()
        if line.strip()
    }
    assert "argon2-cffi" in pkgs
    for banned in ("pytest", "ruff", "mypy", "pytest-asyncio", "opentelemetry-sdk"):
        assert banned not in pkgs, banned


# --- работающий контейнер ------------------------------------------------------------------


def test_fr6_bootstrap_runs_on_start_and_container_becomes_healthy(api: str) -> None:
    """FR-6, FR-48: bootstrap при старте, контейнер healthy по HEALTHCHECK за ≤ 60 с."""
    elapsed = wait_healthy(api, timeout=60)
    assert elapsed <= 60


def test_ac23_secrets_in_volume_have_private_modes(api: str) -> None:
    """AC-23: в томе /data/secrets файлы 0600, каталог 0700."""
    wait_healthy(api)
    listing = exec_in(api, "stat", "-c", "%a %u %n", SECRETS, KEY_FILE, PASSWORD_FILE)
    parsed = [line.split(" ", 2) for line in listing.strip().splitlines()]
    modes = {path: mode for mode, _, path in parsed}
    owners = {path: uid for _, uid, path in parsed}
    assert modes[SECRETS] == "700"
    assert modes[KEY_FILE] == "600"
    assert modes[PASSWORD_FILE] == "600"
    assert set(owners.values()) == {"10001"}, owners
    names = exec_in(api, "ls", "-A", SECRETS).split()
    for name in names:
        mode = exec_in(api, "stat", "-c", "%a", f"{SECRETS}/{name}").strip()
        assert mode == "600", (name, mode)


def test_ac23_initial_password_not_in_container_logs(api: str) -> None:
    """AC-23, FR-6: пароль первого ТА и ключ не попадают в docker logs."""
    wait_healthy(api)
    content = exec_in(api, "cat", PASSWORD_FILE)
    password = dict(ln.split("=", 1) for ln in content.splitlines() if "=" in ln)[
        "password"
    ].strip()
    key = exec_in(api, "cat", KEY_FILE).strip()
    text = logs(api)
    assert password and password not in text
    assert key and key not in text
    assert DB_PASSWORD not in text


def test_health_endpoint_200_inside_container(api: str) -> None:
    """FR-48: GET /api/v1/health изнутри контейнера — 200."""
    wait_healthy(api)
    code = exec_in(
        api,
        "python",
        "-c",
        "import urllib.request as u;"
        "print(u.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=5).status)",
    ).strip()
    assert code == "200"


def test_container_stays_healthy_and_pid1_is_uvicorn_as_uid_10001(api: str) -> None:
    """NFR-4: uvicorn (exec, PID 1) под uid 10001; healthy сохраняется."""
    wait_healthy(api)
    status = exec_in(api, "cat", "/proc/1/status")
    uid_line = next(ln for ln in status.splitlines() if ln.startswith("Uid:"))
    assert uid_line.split()[1:] == ["10001"] * 4, uid_line
    cmdline = exec_in(api, "cat", "/proc/1/cmdline").replace("\0", " ")
    assert "uvicorn" in cmdline and "app.main:app" in cmdline, cmdline
    assert "--reload" not in cmdline
    time.sleep(12)
    assert health_status(api) == "healthy"


def test_no_access_log_lines_for_health_requests(api: str) -> None:
    """D-31: access-лог uvicorn выключен (пишет наше приложение)."""
    wait_healthy(api)
    for _ in range(3):
        exec_in(
            api,
            "python",
            "-c",
            "import urllib.request as u;u.urlopen('http://127.0.0.1:8000/api/v1/health')",
        )
    assert not re.search(r'"GET /api/v1/health HTTP/1\.1" 200', logs(api))


def test_second_start_on_same_volume_changes_nothing(api: str) -> None:
    """FR-6: перезапуск на том же томе — тот же ключ и пароль, второго ТА нет."""
    wait_healthy(api)
    key_before = exec_in(api, "cat", KEY_FILE)
    pw_before = exec_in(api, "cat", PASSWORD_FILE)
    count_sql = "SELECT count(*) FROM app_user"
    users_before = exec_in(DB, "psql", "-U", "tracker", "-d", "tracker", "-tAc", count_sql).strip()
    assert users_before == "1"

    remove_container(API)
    start_api(API, VOL_MAIN)
    wait_healthy(API)

    assert exec_in(API, "cat", KEY_FILE) == key_before
    assert exec_in(API, "cat", PASSWORD_FILE) == pw_before
    users_after = exec_in(DB, "psql", "-U", "tracker", "-d", "tracker", "-tAc", count_sql).strip()
    assert users_after == "1"
    ws = exec_in(
        DB, "psql", "-U", "tracker", "-d", "tracker", "-tAc", "SELECT count(*) FROM workspace"
    )
    assert ws.strip() == "1"
    assert (dict(ln.split("=", 1) for ln in pw_before.splitlines() if "=" in ln))[
        "password"
    ].strip() not in logs(API)


# --- отказ без БД и остановка -------------------------------------------------------------


def test_fr6_without_db_exits_nonzero_within_75s_without_dsn_password(stack: None) -> None:
    """FR-6, D-29: БД недоступна → ненулевой код ≤ 75 с, пароль DSN не в логах."""
    start_api(API_NODB, VOL_NODB, dsn=NODB_DSN)
    try:
        t0 = time.monotonic()
        res = docker("wait", API_NODB, timeout=90)
        elapsed = time.monotonic() - t0
        code = int(res.stdout.strip())
        assert code != 0
        assert elapsed <= 75, f"ожидание БД заняло {elapsed:.0f} с"
        text = logs(API_NODB)
        assert text.strip(), "ожидается сообщение об ошибке"
        assert NODB_PASSWORD not in text
    finally:
        remove_container(API_NODB)


def test_docker_stop_is_graceful_within_10s(stack: None) -> None:
    """NFR-4: docker stop → SIGTERM → завершение ≤ 10 с, код 0/143 (не SIGKILL 137)."""
    start_api(API_STOP, VOL_STOP)
    try:
        wait_healthy(API_STOP)
        t0 = time.monotonic()
        docker("stop", "-t", "10", API_STOP, timeout=40)
        elapsed = time.monotonic() - t0
        code = int(docker("inspect", "-f", "{{.State.ExitCode}}", API_STOP).stdout.strip())
        assert code in (0, 143), f"код завершения {code} (137 = убит SIGKILL)"
        assert elapsed < 10, f"остановка заняла {elapsed:.1f} с"
    finally:
        remove_container(API_STOP)
