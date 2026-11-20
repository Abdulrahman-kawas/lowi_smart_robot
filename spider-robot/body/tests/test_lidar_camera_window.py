"""The L2 drops the beams that hit the front camera, and only near the L2; and its IMU turns with
it.

CAMERA_EDGE is what the L2 saw outside the footprint box on the robot (2026-11-20, tripod,
camera at pan 0, nothing else within 0.5 m in front): the camera's front edge 0.5-1 cm past
the box, and ghost returns off that edge out to 0.5 m. The camera stands above the L2's centre,
so all of it is 6-29 deg up; things on the floor are seen below it.
"""

import math
import struct

import numpy as np
import pytest
from pydantic import ValidationError

from spider_body.config import CameraWindowCfg, LidarCfg, SafetyCfg
from spider_body.hw.lidar import LidarFeed, LidarProcessor
from spider_body.safety import SafetyGuard

FOOT = (0.24, 0.27)
CAMERA_EDGE = [  # x, y, z0 (m, robot frame, z from the L2 centre): measured 2026-11-20
    (0.404, -0.081, +0.075), (0.349, -0.068, +0.089), (0.249, -0.134, +0.057),
    (0.326, -0.052, +0.073), (0.244, -0.001, +0.047), (0.250, +0.001, +0.084),
    (0.252, -0.159, +0.082), (0.340, -0.216, +0.086), (0.341, -0.082, +0.085),
    (0.399, -0.078, +0.075), (0.259, -0.007, +0.111), (0.353, -0.242, +0.084),
    (0.261, -0.071, +0.075), (0.417, -0.117, +0.085), (0.505, -0.115, +0.078),
    (0.320, -0.075, +0.072), (0.243, -0.074, +0.074), (0.386, -0.122, +0.082),
    (0.457, -0.145, +0.079), (0.425, -0.134, +0.067), (0.399, -0.124, +0.057),
    (0.393, -0.122, +0.048), (0.319, -0.043, +0.071), (0.436, -0.061, +0.072),
    (0.254, -0.173, +0.071), (0.290, -0.081, +0.048), (0.304, +0.018, +0.061),
    (0.242, -0.084, +0.068), (0.270, -0.094, +0.065), (0.243, -0.045, +0.133),
    (0.317, -0.057, +0.085), (0.494, -0.091, +0.097), (0.423, -0.058, +0.076),
    (0.287, -0.041, +0.072), (0.280, -0.059, +0.080), (0.410, -0.090, +0.088),
]
# The whole camera, with 5 deg around it: bearing -50..+3, elevation 11..37 as measured.
WINDOW = CameraWindowCfg(bearing_min_deg=-55, bearing_max_deg=8, elevation_min_deg=5,
                         elevation_max_deg=42, max_range_m=0.6)


def at(r: float, bearing_deg: float, z0: float = 0.0) -> tuple[float, float, float]:
    a = math.radians(bearing_deg)
    return (r * math.cos(a), r * math.sin(a), z0)


ROOM = [at(0.8, b) for b in range(-180, 180, 10)]  # the room, at the L2's height


def cloud(points) -> np.ndarray:
    return np.array([[x, y, z, 1.0] for x, y, z in points], dtype=np.float32)


def sectors(points, window: CameraWindowCfg | None = WINDOW) -> list[float]:
    proc = LidarProcessor(LidarCfg(camera_window=window), FOOT)
    return proc.process(cloud(points), 0).sectors_m


def walk_ahead(points, window: CameraWindowCfg | None = WINDOW) -> float:
    proc = LidarProcessor(LidarCfg(camera_window=window), FOOT)
    return SafetyGuard(SafetyCfg(), FOOT).limit_motion(
        0.05, 0, 0, proc.process(cloud(points), 0), 0.05).vx


