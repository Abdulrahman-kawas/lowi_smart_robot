"""The table pose: feet in three at a time, body up, held; Stand brings it back."""

import numpy as np
import pytest
from spider_common.protocol import BodyPose, Move, Perform, Posture, Stop
from test_limits import CALIBRATED, EXAMPLE
from test_moves import kinds, last, stood
from test_robot import run_ticks

from spider_body.config import JOINTS, load_config
from spider_body.moves import (
    MAX_RISE_M,
    TRIPOD_A,
    TRIPOD_B,
    Choreo,
    MoveLibrary,
    validate,
)

TS = 5000.0


def table(robot, lidar, world, clock, speed=1.0, seq=20):
    robot.handle(Perform(name="table", speed=speed, ts=TS, seq=seq))
    run_ticks(robot, lidar, world, clock, 6.0)


def test_the_table_steps_three_feet_at_a_time_then_rises(cfg):
    lib = MoveLibrary(cfg)
    spec = lib.get("table")
    rep = validate(lib.geo, spec, 0.5, keep=True)
    assert rep.ok, rep.reason
    up = rep.feet[:, :, 2] > 1e-4
    lifted = {tuple(np.flatnonzero(row)) for row in up if row.any()}
    names = {tuple(sorted(TRIPOD_A)), tuple(sorted(TRIPOD_B))}
    legs = ("LF", "LM", "LR", "RF", "RM", "RR")
    assert {tuple(sorted(legs[i] for i in rows)) for rows in lifted} == names
    body, feet = spec.arrays()
    assert body[-1][0] == pytest.approx(cfg.moves.table_height_m - cfg.geometry.body_height_m)
    inward = np.hypot(feet[-1][:, 0], feet[-1][:, 1])
    assert inward == pytest.approx(np.full(6, cfg.moves.table_in_m))
    assert not up[-1].any()  # every foot on the floor while it holds


def test_the_owners_robot_can_hold_the_table_and_come_back():
    cfg = load_config(EXAMPLE, calibration="/nonexistent")
    for leg in cfg.legs:
        for joint, (direction, trim) in zip(JOINTS, CALIBRATED[leg.name], strict=True):
            s = getattr(leg, joint)
            s.direction, s.trim_deg = direction, trim
    lib = MoveLibrary(cfg)
    spec = lib.get("table")
    for speed in (0.3, 0.5, 1.0):
        assert validate(lib.geo, spec, speed).ok
    body, feet = spec.arrays()
    back, rep = lib.recovery(body[-1], feet[-1])
    assert rep.ok, rep.reason


def test_other_moves_still_may_not_rise_more_than_4_cm(cfg):
    lib = MoveLibrary(cfg)
    too_high = Choreo().to(1.0, dz=MAX_RISE_M + 0.01).home_body(1.0).spec("too_high")
    assert "outside the safe range" in validate(lib.geo, too_high, 0.5).reason


def test_the_table_is_held_until_stand(cfg):
    robot, _servos, lidar, world, brain, clock = stood(cfg)
    table(robot, lidar, world, clock)
    assert last(brain, "perform_done")["detail"] == "table held: send stand to come back"
    assert robot.perform is None and robot._frame is not None
    assert robot.mode == "standing"
    assert robot.gait.height == pytest.approx(cfg.moves.table_height_m, abs=1e-3)
    run_ticks(robot, lidar, world, clock, 2.0)  # still held
    assert robot.gait.height == pytest.approx(cfg.moves.table_height_m, abs=1e-3)


@pytest.mark.parametrize("cmd", [
    Move(vx=0.03, duration_s=1.0, ts=TS, seq=30),
    BodyPose(height_m=0.12, ts=TS, seq=30),
    Posture(posture="relax", ts=TS, seq=30),
])
def test_while_held_it_does_not_walk_change_pose_or_relax(cfg, cmd):
    robot, _servos, lidar, world, brain, clock = stood(cfg)
    table(robot, lidar, world, clock)
    robot.handle(cmd)
    run_ticks(robot, lidar, world, clock, 0.5)
    assert kinds(brain)[-1] == "rejected"
    assert robot._frame is not None and robot.mode == "standing"


def test_another_move_is_refused_while_held(cfg):
    robot, _servos, lidar, world, brain, clock = stood(cfg)
    table(robot, lidar, world, clock)
    robot.handle(Perform(name="wave", ts=TS, seq=30))
    assert "holding the last move pose" in last(brain, "perform_rejected")["detail"]


def test_stand_brings_it_back_to_the_normal_stand(cfg):
    robot, _servos, lidar, world, brain, clock = stood(cfg)
    table(robot, lidar, world, clock)
    robot.handle(Posture(posture="stand", ts=TS, seq=40))
    assert robot.perform is not None and robot.perform.spec.name == "recover"
    run_ticks(robot, lidar, world, clock, 15.0)
    assert robot.perform is None and robot._frame is None
    assert robot.gait.height == pytest.approx(cfg.geometry.body_height_m)
    robot.handle(Move(vx=0.03, duration_s=1.0, ts=TS, seq=41))
    run_ticks(robot, lidar, world, clock, 0.3)
    assert robot.mode == "walking"  # back to normal: it walks again


def test_sit_from_the_table_goes_through_the_stand(cfg):
    robot, _servos, lidar, world, brain, clock = stood(cfg)
    table(robot, lidar, world, clock)
    robot.handle(Posture(posture="sit", ts=TS, seq=40))
    run_ticks(robot, lidar, world, clock, 20.0)
    assert robot.mode == "sitting" and robot._frame is None


def test_a_stop_while_rising_holds_where_it_is_and_stand_still_works(cfg):
    robot, _servos, lidar, world, brain, clock = stood(cfg)
    robot.handle(Perform(name="table", speed=0.5, ts=TS, seq=20))
    run_ticks(robot, lidar, world, clock, 1.0)  # three feet in the air
    robot.handle(Stop(ts=TS, seq=21))
    run_ticks(robot, lidar, world, clock, 0.5)
    assert robot.perform is None and robot._frame is not None
    robot.handle(Posture(posture="stand", ts=TS, seq=22))
    run_ticks(robot, lidar, world, clock, 15.0)
    assert robot._frame is None
    assert robot.gait.height == pytest.approx(cfg.geometry.body_height_m)
