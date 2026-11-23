from spider_common.link import InMemoryHub
from spider_common.protocol import PROTOCOL_VERSION, SayRequest, Topics

from spider_brain.config import Settings
from spider_brain.robot_client import RobotClient
from spider_brain.service import BrainService


def settings():
    return Settings(_env_file=None, dashboard=False)


async def test_say_on_robot_publishes_only_text_to_the_voice_topic():
    hub = InMemoryHub()
    link = hub.endpoint(RobotClient.subscriptions("spider-01"))
    await link.start()
    svc = BrainService(settings(), link=link, vision=object(), planner_factory=lambda tier: None)

    assert svc.say_on_robot("  مرحبا من الدماغ  ") is True
    msg = link.published[-1]
    assert msg.topic == Topics("spider-01").voice_say
    req = SayRequest.model_validate_json(msg.payload)
    assert req.v == PROTOCOL_VERSION and req.trace
    assert req.text == "مرحبا من الدماغ"

    before = len(link.published)
    assert svc.say_on_robot("   ") is False
    assert len(link.published) == before
