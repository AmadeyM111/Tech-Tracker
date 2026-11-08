"""Подкоманда ``gtrack mcp``: stdio-мост к ``/mcp`` для локальных агентов (ADR-0018, PN-8).

Агент (например Claude Code) запускает процесс ``gtrack mcp`` и говорит с ним по stdin/stdout.
Мост пересылает протокол на HTTP-эндпоинт трекера с токеном из окружения; бизнес-логики нет.
Переменные: ``GTRACK_TOKEN`` (обязательна), ``GTRACK_URL`` (по умолчанию
``https://localhost:<HTTPS_PORT>``), ``GTRACK_CA_FILE`` (для самоподписанного сертификата).
Токен аргументом командной строки не принимается: он не попадает в историю shell. В stdout идёт
только протокол; сообщения об ошибках — в stderr.
"""

from __future__ import annotations

import argparse
import os
import ssl
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import anyio
import httpx
from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

TOKEN_ENV = "GTRACK_TOKEN"
URL_ENV = "GTRACK_URL"
CA_ENV = "GTRACK_CA_FILE"
DEFAULT_HTTPS_PORT = "443"
_TIMEOUT = httpx.Timeout(30.0, read=300.0)


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "mcp",
        help="MCP по stdio для локальных агентов (нужен GTRACK_TOKEN)",
        description=(
            "Stdio-мост к /mcp трекера. Переменные окружения: GTRACK_TOKEN (обязательна), "
            "GTRACK_URL, GTRACK_CA_FILE."
        ),
    )
    parser.set_defaults(handler=run)


def endpoint_from_env(env: dict[str, str]) -> str:
    base = env.get(URL_ENV) or f"https://localhost:{env.get('HTTPS_PORT', DEFAULT_HTTPS_PORT)}"
    return base.rstrip("/") + "/mcp"


def http_client(token: str, ca_file: str | None) -> httpx.AsyncClient:
    """HTTP-клиент с Bearer-токеном; CA-файл — для самоподписанного сертификата (ADR-0004)."""
    verify: bool | ssl.SSLContext = ssl.create_default_context(cafile=ca_file) if ca_file else True
    return httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token}"}, timeout=_TIMEOUT, verify=verify
    )


@asynccontextmanager
async def open_session(endpoint: str, client: httpx.AsyncClient) -> AsyncIterator[ClientSession]:
    """Сессия MCP на удалённом ``/mcp``; заголовки клиента не выводятся."""
    async with (
        streamable_http_client(endpoint, http_client=client) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        yield session


def _proxy_server(session: ClientSession) -> Server:
    server = Server("gtrack")

    async def list_tools() -> list[types.Tool]:
        return (await session.list_tools()).tools

    async def call_tool(name: str, arguments: dict[str, Any] | None) -> types.CallToolResult:
        return await session.call_tool(name, arguments or {})

    server.list_tools()(list_tools)  # type: ignore[no-untyped-call]  # декоратор SDK без типов
    server.call_tool(validate_input=False)(call_tool)
    return server


async def _bridge(endpoint: str, token: str, ca_file: str | None) -> int:
    try:
        async with http_client(token, ca_file) as client, open_session(endpoint, client) as session:
            server = _proxy_server(session)
            async with stdio_server() as (stdin, stdout):
                await server.run(stdin, stdout, server.create_initialization_options())
    except Exception as exc:  # без текста ответа и заголовков: только тип и адрес
        print(f"gtrack mcp: сбой моста к {endpoint} ({type(exc).__name__})", file=sys.stderr)
        return 1
    return 0


def run(_args: argparse.Namespace) -> int:
    env = dict(os.environ)
    token = env.get(TOKEN_ENV, "").strip()
    if not token:
        print(
            f"{TOKEN_ENV} не задан: создайте токен в разделе «Доступ для агентов» "
            "и передайте его через окружение",
            file=sys.stderr,
        )
        return 2
    ca_file = env.get(CA_ENV) or None
    if ca_file is not None and not Path(ca_file).is_file():
        print(f"{CA_ENV}: файл не найден", file=sys.stderr)
        return 2
    return anyio.run(_bridge, endpoint_from_env(env), token, ca_file)
