"""Имя клиента агента для журнала событий (ADR-0018, PN-6, FR-7).

MCP-адаптер выставляет имя токена на время одного вызова инструмента; ``record_event`` читает
его и пишет в ``domain_event.client_name``. Веб-запросы имени не выставляют, поэтому у их
событий поле пустое. Контекстная переменная не требует передавать имя через все сервисы.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

CLIENT_NAME_MAX_LENGTH = 64
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_client_name: ContextVar[str | None] = ContextVar("gtrack_client_name", default=None)


def check_client_name(value: str) -> str:
    """Fail Fast: 1–64 символа без управляющих; иначе ``ValueError`` (граница как в БД)."""
    if not 1 <= len(value) <= CLIENT_NAME_MAX_LENGTH or _CONTROL_CHARS.search(value):
        raise ValueError("client_name: 1–64 символа без управляющих символов")
    return value


@contextmanager
def client_name_scope(name: str) -> Iterator[None]:
    """Выставляет имя клиента на время блока (один запрос MCP) и возвращает прежнее значение."""
    token = _client_name.set(check_client_name(name))
    try:
        yield
    finally:
        _client_name.reset(token)


def current_client_name() -> str | None:
    return _client_name.get()
