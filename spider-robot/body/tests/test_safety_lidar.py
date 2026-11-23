import struct

import numpy as np
import pytest
from spider_common.protocol import LidarSummary

from spider_body.config import LidarCfg, SafetyCfg
from spider_body.hw.lidar import LidarFeed, LidarProcessor, SimWorld
from spider_body.safety import SafetyGuard, corridor_clearance

FOOT = (0.24, 0.27)


def summary_with(front: float, default: float = 5.0) -> LidarSummary:
    """front = distance of an obstacle straight ahead, from the LiDAR centre."""
    sectors = [default] * 36
    for i in (35, 0, 1):
        sectors[i] = front
    return LidarSummary(ts=0, sector_deg=10, sectors_m=sectors, nearest_m=min(sectors),
                        nearest_bearing_deg=0, points=100)


def test_processor_builds_sector_map():
    cfg = LidarCfg(mount_height_m=0.15)
    pts = np.array(
        [
            [1.0, 0.0, 0.0, 1],  # 1 m ahead, 0.15 m above ground -> kept
            [0.0, 2.0, 0.0, 1],  # 2 m left -> kept (sector 9)
            [0.5, 0.0, -0.14, 1],  # floor (z=0.01) -> ignored
            [0.1, 0.1, 0.0, 1],  # inside the footprint box (own leg) -> ignored
            [-3.0, 0.0, 1.0, 1],  # above the robot -> ignored
        ],
        dtype=np.float32,
    )
    s = LidarProcessor(cfg, FOOT).process(pts, 0.0)
    assert s.sectors_m[0] == pytest.approx(1.0)
    assert s.sectors_m[9] == pytest.approx(2.0)
    assert s.sectors_m[18] == cfg.max_range_m
    assert s.nearest_m == pytest.approx(1.0) and s.nearest_bearing_deg == 0
    assert s.points == 2


def test_near_object_outside_footprint_is_seen():
    # Reviewer finding: a radius filter made anything closer than 0.25 m read as "8 m free".
    pts = np.array([[0.28, 0.0, 0.0, 1]], dtype=np.float32)  # 4 cm in front of the legs
    s = LidarProcessor(LidarCfg(), FOOT).process(pts, 0.0)
    assert s.sectors_m[0] == pytest.approx(0.28)
    g = SafetyGuard(SafetyCfg(), FOOT)
    out = g.limit_motion(0.05, 0, 0, s, 0.05)
    assert out.vx == 0 and out.reason.startswith("obstacle")


def test_height_offset_follows_body_height():
    p = LidarProcessor(LidarCfg(mount_height_m=0.15, z_min_m=0.04), FOOT)
    box = np.array([[1.0, 0.0, -0.08, 1]], dtype=np.float32)  # 7 cm tall box top when standing
    assert p.process(box, 0).sectors_m[0] == pytest.approx(1.0)
    p.height_offset = -0.05  # body lowered by 5 cm: the same point is now on the floor band
    assert p.process(box, 0).sectors_m[0] == 8.0


def test_feed_parses_bridge_frames():
    feed = LidarFeed(LidarCfg())
    pts = np.array([[1.0, 0.0, 0.0, 5.0]], dtype="<f4")
    feed.handle([b"cloud", struct.pack("<dII", 1.0, 7, 1), pts.tobytes()])
    s, age = feed.latest()
    assert s is not None and age is not None and s.sectors_m[0] == pytest.approx(1.0)
    assert feed.tilt() == (None, None)  # no IMU yet = unknown, not level
    imu = np.array([0, 0, 0, 1, 0, 0, 0, 0.0, 0.0, 9.8], dtype="<f4")
    feed.handle([b"imu", struct.pack("<d", 1.0), imu.tobytes()])
    assert feed.tilt() == pytest.approx((0.0, 0.0))


