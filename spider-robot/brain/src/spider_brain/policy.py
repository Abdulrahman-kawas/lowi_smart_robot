"""Risk of each robot tool call and whether the owner must approve it.

Same ladder as desktop-agent's safety policy (LOW < MEDIUM < HIGH):
  supervised : approve everything
  guarded    : approve MEDIUM and HIGH (default: every movement is approved)
  autonomous : approve HIGH only

The body's own reflexes (obstacle stop, link watchdog, tilt) apply in every mode; approval
is an extra layer, not the only one.
"""

from __future__ import annotations

from enum import IntEnum

from .calls import ToolCall
from .config import Autonomy, Settings


class Risk(IntEnum):
    LOW = 0
    MEDIUM = 1
    HIGH = 2


_READ_ONLY = {"get_status", "scan_surroundings", "look", "stop", "wait"}

_THRESHOLD: dict[Autonomy, Risk] = {
    "supervised": Risk.LOW,
    "guarded": Risk.MEDIUM,
    "autonomous": Risk.HIGH,
}


def classify(call: ToolCall, settings: Settings) -> Risk:
    name, args = call.name, call.args or {}
    if name in _READ_ONLY:
        return Risk.LOW
    if name == "walk":
        try:
            distance = float(args.get("distance_m", 0))
        except (TypeError, ValueError):
            return Risk.HIGH
        return Risk.HIGH if distance > settings.approval_free_walk_m else Risk.MEDIUM
    if name == "turn":
        return Risk.MEDIUM
    if name == "set_posture":
        return Risk.HIGH if args.get("posture") == "relax" else Risk.MEDIUM
    if name == "adjust_body":
        return Risk.MEDIUM
    return Risk.HIGH  # unknown tools fail closed


def needs_approval(risk: Risk, autonomy: Autonomy) -> bool:
    return risk >= _THRESHOLD[autonomy]


def describe(call: ToolCall) -> str:
    a = call.args or {}
    if call.name == "walk":
        return f"walk {a.get('direction')} {a.get('distance_m')} m ({a.get('speed')})"
    if call.name == "turn":
        return f"turn {a.get('angle_deg')} deg"
    if call.name == "set_posture":
        return f"posture: {a.get('posture')}"
    if call.name == "look":
        return f"look: {str(a.get('question', ''))[:80]}"
    if call.name == "adjust_body":
        return f"adjust body: height {a.get('height_m')} m, pitch {a.get('pitch_deg')} deg"
    if call.name == "wait":
        return f"wait {a.get('seconds')} s"
    return call.name
