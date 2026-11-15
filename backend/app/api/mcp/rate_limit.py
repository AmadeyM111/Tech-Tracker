"""Лимит вызовов инструментов MCP: 120 в минуту на токен или OAuth access (спека 032).

Счётчик в памяти процесса: один воркер API. Ключ — ``token_id`` (строка ``api_token`` или access).
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock
from uuid import UUID

TOOL_CALLS_PER_MINUTE = 120
WINDOW_SECONDS = 60.0


class TokenRateLimiter:
    def __init__(self, limit: int = TOOL_CALLS_PER_MINUTE, window: float = WINDOW_SECONDS) -> None:
        self.limit = limit
        self.window = window
        self._hits: dict[UUID, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def hit(self, token_id: UUID, *, now: float | None = None) -> int | None:
        """``None`` — вызов учтён; иначе секунд до ``Retry-After``."""
        t = time.monotonic() if now is None else now
        with self._lock:
            q = self._hits[token_id]
            cutoff = t - self.window
            while q and q[0] <= cutoff:
                q.popleft()
            if len(q) >= self.limit:
                return max(1, int(self.window - (t - q[0])) + 1)
            q.append(t)
            return None
