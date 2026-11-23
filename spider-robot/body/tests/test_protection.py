from spider_common.protocol import (
    EStop,
    EStopRelease,
    Heartbeat,
    Move,
    Perform,
    Posture,
    Protection,
    Reach,
)
from test_robot import events, make, run_ticks, stand

TS = 5000.0


def protection_events(brain):
    return [e for e in events(brain) if e["kind"] == "protection"]


def test_protection_defaults_on_and_changes_only_on_edges(cfg):
    robot, _servos, _lidar, _world, brain, _clock = make(cfg)
    assert robot.state().protection is True

    robot.handle(Protection(enabled=False, ttl_s=2.0, seq=1, ts=TS))
    assert robot.state().protection is False
    assert protection_events(brain)[-1]["detail"] == "off: app"

    robot.handle(Protection(enabled=False, ttl_s=2.0, seq=2, ts=TS))
    assert robot.state().protection is False
    assert len(protection_events(brain)) == 1  # renewals do not spam events

    robot.handle(Protection(enabled=True, seq=3, ts=TS))
    assert robot.state().protection is True
    assert [e["detail"] for e in protection_events(brain)] == ["off: app", "on: app"]


def test_protection_expires_and_renewal_extends_ttl(cfg):
    robot, _servos, lidar, world, brain, clock = make(cfg)

    robot.handle(Protection(enabled=False, ttl_s=1.0, seq=1, ts=TS))
    run_ticks(robot, lidar, world, clock, 0.8)
    assert robot.state().protection is False

    robot.handle(Protection(enabled=False, ttl_s=1.0, seq=2, ts=TS))
    run_ticks(robot, lidar, world, clock, 0.8)
    assert robot.state().protection is False
    assert len(protection_events(brain)) == 1

    run_ticks(robot, lidar, world, clock, 0.3)
    assert robot.state().protection is True
    assert protection_events(brain)[-1]["detail"] == "on: expired"


def test_estop_and_relax_restore_protection(cfg):
    robot, _servos, lidar, world, brain, clock = make(cfg)
    stand(robot, lidar, world, clock)

    robot.handle(Protection(enabled=False, ttl_s=5.0, seq=1, ts=TS))
    robot.handle(EStop(seq=2))
    assert robot.state().protection is True
    assert protection_events(brain)[-1]["detail"] == "on: estop"
    robot.handle(EStopRelease(seq=3, ts=TS))

    robot.handle(Protection(enabled=False, ttl_s=5.0, seq=4, ts=TS))
    robot.handle(Posture(posture="relax", ts=TS, seq=5))
    assert robot.state().protection is True
    assert protection_events(brain)[-1]["detail"] == "on: relax"


def test_estop_refuses_to_turn_protection_off(cfg):
    robot, _servos, lidar, world, brain, clock = make(cfg)
    stand(robot, lidar, world, clock)
    robot.handle(EStop(seq=1))
    robot.handle(Protection(enabled=False, ttl_s=2.0, seq=2, ts=TS))

    assert robot.state().protection is True
    assert not protection_events(brain)
    assert any(e["kind"] == "rejected" and "estop" in e["detail"] for e in events(brain))


def test_off_skips_obstacle_stop(cfg):
    def walk(off):
        robot, _servos, lidar, world, brain, clock = make(cfg, obstacles=[(0.6, 0.0, 0.1)])
        stand(robot, lidar, world, clock)
        if off:
            robot.handle(Protection(enabled=False, ttl_s=5.0, seq=1, ts=TS))
        robot.handle(Move(vx=0.1, duration_s=5.0, seq=2, ts=TS))
        run_ticks(robot, lidar, world, clock, 5.0)
        return world.x, [e["kind"] for e in events(brain)]

    protected_x, protected_kinds = walk(False)
    skipped_x, skipped_kinds = walk(True)
    assert "obstacle_stop" in protected_kinds
    assert "obstacle_stop" not in skipped_kinds
    assert skipped_x > protected_x + 0.05


def test_off_skips_stale_lidar_and_unknown_tilt(cfg):
    robot, _servos, lidar, world, brain, clock = make(cfg)
    stand(robot, lidar, world, clock)
    lidar.scan = lambda: None
    lidar.tilt = lambda: (None, None)
    robot.handle(Protection(enabled=False, ttl_s=5.0, seq=1, ts=TS))
    robot.handle(Move(vx=0.1, duration_s=2.0, seq=2, ts=TS))
    run_ticks(robot, lidar, world, clock, 1.0)

    assert robot.move is not None
    assert world.x > 0.0
    assert not any(e["kind"] in ("error", "obstacle_stop") for e in events(brain))


def test_known_tilt_still_stops_with_protection_off(cfg):
    robot, _servos, lidar, world, brain, clock = make(cfg)
    stand(robot, lidar, world, clock)
    lidar.tilt = lambda: (35.0, 0.0)
    robot.handle(Protection(enabled=False, ttl_s=5.0, seq=1, ts=TS))
    robot.handle(Move(vx=0.1, duration_s=2.0, seq=2, ts=TS))
    run_ticks(robot, lidar, world, clock, 0.2)

    assert robot.move is None
    assert any(e["kind"] == "tilt" for e in events(brain))


def test_reach_nearest_without_lidar_is_a_refusal_not_a_crash(cfg):
    robot, _servos, lidar, world, brain, _clock = make(cfg)
    stand(robot, lidar, world, _clock)
    lidar.latest = lambda: (None, None)
    robot.handle(Protection(enabled=False, ttl_s=5.0, seq=1, ts=TS))
    robot.handle(Reach(target="nearest", seq=2, ts=TS))

    rejected = [e for e in events(brain) if e["kind"] == "perform_rejected"]
    assert rejected and "nothing within reach" in rejected[-1]["detail"]
    assert robot.perform is None


def test_runtime_obstacle_checks_are_skipped_while_off(cfg):
    robot, _servos, lidar, world, brain, clock = make(cfg)
    stand(robot, lidar, world, clock)
    robot.handle(Protection(enabled=False, ttl_s=5.0, seq=1, ts=TS))
    robot.handle(Perform(name="dance", seq=2, ts=TS))
    assert robot.perform is not None

    lidar.latest = lambda: (None, None)
    lidar.tilt = lambda: (None, None)
    for i in range(50):
        clock.t += 0.02
        if i % 10 == 0:
            robot.handle(Heartbeat(ts=TS))
        robot.tick(0.02)

    assert robot.perform is not None
    assert not any(e["kind"] in ("error", "obstacle_stop") for e in events(brain))
