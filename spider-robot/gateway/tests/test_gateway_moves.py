"""Expressive moves (Perform, Reach) at the gateway: who may start them, and how they end."""

import json
import tempfile
from pathlib import Path

import pytest
from spider_common.link import InMemoryHub
from spider_common.protocol import (
    EStop,
    Move,
    MovesSwitch,
    Perform,
    Reach,
    RobotEvent,
    RobotState,
    Stop,
    Topics,
)

from spider_gateway.gateway import Gateway, GatewayConfig
from spider_gateway.policy import DEFAULT_POLICIES, load_policies

ROBOT = "spider-01"
T = Topics(ROBOT)


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


async def rig_for(policies=None, bench=False, state_dir=None, enable_remote=True):
    link = InMemoryHub().endpoint([])
    await link.start()
    clock = Clock()
    config = GatewayConfig(bench_enabled=bench,
                           state_dir=state_dir or Path(tempfile.mkdtemp(prefix="spider-moves-")))
    gw = Gateway(link, ROBOT, clock=clock, wall=lambda: 1000.0 + clock.now,
                 config=config, policies=policies)
    if enable_remote:
        gw.on_request("remote", MovesSwitch(remote=True, ts=1000.0 + clock.now).model_dump_json())
        link.published.clear()
    return gw, link, clock


def sent(link):
    return [json.loads(m.payload) for m in link.published if m.topic == T.cmd]


def replies(link, source):
    return [json.loads(m.payload) for m in link.published if m.topic == T.source_event(source)]


def perform(clock, name="dance", seq=1, session="s", **kw):
    return Perform(name=name, seq=seq, session=session, ts=1000.0 + clock.now,
                   **kw).model_dump_json()


def body_state(gw, mode="standing", estop=False):
    gw.on_state(RobotState(robot_id=ROBOT, mode=mode, estop=estop).model_dump_json())


def body_event(gw, kind, seq):
    gw.on_event(RobotEvent(robot_id=ROBOT, kind=kind, seq=seq).model_dump_json())


async def test_voice_and_bench_may_start_moves():
    gw, link, clock = await rig_for(bench=True)
    gw.on_request("voice", perform(clock))
    assert sent(link)[-1]["type"] == "perform" and sent(link)[-1]["name"] == "dance"
    gw.on_request("voice", Stop(seq=2, session="s", ts=1000.0 + clock.now).model_dump_json())
    clock.now += 3.0
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


async def test_remote_moves_need_fresh_standing_telemetry():
    gw, link, clock = await rig_for()
    gw.on_request("remote", perform(clock, session="r"))
    assert sent(link) == []
    assert replies(link, "remote")[-1]["detail"] == "moves from remote need the robot standing"

    body_state(gw)
    gw.on_request("remote", perform(clock, session="r"))
    assert sent(link)[-1]["name"] == "dance"

    gw.on_request("planner", Stop(seq=1, session="p", ts=1000.0 + clock.now).model_dump_json())
    clock.now += 2.0
    gw.on_request("remote", perform(clock, seq=2, session="r"))
    assert sent(link)[-1]["type"] == "stop"
    assert replies(link, "remote")[-1]["detail"] == "moves from remote need the robot standing"

    body_state(gw, mode="sitting")
    gw.on_request("remote", perform(clock, seq=3, session="r"))
    assert replies(link, "remote")[-1]["detail"] == "moves from remote need the robot standing"

    body_state(gw, estop=True)
    gw.on_request("remote", perform(clock, seq=4, session="r"))
    assert replies(link, "remote")[-1]["detail"] == "moves from remote need the robot standing"


