"""Логирование без секретов (plan §4.2, D-31; FR-57, FR-51).

- ``configure_logging(level)``: JSON-строки в stdout (одна запись = одна физическая строка);
- ``SecretsFilter``: маскирует значения ключей ``password|secret|token|cookie|authorization``
  в ``extra`` и аргументах (в том числе вложенных) на копиях, готовит очищенный текст
  трассировки без ``f_locals`` и значений аргументов, подавляет дубль трассировки
  ``uvicorn.error``;
- ``JsonFormatter``: сборка JSON-записи; текст сообщения и исключений очищается от
  ``key=value`` / ``key: value`` для запрещённых ключей;
- ``AccessLogMiddleware``: чистый ASGI access-лог без заголовков и тел.
"""

from __future__ import annotations

import contextlib
import json
import logging
import math
import re
import sys
import time
import traceback
from collections import namedtuple
from collections.abc import Mapping
from datetime import UTC, datetime
from types import TracebackType
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

MASK = "***"

_SECRET_WORDS = r"password|secret|token|cookie|authorization"
_SECRET_KEY_RE = re.compile(_SECRET_WORDS, re.IGNORECASE)

# ``key=value`` / ``key: value`` / ``key => value`` / ``key := value`` / ``"key": "value"``;
# ключ — слово, содержащее запрещённую
# подстроку (access_token, Set-Cookie). Линейность: совпадение начинается только на границе
# слова (lookbehind), наличие ключевого слова проверяет lookahead (атомарный), само слово
# потребляется одним квантификатором. Значение: необязательная схема (Bearer ...) и строка в
# кавычках (с экранированием) либо цепочка до пробела/;/&. Хвост ``; a=b`` нужен для значений
# cookie (несколько пар в одном заголовке).
_TEXT_SECRET_RE = re.compile(
    rf"""(?<![\w.\-])
    (?=[\w.\-]*(?:{_SECRET_WORDS}))
    (?P<key>[\w.\-]+)
    (?P<close>["']?)
    (?P<sep>[ \t]*(?:=>|:=|[=:])[ \t]*)
    (?P<val>(?:(?:bearer|basic|digest|negotiate)[ \t]+)?
        (?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s;&]+))
    (?P<tail>(?:;[ \t]*[\w.\-]+=[^\s;]*)*)
    """,
    re.IGNORECASE | re.VERBOSE,
)

# DSN ``scheme://user:pass@host``: пароль до последнего ``@`` перед ``/`` или пробелом.
_DSN_RE = re.compile(r"(?<![\w+.\-])(?P<scheme>\w[\w+.\-]*://)(?P<user>[^:/@\s]*):(?P<pw>[^/\s]+)@")

# repr(UnicodeError): ``UnicodeEncodeError('utf-8', 'пароль', 3, 4, 'reason')`` содержит args[1].
_UNICODE_OPEN_RE = re.compile(r"\bUnicode\w*Error\(")
_UNICODE_END_RE = re.compile(r""",\s*\d+,\s*\d+,\s*(?:'[^']*'|"[^"]*")\)""")

_INPUT_VALUE = "input_value="
_INPUT_TYPE = ", input_type="

_MAX_DEPTH = 20
_TRUNCATED = "<truncated>"

# Атрибуты самого LogRecord; всё остальное в ``__dict__`` — это ``extra``.
_SANITIZED_ATTR = "_gt_sanitized"  # метка: фильтр уже очистил запись, форматтер не повторяет
_STANDARD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    _SANITIZED_ATTR,
}
# extra, которые не попадают в JSON (дублируют message; содержат ANSI-коды)
_DROPPED_EXTRAS = frozenset({"color_message"})
_UVICORN_DUPLICATE_MESSAGE = "Exception in ASGI application"
_RESERVED_FIELDS = frozenset({"timestamp", "level", "logger", "message", "exception", "stack"})

_ACCESS_LOGGER = logging.getLogger("app.access")


# --------------------------------------------------------------------------- очистка значений


def _is_secret_key(key: object) -> bool:
    return _SECRET_KEY_RE.search(key if isinstance(key, str) else str(key)) is not None


