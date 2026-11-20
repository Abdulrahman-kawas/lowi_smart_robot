"""The LiDAR ignores the front camera, at its own place and distance only, following the pan.

The numbers are the owner's tripod measurement (2026-11-20, L2 turned 180 deg): the camera puts
returns 24-40 cm out in the front and front-right sectors, and at +-40 deg it hides sector 34
(-20 deg) completely.
"""

import logging
import math
import struct

import numpy as np
import pytest
import yaml
from spider_common.protocol import Look
from test_robot import make, run_ticks, stand

from spider_body.config import LidarCfg, SafetyCfg, SelfMask
from spider_body.hw.lidar import LidarFeed, LidarProcessor, SelfMaskTable
from spider_body.safety import SafetyGuard

FOOT = (0.24, 0.27)
OWNER_YAML = """
margin_m: 0.05
pans:
  0:   {mask: {0: 0.24, 34: 0.25, 33: 0.29, 32: 0.40}, shadow: []}
  40:  {mask: {0: 0.26, 33: 0.29, 32: 0.31}, shadow: [34]}
  -40: {mask: {35: 0.26}, shadow: [34]}
"""
OWNER = SelfMask.model_validate(yaml.safe_load(OWNER_YAML))


def pt(r: float, bearing_deg: float) -> list[float]:
    """A point r metres from the L2 at this bearing (+ left), at the L2's height."""
    a = math.radians(bearing_deg)
    return [r * math.cos(a), r * math.sin(a), 0.0, 1.0]


def cloud(*points) -> np.ndarray:
    return np.array(points, dtype=np.float32)


def proc(pan: float | None = 0.0, mask: SelfMask | None = OWNER) -> LidarProcessor:
    p = LidarProcessor(LidarCfg(), FOOT, mask)
    p.set_camera_pan(pan)
    return p


def test_the_camera_is_dropped_and_anything_past_it_is_kept():
    p = proc(0.0)
    assert p.process(cloud(pt(0.27, 0)), 0).sectors_m[0] == 8.0  # within 0.24 + 0.05 margin
    s = p.process(cloud(pt(0.27, 0), pt(0.35, 0)), 0)  # a box 6 cm past the masked distance
    assert s.sectors_m[0] == pytest.approx(0.35)
    assert s.points == 1


def test_the_mask_is_only_in_its_own_sectors():
    s = proc(0.0).process(cloud(pt(0.27, 90), pt(0.27, -90)), 0)  # left and right: not the camera
    assert s.sectors_m[9] == pytest.approx(0.27) and s.sectors_m[27] == pytest.approx(0.27)


def test_the_mask_follows_the_pan():
    near_front = cloud(pt(0.27, 0))
    assert proc(0.0).process(near_front, 0).sectors_m[0] == 8.0
    assert proc(-40.0).process(near_front, 0).sectors_m[0] == pytest.approx(0.27)  # camera is away
    near_front_right = cloud(pt(0.28, -10))
    assert proc(-40.0).process(near_front_right, 0).sectors_m[35] == 8.0
    assert proc(0.0).process(near_front_right, 0).sectors_m[35] == pytest.approx(0.28)


def test_a_pan_between_two_measured_pans_uses_both():
    table = SelfMaskTable(OWNER, 36)
    assert table.bracket(-20.0) == (-40.0, 0.0)
    assert table.bracket(0.0) == (0.0,)
    assert table.bracket(55.0) == (40.0,)  # past the last measured pan: the end one
    assert table.bracket(-70.0) == (-40.0,)
    s = proc(-20.0).process(cloud(pt(0.27, 0), pt(0.28, -10)), 0)
    assert s.sectors_m[0] == 8.0 and s.sectors_m[35] == 8.0


def test_an_unknown_pan_uses_every_measured_pan():
    s = proc(None).process(cloud(pt(0.27, 0), pt(0.28, -10), pt(0.42, -40)), 0)
    assert s.sectors_m[0] == 8.0 and s.sectors_m[35] == 8.0 and s.sectors_m[32] == 8.0
    hidden = proc(None).process(cloud(pt(1.1, -30), pt(1.6, -10)), 0)
    assert hidden.sectors_m[34] == pytest.approx(1.1)  # the shadow of +-40 applies too


