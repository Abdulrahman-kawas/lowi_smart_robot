import math

import numpy as np
import pytest
from spider_common.protocol import (
    MOVE_NAMES,
    BodyPose,
    EStop,
    EStopRelease,
    Move,
    Perform,
    Posture,
    Reach,
    Stop,
)
from test_robot import events, make, run_ticks

from spider_body.moves import (
    ATTACK_MAX_SHIFT_M,
    LEGS,
    OFFER_CLEAR_M,
    Choreo,
    Geometry,
    MoveLibrary,
    Runner,
    validate,
)

TS = 5000.0  # the test robot's wall clock
SIDED = ("wave", "hi", "offer_hand")
CASES = [(n, leg) for n in MOVE_NAMES for leg in (("LF", "RF") if n in SIDED else (None,))]


def stood(cfg, obstacles=None):
    robot, servos, lidar, world, brain, clock = make(cfg, obstacles)
    robot.handle(Posture(posture="stand", ts=TS))
    run_ticks(robot, lidar, world, clock, 3)
    assert robot.mode == "standing"
    return robot, servos, lidar, world, brain, clock


def kinds(brain):
    return [e["kind"] for e in events(brain)]


def last(brain, kind):
    return [e for e in events(brain) if e["kind"] == kind][-1]


def tick(robot, lidar, world, clock, n=1):
    run_ticks(robot, lidar, world, clock, n / 50)


# ------------------------------------------------------------------ the validator
@pytest.mark.parametrize(("name", "leg"), CASES)
@pytest.mark.parametrize("speed", [0.5, 1.0])
def test_every_builtin_move_passes_the_validator(cfg, name, leg, speed):
    lib = MoveLibrary(cfg)
    rep = validate(lib.geo, lib.get(name, leg), speed)
    assert rep.ok, rep.reason
    assert rep.duration_s <= 20.0
    assert rep.max_joint_dps <= cfg.moves.max_joint_speed_dps
    assert rep.min_margin_m >= cfg.moves.support_margin_m


@pytest.mark.parametrize(("name", "leg"), CASES)
def test_body_translation_stays_within_3_cm(cfg, name, leg):
    lib = MoveLibrary(cfg)
    rep = validate(lib.geo, lib.get(name, leg), 0.5, keep=True)
    shift = np.hypot(rep.body[:, 4], rep.body[:, 5])
    assert shift.max() < 0.03
    if name == "attack_stance":
        assert shift.max() <= ATTACK_MAX_SHIFT_M


def test_speed_caps_and_time_scaling(cfg):
    lib = MoveLibrary(cfg)
    assert Runner(lib.get("attack_stance"), 1.0).speed == 0.7
    assert Runner(lib.get("offer_hand"), 1.0).speed == 0.4
    bow = lib.get("bow")
    assert bow.duration(1.0) == pytest.approx(bow.duration(0.5) / 2)
    # holds marked fixed keep their length: sleep breathes for 6 s at any speed
    sleep = lib.get("sleep")
    assert sleep.duration(1.0) - 6.0 == pytest.approx((sleep.duration(0.5) - 6.0) / 2)


def test_dance_is_16_s_at_the_default_tempo(cfg):
    lib = MoveLibrary(cfg)
    assert lib.get("dance").duration(0.5) == pytest.approx(16.0, abs=0.3)


def test_a_too_slow_request_is_refused_not_cut(cfg):
    lib = MoveLibrary(cfg)
    rep = validate(lib.geo, lib.get("dance"), 0.3)
    assert not rep.ok and "at most 20 s" in rep.reason


def _check(cfg, build):
    c = Choreo()
    build(c)
    return validate(Geometry(cfg), c.spec("test"), 0.5)


