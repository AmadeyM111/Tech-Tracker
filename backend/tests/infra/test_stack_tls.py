"""T26: TLS, прокси и поведение образа web в инфраструктурном стеке (AC-40, FR-63, FR-51,
AC-95, AC-105, T25 п.1, 2, 5, 6, 7).

Маркер ``infra_stack``; без ``GT_INFRA_STACK=1`` пропускаются (см. stack_support.py).

Две части:
1. запросы к поднятому стеку (проект gostracker-infratest, порты HTTP_PORT/HTTPS_PORT);
2. поведение скрипта ``10-gostracker-tls.sh`` на ОБРАЗЕ web из стека: отдельные контейнеры
   ``gt-t26-*`` без публикации портов, без сети с api и с собственными томами ``gt-t26-*``.
   Всё создаваемое удаляется в finalizer'ах. Ни стек пользователя, ни тома проекта не затрагиваются.

Контракт, который проверяют тесты части 2 (plan §4.12, tasks T26 «Перенесено из ревью T25»):
- сгенерированная пара лежит в ``/var/lib/gostracker/tls/tls.{crt,key}``, сертификат оператора -
  ``/etc/gostracker/tls/tls.{crt,key}``;
- ошибка конфигурации = контейнер завершается с кодом != 0, причина названа в логе по имени
  переменной (``TLS_SERVER_NAME``/``HTTPS_PORT``), значение выполняться не должно;
- сгенерированная пара при несовпадении ключа и сертификата или истечении срока перегенерируется;
  сертификат оператора не перегенерируется и не подменяется;
- если оператор положил только один из файлов - в логе предупреждение (слова «предупрежд» или
  «warn» и имя недостающего файла), сертификат при этом генерируется.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import pytest

from tests.infra import stack_support as ss

pytestmark = ss.stack_marks()

CSP = (
    "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
    "frame-ancestors 'none'"
)
GEN = "/var/lib/gostracker/tls"
OPR = "/etc/gostracker/tls"
PAIR_CHECK = (
    'a=$(openssl x509 -in {d}/tls.crt -noout -pubkey | openssl sha256); '
    'b=$(openssl pkey -in {d}/tls.key -pubout | openssl sha256); '
    '[ "$a" = "$b" ] && echo MATCH || echo MISMATCH'
)  # fmt: skip
GEN_CERT = (
    "openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 30 "
    "-subj /CN=op.test -keyout {d}/tls.key -out {d}/tls.crt 2>/dev/null"
)


# =============================================================================================
# Часть 1. Поднятый стек
# =============================================================================================


def test_ac40_http_redirects_308_to_https_port_without_app_data() -> None:
    """AC-40, FR-63: GET по http -> 308 на https://host:HTTPS_PORT с тем же путём и query."""
    r = ss.request("/projects/42?q=1", tls=False)
    assert r.status == 308
    assert r.header("location") == f"https://{ss.HOST}:{ss.HTTPS_PORT}/projects/42?q=1"
    assert b"<html" not in r.body.lower() or b"308" in r.body
    assert b"root" not in r.body.lower(), "в теле редиректа нет данных приложения"


def test_ac40_http_post_and_api_are_redirected_not_proxied() -> None:
    """AC-40: по http нет ни проксирования, ни ответов приложения (в том числе POST)."""
    for method, path in (("POST", "/api/v1/auth/login"), ("GET", "/api/v1/health")):
        r = ss.request(path, method=method, tls=False, body=b"{}" if method == "POST" else None)
        assert r.status == 308, (method, path)
        assert r.header("location") == f"https://{ss.HOST}:{ss.HTTPS_PORT}{path}"
        assert b'"status"' not in r.body and b'"code"' not in r.body


def test_ac40_tls11_rejected_tls12_and_tls13_accepted() -> None:
    """AC-40, FR-63: TLS 1.1 отклонён; 1.2 и 1.3 принимаются."""
    out11 = ss.s_client("-tls1_1", "-cipher", "'DEFAULT:@SECLEVEL=0'")
    assert "no protocols available" not in out11 and "unknown option" not in out11.lower(), (
        f"клиент не умеет TLS 1.1, проверка бессмысленна:\n{out11[-600:]}"
    )
    refused = (
        "alert protocol version" in out11
        or re.search(r"Cipher is \(NONE\)", out11)
        or re.search(r"Cipher\s*:\s*0000", out11)
        or "no peer certificate" in out11
    )
    assert refused, f"нет признаков отказа сервера в TLS 1.1:\n{out11[-600:]}"
    assert not re.search(r"Cipher is (?!\(NONE\))\S+", out11), out11[-600:]
    assert re.search(r"Protocol\s*:\s*TLSv1\.2", ss.s_client("-tls1_2"))
    assert re.search(r"Protocol\s*:\s*TLSv1\.3", ss.s_client("-tls1_3"))


