"""Спека 032: счётчик ``tools/call`` в памяти процесса."""

from __future__ import annotations

from uuid import uuid4

from app.api.mcp.rate_limit import TokenRateLimiter


def test_032_limiter_allows_limit_then_returns_retry_after() -> None:
    limiter = TokenRateLimiter(limit=2, window=60.0)
    token = uuid4()
    assert limiter.hit(token, now=100.0) is None
    assert limiter.hit(token, now=100.1) is None
    wait = limiter.hit(token, now=100.2)
    assert wait is not None and wait >= 1
    other = uuid4()
    assert limiter.hit(other, now=100.2) is None
    assert limiter.hit(token, now=160.3) is None
