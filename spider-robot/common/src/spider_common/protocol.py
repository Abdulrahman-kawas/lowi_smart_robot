"""Wire protocol between every process of the spider robot. The single contract.

Every message is JSON over MQTT, except camera frames, which are raw JPEG bytes.

Safety contract: the body validates every command with these models and then clamps the
values again with its own (tighter) limits from robot.yaml. The brain is never trusted to
keep the robot safe; it can only ask.

Versioning: the gateway is the compatibility boundary. Sources (voice, remote, planner) may speak
any version from MIN_SOURCE_PROTOCOL to PROTOCOL_VERSION; the gateway always re-emits
PROTOCOL_VERSION to the body, and the body rejects anything else. Body and gateway are deployed
together on the Pi, so upgrade the Pi first and the server second. New optional fields are additive
within a version; removing or changing the meaning of a field bumps PROTOCOL_VERSION.
"""

from __future__ import annotations

import time
from typing import Annotated, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

PROTOCOL_VERSION = 3  # bump on any incompatible change; the body rejects other versions
MIN_SOURCE_PROTOCOL = 2  # the oldest version the gateway still accepts from a command source
SOURCES = ("voice", "bench", "remote", "planner", "button")  # motion first; button only releases
PATTERN_ID = r"^[A-Za-z0-9_-]+$"


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
        self._gateway = f"{base}/gw"  # command sources <-> the gateway on the Pi
        self.gateway_status = f"{self._gateway}/status"  # gateway -> all (retained + last will)
        self.voice_turn = f"{base}/voice/turn"  # voice -> brain (one record per utterance)
        self.record_cmd = f"{base}/rec/cmd"  # brain -> recorder on the Pi
        self.record_event = f"{base}/rec/event"  # recorder -> brain
        self._health = f"{base}/health"
        self._rpc = f"{base}/rpc"  # request/reply between the Pi and server workers

    def request(self, source: str) -> str:
        """Where a command source (voice, remote, planner) sends commands for the gateway."""
        return f"{self._gateway}/{source}/cmd"

    @property
    def request_filter(self) -> str:
        return f"{self._gateway}/+/cmd"

    def source_event(self, source: str) -> str:
        """Events the gateway returns to one source, with that source's own seq numbers."""
        return f"{self._gateway}/{source}/event"

    def health(self, service: str) -> str:
        """Retained health report of one service."""
        return f"{self._health}/{service}"

    @property
    def health_filter(self) -> str:
        return f"{self._health}/+"

    def rpc_request(self, service: str) -> str:
        """Where a client asks a worker (service: ask, stt)."""
        return f"{self._rpc}/{service}/req"

    def rpc_reply(self, service: str, client: str) -> str:
        return f"{self._rpc}/{service}/res/{client}"

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
    trace: str = Field("", max_length=32)  # correlation id, from utterance or task to motion


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
    challenge: str = Field("", max_length=32)  # gateway only: confirmed wake from limp
    frame_sha256: str = Field("", max_length=64)


class BodyPose(_Cmd):
    type: Literal["body_pose"] = "body_pose"
    height_m: float | None = Field(None, ge=0.03, le=0.20)
    roll_deg: float = Field(0.0, ge=-20.0, le=20.0)
    pitch_deg: float = Field(0.0, ge=-20.0, le=20.0)
    yaw_deg: float = Field(0.0, ge=-20.0, le=20.0)


class Snapshot(_Cmd):
    type: Literal["snapshot"] = "snapshot"
    request_id: str = Field(min_length=1, max_length=64, pattern=PATTERN_ID)


class Heartbeat(_Cmd):
    type: Literal["heartbeat"] = "heartbeat"


class EStop(_Cmd):
    type: Literal["estop"] = "estop"


class EStopRelease(_Cmd):
    """A remote release must quote a challenge the gateway issued for one fresh camera frame."""

    type: Literal["estop_release"] = "estop_release"
    challenge: str = Field("", max_length=32)  # gateway only: ties the release to one frame
    frame_sha256: str = Field("", max_length=64)


ConfirmAction = Literal["estop_release", "wake_from_limp"]


class ConfirmRequest(_Cmd):
    """Gateway only, never forwarded: take a fresh frame and issue a challenge bound to it."""

    type: Literal["confirm_request"] = "confirm_request"
    action: ConfirmAction
    request_id: str = Field(min_length=1, max_length=64, pattern=PATTERN_ID)


class Look(_Cmd):
    """Turn the front camera's pan servo to an absolute angle and hold it there.

    pan_deg: 0 = straight ahead, + = left (counter-clockwise seen from above, like wz). The body
    glides there at camera_pan.max_rate_dps * speed at most and clamps to its own limits. It moves
    no leg; Stop and E-stop freeze it where it is.
    """

    type: Literal["look"] = "look"
    pan_deg: float = Field(0.0, ge=-90.0, le=90.0)
    speed: float = Field(0.5, gt=0.0, le=1.0)


