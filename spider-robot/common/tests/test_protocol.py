import asyncio

import pytest
from pydantic import ValidationError

from spider_common.link import InMemoryHub, topic_matches
from spider_common.protocol import Move, Snapshot, Topics, parse_command


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
