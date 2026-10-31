"""T27: переносы из ревью T26 в образ web (plan §4.12, «Решения после ревью T26» (в)).

- (7) ``10-gostracker-tls.sh`` под flock удаляет остатки ``.tls.key.XXXXXX`` / ``.tls.crt.XXXXXX``
  (шесть символов, как у ``mktemp``) в томе сгенерированной пары; файлы оператора, посторонние
  имена и ``tls.crt``/``tls.key`` не трогаются;
- (8) HEALTHCHECK web не пишется в access-лог nginx: интерфейс - ``location = /healthz`` с
  ``access_log off`` и ответом 200 без проксирования и без SPA; HEALTHCHECK Dockerfile
  обращается к ``/healthz``.

Docker-часть собирает образ ``gostracker-web:t27`` и запускает контейнеры ``gt-t27-*``; без
Docker пропускается. Стек пользователя не затрагивается.
"""

from __future__ import annotations

import http.client
import re
import socket
import ssl
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

pytestmark = pytest.mark.infra_static

REPO_ROOT = Path(__file__).resolve().parents[3]
WEB_DIR = REPO_ROOT / "deploy" / "web"
IMAGE = "gostracker-web:t27"
VOL = "gt-t27-tls"
CONTAINER = "gt-t27-web"


def _read(name: str) -> str:
    path = WEB_DIR / name
    assert path.is_file(), f"нет deploy/web/{name}"
    return path.read_text(encoding="utf-8")


def _strip_comments(text: str) -> str:
    return "\n".join(re.sub(r"(^|\s)#.*$", "", ln) for ln in text.splitlines())


# --- статика: nginx и HEALTHCHECK ----------------------------------------------------------


def _location_body(conf: str, header_regex: str) -> str:
    m = re.search(header_regex + r"\s*\{", conf)
    assert m, f"нет location {header_regex!r}"
    depth, i = 1, m.end()
    while i < len(conf) and depth:
        depth += {"{": 1, "}": -1}.get(conf[i], 0)
        i += 1
    return conf[m.end() : i - 1]


def test_t27_nginx_has_exact_healthz_location_without_access_log() -> None:
    conf = _strip_comments(_read("default.conf.template"))
    body = _location_body(conf, r"location\s*=\s*/healthz")
    assert re.search(r"access_log\s+off\s*;", body)
    assert re.search(r"return\s+200\b", body), "healthz отвечает 200 сам (не try_files/proxy_pass)"
    assert "proxy_pass" not in body and "try_files" not in body


def test_t27_healthz_is_declared_in_the_tls_server_block() -> None:
    conf = _strip_comments(_read("default.conf.template"))
    tls_server = conf[conf.index("listen 443") :]
    assert re.search(r"location\s*=\s*/healthz\s*\{", tls_server)


def test_t27_dockerfile_healthcheck_uses_healthz() -> None:
    text = _read("Dockerfile")
    m = re.search(r"^HEALTHCHECK\b.*?(?=^\S|\Z)", text, re.M | re.S)
    assert m, "нет HEALTHCHECK"
    block = m.group(0).replace("\\\n", " ")
    cmd = re.sub(r"(?m)^\s*#.*$", "", block.split("CMD", 1)[1])
    assert "/healthz" in cmd, cmd
    assert not re.search(r"https://127\.0\.0\.1:443/\s", cmd + " "), "проверка всё ещё на /"


# --- R7-T16: access-лог web без строки запроса (007/AC-38, FR-32; plan PD-11 (5)) -----------

GT_ACCESS_FORMAT = (
    '$remote_addr - - [$time_local] "$request_method $uri $server_protocol" '
    '$status $body_bytes_sent "$http_user_agent"'
)
# переменные nginx, которые несут строку запроса (ключ в ``?…``) или заголовки с секретами;
# ``$remote_user`` nginx берёт из ``Authorization: Basic`` (``curl -u gtk_…:``)
FORBIDDEN_LOG_VARS = re.compile(
    r"\$(?:request|args|query_string|request_uri|is_args|arg_\w+|request_body|"
    r"http_authorization|http_cookie|http_referer|cookie_\w+|remote_user)(?!\w)"
)