def _mask_match(match: re.Match[str]) -> str:
    key = match["key"]
    value = match["val"]
    if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
        masked = f"{value[0]}{MASK}{value[0]}"
    else:
        masked = MASK
    # значения cookie — все пары до конца заголовка; для прочих ключей хвост сохраняется
    tail = "" if "cookie" in key.lower() else match["tail"]
    return f"{key}{match['close']}{match['sep']}{masked}{tail}"


def _mask_input_values(text: str) -> str:
    """pydantic ``input_value=… , input_type=``: значение маскируется безусловно (линейно)."""
    if _INPUT_VALUE not in text:
        return text
    last_end = text.rfind(_INPUT_TYPE)
    parts: list[str] = []
    pos = 0
    while True:
        found = text.find(_INPUT_VALUE, pos)
        if found < 0:
            break
        start = found + len(_INPUT_VALUE)
        if last_end >= start:
            end = text.find(_INPUT_TYPE, start)
        else:  # терминатора дальше нет: до конца строки
            end = text.find("\n", start)
            if end < 0:
                end = len(text)
        parts.append(text[pos:start])
        parts.append(MASK)
        pos = end
    parts.append(text[pos:])
    return "".join(parts)


def _strip_unicode_reprs(text: str) -> str:
    """``UnicodeEncodeError('utf-8', 'пароль', 3, 4, 'r')`` -> ``UnicodeEncodeError`` (линейно)."""
    if "Error(" not in text:
        return text
    opens = list(_UNICODE_OPEN_RE.finditer(text))
    if not opens:
        return text
    ends = [(m.start(), m.end()) for m in _UNICODE_END_RE.finditer(text)]
    parts: list[str] = []
    pos = 0
    k = 0
    for match in opens:
        if match.start() < pos:
            continue
        while k < len(ends) and ends[k][0] < match.end():
            k += 1
        if k == len(ends):
            break
        parts.append(text[pos : match.start()])
        parts.append(match.group(0)[:-1])
        pos = ends[k][1]
    parts.append(text[pos:])
    return "".join(parts)


def redact_text(text: str) -> str:
    """Заменяет значения запрещённых ключей, пароли в DSN и repr ``UnicodeError`` в тексте."""
    if not text:
        return text
    text = _mask_input_values(text)
    text = _strip_unicode_reprs(text)
    if "://" in text and "@" in text:
        text = _DSN_RE.sub(rf"\g<scheme>\g<user>:{MASK}@", text)
    if _SECRET_KEY_RE.search(text) is None:
        return text
    return _TEXT_SECRET_RE.sub(_mask_match, text)


# Рекурсивно разбираются только точные типы: подклассы (namedtuple, ``sqlalchemy.engine.URL``)
# сами решают, как себя показывать (URL маскирует пароль в str/repr).
_PLAIN_CONTAINERS: tuple[type, ...] = (list, tuple, set, frozenset)
_NAMEDTUPLE_MODULE = namedtuple.__module__  # модуль функций, сгенерированных namedtuple


def _owner(cls: type, name: str) -> type | None:
    return next((c for c in cls.__mro__ if name in c.__dict__), None)


def _has_generated_repr(cls: type) -> bool:
    """namedtuple без собственного ``__repr__``/``__str__``: печатает значения всех полей.

    ``typing.NamedTuple`` кладёт свой ``__repr__`` в тот же класс, что и ``_fields``,
    поэтому сгенерированный ``__repr__`` узнаём по модулю ``collections``.
    """
    if _owner(cls, "_fields") is None or _owner(cls, "__str__") not in (tuple, object):
        return False
    return getattr(cls.__repr__, "__module__", None) == _NAMEDTUPLE_MODULE


