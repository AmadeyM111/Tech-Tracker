"""Помощники инфраструктурных тестов поднятого стека (T26, маркер ``infra_stack``).

Стек поднимает исполнитель, тесты только обращаются к нему:

    HTTP_PORT=18080 HTTPS_PORT=18443 docker compose -p gostracker-infratest up -d --build --wait
    GT_INFRA_STACK=1 GT_INFRA_PROJECT=gostracker-infratest HTTP_PORT=18080 HTTPS_PORT=18443 \
        pytest -q -m infra_stack backend/tests/infra

Тесты ``test_stack_first_run.py`` рассчитаны на СВЕЖИЙ стек (чистые тома): они идут по сценарию
первого запуска по порядку определения в файле и меняют состояние (смена пароля первого ТА).

Защита: проект обязан начинаться с ``gostracker-infratest``; стек пользователя
(``gostracker``/``gostracker-dev``) и БД ``tracker`` не затрагиваются. Дополнительные контейнеры,
тома и каталоги тестов называются ``gt-t26-*``.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import ssl
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

ENABLED = os.environ.get("GT_INFRA_STACK") == "1"
PROJECT = os.environ.get("GT_INFRA_PROJECT", "gostracker-infratest")
HTTP_PORT = int(os.environ.get("HTTP_PORT", "18080"))
HTTPS_PORT = int(os.environ.get("HTTPS_PORT", "18443"))
HOST = "127.0.0.1"
ORIGIN = f"https://{HOST}:{HTTPS_PORT}"
SERVICES = ("db", "api", "web")

requires_stack = pytest.mark.skipif(
    not ENABLED, reason="нужен поднятый стек: GT_INFRA_STACK=1 (см. tasks.md T26)"
)
infra_stack = pytest.mark.infra_stack


def stack_marks() -> list[Any]:
    return [infra_stack, requires_stack]


def _guard() -> None:
    assert PROJECT.startswith("gostracker-infratest"), (
        f"GT_INFRA_PROJECT={PROJECT!r}: допустим только проект gostracker-infratest*"
    )
    assert HTTP_PORT != 80 and HTTPS_PORT != 443 and HTTPS_PORT not in (5432,), (
        "порты тестового стека должны отличаться от стандартных (18080/18443)"
    )


def run(
    args: list[str], *, input: str | None = None, timeout: float = 180, check: bool = True
) -> subprocess.CompletedProcess[str]:
    res = subprocess.run(
        args,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        input=input,
        timeout=timeout,
        check=False,
        env={**os.environ, "HTTP_PORT": str(HTTP_PORT), "HTTPS_PORT": str(HTTPS_PORT)},
    )
    if check and res.returncode != 0:
        raise AssertionError(
            f"{' '.join(args[:5])} -> rc={res.returncode}\n"
            f"{res.stdout[-1500:]}\n{res.stderr[-1500:]}"
        )
    return res


def compose(*args: str, **kw: Any) -> subprocess.CompletedProcess[str]:
    _guard()
    return run(["docker", "compose", "-p", PROJECT, *args], **kw)


def docker(*args: str, **kw: Any) -> subprocess.CompletedProcess[str]:
    return run(["docker", *args], **kw)


def exec_in(service: str, *cmd: str, input: str | None = None, check: bool = True) -> str:
    flags = ["-T"]
    return compose("exec", *flags, service, *cmd, input=input, check=check).stdout


def sh_in(service: str, script: str, *, check: bool = True) -> str:
    return exec_in(service, "sh", "-c", script, check=check)


def psql(sql: str) -> str:
    """Запрос в БД стека учётной записью приложения (-At: без выравнивания)."""
    return exec_in(
        "db", "sh", "-c", 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -v ON_ERROR_STOP=1',
        input=sql,
    ).strip()  # fmt: skip


def container_id(service: str) -> str:
    cid = compose("ps", "-q", service).stdout.strip()
    assert cid, f"сервис {service} не запущен в проекте {PROJECT}"
    return cid


def inspect(service: str, fmt: str) -> str:
    return docker("inspect", "-f", fmt, container_id(service)).stdout.strip()


def wait_healthy(service: str, timeout: float = 150) -> None:
    deadline = time.monotonic() + timeout
    status = "?"
    while time.monotonic() < deadline:
        status = inspect(service, "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}")
        if status == "healthy":
            return
        time.sleep(1)
    raise AssertionError(f"{service}: healthcheck не стал healthy за {timeout:.0f} с ({status})")


def wait_api_through_web(timeout: float = 90) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if request("/api/v1/health").status == 200:
                return
        except (OSError, http.client.HTTPException):
            pass
        time.sleep(1)
    raise AssertionError("api не отвечает через web")


def restart(service: str) -> None:
    compose("restart", service, timeout=240)
    wait_healthy(service)
    if service in ("api", "web", "db"):
        wait_api_through_web()


def logs(*services: str, since: str | None = None) -> str:
    args = ["logs", "--no-color", "--no-log-prefix"]
    if since:
        args += ["--since", since]
    res = compose(*args, *services, check=False, timeout=120)
    return res.stdout + res.stderr


# --- HTTP-клиент (самоподписанный сертификат, без проверки) --------------------------------


@dataclass
class Resp:
    status: int
    headers: list[tuple[str, str]] = field(default_factory=list)
    body: bytes = b""

    def header(self, name: str) -> str | None:
        for k, v in self.headers:
            if k.lower() == name.lower():
                return v
        return None

    def all(self, name: str) -> list[str]:
        return [v for k, v in self.headers if k.lower() == name.lower()]

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))

    def cookie(self, name: str = "gt_session") -> tuple[str, str] | None:
        """(значение, сырая строка Set-Cookie) или None."""
        for raw in self.all("set-cookie"):
            if raw.startswith(f"{name}="):
                return raw.split(";", 1)[0].split("=", 1)[1], raw
        return None


def request(
    path: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    json_body: Any = None,
    tls: bool = True,
    cookie: str | None = None,
    origin: str | None = None,
    timeout: float = 60,
) -> Resp:
    hdrs = dict(headers or {})
    if json_body is not None:
        body = json.dumps(json_body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    if cookie:
        hdrs["Cookie"] = f"gt_session={cookie}"
    if origin:
        hdrs["Origin"] = origin
    if tls:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        conn: http.client.HTTPConnection = http.client.HTTPSConnection(
            HOST, HTTPS_PORT, context=ctx, timeout=timeout
        )
    else:
        conn = http.client.HTTPConnection(HOST, HTTP_PORT, timeout=timeout)
    try:
        conn.request(method, path, body=body, headers=hdrs)
        r = conn.getresponse()
        data = r.read()
        return Resp(r.status, list(r.getheaders()), data)
    finally:
        conn.close()


def s_client(*opts: str) -> str:
    """Вывод ``openssl s_client`` внутри контейнера web к его же порту 443."""
    return sh_in(
        "web",
        f"openssl s_client -connect 127.0.0.1:443 -servername localhost {' '.join(opts)} "
        "</dev/null 2>&1 || true",
    )


def json_lines(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ln in text.splitlines():
        ln = ln.strip()
        if ln.startswith("{") and ln.endswith("}"):
            try:
                out.append(json.loads(ln))
            except ValueError:
                continue
    return out


def parse_env_file_values(path: Path) -> list[str]:
    vals: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            vals.append(line.partition("=")[2].strip())
    return vals


def read_initial_credentials() -> dict[str, str]:
    raw = exec_in("api", "cat", "/data/secrets/initial-admin-password.txt")
    creds = dict(ln.split("=", 1) for ln in raw.splitlines() if re.match(r"^(login|password)=", ln))
    assert set(creds) == {"login", "password"}, "формат файла: login=…\\npassword=…"
    return creds