async def test_a_policy_speed_cap_clamps_a_move(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text("remote: {max_move_speed: 0.4}\n")
    gw, link, clock = await rig_for(policies=load_policies(path))
    body_state(gw)
    gw.on_request("remote", perform(clock, session="r", speed=0.8))
    assert sent(link)[-1]["speed"] == 0.4
    assert replies(link, "remote")[-1]["kind"] == "clamped"
    assert "0.4" in replies(link, "remote")[-1]["detail"]


@pytest.mark.parametrize("name", ["hi", "double_hi", "offer_hand"])
async def test_every_greeting_move_is_open_to_the_app(name):
    gw, link, clock = await rig_for()
    body_state(gw)
    gw.on_request("remote", perform(clock, name=name, session="r"))
    assert sent(link)[-1]["name"] == name


async def test_a_move_closed_in_the_policy_is_only_local(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text("remote: {local_only_moves: [offer_hand]}\n")
    gw, link, clock = await rig_for(policies=load_policies(path), bench=True)
    body_state(gw)
    gw.on_request("remote", perform(clock, name="offer_hand", session="r"))
    assert sent(link) == []
    assert "is closed to remote" in replies(link, "remote")[-1]["detail"]

    gw.on_request("voice", perform(clock, name="offer_hand", session="v"))
    assert sent(link)[-1]["name"] == "offer_hand"
    gw.on_request("planner", Stop(seq=2, session="p", ts=1000.0 + clock.now).model_dump_json())
    clock.now += 3.0
    gw.on_request("bench", perform(clock, name="offer_hand", seq=1, session="b"))
    assert sent(link)[-1]["name"] == "offer_hand"


async def test_reach_stays_local():
    gw, link, clock = await rig_for()
    body_state(gw)
    gw.on_request("remote", Reach(target=(0.3, 0.1, -0.03), seq=1, session="r",
                                  ts=1000.0 + clock.now).model_dump_json())
    assert sent(link) == []
    assert "reach needs someone at the robot" in replies(link, "remote")[-1]["detail"]


async def test_a_move_owns_the_motion_until_the_body_says_done():
    gw, link, clock = await rig_for(policies={**DEFAULT_POLICIES})
    gw.on_request("voice", perform(clock, session="v"))
    out_seq = sent(link)[-1]["seq"]
    clock.now += 5.0
    gw.on_request("voice", '{"type":"heartbeat","ts":%f}' % (1000.0 + clock.now))
    gw.on_request("planner", Move(vx=0.05, seq=1, session="p",
                                  ts=1000.0 + clock.now).model_dump_json())
    assert "busy: voice is in control" in replies(link, "planner")[-1]["detail"]
    body_event(gw, "perform_done", out_seq)
    assert replies(link, "voice")[-1]["kind"] == "perform_done"
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
    clock.now += 2.0
    gw.tick()
    assert sent(link)[-1]["type"] == "stop"
    assert replies(link, "voice")[-1]["kind"] == "link_lost"


async def test_the_switch_controls_both_sources(tmp_path):
    gw, link, clock = await rig_for(state_dir=tmp_path, enable_remote=False)
    assert gw.status(clock.now).moves == {"voice": True, "remote": False}
    body_state(gw)
    gw.on_request("remote", perform(clock, session="r"))
    assert sent(link) == []
    assert replies(link, "remote")[-1]["detail"] == "moves from remote are switched off"

    gw.on_request("remote", MovesSwitch(voice=False, remote=True,
                                        ts=1000.0 + clock.now).model_dump_json())
    assert gw.status(clock.now).moves == {"voice": False, "remote": True}
    assert replies(link, "remote")[-1]["detail"] == "moves: voice off, remote on"
    gw.on_request("remote", perform(clock, seq=2, session="r"))
    assert sent(link)[-1]["name"] == "dance"
    gw.on_request("voice", perform(clock, seq=2, session="v"))
    assert replies(link, "voice")[-1]["detail"] == "moves from voice are switched off"


async def test_the_switch_survives_a_gateway_restart(tmp_path):
    gw, link, clock = await rig_for(state_dir=tmp_path, enable_remote=False)
    gw.on_request("remote", MovesSwitch(remote=True, ts=1000.0 + clock.now).model_dump_json())
    assert json.loads((tmp_path / "moves.json").read_text("utf-8")) == {
        "remote": True, "voice": True,
    }
    restarted = Gateway(link, ROBOT, clock=clock, wall=lambda: 1000.0 + clock.now,
                        config=GatewayConfig(state_dir=tmp_path))
    assert restarted.status(clock.now).moves == {"voice": True, "remote": True}


async def test_the_planner_may_not_change_the_moves_switch(tmp_path):
    gw, link, clock = await rig_for(state_dir=tmp_path, enable_remote=False)
    gw.on_request("planner", MovesSwitch(remote=True,
                                         ts=1000.0 + clock.now).model_dump_json())
    assert sent(link) == []
    assert replies(link, "planner")[-1]["detail"] == "the planner may not change the moves switch"
    assert gw.status(clock.now).moves["remote"] is False


async def test_a_policy_that_forbids_moves_cannot_be_switched_on(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text("remote: {allow_moves: false}\n")
    gw, link, clock = await rig_for(policies=load_policies(path), state_dir=tmp_path,
                                    enable_remote=False)
    gw.on_request("remote", MovesSwitch(remote=True, ts=1000.0 + clock.now).model_dump_json())
    assert "allow_moves is off" in replies(link, "remote")[-1]["detail"]
    assert gw.status(clock.now).moves["remote"] is False
    gw.on_request("remote", MovesSwitch(voice=False, remote=True,
                                        ts=1000.0 + clock.now).model_dump_json())
    assert "allow_moves is off" in replies(link, "remote")[-1]["detail"]
    assert gw.status(clock.now).moves == {"voice": True, "remote": False}  # all or nothing

    gw.on_request("remote", MovesSwitch(remote=False, ts=1000.0 + clock.now).model_dump_json())
    assert replies(link, "remote")[-1]["kind"] == "ack"


async def test_an_unwritable_state_dir_keeps_the_switch_in_memory(tmp_path):
    blocked = tmp_path / "not-a-dir"
    blocked.write_text("x")
    gw, link, clock = await rig_for(state_dir=blocked, enable_remote=False)
    gw.on_request("remote", MovesSwitch(remote=True, ts=1000.0 + clock.now).model_dump_json())
    assert gw.status(clock.now).moves["remote"] is True
    assert replies(link, "remote")[-1]["kind"] == "ack"


async def test_a_late_moves_switch_is_refused(tmp_path):
    gw, link, clock = await rig_for(state_dir=tmp_path, enable_remote=False)
    gw.on_request("remote", MovesSwitch(remote=False, ts=1000.0 + clock.now).model_dump_json())
    link.published.clear()
    clock.now += 1.0
    gw.on_request("remote", MovesSwitch(remote=True,
                                        ts=996.0 + clock.now).model_dump_json())
    assert "late" in replies(link, "remote")[-1]["detail"]
    assert gw.status(clock.now).moves["remote"] is False


async def test_bench_can_change_the_moves_switch(tmp_path):
    gw, link, clock = await rig_for(bench=True, state_dir=tmp_path, enable_remote=False)
    gw.on_request("bench", MovesSwitch(remote=True, ts=1000.0 + clock.now).model_dump_json())
    assert replies(link, "bench")[-1]["kind"] == "ack"
    assert gw.status(clock.now).moves["remote"] is True
