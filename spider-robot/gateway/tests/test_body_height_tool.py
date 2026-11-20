"""infra/pi/body_height.py: one BodyPose on the bench source, alive until the height is reached."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from spider_common.protocol import BodyPose, Heartbeat, RobotEvent, Topics

TOOL = Path(__file__).resolve().parents[2] / "infra" / "pi" / "body_height.py"
_spec = importlib.util.spec_from_file_location("body_height", TOOL)
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)


class FakeConsole:
    def __init__(self, kind: str, detail: str) -> None:
        self.topics, self.source = Topics("spider-01"), "bench"
        self.kind, self.detail = kind, detail
        self.sent: list = []
        self.beat_s = 0.0

    def send(self, cmd) -> int:
        self.sent.append(cmd)
        return len(self.sent)

    async def _beat_for(self, seconds: float) -> None:
        self.beat_s += seconds

    async def wait_for(self, predicate, timeout_s: float):
        ev = RobotEvent(robot_id="spider-01", kind=self.kind, seq=len(self.sent),
                        detail=self.detail)
        return predicate(SimpleNamespace(topic=self.topics.source_event("bench"),
                                         payload=ev.model_dump_json()))


async def test_the_pose_is_sent_and_the_source_stays_alive_for_the_ramp():
    console = FakeConsole("ack", "body pose")
    assert await tool.set_height(console, 0.12, 5.0) == "ack: body pose"
    assert isinstance(console.sent[0], Heartbeat)
    pose = console.sent[1]
    assert isinstance(pose, BodyPose) and pose.height_m == 0.12 and pose.pitch_deg == 5.0
    assert console.beat_s == tool.RAMP_S


async def test_a_refusal_is_reported():
    console = FakeConsole("rejected", "body pose needs standing (not walking)")
    assert await tool.set_height(console, 0.12) == ("rejected: body pose needs standing "
                                                    "(not walking)")


@pytest.mark.parametrize("argv", [["0.5"], ["0.01"], ["0.12", "--pitch", "30"]])
def test_bad_arguments_are_refused(argv):
    with pytest.raises(SystemExit):
        tool.main(argv)
