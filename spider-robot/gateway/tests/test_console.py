import asyncio
import json

from spider_common.link import InMemoryHub
from spider_common.protocol import RobotState, Snapshot, Stop, Topics

from spider_gateway.console import Console
from spider_gateway.gateway import Gateway

ROBOT = "spider-01"
T = Topics(ROBOT)


async def rig():
    hub = InMemoryHub()
    link = hub.endpoint(Console.subscriptions(ROBOT))
    gw_link = hub.endpoint(Gateway.subscriptions(ROBOT))
    camera = hub.endpoint([T.cmd])
    await link.start()
    await gw_link.start()
    await camera.start()
    gateway = Gateway(gw_link, ROBOT)
    return Console(link, ROBOT), gateway, gw_link, camera, hub


def published(link, topic):
    return [json.loads(m.payload) for m in link.published if m.topic == topic]


async def test_stop_goes_through_the_gateway_as_remote():
    console, gateway, gw_link, _, _ = await rig()
    pump = asyncio.create_task(gateway._pump())
    console.send(Stop())
    await asyncio.sleep(0.02)
    pump.cancel()
    assert published(gw_link, T.cmd)[-1]["type"] == "stop"


async def test_status_reads_telemetry():
    console, _, gw_link, _, _ = await rig()
    gw_link.publish(T.state, RobotState(robot_id=ROBOT, mode="standing").model_dump_json())
    assert "mode=standing" in await console.status()


async def _camera_answers(gateway, gw_link, camera, hub):
    """Stands in for spider-camera: answers each forwarded Snapshot."""
    answer = hub.endpoint([])
    await answer.start()
    async for msg in camera.messages():
        data = json.loads(msg.payload)
        if data.get("type") == "snapshot":
            cmd = Snapshot.model_validate(data)
            answer.publish(T.camera(cmd.request_id), b"\xff\xd8", qos=1)


async def test_release_shows_the_frame_first_and_honours_the_answer(tmp_path):
    console, gateway, gw_link, camera, hub = await rig()
    tasks = [asyncio.create_task(gateway._pump()),
             asyncio.create_task(_camera_answers(gateway, gw_link, camera, hub))]
    try:
        seen = []

        def refuse(path):
            seen.append(path)
            return False

        assert await console.release(refuse, tmp_path) == "E-stop kept"
        assert seen[0].read_bytes() == b"\xff\xd8"
        assert not [c for c in published(gw_link, T.cmd) if c["type"] == "estop_release"]

        await asyncio.sleep(0.6)  # the gateway's snapshot rate limit
        result = await console.release(lambda path: True, tmp_path)
        released = [c for c in published(gw_link, T.cmd) if c["type"] == "estop_release"]
        assert len(released) == 1 and released[0]["challenge"], result
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_bench_walk_renews_short_moves_and_always_ends_with_a_stop():
    hub = InMemoryHub()
    link = hub.endpoint([])
    await link.start()
    console = Console(link, ROBOT, source="bench")
    await console.bench_walk(0.05, 0.0, 0.0, 0.05)
    out = [json.loads(m.payload) for m in link.published]
    assert {m.topic for m in link.published} == {T.request("bench")}
    moves = [c for c in out if c["type"] == "move"]
    assert moves and all(c["duration_s"] == 1.0 for c in moves)
    assert out[-1]["type"] == "stop"


async def test_bench_posture_keeps_the_source_alive_while_it_ramps():
    hub = InMemoryHub()
    link = hub.endpoint([])
    await link.start()
    console = Console(link, ROBOT, source="bench")
    await console.bench_posture("stand", wait_s=0.03)
    kinds = [json.loads(m.payload)["type"] for m in link.published]
    assert "posture" in kinds and kinds.count("heartbeat") >= 2
