"""R8-T14: AC-32 (spec 019, FR-1, Q10, Q12) — у настроек нет отдельного выключателя регистрации
и списков допуска.

Регистрация включается тем же условием, что сброс пароля (SMTP настроен; ``password_reset_enabled``
— свойство, а не поле), поэтому в ``Settings.model_fields`` не должно появиться имён, которые
описывают выключатель или допуск. Код настроек в этой задаче не меняется.
"""

from __future__ import annotations

from app.core.config import Settings

# Части имён, которыми назвали бы выключатель регистрации или список допуска (plan §6, AC-32).
FORBIDDEN_NAME_PARTS = ("regist", "allow", "list", "domain", "pilot", "captcha")


def test_019_ac32_no_field_names_for_registration_switch_or_allowlist() -> None:
    offending = sorted(
        name
        for name in Settings.model_fields
        if any(part in name.lower() for part in FORBIDDEN_NAME_PARTS)
    )
    assert offending == []


def test_019_ac32_no_separate_feature_flag_field() -> None:
    """Единственный признак функции — свойство ``password_reset_enabled`` (SMTP настроен)."""
    flags = sorted(
        name
        for name in Settings.model_fields
        if "enable" in name.lower() or name.lower().startswith("feature")
    )
    assert flags == []
    assert isinstance(Settings.__dict__.get("password_reset_enabled"), property)


def test_019_ac32_feature_follows_smtp_configuration_only() -> None:
    """Без SMTP функция выключена; с SMTP включена и без всяких дополнительных настроек."""
    off = Settings(env="test", smtp_host=None, cookie_secure=False)
    assert off.password_reset_enabled is False

    on = Settings(
        env="test",
        smtp_host="smtp.example.test",
        smtp_from="tracker@example.test",
        public_base_url="https://tracker.example.test",
        cookie_secure=False,
    )
    assert on.password_reset_enabled is True
