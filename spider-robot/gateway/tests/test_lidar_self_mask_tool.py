"""infra/pi/lidar_self_mask.py: from measured sector maps to lidar_self_mask.yaml."""

import importlib.util
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from spider_common.protocol import LidarSummary, RobotState, Topics

TOOL = Path(__file__).resolve().parents[2] / "infra" / "pi" / "lidar_self_mask.py"
_spec = importlib.util.spec_from_file_location("lidar_self_mask", TOOL)
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)


def room(**near: float) -> list[float]:
    """A closed room 1.5 m away, with some sectors set: near={"s0": 0.24, ...}."""
    sectors = [1.5] * 36
    for key, d in near.items():
        sectors[int(key[1:])] = d
    return sectors


# The owner's tripod measurement, 2026-11-20 (sector 34 = -20 deg; 8.0 = no return), plus a
# pan of -60 where the camera is far right and the front sectors show the room behind it.
OWNER = {
    0.0: room(s0=0.240, s1=1.175, s35=1.663, s34=0.253, s33=0.291, s32=0.396),
    40.0: room(s0=0.260, s1=0.825, s35=0.826, s34=8.0, s33=0.289, s32=0.305),
    -40.0: room(s0=1.334, s1=1.091, s35=0.259, s34=8.0, s33=1.668, s32=1.334),
    -60.0: room(s29=0.30),
}


def test_the_owners_measurement_becomes_a_mask():
    table, problems = tool.build(OWNER, 0.05)
    assert problems == []
    assert table["margin_m"] == 0.05
    assert table["pans"][0.0] == {"mask": {0: 0.24, 32: 0.396, 33: 0.291, 34: 0.253},
                                  "shadow": []}
    assert table["pans"][40.0] == {"mask": {0: 0.26, 32: 0.305, 33: 0.289}, "shadow": [34]}
    assert table["pans"][-40.0] == {"mask": {35: 0.259}, "shadow": [34]}
    assert table["pans"][-60.0] == {"mask": {29: 0.3}, "shadow": []}


def test_furniture_near_the_robot_is_never_masked():
    # a chair leg 0.45 m away at +30 deg and a box 0.5 m away at -40 deg, in every pan; the
    # camera passes in front of the box at pan 0
    maps = {pan: room(s3=0.45, s32=0.5) for pan in (-40.0, 40.0)}
    maps[0.0] = room(s3=0.45, s32=0.396, s0=0.24)
    table, problems = tool.build(maps, 0.05)
    assert problems == []
    assert table["pans"][0.0]["mask"] == {0: 0.24, 32: 0.396}  # 0.396 + 0.05 < the box
    assert all(3 not in e["mask"] for e in table["pans"].values())
    assert table["pans"][40.0]["mask"] == {}


def test_a_return_that_only_the_camera_ever_hides_is_kept():
    # sector 34 reads 0.25 or nothing: no pan shows what is behind, so it cannot be told from
    # the room and stays an obstacle (safe; the hidden pans still get their shadow)
    table, _ = tool.build({0.0: room(s34=0.25), 40.0: room(s34=8.0)}, 0.05)
    assert table["pans"][0.0] == {"mask": {}, "shadow": []}
    assert table["pans"][40.0] == {"mask": {}, "shadow": [34]}


def test_something_that_moves_behind_the_robot_stops_the_measurement():
    _, problems = tool.build({0.0: room(s0=0.24, s18=0.4), 40.0: room()}, 0.05)
    assert len(problems) == 1 and "+180 deg, behind the robot" in problems[0]
    still, problems = tool.build({0.0: room(s18=0.4), 40.0: room(s18=0.4)}, 0.05)
    assert problems == [] and all(e["mask"] == {} for e in still["pans"].values())


def test_the_file_reads_back_as_written():
    table, _ = tool.build(OWNER, 0.05)
    text = tool.to_yaml(table, "test")
    assert yaml.safe_load(text) == {"margin_m": 0.05, "pans": {
        -60: {"mask": {29: 0.3}, "shadow": []},
        -40: {"mask": {35: 0.259}, "shadow": [34]},
        0: {"mask": {0: 0.24, 32: 0.396, 33: 0.291, 34: 0.253}, "shadow": []},
        40: {"mask": {0: 0.26, 32: 0.305, 33: 0.289}, "shadow": [34]},
    }}


