"""Сервер MCP (stdio) для ИИ-агента: инструменты работают через API трекера по ключу.

Spec 007: FR-35, FR-37, FR-38, NFR-3, NFR-6; plan §4.9, PD-12, PD-14, PD-15.

Модуль самодостаточен: только стандартная библиотека, импортов ``app.*`` нет. Запуск::

    python3 -I <репозиторий>/backend/app/agent_mcp.py

Конфигурация — переменные окружения процесса: ``GOSTRACKER_URL``, ``GOSTRACKER_API_KEY``,
``GOSTRACKER_CA_FILE`` (необязательная). Протокол: JSON-RPC 2.0, одно сообщение — одна строка
UTF-8 в stdin/stdout. В stdout пишется только JSON-RPC; журнал — в stderr (имя инструмента и
HTTP-статус). Ключ, аргументы и тела ответов не логируются и не попадают в repr/тексты ошибок.
"""

from __future__ import annotations

import copy
import email.utils
import http.client
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import BinaryIO, Final, Protocol

PROTOCOL_VERSIONS: Final = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO: Final = {"name": "gostracker", "version": "0.1.0"}
ENV_URL, ENV_KEY, ENV_CA = "GOSTRACKER_URL", "GOSTRACKER_API_KEY", "GOSTRACKER_CA_FILE"

_LOOPBACK_HOSTS: Final = frozenset({"localhost", "127.0.0.1", "::1"})
_UUID_RE: Final = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_KEY_RE: Final = re.compile(r"[\x21-\x7e]+")
_MAX_RESPONSE_BYTES: Final = 8 * 1024 * 1024
_RETRY_STATUSES: Final = (429, 503)

# Коды ошибок JSON-RPC.
_PARSE_ERROR: Final = -32700
_INVALID_REQUEST: Final = -32600
_METHOD_NOT_FOUND: Final = -32601
_INVALID_PARAMS: Final = -32602
_INTERNAL_ERROR: Final = -32603


def _log(message: str) -> None:
    """Строка в stderr. Вызывающий передаёт только имя инструмента и статус/код."""
    try:
        sys.stderr.write(f"gostracker-mcp: {message}\n")
        sys.stderr.flush()
    except (OSError, ValueError):
        pass


# --- HTTP-транспорт --------------------------------------------------------------------------


@dataclass(frozen=True)
class ApiResponse:
    status: int
    body: object
    retry_after: int | None


