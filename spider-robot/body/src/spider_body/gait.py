"""Periodic gait generator for a hexapod.

Each leg follows the same cycle shifted by a per-gait phase offset:
  stance (local phase < duty): the foot slides backwards on the ground (this moves the body)
  swing  (local phase >= duty): the foot lifts on a half-sine and returns forwards

The stride of each foot comes from the body twist (vx, vy, wz) at that foot, so walking,
strafing and turning in place all use the same code. Velocity is ramped with acceleration
limits and the step lift fades in and out, so starting and stopping never makes a foot jump.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .config import GaitCfg, GeometryCfg, LegCfg

# gait name -> (duty factor, phase offset per leg)
GAITS: dict[str, tuple[float, dict[str, float]]] = {
    # two alternating tripods: fastest, 3 feet always on the ground
    "tripod": (0.5, {"LF": 0.0, "RM": 0.0, "LR": 0.0, "RF": 0.5, "LM": 0.5, "RR": 0.5}),
    # one leg per side in the air, sides half a cycle apart
    "ripple": (2 / 3, {"LR": 0.0, "LM": 1 / 3, "LF": 2 / 3, "RR": 0.5, "RM": 5 / 6, "RF": 1 / 6}),
    # one leg at a time: slowest, most stable (rough ground, carrying load)
    "wave": (5 / 6, {"LR": 0.0, "LM": 1 / 6, "LF": 2 / 6, "RR": 3 / 6, "RM": 4 / 6, "RF": 5 / 6}),
}

_EPS = 1e-4

Foot = tuple[float, float, float]


@dataclass
class Twist:
    vx: float = 0.0
    vy: float = 0.0
    wz: float = 0.0

    def is_zero(self) -> bool:
        return abs(self.vx) < _EPS and abs(self.vy) < _EPS and abs(self.wz) < _EPS


def _approach(cur: float, target: float, max_step: float) -> float:
    if target > cur:
        return min(target, cur + max_step)
    return max(target, cur - max_step)


class GaitEngine:
    def __init__(self, legs: list[LegCfg], geom: GeometryCfg, cfg: GaitCfg) -> None:
        self.cfg = cfg
        self.geom = geom
        self.neutral: dict[str, tuple[float, float]] = {}
        for leg in legs:
            a = math.radians(leg.mount_angle_deg)
            self.neutral[leg.name] = (
                leg.mount_x + geom.stance_radius_m * math.cos(a),
                leg.mount_y + geom.stance_radius_m * math.sin(a),
            )
        self.phase = 0.0
        self.gait = "tripod"
        self.target = Twist()
        self.current = Twist()  # ramped velocity
        self.effective = Twist()  # after the stride clamp: what the body really does
        self.lift_gain = 0.0
        self.height = geom.sit_height_m
        self.frozen = False  # E-stop: hold every foot exactly where it is
        self._last_feet: dict[str, Foot] | None = None

    # ------------------------------------------------------------------ inputs
    def set_velocity(self, vx: float, vy: float, wz: float, gait: str | None = None) -> None:
        c = self.cfg
        self.target = Twist(
            max(-c.max_vx, min(c.max_vx, vx)),
            max(-c.max_vy, min(c.max_vy, vy)),
            max(-c.max_wz, min(c.max_wz, wz)),
        )
        # Changing gait mid-stride would make feet jump: only switch while idle.
        if gait in GAITS and gait != self.gait and self.is_idle():
            self.gait = gait

    def stop(self) -> None:
        self.target = Twist()

    def halt_now(self) -> None:
        """Forget all motion at once (used when the robot has fallen and the servos go limp)."""
        self.target = Twist()
        self.current = Twist()

    def freeze(self) -> None:
        """E-stop: stop the cycle and hold every foot where it is (no jump)."""
        self.target = Twist()
        self.frozen = True

    def unfreeze(self) -> None:
        """Continue from the frozen pose; the velocity then ramps down smoothly."""
        self.frozen = False

    def is_idle(self) -> bool:
        return self.current.is_zero() and self.target.is_zero() and self.lift_gain <= 0.0

    @property
    def moving(self) -> bool:
        return not self.is_idle()

    # ------------------------------------------------------------------ output
    def step(self, dt: float) -> dict[str, Foot]:
        if self.frozen and self._last_feet is not None:
            self.effective = Twist()
            return self._last_feet
        feet = self._step(dt)
        self._last_feet = feet
        return feet

    def _step(self, dt: float) -> dict[str, Foot]:
        c = self.cfg
        cur, tgt = self.current, self.target
        cur.vx = _approach(cur.vx, tgt.vx, c.accel * dt)
        cur.vy = _approach(cur.vy, tgt.vy, c.accel * dt)
        cur.wz = _approach(cur.wz, tgt.wz, c.yaw_accel * dt)

        want_lift = 0.0 if (tgt.is_zero() and cur.is_zero()) else 1.0
        self.lift_gain = _approach(self.lift_gain, want_lift, dt / (0.5 * c.period_s))

        duty, offsets = GAITS[self.gait]
        stance_time = c.period_s * duty

        # Per-foot stride; scale the whole twist down if any foot would over-reach.
        strides: dict[str, tuple[float, float]] = {}
        scale = 1.0
        for name, (px, py) in self.neutral.items():
            sx = (cur.vx - cur.wz * py) * stance_time
            sy = (cur.vy + cur.wz * px) * stance_time
            strides[name] = (sx, sy)
            length = math.hypot(sx, sy)
            if length > c.max_stride_m:
                scale = min(scale, c.max_stride_m / length)
        self.effective = Twist(cur.vx * scale, cur.vy * scale, cur.wz * scale)

        if self.moving:
            self.phase = (self.phase + dt / c.period_s) % 1.0

        feet: dict[str, Foot] = {}
        for name, (nx, ny) in self.neutral.items():
            sx, sy = strides[name][0] * scale, strides[name][1] * scale
            local = (self.phase + offsets[name]) % 1.0
            if local < duty:
                k = 0.5 - local / duty  # +0.5 -> -0.5 while on the ground
                lift = 0.0
            else:
                s = (local - duty) / (1.0 - duty)
                k = -0.5 + s  # -0.5 -> +0.5 while in the air
                lift = c.step_height_m * self.lift_gain * math.sin(math.pi * s)
            feet[name] = (nx + k * sx, ny + k * sy, -self.height + lift)
        return feet
