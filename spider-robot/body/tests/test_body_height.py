"""A higher stand with BodyPose: it ramps there, the robot walks at it, and stand brings it back."""

import pytest
from spider_common.protocol import BodyPose, Move, Posture
from test_robot import events, make, run_ticks, stand

TS = 5000.0


def test_a_higher_stand_walks_and_stand_returns_to_normal(cfg):
    robot, _servos, lidar, world, brain, clock = make(cfg)
    stand(robot, lidar, world, clock)
    normal = cfg.geometry.body_height_m
    robot.handle(BodyPose(height_m=normal + 0.03, ts=TS, seq=10))
    run_ticks(robot, lidar, world, clock, 2.0)
    assert robot.gait.height == pytest.approx(normal + 0.03, abs=0.002)
    assert robot.mode == "standing"
    robot.handle(Move(vx=0.03, duration_s=1.0, ts=TS, seq=11))
    run_ticks(robot, lidar, world, clock, 0.5)
    assert robot.mode == "walking"
    assert robot.gait.height == pytest.approx(normal + 0.03, abs=0.002)  # walks at that height
    run_ticks(robot, lidar, world, clock, 1.5)
    robot.handle(Posture(posture="stand", ts=TS, seq=12))
    run_ticks(robot, lidar, world, clock, 2.0)
    assert robot.gait.height == pytest.approx(normal, abs=0.002)


def test_a_stand_too_high_is_limited_to_four_cm_above_normal(cfg):
    robot, _servos, lidar, world, brain, clock = make(cfg)
    stand(robot, lidar, world, clock)
    robot.handle(BodyPose(height_m=0.20, ts=TS, seq=10))
    run_ticks(robot, lidar, world, clock, 4.0)
    assert robot.gait.height == pytest.approx(cfg.geometry.body_height_m + 0.04, abs=0.002)


def test_a_higher_stand_needs_the_robot_standing(cfg):
    robot, _servos, lidar, world, brain, clock = make(cfg)
    robot.handle(BodyPose(height_m=0.12, ts=TS, seq=10))
    assert [e["detail"] for e in events(brain) if e["kind"] == "rejected"] == [
        "body pose needs standing (not walking)"]


@pytest.mark.parametrize("up_m", [0.02, 0.04])
def test_the_calibrated_robot_stands_and_walks_higher_inside_its_limits(up_m):
    import math

    from spider_common.link import InMemoryHub
    from test_limits import CALIBRATED, EXAMPLE, _Bank, _servo_deg

    from spider_body.config import JOINTS, load_config
    from spider_body.hw.camera import NoCamera
    from spider_body.hw.lidar import NoLidar
    from spider_body.robot import Robot

    cfg = load_config(EXAMPLE, calibration="/nonexistent")
    for leg in cfg.legs:
        for joint, (direction, trim) in zip(JOINTS, CALIBRATED[leg.name], strict=True):
            s = getattr(leg, joint)
            s.direction, s.trim_deg = direction, trim
    robot = Robot(cfg, _Bank(), NoLidar(), NoCamera(), InMemoryHub().endpoint([]))
    gait, m = robot.gait, cfg.gait
    gait.height = cfg.geometry.body_height_m + up_m
    frames = [gait.step(0.0)]
    for vx, vy, wz in ((m.max_vx, 0, 0), (-m.max_vx, 0, 0), (0, m.max_vy, 0),
                       (0, 0, m.max_wz), (0, 0, -m.max_wz)):
        gait.set_velocity(vx, vy, wz)
        frames += [gait.step(0.02) for _ in range(400)]
        gait.set_velocity(0, 0, 0)
        frames += [gait.step(0.02) for _ in range(150)]
    worst = math.inf
    for feet in frames:
        for jid, deg in _servo_deg(cfg, robot, feet).items():
            lo, hi = cfg.limits_of(cfg.servo(jid))
            worst = min(worst, deg - lo, hi - deg)
    assert worst > 20.0  # degrees left before any joint limit (normal stand: 25)