class TransportError(Exception):
    """Сбой обращения к API; code: connection_error, redirect_not_allowed, invalid_response."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class Transport(Protocol):
    def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        body: Mapping[str, object] | None = None,
    ) -> ApiResponse: ...


def _parse_retry_after(value: str | None) -> int | None:
    if value is None:
        return None
    value = value.strip()
    if value.isascii() and value.isdigit():
        try:
            return int(value)
        except ValueError:  # длиннее предела int(str) (4300 цифр): значение не используется
            return None
    try:
        moment = email.utils.parsedate_to_datetime(value)
        return max(0, int(moment.timestamp() - time.time()))
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


class UrllibTransport:
    """Запросы к API трекера через ``urllib`` (PD-15).

    Только origin ``https://host[:port]``; ``http://`` — лишь для localhost/127.0.0.1/[::1].
    Переадресации не выполняются, системные прокси не используются: ключ уходит только
    на заданный адрес.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        cafile: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = self._check_base_url(base_url)
        if not _KEY_RE.fullmatch(api_key):
            raise ValueError("Неверный формат ключа в GOSTRACKER_API_KEY")
        self._authorization = "Bearer " + api_key
        self._timeout = timeout
        handlers: list[urllib.request.BaseHandler] = [
            urllib.request.ProxyHandler({}),
            urllib.request.UnknownHandler(),
            urllib.request.HTTPHandler(),
            urllib.request.HTTPDefaultErrorHandler(),
            urllib.request.HTTPErrorProcessor(),
        ]
        if self._base_url.startswith("https://"):
            try:
                context = ssl.create_default_context(cafile=cafile)
            except (OSError, ssl.SSLError) as exc:
                raise ValueError(
                    "Не удалось загрузить файл сертификата GOSTRACKER_CA_FILE"
                ) from exc
            handlers.append(urllib.request.HTTPSHandler(context=context))
        # Без HTTPRedirectHandler: 3xx приходит как HTTPError и не выполняется.
        opener = urllib.request.OpenerDirector()
        for handler in handlers:
            opener.add_handler(handler)
        self._opener = opener

    @staticmethod
    def _check_base_url(base_url: str) -> str:
        message = (
            "Неверный GOSTRACKER_URL: нужен адрес вида https://хост[:порт] без пути; "
            "http:// допускается только для localhost, 127.0.0.1 и [::1]"
        )
        try:
            parts = urllib.parse.urlsplit(base_url)
            hostname = parts.hostname
            parts.port  # noqa: B018 - проверка корректности порта
        except ValueError as exc:
            raise ValueError(message) from exc
        if parts.scheme not in ("http", "https") or not hostname:
            raise ValueError(message)
        if parts.path or parts.query or parts.fragment or parts.username or parts.password:
            raise ValueError(message)
        if parts.scheme == "http" and hostname not in _LOOPBACK_HOSTS:
            raise ValueError(message)
        return f"{parts.scheme}://{parts.netloc}"

    def __repr__(self) -> str:
        return f"UrllibTransport(base_url={self._base_url!r})"

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        body: Mapping[str, object] | None = None,
    ) -> ApiResponse:
        if not path.startswith("/"):
            raise ValueError("Путь запроса должен начинаться с «/»")
        url = self._base_url + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        headers = {
            "Authorization": self._authorization,
            "Accept": "application/json",
            "User-Agent": "gostracker-mcp/" + str(SERVER_INFO["version"]),
        }
        data: bytes | None = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self._opener.open(req, timeout=self._timeout) as resp:
                return self._response(resp.status, resp.read(_MAX_RESPONSE_BYTES + 1), None)
        except urllib.error.HTTPError as exc:
            try:
                raw = exc.read(_MAX_RESPONSE_BYTES + 1)
                retry_after = _parse_retry_after(exc.headers.get("Retry-After"))
            except (OSError, http.client.HTTPException) as err:
                raise TransportError("connection_error", "Не удалось прочитать ответ API") from err
            finally:
                exc.close()
            if 300 <= exc.code < 400:
                raise TransportError(
                    "redirect_not_allowed",
                    "API ответил переадресацией; переадресации не выполняются, "
                    "проверьте GOSTRACKER_URL",
                ) from None
            return self._response(exc.code, raw, retry_after, error=True)
        except TimeoutError as exc:
            raise TransportError("connection_error", "Превышено время ожидания ответа API") from exc
        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            raise TransportError("connection_error", "API трекера недоступен") from exc

    @staticmethod
    def _response(
        status: int, raw: bytes, retry_after: int | None, *, error: bool = False
    ) -> ApiResponse:
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise TransportError("invalid_response", "Ответ API слишком велик")
        if not raw.strip():
            return ApiResponse(status, None, retry_after)
        try:
            parsed: object = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            if error:
                return ApiResponse(status, None, retry_after)
            raise TransportError("invalid_response", "Ответ API не является JSON") from None
        return ApiResponse(status, parsed, retry_after)


# --- Протокол --------------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: Mapping[str, object]
    method: str
    path: str  # шаблон, например "/api/v1/tasks/{task_id}"
    path_params: tuple[str, ...] = ()
    query_params: tuple[str, ...] = ()
    body_params: tuple[str, ...] = ()


