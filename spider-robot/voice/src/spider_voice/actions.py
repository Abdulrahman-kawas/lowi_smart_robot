"""Each spoken act maps to one short, self-ending command."""

from __future__ import annotations

from spider_common.protocol import Command, Move, Posture

from .config import MotionCfg


def to_command(act: str, m: MotionCfg) -> Command | None:
    """The command for an act, or None for acts that are not motion (look, none)."""
    if act == "forward":
        return Move(vx=m.speed_mps, duration_s=m.duration_s, gait=m.gait)
    if act == "back":
        return Move(vx=-m.speed_mps, duration_s=m.duration_s, gait=m.gait)
    if act == "left":
        return Move(wz=m.turn_rps, duration_s=m.duration_s, gait=m.gait)
    if act == "right":
        return Move(wz=-m.turn_rps, duration_s=m.duration_s, gait=m.gait)
    if act == "stand":
        return Posture(posture="stand")
    if act == "sit":
        return Posture(posture="sit")
    return None
