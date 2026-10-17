"""002/R3-T11: описание API и роль, AC-1 (FR-1, FR-19, FR-20, NFR-1).

Проверяется и генерация (``gostracker openapi``, как ``app.openapi()`` без БД), и закоммиченный
``docs/api/openapi.json``: во всех полях текущей роли пользователя перечень допустимых значений -
ровно ``tech_admin``, ``business_admin``, ``user``; значения ``mixed`` нет. Поля прежней и новой
роли в записи журнала описаны как строки без перечня (исторические значения, FR-20).
"""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

import pytest

from app.core.config import get_settings
from tests.db_support import BACKEND_DIR

REPO_ROOT = BACKEND_DIR.parent
COMMITTED_SPEC = REPO_ROOT / "docs" / "api" / "openapi.json"
BAD_DSN = "postgresql+asyncpg://nobody:Zz9-never-print@127.0.0.1:1/tracker_none"
THREE_ROLES = ["tech_admin", "business_admin", "user"]
# Поля текущей роли из AC-1: (схема, свойство, что это за поле)
ROLE_FIELDS = [
    ("SessionUser", "role", "ответ на вход"),
    ("MeResponse", "role", "профиль"),
    ("AdminUser", "role", "учётные записи"),
    ("SetRoleRequest", "role", "запрос на назначение роли"),
    ("ProjectMember", "role", "участники проекта"),
    ("DirectoryUser", "role", "справочник пользователей"),
]


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Окружение без БД и секретов: DSN битый, ключа нет, data_dir пуст."""
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("DATABASE_URL", BAD_DSN)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("COOKIE_SECURE", "false")
    get_settings.cache_clear()
    yield tmp_path / "data"
    get_settings.cache_clear()


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("сетевой вызов запрещён при генерации OpenAPI")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


import app.cli.main  # noqa: E402,F401  # до capfd.readouterr(): иначе JSON-логи попадают в stdout


def _generate(capfd: pytest.CaptureFixture[str]) -> str:
    from app.cli.main import main

    capfd.readouterr()
    try:
        code = int(main(["openapi"]))
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    assert code == 0
    return capfd.readouterr().out


@pytest.fixture
def generated_text(cli_env: Path, no_network: None, capfd: pytest.CaptureFixture[str]) -> str:
    return _generate(capfd)


@pytest.fixture(params=["generated", "committed"])
def spec_pair(request: pytest.FixtureRequest) -> tuple[str, dict[str, Any], str]:
    """(источник, разобранная спецификация, исходный текст) - генерация и файл в репозитории."""
    if request.param == "generated":
        text = request.getfixturevalue("generated_text")
    else:
        assert COMMITTED_SPEC.is_file(), f"нет {COMMITTED_SPEC}"
        text = COMMITTED_SPEC.read_text(encoding="utf-8")
    loaded = json.loads(text)
    assert isinstance(loaded, dict)
    return str(request.param), loaded, text


def _schemas(spec: dict[str, Any]) -> dict[str, Any]:
    return dict(spec["components"]["schemas"])


def _role_enum(spec: dict[str, Any], schema: str, prop: str) -> list[str]:
    """Перечень значений поля: ``$ref`` (в т. ч. внутри ``anyOf``) -> ``Role.enum``, либо inline."""
    definition = _schemas(spec)[schema]["properties"][prop]
    candidates = definition.get("anyOf", [definition])
    found: list[list[str]] = []
    for item in candidates:
        if "$ref" in item:
            target = _schemas(spec)[str(item["$ref"]).rsplit("/", 1)[1]]
            assert "enum" in target, f"{schema}.{prop}: {item['$ref']} без enum"
            found.append(list(target["enum"]))
        elif "enum" in item:
            found.append(list(item["enum"]))
    assert len(found) == 1, f"{schema}.{prop}: ожидался один перечень, найдено {found}"
    return found[0]


def test_002_ac1_role_component_is_exactly_three_values(
    spec_pair: tuple[str, dict[str, Any], str],
) -> None:
    """002/AC-1 (FR-1): ``components.schemas.Role.enum`` - ровно три значения, без `mixed`."""
    source, spec, _ = spec_pair
    assert _schemas(spec)["Role"]["enum"] == THREE_ROLES, source


@pytest.mark.parametrize(
    ("schema", "prop", "label"), ROLE_FIELDS, ids=[f"{f[0]}.{f[1]}" for f in ROLE_FIELDS]
)
def test_002_ac1_every_current_role_field_lists_exactly_three_values(
    spec_pair: tuple[str, dict[str, Any], str], schema: str, prop: str, label: str
) -> None:
    """002/AC-1 (FR-1, FR-19): в каждом поле текущей роли перечень - ровно три значения."""
    source, spec, _ = spec_pair
    values = _role_enum(spec, schema, prop)
    assert values == THREE_ROLES, f"{source}: {schema}.{prop} ({label})"
    assert "mixed" not in values


def test_002_ac1_all_role_properties_are_covered_by_the_field_list(
    spec_pair: tuple[str, dict[str, Any], str],
) -> None:
    """002/AC-1: любое поле, ссылающееся на ``Role``, входит в проверенный перечень (нет новых)."""
    source, spec, _ = spec_pair
    referencing = {
        (name, prop)
        for name, schema in _schemas(spec).items()
        for prop, definition in schema.get("properties", {}).items()
        if "#/components/schemas/Role" in json.dumps(definition)
    }
    assert referencing == {(s, p) for s, p, _ in ROLE_FIELDS}, source


def test_002_ac1_no_other_enum_offers_role_values(
    spec_pair: tuple[str, dict[str, Any], str],
) -> None:
    """002/AC-1, FR-19: ни один другой перечень в описании API не содержит `mixed`."""
    source, spec, _ = spec_pair

    def walk(node: Any, path: str) -> list[str]:
        hits: list[str] = []
        if isinstance(node, dict):
            enum = node.get("enum")
            if isinstance(enum, list) and "mixed" in enum:
                hits.append(path)
            for key, value in node.items():
                hits += walk(value, f"{path}/{key}")
        elif isinstance(node, list):
            for i, value in enumerate(node):
                hits += walk(value, f"{path}/{i}")
        return hits

    assert walk(spec, "") == [], source


def test_002_ac1_audit_entry_details_are_plain_strings_without_enum(
    spec_pair: tuple[str, dict[str, Any], str],
) -> None:
    """002/AC-1, FR-20: ``AuditEntry.details`` - строки (или null) без перечня допустимых значений;
    ссылок на ``Role`` в записи журнала нет (исторические `mixed` остаются строками)."""
    source, spec, _ = spec_pair
    entry = _schemas(spec)["AuditEntry"]
    details = entry["properties"]["details"]

    assert "enum" not in json.dumps(entry), source
    assert "#/components/schemas/Role" not in json.dumps(entry), source
    variants = details.get("anyOf", [details])
    objects = [v for v in variants if v.get("type") == "object"]
    assert len(objects) == 1, source
    values = objects[0]["additionalProperties"]
    value_types = {v.get("type") for v in values.get("anyOf", [values])}
    assert value_types == {"string", "null"}, source


def test_002_ac1_committed_openapi_json_has_no_mixed() -> None:
    """002/AC-1 (FR-1, D-16): в ``docs/api/openapi.json`` нет `mixed` ни в каком виде."""
    assert COMMITTED_SPEC.is_file(), f"нет {COMMITTED_SPEC}"
    text = COMMITTED_SPEC.read_text(encoding="utf-8")
    assert '"mixed"' not in text
    assert "mixed" not in text.lower()


def test_002_ac1_generated_openapi_has_no_mixed(generated_text: str) -> None:
    """002/AC-1 (FR-1): в сгенерированном описании API нет `mixed`."""
    assert "mixed" not in generated_text.lower()
