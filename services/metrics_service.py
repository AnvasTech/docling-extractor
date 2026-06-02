"""In-process, ephemeral metrics for observability (no persistence)."""

from __future__ import annotations

import threading


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.requests = 0
        self.failures = 0
        self.by_method: dict[str, int] = {}
        self.total_ms = 0

    def record(self, method: str, ms: int, ok: bool) -> None:
        with self._lock:
            self.requests += 1
            self.total_ms += ms
            if ok:
                self.by_method[method] = self.by_method.get(method, 0) + 1
            else:
                self.failures += 1

    def snapshot(self) -> dict:
        with self._lock:
            avg = self.total_ms / self.requests if self.requests else 0
            return {
                "requests": self.requests,
                "failures": self.failures,
                "avg_ms": round(avg, 1),
                "by_method": dict(self.by_method),
            }


metrics = Metrics()
