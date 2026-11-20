import asyncio
import json
import logging

import pytest
from pydantic import ValidationError

from spider_common.link import InMemoryHub, topic_matches
from spider_common.obs import Histogram, JsonFormatter
from spider_common.protocol import (
    EStopRelease,
    GatewayStatus,
    HealthReport,
    Move,
    MovesSwitch,
    Snapshot,
    SourceStatus,
    SpeedLimit,
    Topics,
    VoiceTurn,
    parse_command,
)


def test_parse_move_roundtrip():
    cmd = parse_command(Move(vx=0.1, duration_s=2, seq=3).model_dump_json())
    assert isinstance(cmd, Move)
    assert cmd.vx == 0.1 and cmd.seq == 3


@pytest.mark.parametrize(
    "payload",
    [
        '{"type":"move","vx":5}',  # above protocol limit
        '{"type":"move","duration_s":0}',  # must be > 0
        '{"type":"jump"}',  # unknown command
        '{"type":"stop","extra":1}',  # extra fields forbidden
        '{"type":"snapshot","request_id":"../etc"}',  # unsafe id
        "not json",
    ],
)
def test_bad_commands_rejected(payload):
    with pytest.raises(ValidationError):
        parse_command(payload)


def test_topics():
    t = Topics("spider-01")
    assert t.cmd == "spider/spider-01/cmd"
    assert topic_matches(t.camera_filter, t.camera("abc"))
    assert not topic_matches(t.camera_filter, t.state)


async def test_in_memory_hub_routes_by_subscription():
    hub = InMemoryHub()
    t = Topics("r1")
    body = hub.endpoint([t.cmd])
    brain = hub.endpoint([t.state, t.event])
    await body.start()
    await brain.start()
    brain.publish(t.cmd, Snapshot(request_id="x1").model_dump_json())
    msg = await asyncio.wait_for(anext(body.messages()), 1)
    assert msg.topic == t.cmd
    assert brain.inbox.queue.empty()


def test_v2_source_command_still_parses():
    # A not-yet-upgraded brain sends v2 with no trace field; the gateway must still understand it.
    cmd = parse_command('{"v":2,"type":"move","vx":0.05,"duration_s":1,"session":"a","seq":1}')
    assert cmd.v == 2 and cmd.trace == ""


def test_v3_fields_roundtrip():
    release = parse_command(
        EStopRelease(challenge="c1", frame_sha256="ab", trace="t1").model_dump_json()
    )
    assert isinstance(release, EStopRelease)
    assert (release.challenge, release.frame_sha256, release.trace) == ("c1", "ab", "t1")


def test_moves_switch_roundtrip():
    cmd = parse_command(MovesSwitch(voice=True, trace="t1").model_dump_json())
    assert isinstance(cmd, MovesSwitch)
    assert (cmd.voice, cmd.remote, cmd.trace) == (True, None, "t1")


def test_speed_limit_roundtrip_and_bounds():
    cmd = parse_command(SpeedLimit(max_speed_mps=0.08, max_wz_rps=0.4).model_dump_json())
    assert isinstance(cmd, SpeedLimit) and (cmd.max_speed_mps, cmd.max_wz_rps) == (0.08, 0.4)
    for bad in ('{"type":"speed_limit","max_speed_mps":0,"max_wz_rps":0.4}',
                '{"type":"speed_limit","max_speed_mps":0.08}',
                '{"type":"speed_limit","max_speed_mps":0.6,"max_wz_rps":0.4}'):
        with pytest.raises(ValidationError):
            parse_command(bad)


def test_status_models_serialise():
    limits = {"max_speed_mps": 0.05, "max_wz_rps": 0.3, "ceiling_speed_mps": 0.12,
              "ceiling_wz_rps": 0.6}
    s = GatewayStatus(robot_id="r", sources={"voice": SourceStatus(alive=True)},
                      moves={"voice": True, "remote": False}, remote_limits=limits)
    restored = GatewayStatus.model_validate_json(s.model_dump_json())
    assert restored.sources["voice"].alive
    assert restored.moves == {"voice": True, "remote": False}
    assert restored.remote_limits == limits
    assert GatewayStatus(robot_id="r").remote_limits == {}  # an older gateway sends none
    assert VoiceTurn(trace="t", route="stop").route == "stop"
    assert HealthReport(robot_id="r", service="voice").level == "ok"


def test_health_topics():
    t = Topics("spider-01")
    assert t.health("voice") == "spider/spider-01/health/voice"
    assert topic_matches(t.health_filter, t.health("camera"))
    assert t.gateway_status == "spider/spider-01/gw/status"


def test_histogram_percentiles_are_conservative():
    h = Histogram()
    for v in [0.05] * 99 + [50.0]:
        h.record(v)
    assert h.percentile(0.50) == 0.1
    assert h.percentile(0.999) == 60.0
    assert h.snapshot()["max_ms"] == 50.0
    assert Histogram().percentile(0.5) == 0.0


def test_json_formatter_merges_fields():
    record = logging.LogRecord("x", logging.INFO, "f", 1, "hello", None, None)
    record.fields = {"trace": "abc", "stage": "stt"}
    out = json.loads(JsonFormatter().format(record))
    assert out["msg"] == "hello" and out["trace"] == "abc" and out["stage"] == "stt"