def _sanitize_tuple_subclass(
    value: tuple[Any, ...], *, json_mode: bool, redact: bool, depth: int
) -> Any:
    """Подкласс tuple: namedtuple с секретным полем — маскируется поле, иначе объект как есть.

    Объект с собственным ``__str__``/``__repr__`` (``URL``) не разбирается: в ``%``-форматировании
    он печатает себя сам (итоговое сообщение очищается), в JSON — ``redact_text(str(v))``.
    """
    cls = type(value)
    fields = getattr(cls, "_fields", None)
    if (
        _has_generated_repr(cls)
        and isinstance(fields, tuple)
        and len(fields) == len(value)
        and any(_is_secret_key(name) for name in fields)
    ):
        mapping = dict(zip(fields, value, strict=True))
        if json_mode:
            return _sanitize(mapping, json_mode=True, redact=redact, depth=depth)
        clean = _sanitize(mapping, redact=redact, depth=depth)
        try:
            return cls._make(clean[name] for name in fields)  # type: ignore[attr-defined]
        except Exception:  # нестандартный конструктор: показываем очищенный словарь
            return clean
    if not json_mode:
        return value
    return _stringify(value)


def _stringify(value: object) -> str:
    try:
        return redact_text(str(value))
    except Exception:  # __str__ пользовательского объекта не должен ронять логирование
        return f"<unprintable {type(value).__name__}>"


def _sanitize(value: Any, *, json_mode: bool = False, redact: bool = True, depth: int = 0) -> Any:
    """Копия значения без секретов; исходные объекты не меняются.

    ``json_mode=False`` сохраняет типы контейнеров (для ``%``-форматирования),
    ``json_mode=True`` приводит всё к JSON-совместимым типам. ``redact=False`` не чистит
    текст строк (его очистит итоговое сообщение), но маскирует ключи и ``UnicodeError``.
    """
    if depth > _MAX_DEPTH:
        return _TRUNCATED
    if isinstance(value, str):
        return redact_text(value) if redact else value
    if isinstance(value, UnicodeError):
        return type(value).__name__
    if isinstance(value, Mapping):
        out: dict[Any, Any] = {}
        for key, item in value.items():
            out_key = str(key) if json_mode and not isinstance(key, str) else key
            if _is_secret_key(key):
                out[out_key] = MASK
            else:
                out[out_key] = _sanitize(item, json_mode=json_mode, redact=redact, depth=depth + 1)
        return out
    if isinstance(value, tuple) and type(value) is not tuple:
        return _sanitize_tuple_subclass(value, json_mode=json_mode, redact=redact, depth=depth)
    if type(value) in _PLAIN_CONTAINERS:
        if (
            isinstance(value, list | tuple)
            and len(value) == 2
            and isinstance(value[0], str | bytes)
            and _is_secret_key(value[0])
        ):  # пара (ключ, значение): сырые заголовки ASGI, items() словаря
            first = _sanitize(value[0], json_mode=json_mode, redact=redact, depth=depth + 1)
            pair = [first, MASK]
            return pair if json_mode or isinstance(value, list) else tuple(pair)
        items = [
            _sanitize(item, json_mode=json_mode, redact=redact, depth=depth + 1) for item in value
        ]
        if json_mode or isinstance(value, list):
            return items
        if isinstance(value, tuple):
            return tuple(items)
        return frozenset(items) if isinstance(value, frozenset) else set(items)
    if not json_mode:
        return value
    if isinstance(value, bytes):
        return redact_text(value.decode("utf-8", "backslashreplace"))
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    return _stringify(value)


# --------------------------------------------------------------------------- трассировка


def _chain(exc: BaseException | None) -> list[BaseException]:
    """Все исключения цепочки (``__cause__``/``__context__``/подгруппы) без повторов."""
    seen: dict[int, BaseException] = {}
    stack: list[BaseException] = [exc] if exc is not None else []
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen[id(current)] = current
        for nxt in (current.__cause__, current.__context__):
            if nxt is not None:
                stack.append(nxt)
        if isinstance(current, BaseExceptionGroup):
            stack.extend(current.exceptions)
    return list(seen.values())


