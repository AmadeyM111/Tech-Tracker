"""T20: статический разбор образа API (plan §4.12, D-19, D-21, FR-6, FR-48, NFR-4, N-6, AC-23).

Docker не запускается: разбираются ``backend/Dockerfile``, ``backend/docker-entrypoint.sh``,
``backend/.dockerignore`` и ``docker-compose.yml`` (healthcheck db, заметка ревью T02).
Сервис ``api`` в compose здесь НЕ проверяется (T26).
"""

from __future__ import annotations

import os
import re
import shlex
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.infra_static

BASE_IMAGE = "python:3.12-slim-bookworm"


# --- помощники ---------------------------------------------------------------------------


def _read(path: Path) -> str:
    assert path.is_file(), f"нет файла {path}"
    return path.read_text(encoding="utf-8")


def _instructions(dockerfile: str) -> list[tuple[str, str]]:
    """Инструкции Dockerfile (без комментариев, с объединением строк через ``\\``)."""
    joined: list[str] = []
    buf = ""
    for raw in dockerfile.splitlines():
        line = raw.rstrip()
        if not buf and (not line.strip() or line.lstrip().startswith("#")):
            continue
        if line.lstrip().startswith("#") and buf:
            continue
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        joined.append((buf + line).strip())
        buf = ""
    if buf:
        joined.append(buf.strip())
    out: list[tuple[str, str]] = []
    for item in joined:
        head, _, rest = item.partition(" ")
        out.append((head.upper(), rest.strip()))
    return out


@pytest.fixture(scope="module")
def dockerfile_path(repo_root: Path) -> Path:
    return repo_root / "backend" / "Dockerfile"


@pytest.fixture(scope="module")
def dockerfile(dockerfile_path: Path) -> str:
    return _read(dockerfile_path)


@pytest.fixture(scope="module")
def instr(dockerfile: str) -> list[tuple[str, str]]:
    return _instructions(dockerfile)


@pytest.fixture(scope="module")
def entrypoint(repo_root: Path) -> str:
    return _read(repo_root / "backend" / "docker-entrypoint.sh")


def _code_lines(script: str) -> list[str]:
    return [
        ln.strip() for ln in script.splitlines() if ln.strip() and not ln.strip().startswith("#")
    ]


def _commands(entrypoint: str) -> list[str]:
    """Строки скрипта с объединением продолжений ``\\``."""
    out: list[str] = []
    buf = ""
    for ln in _code_lines(entrypoint):
        if ln.endswith("\\"):
            buf += ln[:-1] + " "
            continue
        out.append(buf + ln)
        buf = ""
    return out


# --- Dockerfile --------------------------------------------------------------------------


def test_fr48_base_image_is_pinned_python312_slim_bookworm(instr: list[tuple[str, str]]) -> None:
    """FR-48, plan §4.12: единственная база — python:3.12-slim-bookworm по тегу."""
    froms = [rest.split()[0] for head, rest in instr if head == "FROM"]
    assert froms, "нет FROM"
    assert all(f == BASE_IMAGE for f in froms), froms


def test_nfr4_no_latest_tags(dockerfile: str) -> None:
    """N-6: теги не плавают."""
    assert not re.search(r":latest\b", dockerfile)
    for head, rest in _instructions(dockerfile):
        if head == "FROM":
            image = rest.split()[0]
            assert ":" in image or "@sha256:" in image, f"FROM без тега: {image}"


def test_pip_install_uses_no_cache_dir(instr: list[tuple[str, str]]) -> None:
    """plan §4.12: каждая установка pip — с --no-cache-dir."""
    pip_install = re.compile(r"\bpip3?\b.*\binstall\b")
    runs = [rest for head, rest in instr if head == "RUN" and pip_install.search(rest)]
    assert runs, "нет pip install"
    for rest in runs:
        assert "--no-cache-dir" in rest, rest


def test_pip_install_is_not_editable(instr: list[tuple[str, str]]) -> None:
    """plan §4.12: ``pip install .`` / ``/app`` — не editable (иначе нет подпакетов в образе)."""
    for head, rest in instr:
        if head == "RUN" and "pip" in rest and "install" in rest:
            assert not re.search(r"\s-e\b|--editable", rest), rest


def test_pip_does_not_install_dev_extras(instr: list[tuple[str, str]]) -> None:
    """Dev-зависимости (pytest, ruff, mypy) не входят в образ."""
    for head, rest in instr:
        if head == "RUN" and "pip" in rest and "install" in rest:
            assert "[dev" not in rest, rest


def test_alembic_config_env_points_into_app(instr: list[tuple[str, str]]) -> None:
    """D-21: ENV ALEMBIC_CONFIG=/app/alembic.ini."""
    envs = " ".join(rest for head, rest in instr if head == "ENV")
    assert re.search(r"ALEMBIC_CONFIG[= ]\"?/app/alembic\.ini\"?", envs), envs