def test_a_hidden_sector_takes_its_nearer_neighbour_and_never_reads_free():
    s = proc(40.0).process(cloud(pt(1.1, -30), pt(1.6, -10)), 0)
    assert s.sectors_m[34] == pytest.approx(1.1)
    assert s.sectors_m[10] == 8.0  # an empty sector that is not hidden is still free
    seen = proc(40.0).process(cloud(pt(1.1, -30), pt(1.6, -10), pt(0.9, -20)), 0)
    assert seen.sectors_m[34] == pytest.approx(0.9)  # anything the L2 does see there counts
    not_hidden = proc(0.0).process(cloud(pt(1.1, -30), pt(1.6, -10)), 0)
    assert not_hidden.sectors_m[34] == 8.0  # at pan 0 the camera hides nothing


def test_the_owners_camera_no_longer_blocks_walking_but_a_box_still_does():
    camera = [pt(0.245, 0), pt(0.253, -20), pt(0.291, -30), pt(0.396, -40)]
    room = [pt(1.2, 10), pt(1.66, -10), pt(1.3, 90), pt(1.5, -90), pt(2.0, 180)]
    guard = SafetyGuard(SafetyCfg(), FOOT)
    unmasked = proc(0.0, mask=None).process(cloud(*camera, *room), 0)
    assert guard.limit_motion(0.05, 0, 0, unmasked, 0.05).vx == 0  # the bug: blocked by itself
    masked = proc(0.0).process(cloud(*camera, *room), 0)
    assert guard.limit_motion(0.05, 0, 0, masked, 0.05).vx > 0
    box = proc(0.0).process(cloud(*camera, *room, pt(0.35, 0)), 0)  # 11 cm past the legs
    out = guard.limit_motion(0.05, 0, 0, box, 0.05)
    assert out.vx == 0 and out.reason.startswith("obstacle")


def test_no_mask_file_gives_the_same_sector_map_as_before(tmp_path, caplog):
    rng = np.random.default_rng(7)
    pts = np.column_stack([rng.uniform(-3, 3, 2000), rng.uniform(-3, 3, 2000),
                           rng.uniform(-0.2, 0.3, 2000), np.ones(2000)]).astype(np.float32)
    before = LidarProcessor(LidarCfg(), FOOT).process(pts, 0)
    with caplog.at_level(logging.WARNING):
        feed = LidarFeed(LidarCfg(self_mask_file=str(tmp_path / "missing.yaml")), FOOT)
    assert "not found" in caplog.text
    feed.set_camera_pan(0.0)
    assert feed.proc.process(pts, 0) == before
    assert LidarFeed(LidarCfg(), FOOT).proc.process(pts, 0) == before


def test_the_mask_file_loads(tmp_path):
    f = tmp_path / "lidar_self_mask.yaml"
    f.write_text(OWNER_YAML)
    feed = LidarFeed(LidarCfg(self_mask_file=str(f)), FOOT)
    assert feed.proc.self_mask is not None and feed.proc.self_mask.pans == [-40.0, 0.0, 40.0]


@pytest.mark.parametrize(("text", "error"), [
    ("pans: {0: {mask: {0: 0.8}}}", "not the robot"),
    ("pans: {0: {mask: {0: 0.0}}}", "not the robot"),
    ("pans: {0: {mask: {36: 0.3}}}", "outside 0..35"),
    ("pans: {0: {shadow: [-1]}}", "outside 0..35"),
    ("pans: {120: {shadow: [3]}}", "outside -90..90"),
    ("pans: {}", "at least 1"),
    ("margin_m: 0.3\npans: {0: {}}", "less than or equal"),
    ("pans: {0: {masks: {0: 0.3}}}", "Extra inputs"),
])
def test_a_wrong_mask_file_stops_the_start(tmp_path, text, error):
    f = tmp_path / "lidar_self_mask.yaml"
    f.write_text(text)
    with pytest.raises(ValueError, match=error):
        LidarFeed(LidarCfg(self_mask_file=str(f)), FOOT)


