import asyncio
import json
import time
from pathlib import Path

import pytest
from spider_body.config import load_config
from spider_body.hw.camera import FakeCamera
from spider_body.hw.lidar import SimLidar, SimWorld
from spider_body.hw.servos import FakeServoBank
from spider_body.main import command_loop, control_loop, state_loop
from spider_body.robot import Robot
from spider_common.link import InMemoryHub
from spider_common.protocol import (
    EStop,
    EStopRelease,
    Heartbeat,
    Move,
    Posture,
    RobotEvent,
    Stop,
    Topics,
)

from spider_gateway.gateway import Gateway

ROBOT = "spider-01"
SIM_CFG = Path(__file__).resolve().parents[2] / "body" / "config" / "robot.sim.yaml"
T = Topics(ROBOT)


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
async def rig():
    link = InMemoryHub().endpoint([])
    await link.start()
    clock = Clock()
    return Gateway(link, ROBOT, clock=clock, wall=lambda: 1000.0 + clock.now), link, clock


def sent(link):
    return [json.loads(m.payload) for m in link.published if m.topic == T.cmd]


def replies(link, source):
    return [json.loads(m.payload) for m in link.published if m.topic == T.source_event(source)]


def move(seq=1, session="s", ts=1200.0, duration=1.0):
    return Move(seq=seq, session=session, ts=ts, vx=0.05, duration_s=duration).model_dump_json()


def stop(seq=2, session="s", ts=1100.0):
    return Stop(seq=seq, session=session, ts=ts).model_dump_json()


def beat():
    return Heartbeat(ts=1100.0).model_dump_json()


async def test_all_sources_become_one_session_with_rising_seq(rig):
    gw, link, _ = rig
    gw.on_request("planner", move(seq=50, session="a"))
    gw.on_request("voice", move(seq=3, session="b"))
    out = sent(link)
    assert {c["session"] for c in out} == {gw.session}
    assert [c["seq"] for c in out] == [1, 2]


async def test_voice_takes_over_and_planner_waits_until_it_ends(rig):
    gw, link, clock = rig
    gw.on_request("voice", move(duration=2.0))
    gw.on_request("planner", move(seq=9, session="p"))
    assert len(sent(link)) == 1
    refused = replies(link, "planner")[-1]
    assert (refused["kind"], refused["seq"]) == ("rejected", 9)
    clock.now += 2.1
    gw.on_request("planner", move(seq=10, session="p"))
    assert len(sent(link)) == 2


async def test_voice_preempts_planner(rig):
    gw, link, _ = rig
    gw.on_request("planner", move(duration=5.0, session="p"))
    gw.on_request("voice", move(session="v"))
    assert len(sent(link)) == 2


async def test_stop_from_lowest_priority_source_always_passes(rig):
    gw, link, _ = rig
    gw.on_request("voice", move(duration=5.0))
    gw.on_request("planner", stop(session="p"))
    assert sent(link)[-1]["type"] == "stop"
    gw.on_request("planner", move(seq=5, session="p", ts=1300.0))
    assert sent(link)[-1]["type"] == "move"


async def test_late_move_from_same_session_is_fenced_silently(rig):
    gw, link, _ = rig
    gw.on_request("remote", stop(seq=5))
    gw.on_request("remote", move(seq=4))
    assert [c["type"] for c in sent(link)] == ["stop"]
    assert replies(link, "remote") == []


async def test_move_sent_before_another_sources_stop_is_refused(rig):
    gw, link, _ = rig
    gw.on_request("voice", stop(ts=1100.0, session="v"))
    gw.on_request("remote", move(seq=4, ts=1099.0, session="r"))
    assert [c["type"] for c in sent(link)] == ["stop"]
    assert replies(link, "remote")[-1]["kind"] == "rejected"


async def test_stop_with_future_clock_does_not_block_other_sources(rig):
    gw, link, clock = rig
    gw.on_request("voice", stop(ts=99999.0, session="v"))
    gw.on_request("remote", move(ts=1000.0 + clock.now, session="r"))
    assert sent(link)[-1]["type"] == "move"


async def test_lost_owner_stops_robot_and_voice_keeps_the_link(rig):
    gw, link, clock = rig
    gw.on_request("voice", beat())
    gw.on_request("remote", move(duration=9.0))
    clock.now += 1.0
    gw.on_request("voice", beat())
    clock.now += 1.0  # remote silent for 2 s, voice for 1 s
    gw.tick()
    types = [c["type"] for c in sent(link)]
    assert types == ["move", "stop", "heartbeat"]
    assert replies(link, "remote")[-1]["kind"] == "link_lost"
    gw.on_request("voice", move(session="v", ts=1000.0 + clock.now))
    assert sent(link)[-1]["type"] == "move"