def _server_blocks(conf: str) -> list[str]:
    """Тела всех блоков ``server { … }`` верхнего уровня шаблона."""
    blocks: list[str] = []
    for m in re.finditer(r"(?m)^\s*server\s*\{", conf):
        depth, i = 1, m.end()
        while i < len(conf) and depth:
            depth += {"{": 1, "}": -1}.get(conf[i], 0)
            i += 1
        blocks.append(conf[m.end() : i - 1])
    return blocks


def _top_level(body: str) -> str:
    """Директивы самого блока без вложенных ``location``/``if``."""
    out, depth = [], 0
    for ch in body:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif depth == 0:
            out.append(ch)
    return "".join(out)


def _tls_server(conf: str) -> str:
    found = [b for b in _server_blocks(conf) if re.search(r"\blisten\s+443\b", _top_level(b))]
    assert len(found) == 1, f"сервер 443 не найден однозначно: {len(found)}"
    return found[0]


def _log_format(conf: str, name: str) -> str | None:
    m = re.search(rf"\blog_format\s+{name}\s+(.*?);", conf, re.S)
    if m is None:
        return None
    raw = m.group(1)
    if raw.lstrip().startswith("escape="):
        raw = raw.lstrip().split(None, 1)[1]
    parts = re.findall(r"'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\"", raw)
    if parts:
        return "".join(a or b for a, b in parts)
    return " ".join(raw.split())


def test_007_ac38_web_access_log_format_has_no_query_string() -> None:
    """Сервер 443 пишет access-лог в формате ``gt_access`` без ``$request``, ``$args``,
    ``$query_string``, ``$request_uri``: ключ в ``?…`` не попадает в access-лог web
    (FR-32, plan PD-11 (5)); ``location = /healthz`` по-прежнему без access-лога."""
    conf = _strip_comments(_read("default.conf.template"))

    fmt = _log_format(conf, "gt_access")
    assert fmt is not None, "нет log_format gt_access"
    assert not FORBIDDEN_LOG_VARS.search(fmt), f"формат пишет строку запроса: {fmt}"
    assert " ".join(fmt.split()) == " ".join(GT_ACCESS_FORMAT.split()), fmt

    server = _tls_server(conf)
    server_level = re.findall(r"\baccess_log\s+([^;]*);", _top_level(server))
    assert any(re.fullmatch(r"\S+\s+gt_access(?:\s+.*)?", d.strip()) for d in server_level), (
        f"у сервера 443 нет access_log … gt_access: {server_level}"
    )
    for directive in re.findall(r"\baccess_log\s+([^;]*);", server):
        d = directive.strip()
        assert d == "off" or re.fullmatch(r"\S+\s+gt_access(?:\s+.*)?", d), (
            f"access_log сервера 443 без формата gt_access: {d}"
        )
    body = _location_body(conf, r"location\s*=\s*/healthz")
    assert re.search(r"access_log\s+off\s*;", body)


def test_007_ac38_web_does_not_log_or_strip_authorization_header() -> None:
    """Заметка ревью R7-T12 (статическая часть): прокси ``/api/`` не переписывает и не убирает
    ``Authorization`` и пересылает заголовки; ни один ``log_format`` не пишет его значение."""
    conf = _strip_comments(_read("default.conf.template"))
    api = _location_body(conf, r"location\s+/api/")
    assert not re.search(r"proxy_set_header\s+Authorization\b", api, re.I)
    assert not re.search(r"proxy_pass_request_headers\s+off", api)
    assert not re.search(r"\$http_authorization\b", conf)


# --- Docker-часть --------------------------------------------------------------------------


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


def _cleanup() -> None:
    docker("rm", "-f", "-v", CONTAINER, check=False)
    docker("volume", "rm", "-f", VOL, check=False)


@pytest.fixture(scope="module")
def image() -> Iterator[str]:
    if not _docker_available():
        pytest.skip("Docker недоступен")
    _cleanup()
    res = docker(
        "build", "-f", str(WEB_DIR / "Dockerfile"), "-t", IMAGE, str(REPO_ROOT),
        timeout=1500, check=False,
    )  # fmt: skip
    assert res.returncode == 0, f"docker build упал:\n{(res.stdout + res.stderr)[-3000:]}"
    yield IMAGE
    _cleanup()
    docker("rmi", "-f", IMAGE, check=False)


