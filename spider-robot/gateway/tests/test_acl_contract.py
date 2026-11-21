"""Every client's real topics, checked against the ACL file the broker will load."""

from pathlib import Path

import pytest
from spider_common.link import topic_matches
from spider_common.protocol import Topics

from spider_gateway.gateway import Gateway

ACL = Path(__file__).resolve().parents[2] / "infra" / "local" / "acl"
ROBOT = "spider-01"
T = Topics(ROBOT)


def load():
    rules: dict[str, list[tuple[str, str]]] = {}
    patterns: list[tuple[str, str]] = []
    user = None
    for line in ACL.read_text("utf-8").splitlines():
        words = line.split()
        if not words or words[0].startswith("#"):
            continue
        if words[0] == "user":
            user = words[1]
            rules[user] = []
        elif words[0] == "pattern":
            patterns.append((words[1], words[2]))
        elif words[0] == "topic":
            rules[user].append((words[1], words[2]))
    return rules, patterns


RULES, PATTERNS = load()


def allowed(user, access, topic):
    grants = list(RULES.get(user, []))
    grants += [(a, p.replace("%u", user)) for a, p in PATTERNS]
    return any(a in (access, "readwrite") and topic_matches(flt, topic) for a, flt in grants)


CLIENTS = {
    "spider-01": {"write": [T.state, T.event, T.camera("x")], "read": [T.cmd]},
    "spider-gateway": {
        "read": [T.request("voice"), T.request("remote"), T.request("planner"),
                 T.request("button"), T.event, T.state, T.camera("x")],
        "write": [T.cmd, T.source_event("voice"), T.source_event("remote"),
                  T.source_event("planner"), T.source_event("button"), T.gateway_status],
    },
    "spider-brain": {
        "write": [T.request("remote"), T.request("planner"), T.rpc_reply("ask", "voice"),
                  T.rpc_reply("stt", "voice"), T.record_cmd, T.voice_say, T.health("brain")],
        "read": [T.source_event("remote"), T.source_event("planner"), T.state, T.camera("x"),
                 T.voice_turn, T.health("voice"), T.health("system"), T.gateway_status,
                 T.rpc_request("ask"), T.rpc_request("stt"), T.record_event],
    },
    "spider-voice": {
        "write": [T.request("voice"), T.voice_turn, T.health("voice"), T.rpc_request("ask"),
                  T.rpc_request("stt")],
        "read": [T.source_event("voice"), T.state, T.rpc_reply("ask", "voice"),
                 T.rpc_reply("stt", "voice"), T.voice_say],
    },
    "spider-camera": {"read": [T.cmd], "write": [T.event, T.camera("x"), T.health("camera")]},
    "spider-recorder": {"read": [T.record_cmd], "write": [T.record_event]},
    "spider-sysmon": {"write": [T.health("system")]},
    "spider-console": {
        "write": [T.request("remote"), T.request("bench")],
        "read": [T.source_event("remote"), T.source_event("bench"), T.gateway_status, T.state,
                 T.camera("x")],
    },
    "spider-button": {"write": [T.request("button")], "read": [T.source_event("button")]},
}


@pytest.mark.parametrize("user,access,topic", [
    (u, a, t) for u, spec in CLIENTS.items() for a, topics in spec.items() for t in topics])
def test_client_may_use_its_topics(user, access, topic):
    assert allowed(user, access, topic)


def test_gateway_subscriptions_are_covered():
    for flt in Gateway.subscriptions(ROBOT):
        sample = flt.replace("+", "x")
        assert allowed("spider-gateway", "read", sample)


@pytest.mark.parametrize("user", [
    "spider-brain", "spider-voice", "spider-camera", "spider-recorder", "spider-sysmon",
    "spider-console", "spider-button",
])
def test_only_the_gateway_may_command_the_body(user):
    assert not allowed(user, "write", T.cmd)


def test_brain_cannot_impersonate_voice():
    assert not allowed("spider-brain", "write", T.request("voice"))


def test_only_the_brain_may_ask_voice_to_speak():
    assert allowed("spider-brain", "write", T.voice_say)
    assert allowed("spider-voice", "read", T.voice_say)
    assert not allowed("spider-voice", "write", T.voice_say)
    assert not allowed("spider-console", "write", T.voice_say)


def test_voice_cannot_impersonate_remote():
    assert not allowed("spider-voice", "write", T.request("remote"))


def test_robot_identity_is_limited_to_its_own_robot():
    assert not allowed("spider-01", "read", Topics("spider-02").cmd)


def test_body_cannot_publish_commands_to_itself():
    assert not allowed("spider-01", "write", T.cmd)


@pytest.mark.parametrize("source", ["voice", "remote", "planner"])
def test_button_cannot_send_as_a_motion_source(source):
    assert not allowed("spider-button", "write", T.request(source))


@pytest.mark.parametrize("user", ["spider-brain", "spider-voice", "spider-console"])
def test_nobody_else_can_press_the_button(user):
    assert not allowed(user, "write", T.request("button"))


@pytest.mark.parametrize("user", ["spider-brain", "spider-voice", "spider-button"])
def test_only_the_console_may_use_the_bench_source(user):
    assert not allowed(user, "write", T.request("bench"))


def test_console_cannot_send_as_voice():
    assert not allowed("spider-console", "write", T.request("voice"))