def test_the_robot_tells_the_lidar_where_the_camera_points(cfg):
    robot, _servos, lidar, world, _brain, clock = make(cfg)
    seen: list[float | None] = []
    lidar.set_camera_pan = seen.append
    run_ticks(robot, lidar, world, clock, 0.1)
    assert seen[-1] is None  # relaxed: the camera servo is limp, so every pan applies
    stand(robot, lidar, world, clock)
    robot.handle(Look(pan_deg=30.0, speed=1.0, ts=5000.0, seq=50))
    run_ticks(robot, lidar, world, clock, 1.0)
    assert seen[-1] == pytest.approx(30.0)


def imu(ax: float, ay: float, az: float) -> list[bytes]:
    data = np.array([0, 0, 0, 1, 0, 0, 0, ax, ay, az], dtype="<f4")
    return [b"imu", struct.pack("<d", 1.0), data.tobytes()]


@pytest.mark.parametrize("yaw", [0.0, 90.0, 180.0, -90.0])
@pytest.mark.parametrize(("roll", "pitch"), [(0.0, 10.0), (8.0, 0.0), (-5.0, -7.0)])
def test_a_turned_l2_reads_the_same_tilt_as_one_facing_forward(yaw, roll, pitch):
    facing = LidarFeed(LidarCfg())
    g = 9.8
    r, p = math.radians(roll), math.radians(pitch)
    ax, ay, az = -g * math.sin(p), g * math.cos(p) * math.sin(r), g * math.cos(p) * math.cos(r)
    facing.handle(imu(ax, ay, az))
    want = facing.tilt()
    assert want == pytest.approx((roll, pitch), abs=0.01)
    c, s = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    turned = LidarFeed(LidarCfg(mount_yaw_deg=yaw))  # its x axis is turned yaw from forward
    turned.handle(imu(c * ax + s * ay, -s * ax + c * ay, az))
    assert turned.tilt() == pytest.approx(want, abs=0.01)


def test_nose_down_reads_nose_down_with_the_l2_turned_round():
    nose_down = imu(-1.7, 0.0, 9.65)  # the robot's frame: +pitch
    turned_round = imu(1.7, 0.0, 9.65)  # the same tilt, as an L2 facing backwards measures it
    forward, backward = LidarFeed(LidarCfg()), LidarFeed(LidarCfg(mount_yaw_deg=180))
    forward.handle(nose_down)
    backward.handle(turned_round)
    assert forward.tilt()[1] > 5 and backward.tilt() == pytest.approx(forward.tilt(), abs=0.01)


def test_the_file_the_measuring_tool_writes_loads_in_the_body(tmp_path):
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "infra" / "pi" / "lidar_self_mask.py"
    spec = importlib.util.spec_from_file_location("lidar_self_mask", path)
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    front = [1.5] * 36
    front[0], front[34], front[33], front[32] = 0.240, 0.253, 0.291, 0.396
    left = [1.5] * 36
    left[0], left[34], left[33], left[32] = 0.260, 8.0, 0.289, 0.305
    right = [1.5] * 36
    right[35], right[34] = 0.259, 8.0
    table, problems = tool.build({0.0: front, 40.0: left, -40.0: right}, 0.05)
    assert problems == []
    f = tmp_path / "lidar_self_mask.yaml"
    f.write_text(tool.to_yaml(table, "test"))
    feed = LidarFeed(LidarCfg(self_mask_file=str(f)), FOOT)
    feed.set_camera_pan(0.0)
    assert feed.proc.process(cloud(pt(0.27, 0), pt(1.5, 10)), 0).sectors_m[0] == 8.0
    feed.set_camera_pan(40.0)
    assert feed.proc.process(cloud(pt(1.1, -30), pt(1.6, -10)), 0).sectors_m[34] == 1.1
