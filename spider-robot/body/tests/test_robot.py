import asyncio
import json

import pytest
from spider_common.link import InMemoryHub
from spider_common.protocol import (
    BodyPose,
    EStop,
    EStopRelease,
    Heartbeat,
    Move,
    Posture,
    Snapshot,
    Stop,
    Topics,
)

from spider_body.hw.camera import FakeCamera
from spider_body.hw.lidar import SimLidar, SimWorld
from spider_body.hw.servos import FakeServoBank
from spider_body.robot import Robot


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(cfg, obstacles=None):
    clock = Clock()
    hub = InMemoryHub()
    t = Topics(cfg.robot_id)
    body_link = hub.endpoint([t.cmd])
    brain_link = hub.endpoint([t.event, t.state, t.camera_filter])
    body_link.connected.set()
    brain_link.connected.set()
    world = SimWorld(obstacles=obstacles if obstacles is not None else [])
    lidar = SimLidar(cfg.lidar, world, clock=clock)
    servos = FakeServoBank()
    robot = Robot(cfg, servos, lidar, FakeCamera(cfg.camera), body_link, clock=clock,
                  wall=lambda: 5000.0)
    return robot, servos, lidar, world, brain_link, clock


def run_ticks(robot, lidar, world, clock, seconds, hz=50, heartbeat=True):
    dt = 1 / hz
    for i in range(int(seconds * hz)):
        clock.t += dt
        if i % 10 == 0:
            lidar.scan()
            if heartbeat:
                robot.handle(Heartbeat(ts=5000.0))
        robot.tick(dt)
        e = robot.gait.effective
        world.integrate(e.vx, e.vy, e.wz, dt)


def events(link):
    return [json.loads(m.payload) for m in link.inbox.queue._queue if m.topic.endswith("/event")]


def stand(robot, lidar, world, clock):
    robot.handle(Posture(posture="stand", ts=5000.0))
    run_ticks(robot, lidar, world, clock, 3)
    assert robot.mode == "standing"


def test_starts_relaxed_and_stands(cfg):
    robot, servos, lidar, world, brain, clock = make(cfg)
    assert robot.mode == "relaxed"
    stand(robot, lidar, world, clock)
    assert robot.gait.height == pytest.approx(cfg.geometry.body_height_m)
    assert len(servos.last) == 19  # 18 legs + the camera pan, centred
    assert all(10 <= v <= 170 for v in servos.last.values())


def test_move_requires_standing(cfg):
    robot, *_rest, brain, clock = make(cfg)
    robot.handle(Move(vx=0.1, duration_s=1, seq=1, ts=5000.0))
    assert robot.move is None
    assert events(brain)[-1]["kind"] == "rejected"


def test_walk_forward_then_move_done(cfg):
    robot, servos, lidar, world, brain, clock = make(cfg)
    stand(robot, lidar, world, clock)
    robot.handle(Move(vx=0.1, duration_s=2.0, seq=5, ts=5000.0))
    run_ticks(robot, lidar, world, clock, 4)
    assert world.x > 0.1
    kinds = [e["kind"] for e in events(brain)]
    assert "move_done" in kinds
    assert robot.mode == "standing" and not robot.gait.moving


def test_obstacle_stops_robot(cfg):
    robot, servos, lidar, world, brain, clock = make(cfg, obstacles=[(0.6, 0.0, 0.1)])
    stand(robot, lidar, world, clock)
    robot.handle(Move(vx=0.1, duration_s=10.0, seq=9, ts=5000.0))
    run_ticks(robot, lidar, world, clock, 8)
    assert world.x < 0.6 - 0.1 - cfg.safety.stop_distance_m + 0.06  # stopped in front of it
    assert any(e["kind"] == "obstacle_stop" and e["seq"] == 9 for e in events(brain))


def test_link_loss_stops_robot(cfg):
    robot, servos, lidar, world, brain, clock = make(cfg)
    stand(robot, lidar, world, clock)
    robot.handle(Move(vx=0.1, duration_s=10.0, seq=3, ts=5000.0))
    run_ticks(robot, lidar, world, clock, 1)
    run_ticks(robot, lidar, world, clock, 3, heartbeat=False)
    assert robot.move is None
    assert any(e["kind"] == "link_lost" for e in events(brain))


def test_stale_command_rejected(cfg):
    robot, *_rest, brain, clock = make(cfg)
    robot.handle(Posture(posture="stand", ts=4990.0))  # 10 s old
    assert robot.mode == "relaxed"
    assert "stale" in events(brain)[-1]["detail"]


def test_estop_latches(cfg):
    robot, servos, lidar, world, brain, clock = make(cfg)
    stand(robot, lidar, world, clock)
    robot.handle(EStop(seq=1))
    robot.handle(Move(vx=0.1, duration_s=2, seq=2, ts=5000.0))
    assert robot.move is None and robot.mode == "estop"
    robot.handle(EStopRelease(seq=3, ts=5000.0))
    assert robot.mode == "standing"
    robot.handle(Move(vx=0.1, duration_s=2, seq=4, ts=5000.0))
    assert robot.move is not None


def test_relax_only_from_sitting(cfg):
    robot, servos, lidar, world, brain, clock = make(cfg)
    stand(robot, lidar, world, clock)
    robot.handle(Posture(posture="relax", ts=5000.0))
    assert robot.mode == "standing"
    robot.handle(Posture(posture="sit", ts=5000.0))
    run_ticks(robot, lidar, world, clock, 3)
    robot.handle(Posture(posture="relax", ts=5000.0))
    assert robot.mode == "relaxed" and servos.relaxed