_API: Final = "/api/v1"
_STATUSES: Final = ("todo", "in_progress", "review", "done")
_PRIORITIES: Final = ("low", "medium", "high")
_DATE_PATTERN: Final = r"^\d{4}-\d{2}-\d{2}$"
_DATE_RULE: Final = "Срок в формате YYYY-MM-DD, не раньше сегодняшней даты по Europe/Moscow."
_STATUS_TEXT: Final = (
    "Статусы: todo — к выполнению, in_progress — в работе, review — на проверке, "
    "done — выполнена (закрытие задачи)."
)
_PRIORITY_TEXT: Final = "Приоритет: low — низкий, medium — средний, high — высокий."
_PAGE_FIELDS: Final = ("page", "page_size")


def _schema(properties: Mapping[str, object], required: Sequence[str] = ()) -> dict[str, object]:
    return {
        "type": "object",
        "properties": dict(properties),
        "required": list(required),
        "additionalProperties": False,
    }


def _uuid(description: str) -> dict[str, object]:
    return {"type": "string", "format": "uuid", "description": description}


def _uuid_or_null(description: str) -> dict[str, object]:
    return {
        "anyOf": [{"type": "string", "format": "uuid"}, {"type": "null"}],
        "description": description,
    }


def _status(description: str) -> dict[str, object]:
    return {"type": "string", "enum": list(_STATUSES), "description": description}


def _priority(description: str, *, default: str | None = None) -> dict[str, object]:
    prop: dict[str, object] = {
        "type": "string",
        "enum": list(_PRIORITIES),
        "description": description,
    }
    if default is not None:
        prop["default"] = default
    return prop


def _due_date(description: str) -> dict[str, object]:
    return {
        "type": "string",
        "format": "date",
        "pattern": _DATE_PATTERN,
        "description": description,
    }


def _due_date_or_null(description: str) -> dict[str, object]:
    return {
        "anyOf": [
            {
                "type": "string",
                "format": "date",
                "pattern": _DATE_PATTERN,
                "description": "Дата в формате YYYY-MM-DD.",
            },
            {"type": "null"},
        ],
        "description": description,
    }


def _title(description: str) -> dict[str, object]:
    return {"type": "string", "minLength": 1, "maxLength": 255, "description": description}


def _text(description: str, *, min_length: int = 0) -> dict[str, object]:
    prop: dict[str, object] = {"type": "string", "maxLength": 10000, "description": description}
    if min_length:
        prop["minLength"] = min_length
    return prop


_PAGE_PROPS: Final[Mapping[str, object]] = {
    "page": {"type": "integer", "minimum": 1, "description": "Номер страницы, начиная с 1."},
    "page_size": {
        "type": "integer",
        "minimum": 1,
        "maximum": 100,
        "description": "Размер страницы: от 1 до 100 (по умолчанию 50).",
    },
}
_TASK_ID: Final = _uuid("Идентификатор задачи или подзадачи (UUID).")
_PROJECT_ID: Final = _uuid("Идентификатор проекта (UUID).")