# Expressive moves run on the body from a fixed list: no source can upload a trajectory. The body
# validates every one before it starts (support, reach, servo limits, joint speed) and refuses it
# whole rather than clipping it. Stop and E-stop end any move within one control tick.
MoveName = Literal[
    "wave", "bow", "body_wave", "shimmy", "leg_ripple", "stomp", "dance",
    "attack_stance", "defense_stance", "alert", "crab_sway", "stretch", "sleep", "celebrate",
    "hi", "double_hi", "offer_hand", "table",
]
MOVE_NAMES: tuple[str, ...] = get_args(MoveName)
FrontLeg = Literal["LF", "RF"]
_Coord = Annotated[float, Field(ge=-0.5, le=0.5)]  # body frame, metres


class Perform(_Cmd):
    """Run one built-in move. speed scales time only: 1.0 is the fastest, 0.5 the default."""

    type: Literal["perform"] = "perform"
    name: MoveName
    speed: float = Field(0.5, gt=0.0, le=1.0)
    leg: FrontLeg | None = None  # the leading leg of wave, hi and offer_hand (default LF)


class Reach(_Cmd):
    """Move a front foot to 1 cm short of a target and hold. The robot cannot feel: no pushing."""

    type: Literal["reach"] = "reach"
    leg: FrontLeg | None = None  # None: the front leg on the target's side
    target: Literal["nearest"] | tuple[_Coord, _Coord, _Coord] = "nearest"
    speed: float = Field(0.5, gt=0.0, le=1.0)


class MovesSwitch(_Cmd):
    """Gateway only: who may start expressive moves now. None leaves that source as it is.
    Turning a source on never goes past its policy (allow_moves in SG_POLICY_FILE)."""

    type: Literal["moves_switch"] = "moves_switch"
    voice: bool | None = None
    remote: bool | None = None


class SpeedLimit(_Cmd):
    """Gateway only: the remote source's (the app's) top speed and turn rate from now on. It can
    never go above the remote policy's max_speed_mps and max_wz_rps (the ceiling in
    SG_POLICY_FILE), and the body still clamps with its own limits."""

    type: Literal["speed_limit"] = "speed_limit"
    max_speed_mps: float = Field(gt=0.0, le=0.5)
    max_wz_rps: float = Field(gt=0.0, le=2.0)


class Protection(_Cmd):
    """App only: skip LiDAR/IMU checks while enabled=false. The body expires the override.

    ttl_s is used only when turning protection off; the app renews about once a second.
    """

    type: Literal["protection"] = "protection"
    enabled: bool
    ttl_s: float = Field(2.0, ge=1.0, le=5.0)