async def test_live_owner_keeps_moving_and_gets_heartbeats(rig):
    gw, link, clock = rig
    gw.on_request("remote", move(duration=9.0))
    clock.now += 1.0
    gw.on_request("remote", beat())
    gw.tick()
    assert [c["type"] for c in sent(link)] == ["move", "heartbeat"]


async def test_no_heartbeat_when_every_source_is_gone(rig):
    gw, link, clock = rig
    gw.on_request("voice", beat())
    clock.now += 2.0
    gw.tick()
    assert sent(link) == []


async def test_only_owner_side_sources_can_release_estop(rig):
    gw, link, _ = rig
    gw.on_request("voice", EStop(seq=1, session="v", ts=1100.0).model_dump_json())
    release = EStopRelease(seq=2, session="p", ts=1200.0).model_dump_json()
    gw.on_request("planner", release)
    assert [c["type"] for c in sent(link)] == ["estop"]
    gw.on_request("remote", release)
    assert [c["type"] for c in sent(link)] == ["estop", "estop_release"]


async def test_invalid_command_is_rejected_to_its_source(rig):
    gw, link, _ = rig
    gw.on_request("voice", b'{"type": "fly"}')
    assert sent(link) == []
    assert replies(link, "voice")[-1]["kind"] == "rejected"


async def test_unknown_source_is_ignored(rig):
    gw, link, _ = rig
    gw.on_request("stranger", move())
    assert link.published == []


async def test_ack_returns_only_to_its_source_with_its_own_seq(rig):
    gw, link, _ = rig
    gw.on_request("remote", move(seq=77))
    body_seq = sent(link)[0]["seq"]
    gw.on_event(RobotEvent(robot_id=ROBOT, kind="ack", seq=body_seq).model_dump_json())
    assert replies(link, "remote")[-1]["seq"] == 77
    assert replies(link, "voice") == []


async def test_safety_event_reaches_every_source(rig):
    gw, link, _ = rig
    gw.on_request("remote", move(seq=77))
    body_seq = sent(link)[0]["seq"]
    gw.on_event(RobotEvent(robot_id=ROBOT, kind="fallen", seq=body_seq).model_dump_json())
    assert replies(link, "remote")[-1]["seq"] == 77
    assert replies(link, "voice")[-1]["kind"] == "fallen"
    assert replies(link, "voice")[-1]["seq"] is None


# ------------------------------------------------------------------ against the simulated body
async def _until(condition, timeout_s):
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        if condition():
            return True
        await asyncio.sleep(0.02)
    return False


async def _beats(link, source, hz=10.0):
    while True:
        link.publish(T.request(source), Heartbeat(ts=time.time()).model_dump_json())
        await asyncio.sleep(1.0 / hz)


async def test_simulated_body_stops_when_remote_source_disappears():
    cfg = load_config(SIM_CFG, calibration="/nonexistent")
    cfg.gait.posture_speed_mps = 0.2
    hub = InMemoryHub()
    world = SimWorld(obstacles=[])
    body_link = hub.endpoint([T.cmd])
    robot = Robot(cfg, FakeServoBank(), SimLidar(cfg.lidar, world), FakeCamera(cfg.camera),
                  body_link)
    gw_link = hub.endpoint(Gateway.subscriptions(ROBOT))
    remote = hub.endpoint([T.source_event("remote")])
    for link in (body_link, gw_link, remote):
        await link.start()
    gateway = Gateway(gw_link, ROBOT, source_timeout_s=0.4)
    tasks = [asyncio.create_task(c) for c in (
        control_loop(robot, world), command_loop(robot, body_link), state_loop(robot, body_link),
        robot.lidar.run(), gateway.run(tick_hz=20.0))]
    heart = asyncio.create_task(_beats(remote, "remote"))
    try:
        remote.publish(T.request("remote"), Posture(
            seq=7, session="r", ts=time.time(), posture="stand").model_dump_json())
        assert await _until(lambda: robot.mode == "standing" and robot._height_reached(), 15.0)
        events = []
        while not remote.inbox.queue.empty():  # "online" is broadcast too, so look for the ack
            events.append(RobotEvent.model_validate_json(remote.inbox.queue.get_nowait().payload))
        assert ("ack", 7) in [(ev.kind, ev.seq) for ev in events]

        remote.publish(T.request("remote"), Move(
            seq=8, session="r", ts=time.time(), vx=0.05, duration_s=9.0).model_dump_json())
        assert await _until(lambda: robot.move is not None, 3.0)

        heart.cancel()
        assert await _until(lambda: robot.move is None, 2.0)
    finally:
        heart.cancel()
        for task in tasks:
            task.cancel()
        await asyncio.gather(heart, *tasks, return_exceptions=True)
