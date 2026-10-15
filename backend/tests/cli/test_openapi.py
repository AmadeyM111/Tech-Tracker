"""T19: ``gostracker openapi [--out PATH]`` (plan §4.13, §4.14; FR-43, FR-44, FR-45, D-32, D-33).

Генерация идёт без БД и без секретов; вывод детерминирован (``sort_keys``, ``indent=2``,
``ensure_ascii=False``, завершающий ``\\n``); файл ``docs/api/openapi.json`` в репозитории
обязан совпадать с генерацией.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from app.core.config import get_settings
from tests.db_support import BACKEND_DIR

REPO_ROOT = BACKEND_DIR.parent
COMMITTED_SPEC = REPO_ROOT / "docs" / "api" / "openapi.json"
BAD_DSN = "postgresql+asyncpg://nobody:Zz9-never-print@127.0.0.1:1/tracker_none"
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Окружение без БД и секретов: DSN битый, ключа нет, data_dir пуст."""
    data_dir = tmp_path / "data"
    for name in ("SECRET_KEY",):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("DATABASE_URL", BAD_DSN)
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("COOKIE_SECURE", "false")
    get_settings.cache_clear()
    yield data_dir
    get_settings.cache_clear()


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("сетевой вызов запрещён при генерации OpenAPI")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


import app.cli.main  # noqa: E402,F401  # до capfd.readouterr(): иначе JSON-логи alembic попадают в stdout


def _run(argv: list[str]) -> int:
    from app.cli.main import main

    try:
        return int(main(argv))
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)


def _generate_stdout(capfd: pytest.CaptureFixture[str]) -> str:
    capfd.readouterr()
    assert _run(["openapi"]) == 0
    return capfd.readouterr().out


@pytest.fixture
def spec_text(cli_env: Path, no_network: None, capfd: pytest.CaptureFixture[str]) -> str:
    return _generate_stdout(capfd)


@pytest.fixture
def spec(spec_text: str) -> dict[str, Any]:
    loaded = json.loads(spec_text)
    assert isinstance(loaded, dict)
    return loaded


def _operations(spec: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (method.upper(), path, op)
        for path, item in spec["paths"].items()
        for method, op in item.items()
        if method in HTTP_METHODS
    ]


def _ref(schema: dict[str, Any] | None) -> str | None:
    if not schema:
        return None
    ref = schema.get("$ref")
    return str(ref) if ref else None


def _error_ref(op: dict[str, Any], status: str) -> str | None:
    response = op["responses"].get(status)
    if response is None:
        return None
    return _ref(response.get("content", {}).get("application/json", {}).get("schema"))


def _resolve(spec: dict[str, Any], ref: str) -> dict[str, Any]:
    assert ref.startswith("#/components/schemas/"), ref
    return spec["components"]["schemas"][ref.rsplit("/", 1)[1]]


# --- вывод и формат -----------------------------------------------------------------------


def test_ac_fr44_openapi_stdout_is_valid_json_exit_0(spec: dict[str, Any]) -> None:
    """FR-44: код 0, в stdout валидный OpenAPI 3.x с путями."""
    assert str(spec["openapi"]).startswith("3.")
    assert spec["paths"]


