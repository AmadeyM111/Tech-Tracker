"""Первый запуск: пространство и первый техадминистратор (plan §4.7, FR-6, D-9, D-19).

``run_bootstrap`` выполняется под ``pg_advisory_lock`` (соединение AUTOCOMMIT, не «idle in
transaction»): на чистой установке создаёт
пространство, первого ТА (роль ``tech_admin``, ``must_change_password``, автор «система») и
записывает случайный пароль в ``secrets_dir/initial-admin-password.txt`` (0600). В БД хранится
только Argon2id-хеш. Событий аудита первый запуск не пишет (D-9, FR-41).

Порядок записи: сгенерировать пароль → вставить строки → записать файл → зафиксировать
транзакцию. При ошибке фиксации отдельной сессией проверяется, не зафиксировано ли
пространство: если да, файл остаётся (пароль в БД действует), иначе файл удаляется (до
освобождения блокировки).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator, Callable
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
from app.domain.auth.provider import normalize_login
from app.domain.users.models import AppUser
from app.domain.workspaces.models import Workspace, WorkspaceMember

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

INITIAL_ADMIN_FILE: Final = "initial-admin-password.txt"

# bigint-константа блокировки первого запуска (ASCII «GOST» + номер)
_BOOTSTRAP_LOCK_KEY: Final = 0x474F535400000001


class BootstrapLock:
    """Токен «блокировка первого запуска удерживается»: выдаётся только ``bootstrap_lock``.

    Передаётся в ``run_bootstrap(locked=token)``; голый ``True`` не принимается. После выхода
    из контекста блокировки токен недействителен.
    """

    __slots__ = ("active",)

    def __init__(self) -> None:
        self.active = True


@dataclass(frozen=True)
class BootstrapResult:
    workspace_id: UUID
    admin_created: bool


def _initial_login(settings: Settings) -> tuple[str, str]:
    """Логин первого ТА: ``(ключ, написание из настройки)`` (FR-73, FR-73a, OI-130).

    Ключ — тот же разбор, что при входе и создании (``normalize_login``); показ и файл пароля —
    в написании, заданном в ``INITIAL_ADMIN_LOGIN``.
    """
    login = normalize_login(settings.initial_admin_login)
    if login is None:
        # значение не включаем: сообщение должно быть безопасным для логов
        raise ValueError("INITIAL_ADMIN_LOGIN не соответствует шаблону логина (FR-73)")
    return login, settings.initial_admin_login


def _discard_file(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink()


def _remove_stale_tmp_files(directory: Path) -> None:
    """Удаляет ``.<файл пароля>.*.tmp`` от прерванных запусков (в них лежит пароль).

    Вызывается под блокировкой первого запуска, поэтому чужих «живых» временных файлов нет.
    Посторонние файлы не трогаются.
    """
    prefix = f".{INITIAL_ADMIN_FILE}."
    try:
        entries = list(os.scandir(directory))
    except FileNotFoundError:
        return
    for entry in entries:
        name = entry.name
        if name.startswith(prefix) and name.endswith(".tmp") and len(name) > len(prefix) + 4:
            with contextlib.suppress(OSError):
                os.unlink(entry.path)


async def _workspace_committed(
    sessionmaker: async_sessionmaker[AsyncSession], workspace_id: UUID
) -> bool | None:
    """Зафиксировано ли пространство: отдельная сессия, отдельное соединение.

    ``None`` — проверить не удалось (БД недоступна): исход фиксации неизвестен.
    """
    try:
        async with sessionmaker() as check:
            found = (
                await check.execute(select(Workspace.id).where(Workspace.id == workspace_id))
            ).scalar_one_or_none()
    except Exception:
        return None
    return found is not None


async def _create_first_admin(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    generate: Callable[[], str],
) -> BootstrapResult:
    path = settings.secrets_dir / INITIAL_ADMIN_FILE
    _remove_stale_tmp_files(settings.secrets_dir)
    file_written = False
    workspace_id: UUID | None = None
    try:
        async with sessionmaker() as session, session.begin():
            existing = (
                await session.execute(
                    select(Workspace.id).order_by(Workspace.created_at, Workspace.id).limit(1)
                )
            ).scalar_one_or_none()
            if existing is not None:
                return BootstrapResult(workspace_id=existing, admin_created=False)

            login, login_display = _initial_login(settings)
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
                login_display=login_display,
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
            workspace_id = workspace.id

            ensure_private_dir(settings.secrets_dir)
            # пространства нет, а файл есть: остаток прерванного запуска, пароль нигде не
            # действует; блокировка не даёт другому запуску создать файл параллельно
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
            write_private_file(path, f"login={login_display}\npassword={password}\n")
            file_written = True
        # здесь выполнена фиксация транзакции (выход из session.begin())
    except Exception:
        if not file_written or workspace_id is None:
            raise
        # COMMIT мог дойти до БД, а подтверждение потеряться (обрыв соединения): тогда пароль
        # в БД действует, и файл удалять нельзя (иначе пароль потерян). Проверяем отдельной
        # сессией; исход неизвестен (БД недоступна) - файл остаётся: при следующем запуске он
        # либо действует (пространство есть), либо перезаписывается как остаток.
        committed = await _workspace_committed(sessionmaker, workspace_id)
        if committed:
            return BootstrapResult(workspace_id=workspace_id, admin_created=True)
        if committed is False:
            _discard_file(path)
        raise
    return BootstrapResult(workspace_id=workspace_id, admin_created=True)


@contextlib.asynccontextmanager
async def bootstrap_lock(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[BootstrapLock]:
    """Сессионная ``pg_advisory_lock`` первого запуска на отдельном AUTOCOMMIT-соединении.

    Соединение в режиме AUTOCOMMIT: между запросами оно ``idle``, а не «idle in transaction»,
    поэтому ``idle_in_transaction_session_timeout`` сервера не разрывает его во время миграций
    (заметка T16). Блокировка удерживается до выхода из контекста: ею накрывается вся
    последовательность «миграции + первый запуск» (ревью T10), а не только создание ТА.

    Отдаёт токен ``BootstrapLock``; внутри контекста ``run_bootstrap`` вызывается с
    ``locked=token`` (повторное взятие на другом соединении заблокировало бы процесс самим собой).
    """
    token = BootstrapLock()
    async with sessionmaker() as lock_session:
        connection = await lock_session.connection(
            execution_options={"isolation_level": "AUTOCOMMIT"}
        )
        # Серверный lock_timeout (plan §4.12, решения T26) не должен обрывать ожидание: второй
        # экземпляр bootstrap ждёт освобождения блокировки (plan §4.7).
        await connection.execute(text("SET lock_timeout = 0"))
        await connection.execute(
            text("SELECT pg_advisory_lock(:key)"), {"key": _BOOTSTRAP_LOCK_KEY}
        )
        try:
            yield token
        finally:
            token.active = False
            try:
                await connection.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": _BOOTSTRAP_LOCK_KEY}
                )
            except BaseException:
                # соединение закрывается: блокировка снимается сервером, в пул не вернётся
                await lock_session.invalidate()
                raise


async def run_bootstrap(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    clock: Clock,
    generate: Callable[[], str] = generate_password,
    locked: BootstrapLock | None = None,
) -> BootstrapResult:
    """Идемпотентная инициализация чистой установки (plan §4.7).

    Блокировка сессионная (``pg_advisory_lock``) на отдельном соединении: она удерживается
    до удаления файла при неудачной фиксации, поэтому параллельный запуск не увидит
    полузавершённое состояние. ``locked`` — токен от ``bootstrap_lock``: вызывающий уже держит
    блокировку. Без токена блокировку берёт сама функция. Голый ``True`` не принимается.
    """
    if locked is not None:
        if not isinstance(locked, BootstrapLock):
            raise TypeError("locked принимает только токен, выданный bootstrap_lock")
        if not locked.active:
            raise ValueError("блокировка первого запуска уже снята")
        with use_clock(clock):
            return await _create_first_admin(sessionmaker, settings, generate)
    async with bootstrap_lock(sessionmaker):
        with use_clock(clock):
            return await _create_first_admin(sessionmaker, settings, generate)


def remove_initial_admin_file_if_for(settings: Settings, login: str) -> None:
    """Удаляет файл пароля первого ТА, если он выдан этому логину (FR-6, ADR-0004).

    Файла нет — ничего не делает. Файл другого логина не трогается. Содержимое файла не
    попадает в исключения. Сравнение без учёта регистра с обеих сторон: вызывающий передаёт
    ``Actor.login`` (отображаемый логин), а в файле — написание из настройки (в установках до
    миграции 0005 — строчное), FR-73a.
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
    if owner is not None and owner.lower() == login.strip().lower():
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
