"""R7-T01: совместимость API с базой ``f7f19cf`` (007/AC-47, NFR-1, plan PD-18).

База — ``openapi_baseline_f7f19cf.json`` (копия ``docs/api/openapi.json`` на ``f7f19cf``).
Сравнивается с ``create_app(settings).openapi()`` (БД и секреты не нужны). Проверки:
(1) каждая пара (путь, метод) базы есть; (2) каждая схема ``components.schemas`` базы есть,
свойства не удалены и не изменили ``type``/``$ref``/``format``/``enum``/``items``/``anyOf``
(``title``, ``description``, ``default`` не сравниваются); (3) у схем тел запросов существующих
операций набор ``required`` не вырос, у параметров пути и запроса нет новых обязательных.
Сравнение — чистые функции ниже; их работу доказывает тест на маленьких словарях.
"""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings
from app.main import create_app

BASELINE_PATH = Path(__file__).with_name("openapi_baseline_f7f19cf.json")
HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
IGNORED_KEYS = frozenset({"title", "description", "default"})
COMPARED_KEYS = ("type", "$ref", "format", "enum", "items", "anyOf")

Spec = dict[str, Any]


def _strip(node: Any) -> Any:
    """Рекурсивно убирает ``title``/``description``/``default`` из вложенных схем."""
    if isinstance(node, dict):
        return {k: _strip(v) for k, v in node.items() if k not in IGNORED_KEYS}
    if isinstance(node, list):
        return [_strip(v) for v in node]
    return node


def operations(spec: Spec) -> set[tuple[str, str]]:
    return {
        (path, method)
        for path, item in spec.get("paths", {}).items()
        for method in item
        if method in HTTP_METHODS
    }


def missing_operations(base: Spec, cur: Spec) -> list[str]:
    return sorted(f"{m.upper()} {p}" for p, m in operations(base) - operations(cur))


def _compared(node: Spec) -> dict[str, Any]:
    return {key: _strip(node.get(key)) for key in COMPARED_KEYS}


def schema_problems(base: Spec, cur: Spec) -> list[str]:
    problems: list[str] = []
    base_schemas = base.get("components", {}).get("schemas", {})
    cur_schemas = cur.get("components", {}).get("schemas", {})
    for name, bschema in sorted(base_schemas.items()):
        if name not in cur_schemas:
            problems.append(f"схема {name} удалена")
            continue
        cschema = cur_schemas[name]
        for key in COMPARED_KEYS:
            if _strip(bschema.get(key)) != _strip(cschema.get(key)):
                problems.append(f"{name}: изменилось {key}")
        cprops = cschema.get("properties", {})
        for prop, bprop in sorted(bschema.get("properties", {}).items()):
            if prop not in cprops:
                problems.append(f"{name}.{prop}: свойство удалено")
                continue
            for key in COMPARED_KEYS:
                if _strip(bprop.get(key)) != _strip(cprops[prop].get(key)):
                    problems.append(f"{name}.{prop}: изменилось {key}")
    return problems


def _resolve(spec: Spec, ref: str) -> Spec:
    node: Any = spec
    for part in ref.removeprefix("#/").split("/"):
        if not isinstance(node, dict) or part not in node:
            raise AssertionError(f"висячий $ref {ref}")
        node = node[part]
    assert isinstance(node, dict)
    return node


def _body_schema(spec: Spec, operation: Spec) -> tuple[str | None, Spec]:
    content = operation.get("requestBody", {}).get("content", {})
    schema: Spec = {}
    for media in content.values():
        schema = media.get("schema", {})
        break
    ref = schema.get("$ref")
    if isinstance(ref, str):
        return ref.rsplit("/", 1)[-1], _resolve(spec, ref)
    return None, schema


def _required_params(operation: Spec, item: Spec) -> set[tuple[str, str]]:
    params = [*item.get("parameters", []), *operation.get("parameters", [])]
    return {
        (p["in"], p["name"])
        for p in params
        if p.get("required") and p.get("in") in ("path", "query", "header", "cookie")
    }


