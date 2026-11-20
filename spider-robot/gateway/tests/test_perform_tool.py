"""infra/pi/perform.py: a move or the way back to stand, from the bench."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from spider_common.protocol import Heartbeat, Perform, Posture, RobotEvent, Stop, Topics

TOOL = Path(__file__).resolve().parents[2] / "infra" / "pi" / "perform.py"
_spec = importlib.util.spec_from_file_location("perform_tool", TOOL)
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)


class FakeConsole:
    """Answers the command it was sent with a scripted list of (kind, detail) events."""

    def __init__(self, script: list[tuple[str, str]]) -> None:
        self.topics, self.source = Topics("spider-01"), "bench"
        self.script = script
        self.sent: list = []

    def send(self, cmd) -> int:
        self.sent.append(cmd)
        return len(self.sent)

    async def _beat_for(self, seconds: float) -> None:
        return None

    async def wait_for(self, predicate, timeout_s: float):
        seq = len(self.sent)
        for kind, detail in self.script:
            ev = RobotEvent(robot_id="spider-01", kind=kind, seq=seq, detail=detail)
            result = predicate(SimpleNamespace(topic=self.topics.source_event("bench"),
                                               payload=ev.model_dump_json()))
            if result is not None:
                return result
        return None


async def test_the_table_runs_until_the_body_holds_it():
    console = FakeConsole([("perform_started", "table: 5.2 s"),
                           ("perform_done", "table held: send stand to come back")])
    assert await tool.play(console, "table", 0.5) == ("perform_done: table held: send stand "
                                                      "to come back")
    assert isinstance(console.sent[0], Heartbeat)
    assert isinstance(console.sent[1], Perform) and console.sent[1].name == "table"
    assert not any(isinstance(c, Stop) for c in console.sent)


async def test_stand_from_a_held_pose_waits_for_the_way_back():
    console = FakeConsole([("ack", "stand: back to the stand pose first"),
                           ("perform_started", "recover: 7.0 s"),
                           ("perform_done", "recover done")])
    assert await tool.play(console, "stand", 0.5) == "perform_done: recover done"
    assert isinstance(console.sent[1], Posture) and console.sent[1].posture == "stand"


async def test_a_refused_move_is_reported():
    console = FakeConsole([("perform_rejected", "table: LiDAR data is stale")])
    assert await tool.play(console, "table", 0.5) == "perform_rejected: table: LiDAR data is stale"


async def test_no_answer_sends_stop():
    console = FakeConsole([])
    assert await tool.play(console, "table", 0.5, wait_s=0.1) == "no answer from the robot"
    assert isinstance(console.sent[-1], Stop)


@pytest.mark.parametrize("argv", [["fly"], ["table", "--speed", "0"], ["table", "--speed", "2"]])
def test_bad_arguments_are_refused(argv):
    with pytest.raises(SystemExit):
        tool.main(argv)
