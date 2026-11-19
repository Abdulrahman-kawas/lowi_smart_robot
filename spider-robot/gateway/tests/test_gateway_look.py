"""Look (camera pan) at the gateway: who may turn it, and what holds it off."""

import json

import pytest
from spider_common.link import InMemoryHub
from spider_common.protocol import Look, Stop, Topics

from spider_gateway.gateway import Gateway, GatewayConfig
from spider_gateway.policy import load_policies

ROBOT = "spider-01"
T = Topics(ROBOT)


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


async def rig(policies=None, bench=False):
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


def look(clock, source, session, seq=1, pan_deg=30.0, speed=0.5):
    cmd = Look(pan_deg=pan_deg, speed=speed, seq=seq, session=session,
               ts=1000.0 + clock.now)
    return cmd.model_dump_json()


async def test_remote_voice_and_bench_may_turn_the_camera():
    gw, link, clock = await rig(bench=True)
    gw.on_request("remote", look(clock, "remote", "r"))
    gw.on_request("voice", look(clock, "voice", "v"))
    gw.on_request("bench", look(clock, "bench", "b"))
    assert [c["type"] for c in sent(link)] == ["look"] * 3
    assert [c["pan_deg"] for c in sent(link)] == [30.0] * 3


async def test_the_planner_may_never_turn_the_camera():
    gw, link, clock = await rig()
    gw.on_request("planner", look(clock, "planner", "p"))
    assert sent(link) == []
    assert replies(link, "planner")[-1]["detail"] == "planner may not turn the camera"


async def test_the_planner_cannot_be_configured_to_turn_the_camera(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text("planner: {allow_look: true}\n")
    with pytest.raises(ValueError, match="planner may not turn the camera"):
        load_policies(path)


async def test_a_second_look_within_the_rate_limit_is_refused():
    gw, link, clock = await rig()
    gw.on_request("remote", look(clock, "remote", "r", seq=1))
    gw.on_request("remote", look(clock, "remote", "r", seq=2, pan_deg=-30.0))
    assert [c["type"] for c in sent(link)] == ["look"]
    assert replies(link, "remote")[-1]["detail"] == "look rate limit"
    clock.now += 0.2
    gw.on_request("remote", look(clock, "remote", "r", seq=3, pan_deg=-30.0))
    assert sent(link)[-1]["pan_deg"] == -30.0


async def test_a_look_during_a_holdoff_from_another_source_is_refused():
    gw, link, clock = await rig()
    gw.on_request("voice", Stop(seq=9, session="v", ts=1000.0 + clock.now).model_dump_json())
    gw.on_request("remote", look(clock, "remote", "r"))
    assert [c["type"] for c in sent(link)] == ["stop"]
    assert "held off after a stop from voice" in replies(link, "remote")[-1]["detail"]


async def test_a_look_sent_before_its_own_stop_is_dropped():
    gw, link, clock = await rig()
    gw.on_request("remote", Stop(seq=5, session="r", ts=1000.0 + clock.now).model_dump_json())
    gw.on_request("remote", look(clock, "remote", "r", seq=4))
    assert [c["type"] for c in sent(link)] == ["stop"]
    assert replies(link, "remote") == []