def _success_schemas(operation: Spec) -> dict[str, Spec]:
    """Схемы успешных (2xx) ответов операции: код статуса -> схема первого типа содержимого."""
    result: dict[str, Spec] = {}
    for code, response in operation.get("responses", {}).items():
        if not str(code).startswith("2"):
            continue
        schema: Spec = {}
        for media in response.get("content", {}).values():
            schema = media.get("schema", {})
            break
        result[str(code)] = schema
    return result


def _refs_in(node: Any) -> set[str]:
    if isinstance(node, dict):
        found = {node["$ref"]} if isinstance(node.get("$ref"), str) else set()
        for value in node.values():
            found |= _refs_in(value)
        return found
    if isinstance(node, list):
        return set().union(*(_refs_in(v) for v in node)) if node else set()
    return set()


def _response_schema_names(base: Spec) -> set[str]:
    """Имена схем, достижимых из успешных ответов базы (транзитивно по ``$ref``)."""
    schemas = base.get("components", {}).get("schemas", {})
    pending: list[str] = []
    for bitem in base.get("paths", {}).values():
        for method, bop in bitem.items():
            if method in HTTP_METHODS:
                for schema in _success_schemas(bop).values():
                    pending += [r.rsplit("/", 1)[-1] for r in _refs_in(schema)]
    seen: set[str] = set()
    while pending:
        name = pending.pop()
        if name in seen or name not in schemas:
            continue
        seen.add(name)
        pending += [r.rsplit("/", 1)[-1] for r in _refs_in(schemas[name])]
    return seen


def response_problems(base: Spec, cur: Spec) -> list[str]:
    problems: list[str] = []
    for path, method in sorted(operations(base) & operations(cur)):
        label = f"{method.upper()} {path}"
        bsucc = _success_schemas(base["paths"][path][method])
        csucc = _success_schemas(cur["paths"][path][method])
        for code, bschema in sorted(bsucc.items()):
            if code not in csucc:
                problems.append(f"{label}: успешный ответ {code} пропал")
            elif _compared(bschema) != _compared(csucc[code]):
                problems.append(f"{label}: схема ответа {code} изменилась")
    base_schemas = base.get("components", {}).get("schemas", {})
    cur_schemas = cur.get("components", {}).get("schemas", {})
    for name in sorted(_response_schema_names(base)):
        if name not in cur_schemas:
            continue
        lost = set(base_schemas[name].get("required", [])) - set(
            cur_schemas[name].get("required", [])
        )
        if lost:
            problems.append(f"{name}: поля ответа перестали быть обязательными {sorted(lost)}")
    return problems


def request_problems(base: Spec, cur: Spec) -> list[str]:
    problems: list[str] = []
    for path, method in sorted(operations(base) & operations(cur)):
        bitem, citem = base["paths"][path], cur["paths"][path]
        bop, cop = bitem[method], citem[method]
        label = f"{method.upper()} {path}"
        bname, bbody = _body_schema(base, bop)
        _, cbody = _body_schema(cur, cop)
        grown = set(cbody.get("required", [])) - set(bbody.get("required", []))
        if grown:
            problems.append(f"{label}: новые обязательные поля тела {sorted(grown)} ({bname})")
        if cop.get("requestBody", {}).get("required") and not bop.get("requestBody", {}).get(
            "required"
        ):
            problems.append(f"{label}: тело запроса стало обязательным")
        new_params = _required_params(cop, citem) - _required_params(bop, bitem)
        if new_params:
            problems.append(f"{label}: новые обязательные параметры {sorted(new_params)}")
    return problems


@pytest.fixture(scope="module")
def baseline() -> Spec:
    data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


@pytest.fixture(scope="module")
def current() -> Spec:
    app = create_app(Settings(env="test", cookie_secure=False, expose_api_docs=False))
    spec: Spec = app.openapi()
    return spec


def test_ac47_baseline_is_nonempty(baseline: Spec) -> None:
    """База не пуста: сравнение не вырождается."""
    assert len(operations(baseline)) >= 30
    assert len(baseline["components"]["schemas"]) >= 20


def test_ac47_no_path_or_method_removed(baseline: Spec, current: Spec) -> None:
    assert missing_operations(baseline, current) == []


