"""Contract tests: the rules Pi and server rely on during a rolling update."""

import json
import logging

import pytest
from pydantic import ValidationError

from spider_common.link import InMemoryHub
from spider_common.obs import JsonFormatter, new_trace
from spider_common.protocol import (
    PROTOCOL_VERSION,
    AskReply,
    AskRequest,
    ConfirmChallenge,
    ConfirmRequest,
    EStopRelease,
    GatewayStatus,
    Move,
    Posture,
    Protection,
    RobotEvent,
    RobotState,
    SttRequest,
    Topics,
    parse_command,
)


def test_commands_from_the_previous_build_still_parse():
    # A server that has not been updated sends no trace or challenge fields.
    old = '{"type":"move","v":2,"session":"s","seq":3,"ts":1.0,"vx":0.05,"duration_s":1.0}'
    cmd = parse_command(old)
    assert isinstance(cmd, Move) and cmd.trace == ""


def test_unknown_event_kind_and_state_field_are_tolerated():
    ev = RobotEvent.model_validate_json('{"robot_id":"r","kind":"from_the_future"}')
    assert ev.kind == "from_the_future"
    st = RobotState.model_validate_json('{"robot_id":"r","mode":"standing","new_field":1}')
    assert st.mode == "standing" and st.protection is None  # older body: treat as on
    new = RobotState(robot_id="r", mode="standing", protection=False)
    assert "protection" in json.loads(new.model_dump_json())
    cmd = parse_command(Protection(enabled=False).model_dump_json())
    assert isinstance(cmd, Protection) and cmd.ttl_s == 2.0


def test_commands_still_reject_unknown_fields():
    with pytest.raises(ValidationError):
        parse_command('{"type":"stop","surprise":1}')


def test_confirm_flow_messages_roundtrip():
    req = parse_command(ConfirmRequest(action="estop_release", request_id="r1").model_dump_json())
    assert isinstance(req, ConfirmRequest)
    rel = parse_command(EStopRelease(challenge="c1", frame_sha256="ab").model_dump_json())
    assert isinstance(rel, EStopRelease) and rel.challenge == "c1"
    pose = parse_command(Posture(posture="stand", challenge="c2").model_dump_json())
    assert isinstance(pose, Posture) and pose.challenge == "c2"
    ch = ConfirmChallenge(id="c", action="wake_from_limp", request_id="r", sha256="x", ttl_s=30)
    ev = RobotEvent(robot_id="r", kind="challenge", detail=ch.model_dump_json())
    assert ConfirmChallenge.model_validate_json(ev.detail).action == "wake_from_limp"


def test_ask_reply_cannot_carry_an_action():
    # Decision 7: vision and cloud answers are spoken only.
    assert set(AskReply.model_fields) == {
        "v", "trace", "ts", "ok", "text", "provider", "elapsed_ms", "error"
    }


def test_ask_and_stt_requests_are_bounded():
    with pytest.raises(ValidationError):
        AskRequest(trace="a", text="x" * 5000)
    with pytest.raises(ValidationError):
        AskRequest(trace="../bad", text="hi")
    with pytest.raises(ValidationError):
        SttRequest(trace="a", audio_b64="A" * 500_000)


def test_gateway_status_schema():
    st = GatewayStatus(robot_id="r", session="s")
    data = json.loads(st.model_dump_json())
    assert data["v"] == PROTOCOL_VERSION and data["online"] is True


def test_new_topics_are_namespaced_per_robot():
    t = Topics("r1")
    assert t.gateway_status == "spider/r1/gw/status"
    assert t.rpc_request("ask") == "spider/r1/rpc/ask/req"
    assert t.rpc_reply("stt", "voice") == "spider/r1/rpc/stt/res/voice"


async def test_retained_message_reaches_a_late_subscriber():
    hub = InMemoryHub()
    t = Topics("r")
    pub = hub.endpoint([])
    await pub.start()
    pub.publish(t.gateway_status, b"x", qos=1, retain=True)
    late = hub.endpoint([t.gateway_status])
    await late.start()
    assert late.inbox.queue.get_nowait().payload == b"x"


def test_json_logs_carry_service_and_correlation_id():
    fmt = JsonFormatter("spider-test")
    rec = logging.LogRecord("x", logging.INFO, "f", 1, "hello %s", ("w",), None)
    rec.trace = "abc"
    out = json.loads(fmt.format(rec))
    assert out["svc"] == "spider-test" and out["msg"] == "hello w" and out["trace"] == "abc"
    assert len(new_trace()) == 12


# ------------------------------------------------------------------ expressive moves (v3, additive)
def test_perform_and_reach_roundtrip():
    from spider_common.protocol import MOVE_NAMES, Perform, Reach

    for name in MOVE_NAMES:
        cmd = parse_command(Perform(name=name, speed=1.0).model_dump_json())
        assert isinstance(cmd, Perform) and cmd.name == name and cmd.leg is None
    assert len(MOVE_NAMES) == 18 and "offer_hand" in MOVE_NAMES and "table" in MOVE_NAMES
    reach = parse_command('{"type":"reach","target":[0.3,0.1,-0.03],"leg":"RF"}')
    assert isinstance(reach, Reach) and reach.target == (0.3, 0.1, -0.03)
    assert parse_command('{"type":"reach"}').target == "nearest"
    assert parse_command('{"type":"perform","name":"hi"}').speed == 0.5


@pytest.mark.parametrize(
    "payload",
    [
        '{"type":"perform","name":"moonwalk"}',  # not in the fixed list
        '{"type":"perform","name":"dance","speed":1.5}',  # nothing runs above 1.0
        '{"type":"perform","name":"dance","speed":0}',
        '{"type":"perform","name":"wave","leg":"LM"}',  # front legs only
        '{"type":"reach","leg":"RR"}',
        '{"type":"reach","target":[2.0,0,0]}',  # bounded coordinates
        '{"type":"reach","target":"farthest"}',
        '{"type":"perform","name":"dance","keyframes":[]}',  # no trajectory upload
    ],
)
def test_moves_reject_anything_outside_the_contract(payload):
    with pytest.raises(ValidationError):
        parse_command(payload)


def test_move_events_and_state_field_are_additive():
    from typing import get_args

    from spider_common.protocol import EventKind, RobotMode

    assert {"perform_started", "perform_done", "perform_rejected"} <= set(get_args(EventKind))
    old = RobotState.model_validate_json('{"robot_id":"r","mode":"standing"}')
    assert old.perform is None  # a body from the previous build still parses
    assert RobotState(robot_id="r", mode="standing", perform="dance").perform == "dance"
    # a move runs in mode "standing": no new mode value an older reader would refuse
    assert set(get_args(RobotMode)) == {"relaxed", "sitting", "standing", "walking", "estop",
                                        "fallen"}
