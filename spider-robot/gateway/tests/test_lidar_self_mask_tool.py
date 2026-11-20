"""infra/pi/lidar_self_mask.py: from measured sector maps to lidar_self_mask.yaml."""

import importlib.util
import re
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

FAR = 1.5  # the room, wherever the tool printed nothing (it prints sectors under 1.2 m)


def room(**near: float) -> list[float]:
    """A room 1.5 m away, with some sectors set: near={"s0": 0.24, ...}."""
    sectors = [FAR] * 36
    for key, d in near.items():
        sectors[int(key[1:])] = d
    return sectors


# The sweep on the robot, 2026-11-20 (tripod, right wall ~0.6 m, screen on the left ~0.5 m,
# the owner sitting in front), as the tool printed it: bearing:metres for sectors under 1.2 m.
ROBOT_SWEEP = """
-60: +0:0.82 +10:0.78 +20:1.09 +30:1.12 +40:0.89 +50:0.64 +60:0.52 +70:0.50 -170:1.07 -160:0.88
    -150:0.71 -140:0.65 -130:0.62 -120:0.59 -110:0.59 -100:0.60 -90:0.65 -80:0.68-70:0.80
    -60:0.98 -30:0.28 -20:0.27 -10:0.26
-50: +0:0.81 +20:1.07 +30:1.10 +40:0.85 +50:0.62 +60:0.50 +70:0.46 +130:1.20 -170:1.05
    -160:0.85 -150:0.72 -140:0.65 -130:0.60 -120:0.59 -110:0.59 -100:0.60 -90:0.64 -80:0.68
    -70:0.80 -60:0.97 -40:0.30 -30:0.29 -20:0.26 -10:0.24
-40: +0:0.80 +20:1.08 +30:1.10 +40:0.88 +50:0.64 +60:0.51 +70:0.49 -170:1.08 -160:0.87
    -150:0.70 -140:0.65 -130:0.60 -120:0.60 -110:0.59 -100:0.60 -90:0.62 -80:0.68
    -70:0.82-60:0.99 -30:0.28 -20:0.26 -10:0.24
-30: +0:0.62 +10:0.81 +20:1.08 +40:0.90 +50:0.64 +60:0.49 +70:0.50 -170:1.07 -160:0.88
    -150:0.70 -140:0.64 -130:0.61 -120:0.60 -110:0.59 -100:0.59 -90:0.64 -80:0.68
    -70:0.82-60:0.97 -40:0.30 -30:0.29 -20:0.26 -10:0.24
-20: +0:0.25 +10:0.82 +20:1.09 +30:1.20 +40:0.84 +50:0.61 +60:0.48 +70:0.48 +120:1.20 -170:1.07
    -160:0.87 -150:0.71 -140:0.65 -130:0.61 -120:0.59 -110:0.59 -100:0.59 -90:0.62 -80:0.69
    -70:0.81 -60:0.96 -40:0.29 -30:0.29 -20:0.31 -10:0.25
-10: +0:0.24 +10:0.82 +20:1.08 +30:1.10 +40:0.84 +50:0.62 +60:0.50 +70:0.50 -170:1.05 -160:0.85
    -150:0.73 -140:0.65 -130:0.60 -120:0.59 -110:0.59 -100:0.60 -90:0.64 -80:0.67-70:0.81
    -60:0.96 -40:0.31 -30:0.28 -20:0.27 -10:0.25
0: +0:0.24 +20:1.08 +30:1.11 +40:0.86 +50:0.62 +60:0.50 +70:0.49 -170:1.05 -160:0.86 -150:0.73
    -140:0.66 -130:0.61 -120:0.60 -110:0.59 -100:0.60 -90:0.62 -80:0.68 -70:0.81-60:0.97
    -40:0.30 -30:0.29 -20:0.26 -10:0.24
10: +0:0.24 +10:0.83 +20:1.08 +30:1.11 +40:0.84 +50:0.61 +60:0.50 +70:0.48 -170:1.06 -160:0.85
    -150:0.71 -140:0.65 -130:0.60 -120:0.59 -110:0.59 -100:0.60 -90:0.64 -80:0.68-70:0.80
    -60:0.98 -30:0.31 -20:0.29 -10:0.25
20: +0:0.24 +20:1.09 +30:1.09 +40:0.87 +50:0.60 +60:0.49 +70:0.49 -170:1.06 -160:0.86 -150:0.71
    -140:0.64 -130:0.60 -120:0.59 -110:0.58 -100:0.61 -90:0.65 -80:0.68 -70:0.81-60:0.98
    -50:0.35 -40:0.34 -30:0.27 -20:0.28 -10:0.25
30: +0:0.24 +20:1.07 +30:1.11 +40:0.85 +50:0.62 +60:0.50 +70:0.49 +130:1.20 -170:1.07 -160:0.85
    -150:0.72 -140:0.66 -130:0.61 -120:0.60 -110:0.59 -100:0.60 -90:0.63 -80:0.69 -70:0.80
    -60:0.97 -50:0.35 -40:0.30 -30:0.27 -20:0.26 -10:0.25
40: +0:0.26 +10:0.78 +20:1.08 +30:1.11 +40:0.83 +50:0.61 +60:0.50 +70:0.49 -170:1.08 -160:0.85
    -150:0.72 -140:0.66 -130:0.61 -120:0.59 -110:0.59 -100:0.60 -90:0.63 -80:0.69-70:0.81
    -60:0.97 -40:0.29 -30:0.27 -20:0.26 -10:0.26
50: +0:0.25 +10:0.41 +20:1.08 +30:1.18 +40:0.88 +50:0.61 +60:0.49 +70:0.49 -170:1.07 -160:0.87
    -150:0.71 -140:0.66 -130:0.61 -120:0.59 -110:0.60 -100:0.60 -90:0.64 -80:0.69-70:0.81
    -60:0.97 -40:0.30 -30:0.27 -20:0.26 -10:0.24
60: +0:0.24 +10:0.82 +20:1.08 +30:1.10 +40:0.85 +50:0.63 +60:0.50 +70:0.49 -170:1.06 -160:0.85
    -150:0.72 -140:0.65 -130:0.61 -120:0.59 -110:0.59 -100:0.60 -90:0.64 -80:0.69-70:0.80
    -60:0.96 -40:0.30 -30:0.27 -20:0.26 -10:0.25
"""


