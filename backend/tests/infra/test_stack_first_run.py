"""T26: сценарий первого запуска в поднятом стеке (AC-23, AC-105, FR-6, FR-58, FR-57, FR-51).

Маркер ``infra_stack``; без ``GT_INFRA_STACK=1`` все тесты пропускаются (см. stack_support.py).
Стек должен быть СВЕЖИМ (чистые тома проекта gostracker-infratest): тесты идут строго в порядке
определения и делят состояние сценария: сначала проверяется нетронутое состояние первого
запуска, затем вход, перезапуск api, смена пароля, повторный перезапуск.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import stat
from datetime import UTC, datetime
from typing import Any

import pytest

from tests.infra import stack_support as ss

pytestmark = ss.stack_marks()

PASSWORD_FILE = "/data/secrets/initial-admin-password.txt"
SECRET_FILE = "/data/secrets/secret_key"
NEW_PASSWORD = "Gt" + secrets.token_hex(10) + "Ab"  # 22 символа, не из списка частых

STATE: dict[str, Any] = {}


@pytest.fixture(scope="module", autouse=True)
def _fresh_stack_guard() -> None:
    """T27 (ревью T26): сценарий рассчитан на свежий стек; на «использованном» стеке вместо
    каскада KeyError - одно понятное сообщение."""
    reasons: list[str] = []
    if not _exists("api", PASSWORD_FILE):
        reasons.append("нет файла пароля первого администратора (пароль уже сменён)")
    if int(ss.psql("SELECT count(*) FROM app_user;")) != 1:
        reasons.append("в app_user не одна строка")
    if int(ss.psql("SELECT count(*) FROM user_session;")) > 0:
        reasons.append("уже есть сессии (user_session не пуста)")
    if reasons:
        pytest.fail("нужен свежий стек: down -v (" + "; ".join(reasons) + ")")


def _stat(service: str, path: str) -> tuple[int, int]:
    """(права, uid) файла внутри контейнера."""
    out = ss.sh_in(service, f"stat -c '%a %u' {path}").split()
    return int(out[0], 8), int(out[1])


def _exists(service: str, path: str) -> bool:
    res = ss.compose("exec", "-T", service, "test", "-e", path, check=False)
    return res.returncode == 0


def _admin_counts() -> tuple[int, int, int]:
    row = ss.psql(
        "SELECT (SELECT count(*) FROM workspace), (SELECT count(*) FROM app_user), "
        "(SELECT count(*) FROM workspace_member WHERE role = 'tech_admin');"
    )
    ws, users, admins = (int(x) for x in row.split("|"))
    return ws, users, admins


# --- состояние сразу после первого запуска -------------------------------------------------


def test_fr48_all_services_are_running_and_healthy() -> None:
    """FR-48, NFR-3: db, api, web подняты, healthcheck зелёный (``up --wait``)."""
    for service in ss.SERVICES:
        ss.wait_healthy(service, timeout=30)


def test_ac23_exactly_one_tech_admin_in_db() -> None:
    """AC-23: в БД одно пространство, один пользователь, один техадмин."""
    assert _admin_counts() == (1, 1, 1)


def test_ac23_password_file_is_0600_owned_by_app_user() -> None:
    """AC-23, D-19: файл пароля - 0600, владелец uid 10001; каталог секретов 0700."""
    mode, uid = _stat("api", PASSWORD_FILE)
    assert stat.S_IMODE(mode) == 0o600
    assert uid == 10001
    dir_mode, dir_uid = _stat("api", "/data/secrets")
    assert dir_mode == 0o700 and dir_uid == 10001
    key_mode, _ = _stat("api", SECRET_FILE)
    assert key_mode == 0o600


def test_ac23_password_file_content_matches_db_hash() -> None:
    """AC-23: файл login=/password=, пароль случайный (>= 12), в БД только Argon2id-хеш."""
    creds = ss.read_initial_credentials()
    assert re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,63}", creds["login"])
    assert len(creds["password"]) >= 12
    STATE["login"], STATE["password"] = creds["login"], creds["password"]
    stored = ss.psql(f"SELECT password_hash FROM app_user WHERE login = '{creds['login']}';")
    assert stored.startswith("$argon2id$")
    assert creds["password"] not in stored


def test_ac23_secret_key_is_generated_and_differs_from_env_example() -> None:
    """AC-23, D-20: ключ создан в /data/secrets, 32 байта hex, не из .env.example."""
    key = ss.exec_in("api", "cat", SECRET_FILE).strip()
    assert re.fullmatch(r"[0-9a-f]{64}", key)
    values = ss.parse_env_file_values(ss.REPO_ROOT / ".env.example")
    assert key not in values and "change-me" not in values
    STATE["key"] = key


def test_ac23_secret_key_not_in_api_environment() -> None:
    """D-20: при пустом SECRET_KEY контейнер не получает ключ через окружение."""
    env = ss.inspect("api", "{{json .Config.Env}}")
    assert not re.search(r'"SECRET_KEY=[^"]+"', env)


def test_ac23_only_web_publishes_ports_and_db_port_is_closed() -> None:
    """AC-23, AC-105, FR-6a: опубликованы только 80 и 443 сервиса web; у db и api нет."""
    published: dict[str, set[tuple[int, int]]] = {}
    for service in ss.SERVICES:
        raw = ss.inspect(service, "{{json .NetworkSettings.Ports}}")
        ports = json.loads(raw)
        pairs: set[tuple[int, int]] = set()
        for container_port, bindings in ports.items():
            for b in bindings or []:
                pairs.add((int(container_port.split("/")[0]), int(b["HostPort"])))
        published[service] = pairs
    assert published["db"] == set()
    assert published["api"] == set()
    assert published["web"] == {(80, ss.HTTP_PORT), (443, ss.HTTPS_PORT)}
    # Docker Compose v5 при отсутствии публикации печатает пусто или "invalid IP:0"
    port_out = ss.compose("port", "db", "5432", check=False).stdout.strip()
    assert port_out in ("", "invalid IP:0"), f"порт db опубликован: {port_out!r}"


def test_ac23_passwords_and_key_not_in_any_service_logs() -> None:
    """AC-23, FR-57: в логах сервисов нет пароля первого ТА и секретного ключа."""
    text = ss.logs()
    assert STATE["password"] not in text
    assert STATE["key"] not in text
    # путь к файлу в логах допустим, содержимое - нет
    assert not re.search(r"password\s*[=:]\s*" + re.escape(STATE["password"]), text)


def test_nfr4_bootstrap_logs_have_no_alembic_path_separator_warning() -> None:
    """Перенесено T10/T20 (5): в логах api нет предупреждения alembic про path_separator."""
    text = ss.logs("api")
    assert "path_separator" not in text
    assert "DeprecationWarning" not in text


def test_t16_db_has_idle_in_transaction_and_lock_timeouts() -> None:
    """Заметка T16: у соединений приложения заданы idle_in_transaction_session_timeout и
    lock_timeout (место задания не фиксируется: параметры сервера, роль или БД)."""
    rows = ss.psql(
        "SELECT name, setting FROM pg_settings WHERE name IN "
        "('idle_in_transaction_session_timeout', 'lock_timeout') ORDER BY name;"
    )
    values = {ln.split("|")[0]: int(ln.split("|")[1]) for ln in rows.splitlines()}  # мс
    assert set(values) == {"idle_in_transaction_session_timeout", "lock_timeout"}
    for name, ms in values.items():
        assert 0 < ms <= 600_000, f"{name}={ms} мс: должен быть задан и не больше 10 минут"


# --- вход со сгенерированным паролем -------------------------------------------------------


def test_ac23_login_with_generated_password_requires_password_change() -> None:
    """AC-23, FR-58, T12: вход по HTTPS с Origin, содержащим порт, без ложного origin_mismatch;
    cookie HttpOnly/Secure/SameSite=Lax; до смены пароля остальные действия закрыты."""
    r = ss.request(
        "/api/v1/auth/login",
        method="POST",
        json_body={"login": STATE["login"], "password": STATE["password"]},
        origin=ss.ORIGIN,
    )
    assert r.status == 200, r.body[:300]
    user = r.json()["user"]
    assert user["login"] == STATE["login"]
    assert user["role"] == "tech_admin"
    assert user["must_change_password"] is True
    cookie = r.cookie()
    assert cookie is not None, "нет Set-Cookie gt_session"
    token, raw = cookie
    flags = raw.lower()
    assert "httponly" in flags and "secure" in flags and "samesite=lax" in flags
    STATE["token"] = token

    me = ss.request("/api/v1/me", cookie=token)
    assert me.status == 403
    assert me.json()["code"] == "password_change_required"


def test_fr58_session_id_in_db_is_hmac_of_token_with_secret_key() -> None:
    """FR-58, D-13: в user_session лежит HMAC-SHA256(secret_key, token), а не сам токен."""
    key = bytes.fromhex(STATE["key"])
    expected = hmac.new(key, STATE["token"].encode(), hashlib.sha256).hexdigest()
    ids = ss.psql("SELECT encode(id, 'hex') FROM user_session;").split()
    assert expected in ids
    assert STATE["token"] not in " ".join(ids)


def test_t12_wrong_origin_port_is_origin_mismatch_but_right_one_is_not() -> None:
    """T12, T25 п.5: Origin с чужим портом -> 403 origin_mismatch; с портом стека -> обычный
    отказ входа 401 (несуществующий логин: счётчик администратора не затрагивается)."""
    body = {"login": "nobody-here", "password": "Irrelevant-password-1"}
    bad = ss.request(
        "/api/v1/auth/login", method="POST", json_body=body, origin=f"https://{ss.HOST}:9"
    )
    assert bad.status == 403 and bad.json()["code"] == "origin_mismatch"
    no_port = ss.request(
        "/api/v1/auth/login", method="POST", json_body=body, origin=f"https://{ss.HOST}"
    )
    assert no_port.status == 403 and no_port.json()["code"] == "origin_mismatch"
    good = ss.request("/api/v1/auth/login", method="POST", json_body=body, origin=ss.ORIGIN)
    assert good.status == 401 and good.json()["code"] == "invalid_credentials"


def test_t25_spoofed_forwarded_proto_changes_nothing() -> None:
    """T25 п.5: клиентский X-Forwarded-Proto перезаписывается nginx: схема всегда https."""
    body = {"login": "nobody-here", "password": "Irrelevant-password-1"}
    spoof_http = ss.request(
        "/api/v1/auth/login",
        method="POST",
        json_body=body,
        origin=ss.ORIGIN,
        headers={"X-Forwarded-Proto": "http", "X-Forwarded-For": "1.2.3.4"},
    )
    assert spoof_http.status == 401, "https-Origin отвергнут из-за подставной схемы http"
    http_origin = ss.request(
        "/api/v1/auth/login",
        method="POST",
        json_body=body,
        origin=f"http://{ss.HOST}:{ss.HTTPS_PORT}",
        headers={"X-Forwarded-Proto": "http"},
    )
    assert http_origin.status == 403 and http_origin.json()["code"] == "origin_mismatch"


# --- перезапуск api до смены пароля --------------------------------------------------------


def test_ac23_restart_keeps_single_admin_key_file_and_sessions() -> None:
    """AC-23, FR-6, D-20: после перезапуска api - один ТА, тот же ключ, файл пароля не
    пересоздан, прежняя сессия действует."""
    file_before = ss.exec_in("api", "cat", PASSWORD_FILE)
    inode_before = ss.sh_in("api", f"stat -c '%i %Y' {PASSWORD_FILE}")
    ss.restart("api")

    assert _admin_counts() == (1, 1, 1)
    assert ss.exec_in("api", "cat", SECRET_FILE).strip() == STATE["key"]
    assert ss.exec_in("api", "cat", PASSWORD_FILE) == file_before
    assert ss.sh_in("api", f"stat -c '%i %Y' {PASSWORD_FILE}") == inode_before
    me = ss.request("/api/v1/me", cookie=STATE["token"])
    assert me.status == 403 and me.json()["code"] == "password_change_required", (
        "сессия не пережила перезапуск (ключ изменился?)"
    )
    text = ss.logs("api")
    assert STATE["password"] not in text and STATE["key"] not in text


def test_ac23_restart_db_keeps_data_in_volume() -> None:
    """NFR-3: данные БД лежат в томе pgdata и переживают перезапуск контейнера db."""
    ss.restart("db")
    ss.wait_healthy("api", timeout=120)
    ss.wait_api_through_web()
    assert _admin_counts() == (1, 1, 1)


# --- смена пароля --------------------------------------------------------------------------


def test_ac23_password_change_removes_file_after_commit() -> None:
    """AC-23, FR-6: после смены пароля файл удалён; новый пароль работает, старый - нет."""
    # сессия могла быть создана до перезапуска db; входим заново
    login = ss.request(
        "/api/v1/auth/login",
        method="POST",
        json_body={"login": STATE["login"], "password": STATE["password"]},
        origin=ss.ORIGIN,
    )
    assert login.status == 200
    token = login.cookie()
    assert token is not None
    r = ss.request(
        "/api/v1/auth/password",
        method="POST",
        json_body={"current_password": STATE["password"], "new_password": NEW_PASSWORD},
        cookie=token[0],
        origin=ss.ORIGIN,
    )
    assert r.status == 204, r.body[:300]
    assert not _exists("api", PASSWORD_FILE), "файл пароля первого ТА не удалён"

    old = ss.request(
        "/api/v1/auth/login",
        method="POST",
        json_body={"login": STATE["login"], "password": STATE["password"]},
        origin=ss.ORIGIN,
    )
    assert old.status == 401
    new = ss.request(
        "/api/v1/auth/login",
        method="POST",
        json_body={"login": STATE["login"], "password": NEW_PASSWORD},
        origin=ss.ORIGIN,
    )
    assert new.status == 200
    assert new.json()["user"]["must_change_password"] is False
    cookie = new.cookie()
    assert cookie is not None
    STATE["token2"] = cookie[0]
    me = ss.request("/api/v1/me", cookie=cookie[0])
    assert me.status == 200 and me.json()["role"] == "tech_admin"


def test_ac23_restart_after_change_does_not_recreate_password_file() -> None:
    """FR-6: повторный запуск не пересоздаёт файл пароля и не создаёт второго ТА."""
    ss.restart("api")
    assert not _exists("api", PASSWORD_FILE)
    assert _admin_counts() == (1, 1, 1)
    assert ss.exec_in("api", "cat", SECRET_FILE).strip() == STATE["key"]
    assert NEW_PASSWORD not in ss.logs()


# --- логи ----------------------------------------------------------------------------------


def test_t20_health_is_not_logged_at_info_but_other_requests_are() -> None:
    """Перенесено T20: /api/v1/health (HEALTHCHECK, ~8,6 тыс. строк/сутки) не пишется в INFO;
    остальные запросы по-прежнему пишутся (контроль, что access-лог не отключён целиком)."""
    since = datetime.now(UTC).isoformat()
    for _ in range(3):
        assert ss.request("/api/v1/health").status == 200
    ss.request("/api/v1/me", cookie=STATE["token2"])
    text = ss.logs("api", since=since)
    records = ss.json_lines(text)
    info_paths = [r.get("path") for r in records if str(r.get("level", "")).upper() == "INFO"]
    assert "/api/v1/me" in info_paths, f"access-лог пуст? {text[-500:]}"
    assert "/api/v1/health" not in info_paths


def test_fr57_logs_have_no_cookie_or_passwords_after_scenario() -> None:
    """FR-57: после всего сценария в логах нет ни паролей, ни токена сессии, ни ключа."""
    text = ss.logs()
    for secret in (NEW_PASSWORD, STATE["password"], STATE["key"], STATE["token"], STATE["token2"]):
        assert secret not in text


# --- тома ----------------------------------------------------------------------------------


def test_fr51_d19_named_volumes_exist_with_expected_mounts() -> None:
    """D-19: тома pgdata, appdata, tls-generated проекта; /data - том appdata (не bind)."""
    names = set(ss.docker("volume", "ls", "--format", "{{.Name}}").stdout.split())
    for vol in ("pgdata", "appdata", "tls-generated"):
        assert f"{ss.PROJECT}_{vol}" in names
    mounts = ss.inspect("api", "{{range .Mounts}}{{.Type}}:{{.Name}}:{{.Destination}};{{end}}")
    assert f"volume:{ss.PROJECT}_appdata:/data;" in mounts


def test_d19_data_dir_permissions_and_no_world_readable_files() -> None:
    """D-19, NFR-9: /data принадлежит 10001; файлы секретов без прав для группы и остальных."""
    mode, uid = _stat("api", "/data")
    assert uid == 10001
    assert mode & 0o007 == 0, f"/data доступен всем: {mode:o}"
    out = ss.sh_in("api", "find /data/secrets -type f -exec stat -c '%a %n' {} +")
    assert out.strip(), "в /data/secrets нет файлов"
    for line in out.splitlines():
        perm, _, name = line.partition(" ")
        assert int(perm, 8) & 0o077 == 0, f"{name}: права {perm}"
    stale = ss.sh_in("api", "ls -A /data/secrets")
    assert ".tmp" not in stale, "остатки временных файлов в /data/secrets"
