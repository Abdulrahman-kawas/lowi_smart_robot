import asyncio

from spider_common.link import InMemoryHub
from spider_common.protocol import RobotEvent, Stop, Topics

from spider_brain.robot_client import RobotClient

ROBOT = "spider-01"
T = Topics(ROBOT)


async def test_client_with_source_talks_only_to_the_gateway():
    hub = InMemoryHub()
    link = hub.endpoint(RobotClient.subscriptions(ROBOT, "remote"))
    gateway = hub.endpoint([T.request_filter])
    await link.start()
    await gateway.start()
    robot = RobotClient(link, ROBOT, source="remote")
    pump = asyncio.create_task(robot.run())
    beat = asyncio.create_task(robot.heartbeat_loop(100.0))
    try:
        seq = robot._send(Stop())
        await asyncio.sleep(0.02)
        topics = {m.topic for m in link.published}
        assert T.request("remote") in topics  # something was really sent, on the right source
        assert topics <= {T.request("remote"), T.request("planner")}

        gateway.publish(T.source_event("remote"),
                        RobotEvent(robot_id=ROBOT, kind="ack", seq=seq).model_dump_json())
        await asyncio.sleep(0.02)
        assert [ev.seq for _, ev in robot.events] == [seq]
    finally:
        beat.cancel()
        pump.cancel()
        await asyncio.gather(beat, pump, return_exceptions=True)


def test_client_without_source_keeps_the_direct_topics():
    assert T.event in RobotClient.subscriptions(ROBOT)
    assert T.source_event("remote") not in RobotClient.subscriptions(ROBOT)