def format_exception_text(
    exc_info: tuple[type[BaseException], BaseException, TracebackType | None],
) -> str:
    """Трассировка без ``f_locals`` и значений аргументов, с очищенным текстом исключений.

    Для ``UnicodeError`` вместо ``str(exc)`` выводится только ``reason`` (в ``args[1]``
    лежит исходная строка — возможно, пароль).
    """
    exc_type, exc, tb = exc_info
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    for item in _chain(exc):
        if isinstance(item, UnicodeError):
            try:
                original = str(item)
            except Exception:
                continue
            if original:
                text = text.replace(original, str(getattr(item, "reason", "")))
    return redact_text(text.rstrip("\n"))


def _exc_info_of(
    record: logging.LogRecord,
) -> tuple[type[BaseException], BaseException, TracebackType | None] | None:
    info = record.exc_info
    if isinstance(info, tuple) and info[0] is not None and info[1] is not None:
        return (info[0], info[1], info[2])
    return None


# --------------------------------------------------------------------------- фильтр и формат


def _is_uvicorn_duplicate(record: logging.LogRecord) -> bool:
    """Дубль трассировки необработанной ошибки: её уже записал ``app.errors``.

    Внимание: ``SecretsFilter`` висит на обработчике и возвращает ``False`` ДО очистки записи,
    поэтому подавление действует только для этого обработчика; другие обработчики записи
    (если они появятся) получат дубль в сыром виде — их нужно защищать отдельно.
    """
    name = record.name
    if name != "uvicorn.error" and not name.startswith("uvicorn.error."):
        return False
    return bool(record.exc_info) and str(record.msg).startswith(_UVICORN_DUPLICATE_MESSAGE)


class SecretsFilter(logging.Filter):
    """Очищает запись на месте (на копиях значений) и подавляет дубль трассировки uvicorn.

    Вешается на обработчик: фильтры логгера не срабатывают для записей дочерних логгеров.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if _is_uvicorn_duplicate(record):
            return False
        try:
            self._sanitize_record(record)
        except Exception:  # fail-closed: лучше заглушка, чем неочищенная запись
            for key in [k for k in record.__dict__ if k not in _STANDARD_ATTRS]:
                del record.__dict__[key]
            record.msg = "log record sanitization failed; original record suppressed"
            record.args = None
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        record.__dict__[_SANITIZED_ATTR] = True
        return True

    @staticmethod
    def _sanitize_record(record: logging.LogRecord) -> None:
        args = record.args
        if args:
            # текст строк-аргументов очищает итоговое сообщение (один проход ниже)
            record.args = _sanitize(args, redact=False)
        # сообщение собирается и очищается один раз; сырые msg/args не доходят ни до
        # форматтера, ни до других обработчиков, ни до handleError
        record.msg = redact_text(_message_of(record))
        record.args = None
        for key in [k for k in record.__dict__ if k not in _STANDARD_ATTRS]:
            record.__dict__[key] = MASK if _is_secret_key(key) else _sanitize(record.__dict__[key])
        info = _exc_info_of(record)
        if info is not None:
            record.exc_text = format_exception_text(info)
        elif record.exc_text:
            record.exc_text = redact_text(record.exc_text)
        if record.stack_info:
            record.stack_info = redact_text(record.stack_info)


def _message_of(record: logging.LogRecord) -> str:
    try:
        return record.getMessage()
    except Exception:  # неверный формат/аргументы: не показываем args
        return f"{record.msg} [log format error]"


class JsonFormatter(logging.Formatter):
    """Одна запись — одна физическая строка JSON (UTC, кириллица не экранируется).

    Если запись уже прошла ``SecretsFilter`` (метка), extra и трассировка повторно не
    чистятся; сообщение очищается один раз после форматирования.
    """

    def format(self, record: logging.LogRecord) -> str:
        clean = bool(record.__dict__.get(_SANITIZED_ATTR))
        message = _message_of(record)
        entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": message if clean else redact_text(message),
        }
        for key, value in record.__dict__.items():
            if key in _STANDARD_ATTRS or key in _DROPPED_EXTRAS:
                continue
            name = f"extra_{key}" if key in _RESERVED_FIELDS else key
            if _is_secret_key(key):
                entry[name] = MASK
            else:
                entry[name] = _sanitize(value, json_mode=True, redact=not clean)
        info = _exc_info_of(record)
        if info is not None:
            entry["exception"] = (
                record.exc_text if clean and record.exc_text else format_exception_text(info)
            )
        elif record.exc_text:
            entry["exception"] = record.exc_text if clean else redact_text(record.exc_text)
        if record.stack_info:
            entry["stack"] = record.stack_info if clean else redact_text(record.stack_info)
        return _to_line(entry)


def _to_line(entry: dict[str, Any]) -> str:
    line = json.dumps(entry, ensure_ascii=False, default=str)
    # одиночные суррогаты нельзя закодировать в UTF-8; разделители строк Unicode — экранируем
    line = line.encode("utf-8", "backslashreplace").decode("utf-8")
    return line.replace("\x85", "\\u0085").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


class _StdoutHandler(logging.Handler):
    """Пишет в ``sys.stdout`` на момент записи (перехват pytest/capsys, переназначение)."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            stream = sys.stdout
            stream.write(self.format(record) + "\n")
            stream.flush()
        except Exception:
            self.handleError(record)

    def handleError(self, record: logging.LogRecord) -> None:  # noqa: N802 (API logging)
        """Сбой записи: в stderr только тип ошибки и имя логгера.

        Стандартный ``handleError`` печатает ``Message``/``Arguments``, текст исключения и
        стек вызова с исходными строками — там могут быть секреты.
        """
        if not logging.raiseExceptions:
            return
        exc_type = sys.exc_info()[0]
        name = exc_type.__name__ if exc_type is not None else "UnknownError"
        # stderr тоже недоступен: молча теряем запись, как stdlib
        with contextlib.suppress(Exception):
            sys.stderr.write(f"--- Logging error: {name} in logger {record.name!r} ---\n")


