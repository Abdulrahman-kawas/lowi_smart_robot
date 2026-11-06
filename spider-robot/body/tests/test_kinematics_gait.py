import math

import pytest

from spider_body.gait import GAITS, GaitEngine
from spider_body.kinematics import (
    IKError,
    JointAngles,
    LegGeometry,
    leg_fk,
    leg_ik,
    rotate_rpy,
)

G = LegGeometry(0.045, 0.075, 0.13)


@pytest.mark.parametrize(
    "p", [(0.12, 0.0, -0.09), (0.10, 0.04, -0.05), (0.15, -0.03, -0.12), (0.09, 0.0, -0.035)]
)
def test_ik_fk_roundtrip(p):
    j = leg_ik(*p, G)
    assert leg_fk(j, G) == pytest.approx(p, abs=1e-9)


def test_neutral_stance_is_knee_up():
    j = leg_ik(0.12, 0.0, -0.09, G)
    assert j.femur > 0  # femur raised
    assert 0 < j.tibia < math.pi  # knee bent down


def test_unreachable_raises():
    with pytest.raises(IKError):
        leg_ik(0.40, 0.0, -0.09, G)


def test_rotate_inverse():
    p = (0.1, -0.2, 0.05)
    q = rotate_rpy(p, 0.1, -0.2, 0.3)
    assert rotate_rpy(q, 0.1, -0.2, 0.3, inverse=True) == pytest.approx(p)


def test_fk_known_pose():
    j = JointAngles(0.0, 0.0, math.pi / 2)  # femur horizontal, tibia vertical
    assert leg_fk(j, G) == pytest.approx((0.045 + 0.075, 0.0, -0.13))


@pytest.mark.parametrize("gait", list(GAITS))
def test_gait_starts_and_stops_at_neutral(cfg, gait):
    eng = GaitEngine(cfg.legs, cfg.geometry, cfg.gait)
    eng.height = cfg.geometry.body_height_m
    rest = eng.step(0.02)
    eng.set_velocity(0.0, 0.0, 0.0, gait)
    assert eng.gait == gait
    eng.set_velocity(0.08, 0.0, 0.2)
    prev = rest
    for _ in range(200):  # 4 s walking
        feet = eng.step(0.02)
        for leg in feet:  # no foot ever jumps more than 2 cm between ticks
            assert math.dist(feet[leg], prev[leg]) < 0.02
        prev = feet
    assert eng.moving
    eng.stop()
    for _ in range(200):
        prev = eng.step(0.02)
    assert not eng.moving
    for leg, p in prev.items():
        assert p == pytest.approx(rest[leg], abs=1e-6)


def test_tripod_groups_alternate(cfg):
    eng = GaitEngine(cfg.legs, cfg.geometry, cfg.gait)
    eng.height = cfg.geometry.body_height_m
    eng.set_velocity(0.1, 0, 0)
    for _ in range(150):
        feet = eng.step(0.02)
    lifted = {leg for leg, p in feet.items() if p[2] > -eng.height + 1e-4}
    assert lifted in ({"LF", "RM", "LR"}, {"RF", "LM", "RR"}, set())


def test_stride_is_clamped(cfg):
    eng = GaitEngine(cfg.legs, cfg.geometry, cfg.gait)
    eng.height = cfg.geometry.body_height_m
    eng.set_velocity(10.0, 0, 0)  # way above max_vx
    for _ in range(300):
        eng.step(0.02)
    duty = GAITS["tripod"][0]
    assert eng.effective.vx * cfg.gait.period_s * duty <= cfg.gait.max_stride_m + 1e-9
    assert eng.effective.vx <= cfg.gait.max_vx + 1e-9