def test_alembic_ini_is_copied_next_to_app(dockerfile: str, repo_root: Path) -> None:
    """D-21: alembic.ini и migrations доезжают в образ (COPY всего каталога или явно)."""
    assert (repo_root / "backend" / "alembic.ini").is_file()
    copies = [rest for head, rest in _instructions(dockerfile) if head == "COPY"]
    assert copies, "нет COPY"
    joined = " ".join(copies)
    copies_all = any(re.match(r"(--\S+\s+)*\.\s+\S+$", c) for c in copies)
    explicit = "alembic.ini" in joined and "migrations" in joined
    assert copies_all or explicit, copies


def test_user_is_uid_10001_not_root(instr: list[tuple[str, str]]) -> None:
    """NFR-4, D-19: итоговый USER — uid 10001 (не root, не 0)."""
    users = [rest.strip() for head, rest in instr if head == "USER"]
    assert users, "нет USER"
    last = users[-1]
    assert last.split(":")[0] not in ("root", "0"), last
    assert last.startswith("10001"), f"USER должен быть числовым 10001: {last}"


def test_data_dir_created_and_owned_by_uid(instr: list[tuple[str, str]]) -> None:
    """D-19: /data создан и принадлежит 10001 до VOLUME (иначе том будет root)."""
    idx_volume = next(i for i, (h, r) in enumerate(instr) if h == "VOLUME" and "/data" in r)
    before = instr[:idx_volume]
    mk = [
        i
        for i, (h, r) in enumerate(before)
        if h == "RUN" and "/data" in r and re.search(r"mkdir|install\s+-d", r)
    ]
    assert mk, "нет создания /data до VOLUME"
    owned = any(
        (h == "RUN" and re.search(r"chown[^&;]*10001[^&;]*/data|chown[^&;]*/data", r))
        or (h == "RUN" and re.search(r"install\s+-d[^&;]*-o\s*10001[^&;]*/data", r))
        for h, r in before
    ) or any(h == "COPY" and "--chown=10001" in r and "/data" in r for h, r in before)
    assert owned, "/data не передан uid 10001 до VOLUME"
    # права не шире 0750, если заданы явно
    for h, r in before:
        if h == "RUN" and "/data" in r:
            for m in re.finditer(r"chmod\s+(-R\s+)?([0-7]{3,4})\s+[^&;]*/data", r):
                assert int(m.group(2), 8) & 0o027 == 0, m.group(0)
            for m in re.finditer(r"-m\s*([0-7]{3,4})[^&;]*/data", r):
                assert int(m.group(1), 8) & 0o027 == 0, m.group(0)


def test_volume_data_declared(instr: list[tuple[str, str]]) -> None:
    """D-19: VOLUME /data."""
    vols = [r for h, r in instr if h == "VOLUME"]
    assert any(re.fullmatch(r"\[?\s*\"?/data\"?\s*\]?", v) for v in vols), vols


def test_expose_8000(instr: list[tuple[str, str]]) -> None:
    """plan §4.12: порт 8000 (uvicorn) объявлен."""
    ports = [r for h, r in instr if h == "EXPOSE"]
    assert any(re.match(r"8000(/tcp)?$", p.strip()) for p in ports), ports


def test_healthcheck_uses_python_without_curl(instr: list[tuple[str, str]]) -> None:
    """FR-48: HEALTHCHECK на /api/v1/health средствами Python, без curl/wget."""
    hc = [r for h, r in instr if h == "HEALTHCHECK"]
    assert len(hc) == 1, hc
    body = hc[0]
    assert "NONE" not in body.upper().split()[:1]
    assert "/api/v1/health" in body
    assert re.search(r"\bpython3?\b", body), body
    assert not re.search(r"\b(curl|wget)\b", body), body
    assert re.search(r"urllib|http\.client|urlopen", body), body
    assert "--start-period" in body, "нужен --start-period: bootstrap ждёт БД до 60 с"
    assert "--interval" in body
    assert "--retries" in body


def test_entrypoint_is_the_script(instr: list[tuple[str, str]]) -> None:
    """D-21: ENTRYPOINT — docker-entrypoint.sh, в exec-форме."""
    eps = [r for h, r in instr if h == "ENTRYPOINT"]
    assert len(eps) == 1, eps
    assert "docker-entrypoint.sh" in eps[0]
    assert eps[0].lstrip().startswith("["), "ENTRYPOINT должен быть в exec-форме (сигналы доходят)"


