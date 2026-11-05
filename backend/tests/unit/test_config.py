"""Юнит-тесты app.core.config (plan §4.2, T03; NFR-5, FR-46)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

SETTINGS_FIELDS = (
    "env",
    "database_url",
    "data_dir",
    "secret_key",
    "cookie_secure",
    "cookie_name",
    "session_idle_timeout",
    "session_absolute_timeout",
    "login_max_failures",
    "login_lock_duration",
    "argon2_time_cost",
    "argon2_memory_cost_kib",
    "argon2_parallelism",
    "expose_api_docs",
    "log_level",
    "initial_admin_login",
    "attachment_max_bytes",
    "attachments_per_task",
    "trash_retention",
    "smtp_host",
    "smtp_port",
    "smtp_user",
    "smtp_password",
    "smtp_from",
    "smtp_starttls",
    "public_base_url",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Окружение без переменных Settings и рабочий каталог без .env."""
    for name in list(os.environ):
        if name.lower() in SETTINGS_FIELDS:
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
    yield


@pytest.fixture
def config() -> Any:
    from app.core import config as module

    module.get_settings.cache_clear()
    yield module
    module.get_settings.cache_clear()


def test_nfr5_defaults_match_plan(config: Any) -> None:
    s = config.Settings()
    assert s.env == "production"
    assert s.database_url == "postgresql+asyncpg://tracker:tracker@localhost:5432/tracker"
    assert s.data_dir == Path("/data")
    assert s.secret_key is None
    assert s.cookie_secure is True
    assert s.cookie_name == "gt_session"
    assert s.session_idle_timeout == timedelta(hours=8)
    assert s.session_absolute_timeout == timedelta(days=7)
    assert s.login_max_failures == 5
    assert s.login_lock_duration == timedelta(minutes=15)
    assert s.argon2_time_cost == 3
    assert s.argon2_memory_cost_kib == 131072
    assert s.argon2_parallelism == 2
    assert s.expose_api_docs is False
    assert s.log_level == "INFO"
    assert s.initial_admin_login == "admin"
    assert s.attachment_max_bytes == 10 * 1024 * 1024 == 10_485_760
    assert s.attachments_per_task == 20
    assert s.trash_retention == timedelta(days=30)


def test_nfr5_cookie_secure_true_by_default(config: Any) -> None:
    assert config.Settings().cookie_secure is True


def test_nfr5_derived_dirs_under_data_dir(config: Any, tmp_path: Path) -> None:
    s = config.Settings(data_dir=tmp_path / "d")
    assert s.secrets_dir == tmp_path / "d" / "secrets"
    assert s.attachments_dir == tmp_path / "d" / "attachments"
    assert s.exports_dir == tmp_path / "d" / "exports"