def test_ac40_clean_install_serves_selfsigned_certificate_for_server_name() -> None:
    """AC-40: чистая установка без сертификата оператора -> HTTPS с самоподписанным
    сертификатом: issuer == subject, CN = TLS_SERVER_NAME, SAN включает localhost и 127.0.0.1."""
    name = os.environ.get("TLS_SERVER_NAME", "localhost")
    info = ss.sh_in(
        "web",
        "openssl s_client -connect 127.0.0.1:443 -servername x </dev/null 2>/dev/null "
        "| openssl x509 -noout -subject -issuer -ext subjectAltName",
    )
    subject = re.search(r"subject=\s*(.+)", info)
    issuer = re.search(r"issuer=\s*(.+)", info)
    assert subject and issuer
    assert subject.group(1).strip() == issuer.group(1).strip(), "сертификат не самоподписанный"
    assert re.search(rf"CN\s*=\s*{re.escape(name)}\b", subject.group(1))
    assert "DNS:localhost" in info and "IP Address:127.0.0.1" in info


def test_fr63_generated_key_is_0600_and_cert_survives_web_restart() -> None:
    """FR-63, T25: ключ в томе tls-generated 0600; перезапуск web не меняет сертификат."""
    mode = ss.sh_in("web", f"stat -c '%a' {GEN}/tls.key").strip()
    assert mode == "600"
    before = ss.s_client("-showcerts")
    fp1 = ss.sh_in("web", f"openssl x509 -in {GEN}/tls.crt -noout -fingerprint -sha256").strip()
    ss.restart("web")
    fp2 = ss.sh_in("web", f"openssl x509 -in {GEN}/tls.crt -noout -fingerprint -sha256").strip()
    assert fp1 == fp2
    assert ss.request("/").status == 200
    assert before, "s_client ничего не вернул"


def test_t25_spa_index_is_no_cache_and_assets_are_cacheable() -> None:
    """T25 п.6: index.html - Cache-Control: no-cache; хэшированные /assets/* кешируются."""
    r = ss.request("/")
    assert r.status == 200
    assert "no-cache" in (r.header("cache-control") or "").lower()
    assert b'<div id="root"' in r.body or b"<script" in r.body
    m = re.search(rb'(?:src|href)="(/assets/[^"]+\.js)"', r.body)
    assert m, "в index.html нет /assets/*.js"
    asset = ss.request(m.group(1).decode())
    assert asset.status == 200
    assert "max-age" in (asset.header("cache-control") or "").lower()


def test_t25_missing_asset_is_404_and_api_never_returns_index() -> None:
    """T25 п.6: отсутствующий /assets/* - 404, не index.html; /api и /api/... не отдают index."""
    index = ss.request("/").body
    missing = ss.request(f"/assets/{secrets.token_hex(6)}.js")
    assert missing.status == 404
    assert missing.body != index
    bare = ss.request("/api")
    assert bare.status == 404 and bare.body != index
    unknown = ss.request("/api/v1/definitely-unknown")
    assert unknown.status == 404
    assert unknown.body != index
    assert unknown.json()["code"] == "not_found", "ответ api (ErrorResponse), не страница nginx"


def test_t25_server_tokens_off_no_version_in_header_or_error_page() -> None:
    """T25 п.6: в Server нет версии nginx; страницы ошибок тоже."""
    for path in ("/", f"/assets/{secrets.token_hex(4)}.css"):
        r = ss.request(path)
        server = r.header("server") or ""
        assert not re.search(r"\d", server), f"версия в Server: {server!r}"
        assert not re.search(rb"nginx/\d", r.body)
    http_r = ss.request("/x", tls=False)
    assert not re.search(r"\d", http_r.header("server") or "")


def test_fr63_security_headers_on_stack() -> None:
    """plan §4.12: заголовки безопасности есть, HSTS нет."""
    for path in ("/", "/projects/1", "/api/v1/health"):
        r = ss.request(path)
        assert r.header("x-content-type-options") == "nosniff", path
        assert (r.header("x-frame-options") or "").upper() == "DENY", path
        assert r.header("referrer-policy") == "same-origin", path
        assert r.header("content-security-policy") == CSP, path
        assert r.header("strict-transport-security") is None, path