def test_imu_goes_stale():
    feed = LidarFeed(LidarCfg(), imu_timeout_s=0.0)
    imu = np.array([0, 0, 0, 1, 0, 0, 0, 0.0, 0.0, 9.8], dtype="<f4")
    feed.handle([b"imu", struct.pack("<d", 1.0), imu.tobytes()])
    assert feed.tilt() == (None, None)


def test_imu_upside_down_flag():
    imu = np.array([0, 0, 0, 1, 0, 0, 0, 0.0, 0.0, -9.8], dtype="<f4")  # gravity reads negative z
    plain = LidarFeed(LidarCfg())
    plain.handle([b"imu", struct.pack("<d", 1.0), imu.tobytes()])
    assert abs(plain.tilt()[0]) == pytest.approx(180.0)  # would look like the robot fell over
    flipped = LidarFeed(LidarCfg(imu_upside_down=True))
    flipped.handle([b"imu", struct.pack("<d", 1.0), imu.tobytes()])
    assert flipped.tilt() == pytest.approx((0.0, 0.0))


def test_corridor_measures_from_footprint_edge():
    s = summary_with(0.54)  # 0.30 m in front of the 0.24 m footprint
    assert corridor_clearance(s, 0, FOOT, 0.04) == pytest.approx(0.30, abs=0.01)
    assert corridor_clearance(s, 180, FOOT, 0.04) == pytest.approx(5.0 - 0.24, abs=0.01)


def test_corridor_catches_side_obstacle_a_cone_missed():
    # obstacle 0.6 m ahead and 0.22 m to the side: outside a +-35 deg cone at 0.3 m,
    # but inside the swept corridor of a 0.27 m half-wide robot
    sectors = [5.0] * 36
    sectors[2] = 0.64  # bearing 20 deg: x=0.60, y=0.22
    s = LidarSummary(ts=0, sector_deg=10, sectors_m=sectors, nearest_m=0.64,
                     nearest_bearing_deg=20, points=1)
    assert corridor_clearance(s, 0, FOOT, 0.04) == pytest.approx(0.60 - 0.24, abs=0.01)


def test_obstacle_blocks_forward_but_not_backward():
    g = SafetyGuard(SafetyCfg(), FOOT)
    s = summary_with(0.35)
    fwd = g.limit_motion(0.1, 0, 0, s, 0.05)
    assert fwd.vx == 0 and fwd.reason.startswith("obstacle")
    back = g.limit_motion(-0.1, 0, 0, s, 0.05)
    assert back.vx == -0.1 and back.reason is None


def test_slow_zone_scales_speed():
    g = SafetyGuard(SafetyCfg(stop_distance_m=0.15, slow_distance_m=0.40), FOOT)
    s = summary_with(0.24 + 0.275)
    free = corridor_clearance(s, 0, FOOT, 0.04)  # ~0.27 m (side sectors project closer)
    out = g.limit_motion(0.1, 0, 0, s, 0.05)
    assert 0.15 < free < 0.40
    assert out.vx == pytest.approx(0.1 * (free - 0.15) / 0.25)


def test_turn_reflex_fires():
    # Reviewer finding: the old turn check could never trigger.
    g = SafetyGuard(SafetyCfg(turn_clearance_m=0.06), FOOT)
    near = g.limit_motion(0, 0, 0.5, summary_with(0.40), 0.05)
    assert near.wz == 0 and near.reason.startswith("too close to turn")
    far = g.limit_motion(0, 0, 0.5, summary_with(1.0), 0.05)
    assert far.wz == 0.5


def test_stale_lidar_blocks_motion():
    g = SafetyGuard(SafetyCfg(require_lidar=True), FOOT)
    assert g.limit_motion(0.1, 0, 0.3, summary_with(5.0), 2.0).reason == "lidar_stale"
    assert g.limit_motion(0.1, 0, 0, None, None).vx == 0
    bench = SafetyGuard(SafetyCfg(require_lidar=False), FOOT)
    assert bench.limit_motion(0.1, 0, 0, None, None).vx == 0.1


