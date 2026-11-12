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


def test_behind_proxy_routes_oauth_metadata_to_api_and_authorize_to_spa() -> None:
    """Спека 028 §8: метаданные OAuth — на api; /oauth/authorize (экран согласия) — в SPA."""
    text = (WEB / "behind-proxy.conf.template").read_text(encoding="utf-8")
    assert "location ^~ /.well-known/oauth- {" in text
    assert "location = /.well-known/openid-configuration {" in text
    for block in (
        "location ^~ /.well-known/oauth- {",
        "location = /.well-known/openid-configuration {",
    ):
        start = text.index(block)
        body = text[start : text.index("}", start)]
        assert "proxy_pass $api_upstream;" in body and "http://api:8000" in body
    # /oauth/ в nginx не проксируется: нет ни одного блока для него (SPA отдаёт location /)
    assert "location ^~ /oauth/" not in text
    assert "location /oauth" not in text