async def test_snapshot_publishes_jpeg(cfg):
    robot, servos, lidar, world, brain, clock = make(cfg)
    robot.handle(Snapshot(request_id="abc", ts=5000.0))
    # The first use imports OpenCV, which takes seconds on a cold, busy machine.
    msg = await asyncio.wait_for(anext(brain.messages()), 60)
    assert msg.topic.endswith("/camera/abc")
    assert msg.payload[:2] == b"\xff\xd8"  # JPEG magic


def test_state_is_serialisable(cfg):
    robot, servos, lidar, world, brain, clock = make(cfg)
    lidar.scan()
    st = robot.state()
    assert json.loads(st.model_dump_json())["mode"] == "relaxed"


def test_late_move_after_stop_is_dropped(cfg):
    # Reviewer finding: MQTT may deliver an older Move after a newer Stop.
    robot, _servos, lidar, world, brain, clock = make(cfg)
    stand(robot, lidar, world, clock)
    robot.handle(Stop(seq=11, session="s1"))
    robot.handle(Move(vx=0.1, duration_s=2, seq=10, session="s1", ts=5000.0))
    assert robot.move is None
    robot.handle(Move(vx=0.1, duration_s=2, seq=12, session="s1", ts=5000.0))
    assert robot.move is not None


def test_stale_estop_release_is_rejected(cfg):
    robot, _servos, lidar, world, brain, clock = make(cfg)
    stand(robot, lidar, world, clock)
    robot.handle(EStop(ts=1000.0))  # stopping is accepted however old
    assert robot.estop
    robot.handle(EStopRelease(ts=1000.0))  # an hour-old release must not unlatch
    assert robot.estop


def test_wrong_protocol_version_rejected(cfg):
    robot, _servos, lidar, world, brain, clock = make(cfg)
    robot.handle(Posture(posture="stand", ts=5000.0, v=1))
    assert robot.mode == "relaxed"
    assert "protocol" in events(brain)[-1]["detail"]


def test_body_levels_before_walking(cfg):
    robot, _servos, lidar, world, brain, clock = make(cfg)
    stand(robot, lidar, world, clock)
    robot.handle(BodyPose(pitch_deg=15, ts=5000.0))
    run_ticks(robot, lidar, world, clock, 1)
    robot.handle(Move(vx=0.1, duration_s=2.0, ts=5000.0))
    run_ticks(robot, lidar, world, clock, 0.1)
    assert robot.limiter == "leveling body" and world.x == 0
    run_ticks(robot, lidar, world, clock, 1.5)
    assert world.x > 0



def walking(cfg, seq=7):
    robot, _servos, lidar, world, brain, clock = make(cfg)
    stand(robot, lidar, world, clock)
    robot.handle(Move(vx=0.1, duration_s=10.0, seq=seq, ts=5000.0))
    run_ticks(robot, lidar, world, clock, 1)
    assert robot.move is not None
    return robot, lidar, world, brain, clock


def test_a_lasting_lean_while_walking_stops_the_walk(cfg):
    robot, lidar, world, brain, clock = walking(cfg, seq=7)
    lidar.tilt = lambda: (2.0, 10.0)  # front feet up on a step
    run_ticks(robot, lidar, world, clock, cfg.safety.walk_tilt_s - 0.1)
    assert robot.move is not None  # not yet: one bump is not the ground
    run_ticks(robot, lidar, world, clock, 0.2)
    assert robot.move is None
    tilt = [e for e in events(brain) if e["kind"] == "tilt"]
    assert len(tilt) == 1 and tilt[0]["seq"] == 7
    assert tilt[0]["detail"] == "ground not level: roll=2 pitch=10; stopped"


def test_short_leans_while_walking_do_not_add_up(cfg):
    robot, lidar, world, brain, clock = walking(cfg)
    for _ in range(3):
        lidar.tilt = lambda: (0.0, -12.0)
        run_ticks(robot, lidar, world, clock, cfg.safety.walk_tilt_s - 0.1)
        lidar.tilt = lambda: (1.0, 0.5)
        run_ticks(robot, lidar, world, clock, 0.1)
    assert robot.move is not None
    assert not [e for e in events(brain) if e["kind"] == "tilt"]


def test_a_lean_below_walk_tilt_or_while_standing_does_not_stop(cfg):
    robot, lidar, world, brain, clock = walking(cfg)
    lidar.tilt = lambda: (cfg.safety.walk_tilt_deg - 1.0, 0.0)
    run_ticks(robot, lidar, world, clock, 2)
    assert robot.move is not None
    robot.handle(Stop(ts=5000.0))
    run_ticks(robot, lidar, world, clock, 2)
    lidar.tilt = lambda: (0.0, 15.0)  # standing on a slope is max_tilt's business
    run_ticks(robot, lidar, world, clock, 2)
    assert robot.mode == "standing"
    assert not [e for e in events(brain) if e["kind"] == "tilt"]


def test_estop_freezes_feet_without_jump(cfg):
    robot, servos, lidar, world, brain, clock = make(cfg)
    stand(robot, lidar, world, clock)
    robot.handle(Move(vx=0.1, duration_s=5.0, ts=5000.0))
    run_ticks(robot, lidar, world, clock, 1)
    before = dict(servos.last)
    robot.handle(EStop())
    run_ticks(robot, lidar, world, clock, 0.5)
    assert max(abs(servos.last[k] - before[k]) for k in before) < 3.0  # degrees
