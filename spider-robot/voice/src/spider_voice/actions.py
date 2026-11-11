"""Each spoken act maps to one short, self-ending command."""

from __future__ import annotations

from spider_common.protocol import Command, Move, Perform, Posture, Reach

from .config import MotionCfg
from .grammar import MOVE_ACTS


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
    if act == "reach":
        return Reach(target="nearest", speed=m.move_speed)
    if act in MOVE_ACTS:  # the act names are the body's move names
        return Perform(name=act, speed=m.move_speed)
    return None