def test_validator_refuses_each_broken_rule(cfg):
    rep = _check(cfg, lambda c: c.lift(0.5, ["LF", "LM", "LR", "RF"], 0.02).lift(0.5, LEGS, 0.0))
    assert "fewer than 3 feet" in rep.reason
    rep = _check(cfg, lambda c: c.to(0.5, LF=(0.03, 0.0, 0.0)).to(0.5, LF=(0.0, 0.0, 0.0)))
    assert "slides" in rep.reason
    rep = _check(cfg, lambda c: c.to(0.8, x=0.04).to(0.8, x=0.0))
    assert "from where it started" in rep.reason
    rep = _check(cfg, lambda c: c.lift(0.5, ["LF"], 0.08).lift(0.5, ["LF"], 0.0))
    assert "LF.femur would need" in rep.reason  # straight up past the servo limit
    rep = _check(cfg, lambda c: c.lift(0.05, ["LM"], 0.03).lift(0.05, ["LM"], 0.0))
    assert "deg/s" in rep.reason
    # three feet left, all on one side of the body: the centre is outside them
    rep = _check(cfg, lambda c: c.lift(0.5, ["RF", "RM", "RR"], 0.02).lift(0.5, LEGS, 0.0))
    assert "inside the feet" in rep.reason
    rep = _check(cfg, lambda c: c.to(0.5, dz=-0.07).to(0.5, dz=0.0))
    assert "body height" in rep.reason


def test_numpy_kinematics_match_robot_solve(cfg):
    robot = make(cfg)[0]
    geo = robot.moves.geo
    rng = np.random.default_rng(1)
    compared = 0
    while compared < 20:
        body = np.array([rng.uniform(-0.02, 0.02), *rng.uniform(-8, 8, 3),
                         *rng.uniform(-0.02, 0.02, 2)])
        feet = np.zeros((6, 3))
        feet[:, :2] = rng.uniform(-0.02, 0.02, (6, 2))
        feet[:, 2] = rng.uniform(0.0, 0.03, 6)
        deg, ok = geo.servo_deg(body[None], feet[None])
        if not ok.all() or np.any(deg[0] < geo.lo) or np.any(deg[0] > geo.hi):
            continue  # Robot.solve clamps there; the validator refuses such a frame anyway
        compared += 1
        pts, pose, _ = geo.to_robot(body, feet)
        robot.pose = pose
        out = robot.solve(pts)
        assert out is not None
        for i, leg in enumerate(LEGS):
            for j, joint in enumerate(("coxa", "femur", "tibia")):
                assert out[f"{leg}.{joint}"] == pytest.approx(deg[0, i, j], abs=1e-6)


# ------------------------------------------------------------------ running on the robot
def test_a_move_plays_and_ends_in_the_neutral_stand(cfg):
    robot, servos, lidar, world, brain, clock = stood(cfg)
    neutral = dict(servos.last)
    robot.handle(Perform(name="hi", ts=TS, seq=5))
    assert robot.state().perform == "hi" and robot.mode == "standing"
    run_ticks(robot, lidar, world, clock, 2.0)
    assert max(abs(servos.last[k] - neutral[k]) for k in neutral) > 5.0  # really moving
    run_ticks(robot, lidar, world, clock, 4.0)
    assert kinds(brain)[-2:] == ["perform_started", "perform_done"]
    assert last(brain, "perform_done")["seq"] == 5
    assert max(abs(servos.last[k] - neutral[k]) for k in neutral) < 1e-6
    assert (world.x, world.y, world.yaw) == (0.0, 0.0, 0.0)
    robot.handle(Move(vx=0.05, duration_s=0.5, ts=TS, seq=6))  # walking works again
    assert robot.move is not None