def test_ac47_no_schema_or_property_removed_or_retyped(baseline: Spec, current: Spec) -> None:
    assert schema_problems(baseline, current) == []


def test_ac47_no_new_required_request_input(baseline: Spec, current: Spec) -> None:
    assert request_problems(baseline, current) == []


def test_ac47_success_responses_keep_shape(baseline: Spec, current: Spec) -> None:
    assert response_problems(baseline, current) == []


def _mini_base() -> Spec:
    return {
        "paths": {
            "/a": {
                "post": {
                    "parameters": [{"name": "q", "in": "query", "required": False}],
                    "requestBody": {
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/In"}}
                        }
                    },
                },
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {"schema": {"$ref": "#/components/schemas/Out"}}
                            }
                        }
                    }
                },
            },
            "/b/{id}": {"get": {"parameters": [{"name": "id", "in": "path", "required": True}]}},
        },
        "components": {
            "schemas": {
                "In": {"properties": {"x": {"type": "string"}}, "required": ["x"]},
                "Color": {"type": "string", "enum": ["red", "green"]},
                "Out": {
                    "required": ["id"],
                    "properties": {
                        "items_": {"type": "array", "items": {"type": "string"}},
                        "id": {"type": "string", "format": "uuid", "title": "Id"},
                        "tag": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
                        "kind": {"type": "string", "enum": ["a", "b"]},
                    },
                },
            }
        },
    }


def test_ac47_comparison_accepts_identical_and_additive_changes() -> None:
    base = _mini_base()
    assert missing_operations(base, copy.deepcopy(base)) == []
    assert schema_problems(base, copy.deepcopy(base)) == []
    assert request_problems(base, copy.deepcopy(base)) == []

    cur = copy.deepcopy(base)
    cur["paths"]["/c"] = {"get": {}}
    cur["paths"]["/a"]["put"] = {}
    cur["components"]["schemas"]["Out"]["properties"]["new"] = {"type": "integer"}
    cur["components"]["schemas"]["Out"]["properties"]["id"]["title"] = "Other"
    cur["components"]["schemas"]["Out"]["properties"]["id"]["description"] = "d"
    cur["components"]["schemas"]["Out"]["properties"]["tag"]["default"] = "z"
    cur["components"]["schemas"]["In"]["properties"]["y"] = {"type": "string"}
    cur["paths"]["/a"]["post"]["parameters"].append(
        {"name": "opt", "in": "query", "required": False}
    )
    assert missing_operations(base, cur) == []
    assert schema_problems(base, cur) == []
    assert request_problems(base, cur) == []
    assert response_problems(base, cur) == []

    # допустимо: ответы 429/403, обязательное новое поле ответа, необязательный заголовок
    cur = copy.deepcopy(base)
    cur["paths"]["/a"]["get"]["responses"].update({"429": {}, "403": {}})
    cur["components"]["schemas"]["Out"]["properties"]["is_agent"] = {"type": "boolean"}
    cur["components"]["schemas"]["Out"]["required"].append("is_agent")
    cur["components"]["schemas"]["Color"]["title"] = "Colour"
    cur["paths"]["/a"]["post"]["parameters"].append(
        {"name": "X-H", "in": "header", "required": False}
    )
    assert schema_problems(base, cur) == []
    assert request_problems(base, cur) == []
    assert response_problems(base, cur) == []


