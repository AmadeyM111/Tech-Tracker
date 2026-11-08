"""Шаблон nginx web-образа: /mcp проксируется на api (ADR-0018, фикс AC-9 M20).

Без этого блока /mcp попадает в SPA (location /), и POST отдаёт 405 от nginx. Проверяем текст
шаблона: точный путь (не префикс), прокси на api, отсутствие буферизации для потоковых ответов.
Поведение на живом стеке проверено вручную (см. описание PR): POST /mcp без токена -> 401 от api.
"""

from __future__ import annotations

import re
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[3] / "deploy" / "web" / "default.conf.template"


def _mcp_location() -> str:
    text = TEMPLATE.read_text(encoding="utf-8")
    match = re.search(r"location ~ \^/mcp/\?\$ \{(.*?)\n    \}", text, re.S)
    assert match, "в шаблоне nginx нет location для /mcp (точное совпадение /mcp и /mcp/)"
    return match.group(1)


def test_mcp_location_matches_exact_path_only() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    # Точный путь через регулярное выражение, а не префикс: /mcpx не уходит в api.
    assert "location ~ ^/mcp/?$" in text
    assert "location /mcp " not in text


def test_mcp_location_proxies_to_api_with_streaming_settings() -> None:
    body = _mcp_location()
    assert "proxy_pass $api_upstream;" in body
    assert "set $api_upstream http://api:8000;" in body
    assert "proxy_set_header Host $http_host;" in body
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in body
    # Streamable HTTP: потоковые ответы не буферизуются, таймаут длинный.
    assert "proxy_buffering off;" in body
    assert "proxy_read_timeout 3600s;" in body


def test_mcp_location_is_before_spa_fallback() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    assert text.index("location ~ ^/mcp/?$") < text.index("location / {")