def test_extend_adds_what_shows_through_the_mask_and_keeps_the_rest():
    old = {"margin_m": 0.04, "pans": {0: {"mask": {0: 0.24, 34: 0.25}, "shadow": [5]},
                                      60: {"mask": {1: 0.3}, "shadow": []}}}
    # through the mask: the camera goes on to 0.31 in sector 0, sector 33 is now empty,
    # sector 5 (an old shadow) reads its neighbour's value
    seen = {0.0: room(s0=0.31, s33=8.0, s5=0.3), -40.0: room()}
    table, problems = tool.build(seen, 0.05, old)
    assert problems == []
    assert table["margin_m"] == 0.04  # the file's margin stays
    assert table["pans"][0.0] == {"mask": {0: 0.31, 34: 0.25}, "shadow": [5, 33]}
    assert table["pans"][60.0] == {"mask": {1: 0.3}, "shadow": []}  # not swept: unchanged
    assert tool.changes(old, table) == ["pan +0: +0 deg masked to 0.310 m (was 0.240)",
                                        "pan +0: -30 deg is hidden"]


def test_extend_finds_nothing_when_the_mask_covers_the_camera():
    old = {"margin_m": 0.05, "pans": {0: {"mask": {0: 0.24}, "shadow": []}}}
    table, _ = tool.build({0.0: room()}, 0.05, old)
    assert tool.changes(old, table) == []


def test_checks_for_a_fixed_return_and_a_blind_sector():
    maps = {p: room(s2=0.45, s20=8.0) for p in (-40.0, 0.0, 40.0)}
    assert tool.same_everywhere(maps) == [2]
    assert tool.blind_everywhere(maps) == [20]
    table, _ = tool.build(maps, 0.05)
    assert all(e == {"mask": {}, "shadow": [20]} for e in table["pans"].values())


class FakeRobot:
    """The console as the tool uses it: bench_look, wait_for and the state topic."""

    def __init__(self, limit: float = 50.0) -> None:
        self.topics = Topics("spider-01")
        self.limit = limit
        self.pan: float | None = None
        self.looks: list[float] = []

    async def bench_look(self, pan: float, speed: float) -> str:
        self.looks.append(pan)
        self.pan = max(-self.limit, min(self.limit, pan))
        return f"ack: look {self.pan:+.0f}"

    async def wait_for(self, predicate, timeout_s: float):
        for _ in range(20):
            state = RobotState(
                robot_id="spider-01", ts=time.time() + 1, mode="standing",
                camera_pan_deg=self.pan, lidar_age_s=0.1,
                lidar=LidarSummary(ts=0, sector_deg=10, sectors_m=OWNER.get(self.pan, room()),
                                   nearest_m=0.24, nearest_bearing_deg=0, points=100))
            msg = SimpleNamespace(topic=self.topics.state, payload=state.model_dump_json())
            result = predicate(msg)
            if result is not None:
                return result
        return None


async def test_the_sweep_keys_by_the_pan_the_body_reached_and_ends_straight_ahead():
    robot = FakeRobot(limit=50.0)
    maps = await tool.sweep(robot, [-60.0, -40.0, 0.0, 40.0, 50.0, 60.0], 0.0, 3)
    assert sorted(maps) == [-50.0, -40.0, 0.0, 40.0, 50.0]  # 60 was limited to 50: kept once
    assert maps[40.0] == OWNER[40.0]
    assert robot.looks[-1] == 0.0


async def test_a_refused_look_stops_the_sweep_and_still_centres_the_camera():
    robot = FakeRobot()

    async def refuse(pan, speed):
        robot.looks.append(pan)
        return "rejected: cannot look while relaxed"

    robot.bench_look = refuse
    with pytest.raises(RuntimeError, match="cannot look while relaxed"):
        await tool.sweep(robot, [-60.0, 0.0], 0.0, 3)
    assert robot.looks == [-60.0, 0.0]


@pytest.mark.parametrize("argv", [["--start", "10", "--stop", "-10"], ["--step", "0"],
                                  ["--margin", "0.3"], ["--stop", "120"]])
def test_bad_arguments_are_refused(argv):
    with pytest.raises(SystemExit):
        tool.main(argv)