TOOLS: Final[tuple[ToolSpec, ...]] = (
    ToolSpec(
        name="whoami",
        description=(
            "Сведения о своей учётной записи агента: идентификатор, логин, роль и признак "
            "«агент». Параметров нет."
        ),
        input_schema=_schema({}),
        method="GET",
        path=f"{_API}/me",
    ),
    ToolSpec(
        name="list_projects",
        description=(
            "Список проектов, где учётная запись агента — участник: идентификатор, название, "
            "владелец. Постраничный: page и page_size."
        ),
        input_schema=_schema(_PAGE_PROPS),
        method="GET",
        path=f"{_API}/projects",
        query_params=_PAGE_FIELDS,
    ),
    ToolSpec(
        name="list_my_tasks",
        description=(
            "Задачи и подзадачи всех своих проектов, где агент — исполнитель. "
            "Постраничный: page и page_size."
        ),
        input_schema=_schema(_PAGE_PROPS),
        method="GET",
        path=f"{_API}/me/tasks",
        query_params=_PAGE_FIELDS,
    ),
    ToolSpec(
        name="list_project_tasks",
        description=(
            "Задачи и подзадачи проекта с фильтрами по статусу и исполнителю. Обязателен "
            f"project_id. {_STATUS_TEXT} Проект, где агент не участник, — ошибка 403. "
            "Постраничный: page и page_size."
        ),
        input_schema=_schema(
            {
                "project_id": _PROJECT_ID,
                "status": _status(f"Фильтр по статусу. {_STATUS_TEXT}"),
                "assignee_id": _uuid("Фильтр по исполнителю: идентификатор пользователя (UUID)."),
                **_PAGE_PROPS,
            },
            ["project_id"],
        ),
        method="GET",
        path=f"{_API}/projects/{{project_id}}/tasks",
        path_params=("project_id",),
        query_params=("status", "assignee_id", *_PAGE_FIELDS),
    ),
    ToolSpec(
        name="get_task",
        description=(
            "Карточка задачи или подзадачи: все поля, автор, исполнитель, подзадачи и прогресс, "
            "ссылка на родителя, права агента на эту задачу."
        ),
        input_schema=_schema({"task_id": _TASK_ID}, ["task_id"]),
        method="GET",
        path=f"{_API}/tasks/{{task_id}}",
        path_params=("task_id",),
    ),
    ToolSpec(
        name="create_task",
        description=(
            "Создать задачу верхнего уровня в проекте, где агент — участник. Обязательные поля: "
            "project_id, название (title, 1–255 символов), описание (description, не пустое, "
            "до 10 000 символов) и срок (due_date, формат YYYY-MM-DD, не раньше сегодняшней "
            "даты по Europe/Moscow). Приоритет (priority): low, medium или high, по умолчанию "
            "medium. Исполнитель по умолчанию — сам агент; назначить другого (assignee_id, "
            "участник проекта) может только агент с ролью БА. Статус новой задачи — todo."
        ),
        input_schema=_schema(
            {
                "project_id": _PROJECT_ID,
                "title": _title("Название задачи, 1–255 символов. Обязательно."),
                "description": _text(
                    "Описание задачи: обязательно, не пустое, до 10 000 символов.", min_length=1
                ),
                "due_date": _due_date(f"{_DATE_RULE} Обязателен."),
                "priority": _priority(_PRIORITY_TEXT + " По умолчанию medium.", default="medium"),
                "assignee_id": _uuid(
                    "Исполнитель (UUID участника проекта). По умолчанию — сам агент; другого "
                    "может назначить только агент с ролью БА."
                ),
            },
            ["project_id", "title", "description", "due_date"],
        ),
        method="POST",
        path=f"{_API}/projects/{{project_id}}/tasks",
        path_params=("project_id",),
        body_params=("title", "description", "due_date", "priority", "assignee_id"),
    ),
    ToolSpec(
        name="create_subtask",
        description=(
            "Создать подзадачу у задачи верхнего уровня (task_id — родитель). Достаточно "
            "названия (title); вложенность — один уровень. Необязательные поля: описание, срок "
            "(YYYY-MM-DD), приоритет (low, medium, high), исполнитель."
        ),
        input_schema=_schema(
            {
                "task_id": _uuid("Идентификатор родительской задачи (UUID)."),
                "title": _title("Название подзадачи, 1–255 символов. Обязательно."),
                "description": _text("Описание подзадачи, до 10 000 символов."),
                "due_date": _due_date("Срок в формате YYYY-MM-DD."),
                "priority": _priority(_PRIORITY_TEXT),
                "assignee_id": _uuid(
                    "Исполнитель (UUID участника проекта); назначить другого может только "
                    "агент с ролью БА."
                ),
            },
            ["task_id", "title"],
        ),
        method="POST",
        path=f"{_API}/tasks/{{task_id}}/subtasks",
        path_params=("task_id",),
        body_params=("title", "description", "due_date", "priority", "assignee_id"),
    ),
    ToolSpec(
        name="set_task_status",
        description=(
            "Сменить статус задачи или подзадачи. Закрыть задачу — перевести в done; переходы "
            f"не ограничены, из любого статуса в любой, включая возврат из done. {_STATUS_TEXT}"
        ),
        input_schema=_schema(
            {"task_id": _TASK_ID, "status": _status(f"Новый статус. {_STATUS_TEXT}")},
            ["task_id", "status"],
        ),
        method="PATCH",
        path=f"{_API}/tasks/{{task_id}}",
        path_params=("task_id",),
        body_params=("status",),
    ),
    ToolSpec(
        name="update_task",
        description=(
            "Изменить поля задачи или подзадачи: название, описание, срок, приоритет, "
            "исполнитель. Меняются только переданные поля, всё или ничего. Статус здесь не "
            "меняется — для этого set_task_status. У задачи верхнего уровня нельзя снять "
            "исполнителя или срок, очистить описание, поставить срок раньше сегодняшней даты "
            "по Europe/Moscow. Сменить исполнителя может только агент с ролью БА."
        ),
        input_schema=_schema(
            {
                "task_id": _TASK_ID,
                "title": _title("Новое название, 1–255 символов."),
                "description": _text("Новое описание, до 10 000 символов."),
                "due_date": _due_date_or_null(
                    "Новый срок в формате YYYY-MM-DD или null, чтобы снять срок (только у "
                    "подзадачи)."
                ),
                "priority": _priority(_PRIORITY_TEXT),
                "assignee_id": _uuid_or_null(
                    "Новый исполнитель (UUID участника проекта) или null, чтобы снять "
                    "исполнителя (только у подзадачи)."
                ),
            },
            ["task_id"],
        ),
        method="PATCH",
        path=f"{_API}/tasks/{{task_id}}",
        path_params=("task_id",),
        body_params=("title", "description", "due_date", "priority", "assignee_id"),
    ),
    ToolSpec(
        name="list_comments",
        description=(
            "Комментарии задачи или подзадачи; удалённые показываются заглушкой. "
            "Постраничный: page и page_size."
        ),
        input_schema=_schema({"task_id": _TASK_ID, **_PAGE_PROPS}, ["task_id"]),
        method="GET",
        path=f"{_API}/tasks/{{task_id}}/comments",
        path_params=("task_id",),
        query_params=_PAGE_FIELDS,
    ),
    ToolSpec(
        name="add_comment",
        description=(
            "Добавить комментарий к задаче или подзадаче: текст 1–10 000 символов, HTML "
            "вырезается. Результат работы агент оставляет комментарием."
        ),
        input_schema=_schema(
            {
                "task_id": _TASK_ID,
                "body": _text("Текст комментария, 1–10 000 символов.", min_length=1),
            },
            ["task_id", "body"],
        ),
        method="POST",
        path=f"{_API}/tasks/{{task_id}}/comments",
        path_params=("task_id",),
        body_params=("body",),
    ),
)


