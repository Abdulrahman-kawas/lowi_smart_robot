"""Body configuration: robot.yaml (+ calibration.yaml for per-servo trims and directions)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from spider_common.link import MqttSettings

LEG_NAMES = ("LF", "LM", "LR", "RF", "RM", "RR")
JOINTS = ("coxa", "femur", "tibia")
CAMERA_PAN = "camera_pan"  # servo id of the front camera's pan servo, beside "LF.coxa" and co.


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MqttCfg(_M):
    host: str
    port: int = 8883
    tls: bool = True
    ca_path: str | None = None
    cert_path: str | None = None
    key_path: str | None = None
    username: str | None = None  # loopback listener on the Pi: no certificate, no clock needed
    password_file: str | None = None
    reconnect_max_s: int = 30


def broker_settings(
    m: MqttCfg, client_id: str, username: str | None = None, password_file: str | None = None
) -> MqttSettings:
    """Settings for one process. Camera, recorder and sysmon pass their own broker login."""
    secret = password_file or m.password_file
    return MqttSettings(
        host=m.host, port=m.port, client_id=client_id, tls=m.tls, ca_path=m.ca_path,
        cert_path=m.cert_path, key_path=m.key_path, username=username or m.username,
        password=Path(secret).read_text("utf-8").strip() if secret else None,
        reconnect_max_s=m.reconnect_max_s,
    )


class PulseCfg(_M):
    """Servo pulse mapping, shared by every servo driver.

    "Servo degrees" in this code are LOGICAL: 90 = pulse centre, and one logical degree is one
    physical degree whatever the servo's full range is, so 90 +- range_deg / 2 are the ends of
    its travel (-45..225 on a 270-degree servo, 0..180 on a 180-degree one).
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
    # Joint limits in servo degrees around the calibrated neutral: the joint may go from
    # min_deg + trim_deg to max_deg + trim_deg (a horn seated off by the trim moves the joint's
    # stops with it), and never past the servo's own travel. See BodyConfig.limits_of.
    min_deg: float = 10.0
    max_deg: float = 170.0
    # This servo's own pulse range, for one servo that differs from the rest (a 180-degree
    # servo among 270-degree ones). None = the shared `pulse`. Logical degrees keep their
    # meaning either way.
    pulse: PulseCfg | None = None


class FemurServoCfg(ServoCfg):
    # Sitting needs the femur about 86 deg up (default geometry), more than +-80 allows.
    min_deg: float = 0.0
    max_deg: float = 180.0


class CameraPanCfg(ServoCfg):
    """The front camera's pan servo on the SSC-32U (owner: 10 kg, 180 degrees, channel 27).

    Servo degrees as for the legs: 90 + trim_deg looks straight ahead, and
    servo = 90 + trim_deg + direction * pan_deg, so after `spider-calibrate direction --camera`
    a positive pan turns the camera left. min_deg..max_deg keep it clear of the legs and its cable
    (they move with the trim, see BodyConfig.limits_of): widen them only after looking.
    """

    channel: int = Field(27, ge=0, le=31)
    min_deg: float = 30.0
    max_deg: float = 150.0
    pulse: PulseCfg | None = Field(default_factory=lambda: PulseCfg(range_deg=180.0))
    max_rate_dps: float = Field(90.0, gt=0.0, le=360.0)  # glide rate at Look.speed 1.0


class LegCfg(_M):
    name: Literal["LF", "LM", "LR", "RF", "RM", "RR"]
    mount_x: float  # m, + forward from body centre
    mount_y: float  # m, + left
    mount_angle_deg: float  # direction the coxa points at neutral, CCW from forward
    coxa: ServoCfg
    femur: FemurServoCfg
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


class MovesCfg(_M):
    """Expressive moves (moves.py). Every move is checked against these before it starts."""

    clear_radius_m: float = Field(0.35, ge=0.0)  # nothing this close to the footprint edge
    support_margin_m: float = Field(0.02, ge=0.0)  # body centre inside the feet polygon by this
    max_joint_speed_dps: float = Field(240.0, gt=0.0, le=600.0)
    max_duration_s: float = Field(20.0, gt=0.0, le=20.0)
    max_shift_m: float = Field(0.03, gt=0.0, le=0.03)  # body translation from where it started
    dance_bpm: float = Field(100.0, ge=60.0, le=140.0)
    reach_touch_height_m: float = Field(0.06, ge=0.02, le=0.15)  # "nearest": touch at this height
    # offer_hand: the foot goes to a fixed point this far ahead of the footprint edge, this high.
    offer_hand_ahead_m: float = Field(0.10, ge=0.0, le=0.20)
    offer_hand_height_m: float = Field(0.12, ge=0.04, le=0.20)
    # table: the feet step in toward the body, three at a time, then the body rises to this height
    # (ground to coxa joints) and holds with the legs nearly upright. Stand brings it back.
    table_in_m: float = Field(0.03, ge=0.0, le=0.05)
    table_height_m: float = Field(0.17, ge=0.10, le=0.19)


