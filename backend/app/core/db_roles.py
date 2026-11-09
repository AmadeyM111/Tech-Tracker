"""Рабочая роль БД процесса API (spec 010 FR-1…FR-4; plan PR-1…PR-5).

Владелец схемы — роль из ``DATABASE_URL`` (миграции, bootstrap, команды оператора). Процесс API
подключается под ``DB_APP_ROLE``: без SUPERUSER, CREATEDB, CREATEROLE и владения объектами; на
``domain_event`` — только SELECT и INSERT. Пароль роли — файл ``DATA_DIR/secrets/db_app_password``
(0600); на сервер уходит только SCRAM-SHA-256-верификатор (PR-3). Пароль не попадает в логи и
тексты исключений.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import re
import secrets
from pathlib import Path
from typing import TYPE_CHECKING, Final

from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.core.secrets import ensure_private_dir, write_private_file

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

APP_PASSWORD_FILE: Final = "db_app_password"
PASSWORD_BYTES: Final = 32
SCRAM_ITERATIONS: Final = 4096
ROLE_RE: Final = re.compile(r"[a-z_][a-z0-9_]{0,62}")
# Таблицы с урезанными правами рабочей роли (FR-2).
APPEND_ONLY: Final = ("domain_event",)
# backup_run пишет только CLI оператора (владелец схемы); API читает статус для ТА (ревью 010).
READ_ONLY: Final = ("alembic_version", "backup_run")


class AppRoleError(RuntimeError):
    """Неверная настройка рабочей роли; текст без паролей."""


def check_role_name(role: str) -> str:
    if ROLE_RE.fullmatch(role) is None:
        raise AppRoleError("DB_APP_ROLE: допустимы a-z, 0-9 и _, до 63 символов")
    return role


def app_password_path(settings: Settings) -> Path:
    return settings.secrets_dir / APP_PASSWORD_FILE


def ensure_app_password(settings: Settings) -> str:
    """Пароль рабочей роли: читает файл или создаёт его (0600) при первом запуске."""
    path = app_password_path(settings)
    ensure_private_dir(settings.secrets_dir)
    if not path.exists():
        # FileExistsError: параллельный bootstrap успел раньше
        with contextlib.suppress(FileExistsError):
            write_private_file(path, secrets.token_urlsafe(PASSWORD_BYTES))
    return read_app_password(settings)


def read_app_password(settings: Settings) -> str:
    path = app_password_path(settings)
    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        raise AppRoleError(
            f"нет файла пароля рабочей роли БД ({path}): выполните gtrack bootstrap"
        ) from None
    if len(value) < 32:
        raise AppRoleError(f"файл пароля рабочей роли БД повреждён: {path}")
    return value


def scram_verifier(
    password: str, *, salt: bytes | None = None, iterations: int = SCRAM_ITERATIONS
) -> str:
    """Верификатор SCRAM-SHA-256 в формате ``pg_authid.rolpassword`` (RFC 5802/7677)."""
    salt = secrets.token_bytes(16) if salt is None else salt
    salted = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()

    def b64(raw: bytes) -> str:
        return base64.b64encode(raw).decode("ascii")

    return f"SCRAM-SHA-256${iterations}:{b64(salt)}${b64(stored_key)}:{b64(server_key)}"


async def ensure_app_role(conn: AsyncConnection, role: str, verifier: str) -> None:
    """Создаёт роль или приводит её к FR-1 и выдаёт права FR-2 (идемпотентно).

    Выполняется владельцем схемы в его транзакции. Имя роли проверено ``check_role_name``;
    верификатор — литерал из ``scram_verifier`` (без кавычек и обратных слешей).
    """
    check_role_name(role)
    if not verifier.startswith("SCRAM-SHA-256$") or "'" in verifier or "\\" in verifier:
        raise AppRoleError("неверный верификатор пароля")
    exists = (
        await conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role})
    ).scalar()
    attrs = "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT"
    verb = "ALTER" if exists else "CREATE"
    try:
        # exec_driver_sql: «:» верификатора не разбирается как параметр; текст ошибки не выводится
        await conn.exec_driver_sql(f"{verb} ROLE {role} WITH {attrs} PASSWORD '{verifier}'")
    except Exception as exc:
        raise AppRoleError(f"не удалось {verb.lower()} роль {role}: {type(exc).__name__}") from None
    database = (await conn.execute(text("SELECT current_database()"))).scalar_one()
    await conn.execute(text(f'GRANT CONNECT ON DATABASE "{database}" TO {role}'))
    await conn.execute(text(f"REVOKE CREATE ON SCHEMA public FROM {role}"))
    await conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
    await conn.execute(text(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}"))
    await conn.execute(
        text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}")
    )
    for table in APPEND_ONLY:
        await conn.execute(text(f"REVOKE UPDATE, DELETE ON {table} FROM {role}"))
    for table in READ_ONLY:
        await conn.execute(text(f"REVOKE INSERT, UPDATE, DELETE ON {table} FROM {role}"))
    await conn.execute(text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role}"))


def app_database_url(settings: Settings) -> str:
    """DSN процесса API: ``DATABASE_URL`` с пользователем ``DB_APP_ROLE`` и его паролем."""
    if settings.db_app_role is None:
        if settings.env == "production":
            raise AppRoleError(
                "DB_APP_ROLE не задан: API в production не работает под владельцем БД"
            )
        return settings.database_url
    role = check_role_name(settings.db_app_role)
    url = make_url(settings.database_url).set(username=role, password=read_app_password(settings))
    return url.render_as_string(hide_password=False)