def test_t25_p7_oversize_body_gets_json_413_attachment_too_large_on_any_path() -> None:
    """T25 п.7: тело > 12 МБ -> 413 {detail, code: attachment_too_large} для любого пути."""
    big = b"x" * (13 * 1024 * 1024)
    for path in ("/api/v1/auth/login", "/api/v1/anything/else"):
        r = ss.request(path, method="POST", body=big, headers={"Content-Type": "text/plain"})
        assert r.status == 413, path
        assert "application/json" in (r.header("content-type") or "")
        assert r.json()["code"] == "attachment_too_large"


def test_ac95_runtime_log_driver_json_file_10m_x5_for_every_container() -> None:
    """AC-95, FR-51: фактическая конфигурация логов каждого контейнера стека (в т.ч. web)."""
    for service in ss.SERVICES:
        cfg = json.loads(ss.inspect(service, "{{json .HostConfig.LogConfig}}"))
        assert cfg["Type"] == "json-file", service
        opts = {k: str(v) for k, v in cfg["Config"].items()}
        assert opts.get("max-size") == "10m" and opts.get("max-file") == "5", (service, opts)


def test_ac105_api_container_has_secure_cookies_forced_on() -> None:
    """AC-105, FR-58: в окружении запущенного api COOKIE_SECURE=true, режима разработки нет."""
    env = dict(
        e.split("=", 1) for e in json.loads(ss.inspect("api", "{{json .Config.Env}}")) if "=" in e
    )
    assert env.get("COOKIE_SECURE") == "true"
    assert env.get("ENV", "production") == "production"
    assert env.get("EXPOSE_API_DOCS", "false").lower() in ("", "false", "0")
    for path in ("/api/openapi.json", "/api/docs", "/api/redoc"):
        r = ss.request(path)
        assert r.status == 404, f"{path}: {r.status}"
        assert b'<div id="root"' not in r.body and b"<!doctype html" not in r.body.lower()


# =============================================================================================
# Часть 2. Образ web из стека: скрипт 10-gostracker-tls.sh и валидация переменных
# =============================================================================================


@pytest.fixture(scope="module")
def image() -> str:
    return ss.inspect("web", "{{.Image}}")


@pytest.fixture
def vols() -> Iterator[list[str]]:
    created: list[str] = []
    yield created
    for name in created:
        ss.docker("volume", "rm", "-f", name, check=False)


def _vol(vols: list[str], tag: str) -> str:
    name = f"gt-t26-{tag}-{secrets.token_hex(3)}"
    ss.docker("volume", "create", name)
    vols.append(name)
    return name


def _vol_sh(image: str, script: str, *volumes: str) -> str:
    args = ["run", "--rm", "--entrypoint", "sh"]
    for v in volumes:
        args += ["-v", v]
    return ss.docker(*args, image, "-c", script).stdout


@dataclass
class Ran:
    name: str
    state: str  # running | exited
    code: int | None
    log: str


def _start(image: str, tag: str, env: dict[str, str], volumes: list[str]) -> str:
    name = f"gt-t26-{tag}-{secrets.token_hex(3)}"
    args = ["run", "-d", "--name", name]
    for k, v in env.items():
        args += ["-e", f"{k}={v}"]
    for v in volumes:
        args += ["-v", v]
    ss.docker(*args, image)
    return name


def _settle(name: str, timeout: float = 25, stay_running: float = 4) -> Ran:
    """Ждёт завершения контейнера до timeout; если жив - после stay_running с считается running."""
    deadline = time.monotonic() + timeout
    start = time.monotonic()
    state, code = "running", None
    while time.monotonic() < deadline:
        out = ss.docker(
            "inspect", "-f", "{{.State.Status}} {{.State.ExitCode}}", name, check=False
        ).stdout.split()
        state, code = out[0], int(out[1])
        if state == "exited":
            break
        if time.monotonic() - start >= stay_running and state == "running":
            break
        time.sleep(0.5)
    log = ss.docker("logs", name, check=False)
    return Ran(name, state, code if state == "exited" else None, log.stdout + log.stderr)


class _Cleanup:
    def __init__(self) -> None:
        self.names: list[str] = []

    def add(self, name: str) -> str:
        self.names.append(name)
        return name


