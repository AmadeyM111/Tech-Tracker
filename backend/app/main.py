"""Точка входа API: фабрика приложения (plan §4.2, D-32)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api.deps import check_origin
from app.api.mcp.endpoint import McpEndpoint
from app.api.mcp.server import McpRuntime, build_session_manager
from app.api.mcp.tools import default_registry
from app.api.v1 import router as api_v1_router
from app.api.wellknown import router as wellknown_router
from app.core.clock import Clock, SystemClock, use_clock
from app.core.config import Settings, get_settings
from app.core.db import create_engine
from app.core.db_roles import app_database_url
from app.core.errors import install_error_handlers
from app.core.logging import AccessLogMiddleware, configure_logging
from app.core.mail import SmtpMailer
from app.core.secrets import ensure_secret_key
from app.core.security.passwords import PasswordHasher
from app.domain.auth.password_reset import ResetPolicy
from app.domain.auth.provider import LocalPasswordProvider
from app.domain.auth.registration import RegistrationPolicy
from app.domain.auth.sessions import SessionStore


class ClockMiddleware:
    """Чистый ASGI-middleware: на каждый запрос берёт ``app.state.clock`` и ставит ``use_clock``."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        with use_clock(scope["app"].state.clock):
            await self.app(scope, receive, send)


def _operation_id(route: APIRoute) -> str:
    return route.name


@asynccontextmanager
async def _lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Общие объекты живут от старта до остановки приложения (plan §4.2, §4.6).

    Секретный ключ короче 32 байт роняет запуск (``SessionStore``). К БД lifespan не
    обращается: движок подключается лениво, миграции и первый запуск — команда ``bootstrap``.
    """
    settings: Settings = application.state.settings
    state = application.state
    state.session_store = SessionStore(
        ensure_secret_key(settings),
        idle_timeout=settings.session_idle_timeout,
        absolute_timeout=settings.session_absolute_timeout,
    )
    state.password_hasher = PasswordHasher(
        time_cost=settings.argon2_time_cost,
        memory_cost_kib=settings.argon2_memory_cost_kib,
        parallelism=settings.argon2_parallelism,
    )
    state.auth_provider = LocalPasswordProvider(
        state.password_hasher,
        max_failures=settings.login_max_failures,
        lock_duration=settings.login_lock_duration,
    )
    if settings.password_reset_enabled:
        if settings.public_base_url is None:
            raise RuntimeError(
                "Сброс пароля включён (SMTP_HOST задан), но PUBLIC_BASE_URL не задан"
            )
        state.mailer = SmtpMailer(settings)
        state.password_reset_policy = ResetPolicy(
            base_url=settings.public_base_url, limit_key=ensure_secret_key(settings)
        )
        state.registration_policy = RegistrationPolicy(
            base_url=settings.public_base_url, limit_key=ensure_secret_key(settings)
        )
    else:
        state.mailer = None
        state.password_reset_policy = None
        state.registration_policy = None
    # spec 010: процесс API — под рабочей ролью БД (DB_APP_ROLE), не под владельцем схемы
    engine = create_engine(settings, url=app_database_url(settings))
    application.state.engine = engine
    application.state.sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with application.state.mcp_runtime:
            yield
    finally:
        await engine.dispose()


def create_app(settings: Settings | None = None, *, clock: Clock | None = None) -> FastAPI:
    """Собирает приложение. Подключений к БД и сети не открывает."""
    settings = settings if settings is not None else get_settings()
    configure_logging(settings.log_level)
    docs = settings.expose_api_docs
    application = FastAPI(
        title="Tracker API",
        version="0.0.1",
        debug=False,
        lifespan=_lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
        generate_unique_id_function=_operation_id,
        dependencies=[Depends(check_origin)],  # D-16: CSRF для небезопасных методов
    )
    application.state.settings = settings
    application.state.clock = clock if clock is not None else SystemClock()
    application.add_middleware(ClockMiddleware)
    # добавлен последним — внешний слой: длительность включает остальные middleware
    application.add_middleware(AccessLogMiddleware)
    install_error_handlers(application)
    application.include_router(api_v1_router)
    application.include_router(wellknown_router)  # /.well-known/* (OAuth, спека 028)
    # MCP для AI-агентов (ADR-0018): реестр инструментов и протокольный слой на /mcp
    application.state.mcp_registry = default_registry()
    session_manager = build_session_manager()
    application.state.mcp_runtime = McpRuntime(session_manager)
    # ASGI-приложение как endpoint: Starlette передаёт не-функции без обёртки (типы этого не видят)
    application.add_route(
        "/mcp",
        McpEndpoint(session_manager),  # type: ignore[arg-type]
        methods=["GET", "POST", "DELETE"],
        include_in_schema=False,
    )
    return application


app = create_app()