class UnknownToolError(LookupError):
    """Инструмента с таким именем нет (JSON-RPC -32602)."""


class _InvalidArguments(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def _rpc_error(id_: object, code: int, message: str) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def _tool_error(
    status: int | None,
    code: str,
    detail: object,
    retry_after: int | None = None,
) -> dict[str, object]:
    error: dict[str, object] = {
        "status": status,
        "code": code,
        "detail": detail,
        "retry_after_seconds": retry_after,
    }
    return {
        "content": [{"type": "text", "text": json.dumps({"error": error}, ensure_ascii=False)}],
        "structuredContent": {"error": error},
        "isError": True,
    }


def _scalar_to_query(name: str, value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, str)):
        return str(value)
    raise _InvalidArguments(f"Параметр «{name}» должен быть строкой или числом")


class McpServer:
    """Обработчик сообщений MCP. ``transport=None`` — ключ или конфигурация недоступны."""

    def __init__(
        self,
        transport: Transport | None,
        *,
        config_error: str | None = None,
        tools: Sequence[ToolSpec] = TOOLS,
    ) -> None:
        self._transport = transport
        self._config_error = config_error
        self._tools = {tool.name: tool for tool in tools}
        self._tool_list = tuple(tools)

    # -- JSON-RPC ---------------------------------------------------------------------------

    def handle(self, message: object) -> dict[str, object] | None:
        """Ответ JSON-RPC на сообщение или ``None`` (уведомление)."""
        if isinstance(message, list):
            return _rpc_error(None, _INVALID_REQUEST, "Пакетные запросы не поддерживаются")
        if not isinstance(message, dict):
            return _rpc_error(None, _INVALID_REQUEST, "Некорректный запрос")
        raw_id = message.get("id")
        id_ = raw_id if isinstance(raw_id, (str, int)) and not isinstance(raw_id, bool) else None
        method = message.get("method")
        if message.get("jsonrpc") != "2.0" or not isinstance(method, str):
            return _rpc_error(id_, _INVALID_REQUEST, "Некорректный запрос")
        if "id" not in message:
            return None  # уведомление: ответа нет
        if id_ is None:
            return _rpc_error(None, _INVALID_REQUEST, "Некорректный идентификатор запроса")
        params = message.get("params")
        try:
            return self._dispatch(id_, method, params)
        except Exception as exc:  # noqa: BLE001 - текст исключения клиенту не отдаётся
            _log(f"internal error: {type(exc).__name__}")
            return _rpc_error(id_, _INTERNAL_ERROR, "Внутренняя ошибка сервера")

    def _dispatch(self, id_: object, method: str, params: object) -> dict[str, object]:
        if method == "initialize":
            requested = params.get("protocolVersion") if isinstance(params, dict) else None
            version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
            result: dict[str, object] = {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": dict(SERVER_INFO),
            }
            return {"jsonrpc": "2.0", "id": id_, "result": result}
        if method == "ping":
            return {"jsonrpc": "2.0", "id": id_, "result": {}}
        if method == "tools/list":
            tools = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": copy.deepcopy(dict(tool.input_schema)),
                }
                for tool in self._tool_list
            ]
            return {"jsonrpc": "2.0", "id": id_, "result": {"tools": tools}}
        if method == "tools/call":
            if not isinstance(params, dict):
                return _rpc_error(id_, _INVALID_PARAMS, "Некорректные параметры вызова")
            name = params.get("name")
            if not isinstance(name, str):
                return _rpc_error(id_, _INVALID_PARAMS, "Не указано имя инструмента")
            try:
                tool_result = self.call_tool(name, params.get("arguments"))
            except UnknownToolError:
                return _rpc_error(id_, _INVALID_PARAMS, "Неизвестный инструмент")
            return {"jsonrpc": "2.0", "id": id_, "result": tool_result}
        return _rpc_error(id_, _METHOD_NOT_FOUND, "Метод не поддерживается")

    # -- Инструменты ------------------------------------------------------------------------

    def call_tool(self, name: str, arguments: object) -> dict[str, object]:
        """Выполнить инструмент; результат — ``CallToolResult``. Неизвестное имя — исключение."""
        tool = self._tools.get(name)
        if tool is None:
            raise UnknownToolError(name)
        if self._config_error is not None:
            _log(f"tool={name} error=config_error")
            return _tool_error(None, "config_error", self._config_error)
        if self._transport is None:
            _log(f"tool={name} status=401")
            return _tool_error(
                401,
                "not_authenticated",
                "Требуется вход в систему: задайте GOSTRACKER_API_KEY в конфигурации подключения",
            )
        try:
            path, query, body = self._build_request(tool, arguments)
        except _InvalidArguments as exc:
            _log(f"tool={name} error=invalid_arguments")
            return _tool_error(None, "invalid_arguments", exc.detail)
        try:
            response = self._transport.request(tool.method, path, query=query, body=body)
        except TransportError as exc:
            _log(f"tool={name} error={exc.code}")
            return _tool_error(None, exc.code, exc.detail)
        _log(f"tool={name} status={response.status}")
        return self._result(response)

    @staticmethod
    def _build_request(
        tool: ToolSpec, arguments: object
    ) -> tuple[str, dict[str, str] | None, dict[str, object] | None]:
        """Локальная проверка аргументов (PD-14): объект, известные имена, UUID в пути."""
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise _InvalidArguments("Аргументы должны быть объектом")
        properties = tool.input_schema.get("properties")
        known = set(properties) if isinstance(properties, dict) else set()
        unknown = sorted(str(key) for key in arguments if key not in known)
        if unknown:
            raise _InvalidArguments("Неизвестные параметры: " + ", ".join(unknown))
        quoted: dict[str, str] = {}
        for param in tool.path_params:
            value = arguments.get(param)
            if not isinstance(value, str) or not _UUID_RE.fullmatch(value):
                raise _InvalidArguments(f"Параметр «{param}» обязателен и должен быть UUID")
            quoted[param] = urllib.parse.quote(value, safe="")
        path = tool.path.format_map(quoted)
        query = {
            param: _scalar_to_query(param, arguments[param])
            for param in tool.query_params
            if arguments.get(param) is not None
        }
        body: dict[str, object] | None = None
        if tool.body_params:
            # Обязательные параметры тела уходят всегда (при отсутствии — null): отказ
            # возвращает API (422), а не «успех» пустого запроса; локально не проверяются.
            required_raw = tool.input_schema.get("required")
            required = set(required_raw) if isinstance(required_raw, (list, tuple)) else set()
            body = {
                param: arguments.get(param)
                for param in tool.body_params
                if param in arguments or param in required
            }
        return path, query or None, body

    @staticmethod
    def _result(response: ApiResponse) -> dict[str, object]:
        body = response.body
        if 200 <= response.status < 300:
            structured: object = body if isinstance(body, dict) else {"result": body}
            if body is None:
                structured = {}
            return {
                "content": [{"type": "text", "text": json.dumps(body, ensure_ascii=False)}],
                "structuredContent": structured,
                "isError": False,
            }
        code = "http_error"
        detail: object = f"HTTP {response.status}"
        if isinstance(body, dict):
            if isinstance(body.get("code"), str):
                code = str(body["code"])
            if isinstance(body.get("detail"), (str, list)):
                detail = body["detail"]
        retry = response.retry_after if response.status in _RETRY_STATUSES else None
        return _tool_error(response.status, code, detail, retry)


