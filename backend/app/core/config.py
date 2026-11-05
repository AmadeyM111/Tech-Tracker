"""Настройки приложения (plan §4.2, NFR-5).

Источник значений — только переменные окружения процесса. Файл ``.env`` не читается,
префикса у имён нет; имена переменных совпадают с именами полей, регистр не важен.
"""

from __future__ import annotations

import re
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BASE_URL_RE = re.compile(r"https?://[^/\s]+")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
        # значения (в т.ч. SMTP_PASSWORD) не попадают в тексты ошибок валидации
        hide_input_in_errors=True,
    )

    env: Literal["production", "local", "test"] = "production"
    # dev-умолчание; compose задаёт явно
    database_url: str = "postgresql+asyncpg://tracker:tracker@localhost:5432/tracker"
    data_dir: Path = Path("/data")
    # пусто → файл data_dir/secrets/secret_key
    secret_key: SecretStr | None = None
    cookie_secure: bool = True
    cookie_name: str = "gt_session"
    session_idle_timeout: timedelta = timedelta(hours=8)
    session_absolute_timeout: timedelta = timedelta(days=7)
    login_max_failures: int = 5
    login_lock_duration: timedelta = timedelta(minutes=15)
    argon2_time_cost: int = 3
    argon2_memory_cost_kib: int = 131072
    argon2_parallelism: int = 2
    expose_api_docs: bool = False
    log_level: str = "INFO"
    initial_admin_login: str = "admin"
    attachment_max_bytes: int = 10 * 1024 * 1024  # 10 485 760, включительно
    attachments_per_task: int = 20
    trash_retention: timedelta = timedelta(days=30)
    # [007] отправка писем; без smtp_host функция сброса пароля выключена
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str | None = None
    smtp_starttls: bool = True
    public_base_url: str | None = None

    @field_validator(
        "session_idle_timeout",
        "session_absolute_timeout",
        "login_lock_duration",
        "trash_retention",
        mode="before",
    )
    @classmethod
    def _seconds_from_env(cls, value: Any) -> Any:
        """Переменная окружения — строка: целое число секунд превращаем в число."""
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                return value
        return value

    @field_validator(
        "smtp_host",
        "smtp_user",
        "smtp_password",
        "smtp_from",
        "public_base_url",
        mode="before",
    )
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        """Пустая строка или одни пробелы в переменной окружения означают «не задано»."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("public_base_url")
    @classmethod
    def _check_public_base_url(cls, value: str | None) -> str | None:
        if value is not None and _BASE_URL_RE.fullmatch(value) is None:
            raise ValueError("public_base_url must look like http(s)://host[:port] without a path")
        return value

    @model_validator(mode="after")
    def _smtp_requires_sender_and_base_url(self) -> Settings:
        """Fail Fast: задан smtp_host, но нет обязательных smtp_from/public_base_url (PR-10)."""
        if self.smtp_host is not None:
            missing = [
                name for name in ("smtp_from", "public_base_url") if getattr(self, name) is None
            ]
            if missing:
                raise ValueError(
                    f"smtp_host is set but required settings are missing: {', '.join(missing)}"
                )
        return self

    @property
    def password_reset_enabled(self) -> bool:
        return self.smtp_host is not None

    @property
    def secrets_dir(self) -> Path:
        return self.data_dir / "secrets"

    @property
    def attachments_dir(self) -> Path:
        return self.data_dir / "attachments"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"


@lru_cache
def get_settings() -> Settings:
    return Settings()