class CameraWindowCfg(_M):
    """The beams that hit the robot's own front camera (deg; bearing + left of straight ahead,
    elevation + above the L2's centre, both in the robot's frame). Nothing else is visible along
    them, so their points are only the camera and ghosts off its edges: dropped up to
    max_range_m. Beams below and beside the window are untouched, and the window may never
    reach below the L2's horizon, so whatever stands on the floor is always seen."""

    bearing_min_deg: float = Field(ge=-90.0, le=90.0)
    bearing_max_deg: float = Field(ge=-90.0, le=90.0)
    elevation_min_deg: float = Field(gt=0.0, le=90.0)
    elevation_max_deg: float = Field(gt=0.0, le=90.0)
    max_range_m: float = Field(0.6, gt=0.0, le=0.8)

    @model_validator(mode="after")
    def _a_real_window(self) -> CameraWindowCfg:
        if self.bearing_min_deg >= self.bearing_max_deg:
            raise ValueError("camera_window: bearing_min_deg must be below bearing_max_deg")
        if self.elevation_min_deg >= self.elevation_max_deg:
            raise ValueError("camera_window: elevation_min_deg must be below elevation_max_deg")
        return self


class LidarCfg(_M):
    enabled: bool = True
    endpoint: str = "ipc:///tmp/spider_lidar.ipc"
    mount_height_m: float = 0.15  # LiDAR origin above the ground when standing
    mount_yaw_deg: float = 0.0  # rotation of the LiDAR x axis vs robot forward
    imu_upside_down: bool = False  # the L2 hangs upside down: flips its points and its IMU
    z_min_m: float = 0.04  # ignore the floor
    z_max_m: float = 0.45  # ignore things above the robot
    max_range_m: float = 8.0
    sectors: int = 36
    # One cloud can miss sectors, so each sector reports its nearest return over this many clouds.
    history_clouds: int = Field(3, ge=1, le=10)
    camera_window: CameraWindowCfg | None = None  # None: the camera is not ignored


class CameraCfg(_M):
    backend: Literal["opencv", "picamera2", "fake", "none"] = "opencv"
    # A /dev/videoN number, or a stable /dev/v4l/by-id/... path. Prefer the path: with a ribbon
    # camera fitted, the CSI driver takes video0 at boot and USB cameras get whatever is left.
    device: int | str = 0
    width: int = 640
    height: int = 480
    jpeg_quality: int = 80
    max_bytes: int = 120_000  # kept below the broker's message_size_limit
    # True on the robot: the separate spider-camera process (cores 1-3) answers Snapshot and the
    # control process never loads OpenCV. False keeps the in-process camera for the simulator.
    external: bool = False
    client_id: str = "spider-camera"
    username: str | None = None
    password_file: str | None = None


class RtCfg(_M):
    """Real-time setup of the control process. Unsupported platforms log it and keep running."""

    enabled: bool = True
    cpu: int = Field(0, ge=0, le=3)
    priority: int = Field(50, ge=1, le=90)  # SCHED_FIFO; below kernel IRQ threads and watchdogs
    lock_memory: bool = True
    gil_switch_ms: float = Field(1.0, gt=0, le=10)  # how long another thread may hold the GIL


class WatchdogGpioCfg(_M):
    """A pin toggled once per good tick. External hardware cuts servo power if it stops."""

    chip: str = "/dev/gpiochip0"
    line: int = Field(17, ge=0)


class RecorderCfg(_M):
    endpoint: str = "ipc:///tmp/spider_lidar_rec.ipc"
    out_dir: str = "/var/lib/spider/rec"
    max_bytes: int = 8_000_000_000  # about 90 min at the full L2 point rate
    min_free_bytes: int = 1_000_000_000  # stop before the SD card fills
    client_id: str = "spider-recorder"
    username: str | None = None
    password_file: str | None = None


class SysmonCfg(_M):
    client_id: str = "spider-sysmon"
    username: str | None = None
    password_file: str | None = None
    server_tailscale_name: str = ""  # reports direct or relay path to this peer; empty = skip