Command = Annotated[
    Move | Stop | Posture | BodyPose | Snapshot | Heartbeat | EStop | EStopRelease | ConfirmRequest
    | Perform | Reach | Look | MovesSwitch | SpeedLimit | Protection,
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
    loop_late_max_ms: float = 0.0  # worst tick start lateness in the last state period
    loop_late_p99_ms: float = 0.0  # p99 of tick start lateness since boot
    loop_late_hist: list[int] = Field(default_factory=list)  # since boot: <1,<2,<5,<10,<20,>=20 ms
    rt_ok: bool = False  # SCHED_FIFO and locked memory are really active
    perform: str | None = None  # the move running now (mode stays "standing" while it runs)
    camera_pan_deg: float | None = None  # front camera pan (+ left); None: no pan servo, or limp
    # A pose the body holds until Stand: "table", or "stopped" (a move stopped halfway); else None
    held_pose: str | None = None
    # LiDAR/IMU protection: None from a body built before this field (treat as True).
    protection: bool | None = None


EventKind = Literal[
    "ack", "rejected", "obstacle_stop", "tilt", "fallen", "link_lost", "estop",
    "move_done", "online", "offline", "error", "snapshot_failed", "preempted", "challenge",
    "clamped", "perform_started", "perform_done", "perform_rejected", "protection",
]


class RobotEvent(BaseModel):
    v: int = PROTOCOL_VERSION
    robot_id: str
    ts: float = Field(default_factory=now)
    kind: str  # an EventKind; readers ignore kinds they do not know
    seq: int | None = None
    detail: str = ""
    trace: str = ""


class ConfirmChallenge(BaseModel):
    """JSON inside the detail of a RobotEvent with kind="challenge"."""

    id: str
    action: ConfirmAction
    request_id: str
    sha256: str
    ttl_s: float


# --------------------------------------------------------------------------- gateway and services
class SourceStatus(BaseModel):
    alive: bool = False
    age_s: float | None = None
    queue_delay_ms: float | None = None  # delivery delay above this source's best recent delay
    limited: bool = False


class GatewayStatus(BaseModel):
    """Published retained at 1 Hz. The last will sets online=False."""

    v: int = PROTOCOL_VERSION
    robot_id: str
    ts: float = Field(default_factory=now)
    online: bool = True
    session: str = ""
    owner: str | None = None
    owner_remaining_s: float = 0.0
    mode: str | None = None
    estop: bool | None = None
    sources: dict[str, SourceStatus] = Field(default_factory=dict)
    holdoff_s: dict[str, float] = Field(default_factory=dict)
    moves: dict[str, bool] = Field(default_factory=dict)
    # The app's speed limit now and its ceiling: max_speed_mps, max_wz_rps, ceiling_speed_mps,
    # ceiling_wz_rps. Empty from a gateway older than 2026-11-20.
    remote_limits: dict[str, float] = Field(default_factory=dict)
    pending_challenges: int = 0
    counters: dict[str, int] = Field(default_factory=dict)


HealthLevel = Literal["ok", "degraded", "down"]


class HealthReport(BaseModel):
    """Retained per service. The last will reports level='down'."""

    v: int = PROTOCOL_VERSION
    robot_id: str
    service: str
    ts: float = Field(default_factory=now)
    level: HealthLevel = "ok"
    detail: str = ""
    metrics: dict[str, float] = Field(default_factory=dict)
    info: dict[str, str] = Field(default_factory=dict)  # tailscale_path, failed_units


VoiceRoute = Literal["stop", "grammar", "llm", "escalate", "ignored", "failed"]


class VoiceTurn(BaseModel):
    """One utterance from end of speech to first sound. Stage times are milliseconds."""

    v: int = PROTOCOL_VERSION
    trace: str
    ts: float = Field(default_factory=now)
    route: VoiceRoute
    transcript: str = ""
    act: str = "none"
    say: str = ""
    reason: str = ""  # why it was ignored or failed
    stt_ms: float | None = None
    route_ms: float | None = None
    tts_first_ms: float | None = None
    total_ms: float | None = None
    audio_ms: float | None = None  # length of the utterance


MAX_ASK_CHARS = 2000
MAX_AUDIO_B64 = 400_000  # about 18 s of 16 kHz mono PCM


class AskRequest(BaseModel):
    """Voice -> worker. The answer can only be spoken: AskReply has no action field."""

    v: int = PROTOCOL_VERSION
    trace: str = Field(min_length=1, max_length=32, pattern=PATTERN_ID)
    ts: float = Field(default_factory=now)
    text: str = Field(max_length=MAX_ASK_CHARS)
    need_image: bool = False
    lang: str = Field("ar", max_length=8)
    deadline_s: float = Field(30.0, gt=0, le=120)


class AskReply(BaseModel):
    v: int = PROTOCOL_VERSION
    trace: str
    ts: float = Field(default_factory=now)
    ok: bool
    text: str = ""
    provider: str = ""
    elapsed_ms: float = 0.0
    error: str = ""


class SttRequest(BaseModel):
    v: int = PROTOCOL_VERSION
    trace: str = Field(min_length=1, max_length=32, pattern=PATTERN_ID)
    ts: float = Field(default_factory=now)
    rate: Literal[16000] = 16000
    audio_b64: str = Field(max_length=MAX_AUDIO_B64)  # 16-bit little-endian mono PCM
    lang: str = Field("ar", max_length=8)
    prompt: str = Field("", max_length=400)


class SttReply(BaseModel):
    v: int = PROTOCOL_VERSION
    trace: str
    ts: float = Field(default_factory=now)
    ok: bool
    text: str = ""
    confidence: float = 0.0
    provider: str = ""
    elapsed_ms: float = 0.0
    error: str = ""


class RecordRequest(BaseModel):
    """Brain to recorder: start or stop a LiDAR recording. It never commands motion."""

    model_config = ConfigDict(extra="forbid")
    v: int = PROTOCOL_VERSION
    ts: float = Field(default_factory=now)
    action: Literal["start", "stop"]
    job_id: str = Field(min_length=1, max_length=64, pattern=PATTERN_ID)
    duration_s: float = Field(60.0, gt=0.0, le=3600.0)


class RecordEvent(BaseModel):
    v: int = PROTOCOL_VERSION
    ts: float = Field(default_factory=now)
    job_id: str
    state: Literal["recording", "finished", "failed"]
    detail: str = ""
    path: str = ""
    size_bytes: int = 0
