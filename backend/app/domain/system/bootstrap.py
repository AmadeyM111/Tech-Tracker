"""Первый запуск: пространство и первый техадминистратор (plan §4.7, FR-6, D-9, D-19).

``run_bootstrap`` выполняется под ``pg_advisory_lock``: на чистой установке создаёт
пространство, первого ТА (роль ``tech_admin``, ``must_change_password``, автор «система») и
записывает случайный пароль в ``secrets_dir/initial-admin-password.txt`` (0600). В БД хранится
только Argon2id-хеш. Событий аудита первый запуск не пишет (D-9, FR-41).

Порядок записи: сгенерировать пароль → вставить строки → записать файл → зафиксировать
транзакцию; при ошибке фиксации файл удаляется (до освобождения блокировки).
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Final
from uuid import UUID

from sqlalchemy import select, text

from app.core.clock import Clock, use_clock
from app.core.config import Settings
from app.core.secrets import ensure_private_dir, write_private_file
from app.core.security.passwords import PasswordHasher, generate_password, hash_in_thread
from app.domain.users.models import AppUser
from app.domain.workspaces.models import Workspace, WorkspaceMember

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

INITIAL_ADMIN_FILE: Final = "initial-admin-password.txt"

# bigint-константа блокировки первого запуска (ASCII «GOST» + номер)
_BOOTSTRAP_LOCK_KEY: Final = 0x474F535400000001
# FR-73 / D-39: тот же шаблон, что в CHECK таблицы app_user
_LOGIN_RE: Final = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")


@dataclass(frozen=True)
class BootstrapResult:
    workspace_id: UUID
    admin_created: bool


def _initial_login(settings: Settings) -> str:
    """Логин первого ТА: приводится к нижнему регистру и проверяется по FR-73."""
    login = settings.initial_admin_login.strip().lower()
    if _LOGIN_RE.fullmatch(login) is None:
        # значение не включаем: сообщение должно быть безопасным для логов
        raise ValueError("INITIAL_ADMIN_LOGIN не соответствует шаблону логина (FR-73)")
    return login


def _discard_file(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink()


async def _create_first_admin(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    generate: Callable[[], str],
) -> BootstrapResult:
    path = settings.secrets_dir / INITIAL_ADMIN_FILE
    file_written = False
    async with sessionmaker() as session:
        try:
            async with session.begin():
                existing = (
                    await session.execute(
                        select(Workspace.id).order_by(Workspace.created_at, Workspace.id).limit(1)
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    return BootstrapResult(workspace_id=existing, admin_created=False)

                login = _initial_login(settings)
                password = generate()
                hasher = await asyncio.to_thread(
                    partial(
                        PasswordHasher,
                        time_cost=settings.argon2_time_cost,
                        memory_cost_kib=settings.argon2_memory_cost_kib,
                        parallelism=settings.argon2_parallelism,
                    )
                )
                password_hash = await hash_in_thread(hasher, password)

                workspace = Workspace()
                session.add(workspace)
                await session.flush()
                user = AppUser(
                    login=login,
                    password_hash=password_hash,
                    must_change_password=True,
                    is_blocked=False,
                    created_by=None,
                )
                session.add(user)
                await session.flush()
                session.add(
                    WorkspaceMember(
                        workspace_id=workspace.id,
                        user_id=user.id,
                        role="tech_admin",
                        created_by=None,
                    )
                )
                await session.flush()

                ensure_private_dir(settings.secrets_dir)
                # пространства нет, а файл есть: остаток прерванного запуска, пароль нигде не
                # действует; блокировка не даёт другому запуску создать файл параллельно
                with contextlib.suppress(FileNotFoundError):
                    path.unlink()
                write_private_file(path, f"login={login}\npassword={password}\n")
                file_written = True
                workspace_id = workspace.id
            # здесь выполнена фиксация транзакции (выход из session.begin())
        except BaseException:
            if file_written:
                _discard_file(path)
            raise
    return BootstrapResult(workspace_id=workspace_id, admin_created=True)


async def run_bootstrap(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    clock: Clock,
    generate: Callable[[], str] = generate_password,
) -> BootstrapResult:
    """Идемпотентная инициализация чистой установки (plan §4.7).

    Блокировка сессионная (``pg_advisory_lock``) на отдельном соединении: она удерживается
    до удаления файла при неудачной фиксации, поэтому параллельный запуск не увидит
    полузавершённое состояние.
    """
    async with sessionmaker() as lock_session:
        await lock_session.execute(
            text("SELECT pg_advisory_lock(:key)"), {"key": _BOOTSTRAP_LOCK_KEY}
        )
        try:
            with use_clock(clock):
                return await _create_first_admin(sessionmaker, settings, generate)
        finally:
            try:
                await lock_session.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": _BOOTSTRAP_LOCK_KEY}
                )
            except BaseException:
                # соединение закрывается: блокировка снимается сервером, в пул не вернётся
                await lock_session.invalidate()
                raise


def remove_initial_admin_file_if_for(settings: Settings, login: str) -> None:
    """Удаляет файл пароля первого ТА, если он выдан этому логину (FR-6, ADR-0004).

    Файла нет — ничего не делает. Файл другого логина не трогается. Содержимое файла не
    попадает в исключения.
    """
    path = settings.secrets_dir / INITIAL_ADMIN_FILE
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return  # не наш файл
    owner = next((ln.partition("=")[2].strip() for ln in lines if ln.startswith("login=")), None)
    if owner is not None and owner == login.strip().lower():
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