def _parse_level(level: str | int) -> int:
    if isinstance(level, int):
        return level
    mapping = logging.getLevelNamesMapping()
    name = level.strip().upper()
    if name not in mapping:
        raise ValueError(f"Unknown log level: {level!r}")
    return mapping[name]


def _drop_default_stream_handlers(logger: logging.Logger) -> None:
    # точный тип: дефолтные обработчики uvicorn; caplog и прочие подклассы не трогаем
    for handler in list(logger.handlers):
        if type(handler) is logging.StreamHandler:
            logger.removeHandler(handler)


def configure_logging(level: str | int = "INFO") -> None:
    """Подключает JSON-вывод в stdout; повторный вызов заменяет только свой обработчик."""
    numeric = _parse_level(level)
    root = logging.getLogger()
    for existing in list(root.handlers):
        if isinstance(existing, _StdoutHandler):
            root.removeHandler(existing)
            existing.close()
    handler = _StdoutHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(SecretsFilter())
    # Первым в списке: фильтр очищает запись на месте, и остальные обработчики корня
    # (добавленные раньше — например, caplog, или позже) получают уже очищенную запись.
    root.handlers.insert(0, handler)
    root.setLevel(numeric)

    # uvicorn: свои записи идут через корневой обработчик (JSON), дефолтные handlers убираем
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        _drop_default_stream_handlers(uvicorn_logger)
        uvicorn_logger.propagate = True
    access = logging.getLogger("uvicorn.access")
    _drop_default_stream_handlers(access)
    access.propagate = False
    access.disabled = True


# --------------------------------------------------------------------------- access-лог


class AccessLogMiddleware:
    """Чистый ASGI-middleware: метод, путь без query, статус, длительность, user_id.

    Заголовки и тела не читаются. Запись делается в ``finally``: при исключении статус 500
    (ответ 500 формирует ``ServerErrorMiddleware`` снаружи).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            method = str(scope.get("method", ""))
            path = str(scope.get("path", ""))
            extra: dict[str, Any] = {
                "method": method,
                "path": path,
                "status": status,
                "duration_ms": duration_ms,
            }
            state = scope.get("state")
            user_id = state.get("user_id") if isinstance(state, dict) else None
            if user_id is not None:
                extra["user_id"] = str(user_id)
            # путь только в extra: он очищается один раз, дублировать его в тексте незачем
            _ACCESS_LOGGER.info("http request", extra=extra)