def test_tilt_levels():
    g = SafetyGuard(SafetyCfg(max_tilt_deg=30, fall_tilt_deg=55), FOOT)
    assert g.tilt_state(5, -3) == "ok"
    assert g.tilt_state(35, 0) == "tilt"
    assert g.tilt_state(0, -70) == "fallen"
    assert g.tilt_state(None, None) == "ok"


def test_config_rejects_unsafe_stop_distance(cfg):
    from pydantic import ValidationError

    from spider_body.config import BodyConfig

    data = cfg.model_dump()
    data["safety"]["stop_distance_m"] = 0.01
    with pytest.raises(ValidationError):
        BodyConfig.model_validate(data)


def test_sim_world_ray():
    w = SimWorld(obstacles=[(1.0, 0.0, 0.2)])
    assert w.ray(0.0, 8.0) == pytest.approx(0.8)
    assert w.ray(3.14159265 / 2, 8.0) == pytest.approx(2.0)


class FakeSMBus:
    def __init__(self):
        self.regs = {}
        self.transfers = []

    def read_byte_data(self, addr, reg):
        return self.regs.get((addr, reg), 0x11)

    def write_byte_data(self, addr, reg, val):
        self.regs[(addr, reg)] = val

    def write_i2c_block_data(self, addr, reg, data):
        self.transfers.append((addr, reg, list(data)))

    def i2c_rdwr(self, *msgs):
        for m in msgs:
            data = list(m)
            self.transfers.append((m.addr, data[0], data[1:]))


def test_servo_bank_writes_only_changes_in_one_transfer_per_board(cfg):
    from spider_body.hw.servos import PcaServoBank

    data = cfg.model_dump()
    data["servo_driver"] = "pca9685"
    data["camera_pan"] = None  # the camera pan needs the SSC-32U
    for leg in data["legs"]:
        for j in ("coxa", "femur", "tibia"):
            if leg[j]["channel"] >= 16:  # channels 16-31: second board, channels 0-15
                leg[j]["board"], leg[j]["channel"] = 1, leg[j]["channel"] - 16
    cfg = type(cfg).model_validate(data)
    bus = FakeSMBus()
    bank = PcaServoBank(cfg, bus=bus)
    angles = {f"{leg}.{j}": 90.0 for leg in ("LF", "LM", "LR", "RF", "RM", "RR")
              for j in ("coxa", "femur", "tibia")}
    bus.transfers.clear()
    bank.write(angles)
    assert len(bus.transfers) == 2  # one per board, not 18
    used: dict[int, list[int]] = {}  # board -> its channels, from the config (any wiring)
    for s in bank.servos.values():
        used.setdefault(s.board, []).append(s.channel)
    for addr, reg, data in bus.transfers:  # one span per board, lowest to highest channel used
        chans = used[cfg.pca.addresses.index(addr)]
        assert reg == 0x06 + 4 * min(chans) and len(data) == 4 * (max(chans) - min(chans) + 1)
    bus.transfers.clear()
    bank.write(angles)  # nothing changed -> no I2C traffic at all
    assert bus.transfers == []
    angles["RM.femur"] = 100.0
    bank.write(angles)
    femur = bank.servos["RM.femur"]
    assert len(bus.transfers) == 1 and bus.transfers[0][0] == cfg.pca.addresses[femur.board]
    assert bus.transfers[0][1] == 0x06 + 4 * femur.channel and len(bus.transfers[0][2]) == 4


class FakeSerial:
    def __init__(self, reply=b"SSC32-V2.50USB\r"):
        self.written: list[bytes] = []
        self.reply = reply

    def write(self, data):
        self.written.append(bytes(data))
        return len(data)

    def reset_input_buffer(self):
        pass

    def read_until(self, end):
        return self.reply