def test_ac47_comparison_detects_each_violation() -> None:
    base = _mini_base()

    cur = copy.deepcopy(base)
    del cur["paths"]["/a"]["get"]
    assert missing_operations(base, cur) == ["GET /a"]

    cur = copy.deepcopy(base)
    del cur["paths"]["/b/{id}"]
    assert missing_operations(base, cur) == ["GET /b/{id}"]

    cur = copy.deepcopy(base)
    del cur["components"]["schemas"]["Out"]
    assert any("Out" in p for p in schema_problems(base, cur))

    cur = copy.deepcopy(base)
    del cur["components"]["schemas"]["Out"]["properties"]["id"]
    assert any("Out.id" in p for p in schema_problems(base, cur))

    cur = copy.deepcopy(base)
    cur["components"]["schemas"]["Out"]["properties"]["id"]["type"] = "integer"
    assert any("Out.id" in p and "type" in p for p in schema_problems(base, cur))

    cur = copy.deepcopy(base)
    cur["components"]["schemas"]["Out"]["properties"]["id"]["format"] = "date-time"
    assert any("Out.id" in p and "format" in p for p in schema_problems(base, cur))

    cur = copy.deepcopy(base)
    cur["components"]["schemas"]["Out"]["properties"]["kind"]["enum"] = ["a"]
    assert any("Out.kind" in p and "enum" in p for p in schema_problems(base, cur))

    cur = copy.deepcopy(base)
    cur["components"]["schemas"]["Out"]["properties"]["tag"]["anyOf"] = [{"type": "string"}]
    assert any("Out.tag" in p and "anyOf" in p for p in schema_problems(base, cur))

    cur = copy.deepcopy(base)
    cur["components"]["schemas"]["Out"]["properties"]["id"] = {"$ref": "#/components/schemas/In"}
    assert any("Out.id" in p for p in schema_problems(base, cur))

    cur = copy.deepcopy(base)
    cur["components"]["schemas"]["In"]["properties"]["y"] = {"type": "string"}
    cur["components"]["schemas"]["In"]["required"] = ["x", "y"]
    assert any("новые обязательные поля" in p for p in request_problems(base, cur))

    cur = copy.deepcopy(base)
    cur["paths"]["/a"]["post"]["parameters"][0]["required"] = True
    assert any("новые обязательные параметры" in p for p in request_problems(base, cur))

    cur = copy.deepcopy(base)
    cur["paths"]["/b/{id}"]["get"]["parameters"].append(
        {"name": "p", "in": "query", "required": True}
    )
    assert any("новые обязательные параметры" in p for p in request_problems(base, cur))

    # схема-перечисление верхнего уровня: удалено значение и сменён тип
    cur = copy.deepcopy(base)
    cur["components"]["schemas"]["Color"]["enum"] = ["red"]
    assert any(p.startswith("Color:") and "enum" in p for p in schema_problems(base, cur))

    cur = copy.deepcopy(base)
    cur["components"]["schemas"]["Color"]["type"] = "integer"
    assert any(p.startswith("Color:") and "type" in p for p in schema_problems(base, cur))

    # смена items у свойства
    cur = copy.deepcopy(base)
    cur["components"]["schemas"]["Out"]["properties"]["items_"]["items"] = {"type": "integer"}
    assert any("Out.items_" in p and "items" in p for p in schema_problems(base, cur))

    # обязательные параметры header и cookie
    for place in ("header", "cookie"):
        cur = copy.deepcopy(base)
        cur["paths"]["/a"]["post"]["parameters"].append(
            {"name": "X-K", "in": place, "required": True}
        )
        assert any("новые обязательные параметры" in p for p in request_problems(base, cur))

    # успешный ответ: смена $ref, пропажа кода, сокращение required
    cur = copy.deepcopy(base)
    schema = cur["paths"]["/a"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    schema["$ref"] = "#/components/schemas/In"
    assert any("GET /a" in p and "изменилась" in p for p in response_problems(base, cur))

    cur = copy.deepcopy(base)
    cur["paths"]["/a"]["get"]["responses"] = {"204": {}}
    assert any("пропал" in p for p in response_problems(base, cur))

    cur = copy.deepcopy(base)
    cur["components"]["schemas"]["Out"]["required"] = []
    assert any("Out" in p and "обязательными" in p for p in response_problems(base, cur))

    # схема только для входа: ослабление required ответом не считается
    cur = copy.deepcopy(base)
    cur["components"]["schemas"]["In"]["required"] = []
    assert response_problems(base, cur) == []


def test_ac47_dangling_ref_gives_clear_message() -> None:
    base = _mini_base()
    cur = copy.deepcopy(base)
    del cur["components"]["schemas"]["In"]
    with pytest.raises(AssertionError, match="висячий"):
        request_problems(base, cur)
