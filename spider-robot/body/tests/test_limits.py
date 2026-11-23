"""Joint limits move with the trim, stop at the servo's own travel, and let the femur sit."""

import math
from pathlib import Path

from spider_common.link import InMemoryHub

from spider_body.config import JOINTS, load_config
from spider_body.hw.camera import NoCamera
from spider_body.hw.lidar import NoLidar
from spider_body.hw.servos import clamp_servo
from spider_body.kinematics import body_to_leg, joint_to_servo_deg, leg_ik
from spider_body.robot import Robot

EXAMPLE = Path(__file__).resolve().parents[1] / "config" / "robot.example.yaml"

# The owner's calibration on 2026-11-19, after every horn was seated again at the zero pose:
# (direction, trim_deg) for coxa, femur, tibia. RF.femur sits at the -30 trim limit.
CALIBRATED = {
    "LF": ((1, -25.0), (-1, 17.0), (-1, -21.0)),
    "LM": ((1, 20.0), (-1, 18.0), (-1, -13.0)),
    "LR": ((1, 15.0), (1, -20.0), (1, 8.0)),
    "RF": ((1, 26.0), (-1, -30.0), (-1, 10.0)),
    "RM": ((1, 21.0), (-1, 3.0), (-1, 18.0)),
    "RR": ((1, 0.0), (-1, -11.0), (-1, -5.0)),
}


class _Bank:
    def write(self, servo_deg):
        pass

    def relax(self):
        pass


def test_limits_move_with_the_trim(cfg):
    s = cfg.servo("RF.tibia")
    s.trim_deg = -25.0
    assert cfg.limits_of(s) == (-15.0, 145.0)
    assert clamp_servo(cfg, s, -20.0) == (-15.0, True)
    assert clamp_servo(cfg, s, 0.0) == (0.0, False)


def test_limits_stop_at_the_servos_own_travel(cfg):
    lr_tibia = cfg.servo("LR.tibia")  # the one 180-degree servo
    lr_tibia.trim_deg = 20.0
    assert cfg.limits_of(lr_tibia) == (30.0, 180.0)
    rf_coxa = cfg.servo("RF.coxa")  # 270 degrees: logical -45..225
    rf_coxa.trim_deg = 60.0
    assert cfg.limits_of(rf_coxa) == (70.0, 225.0)


def test_the_femur_has_room_to_sit(cfg):
    assert cfg.limits_of(cfg.servo("LF.femur")) == (0.0, 180.0)
    assert cfg.limits_of(cfg.servo("LF.coxa")) == (10.0, 170.0)
    assert cfg.limits_of(cfg.servo("LF.tibia")) == (10.0, 170.0)


def _servo_deg(cfg, robot, feet):
    g = cfg.geometry
    neutral = {"coxa": g.coxa_neutral_deg, "femur": g.femur_neutral_deg,
               "tibia": g.tibia_neutral_deg}
    out = {}
    for leg in cfg.legs:
        x, y, z = body_to_leg(feet[leg.name], leg.mount_x, leg.mount_y,
                              math.radians(leg.mount_angle_deg))
        j = leg_ik(x, y, z, robot.geom)
        for joint, rad in zip(JOINTS, (j.coxa, j.femur, j.tibia), strict=True):
            s = getattr(leg, joint)
            out[f"{leg.name}.{joint}"] = joint_to_servo_deg(rad, neutral[joint], s.direction,
                                                            s.trim_deg)
    return out


def test_the_calibrated_robot_stands_sits_and_walks_inside_its_limits():
    cfg = load_config(EXAMPLE, calibration="/nonexistent")
    for leg in cfg.legs:
        for joint, (direction, trim) in zip(JOINTS, CALIBRATED[leg.name], strict=True):
            s = getattr(leg, joint)
            s.direction, s.trim_deg = direction, trim
    robot = Robot(cfg, _Bank(), NoLidar(), NoCamera(), InMemoryHub().endpoint([]))
    g, gait = cfg.geometry, robot.gait
    frames = []
    for height in (g.body_height_m, g.sit_height_m):
        gait.height = height
        frames.append(gait.step(0.0))
    gait.height = g.body_height_m
    m = cfg.gait
    for vx, vy, wz in ((m.max_vx, 0, 0), (-m.max_vx, 0, 0), (0, m.max_vy, 0),
                       (0, 0, m.max_wz), (0, 0, -m.max_wz)):
        gait.set_velocity(vx, vy, wz)
        frames += [gait.step(0.02) for _ in range(400)]
        gait.set_velocity(0, 0, 0)
        frames += [gait.step(0.02) for _ in range(150)]
    worst = {}
    for feet in frames:
        for jid, deg in _servo_deg(cfg, robot, feet).items():
            lo, hi = cfg.limits_of(cfg.servo(jid))
            worst[jid] = min(worst.get(jid, math.inf), deg - lo, hi - deg)
    assert {jid: round(v, 1) for jid, v in worst.items() if v < 0} == {}