def test_stop_halts_a_move_within_one_tick_and_stand_brings_it_back(cfg):
    robot, servos, lidar, world, brain, clock = stood(cfg)
    neutral = dict(servos.last)
    robot.handle(Perform(name="wave", ts=TS, seq=5))
    run_ticks(robot, lidar, world, clock, 1.5)
    robot.handle(Stop(ts=TS, seq=6))
    assert robot.perform is None
    assert last(brain, "perform_done")["detail"] == "wave interrupted: stop"
    tick(robot, lidar, world, clock)
    held = dict(servos.last)
    run_ticks(robot, lidar, world, clock, 1.0)
    assert servos.last == held  # nothing moves after the Stop
    assert robot.state().limiter == "holding a move pose; send stand"

    robot.handle(Move(vx=0.05, ts=TS, seq=7))
    assert last(brain, "rejected")["detail"] == "holding the last move pose; send stand first"
    robot.handle(BodyPose(pitch_deg=5, ts=TS, seq=8))
    assert last(brain, "rejected")["seq"] == 8

    robot.handle(Posture(posture="stand", ts=TS, seq=9))
    assert robot.state().perform == "recover"
    run_ticks(robot, lidar, world, clock, 8.0)
    assert last(brain, "perform_done")["detail"] == "recover done"
    assert max(abs(servos.last[k] - neutral[k]) for k in neutral) < 1e-6


def test_estop_freezes_a_move(cfg):
    robot, servos, lidar, world, brain, clock = stood(cfg)
    robot.handle(Perform(name="dance", ts=TS, seq=5))
    run_ticks(robot, lidar, world, clock, 3.0)
    robot.handle(EStop(ts=TS, seq=6))
    tick(robot, lidar, world, clock)
    frozen = dict(servos.last)
    run_ticks(robot, lidar, world, clock, 2.0)
    assert servos.last == frozen and robot.mode == "estop"
    assert last(brain, "perform_done")["detail"] == "dance interrupted: estop"
    robot.handle(Perform(name="bow", ts=TS, seq=7))
    assert "estop is latched" in last(brain, "perform_rejected")["detail"]
    robot.handle(EStopRelease(ts=TS, seq=8))
    run_ticks(robot, lidar, world, clock, 0.5)
    assert servos.last == frozen and robot.mode == "standing"  # still held after the release
    robot.handle(Posture(posture="sit", ts=TS, seq=9))  # back to the stand, then down
    run_ticks(robot, lidar, world, clock, 12.0)
    assert robot.mode == "sitting" and robot.perform is None


def test_moves_are_refused_while_sitting(cfg):
    robot, _, lidar, world, brain, clock = make(cfg)
    robot.handle(Posture(posture="sit", ts=TS))
    run_ticks(robot, lidar, world, clock, 2)
    robot.handle(Perform(name="dance", ts=TS, seq=3))
    assert last(brain, "perform_rejected")["detail"] == \
        "dance: cannot start a move while sitting; stand first"
    assert robot.perform is None


def test_moves_are_refused_with_an_obstacle_in_the_clear_radius(cfg):
    # 0.30 m ahead of the footprint edge (0.24 m): inside the 0.35 m clear radius
    robot, _, _, _, brain, _ = stood(cfg, obstacles=[(0.24 + 0.30 + 0.05, 0.0, 0.05)])
    robot.handle(Perform(name="bow", ts=TS, seq=3))
    detail = last(brain, "perform_rejected")["detail"]
    assert detail.startswith("bow: obstacle 0.30 m from the legs") and "0.35 m clear" in detail


def test_attack_stance_is_refused_with_someone_close(cfg):
    robot, _, _, _, brain, _ = stood(cfg, obstacles=[(0.55, 0.1, 0.1)])
    robot.handle(Perform(name="attack_stance", speed=1.0, ts=TS, seq=3))
    assert "obstacle" in last(brain, "perform_rejected")["detail"]
    assert robot.perform is None


def test_moves_are_refused_with_stale_lidar(cfg):
    robot, _, lidar, world, brain, clock = stood(cfg)
    clock.t += 1.0  # no new scan for a second
    robot.handle(Perform(name="shimmy", ts=TS, seq=3))
    assert last(brain, "perform_rejected")["detail"] == "shimmy: LiDAR data is stale"


def test_a_move_stops_when_something_comes_close(cfg):
    robot, _, lidar, world, brain, clock = stood(cfg)
    robot.handle(Perform(name="crab_sway", ts=TS, seq=3))
    run_ticks(robot, lidar, world, clock, 1.0)
    world.obstacles.append((0.45, 0.0, 0.05))
    run_ticks(robot, lidar, world, clock, 0.5)
    assert "obstacle_stop" in kinds(brain) and robot.perform is None