def test_ssc32u_group_moves_changed_only_and_rate_limited(cfg):
    from spider_body.hw.servos import SscServoBank

    t = [0.0]
    ser = FakeSerial()
    bank = SscServoBank(cfg, port=ser, clock=lambda: t[0])
    angles = {f"{leg}.{j}": 90.0 for leg in ("LF", "LM", "LR", "RF", "RM", "RR")
              for j in ("coxa", "femur", "tibia")}
    bank.write(angles)
    cmd = ser.written[-1].decode()
    channels = sorted(s.channel for jid, s in bank.servos.items() if jid != "camera_pan")
    assert cmd == "".join(f"#{ch}P1500" for ch in channels) + "T40\r"  # 25 Hz -> T40, all 18
    ser.written.clear()
    t[0] = 0.02
    bank.write(angles)  # nothing changed -> nothing sent
    assert ser.written == []
    angles["RM.femur"] = 117.0  # +27 logical deg = +27 * 2000/270 us = +200 us
    t[0] = 0.03
    bank.write(angles)  # only 30 ms after the last group move -> held back
    assert ser.written == []
    t[0] = 0.04
    bank.write(angles)
    assert ser.written == [f"#{bank.servos['RM.femur'].channel}P1700T40\r".encode()]
    bank.relax()  # every channel, the camera's (27) too
    every = sorted(s.channel for s in bank.servos.values())
    assert ser.written[-1] == ("".join(f"#{ch}P0" for ch in every) + "\r").encode()
    assert bank.version() == "SSC32-V2.50USB"


def test_pulse_mapping_for_270_degree_servo():
    from spider_body.config import PulseCfg

    p = PulseCfg(min_us=500, max_us=2500, range_deg=270)
    assert p.pulse_us(90) == 1500
    assert p.pulse_us(90 + 135) == 2500 and p.pulse_us(-500) == 500


def test_ssc_rejects_9600_baud(cfg):
    from pydantic import ValidationError

    data = cfg.model_dump()
    data["ssc"]["baud"] = 9600
    with pytest.raises(ValidationError):
        type(cfg).model_validate(data)


# The owner wired the servos on 2026-11-19 and keeps this layout:
# coxa (at the body), femur, tibia (tip).
WIRED = {"LF": (29, 30, 31), "LM": (22, 21, 20), "LR": (19, 18, 16),
         "RF": (13, 14, 15), "RM": (5, 6, 7), "RR": (1, 2, 3)}


@pytest.mark.parametrize("name", ["robot.example.yaml", "robot.sim.yaml"])
def test_the_configs_carry_the_owners_wiring(name):
    from pathlib import Path

    from spider_body.config import load_config

    path = Path(__file__).resolve().parents[1] / "config" / name
    cfg = load_config(path, calibration="/nonexistent")
    wired = {leg.name: (leg.coxa.channel, leg.femur.channel, leg.tibia.channel) for leg in cfg.legs}
    assert wired == WIRED
    used = {getattr(leg, j).channel for leg in cfg.legs for j in ("coxa", "femur", "tibia")}
    assert 27 not in used  # the camera's servo


def test_the_one_180_degree_servo_gets_its_own_pulse_range(cfg):
    from spider_body.hw.servos import SscServoBank

    lr_tibia = next(leg.tibia for leg in cfg.legs if leg.name == "LR")
    assert cfg.pulse_of(lr_tibia).range_deg == 180 and cfg.pulse.range_deg == 270
    ser = FakeSerial()
    bank = SscServoBank(cfg, port=ser, clock=lambda: 0.0)
    angles = {f"{leg}.{j}": 90.0 for leg in WIRED for j in ("coxa", "femur", "tibia")}
    angles["LR.tibia"] = angles["LF.tibia"] = 117.0  # +27 logical deg on each
    bank.write(angles)
    cmd = ser.written[-1].decode()
    assert "#16P1800" in cmd  # 180-degree servo: +27 * 2000/180 = +300 us
    assert "#31P1700" in cmd  # 270-degree servo: +27 * 2000/270 = +200 us
