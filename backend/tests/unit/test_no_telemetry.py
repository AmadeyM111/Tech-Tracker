"""T19: отсутствие телеметрии (NFR-4): нет клиентов аналитики, нет сетевых обращений при старте."""

from __future__ import annotations

import importlib.metadata as md
import importlib.util
import re
import socket
import tomllib
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from tests.db_support import BACKEND_DIR

FORBIDDEN_DISTRIBUTIONS = {
    "sentry-sdk",
    "sentry_sdk",
    "raven",
    "posthog",
    "segment-analytics-python",
    "analytics-python",
    "datadog",
    "ddtrace",
    "newrelic",
    "amplitude-analytics",
    "amplitude",
    "mixpanel",
    "rollbar",
    "bugsnag",
    "opentelemetry-sdk",
}
FORBIDDEN_MODULES = ("sentry_sdk", "posthog", "segment", "datadog", "newrelic", "amplitude")
ANALYTICS_HOSTS = (
    "sentry.io",
    "google-analytics",
    "googletagmanager",
    "posthog",
    "segment.io",
    "segment.com",
    "mixpanel",
    "amplitude.com",
    "datadoghq",
    "newrelic",
    "hotjar",
    "mc.yandex",
    "metrika",
    "clarity.ms",
    "plausible.io",
)


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def test_nfr4_opentelemetry_sdk_not_installed() -> None:
    try:
        spec = importlib.util.find_spec("opentelemetry.sdk")
    except ModuleNotFoundError:
        spec = None
    assert spec is None, "пакет opentelemetry.sdk установлен"


def test_nfr4_no_telemetry_distributions_installed() -> None:
    installed = {_norm(d.metadata["Name"]) for d in md.distributions() if d.metadata["Name"]}
    forbidden = {_norm(n) for n in FORBIDDEN_DISTRIBUTIONS}
    assert not (installed & forbidden), installed & forbidden
    exporters = {n for n in installed if n.startswith("opentelemetry-exporter")}
    assert not exporters, exporters


@pytest.mark.parametrize("module", FORBIDDEN_MODULES)
def test_nfr4_telemetry_modules_not_importable(module: str) -> None:
    assert importlib.util.find_spec(module) is None


def test_nfr4_project_dependencies_have_no_telemetry_clients() -> None:
    data = tomllib.loads((BACKEND_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    project = data.get("project", {})
    declared = list(project.get("dependencies", []))
    for group in project.get("optional-dependencies", {}).values():
        declared += group
    for group in data.get("dependency-groups", {}).values():
        declared += [g for g in group if isinstance(g, str)]
    names = {_norm(re.split(r"[<>=!~\[; ]", d, maxsplit=1)[0]) for d in declared}
    forbidden = {_norm(n) for n in FORBIDDEN_DISTRIBUTIONS}
    assert not (names & forbidden), names & forbidden
    assert not {n for n in names if n.startswith("opentelemetry")}


def test_nfr4_app_sources_have_no_analytics_urls() -> None:
    offenders: list[str] = []
    for path in (BACKEND_DIR / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        for host in ANALYTICS_HOSTS:
            if host in text:
                offenders.append(f"{path.relative_to(BACKEND_DIR)}: {host}")
    assert not offenders, offenders


@pytest.mark.asyncio
async def test_nfr4_app_startup_and_request_open_no_network_connections(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """create_app + lifespan + GET /api/v1/health без БД не открывают сетевых соединений."""
    attempts: list[Any] = []

    def refuse(*args: Any, **_kwargs: Any) -> Any:
        attempts.append(args)
        raise AssertionError("сетевое обращение запрещено (NFR-4)")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)

    from app.main import create_app

    settings = Settings(
        env="test",
        database_url="postgresql+asyncpg://nobody:pw@127.0.0.1:1/none_test",
        data_dir=tmp_path / "data",
        cookie_secure=False,
        secret_key=None,
        argon2_time_cost=1,
        argon2_memory_cost_kib=1024,
        argon2_parallelism=1,
    )
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert attempts == []