# --- stdio -----------------------------------------------------------------------------------


def _write(outstream: BinaryIO, message: dict[str, object]) -> None:
    try:
        line = json.dumps(message, ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError):
        line = json.dumps(_rpc_error(message.get("id"), _INTERNAL_ERROR, "Внутренняя ошибка"))
    outstream.write(line.encode("ascii") + b"\n")
    outstream.flush()


def serve(instream: BinaryIO, outstream: BinaryIO, server: McpServer) -> None:
    """Читать сообщения построчно до EOF; ответ — одной строкой, flush после каждого."""
    try:
        for raw in instream:
            line = raw.strip()
            if not line:
                continue
            try:
                message: object = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, ValueError, RecursionError):
                _write(outstream, _rpc_error(None, _PARSE_ERROR, "Некорректный JSON"))
                continue
            response = server.handle(message)
            if response is not None:
                _write(outstream, response)
    except BrokenPipeError:
        return


def build_server(environ: Mapping[str, str]) -> McpServer:
    """Сервер по окружению: нет ключа или ключ недопустимого формата -> 401 на вызовах
    без обращения к сети (FR-38); неверный URL или ``GOSTRACKER_CA_FILE`` -> ``config_error``."""
    api_key = environ.get(ENV_KEY, "").strip()
    if not api_key or not _KEY_RE.fullmatch(api_key):
        return McpServer(None)
    url = environ.get(ENV_URL, "").strip()
    if not url:
        return McpServer(None, config_error=f"Не задан адрес трекера в {ENV_URL}")
    cafile = environ.get(ENV_CA, "").strip() or None
    try:
        transport = UrllibTransport(url, api_key, cafile=cafile)
    except ValueError as exc:
        return McpServer(None, config_error=str(exc))
    return McpServer(transport)


def main() -> int:
    server = build_server(os.environ)
    try:
        serve(sys.stdin.buffer, sys.stdout.buffer, server)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