def parse(text: str) -> dict[float, list[float]]:
    """"<pan>: bearing:metres ..." with indented continuation lines."""
    maps: dict[float, list[float]] = {}
    sectors: list[float] = []
    for line in text.strip().splitlines():
        if not line.startswith(" "):
            pan, line = line.split(":", 1)
            sectors = maps[float(pan)] = [FAR] * 36
        for deg, d in re.findall(r"([+-]\d+):(\d+\.\d+)", line):
            sectors[(int(deg) % 360) // 10] = float(d)
    return maps


SWEEP = parse(ROBOT_SWEEP)


def test_the_robot_sweep_masks_only_the_camera_straight_ahead():
    table, problems, notes = tool.build(SWEEP, 0.05)
    assert problems == []
    masked = {pan: e["mask"] for pan, e in table["pans"].items() if e["mask"]}
    assert masked == {-20.0: {0: 0.25}, -10.0: {0: 0.24}, 0.0: {0: 0.24}, 10.0: {0: 0.24},
                      20.0: {0: 0.24}, 30.0: {0: 0.24}, 40.0: {0: 0.26}, 50.0: {0: 0.25},
                      60.0: {0: 0.24}}
    assert all(e["shadow"] == [] for e in table["pans"].values())
    # the screen (+60, +70) and the right side (-10..-30) read a few cm apart from pan to pan:
    # noise, not the camera; -40, -50 and +10 come and go
    assert [n.split(" ")[0] for n in notes] == ["+10", "-50", "-40"]
    assert {tool.bearing(i) for i in tool.same_everywhere(SWEEP)} >= {-10, -20, -30, 60, 70}


def test_furniture_near_the_robot_is_never_masked():
    # a chair leg 0.45 m away at +30 deg in every pan; a box 0.55 m away at -40 deg, with the
    # camera passing in front of it at pans 0..20 and straight ahead at -10..10
    maps = {}
    for pan in (-30.0, -20.0, -10.0, 0.0, 10.0, 20.0, 30.0):
        maps[pan] = room(s3=0.45, s32=0.40 if 0 <= pan <= 20 else 0.55,
                         s0=0.24 if -10 <= pan <= 10 else FAR)
    table, problems, _ = tool.build(maps, 0.05)
    assert problems == []
    assert table["pans"][0.0]["mask"] == {0: 0.24, 32: 0.4}  # 0.40 + 0.05 stops short of the box
    assert table["pans"][20.0]["mask"] == {32: 0.4}
    assert table["pans"][-30.0]["mask"] == {}
    assert all(3 not in e["mask"] for e in table["pans"].values())


def test_noise_is_not_the_camera():
    maps = {pan: room(s34=0.26 + 0.05 * (pan == 0.0), s6=0.46 + 0.06 * (pan > 0))
            for pan in (-20.0, -10.0, 0.0, 10.0, 20.0)}
    table, _, _ = tool.build(maps, 0.05)
    assert all(e["mask"] == {} for e in table["pans"].values())


def test_a_return_that_comes_and_goes_stays_an_obstacle():
    pans = (-30.0, -20.0, -10.0, 0.0, 10.0, 20.0)
    gaps = {pan: room(s32=FAR if pan == -10.0 else 0.3, s1=0.4 if pan == 20.0 else FAR)
            for pan in pans}
    table, problems, notes = tool.build(gaps, 0.05)
    assert problems == [] and all(e["mask"] == {} for e in table["pans"].values())
    assert notes == ["+10 deg comes and goes (pans +20): not a camera turning, kept as an "
                     "obstacle",
                     "-40 deg comes and goes (pans -30 -20 +0 +10 +20): not a camera turning, "
                     "kept as an obstacle"]


def test_a_return_that_only_the_camera_ever_hides_is_kept():
    maps = {pan: room(s34=8.0 if pan > 0 else 0.25) for pan in (-20.0, -10.0, 0.0, 10.0, 20.0)}
    table, _, _ = tool.build(maps, 0.05)
    assert table["pans"][0.0] == {"mask": {}, "shadow": []}
    assert table["pans"][20.0] == {"mask": {}, "shadow": [34]}


def test_something_that_moves_behind_the_robot_stops_the_measurement():
    pans = (-20.0, -10.0, 0.0, 10.0)
    _, problems, _ = tool.build({p: room(s18=0.4 if p <= -10 else FAR) for p in pans}, 0.05)
    assert len(problems) == 1 and "+180 deg, behind the robot" in problems[0]
    still, problems, _ = tool.build({p: room(s18=0.4) for p in pans}, 0.05)
    assert problems == [] and all(e["mask"] == {} for e in still["pans"].values())


def test_the_file_reads_back_as_written():
    table, _, _ = tool.build(SWEEP, 0.05)
    back = yaml.safe_load(tool.to_yaml(table, "test"))
    assert back["margin_m"] == 0.05
    assert back["pans"][-60] == {"mask": {}, "shadow": []}
    assert back["pans"][40] == {"mask": {0: 0.26}, "shadow": []}
    assert len(back["pans"]) == 13


def test_extend_adds_what_shows_through_the_mask_and_keeps_the_rest():
    old = {"margin_m": 0.04, "pans": {
        -10: {"mask": {0: 0.24}, "shadow": []}, 0: {"mask": {0: 0.24}, "shadow": [5]},
        10: {"mask": {0: 0.24}, "shadow": []}, 60: {"mask": {1: 0.3}, "shadow": []}}}
    # through the mask: the camera goes on to 0.31 in sector 0, sector 33 is now empty at pan
    # 0, sector 5 (an old shadow) reads its neighbour's value
    seen = {pan: room() for pan in (-30.0, -20.0, 20.0)}
    seen.update({-10.0: room(s0=0.31), 0.0: room(s0=0.31, s33=8.0, s5=0.3), 10.0: room(s0=0.31)})
    table, problems, _ = tool.build(seen, 0.05, old)
    assert problems == []
    assert table["margin_m"] == 0.04  # the file's margin stays
    assert table["pans"][0.0] == {"mask": {0: 0.31}, "shadow": [5, 33]}
    assert table["pans"][60.0] == {"mask": {1: 0.3}, "shadow": []}  # not swept: unchanged
    assert tool.changes(old, table) == ["pan -10: +0 deg masked to 0.310 m (was 0.240)",
                                        "pan +0: +0 deg masked to 0.310 m (was 0.240)",
                                        "pan +0: -30 deg is hidden",
                                        "pan +10: +0 deg masked to 0.310 m (was 0.240)"]


def test_extend_finds_nothing_when_the_mask_covers_the_camera():
    old = {"margin_m": 0.05, "pans": {0: {"mask": {0: 0.24}, "shadow": []}}}
    table, _, _ = tool.build({0.0: room(), 10.0: room()}, 0.05, old)
    assert tool.changes(old, table) == []


def test_checks_for_a_fixed_return_and_a_blind_sector():
    maps = {p: room(s2=0.45, s20=8.0) for p in (-40.0, 0.0, 40.0)}
    assert tool.same_everywhere(maps) == [2]
    assert tool.blind_everywhere(maps) == [20]
    table, _, _ = tool.build(maps, 0.05)
    assert all(e == {"mask": {}, "shadow": [20]} for e in table["pans"].values())


class FakeRobot:
    """The console as the tool uses it: bench_look, wait_for and the state topic."""

    def __init__(self, limit: float = 50.0, lidar_age_s: float = 0.1) -> None:
        self.topics = Topics("spider-01")
        self.limit = limit
        self.lidar_age_s = lidar_age_s
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
                camera_pan_deg=self.pan, lidar_age_s=self.lidar_age_s,
                lidar=LidarSummary(ts=0, sector_deg=10, sectors_m=SWEEP.get(self.pan, room()),
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
    assert maps[40.0] == SWEEP[40.0]
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


async def test_a_stale_lidar_stops_the_sweep_with_what_the_robot_said():
    robot = FakeRobot(lidar_age_s=2.4)
    with pytest.raises(RuntimeError, match=r"0 of 3 fresh LiDAR maps .* lidar age 2.4 s"):
        await tool.sweep(robot, [10.0], 0.0, 3)
    assert robot.looks == [10.0, 0.0]


@pytest.mark.parametrize("argv", [["--start", "10", "--stop", "-10"], ["--step", "0"],
                                  ["--margin", "0.3"], ["--stop", "120"]])
def test_bad_arguments_are_refused(argv):
    with pytest.raises(SystemExit):
        tool.main(argv)