def _run_script(image: str, volume: str, shell_prefix: str) -> str:
    """Выполняет ``shell_prefix``, затем скрипт выбора сертификата, затем листинг тома."""
    script = (
        f"{shell_prefix}; /docker-entrypoint.d/10-gostracker-tls.sh >/dev/null 2>&1; "
        "rc=$?; echo rc=$rc; ls -A /var/lib/gostracker/tls"
    )
    res = docker(
        "run", "--rm", "-e", "HTTPS_PORT=443", "-e", "TLS_SERVER_NAME=tracker.test",
        "-v", f"{volume}:/var/lib/gostracker/tls", "--entrypoint", "sh", image, "-c", script,
    )  # fmt: skip
    return res.stdout


LEFTOVERS = ".tls.key.AbC123 .tls.crt.Zz9_x1 .tls.key.000000"
KEEP = ".tls.key.backup-old .tls.key.1234567 .tls.crt.12345 notes.txt tls.key.bak .tls.keyAbC123"


def _files(listing: str) -> set[str]:
    lines = listing.splitlines()
    assert lines[0] == "rc=0", listing
    return set(lines[1:])


@needs_docker
def test_t27_tls_script_removes_leftover_temp_files_when_generating(image: str) -> None:
    docker("volume", "create", VOL)
    prep = (
        f"cd /var/lib/gostracker/tls && touch {LEFTOVERS} {KEEP} && echo secret > .tls.key.QqQqQq"
    )
    names = _files(_run_script(image, VOL, prep))
    for stale in LEFTOVERS.split() + [".tls.key.QqQqQq"]:
        assert stale not in names, f"остаток {stale} не удалён"
    for keep in KEEP.split():
        assert keep in names, f"тронут посторонний файл {keep}"
    assert {"tls.crt", "tls.key"} <= names
    assert not [n for n in names if re.fullmatch(r"\.tls\.(key|crt)\.[A-Za-z0-9]{6}", n)]


@needs_docker
def test_t27_tls_script_removes_leftovers_and_keeps_valid_pair_untouched(image: str) -> None:
    docker("volume", "rm", "-f", VOL, check=False)
    docker("volume", "create", VOL)
    first = _run_script(image, VOL, "true")
    assert {"tls.crt", "tls.key"} <= _files(first)
    sums = "cd /var/lib/gostracker/tls && sha256sum tls.crt tls.key && stat -c '%a' tls.key"

    def snapshot() -> str:
        return docker(
            "run", "--rm", "-v", f"{VOL}:/var/lib/gostracker/tls", "--entrypoint", "sh",
            image, "-c", sums,
        ).stdout  # fmt: skip

    before = snapshot()
    prep = f"cd /var/lib/gostracker/tls && touch {LEFTOVERS} {KEEP}"
    names = _files(_run_script(image, VOL, prep))
    for stale in LEFTOVERS.split():
        assert stale not in names, f"остаток {stale} не удалён (пара цела, генерации нет)"
    for keep in KEEP.split():
        assert keep in names
    assert snapshot() == before, "валидная пара tls.crt/tls.key изменена"


