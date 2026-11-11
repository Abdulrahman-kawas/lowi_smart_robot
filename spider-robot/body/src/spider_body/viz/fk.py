"""Forward kinematics from SERVO degrees: what the legs really do with the commands sent.

This is the exact inverse of the path in Robot.solve:
  foot (level frame) -> rotate_rpy(inverse) -> body_to_leg -> leg_ik -> joint_to_servo_deg
so a viewer drawing these points shows the pose the servos would hold, including the effect of
each servo's direction and trim_deg and of the mechanical clamp (min_deg/max_deg).

Frames are the ones in kinematics.py: body frame x forward, y left, z up, origin at the body
centre on the coxa plane. "Level frame" = body frame rotated by the body pose (roll, pitch, yaw),
the frame the gait engine places feet in.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

from ..config import JOINTS, BodyConfig, GeometryCfg, LegCfg
from ..kinematics import JointAngles, rotate_rpy

Point = tuple[float, float, float]


def servo_to_joint_rad(
    servo_deg: float, neutral_deg: float, direction: int, trim_deg: float
) -> float:
    """Inverse of kinematics.joint_to_servo_deg (direction is +1 or -1, so 1/d == d)."""
    return math.radians(neutral_deg + direction * (servo_deg - 90.0 - trim_deg))


def leg_to_body(p: Point, mount_x: float, mount_y: float, mount_angle: float) -> Point:
    """Inverse of kinematics.body_to_leg."""
    c, s = math.cos(mount_angle), math.sin(mount_angle)
    return (mount_x + c * p[0] - s * p[1], mount_y + s * p[0] + c * p[1], p[2])


def leg_chain(j: JointAngles, geom: GeometryCfg) -> list[Point]:
    """Leg frame points: coxa joint, femur joint (coxa end), knee (femur end), foot.

    Same conventions as kinematics.leg_fk: femur 0 = horizontal, + up; tibia measured from the
    femur line, + = knee bent down.
    """
    cc, sc = math.cos(j.coxa), math.sin(j.coxa)
    r1 = geom.coxa_m
    r2 = r1 + geom.femur_m * math.cos(j.femur)
    z2 = geom.femur_m * math.sin(j.femur)
    r3 = r2 + geom.tibia_m * math.cos(j.femur - j.tibia)
    z3 = z2 + geom.tibia_m * math.sin(j.femur - j.tibia)
    return [(0.0, 0.0, 0.0), (r1 * cc, r1 * sc, 0.0), (r2 * cc, r2 * sc, z2),
            (r3 * cc, r3 * sc, z3)]


def leg_joints(leg: LegCfg, geom: GeometryCfg, servo_deg: Mapping[str, float]) -> JointAngles:
    """Joint angles (rad) of one leg from its three servo commands ("LF.coxa" -> degrees)."""
    neutral = {"coxa": geom.coxa_neutral_deg, "femur": geom.femur_neutral_deg,
               "tibia": geom.tibia_neutral_deg}
    rad = []
    for joint in JOINTS:
        servo = getattr(leg, joint)
        rad.append(servo_to_joint_rad(servo_deg[f"{leg.name}.{joint}"], neutral[joint],
                                      servo.direction, servo.trim_deg))
    return JointAngles(*rad)


def leg_points(
    leg: LegCfg,
    geom: GeometryCfg,
    servo_deg: Mapping[str, float],
    pose: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> list[Point]:
    """[base, coxa end, femur end, foot] of one leg.

    pose = (roll, pitch, yaw) in radians. (0, 0, 0) gives the body frame; robot.pose gives the
    level frame, where the gait engine put the feet.
    """
    a = math.radians(leg.mount_angle_deg)
    pts = [leg_to_body(p, leg.mount_x, leg.mount_y, a)
           for p in leg_chain(leg_joints(leg, geom, servo_deg), geom)]
    if any(pose):
        pts = [rotate_rpy(p, *pose) for p in pts]
    return pts


def all_legs(
    cfg: BodyConfig,
    servo_deg: Mapping[str, float],
    pose: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> dict[str, list[Point]]:
    """Every leg whose three servos have a command. Legs not yet written (limp) are left out."""
    out: dict[str, list[Point]] = {}
    for leg in cfg.legs:
        if all(f"{leg.name}.{j}" in servo_deg for j in JOINTS):
            out[leg.name] = leg_points(leg, cfg.geometry, servo_deg, pose)
    return out
