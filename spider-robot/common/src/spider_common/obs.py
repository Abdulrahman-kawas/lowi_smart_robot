"""Observability helpers shared by every process: JSON logs, trace ids, fixed-cost histograms."""

from __future__ import annotations

import json
import logging
import time
import uuid
from bisect import bisect_right
from typing import Any

_STANDARD = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message", "asctime", "fields",
}


def new_trace() -> str:
    """A short correlation id. Carried from utterance or task, through commands, to events."""
    return uuid.uuid4().hex[:12]


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Anything passed with extra={...} is merged in."""

    def __init__(self, service: str = "") -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": round(record.created, 3),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if self.service:
            out["svc"] = self.service
        for key, value in record.__dict__.items():
            if key not in _STANDARD and not key.startswith("_"):
                out[key] = value
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            out.update(fields)
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False, default=str)


def setup_logging(level: str = "INFO", json_logs: bool = True, service: str = "") -> None:
    root = logging.getLogger()
    root.setLevel(level)
    handler = logging.StreamHandler()
    if json_logs:
        handler.setFormatter(JsonFormatter(service))
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.handlers[:] = [handler]


class Histogram:
    """Fixed buckets: record() allocates nothing and costs the same on every call."""

    def __init__(self, edges_ms: tuple[float, ...] | None = None) -> None:
        self.edges = edges_ms or (
            0.1, 0.2, 0.5, 1, 2, 3, 4, 5, 7, 10, 15, 20, 30, 40, 60, 80, 100, 150, 200, 500, 1000,
        )
        self.counts = [0] * (len(self.edges) + 1)
        self.total = 0
        self.maximum = 0.0

    def record(self, value_ms: float) -> None:
        self.counts[bisect_right(self.edges, value_ms)] += 1
        self.total += 1
        if value_ms > self.maximum:
            self.maximum = value_ms

    def percentile(self, q: float) -> float:
        """Upper bucket edge holding the q quantile, a conservative estimate. 0.0 when empty."""
        if self.total == 0:
            return 0.0
        target = max(1, int(self.total * q + 0.999999))
        seen = 0
        for i, count in enumerate(self.counts):
            seen += count
            if seen >= target:
                return self.edges[i] if i < len(self.edges) else self.maximum
        return self.maximum

    def snapshot(self) -> dict[str, float]:
        return {
            "n": float(self.total),
            "p50_ms": self.percentile(0.50),
            "p99_ms": self.percentile(0.99),
            "p999_ms": self.percentile(0.999),
            "max_ms": round(self.maximum, 3),
        }


class Stopwatch:
    def __init__(self) -> None:
        self.t0 = time.perf_counter()

    def ms(self) -> float:
        return (time.perf_counter() - self.t0) * 1000.0
