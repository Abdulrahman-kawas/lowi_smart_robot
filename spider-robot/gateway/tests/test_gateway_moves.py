"""Expressive moves (Perform, Reach) at the gateway: who may start them, and how they end."""

import json

import pytest
from spider_common.link import InMemoryHub
from spider_common.protocol import EStop, Move, Perform, Reach, RobotEvent, Stop, Topics

from spider_gateway.gateway import Gateway, GatewayConfig
from spider_gateway.policy import DEFAULT_POLICIES, load_policies

ROBOT = "spider-01"
T = Topics(ROBOT)


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


async def rig_for(policies=None, bench=False):
    link = InMemoryHub().endpoint([])
    await link.start()
    clock = Clock()
    gw = Gateway(link, ROBOT, clock=clock, wall=lambda: 1000.0 + clock.now,
                 config=GatewayConfig(bench_enabled=bench), policies=policies)
    return gw, link, clock


def sent(link):
    return [json.loads(m.payload) for m in link.published if m.topic == T.cmd]


def replies(link, source):
    return [json.loads(m.payload) for m in link.published if m.topic == T.source_event(source)]


def perform(clock, name="dance", seq=1, session="s", **kw):
    return Perform(name=name, seq=seq, session=session, ts=1000.0 + clock.now,
                   **kw).model_dump_json()


def body_event(gw, kind, seq):
    gw.on_event(RobotEvent(robot_id=ROBOT, kind=kind, seq=seq).model_dump_json())


async def test_voice_and_bench_may_start_moves():
    gw, link, clock = await rig_for(bench=True)
    gw.on_request("voice", perform(clock))
    assert sent(link)[-1]["type"] == "perform" and sent(link)[-1]["name"] == "dance"
    gw.on_request("voice", Stop(seq=2, session="s", ts=1000.0 + clock.now).model_dump_json())
    clock.now += 3.0  # past the stop hold-off
    gw.on_request("bench", Reach(target=(0.3, 0.1, -0.03), seq=1, session="b",
                                 ts=1000.0 + clock.now).model_dump_json())
    assert sent(link)[-1]["type"] == "reach"


async def test_the_planner_may_never_start_a_move():
    gw, link, clock = await rig_for()
    gw.on_request("planner", perform(clock, session="p"))
    gw.on_request("planner", Reach(seq=2, session="p", ts=1000.0 + clock.now).model_dump_json())
    assert sent(link) == []
    assert [r["detail"] for r in replies(link, "planner")] == [
        "the planner may never start moves"] * 2


async def test_the_planner_cannot_be_configured_to_start_moves(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text("planner: {allow_moves: true}\n")
    with pytest.raises(ValueError, match="planner may never"):
        load_policies(path)


async def test_remote_moves_are_off_by_default_and_can_be_allowed(tmp_path):
    gw, link, clock = await rig_for()
    gw.on_request("remote", perform(clock, session="r"))
    assert sent(link) == []
    assert "allow_moves is off" in replies(link, "remote")[-1]["detail"]

    path = tmp_path / "policy.yaml"
    path.write_text("remote: {allow_moves: true}\n")
    gw, link, clock = await rig_for(policies=load_policies(path))
    gw.on_request("remote", perform(clock, session="r"))
    assert sent(link)[-1]["name"] == "dance"


async def test_offer_hand_only_with_someone_at_the_robot(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text("remote: {allow_moves: true}\n")
    gw, link, clock = await rig_for(policies=load_policies(path), bench=True)
    gw.on_request("remote", perform(clock, name="offer_hand", session="r"))
    gw.on_request("planner", perform(clock, name="offer_hand", session="p"))
    assert sent(link) == []
    assert "voice or bench only" in replies(link, "remote")[-1]["detail"]
    gw.on_request("voice", perform(clock, name="offer_hand", session="v"))
    assert sent(link)[-1]["name"] == "offer_hand"


async def test_a_move_owns_the_motion_until_the_body_says_done():
    gw, link, clock = await rig_for(policies={**DEFAULT_POLICIES})
    gw.on_request("voice", perform(clock, session="v"))
    out_seq = sent(link)[-1]["seq"]
    clock.now += 5.0  # long after a Move would have expired
    gw.on_request("voice", '{"type":"heartbeat","ts":%f}' % (1000.0 + clock.now))
    gw.on_request("planner", Move(vx=0.05, seq=1, session="p",
                                  ts=1000.0 + clock.now).model_dump_json())
    assert "busy: voice is in control" in replies(link, "planner")[-1]["detail"]
    body_event(gw, "perform_done", out_seq)
    assert replies(link, "voice")[-1]["kind"] == "perform_done"  # the source hears it
    gw.on_request("planner", Move(vx=0.05, seq=2, session="p",
                                  ts=1000.0 + clock.now).model_dump_json())
    assert sent(link)[-1]["type"] == "move"


@pytest.mark.parametrize("stopper", ["planner", "remote", "voice"])
async def test_a_stop_from_anyone_ends_a_move(stopper):
    gw, link, clock = await rig_for()
    gw.on_request("voice", perform(clock, session="v"))
    gw.on_request(stopper, Stop(seq=9, session="x", ts=1000.0 + clock.now).model_dump_json())
    assert sent(link)[-1]["type"] == "stop"
    assert gw.status(clock.now).owner is None


async def test_an_estop_ends_a_move():
    gw, link, clock = await rig_for()
    gw.on_request("voice", perform(clock, session="v"))
    gw.on_request("planner", EStop(seq=1, session="p", ts=1000.0 + clock.now).model_dump_json())
    assert sent(link)[-1]["type"] == "estop"


async def test_voice_taking_over_from_a_bench_move_stops_it_first():
    gw, link, clock = await rig_for(bench=True)
    gw.on_request("bench", perform(clock, session="b"))
    gw.on_request("voice", Move(vx=0.05, seq=1, session="v",
                                ts=1000.0 + clock.now).model_dump_json())
    assert [c["type"] for c in sent(link)] == ["perform", "stop", "move"]
    assert replies(link, "bench")[-1]["kind"] == "preempted"


async def test_a_move_sent_before_its_own_stop_is_dropped():
    gw, link, clock = await rig_for()
    gw.on_request("voice", Stop(seq=5, session="v", ts=1000.0 + clock.now).model_dump_json())
    gw.on_request("voice", perform(clock, seq=4, session="v"))
    assert [c["type"] for c in sent(link)] == ["stop"]


async def test_a_lost_voice_ends_its_move():
    gw, link, clock = await rig_for()
    gw.on_request("voice", perform(clock, session="v"))
    clock.now += 2.0  # no heartbeat from voice
    gw.tick()
    assert sent(link)[-1]["type"] == "stop"
    assert replies(link, "voice")[-1]["kind"] == "link_lost"
