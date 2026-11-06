"""Body configuration: robot.yaml (+ calibration.yaml for per-servo trims and directions)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

LEG_NAMES = ("LF", "LM", "LR", "RF", "RM", "RR")
JOINTS = ("coxa", "femur", "tibia")


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MqttCfg(_M):
    host: str
    port: int = 8883
    tls: bool = True
    ca_path: str | None = None
    cert_path: str | None = None
    key_path: str | None = None


class PulseCfg(_M):
    """Servo pulse mapping, shared by every servo driver.

    "Servo degrees" in this code are LOGICAL: 90 = pulse centre (the calibrated neutral pose),
    0..180 = +-90 deg of physical travel around it, whatever the servo's full range is.
    """

    min_us: float = 500.0
    max_us: float = 2500.0
    range_deg: float = 270.0  # physical travel between min_us and max_us (RDS3218: 270)

    def pulse_us(self, deg: float) -> float:
        centre = (self.min_us + self.max_us) / 2.0
        us = centre + (deg - 90.0) * (self.max_us - self.min_us) / self.range_deg
        return max(self.min_us, min(self.max_us, us))


class SscCfg(_M):
    """Lynxmotion SSC-32U on USB (FTDI serial). Set the board to 115200 baud (button)."""

    port: str = "/dev/ttyUSB0"  # prefer the stable /dev/serial/by-id/... path
    baud: int = 115200
    update_hz: float = 25.0  # group moves per second; each uses T = 1/update_hz to glide


class PcaCfg(_M):
    i2c_bus: int = 1
    addresses: list[int] = Field(default_factory=lambda: [0x40, 0x41])
    freq_hz: float = 50.0
    osc_hz: float = 25_000_000.0  # some PCA9685 boards run at 26-27 MHz; measure if angles drift


class ServoCfg(_M):
    board: int = Field(0, ge=0)  # PCA9685 only: index into pca.addresses
    channel: int = Field(ge=0, le=31)  # SSC-32U: 0-31; PCA9685: 0-15
    direction: Literal[1, -1] = 1
    trim_deg: float = 0.0
    min_deg: float = 10.0  # mechanical limits in servo degrees
    max_deg: float = 170.0


class LegCfg(_M):
    name: Literal["LF", "LM", "LR", "RF", "RM", "RR"]
    mount_x: float  # m, + forward from body centre
    mount_y: float  # m, + left
    mount_angle_deg: float  # direction the coxa points at neutral, CCW from forward
    coxa: ServoCfg
    femur: ServoCfg
    tibia: ServoCfg


class GeometryCfg(_M):
    coxa_m: float = 0.045
    femur_m: float = 0.075
    tibia_m: float = 0.130
    stance_radius_m: float = 0.12  # horizontal distance mount -> foot at neutral
    body_height_m: float = 0.09  # standing height (ground -> coxa joints)
    sit_height_m: float = 0.035
    # Half-extents of the robot INCLUDING the legs at neutral stance (top view, from the body
    # centre). LiDAR points inside this box are the robot itself and are ignored; obstacle
    # distances are measured from the edge of this box.
    footprint_x_m: float = 0.24
    footprint_y_m: float = 0.27
    # Joint angles (deg) that correspond to servo 90 deg after calibration:
    # coxa 0 = pointing along mount_angle, femur 0 = horizontal, tibia 90 = vertical down.
    coxa_neutral_deg: float = 0.0
    femur_neutral_deg: float = 0.0
    tibia_neutral_deg: float = 90.0


class GaitCfg(_M):
    period_s: float = 1.0
    step_height_m: float = 0.035
    max_stride_m: float = 0.07
    max_vx: float = 0.12  # m/s
    max_vy: float = 0.08
    max_wz: float = 0.6  # rad/s
    accel: float = 0.25  # m/s^2
    yaw_accel: float = 1.5  # rad/s^2
    control_hz: float = 50.0
    posture_speed_mps: float = 0.04  # how fast stand/sit changes height


class SafetyCfg(_M):
    link_timeout_s: float = 1.5  # no heartbeat for this long while walking -> stop
    max_cmd_age_s: float = 1.0  # older commands are rejected (needs NTP on both ends)
    require_lidar: bool = True  # set false only for bench tests with the robot on a stand
    lidar_timeout_s: float = 0.5
    # Distances below are measured from the EDGE of geometry.footprint, not the LiDAR centre.
    stop_distance_m: float = 0.15  # stop when an obstacle in the path is this close
    slow_distance_m: float = 0.40  # start slowing down here
    corridor_margin_m: float = 0.04  # extra width on each side of the swept corridor
    turn_clearance_m: float = 0.06  # free ring needed outside the swept turning circle
    max_level_deg: float = 2.0  # body must be level (roll/pitch) before walking
    imu_timeout_s: float = 0.3  # stale IMU = tilt unknown = no motion (if require_lidar)
    max_tilt_deg: float = 30.0  # stop walking
    fall_tilt_deg: float = 55.0  # relax servos (robot has fallen)


class LidarCfg(_M):
    enabled: bool = True
    endpoint: str = "ipc:///tmp/spider_lidar.ipc"
    mount_height_m: float = 0.15  # LiDAR origin above the ground when standing
    mount_yaw_deg: float = 0.0  # rotation of the LiDAR x axis vs robot forward
    imu_upside_down: bool = False  # LiDAR mounted upside down: at rest roll would read ~180
    z_min_m: float = 0.04  # ignore the floor
    z_max_m: float = 0.45  # ignore things above the robot
    max_range_m: float = 8.0
    sectors: int = 36


class CameraCfg(_M):
    backend: Literal["opencv", "picamera2", "fake", "none"] = "opencv"
    device: int = 0
    width: int = 640
    height: int = 480
    jpeg_quality: int = 80
    max_bytes: int = 120_000  # AWS IoT Core payload limit is 128 KB


class BodyConfig(_M):
    robot_id: str = "spider-01"
    mqtt: MqttCfg
    servo_driver: Literal["ssc32u", "pca9685"] = "ssc32u"
    pulse: PulseCfg = Field(default_factory=PulseCfg)
    ssc: SscCfg = Field(default_factory=SscCfg)
    pca: PcaCfg = Field(default_factory=PcaCfg)
    geometry: GeometryCfg = Field(default_factory=GeometryCfg)
    gait: GaitCfg = Field(default_factory=GaitCfg)
    safety: SafetyCfg = Field(default_factory=SafetyCfg)
    lidar: LidarCfg = Field(default_factory=LidarCfg)
    camera: CameraCfg = Field(default_factory=CameraCfg)
    state_hz: float = 4.0
    legs: list[LegCfg]

    @model_validator(mode="after")
    def _check_safety(self) -> BodyConfig:
        s, g = self.safety, self.gait
        if not 0 < s.stop_distance_m < s.slow_distance_m:
            raise ValueError("safety: need 0 < stop_distance_m < slow_distance_m")
        # distance needed to stop: one control tick + one telemetry period of travel + braking
        brake = g.max_vx**2 / (2 * g.accel) + g.max_vx * (1.0 / g.control_hz + 0.1)
        if s.stop_distance_m < brake:
            raise ValueError(f"safety.stop_distance_m must be >= {brake:.3f} m for max_vx/accel")
        if s.turn_clearance_m <= 0:
            raise ValueError("safety.turn_clearance_m must be > 0")
        return self

    @model_validator(mode="after")
    def _check_legs(self) -> BodyConfig:
        names = sorted(leg.name for leg in self.legs)
        if names != sorted(LEG_NAMES):
            raise ValueError(f"legs must be exactly {LEG_NAMES}, got {names}")
        if self.servo_driver == "ssc32u" and self.ssc.baud < 38400:
            raise ValueError(
                "ssc.baud must be >= 38400 (18 servos x 25 updates/s does not fit in 9600 baud). "
                "Set the SSC-32U to 115200 with its baud button."
            )
        used: set[tuple[int, int]] = set()
        for leg in self.legs:
            for joint in JOINTS:
                s: ServoCfg = getattr(leg, joint)
                if self.servo_driver == "pca9685":
                    if s.board >= len(self.pca.addresses):
                        raise ValueError(f"{leg.name}.{joint}: board {s.board} has no address")
                    if s.channel > 15:
                        raise ValueError(f"{leg.name}.{joint}: PCA9685 channels are 0-15")
                key = (s.board if self.servo_driver == "pca9685" else 0, s.channel)
                if key in used:
                    raise ValueError(f"{leg.name}.{joint}: board/channel {key} used twice")
                used.add(key)
        return self

    def leg(self, name: str) -> LegCfg:
        return next(leg for leg in self.legs if leg.name == name)

    def servo(self, joint_id: str) -> ServoCfg:
        leg_name, joint = joint_id.split(".")
        return getattr(self.leg(leg_name), joint)


def load_config(path: str | Path, calibration: str | Path | None = None) -> BodyConfig:
    data = yaml.safe_load(Path(path).read_text("utf-8"))
    cfg = BodyConfig.model_validate(data)
    cal_path = Path(calibration) if calibration else Path(path).with_name("calibration.yaml")
    if cal_path.exists():
        apply_calibration(cfg, yaml.safe_load(cal_path.read_text("utf-8")) or {})
    return cfg


def apply_calibration(cfg: BodyConfig, cal: dict) -> None:
    """calibration.yaml maps "LF.coxa" -> {direction: 1|-1, trim_deg: float}."""
    for joint_id, values in cal.items():
        servo = cfg.servo(joint_id)
        if "direction" in values:
            servo.direction = int(values["direction"])  # type: ignore[assignment]
        if "trim_deg" in values:
            servo.trim_deg = float(values["trim_deg"])


def save_calibration(cfg: BodyConfig, path: str | Path) -> None:
    out = {}
    for leg in cfg.legs:
        for joint in JOINTS:
            s: ServoCfg = getattr(leg, joint)
            out[f"{leg.name}.{joint}"] = {
                "direction": s.direction,
                "trim_deg": round(s.trim_deg, 2),
            }
    Path(path).write_text(yaml.safe_dump(out, sort_keys=True), "utf-8")