class BodyConfig(_M):
    robot_id: str = "spider-01"
    mqtt: MqttCfg
    servo_driver: Literal["ssc32u", "pca9685"] = "ssc32u"
    pulse: PulseCfg = Field(default_factory=PulseCfg)  # every servo, unless it has its own
    ssc: SscCfg = Field(default_factory=SscCfg)
    pca: PcaCfg = Field(default_factory=PcaCfg)
    geometry: GeometryCfg = Field(default_factory=GeometryCfg)
    gait: GaitCfg = Field(default_factory=GaitCfg)
    safety: SafetyCfg = Field(default_factory=SafetyCfg)
    lidar: LidarCfg = Field(default_factory=LidarCfg)
    moves: MovesCfg = Field(default_factory=MovesCfg)
    camera: CameraCfg = Field(default_factory=CameraCfg)
    rt: RtCfg = Field(default_factory=RtCfg)
    watchdog_gpio: WatchdogGpioCfg | None = None  # None until the relay board is fitted
    recorder: RecorderCfg = Field(default_factory=RecorderCfg)
    sysmon: SysmonCfg = Field(default_factory=SysmonCfg)
    # File present = E-stop latched, across crashes and reboots. None disables it (simulator).
    estop_latch_path: str | None = None
    state_hz: float = 4.0
    legs: list[LegCfg]
    camera_pan: CameraPanCfg | None = None  # None: no pan servo (configs before 2026-11-20)

    def pulse_of(self, servo: ServoCfg) -> PulseCfg:
        """The pulse range this servo really uses: its own, or the shared one."""
        return servo.pulse or self.pulse

    def limits_of(self, servo: ServoCfg) -> tuple[float, float]:
        """The servo degrees this joint may be sent: min_deg..max_deg shifted by its trim, as
        the trim says how far its horn sits off, cut to the servo's own travel."""
        half = self.pulse_of(servo).range_deg / 2.0
        return (max(servo.min_deg + servo.trim_deg, 90.0 - half),
                min(servo.max_deg + servo.trim_deg, 90.0 + half))

    @model_validator(mode="after")
    def _check_safety(self) -> BodyConfig:
        s, g = self.safety, self.gait
        if not 0 < s.stop_distance_m < s.slow_distance_m:
            raise ValueError("safety: need 0 < stop_distance_m < slow_distance_m")
        # Distance needed to stop: braking, plus travel during detection. The L2 needs up to one
        # revolution (0.18 s) and one cloud (0.083 s) to report a new obstacle, then one tick.
        brake = g.max_vx**2 / (2 * g.accel) + g.max_vx * (1.0 / g.control_hz + 0.18 + 0.083)
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
        if self.camera_pan is not None:
            if self.servo_driver != "ssc32u":
                raise ValueError("camera_pan needs the SSC-32U (servo_driver: ssc32u)")
            if (0, self.camera_pan.channel) in used:
                raise ValueError(f"camera_pan: channel {self.camera_pan.channel} is a leg's")
        return self

    def leg(self, name: str) -> LegCfg:
        return next(leg for leg in self.legs if leg.name == name)

    def servo(self, joint_id: str) -> ServoCfg:
        if joint_id == CAMERA_PAN:
            if self.camera_pan is None:
                raise KeyError("camera_pan is not configured in robot.yaml")
            return self.camera_pan
        leg_name, joint = joint_id.split(".")
        return getattr(self.leg(leg_name), joint)

    def servo_ids(self) -> list[str]:
        """Every servo this body drives: the 18 leg joints, then the camera pan if fitted."""
        ids = [f"{leg.name}.{j}" for leg in self.legs for j in JOINTS]
        return ids + ([CAMERA_PAN] if self.camera_pan is not None else [])

    def pan_range(self) -> tuple[float, float]:
        """The pan angles (deg, + left) the camera may be sent: its servo limits, mapped."""
        s = self.camera_pan
        if s is None:
            raise KeyError("camera_pan is not configured in robot.yaml")
        lo, hi = self.limits_of(s)
        a, b = (lo - 90.0 - s.trim_deg) * s.direction, (hi - 90.0 - s.trim_deg) * s.direction
        return (min(a, b), max(a, b))

    def pan_servo_deg(self, pan_deg: float) -> float:
        """Servo degrees for a pan angle (deg, + left)."""
        s = self.camera_pan
        if s is None:
            raise KeyError("camera_pan is not configured in robot.yaml")
        return 90.0 + s.trim_deg + s.direction * pan_deg


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
        if joint_id == CAMERA_PAN and cfg.camera_pan is None:
            continue  # calibrated once, then removed from robot.yaml: nothing to apply
        servo = cfg.servo(joint_id)
        if "direction" in values:
            servo.direction = int(values["direction"])  # type: ignore[assignment]
        if "trim_deg" in values:
            servo.trim_deg = float(values["trim_deg"])


def save_calibration(cfg: BodyConfig, path: str | Path) -> None:
    out = {}
    for joint_id in cfg.servo_ids():
        s = cfg.servo(joint_id)
        out[joint_id] = {"direction": s.direction, "trim_deg": round(s.trim_deg, 2)}
    Path(path).write_text(yaml.safe_dump(out, sort_keys=True), "utf-8")
