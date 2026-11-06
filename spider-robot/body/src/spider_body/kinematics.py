"""3-DOF leg inverse kinematics (coxa yaw, femur pitch, tibia pitch) and body transforms.

Frames
  body frame : x forward, y left, z up, origin at the body centre on the coxa plane.
  leg frame  : origin at the coxa joint, x along the leg's mount direction, z up.

Joint angles (radians)
  coxa  : 0 = along the mount direction, + = counter-clockwise seen from above
  femur : 0 = horizontal, + = up
  tibia : 0 = straight in line with the femur, + = knee bent down (normal stance ~ +90 deg)
"""

from __future__ import annotations

import math
from dataclasses import dataclass


class IKError(ValueError):
    """The requested foot position is outside the leg's reach."""


@dataclass(frozen=True)
class LegGeometry:
    coxa: float
    femur: float
    tibia: float


@dataclass(frozen=True)
class JointAngles:
    coxa: float
    femur: float
    tibia: float


def _clamp(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def leg_ik(x: float, y: float, z: float, g: LegGeometry) -> JointAngles:
    coxa = math.atan2(y, x)
    r = math.hypot(x, y) - g.coxa  # horizontal distance femur joint -> foot
    d = math.hypot(r, z)
    if d > g.femur + g.tibia - 1e-6 or d < abs(g.femur - g.tibia) + 1e-6:
        raise IKError(f"foot ({x:.3f},{y:.3f},{z:.3f}) out of reach (d={d:.3f})")
    a1 = math.atan2(z, r)
    a2 = math.acos(_clamp((g.femur**2 + d**2 - g.tibia**2) / (2 * g.femur * d)))
    femur = a1 + a2  # knee-up configuration
    gamma = math.acos(_clamp((g.femur**2 + g.tibia**2 - d**2) / (2 * g.femur * g.tibia)))
    tibia = math.pi - gamma
    return JointAngles(coxa, femur, tibia)


def leg_fk(j: JointAngles, g: LegGeometry) -> tuple[float, float, float]:
    r = g.coxa + g.femur * math.cos(j.femur) + g.tibia * math.cos(j.femur - j.tibia)
    z = g.femur * math.sin(j.femur) + g.tibia * math.sin(j.femur - j.tibia)
    return (r * math.cos(j.coxa), r * math.sin(j.coxa), z)


def body_to_leg(
    p: tuple[float, float, float], mount_x: float, mount_y: float, mount_angle: float
) -> tuple[float, float, float]:
    dx, dy = p[0] - mount_x, p[1] - mount_y
    c, s = math.cos(-mount_angle), math.sin(-mount_angle)
    return (c * dx - s * dy, s * dx + c * dy, p[2])


def rotate_rpy(
    p: tuple[float, float, float], roll: float, pitch: float, yaw: float, inverse: bool = False
) -> tuple[float, float, float]:
    """Rotate p by R = Rz(yaw) Ry(pitch) Rx(roll); inverse=True applies R transposed."""
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    r = (
        (cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr),
        (sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr),
        (-sp, cp * sr, cp * cr),
    )
    x, y, z = p
    if inverse:
        return (
            r[0][0] * x + r[1][0] * y + r[2][0] * z,
            r[0][1] * x + r[1][1] * y + r[2][1] * z,
            r[0][2] * x + r[1][2] * y + r[2][2] * z,
        )
    return (
        r[0][0] * x + r[0][1] * y + r[0][2] * z,
        r[1][0] * x + r[1][1] * y + r[1][2] * z,
        r[2][0] * x + r[2][1] * y + r[2][2] * z,
    )


def joint_to_servo_deg(
    joint_rad: float, neutral_deg: float, direction: int, trim_deg: float
) -> float:
    """Servo command (0..180) for a joint angle. Servo 90 = the calibrated neutral pose."""
    return 90.0 + direction * (math.degrees(joint_rad) - neutral_deg) + trim_deg
