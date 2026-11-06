"""Wire protocol between the robot body (Raspberry Pi) and the brain (AWS first, local later).

Every message is JSON over MQTT, except camera frames, which are raw JPEG bytes.

Safety contract: the body validates every command with these models and then clamps the
values again with its own (tighter) limits from robot.yaml. The brain is never trusted to
keep the robot safe; it can only ask.
"""

from __future__ import annotations

import time
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

PROTOCOL_VERSION = 2  # bump on any incompatible change; the body rejects other versions


def now() -> float:
    return time.time()


class Topics:
    """MQTT topic names for one robot. Keep them in sync with infra/aws/*-policy.json."""

    def __init__(self, robot_id: str, prefix: str = "spider") -> None:
        base = f"{prefix}/{robot_id}"
        self.cmd = f"{base}/cmd"  # brain -> body
        self.state = f"{base}/state"  # body -> brain (periodic)
        self.event = f"{base}/event"  # body -> brain (acks, safety trips)
        self.camera_prefix = f"{base}/camera"  # body -> brain (JPEG bytes)

    def camera(self, request_id: str) -> str:
        return f"{self.camera_prefix}/{request_id}"

    @property
    def camera_filter(self) -> str:
        return f"{self.camera_prefix}/+"


# --------------------------------------------------------------------------- commands
class _Cmd(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: int = PROTOCOL_VERSION
    session: str = Field("", max_length=64)  # one per brain process; seq is ordered within it
    seq: int = 0
    ts: float = Field(default_factory=now)


class Move(_Cmd):
    """Walk with a body velocity for at most duration_s, then stop by itself."""

    type: Literal["move"] = "move"
    vx: float = Field(0.0, ge=-0.5, le=0.5)  # m/s, + forward
    vy: float = Field(0.0, ge=-0.5, le=0.5)  # m/s, + left
    wz: float = Field(0.0, ge=-2.0, le=2.0)  # rad/s, + counter-clockwise (left turn)
    duration_s: float = Field(1.0, gt=0.0, le=10.0)
    gait: Literal["tripod", "ripple", "wave"] = "tripod"


class Stop(_Cmd):
    type: Literal["stop"] = "stop"


class Posture(_Cmd):
    type: Literal["posture"] = "posture"
    posture: Literal["stand", "sit", "relax"]


class BodyPose(_Cmd):
    type: Literal["body_pose"] = "body_pose"
    height_m: float | None = Field(None, ge=0.03, le=0.20)
    roll_deg: float = Field(0.0, ge=-20.0, le=20.0)
    pitch_deg: float = Field(0.0, ge=-20.0, le=20.0)
    yaw_deg: float = Field(0.0, ge=-20.0, le=20.0)


class Snapshot(_Cmd):
    type: Literal["snapshot"] = "snapshot"
    request_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class Heartbeat(_Cmd):
    type: Literal["heartbeat"] = "heartbeat"


class EStop(_Cmd):
    type: Literal["estop"] = "estop"


class EStopRelease(_Cmd):
    type: Literal["estop_release"] = "estop_release"


Command = Annotated[
    Move | Stop | Posture | BodyPose | Snapshot | Heartbeat | EStop | EStopRelease,
    Field(discriminator="type"),
]
_COMMAND: TypeAdapter[Command] = TypeAdapter(Command)


def parse_command(payload: bytes | str) -> Command:
    """Validate one command payload. Raises pydantic.ValidationError on anything unexpected."""
    return _COMMAND.validate_json(payload)


# --------------------------------------------------------------------------- telemetry
RobotMode = Literal["relaxed", "sitting", "standing", "walking", "estop", "fallen"]


class LidarSummary(BaseModel):
    ts: float
    sector_deg: float
    sectors_m: list[float]  # index 0 = straight ahead, counter-clockwise; value = nearest obstacle
    nearest_m: float
    nearest_bearing_deg: float
    points: int


class RobotState(BaseModel):
    v: int = PROTOCOL_VERSION
    robot_id: str
    ts: float = Field(default_factory=now)
    mode: RobotMode
    vx: float = 0.0  # effective velocity after safety limits
    vy: float = 0.0
    wz: float = 0.0
    move_remaining_s: float = 0.0
    roll_deg: float | None = None
    pitch_deg: float | None = None
    lidar: LidarSummary | None = None
    lidar_age_s: float | None = None
    last_seq: int = 0
    link_ok: bool = True
    estop: bool = False
    limiter: str | None = None  # why motion is limited right now (obstacle, lidar_stale, ...)
    loop_overruns: int = 0  # control ticks that started late since boot
    loop_max_ms: float = 0.0  # worst tick duration in the last state period


EventKind = Literal[
    "ack", "rejected", "obstacle_stop", "tilt", "fallen", "link_lost", "estop",
    "move_done", "online", "offline", "error", "snapshot_failed",
]


class RobotEvent(BaseModel):
    v: int = PROTOCOL_VERSION
    robot_id: str
    ts: float = Field(default_factory=now)
    kind: EventKind
    seq: int | None = None
    detail: str = ""