def test_the_camera_alone_stops_the_robot_without_the_window():
    assert walk_ahead(CAMERA_EDGE + ROOM, window=None) == 0
    assert min(sectors(CAMERA_EDGE + ROOM, window=None)[33:] + [0.3]) < 0.26


def test_with_the_window_the_camera_and_its_ghosts_are_gone():
    s = sectors(CAMERA_EDGE + ROOM)
    assert s == sectors(ROOM)
    assert walk_ahead(CAMERA_EDGE + ROOM) > 0


def test_a_box_on_the_floor_ahead_is_seen_below_the_camera():
    box = [at(0.35, b, z0) for b in (-10, -5, 0, 5) for z0 in (-0.10, -0.05, 0.0, 0.03)]
    s = sectors(CAMERA_EDGE + ROOM + box)
    assert s[0] == pytest.approx(0.35, abs=0.005)
    assert walk_ahead(CAMERA_EDGE + ROOM + box) == 0


def test_only_near_the_l2_and_only_inside_the_window():
    up_ahead = at(0.45, -20, 0.08)  # 10 deg up, inside the window: the camera's ghost zone
    assert sectors([up_ahead])[34] == 8.0
    far = at(0.7, -20, 0.12)  # same beam, past max_range_m: kept
    assert sectors([far])[34] == pytest.approx(0.7, abs=0.005)
    beside = at(0.45, 30, 0.08)  # left of the window: kept
    assert sectors([beside])[3] == pytest.approx(0.45, abs=0.005)
    below = at(0.45, -20, 0.02)  # under the window (2.5 deg up): kept
    assert sectors([below])[34] == pytest.approx(0.45, abs=0.005)


def test_no_window_gives_the_same_sector_map_as_before():
    rng = np.random.default_rng(7)
    pts = np.column_stack([rng.uniform(-3, 3, 2000), rng.uniform(-3, 3, 2000),
                           rng.uniform(-0.2, 0.3, 2000), np.ones(2000)]).astype(np.float32)
    assert (LidarProcessor(LidarCfg(), FOOT).process(pts, 0)
            == LidarProcessor(LidarCfg(camera_window=None), FOOT).process(pts, 0))


def test_the_window_turns_with_the_mount_yaw():
    # an L2 turned 180 deg: the camera in front of the robot is behind the L2's own x axis
    proc = LidarProcessor(LidarCfg(camera_window=WINDOW, mount_yaw_deg=180), FOOT)
    x, y, z0 = at(0.45, -20, 0.08)
    assert proc.process(cloud([(-x, -y, z0)]), 0).sectors_m[34] == 8.0


@pytest.mark.parametrize(("fields", "error"), [
    ({"elevation_min_deg": 0}, "greater than 0"),  # never at or below the L2's horizon
    ({"elevation_min_deg": -5}, "greater than 0"),
    ({"bearing_min_deg": 10}, "bearing_min_deg must be below"),
    ({"elevation_max_deg": 4}, "elevation_min_deg must be below"),
    ({"max_range_m": 1.0}, "less than or equal to 0.8"),
    ({"bearing_max_deg": 120}, "less than or equal to 90"),
])
def test_a_wrong_window_is_refused(fields, error):
    with pytest.raises(ValidationError, match=error):
        CameraWindowCfg.model_validate(WINDOW.model_dump() | fields)


def test_robot_yaml_takes_the_window():
    cfg = LidarCfg.model_validate({"camera_window": {
        "bearing_min_deg": -30, "bearing_max_deg": 30, "elevation_min_deg": 6,
        "elevation_max_deg": 42}})
    assert cfg.camera_window.max_range_m == 0.6


def imu(ax: float, ay: float, az: float) -> list[bytes]:
    data = np.array([0, 0, 0, 1, 0, 0, 0, ax, ay, az], dtype="<f4")
    return [b"imu", struct.pack("<d", 1.0), data.tobytes()]


@pytest.mark.parametrize("yaw", [0.0, 90.0, 180.0, -90.0, 204.0])
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