@pytest.fixture
def containers() -> Iterator[_Cleanup]:
    c = _Cleanup()
    yield c
    for name in c.names:
        ss.docker("rm", "-f", "-v", name, check=False)


def _start_and_settle(
    image: str,
    containers: _Cleanup,
    tag: str,
    env: dict[str, str],
    volumes: list[str],
    **kw: float,
) -> Ran:
    name = containers.add(_start(image, tag, env, volumes))
    return _settle(name, **kw)


BASE_ENV = {"HTTPS_PORT": "443", "TLS_SERVER_NAME": "tracker.test"}


@pytest.mark.parametrize(
    "bad_name",
    [
        "a;b",
        "$(id)",
        "`id`",
        "a b",
        "a'b",
        'a"b',
        "-leading-dash",
        ".leading-dot",
        "a" * 65,
        "a/b",
        "a,IP:1.2.3.4",
    ],
)
def test_t25_tls_server_name_invalid_is_rejected_with_clear_error(
    image: str, vols: list[str], containers: _Cleanup, bad_name: str
) -> None:
    """T25 п.1/п.6: недопустимое TLS_SERVER_NAME (``;``, ``$(...)``, пробел, длина > 64 и т.д.)
    -> контейнер завершается с кодом != 0, в логе названа переменная."""
    vol = _vol(vols, "badname")
    env = {**BASE_ENV, "TLS_SERVER_NAME": bad_name}
    ran = _start_and_settle(image, containers, "badname", env, [f"{vol}:{GEN}"])
    assert ran.state == "exited", f"web стартовал с TLS_SERVER_NAME={bad_name!r}"
    assert ran.code != 0
    assert "TLS_SERVER_NAME" in ran.log


def test_t25_tls_server_name_command_substitution_is_not_executed(
    image: str, vols: list[str], containers: _Cleanup
) -> None:
    """T25 п.6: ``$(touch ...)`` в TLS_SERVER_NAME не выполняется."""
    vol = _vol(vols, "inject")
    marker = f"/tmp/pwned-{secrets.token_hex(3)}"
    env = {**BASE_ENV, "TLS_SERVER_NAME": f"$(touch {marker})"}
    ran = _start_and_settle(image, containers, "inject", env, [f"{vol}:{GEN}"])
    assert ran.state == "exited" and ran.code != 0
    res = ss.docker("cp", f"{ran.name}:{marker}", "-", check=False)
    assert res.returncode != 0, "команда из TLS_SERVER_NAME выполнена"


@pytest.mark.parametrize(
    "bad_port", ["abc", "0", "65536", "-1", "443;x", "44 3", "$(id)", "0443x", "99999999999"]
)
def test_t25_https_port_not_a_valid_number_is_rejected(
    image: str, vols: list[str], containers: _Cleanup, bad_port: str
) -> None:
    """T25 п.2: HTTPS_PORT не число 1..65535 -> понятная ошибка, код выхода != 0."""
    vol = _vol(vols, "badport")
    env = {**BASE_ENV, "HTTPS_PORT": bad_port}
    ran = _start_and_settle(image, containers, "badport", env, [f"{vol}:{GEN}"])
    assert ran.state == "exited", f"web стартовал с HTTPS_PORT={bad_port!r}"
    assert ran.code != 0
    assert "HTTPS_PORT" in ran.log


@pytest.mark.parametrize("port", ["1", "8443", "65535"])
def test_t25_https_port_boundaries_are_accepted_and_used_in_redirect(
    image: str, vols: list[str], containers: _Cleanup, port: str
) -> None:
    """T25 п.2, T12: допустимые порты принимаются и попадают в Location редиректа."""
    vol = _vol(vols, "okport")
    env = {**BASE_ENV, "HTTPS_PORT": port}
    ran = _start_and_settle(image, containers, "okport", env, [f"{vol}:{GEN}"])
    assert ran.state == "running", ran.log[-800:]
    out = ss.docker(
        "exec", ran.name, "sh", "-c",
        "printf 'GET /p?q=1 HTTP/1.0\\r\\nHost: 127.0.0.1\\r\\n\\r\\n' "
        "| nc -w 3 127.0.0.1 80 || true",
    ).stdout  # fmt: skip
    assert re.search(rf"Location:\s*https://127\.0\.0\.1:{port}/p\?q=1", out), out