@needs_docker
def test_t27_tls_script_directory_named_like_temp_file_does_not_break_start(image: str) -> None:
    """Каталоги ``.tls.key.*``/``.tls.crt.*`` в томе: rc=0, каталоги целы, пара валидна."""
    docker("volume", "rm", "-f", VOL, check=False)
    docker("volume", "create", VOL)
    d = "/var/lib/gostracker/tls"
    script = (
        f"cd {d} && mkdir .tls.key.DirAb1 .tls.crt.DirCd2 && echo keep > .tls.key.DirAb1/inner "
        f"&& echo secret > .tls.key.FilEf3 && touch .tls.crt.FilGh4; "
        "/docker-entrypoint.d/10-gostracker-tls.sh >/tmp/out 2>&1; echo rc=$?; "
        f"cd {d}; ls -A; "
        "[ -f .tls.key.DirAb1/inner ] && echo inner_ok; [ -d .tls.crt.DirCd2 ] && echo dir_ok; "
        '[ -n "$(openssl x509 -in tls.crt -noout -pubkey)" ] && '
        '[ "$(openssl x509 -in tls.crt -noout -pubkey)" = "$(openssl pkey -in tls.key -pubout)" ] '
        "&& openssl x509 -in tls.crt -noout -checkend 0 >/dev/null && echo pair_ok; "
        "tail -n 5 /tmp/out"
    )
    res = docker(
        "run", "--rm", "-e", "HTTPS_PORT=443", "-e", "TLS_SERVER_NAME=tracker.test",
        "-v", f"{VOL}:{d}", "--entrypoint", "sh", image, "-c", script,
    )  # fmt: skip
    lines = res.stdout.splitlines()
    assert "rc=0" in lines, res.stdout
    assert "inner_ok" in lines and "dir_ok" in lines, f"каталог тронут:\n{res.stdout}"
    assert "pair_ok" in lines, f"пара не валидна:\n{res.stdout}"
    assert ".tls.key.FilEf3" not in lines and ".tls.crt.FilGh4" not in lines, (
        f"файлы-остатки не удалены:\n{res.stdout}"
    )
    assert {"tls.crt", "tls.key"} <= set(lines)


@needs_docker
def test_t27_tls_script_operator_cert_branch_keeps_operator_files(
    image: str, tmp_path: Path
) -> None:
    """Сертификат оператора: скрипт завершается ранее и не трогает каталог оператора."""
    docker("volume", "rm", "-f", VOL, check=False)
    docker("volume", "create", VOL)
    script = (
        "mkdir -p /etc/gostracker/tls && cd /etc/gostracker/tls && "
        "openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 2 "
        "-subj /CN=op -keyout tls.key -out tls.crt 2>/dev/null && "
        "touch .tls.key.AbC123 operator-note.txt && "
        "/docker-entrypoint.d/10-gostracker-tls.sh >/dev/null && ls -A /etc/gostracker/tls"
    )
    res = docker(
        "run", "--rm", "-e", "HTTPS_PORT=443", "-v", f"{VOL}:/var/lib/gostracker/tls",
        "--entrypoint", "sh", image, "-c", script,
    )  # fmt: skip
    assert set(res.stdout.split()) == {"tls.crt", "tls.key", ".tls.key.AbC123", "operator-note.txt"}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _get(port: int, path: str) -> tuple[int, bytes]:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    conn = http.client.HTTPSConnection("127.0.0.1", port, context=ctx, timeout=15)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


@needs_docker
def test_t27_healthz_not_in_access_log_ordinary_request_is(image: str) -> None:
    _cleanup()
    port = _free_port()
    # без сети с api: /healthz не может проксироваться (на /api/ был бы 502)
    docker(
        "run", "-d", "--name", CONTAINER, "-p", f"127.0.0.1:{port}:443",
        "-e", "HTTPS_PORT=443", "-e", "TLS_SERVER_NAME=tracker.test", image,
    )  # fmt: skip
    deadline = time.monotonic() + 40
    while True:
        try:
            status, _ = _get(port, "/")
            if status:
                break
        except (OSError, http.client.HTTPException, ssl.SSLError):
            pass
        assert time.monotonic() < deadline, "web не поднялся"
        time.sleep(0.5)

    status, body = _get(port, "/healthz")
    assert status == 200
    assert b"<html" not in body.lower(), "/healthz отдаёт SPA"
    assert _get(port, "/api/v1/health")[0] in (502, 503, 504), "контроль: api недоступен"
    assert _get(port, "/marker-ordinary-request")[0] == 200  # SPA fallback

    time.sleep(1)  # запись access-лога идёт в stdout контейнера
    res = docker("logs", CONTAINER, check=False)
    log = res.stdout + res.stderr
    assert "GET /marker-ordinary-request" in log, "обычный запрос не попал в access-лог"
    assert "/healthz" not in log, "healthcheck пишется в access-лог"
