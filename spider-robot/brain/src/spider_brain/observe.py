"""Latency summaries from voice turns, and alerts from service health reports."""

from __future__ import annotations

import json
import logging
import time
from collections import Counter, deque
from pathlib import Path

from spider_common.protocol import HealthReport, VoiceTurn

from .supervision.events import EventBus

log = logging.getLogger(__name__)

MAX_TRACES = 2000
MAX_FILE_BYTES = 10 * 1024 * 1024
ALERT_COOLDOWN_S = 300.0
_THROTTLE_NOW = 0x7  # under-voltage, frequency capped, throttled, at this moment


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(p * len(ordered)))]


class TraceStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.items: deque[VoiceTurn] = deque(maxlen=MAX_TRACES)

    def add(self, payload: bytes) -> dict:
        trace = VoiceTurn.model_validate_json(payload)
        self.items.append(trace)
        self._append(trace)
        return self.summary()

    def _append(self, trace: VoiceTurn) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.stat().st_size > MAX_FILE_BYTES:
                self.path.replace(self.path.with_suffix(".1"))
            with self.path.open("a", encoding="utf-8") as f:
                f.write(trace.model_dump_json() + "\n")
        except OSError as exc:  # observability must never break the brain
            log.warning("could not store a trace: %s", exc)

    def summary(self) -> dict:
        stages: dict[str, list[float]] = {}
        for trace in self.items:
            for name, ms in (("stt", trace.stt_ms), ("router", trace.route_ms),
                             ("first_audio", trace.tts_first_ms), ("total", trace.total_ms)):
                if ms is not None:
                    stages.setdefault(name, []).append(ms)
        return {
            "stages": {
                name: {"n": len(v), "p50": round(percentile(v, 0.5), 1),
                       "p95": round(percentile(v, 0.95), 1)}
                for name, v in sorted(stages.items())
            },
            "paths": dict(Counter(t.route for t in self.items)),
        }


def assess(r: HealthReport) -> list[str]:
    """The conditions worth waking someone for. Everything else is on the dashboard."""
    problems = []
    m, who = r.metrics, r.service
    if r.level == "down" and who != "system":  # a dead service reports this through its last will
        problems.append(f"{who}: is down {r.detail}".rstrip())
    if m.get("stt_timeouts", 0.0) >= 3:
        problems.append(f"{who}: speech recognition keeps timing out")
    if m.get("temp_c", 0.0) >= 80.0:
        problems.append(f"{who}: CPU at {m['temp_c']:.0f} C")
    if int(m.get("throttled_flags", 0)) & _THROTTLE_NOW:
        problems.append(f"{who}: throttled or under-voltage ({int(m['throttled_flags']):#x})")
    if m.get("mem_available_mb", 1e9) < 300:
        problems.append(f"{who}: only {m['mem_available_mb']:.0f} MB memory free")
    if m.get("disk_free_mb", 1e9) < 1024:
        problems.append(f"{who}: only {m['disk_free_mb']:.0f} MB disk free")
    if r.info.get("failed_units"):
        problems.append(f"{who}: failed units {r.info['failed_units']}")
    if r.info.get("tailscale_path") == "none":
        problems.append(f"{who}: no path to the peer on Tailscale")
    return problems


class HealthMonitor:
    def __init__(self, bus: EventBus, clock=time.monotonic) -> None:
        self.bus, self.clock = bus, clock
        self.reports: dict[str, HealthReport] = {}
        self._alerted: dict[str, float] = {}

    def on_report(self, payload: bytes) -> list[str]:
        report = HealthReport.model_validate_json(payload)
        self.reports[report.service] = report
        self.bus.publish("health", report=json.loads(payload))
        fired = []
        for problem in assess(report):
            key = problem.split(":")[0] + problem.split(":")[1][:12]
            if self.clock() - self._alerted.get(key, -1e9) >= ALERT_COOLDOWN_S:
                self._alerted[key] = self.clock()
                self.bus.publish("robot_event", event="health", seq=None, detail=problem)
                fired.append(problem)
        return fired