def test_no_secrets_or_env_files_copied(dockerfile: str) -> None:
    """NFR-4, FR-6: в образ не копируются .env и секреты."""
    for head, rest in _instructions(dockerfile):
        if head in ("COPY", "ADD"):
            assert not re.search(r"(^|[\s/])\.env\b", rest), rest
            assert not re.search(r"secret|\.pem\b|\.key\b|id_rsa", rest, re.I), rest


def test_no_secret_values_in_env_or_args(instr: list[tuple[str, str]]) -> None:
    """FR-6: SECRET_KEY / пароли не зашиваются в ENV и ARG."""
    for head, rest in instr:
        if head in ("ENV", "ARG"):
            assert not re.search(r"SECRET_KEY|PASSWORD|DATABASE_URL", rest, re.I), rest


def test_no_remote_add(dockerfile: str) -> None:
    """NFR-4: нет ADD по URL и скачиваний curl|sh."""
    for head, rest in _instructions(dockerfile):
        if head == "ADD":
            assert not re.match(r"(--\S+\s+)*https?://", rest), rest
    assert not re.search(r"(curl|wget)[^\n]*\|\s*(ba)?sh", dockerfile)


def test_no_apt_cache_or_extra_packages_left(instr: list[tuple[str, str]]) -> None:
    """Если apt-get используется — без кеша списков (образ минимальный)."""
    for head, rest in instr:
        if head == "RUN" and "apt-get install" in rest:
            assert "--no-install-recommends" in rest, rest
            assert "rm -rf /var/lib/apt/lists" in rest, rest


# --- docker-entrypoint.sh ---------------------------------------------------------------


def test_entrypoint_has_shebang_and_set_e(entrypoint: str) -> None:
    """Shebang sh/bash и ``set -e`` (ошибка bootstrap останавливает запуск)."""
    first = entrypoint.splitlines()[0]
    assert re.match(r"#!\s*(/usr/bin/env\s+(ba)?sh|/bin/(ba)?sh)\b", first), first
    assert re.search(r"^\s*set\s+-[a-z]*e[a-z]*\b", entrypoint, re.M), "нет set -e"


