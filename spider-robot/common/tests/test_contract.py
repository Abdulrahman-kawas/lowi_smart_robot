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
    assert st.mode == "standing"


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
