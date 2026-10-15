"""T02: статический разбор compose-файлов (plan D-18, §4.12).

Покрывает AC-105 (статическая часть), FR-6a, AC-95 (для сервиса db).
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.infra_static


def parse_env_file(path: Path) -> dict[str, str]:
    """Разбор KEY=VALUE; пустые строки и комментарии пропускаются."""
    assert path.is_file(), f"нет файла {path}"
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


def _db(cfg: dict[str, Any]) -> dict[str, Any]:
    assert "db" in cfg["services"]
    db = cfg["services"]["db"]
    assert isinstance(db, dict)
    return db


def _env(service: dict[str, Any]) -> dict[str, str]:
    env = service.get("environment", {})
    if isinstance(env, list):
        return {k: v for k, _, v in (item.partition("=") for item in env)}
    return {k: str(v) for k, v in env.items()}


def test_ac105_db_has_no_ports_in_delivery_compose(compose: dict[str, Any]) -> None:
    """AC-105, FR-6a: у db в поставляемом compose нет ports."""
    assert "ports" not in _db(compose)


def test_ac105_no_override_files_in_repo(repo_files: list[Path]) -> None:
    """AC-105: нет файлов, которые Compose подхватывает автоматически."""
    patterns = ["docker-compose.override.y*ml", "compose.override.y*ml"]
    found = [str(p) for p in repo_files if any(fnmatch.fnmatch(p.name, pat) for pat in patterns)]
    assert found == []


@pytest.mark.parametrize(
    ("var", "default"),
    [("POSTGRES_USER", "tracker"), ("POSTGRES_PASSWORD", "tracker"), ("POSTGRES_DB", "tracker")],
)
def test_fr6a_postgres_env_from_dotenv_with_defaults(
    compose: dict[str, Any], var: str, default: str
) -> None:
    """FR-6a / plan §4.12: POSTGRES_* берутся из окружения с умолчаниями."""
    assert _env(_db(compose)).get(var) == f"${{{var}:-{default}}}"


def test_ac95_db_healthcheck_pg_isready(compose: dict[str, Any]) -> None:
    """plan §4.12: healthcheck db — pg_isready."""
    hc = _db(compose).get("healthcheck")
    assert hc, "у db нет healthcheck"
    test = hc["test"]
    cmd = test if isinstance(test, str) else " ".join(test)
    assert "pg_isready" in cmd


def test_ac95_db_logging_json_file_10m_x5(compose: dict[str, Any]) -> None:
    """AC-95 (для db): драйвер json-file, 10m x 5 файлов."""
    logging_cfg = _db(compose).get("logging")
    assert logging_cfg, "у db нет logging"
    assert logging_cfg["driver"] == "json-file"
    opts = {k: str(v) for k, v in logging_cfg["options"].items()}
    assert opts == {"max-size": "10m", "max-file": "5"}


def test_fr6a_dev_compose_publishes_only_loopback_db_port(
    compose_dev: dict[str, Any],
) -> None:
    """FR-6a, D-18: dev-файл добавляет только db.ports = 127.0.0.1:5432:5432."""
    assert list(compose_dev["services"]) == ["db"]
    assert compose_dev["services"]["db"] == {"ports": ["127.0.0.1:5432:5432"]}
    assert set(compose_dev) <= {"services", "name"}


def test_fr6a_env_example_has_postgres_vars(repo_root: Path) -> None:
    """plan §4.12: .env.example содержит POSTGRES_USER/PASSWORD/DB."""
    env = parse_env_file(repo_root / ".env.example")
    for var in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
        assert env.get(var), f"{var} отсутствует или пуст в .env.example"


def test_fr6a_env_example_has_no_secret_key_or_cookie_secure(repo_root: Path) -> None:
    """plan §4.12: SECRET_KEY и COOKIE_SECURE в .env.example нет (даже в комментариях)."""
    text = (repo_root / ".env.example").read_text(encoding="utf-8")
    assert "SECRET_KEY" not in text
    assert "COOKIE_SECURE" not in text


def test_fr6a_dev_env_example_exists_with_dev_values(repo_root: Path) -> None:
    """plan §4.12: deploy/dev.env.example с настройками локальной разработки."""
    env = parse_env_file(repo_root / "deploy" / "dev.env.example")
    assert env["DATABASE_URL"] == ("postgresql+asyncpg://tracker:tracker@localhost:5432/tracker")
    assert env["COOKIE_SECURE"] == "false"
    assert env["ENV"] == "local"
    assert env["EXPOSE_API_DOCS"] == "true"
    assert env["DATA_DIR"] == "./.data"


# =============================================================================================
# T26: поставляемый docker-compose.yml целиком (plan §4.12, D-17..D-20; AC-95, AC-105, FR-48,
# FR-51, FR-58, FR-63, NFR-3, NFR-9) и .env.example. Существующие проверки выше не менялись.
# =============================================================================================

import re  # noqa: E402
import subprocess  # noqa: E402

LOGGING_ANCHOR = {"driver": "json-file", "options": {"max-size": "10m", "max-file": "5"}}
ALL_SERVICES = ("db", "api", "web")


def _svc(cfg: dict[str, Any], name: str) -> dict[str, Any]:
    services = cfg["services"]
    assert name in services, f"в docker-compose.yml нет сервиса {name!r}"
    svc = services[name]
    assert isinstance(svc, dict)
    return svc


def _raw_env(service: dict[str, Any]) -> dict[str, Any]:
    """environment как есть (без приведения значений к str): отличает "true" от true."""
    env = service.get("environment", {})
    if isinstance(env, list):
        return {k: v for k, _, v in (item.partition("=") for item in env)}
    return dict(env)


def _build(service: dict[str, Any], root: Path) -> tuple[Path, Path]:
    """(абсолютный контекст сборки, абсолютный путь Dockerfile)."""
    build = service.get("build")
    assert build, "у сервиса нет build"
    if isinstance(build, str):
        build = {"context": build}
    context = (root / build.get("context", ".")).resolve()
    dockerfile = (context / build.get("dockerfile", "Dockerfile")).resolve()
    return context, dockerfile


def _hc_text(service: dict[str, Any]) -> str:
    hc = service.get("healthcheck")
    assert isinstance(hc, dict), "нет healthcheck"
    test = hc["test"]
    return test if isinstance(test, str) else " ".join(str(x) for x in test)


def test_fr48_delivery_compose_has_exactly_db_api_web(compose: dict[str, Any]) -> None:
    """FR-48, plan §4.12: сервисы db, api, web; ops (R1.4) в этом этапе отсутствует."""
    assert set(compose["services"]) == set(ALL_SERVICES)


@pytest.mark.parametrize("name", ALL_SERVICES)
def test_ac95_every_service_has_json_file_10m_x5(compose: dict[str, Any], name: str) -> None:
    """AC-95, FR-51: db, api и TLS-прокси web — json-file, 10m x 5."""
    logging_cfg = _svc(compose, name).get("logging")
    assert logging_cfg, f"у {name} нет logging"
    normalised = {
        "driver": logging_cfg.get("driver"),
        "options": {k: str(v) for k, v in (logging_cfg.get("options") or {}).items()},
    }
    assert normalised == LOGGING_ANCHOR


def test_ac95_logging_declared_once_as_anchor(repo_root: Path, compose: dict[str, Any]) -> None:
    """plan §4.12: x-logging &logging на верхнем уровне и ссылки *logging в сервисах."""
    assert "x-logging" in compose
    text = (repo_root / "docker-compose.yml").read_text(encoding="utf-8")
    assert len(re.findall(r"\*logging\b", text)) >= len(ALL_SERVICES)


def test_fr48_named_volumes_are_pgdata_appdata_tls_generated(compose: dict[str, Any]) -> None:
    """D-19, plan §4.12: ровно три именных тома."""
    assert set(compose.get("volumes") or {}) == {"pgdata", "appdata", "tls-generated"}


def _mounts(service: dict[str, Any]) -> set[str]:
    return {v if isinstance(v, str) else f"{v['source']}:{v['target']}" for v in service["volumes"]}


def test_d19_service_volume_mounts(compose: dict[str, Any]) -> None:
    """D-19: pgdata -> db, appdata -> /data api, tls-generated + ./deploy/tls:ro -> web."""
    assert "pgdata:/var/lib/postgresql/data" in _mounts(_svc(compose, "db"))
    assert "appdata:/data" in _mounts(_svc(compose, "api"))
    web = _mounts(_svc(compose, "web"))
    assert "tls-generated:/var/lib/gostracker/tls" in web
    assert "./deploy/tls:/etc/gostracker/tls:ro" in web


def test_fr6a_only_web_publishes_ports(compose: dict[str, Any]) -> None:
    """AC-105, D-18: ports есть только у web; db и api без ports (и без expose наружу)."""
    assert "ports" not in _svc(compose, "db")
    assert "ports" not in _svc(compose, "api")
    assert "ports" in _svc(compose, "web")


def test_fr63_web_ports_from_env_with_defaults(compose: dict[str, Any]) -> None:
    """plan §4.12: "${HTTP_PORT:-80}:80" и "${HTTPS_PORT:-443}:443", без привязки к адресу."""
    ports = [str(p) for p in _svc(compose, "web")["ports"]]
    assert sorted(ports) == sorted(["${HTTP_PORT:-80}:80", "${HTTPS_PORT:-443}:443"])


def test_fr58_api_cookie_secure_is_literal_true(compose: dict[str, Any]) -> None:
    """D-18, FR-58, AC-105: COOKIE_SECURE: "true" литералом, не из .env."""
    env = _raw_env(_svc(compose, "api"))
    assert env.get("COOKIE_SECURE") == "true"
    assert isinstance(env["COOKIE_SECURE"], str), 'значение должно быть строкой "true"'


def test_fr58_api_env_has_no_dev_switches(compose: dict[str, Any]) -> None:
    """AC-105: поставка не включает режим разработки (ENV=local, документация API)."""
    env = _env(_svc(compose, "api"))
    assert env.get("ENV", "production") == "production"
    assert env.get("EXPOSE_API_DOCS", "false").lower() in ("false", "0", "")
    assert "COOKIE_SECURE" in env and env["COOKIE_SECURE"].lower() == "true"


def test_fr6_api_database_url_points_to_db_service(compose: dict[str, Any]) -> None:
    """plan §4.12: DATABASE_URL строится из POSTGRES_* на хост db:5432."""
    url = _env(_svc(compose, "api")).get("DATABASE_URL", "")
    pattern = (
        r"postgresql\+asyncpg://\$\{POSTGRES_USER(:-tracker)?\}:\$\{POSTGRES_PASSWORD(:-tracker)?\}"
        r"@db:5432/\$\{POSTGRES_DB(:-tracker)?\}"
    )
    assert re.fullmatch(pattern, url), url


def test_d19_api_data_dir_is_data(compose: dict[str, Any]) -> None:
    assert _env(_svc(compose, "api")).get("DATA_DIR") == "/data"


@pytest.mark.parametrize(
    ("var", "default"),
    [("ARGON2_TIME_COST", "3"), ("ARGON2_MEMORY_COST_KIB", "131072"), ("ARGON2_PARALLELISM", "2")],
)
def test_nfr9_api_argon2_from_env_with_defaults(
    compose: dict[str, Any], var: str, default: str
) -> None:
    """plan §4.12: ARGON2_* из .env с умолчаниями Settings (иначе .env.example не действует)."""
    assert _env(_svc(compose, "api")).get(var) == f"${{{var}:-{default}}}"


def test_d20_secret_key_not_required_and_has_no_default(compose: dict[str, Any]) -> None:
    """D-20, AC-23, NFR-3: SECRET_KEY необязателен (ключ создаётся в /data/secrets) и не имеет
    значения-заглушки. ``${SECRET_KEY:?...}`` запрещён: он ломает ``cp .env.example .env`` + up.
    (Расходится с формулировкой задачи T26; см. PLAN_ISSUE в отчёте.)"""
    for name in ALL_SERVICES:
        env = _raw_env(_svc(compose, name))
        if "SECRET_KEY" not in env:
            continue
        value = str(env["SECRET_KEY"])
        assert re.fullmatch(r"\$\{SECRET_KEY(:-)?\}", value) or value == "", (
            f"{name}: SECRET_KEY={value!r}: допустимы отсутствие, пустое значение или "
            "${SECRET_KEY} без умолчания"
        )


def test_nfr9_compose_has_no_secrets_or_placeholders(repo_root: Path) -> None:
    """NFR-9: в compose нет секретов и значений-заглушек ключа/пароля администратора."""
    text = (repo_root / "docker-compose.yml").read_text(encoding="utf-8")
    low = text.lower()
    assert "change-me" not in low
    assert "-----begin" not in low
    assert not re.search(r"^\s*secrets\s*:", text, re.M), "docker secrets не используются"
    assert not re.search(r"initial[_-]admin[_-]password", low)
    # PASSWORD-переменные: только ссылки на .env (допустим единственный литерал-умолчание POSTGRES)
    for m in re.finditer(r"^\s*([A-Z_]*PASSWORD[A-Z_]*)\s*:\s*(.+)$", text, re.M):
        assert m.group(2).strip().startswith("${"), f"литерал пароля: {m.group(1)}"


def test_fr48_api_healthcheck_is_get_not_head(compose: dict[str, Any]) -> None:
    """T25 п.4: healthcheck api — GET /api/v1/health (HEAD даёт 405)."""
    cmd = _hc_text(_svc(compose, "api"))
    assert "/api/v1/health" in cmd
    low = cmd.lower()
    assert "head" not in low
    assert not re.search(r"\bcurl\b.*\s-[a-z]*i", low), "curl -I - это HEAD"
    assert "--spider" not in low, "wget --spider шлёт HEAD"
    hc = _svc(compose, "api")["healthcheck"]
    assert "start_period" in hc, "bootstrap ждёт БД до 60 с"


def test_fr48_web_has_healthcheck(repo_root: Path, compose: dict[str, Any]) -> None:
    """T25 п.4: у web есть healthcheck (в compose или HEALTHCHECK в Dockerfile)."""
    web = _svc(compose, "web")
    if isinstance(web.get("healthcheck"), dict) and web["healthcheck"].get("test"):
        assert web["healthcheck"]["test"] != ["NONE"]
        return
    dockerfile = (repo_root / "deploy" / "web" / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"^\s*HEALTHCHECK\s+(?!NONE)", dockerfile, re.M), (
        "нет healthcheck у web ни в compose, ни HEALTHCHECK в deploy/web/Dockerfile"
    )


def test_fr48_depends_on_service_healthy(compose: dict[str, Any]) -> None:
    """plan §4.12: api ждёт healthy db, web ждёт healthy api."""
    api_dep = _svc(compose, "api").get("depends_on")
    web_dep = _svc(compose, "web").get("depends_on")
    assert isinstance(api_dep, dict) and api_dep.get("db") == {"condition": "service_healthy"}
    assert isinstance(web_dep, dict) and web_dep.get("api") == {"condition": "service_healthy"}


def test_t25_web_env_https_port_and_server_name_defaults(compose: dict[str, Any]) -> None:
    """T25 п.4: web получает HTTPS_PORT и TLS_SERVER_NAME с умолчаниями."""
    env = _env(_svc(compose, "web"))
    assert env.get("HTTPS_PORT") == "${HTTPS_PORT:-443}"
    assert env.get("TLS_SERVER_NAME") == "${TLS_SERVER_NAME:-localhost}"


def test_t25_build_contexts(repo_root: Path, compose: dict[str, Any]) -> None:
    """T25 п.4: web — контекст корень + deploy/web/Dockerfile; api — строго ./backend."""
    ctx, dockerfile = _build(_svc(compose, "web"), repo_root)
    assert ctx == repo_root.resolve()
    assert dockerfile == (repo_root / "deploy" / "web" / "Dockerfile").resolve()
    ctx, dockerfile = _build(_svc(compose, "api"), repo_root)
    assert ctx == (repo_root / "backend").resolve()
    assert dockerfile == (repo_root / "backend" / "Dockerfile").resolve()


def test_t25_web_is_single_replica(compose: dict[str, Any]) -> None:
    """T25 п.4: один web на том tls-generated: ни replicas, ни scale; нет container_name."""
    for name in ALL_SERVICES:
        svc = _svc(compose, name)
        assert "scale" not in svc
        assert (svc.get("deploy") or {}).get("replicas", 1) == 1
        assert "container_name" not in svc, "container_name ломает отдельный проект infratest"


def test_fr6a_no_service_mentions_port_5432(compose: dict[str, Any]) -> None:
    """FR-6a: ни один сервис не публикует 5432 ни в какой форме."""
    text = yaml_dump_ports(compose)
    assert "5432" not in text


def yaml_dump_ports(cfg: dict[str, Any]) -> str:
    return " ".join(
        str(s.get("ports", "")) + str(s.get("expose", "")) for s in cfg["services"].values()
    )


# --- .env.example (plan §4.12) ----------------------------------------------------------


def _env_example_lines(repo_root: Path) -> list[str]:
    return (repo_root / ".env.example").read_text(encoding="utf-8").splitlines()


def test_fr63_env_example_has_ports_and_server_name(repo_root: Path) -> None:
    """plan §4.12: HTTP_PORT=80, HTTPS_PORT=443, TLS_SERVER_NAME=localhost."""
    env = parse_env_file(repo_root / ".env.example")
    assert env.get("HTTP_PORT") == "80"
    assert env.get("HTTPS_PORT") == "443"
    assert env.get("TLS_SERVER_NAME") == "localhost"


def test_nfr9_env_example_argon2_commented_out(repo_root: Path) -> None:
    """plan §4.12: ARGON2_* присутствуют закомментированными (значения - умолчания compose)."""
    lines = _env_example_lines(repo_root)
    active = parse_env_file(repo_root / ".env.example")
    for var, default in (
        ("ARGON2_TIME_COST", "3"),
        ("ARGON2_MEMORY_COST_KIB", "131072"),
        ("ARGON2_PARALLELISM", "2"),
    ):
        assert var not in active, f"{var} должен быть закомментирован"
        assert any(re.fullmatch(rf"#\s*{var}={default}", ln.strip()) for ln in lines), var


def test_nfr9_env_example_has_comments_and_no_real_secrets(repo_root: Path) -> None:
    """NFR-9: .env.example с пояснениями; нет ключей, токенов, длинных случайных значений."""
    lines = _env_example_lines(repo_root)
    assert sum(1 for ln in lines if ln.strip().startswith("#")) >= 3, "нужны комментарии"
    text = "\n".join(lines)
    assert "PRIVATE KEY" not in text
    for key, value in parse_env_file(repo_root / ".env.example").items():
        assert len(value) < 32, f"{key}: похоже на реальный секрет"
        assert not re.fullmatch(r"[0-9a-fA-F]{32,}", value)


def test_t16_env_example_documents_initial_admin_login_without_whitespace(
    repo_root: Path,
) -> None:
    """Заметка T16: INITIAL_ADMIN_LOGIN описан (читается без strip); значение без пробелов."""
    lines = _env_example_lines(repo_root)
    mention = [ln for ln in lines if "INITIAL_ADMIN_LOGIN" in ln]
    assert mention, "INITIAL_ADMIN_LOGIN нужно описать в .env.example"
    for ln in mention:
        if ln.lstrip().startswith("#"):
            continue
        _, _, value = ln.partition("=")
        assert value == value.strip(), "пробелы по краям значения дают ошибку запуска"
        assert re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,63}", value), "логин по FR-73"
    assert any(ln.lstrip().startswith("#") and "пробел" in ln.lower() for ln in lines), (
        "в комментарии скажите про пробелы/перевод строки по краям"
    )


def test_t16_api_passes_initial_admin_login_with_default(compose: dict[str, Any]) -> None:
    """Иначе переменная из .env не доходит до контейнера; пустое значение -> admin."""
    assert _env(_svc(compose, "api")).get("INITIAL_ADMIN_LOGIN") == "${INITIAL_ADMIN_LOGIN:-admin}"


def test_t25_gitignore_tls_dir_and_env(repo_root: Path) -> None:
    """T25 п.3, NFR-9: deploy/tls/* игнорируется, кроме README.md; .env игнорируется."""
    lines = [ln.strip() for ln in (repo_root / ".gitignore").read_text("utf-8").splitlines()]
    assert "deploy/tls/*" in lines
    assert "!deploy/tls/README.md" in lines
    assert lines.index("!deploy/tls/README.md") > lines.index("deploy/tls/*")

    def ignored(path: str) -> bool:
        res = subprocess.run(
            ["git", "check-ignore", "-q", "--no-index", path],
            cwd=repo_root,
            capture_output=True,
            check=False,
        )
        return res.returncode == 0

    assert ignored(".env")
    assert not ignored(".env.example")
    assert ignored("deploy/tls/tls.key")
    assert ignored("deploy/tls/server.pem")
    assert not ignored("deploy/tls/README.md")


# --- T27 (перенесено из ревью T26): таймауты сервера и restart policy ---------------------


def _db_command_text(compose: dict[str, Any]) -> str:
    command = _db(compose).get("command")
    assert command, "у db нет command: серверные таймауты не заданы (plan §4.12, решения T26)"
    return " ".join(command) if isinstance(command, list) else str(command)


@pytest.mark.parametrize("param", ["lock_timeout", "idle_in_transaction_session_timeout"])
def test_t27_db_command_sets_positive_server_timeout(compose: dict[str, Any], param: str) -> None:
    """T26 п.2: параметр задан в command сервиса db с положительным значением (0 = выключен)."""
    import re

    text = _db_command_text(compose)
    m = re.search(rf"(?<![\w]){param}[= ]\s*'?(\d+)\s*(ms|s|min|h)?'?(?!\w)", text)
    assert m, f"в command db нет {param}=<значение>: {text!r}"
    assert int(m.group(1)) > 0, f"{param} должен быть > 0"


@pytest.mark.parametrize("service", ["db", "api", "web"])
def test_t27_service_restart_unless_stopped(compose: dict[str, Any], service: str) -> None:
    """T26 п.6, plan §4.12 (а): после перезагрузки хоста стек поднимается сам."""
    assert compose["services"][service].get("restart") == "unless-stopped"