def _start_pair(image: str, containers: _Cleanup, tag: str, mount: list[str]) -> list[str]:
    """Одновременно стартует два контейнера на одном томе (barrier-подобно, через потоки)."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_start, image, f"{tag}{i}", BASE_ENV, mount) for i in range(2)]
        return [containers.add(f.result()) for f in futures]


def test_t25_p1_two_web_containers_on_one_volume_never_desync_pair(
    image: str, vols: list[str], containers: _Cleanup
) -> None:
    """T25 п.1: гонка двух контейнеров web на одном томе tls-generated (одинаковый PID в обоих):
    оба стартуют либо один понятно падает; пара ключ/сертификат согласована, временных
    файлов не осталось. Три раунда на свежих томах."""
    for round_no in range(3):
        vol = _vol(vols, f"race{round_no}")
        mount = [f"{vol}:{GEN}"]
        names = _start_pair(image, containers, f"race{round_no}", mount)
        ran = [_settle(n, timeout=30, stay_running=5) for n in names]
        assert any(r.state == "running" for r in ran), [r.log[-500:] for r in ran]
        for r in ran:
            if r.state == "exited":
                assert r.code != 0 and r.log.strip(), "упал молча или с кодом 0"
        assert _vol_sh(image, PAIR_CHECK.format(d="/v"), f"{vol}:/v").strip() == "MATCH"
        left = sorted(_vol_sh(image, "ls -A /v", f"{vol}:/v").split())
        assert left == ["tls.crt", "tls.key"], f"лишние файлы в томе: {left}"
        for r in ran:
            ss.docker("rm", "-f", "-v", r.name, check=False)


def test_t25_p1_generated_pair_with_mismatched_key_and_cert_is_regenerated(
    image: str, vols: list[str], containers: _Cleanup
) -> None:
    """T25 п.1: в сгенерированном томе ключ не от сертификата -> перегенерация, web стартует."""
    vol = _vol(vols, "mismatch")
    setup = (
        f"{GEN_CERT.format(d='/v')} && mkdir -p /o && {GEN_CERT.format(d='/o')} "
        "&& cp /o/tls.crt /v/tls.crt && openssl x509 -in /v/tls.crt -noout -fingerprint -sha256"
    )
    broken_fp = _vol_sh(image, setup, f"{vol}:/v").strip().splitlines()[-1]
    assert _vol_sh(image, PAIR_CHECK.format(d="/v"), f"{vol}:/v").strip() == "MISMATCH"
    ran = _start_and_settle(image, containers, "mismatch", BASE_ENV, [f"{vol}:{GEN}"])
    assert ran.state == "running", f"web не поднялся на рассинхронизированной паре:\n{ran.log}"
    assert _vol_sh(image, PAIR_CHECK.format(d="/v"), f"{vol}:/v").strip() == "MATCH"
    new_fp = _vol_sh(
        image, "openssl x509 -in /v/tls.crt -noout -fingerprint -sha256", f"{vol}:/v"
    ).strip()
    assert new_fp != broken_fp
    assert re.search(r"гене|regener", ran.log, re.I), "перегенерация должна быть видна в логе"


def test_t25_p1_expired_generated_cert_is_regenerated(
    image: str, vols: list[str], containers: _Cleanup
) -> None:
    """T25 п.1: просроченный сгенерированный сертификат (-checkend 0) -> перегенерация."""
    vol = _vol(vols, "expired")
    res = ss.docker(
        "run", "--rm", "--entrypoint", "sh", "-v", f"{vol}:/v", image, "-c",
        "openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes "
        "-subj /CN=old.test -not_before 20200101000000Z -not_after 20200102000000Z "
        "-keyout /v/tls.key -out /v/tls.crt 2>&1",
        check=False,
    )  # fmt: skip
    if res.returncode != 0:
        pytest.skip(f"openssl образа не умеет -not_before/-not_after: {res.stdout[-200:]}")
    assert _vol_sh(image, PAIR_CHECK.format(d="/v"), f"{vol}:/v").strip() == "MATCH"
    ran = _start_and_settle(image, containers, "expired", BASE_ENV, [f"{vol}:{GEN}"])
    assert ran.state == "running", ran.log[-800:]
    still = _vol_sh(
        image, "openssl x509 -in /v/tls.crt -noout -checkend 0 && echo VALID", f"{vol}:/v"
    )
    assert "VALID" in still, "просроченный сертификат оставлен"
    assert _vol_sh(image, PAIR_CHECK.format(d="/v"), f"{vol}:/v").strip() == "MATCH"


def test_t25_p1_operator_pair_is_never_regenerated_or_replaced(
    image: str, vols: list[str], containers: _Cleanup
) -> None:
    """T25 п.1: сертификат оператора (даже просроченный) используется как есть; его файлы не
    меняются, сгенерированный не подкладывается."""
    op = _vol(vols, "operator")
    gen = _vol(vols, "opgen")
    res = ss.docker(
        "run", "--rm", "--entrypoint", "sh", "-v", f"{op}:/v", image, "-c",
        "openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes "
        "-subj /CN=operator.test -not_before 20200101000000Z -not_after 20200102000000Z "
        "-keyout /v/tls.key -out /v/tls.crt 2>&1 && sha256sum /v/tls.crt /v/tls.key",
        check=False,
    )  # fmt: skip
    if res.returncode != 0:
        pytest.skip(f"openssl образа не умеет -not_before/-not_after: {res.stdout[-200:]}")
    before = res.stdout.strip().splitlines()[-2:]
    ran = _start_and_settle(
        image, containers, "operator", BASE_ENV, [f"{op}:{OPR}:ro", f"{gen}:{GEN}"]
    )
    assert ran.state == "running", ran.log[-800:]
    after = _vol_sh(image, "sha256sum /v/tls.crt /v/tls.key", f"{op}:/v").strip().splitlines()
    assert after == before, "файлы оператора изменены"
    assert _vol_sh(image, "ls -A /v", f"{gen}:/v").strip() == "", (
        "рядом с сертификатом оператора сгенерирован свой"
    )
    served = ss.docker(
        "exec", ran.name, "sh", "-c",
        "openssl s_client -connect 127.0.0.1:443 </dev/null 2>/dev/null "
        "| openssl x509 -noout -subject",
    ).stdout  # fmt: skip
    assert "operator.test" in served


def test_t25_p1_operator_pair_with_mismatched_key_is_not_silently_replaced(
    image: str, vols: list[str], containers: _Cleanup
) -> None:
    """T25 п.1: у оператора ключ не от сертификата - его файлы не трогаются и вместо них не
    выдаётся самоподписанный: либо понятная ошибка запуска, либо работа на его файлах."""
    op = _vol(vols, "opbad")
    gen = _vol(vols, "opbadgen")
    setup = (
        f"{GEN_CERT.format(d='/v')} && mkdir -p /o && {GEN_CERT.format(d='/o')} "
        "&& cp /o/tls.crt /v/tls.crt && sha256sum /v/tls.crt /v/tls.key"
    )
    before = _vol_sh(image, setup, f"{op}:/v").strip().splitlines()[-2:]
    ran = _start_and_settle(
        image, containers, "opbad", BASE_ENV, [f"{op}:{OPR}:ro", f"{gen}:{GEN}"]
    )
    after = _vol_sh(image, "sha256sum /v/tls.crt /v/tls.key", f"{op}:/v").strip().splitlines()
    assert after == before
    assert _vol_sh(image, "ls -A /v", f"{gen}:/v").strip() == ""
    if ran.state == "exited":
        assert ran.code != 0 and ran.log.strip(), "падение без объяснения"


def test_t25_p1_only_one_operator_file_warns_and_falls_back_to_generated(
    image: str, vols: list[str], containers: _Cleanup
) -> None:
    """T25 п.1: оператор положил только tls.crt - в логе предупреждение с именем файла,
    web всё равно поднимается на сгенерированном сертификате."""
    op = _vol(vols, "onefile")
    gen = _vol(vols, "onegen")
    _vol_sh(image, "mkdir -p /o && " + GEN_CERT.format(d="/o") + " && cp /o/tls.crt /v/tls.crt",
            f"{op}:/v")  # fmt: skip
    ran = _start_and_settle(
        image, containers, "onefile", BASE_ENV, [f"{op}:{OPR}:ro", f"{gen}:{GEN}"]
    )
    assert ran.state == "running", ran.log[-800:]
    warn_lines = [
        ln
        for ln in ran.log.splitlines()
        if re.search(r"предупрежд|warn", ln, re.I) and re.search(r"tls\.(key|crt)", ln)
    ]
    assert warn_lines, f"нет предупреждения про одинокий файл оператора:\n{ran.log}"
    assert _vol_sh(image, PAIR_CHECK.format(d="/v"), f"{gen}:/v").strip() == "MATCH"