def test_nfr5_reads_environment_variables(
    config: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("LOGIN_MAX_FAILURES", "9")
    monkeypatch.setenv("EXPOSE_API_DOCS", "true")
    monkeypatch.setenv("SESSION_IDLE_TIMEOUT", "3600")
    monkeypatch.setenv("SECRET_KEY", "s3cret-value")
    s = config.Settings()
    assert s.cookie_secure is False
    assert s.env == "test"
    assert s.data_dir == tmp_path / "data"
    assert s.login_max_failures == 9
    assert s.expose_api_docs is True
    assert s.session_idle_timeout == timedelta(hours=1)
    assert s.secret_key is not None
    assert s.secret_key.get_secret_value() == "s3cret-value"


def test_nfr5_env_names_are_case_insensitive(config: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("cookie_name", "other_cookie")
    assert config.Settings().cookie_name == "other_cookie"


def test_nfr5_dotenv_file_is_not_read(config: Any, tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("COOKIE_SECURE=false\nCOOKIE_NAME=from_dotenv\n")
    s = config.Settings()
    assert s.cookie_secure is True
    assert s.cookie_name == "gt_session"


def test_nfr5_secret_key_is_masked_in_repr(config: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "very-secret-token")
    s = config.Settings()
    assert "very-secret-token" not in repr(s)
    assert "very-secret-token" not in str(s)


def test_nfr5_invalid_env_value_is_rejected(config: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "staging")
    with pytest.raises(ValueError):
        config.Settings()


def test_nfr5_get_settings_is_cached(config: Any) -> None:
    assert config.get_settings() is config.get_settings()


def test_nfr5_get_settings_cache_clear_rereads_environment(
    config: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = config.get_settings()
    assert first.cookie_name == "gt_session"
    monkeypatch.setenv("COOKIE_NAME", "changed")
    assert config.get_settings().cookie_name == "gt_session"  # кеш
    config.get_settings.cache_clear()
    assert config.get_settings().cookie_name == "changed"


# --- 007 (R7-T02): SMTP и PUBLIC_BASE_URL, plan §4.2, PR-10 -----------------------------

_SMTP_NONE_FIELDS = ("smtp_host", "smtp_user", "smtp_password", "smtp_from", "public_base_url")


def test_007_fr3_defaults_feature_disabled(config: Any) -> None:
    s = config.Settings()
    for name in _SMTP_NONE_FIELDS:
        assert getattr(s, name) is None, name
    assert s.smtp_port == 587
    assert s.smtp_starttls is True
    assert s.password_reset_enabled is False


def test_007_fr3_reads_environment_variables(config: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMTP_HOST", "smtp.example.ru")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("SMTP_USER", "mailer")
    monkeypatch.setenv("SMTP_PASSWORD", "p4ss-value")
    monkeypatch.setenv("SMTP_FROM", "noreply@example.ru")
    monkeypatch.setenv("SMTP_STARTTLS", "false")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://tracker.example.ru:8443")
    s = config.Settings()
    assert s.smtp_host == "smtp.example.ru"
    assert s.smtp_port == 2525
    assert s.smtp_user == "mailer"
    assert s.smtp_password is not None
    assert s.smtp_password.get_secret_value() == "p4ss-value"
    assert s.smtp_from == "noreply@example.ru"
    assert s.smtp_starttls is False
    assert s.public_base_url == "https://tracker.example.ru:8443"
    assert s.password_reset_enabled is True


@pytest.mark.parametrize("blank", ["", "   ", "\t "])
def test_007_fr3_blank_strings_become_none(
    config: Any, monkeypatch: pytest.MonkeyPatch, blank: str
) -> None:
    for name in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM", "PUBLIC_BASE_URL"):
        monkeypatch.setenv(name, blank)
    s = config.Settings()
    for name in _SMTP_NONE_FIELDS:
        assert getattr(s, name) is None, name
    assert s.password_reset_enabled is False


def test_007_fr3_blank_user_with_host_means_no_login(
    config: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SMTP_HOST", "smtp.example.ru")
    monkeypatch.setenv("SMTP_FROM", "noreply@example.ru")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://t.example.ru")
    monkeypatch.setenv("SMTP_USER", "")
    monkeypatch.setenv("SMTP_PASSWORD", "")
    s = config.Settings()
    assert s.smtp_user is None
    assert s.smtp_password is None
    assert s.password_reset_enabled is True


def test_007_fr3_smtp_password_is_masked_in_repr(
    config: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SMTP_PASSWORD", "smtp-very-secret")
    s = config.Settings()
    assert "smtp-very-secret" not in repr(s)
    assert "smtp-very-secret" not in str(s)


@pytest.mark.parametrize("missing", ["SMTP_FROM", "PUBLIC_BASE_URL"])
def test_007_pr10_host_without_required_field_fails_fast(
    config: Any, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    env = {
        "SMTP_HOST": "smtp.example.ru-host-value",
        "SMTP_FROM": "noreply@example.ru",
        "PUBLIC_BASE_URL": "https://t.example.ru",
        "SMTP_PASSWORD": "leaky-password-value",
    }
    del env[missing]
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(ValueError) as info:
        config.Settings()
    text = str(info.value)
    assert missing.lower() in text.lower()
    for value in env.values():
        assert value not in text


@pytest.mark.parametrize("blank_name", ["SMTP_FROM", "PUBLIC_BASE_URL"])
def test_007_pr10_blank_required_field_with_host_fails_fast(
    config: Any, monkeypatch: pytest.MonkeyPatch, blank_name: str
) -> None:
    monkeypatch.setenv("SMTP_HOST", "smtp.example.ru")
    monkeypatch.setenv("SMTP_FROM", "noreply@example.ru")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://t.example.ru")
    monkeypatch.setenv(blank_name, "  ")
    with pytest.raises(ValueError):
        config.Settings()


def test_007_pr10_from_and_base_url_without_host_is_allowed(
    config: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SMTP_FROM", "noreply@example.ru")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://t.example.ru")
    s = config.Settings()
    assert s.password_reset_enabled is False


@pytest.mark.parametrize(
    "url",
    [
        "https://tracker.example.ru",
        "http://localhost:8080",
        "http://127.0.0.1:5173",
        "https://t.example.ru:8443",
    ],
)
def test_007_pr10_public_base_url_valid(
    config: Any, monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("PUBLIC_BASE_URL", url)
    assert config.Settings().public_base_url == url


@pytest.mark.parametrize(
    "url",
    [
        "https://t.example.ru/",
        "https://t.example.ru/app",
        "tracker.example.ru",
        "ftp://t.example.ru",
        "https://",
        "https://t.example .ru",
        "javascript:alert(1)",
    ],
)
def test_007_pr10_public_base_url_invalid_is_rejected(
    config: Any, monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("PUBLIC_BASE_URL", url)
    with pytest.raises(ValueError):
        config.Settings()