def test_fr44_openapi_format_is_canonical(spec_text: str) -> None:
    """Формат: sort_keys, indent=2, ensure_ascii=False, завершающий перевод строки."""
    loaded = json.loads(spec_text)
    canonical = json.dumps(loaded, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    assert spec_text == canonical
    assert spec_text.endswith("}\n")
    assert not spec_text.endswith("\n\n")


def test_fr44_openapi_is_deterministic(
    cli_env: Path, no_network: None, capfd: pytest.CaptureFixture[str]
) -> None:
    """Два запуска дают побайтно равный вывод."""
    first = _generate_stdout(capfd)
    second = _generate_stdout(capfd)
    assert first and first == second


def test_fr44_openapi_out_file_equals_stdout(
    cli_env: Path, no_network: None, capfd: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """``--out PATH``: код 0, файл == stdout-вариант (байты), stdout не содержит JSON."""
    stdout_variant = _generate_stdout(capfd)
    out = tmp_path / "nested-ok" / "spec.json"
    out.parent.mkdir()
    capfd.readouterr()
    assert _run(["openapi", "--out", str(out)]) == 0
    printed = capfd.readouterr().out
    assert out.read_bytes() == stdout_variant.encode("utf-8")
    assert '"openapi"' not in printed


def test_fr44_openapi_out_overwrites_existing(
    cli_env: Path, no_network: None, capfd: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    expected = _generate_stdout(capfd)
    out = tmp_path / "spec.json"
    out.write_text("OLD", encoding="utf-8")
    assert _run(["openapi", "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == expected


def test_fr44_openapi_out_is_atomic_no_stray_files(
    cli_env: Path,
    no_network: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Запись через временный файл + замена; при сбое замены старый файл цел, мусора нет."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    out = out_dir / "spec.json"
    out.write_text("OLD", encoding="utf-8")

    calls: list[str] = []
    real_replace, real_rename = os.replace, os.rename

    def failing_replace(*_a: Any, **_k: Any) -> None:
        calls.append("replace")
        raise OSError("simulated failure")

    def failing_rename(*_a: Any, **_k: Any) -> None:
        calls.append("rename")
        raise OSError("simulated failure")

    monkeypatch.setattr(os, "replace", failing_replace)
    monkeypatch.setattr(os, "rename", failing_rename)
    code = _run(["openapi", "--out", str(out)])
    monkeypatch.setattr(os, "replace", real_replace)
    monkeypatch.setattr(os, "rename", real_rename)

    assert calls, "запись должна идти через os.replace/os.rename (атомарная замена)"
    assert code != 0
    assert out.read_text(encoding="utf-8") == "OLD"
    assert [p.name for p in out_dir.iterdir()] == ["spec.json"]


def test_fr44_openapi_out_success_leaves_only_target(
    cli_env: Path, no_network: None, tmp_path: Path
) -> None:
    out_dir = tmp_path / "out2"
    out_dir.mkdir()
    assert _run(["openapi", "--out", str(out_dir / "spec.json")]) == 0
    assert [p.name for p in out_dir.iterdir()] == ["spec.json"]


def test_fr44_openapi_out_missing_directory_clean_error(tmp_path: Path) -> None:
    """``--out`` в несуществующий каталог: код ≠ 0, понятное сообщение, без трассировки."""
    target = tmp_path / "no-such-dir" / "spec.json"
    env = {**os.environ, "ENV": "test", "DATABASE_URL": BAD_DSN, "DATA_DIR": str(tmp_path / "d")}
    env.pop("SECRET_KEY", None)
    proc = subprocess.run(
        [sys.executable, "-m", "app.cli.main", "openapi", "--out", str(target)],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode != 0
    assert proc.returncode != 2, "подкоманда openapi должна существовать"
    assert "invalid choice" not in proc.stderr
    assert "Traceback" not in proc.stderr
    assert proc.stderr.strip(), "ожидается сообщение об ошибке"
    assert not target.parent.exists()
    assert "Zz9-never-print" not in proc.stdout + proc.stderr


def test_fr44_openapi_works_without_db_and_secrets_via_subprocess(tmp_path: Path) -> None:
    """Отдельный процесс: DATABASE_URL битый, SECRET_KEY нет — код 0, ключ не создаётся."""
    data_dir = tmp_path / "data"
    env = {**os.environ, "ENV": "test", "DATABASE_URL": "not-a-url", "DATA_DIR": str(data_dir)}
    env.pop("SECRET_KEY", None)
    proc = subprocess.run(
        [sys.executable, "-m", "app.cli.main", "openapi"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["paths"]
    assert not (data_dir / "secrets").exists()


def test_fr44_openapi_creates_no_secret_files(spec_text: str, cli_env: Path) -> None:
    assert spec_text
    assert not (cli_env / "secrets").exists()


# --- содержание ---------------------------------------------------------------------------


def test_fr43_all_paths_under_api_v1(spec: dict[str, Any]) -> None:
    """FR-43: все пути под ``/api/v1`` (health тоже; docs/redoc в схему не входят)."""
    bad = [p for p in spec["paths"] if not p.startswith("/api/v1/")]
    assert not bad, bad
    assert "/api/v1/health" in spec["paths"]


def test_d32_operation_ids_unique_and_equal_function_names(spec: dict[str, Any]) -> None:
    """D-32: operationId = имя функции роутера (без суффиксов пути/метода), уникален."""
    import importlib
    import inspect
    import pkgutil

    import app.api.v1 as api_v1

    functions: set[str] = set()
    for info in pkgutil.walk_packages(api_v1.__path__, prefix=f"{api_v1.__name__}."):
        module = importlib.import_module(info.name)
        functions |= {
            name
            for name, obj in vars(module).items()
            if inspect.iscoroutinefunction(obj) and obj.__module__ == module.__name__
        }
    ids = [op["operationId"] for _m, _p, op in _operations(spec)]
    assert len(ids) == len(set(ids))
    assert len(ids) >= 14
    for op_id in ids:
        assert op_id in functions, op_id


def test_d33_error_responses_declared(spec: dict[str, Any]) -> None:
    """D-33: 401/403/404/422 описаны там, где возможны: админка, /me, пароль, logout."""
    public = {("POST", "/api/v1/auth/login"), ("GET", "/api/v1/health")}
    for method, path, op in _operations(spec):
        responses = op["responses"]
        if (method, path) in public:
            continue
        assert "401" in responses, (method, path)
        if path.startswith("/api/v1/admin/") or path == "/api/v1/me":
            assert "403" in responses, (method, path)
        if "{" in path:
            assert "404" in responses, (method, path)
        if op.get("parameters") or op.get("requestBody"):
            assert "422" in responses, (method, path)
    login = spec["paths"]["/api/v1/auth/login"]["post"]["responses"]
    assert "422" in login


def test_d33_single_error_schema_with_detail_and_code(spec: dict[str, Any]) -> None:
    """Все 4xx ссылаются на одну схему с обязательными ``detail`` и ``code``; без
    ``HTTPValidationError`` (у неё нет ``code``)."""
    refs: set[str] = set()
    for method, path, op in _operations(spec):
        for status in op["responses"]:
            if not status.startswith("4"):
                continue
            ref = _error_ref(op, status)
            assert ref is not None, (method, path, status, "нет схемы тела ошибки")
            refs.add(ref)
    assert len(refs) == 1, refs
    schema = _resolve(spec, next(iter(refs)))
    assert {"detail", "code"} <= set(schema["properties"])
    assert {"detail", "code"} <= set(schema.get("required", []))
    assert schema["properties"]["code"].get("type") == "string"
    assert "HTTPValidationError" not in json.dumps(spec["paths"])


def test_fr57_password_request_fields_write_only(spec: dict[str, Any]) -> None:
    """Пароли в схемах запросов: ``format: password`` и/или ``writeOnly``."""
    found: list[str] = []
    for name, schema in spec["components"]["schemas"].items():
        for prop, definition in schema.get("properties", {}).items():
            if "password" in prop and definition.get("type") == "string":
                found.append(f"{name}.{prop}")
                assert definition.get("format") == "password" or definition.get("writeOnly"), (
                    name,
                    prop,
                )
    assert len(found) >= 4, found


def test_fr57_no_password_or_hash_in_response_schemas(spec: dict[str, Any]) -> None:
    """В схемах ответов нет полей пароля/хеша (допустим только флаг ``must_change_password``)."""
    response_refs: set[str] = set()

    def collect(node: Any) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                response_refs.add(ref.rsplit("/", 1)[1])
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)

    for _m, _p, op in _operations(spec):
        for status, response in op["responses"].items():
            if status.startswith("2"):
                collect(response)
    # транзитивно: вложенные схемы
    schemas = spec["components"]["schemas"]
    frontier = set(response_refs)
    while frontier:
        nxt: set[str] = set()
        for name in frontier:
            before = set(response_refs)
            collect(schemas[name])
            nxt |= response_refs - before
        frontier = nxt
    assert response_refs
    for name in response_refs:
        for prop, definition in schemas[name].get("properties", {}).items():
            lowered = prop.lower()
            assert "hash" not in lowered, (name, prop)
            if "password" in lowered:
                assert definition.get("type") == "boolean", (name, prop)


def test_fr44_committed_openapi_json_matches_generation(spec_text: str) -> None:
    """``docs/api/openapi.json`` существует и совпадает с генерацией (побайтно).

    Падает, если файла нет или он устарел: обновить ``gostracker openapi --out
    docs/api/openapi.json`` (``scripts/gen-api.sh``).
    """
    assert COMMITTED_SPEC.is_file(), f"нет {COMMITTED_SPEC}: выполните gostracker openapi --out"
    assert COMMITTED_SPEC.read_bytes() == spec_text.encode("utf-8"), (
        "docs/api/openapi.json устарел: перегенерируйте scripts/gen-api.sh"
    )


BODY_ROUTES_400 = {
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/password"),
    ("POST", "/api/v1/admin/users"),
    ("POST", "/api/v1/admin/users/{user_id}/reset-password"),
    ("PUT", "/api/v1/admin/users/{user_id}/role"),
    ("POST", "/api/v1/projects"),
    ("PATCH", "/api/v1/projects/{user_id}"),
    ("PUT", "/api/v1/projects/{user_id}/owner"),
    ("POST", "/api/v1/projects/{user_id}/members"),
}
BAD_JSON_DESCRIPTION = "Некорректный JSON в теле запроса (code: bad_request)"


def test_t68_400_declared_exactly_on_routes_with_body(spec: dict[str, Any]) -> None:
    """D-65: 400 объявлен у маршрутов с телом (ErrorResponse) и только у них."""
    declared: set[tuple[str, str]] = set()
    for method, path, op in _operations(spec):
        has_400 = "400" in op["responses"]
        has_body = "requestBody" in op
        assert has_400 == has_body, (method, path)
        if has_400:
            declared.add((method, path))
            assert op["responses"]["400"]["description"] == BAD_JSON_DESCRIPTION
            ref = _error_ref(op, "400")
            assert ref is not None and ref.endswith("/ErrorResponse"), (method, path)
    normalized = {(m, re.sub(r"\{[^}]+\}", "{user_id}", p)) for m, p in declared}
    assert normalized == BODY_ROUTES_400
