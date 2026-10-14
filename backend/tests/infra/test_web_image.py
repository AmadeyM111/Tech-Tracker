"""T25: образ web - TLS-прокси nginx и статика SPA (plan §4.12, D-17, D-20; FR-63, NFR-4, AC-40).

Две части, обе под маркером ``infra_static``:

1. Статические проверки файлов ``deploy/web/*``, ``deploy/tls/README.md``, ``.gitignore``
   (Docker не нужен).
2. Проверки через Docker (пропуск без Docker): ``docker build -f deploy/web/Dockerfile
   -t gostracker-web:test .`` и запуск контейнеров ``gt-t25-*`` на портах 127.0.0.1. В качестве
   заглушки ``api`` используется сам собранный образ с nginx-конфигом, который отдаёт заголовки
   запроса. Всё созданное удаляется в finalizer'ах. Стек пользователя и dev-БД не затрагиваются.

Контракт образа (то, что тесты считают интерфейсом):
- переменные окружения: ``HTTPS_PORT`` (внешний порт в Location редиректа), ``TLS_SERVER_NAME``
  (CN и SAN самоподписанного сертификата);
- сертификат оператора: ``/etc/gostracker/tls/tls.crt`` + ``tls.key``;
- сгенерированный: каталог ``/var/lib/gostracker/tls/`` (файл ключа ``*.key``, режим 0600);
- слушает 80 (только 308) и 443 (TLS), статика в ``/usr/share/nginx/html``.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import socket
import ssl
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

pytestmark = pytest.mark.infra_static

IMAGE = "gostracker-web:test"
NETWORK = "gt-t25-net"
STUB = "gt-t25-api-stub"
WEB = "gt-t25-web"
WEB2 = "gt-t25-web2"
WEB_OP = "gt-t25-web-operator"
WEB_NOAPI = "gt-t25-web-noapi"
WEB_NONAME = "gt-t25-web-noname"
VOL = "gt-t25-tls"
SERVER_NAME = "tracker.test"
CSP = (
    "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
    "frame-ancestors 'none'"
)

REPO_ROOT = Path(__file__).resolve().parents[3]
WEB_DIR = REPO_ROOT / "deploy" / "web"


# --- статические помощники ---------------------------------------------------------------


def _read(path: Path) -> str:
    assert path.is_file(), f"нет файла {path.relative_to(REPO_ROOT)}"
    return path.read_text(encoding="utf-8")


def _instructions(dockerfile: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    buf = ""
    for raw in dockerfile.splitlines():
        line = raw.rstrip()
        if line.lstrip().startswith("#") or (not line.strip() and not buf):
            continue
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        item = (buf + line).strip()
        buf = ""
        head, _, rest = item.partition(" ")
        out.append((head.upper(), rest.strip()))
    return out


def _strip_comments(conf: str) -> str:
    return "\n".join(re.sub(r"(^|\s)#.*$", "", ln) for ln in conf.splitlines())


def _block(conf: str, opener_regex: str) -> str:
    """Тело ``server { ... }``, содержащего директиву, подходящую под regex (по скобкам)."""
    for m in re.finditer(r"\bserver\s*\{", conf):
        depth, i = 1, m.end()
        while i < len(conf) and depth:
            depth += {"{": 1, "}": -1}.get(conf[i], 0)
            i += 1
        body = conf[m.end() : i - 1]
        if re.search(opener_regex, body):
            return body
    raise AssertionError(f"нет server-блока с {opener_regex!r}")


@pytest.fixture(scope="module")
def template() -> str:
    return _strip_comments(_read(WEB_DIR / "default.conf.template"))


@pytest.fixture(scope="module")
def tls_script() -> str:
    return _read(WEB_DIR / "10-gostracker-tls.sh")


@pytest.fixture(scope="module")
def dockerfile() -> list[tuple[str, str]]:
    return _instructions(_read(WEB_DIR / "Dockerfile"))


# --- статика: Dockerfile -----------------------------------------------------------------


def test_fr63_dockerfile_stages_and_bases(dockerfile: list[tuple[str, str]]) -> None:
    froms = [a.split()[0] for h, a in dockerfile if h == "FROM"]
    assert len(froms) >= 2, "нужна многоэтапная сборка: node (фронтенд) и nginx"
    assert froms[0] == "node:22-alpine"
    last = froms[-1]
    assert re.fullmatch(r"nginx:(stable|\d+(\.\d+){0,2})-alpine(\d+(\.\d+)*)?", last), (
        f"итоговый образ должен быть nginx:<stable>-alpine, а не {last!r}"
    )


def test_fr63_dockerfile_builds_frontend_and_installs_openssl(
    dockerfile: list[tuple[str, str]],
) -> None:
    runs = " && ".join(a for h, a in dockerfile if h == "RUN")
    assert "npm ci" in runs
    assert "npm run build" in runs
    assert re.search(r"apk\s+add\s+--no-cache\s+(\S+\s+)*openssl", runs)


def test_fr63_dockerfile_copies_static_template_and_script(
    dockerfile: list[tuple[str, str]],
) -> None:
    copies = [a for h, a in dockerfile if h in ("COPY", "ADD")]
    joined = "\n".join(copies)
    assert re.search(r"--from=\S+\s+\S*dist\S*\s+/usr/share/nginx/html", joined), (
        "статика из frontend/dist должна попасть в /usr/share/nginx/html"
    )
    assert re.search(
        r"deploy/web/default\.conf\.template\s+/etc/nginx/templates/(default\.conf\.template)?\s*$",
        joined,
        re.M,
    )
    assert re.search(
        r"deploy/web/10-gostracker-tls\.sh\s+/docker-entrypoint\.d/(10-gostracker-tls\.sh)?\s*$",
        joined,
        re.M,
    )


def test_fr63_dockerfile_script_is_executable(dockerfile: list[tuple[str, str]]) -> None:
    mode_ok = os.access(WEB_DIR / "10-gostracker-tls.sh", os.X_OK)
    text = "\n".join(a for h, a in dockerfile)
    chmod_ok = bool(re.search(r"chmod\s+\S*\+x\S*\s+\S*10-gostracker-tls\.sh", text)) or bool(
        re.search(r"COPY\s+--chmod=[0-7]*[1357]{1}\S*\s+deploy/web/10-gostracker-tls\.sh", text)
    )
    assert mode_ok or chmod_ok, "скрипт не исполняемый: nginx entrypoint его пропустит"


def test_fr63_dockerfile_never_copies_keys(dockerfile: list[tuple[str, str]]) -> None:
    for head, args in dockerfile:
        if head in ("COPY", "ADD"):
            assert "deploy/tls" not in args, f"каталог TLS в образе: {head} {args}"
            assert not re.search(r"\.(key|crt|pem)\b", args), f"сертификат/ключ в образе: {args}"
            assert not re.search(r"(^|\s)\.\s+\S", args) or "--from" in args, (
                "COPY . . тянет deploy/tls и .env в образ; копировать только нужное"
            )
        if head in ("ENV", "ARG"):
            assert not re.search(r"PRIVATE KEY|SECRET", args, re.I)


def test_fr63_dockerfile_exposes_http_https(dockerfile: list[tuple[str, str]]) -> None:
    exposed = " ".join(a for h, a in dockerfile if h == "EXPOSE")
    assert "80" in exposed.split() or "80/tcp" in exposed
    assert "443" in exposed.split() or "443/tcp" in exposed


# --- статика: шаблон nginx ---------------------------------------------------------------


def test_ac40_template_http_server_only_redirects(template: str) -> None:
    body = _block(template, r"listen\s+(\[::\]:)?80\b")
    assert re.search(r"return\s+308\s+https://\$host:\$\{HTTPS_PORT\}\$request_uri\s*;", body)
    for forbidden in ("proxy_pass", "root ", "try_files", "alias ", "index "):
        assert forbidden not in body, f"сервер :80 не должен содержать {forbidden!r}"
    assert not re.search(r"\blocation\b", body), "сервер :80 - только return, без location"


def test_fr63_template_tls_policy(template: str) -> None:
    body = _block(template, r"listen\s+(\[::\]:)?443\s+ssl")
    assert re.search(r"ssl_protocols\s+TLSv1\.2\s+TLSv1\.3\s*;", body + template)
    assert "TLSv1 " not in template and "TLSv1.1" not in template
    assert re.search(r"ssl_certificate\s+\S+;", template)
    assert re.search(r"ssl_certificate_key\s+\S+;", template)
    assert re.search(r"ssl_ciphers\s+\S+", template), (
        "нужен явный список шифров (Mozilla intermediate)"
    )
    assert "ECDHE-ECDSA-AES128-GCM-SHA256" in template


def test_nfr4_template_body_limit_and_json_413(template: str) -> None:
    assert re.search(r"client_max_body_size\s+12m\s*;", template)
    assert re.search(r"error_page\s+413\s+\S+", template)
    assert "application/json" in template
    assert '"detail"' in template and '"code"' in template, (
        "тело 413 - ErrorResponse {detail, code}"
    )


def test_fr63_template_lazy_upstream_and_headers(template: str) -> None:
    assert re.search(r"resolver\s+127\.0\.0\.11\b", template)
    m = re.search(r"proxy_pass\s+([^;]+);", template)
    assert m, "нет proxy_pass"
    assert "$" in m.group(1), "proxy_pass с переменной: nginx стартует без api"
    assert re.search(r"api:8000", template)
    assert re.search(r"proxy_set_header\s+Host\s+\$http_host\s*;", template)
    assert not re.search(r"proxy_set_header\s+Host\s+\$host\s*;", template)
    assert re.search(r"proxy_set_header\s+X-Forwarded-Proto\s+(\$scheme|https)\s*;", template)
    assert not re.search(
        r"proxy_set_header\s+X-Forwarded-Proto\s+\$http_x_forwarded_proto", template
    )


def test_fr63_template_spa_and_security_headers(template: str) -> None:
    assert re.search(r"try_files\s+\$uri\s+/index\.html\s*;", template)
    assert "/usr/share/nginx/html" in template
    for name in ("X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy"):
        assert re.search(rf"add_header\s+{name}\s+.+\s+always\s*;", template), name
    assert re.search(
        r"add_header\s+Content-Security-Policy\s+.*frame-ancestors 'none'.*always", template
    )
    assert "Strict-Transport-Security" not in template, "HSTS не включается (plan §4.12)"


# --- статика: скрипт TLS -----------------------------------------------------------------


def test_fr63_script_shape(tls_script: str) -> None:
    assert tls_script.startswith(("#!/bin/sh", "#!/usr/bin/env sh"))
    assert re.search(r"^\s*set\s+-[a-z]*e", tls_script, re.M)


def test_fr63_script_selection_and_generation(tls_script: str) -> None:
    assert "/etc/gostracker/tls/tls.crt" in tls_script
    assert "/etc/gostracker/tls/tls.key" in tls_script
    assert "/var/lib/gostracker/tls" in tls_script
    assert re.search(r"openssl\s+req\s+.*-x509", tls_script, re.S)
    for token in ("ec_paramgen_curve:prime256v1", "-nodes", "-days 825", "TLS_SERVER_NAME"):
        assert token in tls_script, token
    assert "subjectAltName=DNS:${TLS_SERVER_NAME},DNS:localhost,IP:127.0.0.1" in tls_script
    assert re.search(r"umask\s+0?77|chmod\s+0?600", tls_script), "ключ должен быть 0600"
    assert "-newkey ec" in tls_script


# --- статика: README и .gitignore --------------------------------------------------------


def test_fr63_tls_readme_documents_operator_cert() -> None:
    text = _read(REPO_ROOT / "deploy" / "tls" / "README.md")
    assert "tls.crt" in text and "tls.key" in text
    assert "самоподпис" in text.lower()
    assert "git" in text.lower(), "должно быть сказано, что ключи не коммитятся"


def test_fr63_gitignore_entries() -> None:
    lines = {ln.strip() for ln in _read(REPO_ROOT / ".gitignore").splitlines()}
    for entry in ("deploy/tls/*.crt", "deploy/tls/*.key", "backups/"):
        assert entry in lines, f"в .gitignore нет {entry}"
    assert lines & {"frontend/dist", "frontend/dist/", "dist", "dist/"}, (
        "frontend/dist не игнорируется"
    )
    assert "frontend/dist" in lines or "frontend/dist/" in lines, "явная запись frontend/dist"


# --- Docker-часть ------------------------------------------------------------------------


def docker(
    *args: str, timeout: float = 120, check: bool = True, stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    res = subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        input=stdin,
    )
    if check and res.returncode != 0:
        raise AssertionError(
            f"docker {' '.join(args[:3])} -> rc={res.returncode}\n{res.stdout[-2000:]}\n"
            f"{res.stderr[-2000:]}"
        )
    return res


def _docker_available() -> bool:
    try:
        return (
            subprocess.run(
                ["docker", "info"], capture_output=True, check=False, timeout=30
            ).returncode
            == 0
        )
    except (OSError, subprocess.TimeoutExpired):
        return False


needs_docker = pytest.mark.skipif(not _docker_available(), reason="Docker недоступен")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Web:
    def __init__(self, name: str, http_port: int, https_port: int) -> None:
        self.name, self.http_port, self.https_port = name, http_port, https_port

    def request(
        self,
        path: str = "/",
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        tls: bool = True,
    ) -> tuple[int, dict[str, str], bytes]:
        if tls:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            conn: http.client.HTTPConnection = http.client.HTTPSConnection(
                "127.0.0.1", self.https_port, context=ctx, timeout=30
            )
        else:
            conn = http.client.HTTPConnection("127.0.0.1", self.http_port, timeout=30)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            resp = conn.getresponse()
            data = resp.read()
            return resp.status, {k.lower(): v for k, v in resp.getheaders()}, data
        finally:
            conn.close()

    def exec(self, *cmd: str, stdin: str | None = None, check: bool = True) -> str:
        args = ["exec"] + (["-i"] if stdin is not None else []) + [self.name, *cmd]
        return docker(*args, check=check, stdin=stdin).stdout

    def cert_info(self) -> str:
        """Серверный сертификат, как его видит клиент: subject/issuer/SAN/fingerprint."""
        return self.exec(
            "sh",
            "-c",
            "openssl s_client -connect 127.0.0.1:443 -servername x </dev/null 2>/dev/null "
            "| openssl x509 -noout -subject -issuer -ext subjectAltName -fingerprint -sha256",
        )

    def fingerprint(self) -> str:
        m = re.search(r"sha256 Fingerprint=([0-9A-F:]+)", self.cert_info(), re.I)
        assert m, self.cert_info()
        return m.group(1)


def logs(name: str) -> str:
    res = docker("logs", name, check=False)
    return res.stdout + res.stderr


def run_web(
    name: str,
    *,
    network: str | None = NETWORK,
    env: dict[str, str] | None = None,
    volumes: list[str] | None = None,
) -> Web:
    http_port, https_port = free_port(), free_port()
    docker("rm", "-f", "-v", name, check=False)
    args = ["run", "-d", "--name", name, "-p", f"127.0.0.1:{http_port}:80"]
    args += ["-p", f"127.0.0.1:{https_port}:443"]
    if network:
        args += ["--network", network]
    environ = {"HTTPS_PORT": str(https_port), "TLS_SERVER_NAME": SERVER_NAME}
    environ.update(env or {})
    for k, v in environ.items():
        if v is not None:
            args += ["-e", f"{k}={v}"]
    for vol in volumes or []:
        args += ["-v", vol]
    docker(*args, IMAGE)
    web = Web(name, http_port, https_port)
    wait_ready(web)
    return web


def wait_ready(web: Web, timeout: float = 40) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = docker("inspect", "-f", "{{.State.Running}}", web.name, check=False).stdout.strip()
        if state != "true":
            raise AssertionError(f"{web.name} остановился:\n{logs(web.name)[-3000:]}")
        try:
            status, _, _ = web.request("/")
            if status:
                return
        except (OSError, http.client.HTTPException, ssl.SSLError):
            pass
        time.sleep(0.5)
    raise AssertionError(
        f"{web.name} не ответил по HTTPS за {timeout:.0f} с\n{logs(web.name)[-3000:]}"
    )


STUB_CONF = r"""
pid /tmp/stub.pid;
events {}
http {
  client_max_body_size 20m;
  access_log off;
  server {
    listen 8000;
    location / {
      default_type text/plain;
      set $h "host=$http_host;proto=$http_x_forwarded_proto";
      return 200 "$h;uri=$request_uri;method=$request_method";
    }
  }
}
"""


def _cleanup() -> None:
    for c in (WEB, WEB2, WEB_OP, WEB_NOAPI, WEB_NONAME, STUB):
        docker("rm", "-f", "-v", c, check=False)
    docker("volume", "rm", "-f", VOL, check=False)
    docker("network", "rm", NETWORK, check=False)


@pytest.fixture(scope="module")
def image() -> Iterator[str]:
    if not _docker_available():
        pytest.skip("Docker недоступен")
    for required in ("Dockerfile", "default.conf.template", "10-gostracker-tls.sh"):
        assert (WEB_DIR / required).is_file(), f"нет deploy/web/{required}"
    _cleanup()
    res = docker(
        "build", "-f", str(WEB_DIR / "Dockerfile"), "-t", IMAGE, str(REPO_ROOT),
        timeout=1500, check=False,
    )  # fmt: skip
    assert res.returncode == 0, f"docker build упал:\n{(res.stdout + res.stderr)[-3000:]}"
    yield IMAGE
    _cleanup()
    docker("rmi", "-f", IMAGE, check=False)


@pytest.fixture(scope="module")
def web(image: str) -> Iterator[Web]:
    """Основной контейнер + заглушка api в общей сети + том для сгенерированного сертификата."""
    docker("network", "create", NETWORK)
    docker("volume", "create", VOL)
    docker(
        "run", "-d", "--name", STUB, "--network", NETWORK, "--network-alias", "api",
        "-e", f"CONF={STUB_CONF}", "--entrypoint", "sh", image,
        "-c", 'printf "%s" "$CONF" > /tmp/s.conf && exec nginx -c /tmp/s.conf -g "daemon off;"',
    )  # fmt: skip
    yield run_web(WEB, volumes=[f"{VOL}:/var/lib/gostracker/tls"])


# --- Docker: сборка и образ --------------------------------------------------------------


@needs_docker
def test_fr63_image_builds(image: str) -> None:
    out = docker("image", "inspect", "-f", "{{.Id}}", image).stdout.strip()
    assert out.startswith("sha256:")


@needs_docker
def test_fr63_image_has_no_private_keys(image: str) -> None:
    out = docker(
        "run", "--rm", "--entrypoint", "sh", image, "-c",
        "grep -rl 'PRIVATE KEY' /etc/nginx /etc/gostracker /var/lib/gostracker "
        "/usr/share/nginx /docker-entrypoint.d 2>/dev/null; "
        "ls /etc/gostracker/tls /var/lib/gostracker/tls 2>/dev/null; true",
    ).stdout  # fmt: skip
    assert out.strip() == "", f"в образе есть ключи/сертификаты:\n{out}"


@needs_docker
def test_fr63_image_contains_spa_build(image: str) -> None:
    out = docker(
        "run", "--rm", "--entrypoint", "sh", image, "-c",
        "test -f /usr/share/nginx/html/index.html && ls /usr/share/nginx/html/assets | head -1",
    ).stdout  # fmt: skip
    assert out.strip(), "нет /usr/share/nginx/html/assets (сборка фронтенда)"


# --- Docker: сертификат ------------------------------------------------------------------


@needs_docker
def test_ac40_clean_install_serves_https_with_selfsigned_cert(web: Web) -> None:
    info = web.cert_info()
    subject = re.search(r"subject\s*=\s*(.+)", info)
    issuer = re.search(r"issuer\s*=\s*(.+)", info)
    assert subject and issuer
    assert SERVER_NAME in subject.group(1)
    assert subject.group(1).strip() == issuer.group(1).strip(), "сертификат не самоподписанный"
    for san in (f"DNS:{SERVER_NAME}", "DNS:localhost", "IP Address:127.0.0.1"):
        assert san in info, f"нет SAN {san}"
    status, _, body = web.request("/")
    assert status == 200 and b"<html" in body.lower()


@needs_docker
def test_ac40_selfsigned_validity_and_key_mode(web: Web) -> None:
    cert = "echo | openssl s_client -connect 127.0.0.1:443 2>/dev/null | openssl x509 -noout"
    ok = docker("exec", web.name, "sh", "-c", f"{cert} -checkend 69120000", check=False)
    assert ok.returncode == 0, "сертификат должен действовать >= 800 дней"
    over = docker("exec", web.name, "sh", "-c", f"{cert} -checkend 77760000", check=False)
    assert over.returncode == 1, "срок сертификата должен быть ~825 дней (не >= 900)"
    modes = web.exec("sh", "-c", "stat -c '%a' /var/lib/gostracker/tls/*.key").split()
    assert modes and all(m == "600" for m in modes), modes


@needs_docker
def test_ac40_cert_stable_across_restart_and_new_container(web: Web) -> None:
    before = web.fingerprint()
    docker("restart", web.name)
    wait_ready(web)
    assert web.fingerprint() == before, "сертификат перегенерирован при перезапуске"
    other = run_web(WEB2, volumes=[f"{VOL}:/var/lib/gostracker/tls"])
    try:
        assert other.fingerprint() == before, "новый контейнер с тем же томом сменил сертификат"
    finally:
        docker("rm", "-f", "-v", WEB2, check=False)


@needs_docker
def test_ac40_operator_certificate_is_used(image: str, tmp_path: Path) -> None:
    gen = docker(
        "run", "--rm", "--entrypoint", "sh", image, "-c",
        "openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 30 "
        "-subj /CN=operator-cert.test -keyout /tmp/k -out /tmp/c 2>/dev/null "
        "&& cat /tmp/c && echo ---KEY--- && cat /tmp/k",
    ).stdout  # fmt: skip
    crt, key = gen.split("---KEY---")
    d = tmp_path / "tls"
    d.mkdir()
    (d / "tls.crt").write_text(crt.strip() + "\n")
    (d / "tls.key").write_text(key.strip() + "\n")
    (d / "tls.key").chmod(0o600)
    d.chmod(0o755)
    (d / "tls.crt").chmod(0o644)
    op = run_web(WEB_OP, network=None, volumes=[f"{d}:/etc/gostracker/tls:ro"])
    try:
        assert "operator-cert.test" in op.cert_info()
        assert op.request("/")[0] == 200
    finally:
        docker("rm", "-f", "-v", WEB_OP, check=False)


@needs_docker
def test_ac40_starts_without_tls_server_name(image: str) -> None:
    c = run_web(WEB_NONAME, network=None, env={"TLS_SERVER_NAME": ""})
    try:
        assert c.request("/")[0] == 200
        assert "DNS:localhost" in c.cert_info()
    finally:
        docker("rm", "-f", "-v", WEB_NONAME, check=False)


# --- Docker: TLS-политика ----------------------------------------------------------------


def _s_client(web: Web, flag: str) -> subprocess.CompletedProcess[str]:
    return docker(
        "exec", "-i", web.name, "sh", "-c",
        f"openssl s_client -connect 127.0.0.1:443 {flag} -cipher 'ALL:@SECLEVEL=0' 2>&1",
        check=False, stdin="",
    )  # fmt: skip


@needs_docker
def test_ac40_tls12_accepted(web: Web) -> None:
    res = _s_client(web, "-tls1_2")
    assert res.returncode == 0, res.stdout[-1500:]
    assert re.search(r"Protocol\s*:\s*TLSv1\.2", res.stdout)


@needs_docker
def test_ac40_tls13_accepted(web: Web) -> None:
    res = _s_client(web, "-tls1_3")
    assert res.returncode == 0, res.stdout[-1500:]
    assert re.search(r"Protocol\s*:\s*TLSv1\.3", res.stdout)


@needs_docker
def test_ac40_tls11_rejected(web: Web) -> None:
    res = _s_client(web, "-tls1_1")
    out = res.stdout
    assert "no protocols available" not in out and "Unknown option" not in out, (
        f"клиент не умеет TLS 1.1, проверка бессмысленна:\n{out[-800:]}"
    )
    refused = (
        "alert protocol version" in out
        or re.search(r"Cipher is \(NONE\)", out)
        or re.search(r"Cipher\s*:\s*0000", out)
        or "no peer certificate" in out
    )
    assert refused, f"нет признаков отказа в TLS 1.1:\n{out[-800:]}"
    assert not re.search(r"Cipher is (?!\(NONE\))\S+", out), (
        f"рукопожатие состоялось:\n{out[-800:]}"
    )
    assert not re.search(r"Verification\b", out) or "no peer certificate" in out, (
        f"рукопожатие состоялось:\n{out[-800:]}"
    )


@needs_docker
def test_fr63_nginx_t_has_ssl_protocols(web: Web) -> None:
    dump = web.exec("nginx", "-T")
    assert re.search(r"ssl_protocols\s+TLSv1\.2\s+TLSv1\.3\s*;", dump)
    assert "client_max_body_size 12m" in dump
    assert "${HTTPS_PORT}" not in dump, "envsubst не применён к шаблону"


# --- Docker: http -> https ---------------------------------------------------------------


@needs_docker
def test_ac40_http_redirects_308_without_app_data(web: Web) -> None:
    status, headers, body = web.request(
        "/projects/42?q=1", tls=False, headers={"Host": "tracker.example:8080"}
    )
    assert status == 308
    assert headers["location"] == f"https://tracker.example:{web.https_port}/projects/42?q=1"
    assert b"<div id" not in body and b"<script" not in body.lower()
    assert len(body) < 2000


@needs_docker
def test_ac40_http_api_and_post_not_proxied(web: Web) -> None:
    for method, path in (("GET", "/api/v1/health"), ("POST", "/api/v1/auth/login")):
        status, headers, body = web.request(
            path, method=method, tls=False, body=b"{}" if method == "POST" else None,
            headers={"Host": "tracker.example"},
        )  # fmt: skip
        assert status == 308, (method, status)
        assert headers["location"].startswith("https://tracker.example:")
        assert b"proto=" not in body, "запрос ушёл в api по http"


# --- Docker: прокси ----------------------------------------------------------------------


def _stub_fields(body: bytes) -> dict[str, str]:
    return dict(p.split("=", 1) for p in body.decode().split(";"))


@needs_docker
def test_fr63_proxy_keeps_client_host_with_port(web: Web) -> None:
    status, _, body = web.request(
        "/api/v1/health?x=1", headers={"Host": f"tracker.example:{web.https_port}"}
    )
    assert status == 200, body[:300]
    f = _stub_fields(body)
    assert f["host"] == f"tracker.example:{web.https_port}", (
        "Host должен быть $http_host (с портом)"
    )
    assert f["uri"] == "/api/v1/health?x=1"


@needs_docker
def test_fr63_proxy_overwrites_forwarded_proto(web: Web) -> None:
    for spoof in ("http", "https, http", "javascript"):
        status, _, body = web.request(
            "/api/v1/health", headers={"X-Forwarded-Proto": spoof, "Host": "tracker.example"}
        )
        assert status == 200
        assert _stub_fields(body)["proto"] == "https", f"клиентский X-Forwarded-Proto {spoof!r}"


@needs_docker
def test_fr63_proxy_passes_post_methods(web: Web) -> None:
    status, _, body = web.request("/api/v1/auth/login", method="POST", body=b"{}")
    assert status == 200 and _stub_fields(body)["method"] == "POST"


@needs_docker
def test_nfr4_body_limit_12m(web: Web) -> None:
    ok, _, _ = web.request(
        "/api/v1/attachments", method="POST", body=b"x" * (11 * 1024 * 1024),
        headers={"Content-Type": "application/octet-stream"},
    )  # fmt: skip
    assert ok == 200, "11 МиБ должны проходить (вложения до 10 МБ)"


@needs_docker
def test_nfr4_413_json_error_response(web: Web) -> None:
    status, headers, body = web.request(
        "/api/v1/attachments", method="POST", body=b"x" * (13 * 1024 * 1024),
        headers={"Content-Type": "application/octet-stream"},
    )  # fmt: skip
    assert status == 413
    assert headers["content-type"].split(";")[0] == "application/json"
    data = json.loads(body)
    assert set(data) == {"detail", "code"}
    assert isinstance(data["detail"], str) and data["detail"]
    assert isinstance(data["code"], str) and data["code"]


# --- Docker: статика SPA и заголовки -----------------------------------------------------


@needs_docker
def test_fr63_spa_index_and_history_fallback(web: Web) -> None:
    s1, h1, index = web.request("/")
    assert s1 == 200 and h1["content-type"].startswith("text/html")
    assert b'id="root"' in index or b"<script" in index
    for path in ("/projects/abc/board", "/admin/users", "/login"):
        s, h, body = web.request(path)
        assert s == 200, path
        assert body == index, f"{path}: history fallback должен отдавать index.html"


@needs_docker
def test_fr63_spa_assets_served_not_fallback(web: Web) -> None:
    _, _, index = web.request("/")
    m = re.search(rb'(?:src|href)="(/assets/[^"]+\.js)"', index)
    assert m, "в index.html нет ссылки на /assets/*.js"
    status, headers, body = web.request(m.group(1).decode())
    assert status == 200
    assert body != index and b"<!doctype html" not in body[:100].lower()
    assert "javascript" in headers["content-type"]


@needs_docker
def test_fr63_api_paths_never_return_index(web: Web) -> None:
    _, _, index = web.request("/")
    status, _, body = web.request("/api/v1/unknown/path")
    assert body != index
    assert b"<!doctype" not in body.lower()
    assert _stub_fields(body)["uri"] == "/api/v1/unknown/path"


@needs_docker
def test_fr63_security_headers(web: Web) -> None:
    for path in ("/", "/projects/1"):
        _, h, _ = web.request(path)
        assert h["x-content-type-options"] == "nosniff"
        assert h["x-frame-options"].upper() == "DENY"
        assert h["referrer-policy"] == "same-origin"
        assert h["content-security-policy"] == CSP
        assert "strict-transport-security" not in h


# --- Docker: ленивое разрешение api, пользователь ----------------------------------------


@needs_docker
def test_fr63_starts_without_api_and_returns_gateway_error(image: str) -> None:
    c = run_web(WEB_NOAPI, network=None)  # сети с именем api нет, разрешение невозможно
    try:
        assert c.request("/")[0] == 200, "статика должна работать без api"
        status, h, body = c.request("/api/v1/health")
        assert status in (502, 503, 504), status
        assert b"<!doctype" not in body.lower()
        assert h.get("x-content-type-options") == "nosniff", "заголовки и на ошибках (always)"
        assert c.request("/", tls=False)[0] == 308
        assert "host not found" not in logs(c.name).split("[emerg]")[0]
    finally:
        docker("rm", "-f", "-v", WEB_NOAPI, check=False)


@needs_docker
def test_nfr4_workers_not_root(web: Web) -> None:
    ps = web.exec("sh", "-c", "ps -o user,args")
    workers = [ln.split()[0] for ln in ps.splitlines() if "nginx: worker process" in ln]
    assert workers, ps
    assert all(u != "root" for u in workers), f"worker'ы nginx от root: {workers}"
