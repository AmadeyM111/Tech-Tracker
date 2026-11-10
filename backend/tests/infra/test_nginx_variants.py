"""Варианты nginx web согласованы: общие блоки есть в обоих файлах (deploy/web/README.md)."""

from __future__ import annotations

from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[3] / "deploy" / "web"
VARIANTS = ["default.conf.template", "behind-proxy.conf.template"]


@pytest.mark.parametrize("name", VARIANTS)
def test_common_blocks_present(name: str) -> None:
    text = (WEB / name).read_text(encoding="utf-8")
    assert "client_max_body_size 12m;" in text, "лимит вложений 011 (10 МБ + запас)"
    assert "location ~ ^/mcp/?$" in text, "MCP (ADR-0018)"
    assert "location = /healthz" in text
    assert "location /api/ {" in text
    assert "@payload_too_large" in text


def test_behind_proxy_has_no_tls_and_real_ip() -> None:
    text = (WEB / "behind-proxy.conf.template").read_text(encoding="utf-8")
    assert "ssl_certificate" not in text and "listen 443" not in text
    assert "set_real_ip_from" in text and "real_ip_header X-Forwarded-For" in text
    assert "X-Forwarded-Proto https;" in text
    assert "${" not in text, "переменных envsubst нет"