def test_a_move_after_a_move_needs_the_first_to_end(cfg):
    robot, _, lidar, world, brain, clock = stood(cfg)
    robot.handle(Perform(name="bow", ts=TS, seq=3))
    robot.handle(Perform(name="shimmy", ts=TS, seq=4))
    assert last(brain, "perform_rejected")["detail"] == "shimmy: bow is running; send stop first"


# ------------------------------------------------------------------ reach
def _foot_track(lib, spec, leg):
    rep = validate(lib.geo, spec, 0.5, keep=True)
    assert rep.ok, rep.reason
    i = LEGS.index(leg)
    xy = lib.geo.neutral[i] + rep.feet[:, i, :2]
    return np.column_stack([xy, rep.feet[:, i, 2]]), rep


def test_reach_stops_1_cm_short_of_the_target(cfg):
    lib = MoveLibrary(cfg)
    target = (0.30, 0.12, -0.03)  # body frame
    spec = lib.reach(None, target)
    foot, _ = _foot_track(lib, spec, "LF")
    goal = np.array([target[0], target[1], target[2] + cfg.geometry.body_height_m])
    dist = np.linalg.norm(foot - goal, axis=1)
    assert dist.min() == pytest.approx(0.01, abs=1e-4)
    held = dist < 0.0101
    assert held.sum() * 0.01 >= 1.0  # held there for 1 s


def test_reach_refuses_an_unreachable_target(cfg):
    robot, _, _, _, brain, _ = stood(cfg)
    robot.handle(Reach(target=(0.48, 0.0, 0.0), ts=TS, seq=3))
    assert "cannot reach" in last(brain, "perform_rejected")["detail"]
    robot.handle(Reach(target=(0.3, 0.1, -0.2), ts=TS, seq=4))
    assert "below the floor" in last(brain, "perform_rejected")["detail"]


def test_reach_nearest_touches_the_closest_thing_ahead(cfg):
    robot, servos, lidar, world, brain, clock = stood(cfg, obstacles=[(0.36, 0.10, 0.05)])
    robot.handle(Reach(target="nearest", ts=TS, seq=3))
    started = last(brain, "perform_started")["detail"]
    assert started.startswith("reach:") and "LF to" in started
    run_ticks(robot, lidar, world, clock, 12)
    assert last(brain, "perform_done")["detail"] == "reach done"


def test_reach_nearest_refuses_when_nothing_is_in_reach(cfg):
    robot, _, _, _, brain, _ = stood(cfg)  # empty 4 m room
    robot.handle(Reach(target="nearest", ts=TS, seq=3))
    assert "nothing within reach" in last(brain, "perform_rejected")["detail"]


# ------------------------------------------------------------------ offer_hand
def test_offer_hand_never_goes_beyond_its_fixed_point(cfg):
    lib = MoveLibrary(cfg)
    for leg in ("LF", "RF"):
        spec = lib.get("offer_hand", leg)
        foot, _ = _foot_track(lib, spec, leg)
        tx = cfg.geometry.footprint_x_m + cfg.moves.offer_hand_ahead_m
        assert spec.target[0] == pytest.approx(tx)
        assert foot[:, 0].max() <= tx + 1e-9
        out = foot[:, 0] > tx - 1e-6
        assert out.sum() * 0.01 > 5.0  # held out there (at speed 0.4 this is a real-time 0.01 s)
        assert np.all(np.abs(foot[out, 2] - cfg.moves.offer_hand_height_m) <= 0.02 + 1e-9)


