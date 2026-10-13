"""Точка входа API: фабрика приложения (plan §4.2, D-32)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api.v1 import router as api_v1_router
from app.core.clock import Clock, SystemClock, use_clock
from app.core.config import Settings, get_settings
from app.core.db import create_engine
from app.core.errors import install_error_handlers
from app.core.logging import AccessLogMiddleware, configure_logging


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
    """Движок и фабрика сессий живут от старта до остановки приложения (plan §4.2)."""
    settings: Settings = application.state.settings
    engine = create_engine(settings)
    application.state.engine = engine
    application.state.sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
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
    )
    application.state.settings = settings
    application.state.clock = clock if clock is not None else SystemClock()
    application.add_middleware(ClockMiddleware)
    # добавлен последним — внешний слой: длительность включает остальные middleware
    application.add_middleware(AccessLogMiddleware)
    install_error_handlers(application)
    application.include_router(api_v1_router)
    return application


app = create_app()