def test_entrypoint_is_executable(repo_root: Path) -> None:
    """Право на исполнение: git mode 100755 (если файл в индексе) и бит +x на диске."""
    path = repo_root / "backend" / "docker-entrypoint.sh"
    assert path.is_file()
    assert os.stat(path).st_mode & stat.S_IXUSR, "нет бита исполнения"
    res = subprocess.run(
        ["git", "ls-files", "--stage", "--", str(path)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if res.stdout.strip():
        assert res.stdout.split()[0] == "100755", res.stdout


def test_fr6_entrypoint_umask_077_before_bootstrap(entrypoint: str) -> None:
    """FR-6, D-19: ``umask 077`` задан до запуска bootstrap."""
    cmds = _commands(entrypoint)
    umask_idx = next((i for i, c in enumerate(cmds) if re.fullmatch(r"umask\s+0?077", c)), None)
    boot_idx = next((i for i, c in enumerate(cmds) if "gostracker bootstrap" in c), None)
    assert umask_idx is not None, "нет umask 077"
    assert boot_idx is not None, "нет gostracker bootstrap"
    assert umask_idx < boot_idx


def test_fr6_entrypoint_runs_bootstrap_then_exec_uvicorn(entrypoint: str) -> None:
    """FR-6: bootstrap выполняется до uvicorn; uvicorn запускается через exec (PID 1, SIGTERM)."""
    cmds = _commands(entrypoint)
    boot_idx = next(i for i, c in enumerate(cmds) if "gostracker bootstrap" in c)
    uv_idx = next((i for i, c in enumerate(cmds) if "uvicorn" in c), None)
    assert uv_idx is not None, "нет запуска uvicorn"
    assert boot_idx < uv_idx
    assert re.match(r"exec\s+(python3?\s+-m\s+)?uvicorn\b", cmds[uv_idx]), cmds[uv_idx]
    # bootstrap не в фоне и не проглатывается
    assert not cmds[boot_idx].rstrip().endswith("&")
    assert "|| true" not in cmds[boot_idx]
    assert "set -e" in entrypoint or re.search(r"set\s+-\w*e", entrypoint)


def test_entrypoint_uvicorn_flags(entrypoint: str) -> None:
    """plan §4.12, D-31: app.main:app, прокси-заголовки, без access-лога, без --reload."""
    cmds = _commands(entrypoint)
    line = next(c for c in cmds if "uvicorn" in c)
    tokens = shlex.split(line)
    assert "app.main:app" in tokens
    assert "--proxy-headers" in tokens
    assert any(t.startswith("--forwarded-allow-ips") for t in tokens), tokens
    assert "--no-access-log" in tokens
    assert "--reload" not in tokens
    assert "--workers" not in tokens or tokens[tokens.index("--workers") + 1] == "1"
    port_ok = "--port" in tokens and tokens[tokens.index("--port") + 1] == "8000"
    assert port_ok or "--port=8000" in tokens, tokens
    # слушаем на всех интерфейсах контейнера (внутри контейнера допустимо)
    host_ok = "--host" in tokens and tokens[tokens.index("--host") + 1] == "0.0.0.0"
    assert host_ok or "--host=0.0.0.0" in tokens, tokens


def test_entrypoint_has_no_secrets_or_debug(entrypoint: str) -> None:
    """NFR-4: нет xtrace (``set -x`` печатает окружение), нет ключей в тексте."""
    assert not re.search(r"^\s*set\s+-[a-z]*x", entrypoint, re.M)
    assert not re.search(r"SECRET_KEY\s*=\s*\S", entrypoint)
    assert "change-me" not in entrypoint.lower()
    assert "curl" not in entrypoint


# --- .dockerignore ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "pattern",
    [".venv", "tests", ".git", "__pycache__", "*.egg-info", ".env*", "docs", "node_modules"],
)
def test_dockerignore_excludes(repo_root: Path, pattern: str) -> None:
    """NFR-4: контекст сборки не тащит окружение, тесты, .git, секреты и документацию."""
    lines = {
        ln.strip().lstrip("/").rstrip("/")
        for ln in _read(repo_root / "backend" / ".dockerignore").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    }
    variants = {pattern, f"**/{pattern}"}
    assert lines & variants, f"в .dockerignore нет {pattern}"


def test_dockerignore_does_not_exclude_what_image_needs(repo_root: Path) -> None:
    """Сборке нужны app, migrations, alembic.ini, pyproject.toml, entrypoint."""
    lines = [
        ln.strip()
        for ln in _read(repo_root / "backend" / ".dockerignore").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    for needed in ("app", "migrations", "alembic.ini", "pyproject.toml", "docker-entrypoint.sh"):
        assert needed not in lines
        assert f"/{needed}" not in lines
    assert "*" not in lines or any(ln.startswith("!") for ln in lines)


# --- compose: заметка ревью T02 -----------------------------------------------------------


def test_t02_note_db_healthcheck_has_start_period(compose: dict[str, Any]) -> None:
    """Ревью T02: у healthcheck db есть start_period (подготовка к depends_on service_healthy)."""
    hc = compose["services"]["db"].get("healthcheck")
    assert isinstance(hc, dict), "у db нет healthcheck"
    assert "start_period" in hc, "у healthcheck db нет start_period"


# --- семантика .dockerignore (шаблоны действуют от корня контекста) ----------------------


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Упрощённая семантика Docker: ``*`` и ``?`` не пересекают ``/``, ``**`` — любую глубину."""
    out = ""
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        elif pattern[i] == "[" and "]" in pattern[i:]:
            j = pattern.index("]", i)
            out += pattern[i : j + 1]
            i = j + 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(out + r"\Z")


def _is_ignored(rel_path: str, patterns: list[str]) -> bool:
    """Путь исключён, если шаблон совпал с ним или с любым его родительским каталогом."""
    parts = rel_path.split("/")
    prefixes = ["/".join(parts[: n + 1]) for n in range(len(parts))]
    ignored = False
    for pat in patterns:
        negate = pat.startswith("!")
        regex = _glob_to_regex(pat.lstrip("!").strip("/"))
        if any(regex.match(pref) for pref in prefixes):
            ignored = not negate
    return ignored


@pytest.mark.parametrize(
    "rel_path",
    [
        "app/__pycache__/x.cpython-312.pyc",
        "migrations/__pycache__/env.cpython-312.pyc",
        "app/domain/users/__pycache__/m.pyc",
        "tracker_backend.egg-info/PKG-INFO",
        "app/core/foo.pyc",
        "tests/test_x.py",
        ".venv/bin/python",
    ],
)
def test_dockerignore_excludes_nested_artifacts(repo_root: Path, rel_path: str) -> None:
    """NFR-4: шаблоны реально исключают вложенные артефакты (``**/`` для глубины)."""
    patterns = [
        ln.strip()
        for ln in _read(repo_root / "backend" / ".dockerignore").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert _is_ignored(rel_path, patterns), f"{rel_path} попадёт в контекст сборки"


@pytest.mark.parametrize(
    "rel_path",
    ["app/main.py", "migrations/env.py", "alembic.ini", "pyproject.toml", "docker-entrypoint.sh"],
)
def test_dockerignore_keeps_sources(repo_root: Path, rel_path: str) -> None:
    patterns = [
        ln.strip()
        for ln in _read(repo_root / "backend" / ".dockerignore").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert not _is_ignored(rel_path, patterns), rel_path