def test_offer_hand_allows_a_person_in_front_but_not_within_5_cm_of_the_foot(cfg):
    tx = cfg.geometry.footprint_x_m + cfg.moves.offer_hand_ahead_m
    robot, _, _, _, brain, _ = stood(cfg, obstacles=[(0.7, 0.0, 0.15)])  # someone in front
    robot.handle(Perform(name="offer_hand", ts=TS, seq=3))
    assert kinds(brain)[-1] == "perform_started"

    near = tx + OFFER_CLEAR_M * 0.6  # a hand 3 cm beyond the foot point
    robot, _, _, _, brain, _ = stood(cfg, obstacles=[(near + 0.02, 0.145, 0.02)])
    robot.handle(Perform(name="offer_hand", ts=TS, seq=3))
    assert "within 5 cm of where the foot would go" in last(brain, "perform_rejected")["detail"]


def test_a_stop_while_the_hand_is_out_retracts_within_one_tick(cfg):
    robot, servos, lidar, world, brain, clock = stood(cfg)
    neutral = dict(servos.last)
    robot.handle(Perform(name="offer_hand", ts=TS, seq=3))
    run_ticks(robot, lidar, world, clock, 7.0)  # out and holding
    geo = robot.moves.geo
    foot_x = geo.neutral[0, 0] + robot._frame[1][0, 0]
    assert foot_x > geo.footprint[0]
    robot.handle(Stop(ts=TS, seq=4))
    assert robot.state().perform == "recover"
    xs = []
    for _ in range(10):
        tick(robot, lidar, world, clock)
        xs.append(geo.neutral[0, 0] + robot._frame[1][0, 0])
    assert xs[0] <= foot_x and xs[-1] < foot_x - 0.001  # on its way back from the first tick
    assert all(b <= a + 1e-9 for a, b in zip(xs, xs[1:], strict=False))
    run_ticks(robot, lidar, world, clock, 8)
    assert last(brain, "perform_done")["detail"] == "recover done"
    assert max(abs(servos.last[k] - neutral[k]) for k in neutral) < 1e-6


def test_offer_hand_with_the_right_leg(cfg):
    robot, _, lidar, world, brain, clock = stood(cfg)
    robot.handle(Perform(name="offer_hand", leg="RF", ts=TS, seq=3))
    run_ticks(robot, lidar, world, clock, 5.0)
    assert robot._frame[1][LEGS.index("RF"), 2] > 0.1 and robot._frame[1][0, 2] == 0.0


def test_unreachable_offer_point_is_refused_with_the_reason(cfg):
    cfg.moves.offer_hand_ahead_m = 0.10  # the default: past these legs' reach
    robot, _, _, _, brain, _ = stood(cfg)
    robot.handle(Perform(name="offer_hand", ts=TS, seq=3))
    assert "LF cannot reach its foot point" in last(brain, "perform_rejected")["detail"]
    assert math.isclose(cfg.moves.offer_hand_height_m, 0.12)


@pytest.mark.parametrize(("name", "leg"), CASES)
def test_a_stop_at_any_moment_can_return_to_stand(cfg, name, leg):
    lib = MoveLibrary(cfg)
    runner = Runner(lib.get(name, leg), 0.5)
    for t in np.arange(0.0, runner.duration, 0.4):
        runner.elapsed = float(t)
        _, rep = lib.recovery(*runner.frame())
        assert rep.ok, (t, rep.reason)


async def test_shutdown_during_a_move_returns_to_stand_then_sits(cfg):
    import asyncio

    from spider_body.main import sit_and_relax

    robot, servos, lidar, world, brain, clock = stood(cfg)
    robot.handle(Perform(name="hi", ts=TS, seq=3))
    run_ticks(robot, lidar, world, clock, 1.5)  # a front leg is up

    async def ticker():
        while True:
            run_ticks(robot, lidar, world, clock, 0.2)
            await asyncio.sleep(0)

    task = asyncio.create_task(ticker())
    await sit_and_relax(robot)
    task.cancel()
    assert robot.mode == "sitting" and robot._frame is None and servos.relaxed
    assert robot.gait.height == pytest.approx(cfg.geometry.sit_height_m, abs=0.003)
    assert last(brain, "perform_done")["detail"] == "recover done"
