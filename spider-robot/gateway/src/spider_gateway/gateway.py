"""The only process allowed to send commands to the robot body.

The body orders commands per session and accepts a heartbeat from anyone, which is right for one
brain and wrong for several. Voice on the Pi and the brain on the server therefore send to the
gateway, which:

  * renumbers everything into one session and stamps it with the Pi's clock, so a Stop fences
    every earlier Move and the body never compares two machines' clocks
  * lets a Stop or E-stop from any source through at once, ends the current owner's motion, tells
    that owner, and holds off equal and lower priority sources so their renewals cannot restart it
  * gives motion to the highest-priority active source, within that source's speed and time caps
    (policy.py)
  * tracks each source's heartbeat: if the source that owns the motion goes quiet the robot stops,
    while the other sources keep working
  * refuses anything but a Stop that sat in a network queue, measured without trusting the sender's
    clock, and does not count a late message as a sign of life
  * requires a fresh camera frame and a confirmation bound to it before a remote E-stop release or
    a remote wake from limp
  * accepts one more release path that needs no network: a physical hold-to-release button
  * returns each source its events with its own seq numbers
  * lets voice, remote and bench turn the camera (Look) with a rate cap; the planner may not
  * lets voice, bench and remote start expressive moves when the policy allows it, with remote
    moves requiring fresh standing telemetry and the app's speed below the policy cap; Reach stays
    local, and the planner never starts a move. A move owns the motion like a Move until the body
    reports it done
  * keeps the app's (remote) speed and turn-rate limit, which the owner sets from the app or by
    voice (SpeedLimit) up to the remote policy's ceiling, and remembers it across restarts

It adds to the body's limits and replaces none of them. If the gateway dies, its heartbeat stops
and the body's own watchdog stops the robot.
"""

from __future__ import annotations

import asyncio
import hashlib
import itertools
import json
import logging
import math
import time
import uuid
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from spider_common.link import Link, topic_matches
from spider_common.protocol import (
    MIN_SOURCE_PROTOCOL,
    PROTOCOL_VERSION,
    BodyPose,
    Command,
    ConfirmAction,
    ConfirmChallenge,
    ConfirmRequest,
    EStop,
    EStopRelease,
    EventKind,
    GatewayStatus,
    Heartbeat,
    Look,
    Move,
    MovesSwitch,
    Perform,
    Posture,
    Reach,
    RobotEvent,
    RobotState,
    Snapshot,
    SourceStatus,
    SpeedLimit,
    Stop,
    Topics,
    parse_command,
)

from .policy import BENCH_POLICY, DEFAULT_POLICIES, SourcePolicy

log = logging.getLogger(__name__)

PRIORITY = {"voice": 3, "remote": 1, "planner": 0}
BENCH_SOURCE, BENCH_RANK = "bench", 2  # below voice, so a spoken Stop holds the bench off too
POSE_HOLD_S = 2.0  # how long a posture change keeps lower-priority sources out
MAX_TRACKED = 1024  # commands remembered for translating event seq numbers
HEARTBEAT_PERIOD_S = 0.25
STATUS_PERIOD_S = 1.0
CLAMP_NOTICE_PERIOD_S = 2.0
BUTTON_SOURCE = "button"  # the physical release button on the Pi: may only release an E-stop
BUTTON_MAX_AGE_S = 1.0  # same machine, same clock: an older press is a stale message
_SOURCE_ONLY: frozenset[str] = frozenset({
    "ack", "rejected", "move_done", "snapshot_failed", "perform_started", "perform_done",
    "perform_rejected",
})
PERFORM_HOLD_S = 21.0  # the longest move (20 s), unless the body reports it done sooner
_PERFORM_END = frozenset({"perform_done", "perform_rejected"})
_LOCAL_SOURCES = frozenset({"voice", BENCH_SOURCE})
_NEEDS_CONFIRM_TO_WAKE = frozenset({"remote", "planner"})
DEFAULT_MOVES_ON = {"voice": True, "remote": False}
REMOTE_START_LIMITS = (0.05, 0.3)  # m/s, rad/s: the app's top speed until the owner changes it
_SPEED_LIMIT_SOURCES = frozenset({"voice", "remote"})


@dataclass(frozen=True)
class GatewayConfig:
    source_timeout_s: float = 1.5
    stop_holdoff_s: float = 2.0  # longer than one renewal (0.5 s), so the renewal is refused
    challenge_ttl_s: float = 30.0
    bench_enabled: bool = False  # SG_BENCH=1, only while a person is at the robot
    state_dir: Path = Path("/var/lib/spider-gateway")


class SourceClock:
    """How late a message is, without trusting the sender's clock.

    apparent delay = gateway wall clock - message timestamp = true delay + clock offset. The
    smallest apparent delay in the last minute is the best estimate of (network floor + offset), so
    "excess" = apparent delay - that minimum is the extra queueing delay. Any constant clock offset
    cancels out, so remote control needs neither NTP nor a battery-backed clock.

    A clock step looks like every message suddenly being late by the same amount. After
    REBASELINE_AFTER_S of late messages that all agree with each other, the window restarts. A real
    stall does not agree with itself, because a backlog drains with falling delay.
    """

    WINDOW_S = 60.0
    REBASELINE_AFTER_S = 3.0
    REBASELINE_SPREAD_S = 0.25

    def __init__(self) -> None:
        self._window: deque[tuple[float, float]] = deque()  # (arrival, delay), delays increasing
        self._late_since: float | None = None
        self._late_lo = math.inf
        self._late_hi = -math.inf
        self.excess = 0.0
        self.rebaselines = 0

    def _add(self, now: float, delay: float) -> None:
        while self._window and self._window[-1][1] >= delay:
            self._window.pop()
        self._window.append((now, delay))
        while now - self._window[0][0] > self.WINDOW_S:
            self._window.popleft()

    def observe(self, now: float, delay: float, limit: float) -> float:
        self._add(now, delay)
        self.excess = delay - self._window[0][1]
        if self.excess <= limit:
            self._late_since = None
            self._late_lo, self._late_hi = math.inf, -math.inf
            return self.excess
        if self._late_since is None:
            self._late_since = now
        self._late_lo = min(self._late_lo, delay)
        self._late_hi = max(self._late_hi, delay)
        settled = self._late_hi - self._late_lo <= self.REBASELINE_SPREAD_S
        if settled and now - self._late_since >= self.REBASELINE_AFTER_S:
            log.warning("source clock stepped by about %.2f s; re-baselining", self.excess)
            self._window.clear()
            self._add(now, delay)
            self._late_since = None
            self._late_lo, self._late_hi = math.inf, -math.inf
            self.rebaselines += 1
            self.excess = 0.0
        return self.excess


@dataclass
class _Challenge:
    id: str
    action: ConfirmAction
    source: str
    sha256: str
    expires: float


@dataclass
class _PendingFrame:
    source: str
    action: ConfirmAction
    seq: int
    asked: float


class Gateway:
    def __init__(
        self,
        link: Link,
        robot_id: str,
        source_timeout_s: float | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
        config: GatewayConfig | None = None,
        policies: dict[str, SourcePolicy] | None = None,
    ) -> None:
        self.link = link
        self.robot_id = robot_id
        self.topics = Topics(robot_id)
        self.config = config or GatewayConfig()
        self.policies = dict(policies or DEFAULT_POLICIES)
        self.priority = dict(PRIORITY)
        if self.config.bench_enabled:
            self.priority[BENCH_SOURCE] = BENCH_RANK
            self.policies.setdefault(BENCH_SOURCE, BENCH_POLICY)
        self.source_timeout_s = (
            source_timeout_s if source_timeout_s is not None else self.config.source_timeout_s
        )
        self.clock = clock
        self.wall = wall
        self.session = uuid.uuid4().hex[:12]
        self._seq = itertools.count(1)
        self._origin: OrderedDict[int, tuple[str, int]] = OrderedDict()
        self._seen: dict[str, float] = {}
        self._owner: str | None = None
        self._owner_until = 0.0
        self._performing = False  # the owner's motion is a Perform or Reach
        self._fence: dict[tuple[str, str], int] = {}  # (source, session) -> seq of its last Stop
        self._holdoff: dict[str, tuple[float, str]] = {}  # source -> (until, who stopped)
        self._clocks = {source: SourceClock() for source in self.priority}
        self._last_snapshot: dict[str, float] = {}
        self._last_look: dict[str, float] = {}
        self._last_clamp_notice: dict[str, float] = {}
        self._last_beat = -math.inf
        self._last_status = -math.inf
        self._trace = ""  # of the command being handled, for the replies it causes
        self._mode: str | None = None
        self._estop: bool | None = None
        self._state_rx = -math.inf
        self._pending: dict[str, _PendingFrame] = {}
        self._challenges: dict[str, _Challenge] = {}
        self.counters: dict[str, int] = {}
        self._moves_on = self._load_moves_state()
        self._remote_limits = self._load_remote_limits()

    @staticmethod
    def subscriptions(robot_id: str) -> list[str]:
        t = Topics(robot_id)
        return [t.request_filter, t.event, t.state, t.camera_filter]

    def _count(self, name: str) -> None:
        self.counters[name] = self.counters.get(name, 0) + 1

    # ------------------------------------------------------------------ runtime settings
    def _read_state(self, name: str) -> dict[str, Any] | None:
        """A setting the owner changed at run time, from SG_STATE_DIR; None: use the default."""
        path = self.config.state_dir / name
        try:
            saved = json.loads(path.read_text("utf-8"))
            if not isinstance(saved, dict):
                raise ValueError(f"{name} must hold an object")
        except FileNotFoundError:
            return None  # never changed yet
        except (OSError, ValueError, TypeError):
            log.warning("could not read %s; using the default", path)
            return None
        return saved

    def _write_state(self, name: str, data: dict[str, Any]) -> bool:
        """Written whole to a temporary file and renamed. False: kept in memory only."""
        path = self.config.state_dir / name
        try:
            self.config.state_dir.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}.tmp")
            tmp.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            log.warning("could not save %s; keeping it in memory until the gateway restarts", path)
            return False
        return True

    def _load_moves_state(self) -> dict[str, bool]:
        saved = self._read_state("moves.json") or {}
        state = dict(DEFAULT_MOVES_ON)
        for source in DEFAULT_MOVES_ON:
            value = saved.get(source)
            if isinstance(value, bool):
                state[source] = value
        return state

    def _load_remote_limits(self) -> tuple[float, float]:
        """The app's top speed and turn rate: as saved, else the first-start value, and never
        above the remote policy's ceiling (the owner may have lowered it since)."""
        speed, turn = REMOTE_START_LIMITS
        saved = self._read_state("remote_limits.json")
        if saved is not None:
            s, t = saved.get("max_speed_mps"), saved.get("max_wz_rps")
            if _positive(s) and _positive(t):
                speed, turn = float(s), float(t)
            else:
                log.warning("ignoring remote_limits.json without two positive numbers: %s", saved)
        ceiling = self.policies["remote"]
        return min(speed, ceiling.max_speed_mps), min(turn, ceiling.max_wz_rps)

    # ------------------------------------------------------------------ requests
    def on_request(self, source: str, payload: bytes | str) -> None:
        if source != BUTTON_SOURCE and source not in self.priority:
            log.warning("ignoring command from unknown source %r", source)
            return
        try:
            cmd = parse_command(payload)
        except ValidationError as exc:  # garbage proves nothing, so it does not count as alive
            self._reply(source, None, "rejected", f"invalid command ({exc.error_count()} errors)")
            return
        if not MIN_SOURCE_PROTOCOL <= cmd.v <= PROTOCOL_VERSION:
            self._count("bad_version")
            self._reply(source, cmd.seq, "rejected", f"protocol v{cmd.v} not supported")
            return
        self._trace = cmd.trace
        try:
            if source == BUTTON_SOURCE:
                self._on_button(cmd)
            else:
                self._dispatch(cmd, source)
        finally:
            self._trace = ""

    def _dispatch(self, cmd: Command, source: str) -> None:
        now = self.clock()
        policy = self.policies[source]
        limit = policy.max_excess_delay_s
        excess = self._clocks[source].observe(now, self.wall() - cmd.ts, limit)
        late = excess > limit
        if not late:  # a late message does not prove the source is alive now
            self._seen[source] = now
        if isinstance(cmd, (Stop, EStop)):  # stopping is always allowed, however late
            self._on_stop(cmd, source, now)
            return
        if isinstance(cmd, Heartbeat):
            if late:
                self._count("late_heartbeat")
            return
        if late:
            self._count("late_command")
            self._reply(source, cmd.seq, "rejected",
                        f"arrived {excess * 1000:.0f} ms late; network is congested")
            return
        if isinstance(cmd, ConfirmRequest):
            self._on_confirm_request(cmd, source, now)
        elif isinstance(cmd, EStopRelease):
            self._on_release(cmd, source, now)
        elif isinstance(cmd, Move):
            self._on_move(cmd, source, now)
        elif isinstance(cmd, (Perform, Reach)):
            self._on_perform(cmd, source, now)
        elif isinstance(cmd, Posture):
            self._on_posture(cmd, source, now)
        elif isinstance(cmd, BodyPose):
            if self._claim(source, cmd, now):
                self._forward(cmd, source)
            else:
                self._busy(source, cmd.seq)
        elif isinstance(cmd, Snapshot):
            if self._snapshot_allowed(source, cmd.seq, now):
                self._forward(cmd, source)
        elif isinstance(cmd, Look):
            self._on_look(cmd, source, now)
        elif isinstance(cmd, MovesSwitch):
            self._on_moves_switch(cmd, source)
        elif isinstance(cmd, SpeedLimit):
            self._on_speed_limit(cmd, source)
        else:
            self._forward(cmd, source)

    def _on_button(self, cmd: Command) -> None:
        """A person pressed and held the button on the robot. It can do nothing but release."""
        now = self.clock()
        if not isinstance(cmd, EStopRelease):
            self._reply(BUTTON_SOURCE, cmd.seq, "rejected", "the button may only release an E-stop")
            return
        if abs(self.wall() - cmd.ts) > BUTTON_MAX_AGE_S:
            self._reply(BUTTON_SOURCE, cmd.seq, "rejected", "stale button press")
            return
        if self._owner is not None and now < self._owner_until:
            self._reply(BUTTON_SOURCE, cmd.seq, "rejected", f"{self._owner} is in control")
            return
        self._count("button_release")
        self._forward(cmd, BUTTON_SOURCE)

    def _on_stop(self, cmd: Stop | EStop, source: str, now: float) -> None:
        key = (source, cmd.session)
        self._fence[key] = max(self._fence.get(key, -1), cmd.seq)
        displaced = self._owner
        self._owner = None
        self._performing = False
        rank = self.priority[source]
        for other, other_rank in self.priority.items():
            if other != source and other_rank <= rank:
                self._holdoff[other] = (now + self.config.stop_holdoff_s, source)
        self._forward(cmd, source)
        if displaced is not None and displaced != source:
            self._count("preempted")
            self._reply(displaced, None, "preempted", f"stopped by {source}")

    def _busy(self, source: str, seq: int) -> None:
        self._count("busy")
        self._reply(source, seq, "rejected", f"busy: {self._owner} is in control")

    def _on_move(self, cmd: Move, source: str, now: float) -> None:
        if cmd.seq <= self._fence.get((source, cmd.session), -1):
            return  # sent before this source's own Stop: drop silently, as the body does
        held = self._holdoff.get(source)
        if held is not None and now < held[0]:
            self._count("held_off")
            self._reply(source, cmd.seq, "rejected", f"held off after a stop from {held[1]}")
            return
        limited = self._cap(cmd, source, now)
        if not self._claim(source, limited, now):
            self._busy(source, cmd.seq)
            return
        self._forward(limited, source)

    def _on_look(self, cmd: Look, source: str, now: float) -> None:
        """Camera pan. It moves no leg, so it takes no motion ownership, but a Stop still
        holds it off and the planner may never send one."""
        if source == "planner" or not self.policies[source].allow_look:
            self._reply(source, cmd.seq, "rejected", f"{source} may not turn the camera")
            return
        if cmd.seq <= self._fence.get((source, cmd.session), -1):
            return  # sent before this source's own Stop
        held = self._holdoff.get(source)
        if held is not None and now < held[0]:
            self._count("held_off")
            self._reply(source, cmd.seq, "rejected", f"held off after a stop from {held[1]}")
            return
        if now - self._last_look.get(source, -math.inf) < self.policies[source].min_look_period_s:
            self._count("look_limited")
            self._reply(source, cmd.seq, "rejected", "look rate limit")
            return
        self._last_look[source] = now
        self._forward(cmd, source)

    def _on_perform(self, cmd: Perform | Reach, source: str, now: float) -> None:
        name = cmd.name if isinstance(cmd, Perform) else "reach"
        policy = self.policies[source]
        if source == "planner":
            self._reply(source, cmd.seq, "rejected", "the planner may never start moves")
            return
        if not policy.allow_moves:
            self._reply(source, cmd.seq, "rejected", f"{source} may not start moves "
                        "(allow_moves is off)")
            return
        if source in self._moves_on and not self._moves_on[source]:
            self._reply(source, cmd.seq, "rejected", f"moves from {source} are switched off")
            return
        if isinstance(cmd, Reach) and source not in _LOCAL_SOURCES:
            self._reply(source, cmd.seq, "rejected", "reach needs someone at the robot")
            return
        if source == "remote" and (
            self._mode != "standing" or self._estop or now - self._state_rx > 1.0
        ):
            self._reply(source, cmd.seq, "rejected", "moves from remote need the robot standing")
            return
        if source not in _LOCAL_SOURCES and name in policy.local_only_moves:
            self._reply(source, cmd.seq, "rejected", f"{name} is closed to {source} in the policy")
            return
        if cmd.seq <= self._fence.get((source, cmd.session), -1):
            return  # sent before this source's own Stop: drop silently, as for a Move
        held = self._holdoff.get(source)
        if held is not None and now < held[0]:
            self._count("held_off")
            self._reply(source, cmd.seq, "rejected", f"held off after a stop from {held[1]}")
            return
        if cmd.speed > policy.max_move_speed:
            self._count("capped")
            self._reply(source, cmd.seq, "clamped",
                        f"move speed limited to {policy.max_move_speed:g}")
            cmd = cmd.model_copy(update={"speed": policy.max_move_speed})
        if not self._claim(source, cmd, now):
            self._busy(source, cmd.seq)
            return
        self._performing = True
        self._forward(cmd, source)

    def _cap(self, cmd: Move, source: str, now: float) -> Move:
        policy = self.policies[source]
        max_speed, max_wz = (self._remote_limits if source == "remote"
                             else (policy.max_speed_mps, policy.max_wz_rps))
        speed = math.hypot(cmd.vx, cmd.vy)
        scale = min(1.0, max_speed / speed) if speed > 0.0 else 1.0
        wz = max(-max_wz, min(max_wz, cmd.wz))
        duration = min(cmd.duration_s, policy.max_duration_s)
        if scale == 1.0 and wz == cmd.wz and duration == cmd.duration_s:
            return cmd
        self._count("capped")
        if now - self._last_clamp_notice.get(source, -math.inf) >= CLAMP_NOTICE_PERIOD_S:
            self._last_clamp_notice[source] = now
            self._reply(source, cmd.seq, "clamped",
                        f"limited to {max_speed} m/s for {duration} s")
        return cmd.model_copy(update={"vx": cmd.vx * scale, "vy": cmd.vy * scale, "wz": wz,
                                      "duration_s": duration})

    def _snapshot_allowed(self, source: str, seq: int, now: float) -> bool:
        period = self.policies[source].min_snapshot_period_s
        if now - self._last_snapshot.get(source, -math.inf) < period:
            self._count("snapshot_limited")
            self._reply(source, seq, "rejected", "snapshot rate limit")
            return False
        self._last_snapshot[source] = now
        return True

    def _on_posture(self, cmd: Posture, source: str, now: float) -> None:
        waking = cmd.posture != "relax" and (self._mode is None or
                                             self._mode in ("relaxed", "fallen"))
        if waking and source in _NEEDS_CONFIRM_TO_WAKE:
            if source == "planner":
                self._reply(source, cmd.seq, "rejected", "the planner may not wake a limp robot")
                return
            if not self._consume(cmd.challenge, cmd.frame_sha256, "wake_from_limp", source, now):
                self._reply(source, cmd.seq, "rejected",
                            "wake from limp needs a confirmed fresh camera frame")
                return
        if not self._claim(source, cmd, now):
            self._busy(source, cmd.seq)
            return
        self._forward(cmd, source)

    def _claim(
        self, source: str, cmd: Move | Posture | BodyPose | Perform | Reach, now: float
    ) -> bool:
        owner_active = self._owner is not None and now < self._owner_until
        if owner_active and self.priority[source] < self.priority[self._owner]:
            return False
        if owner_active and self._owner != source and self._performing:
            # A move of a lower source is running: it ends first (the body holds that pose).
            self._forward(Stop(ts=self.wall()), None)
        if owner_active and self._owner != source and (
                isinstance(cmd, (Move, Perform, Reach)) or self._performing):
            self._count("preempted")
            self._reply(self._owner, None, "preempted", f"motion taken over by {source}")
        if self._owner != source or not owner_active:
            self._performing = False
        self._owner = source
        if isinstance(cmd, Move):
            hold = cmd.duration_s
        elif isinstance(cmd, (Perform, Reach)):
            hold = PERFORM_HOLD_S
        else:
            hold = POSE_HOLD_S
        self._owner_until = now + hold
        return True

    def _forward(self, cmd: Command, source: str | None) -> None:
        out = next(self._seq)
        if source is not None:
            self._origin[out] = (source, cmd.seq)
            while len(self._origin) > MAX_TRACKED:
                self._origin.popitem(last=False)
        # Re-stamped here: the body's age check now compares two readings of one clock on one
        # machine. Sender clocks and network delay were already judged in _dispatch.
        renumbered = cmd.model_copy(update={
            "seq": out, "session": self.session, "ts": self.wall(), "v": PROTOCOL_VERSION,
        })
        qos = 0 if isinstance(cmd, Move) else 1
        if not self.link.publish(self.topics.cmd, renumbered.model_dump_json(), qos=qos):
            log.warning("could not send %s to the body", cmd.type)
            if source is not None:
                self._reply(source, cmd.seq, "rejected", "gateway is not connected to the body")

    # ------------------------------------------------------------------ confirmed actions
    def _on_confirm_request(self, cmd: ConfirmRequest, source: str, now: float) -> None:
        if not self.policies[source].needs_frame_proof:
            self._reply(source, cmd.seq, "rejected", f"{source} may not request a confirmation")
            return
        if not self._snapshot_allowed(source, cmd.seq, now):
            return
        self._pending[cmd.request_id] = _PendingFrame(source, cmd.action, cmd.seq, now)
        self._forward(Snapshot(request_id=cmd.request_id), None)

    def on_camera(self, request_id: str, payload: bytes) -> None:
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return
        now = self.clock()
        digest = hashlib.sha256(payload).hexdigest()
        challenge = _Challenge(
            uuid.uuid4().hex[:16], pending.action, pending.source, digest,
            now + self.config.challenge_ttl_s,
        )
        self._challenges[challenge.id] = challenge
        body = ConfirmChallenge(id=challenge.id, action=challenge.action, request_id=request_id,
                                sha256=digest, ttl_s=self.config.challenge_ttl_s)
        self._reply(pending.source, pending.seq, "challenge", body.model_dump_json())

    def _consume(
        self, challenge_id: str, sha256: str, action: ConfirmAction, source: str, now: float
    ) -> bool:
        challenge = self._challenges.get(challenge_id)
        if challenge is None or challenge.action != action or challenge.source != source:
            return False
        if now >= challenge.expires or challenge.sha256 != sha256:
            return False
        del self._challenges[challenge_id]  # single use
        return True

    def _on_release(self, cmd: EStopRelease, source: str, now: float) -> None:
        if not self.policies[source].may_release_estop:
            self._reply(source, cmd.seq, "rejected", f"{source} may not release an E-stop")
            return
        if not self._consume(cmd.challenge, cmd.frame_sha256, "estop_release", source, now):
            self._reply(source, cmd.seq, "rejected",
                        "E-stop release needs a confirmed fresh camera frame")
            return
        self._forward(cmd, source)

    def _on_moves_switch(self, cmd: MovesSwitch, source: str) -> None:
        if source == "planner":
            self._reply(source, cmd.seq, "rejected", "the planner may not change the moves switch")
            return
        wanted = {target: value for target, value in (("voice", cmd.voice), ("remote", cmd.remote))
                  if value is not None}
        for target, value in wanted.items():  # all or nothing: check every source first
            policy = self.policies.get(target)
            if value and policy is not None and not policy.allow_moves:
                self._reply(source, cmd.seq, "rejected",
                            f"{target} may not start moves (allow_moves is off)")
                return
        changed = any(self._moves_on[target] != value for target, value in wanted.items())
        self._moves_on.update(wanted)
        if changed:
            self._write_state("moves.json", self._moves_on)
        detail = "moves: " + ", ".join(
            f"{target} {'on' if self._moves_on[target] else 'off'}" for target in DEFAULT_MOVES_ON
        )
        self._reply(source, cmd.seq, "ack", detail)
        self.publish_status(self.clock())

    def _on_speed_limit(self, cmd: SpeedLimit, source: str) -> None:
        """The app's top speed, set from the app or by voice; never above the remote ceiling."""
        if source not in _SPEED_LIMIT_SOURCES:
            self._reply(source, cmd.seq, "rejected",
                        f"{source} may not change the app's speed limit")
            return
        ceiling = self.policies["remote"]
        if cmd.max_speed_mps > ceiling.max_speed_mps or cmd.max_wz_rps > ceiling.max_wz_rps:
            self._reply(source, cmd.seq, "rejected",
                        f"above the ceiling of {ceiling.max_speed_mps:g} m/s and "
                        f"{ceiling.max_wz_rps:g} rad/s (remote in the gateway policy)")
            return
        self._remote_limits = (cmd.max_speed_mps, cmd.max_wz_rps)
        saved = self._write_state("remote_limits.json", {"max_speed_mps": cmd.max_speed_mps,
                                                         "max_wz_rps": cmd.max_wz_rps})
        detail = f"app speed limit {cmd.max_speed_mps:g} m/s, {cmd.max_wz_rps:g} rad/s"
        if not saved:
            detail += " (not saved: kept until the gateway restarts)"
        self._reply(source, cmd.seq, "ack", detail)
        self.publish_status(self.clock())

    # ------------------------------------------------------------------ events
    def on_state(self, payload: bytes | str) -> None:
        st = RobotState.model_validate_json(payload)
        self._mode, self._estop = st.mode, st.estop
        self._state_rx = self.clock()

    def on_event(self, payload: bytes | str) -> None:
        ev = RobotEvent.model_validate_json(payload)
        if ev.kind == "snapshot_failed":
            pending = self._pending.pop(ev.detail.split(":", 1)[0], None)
            if pending is not None:
                self._reply(pending.source, pending.seq, "rejected",
                            f"could not take the confirmation frame: {ev.detail}")
        origin = self._origin.get(ev.seq) if ev.seq is not None else None
        if ev.kind in _PERFORM_END and origin is not None and origin[0] == self._owner \
                and self._performing:
            self._owner, self._performing = None, False  # the move is over: motion is free
        if ev.kind in _SOURCE_ONLY:
            if origin is not None:
                self._republish(ev, origin[0], origin[1])
            return
        for source in self.priority:  # safety events reach everyone
            own = origin is not None and origin[0] == source
            self._republish(ev, source, origin[1] if own else None)

    def _republish(self, ev: RobotEvent, source: str, seq: int | None) -> None:
        translated = ev.model_copy(update={"seq": seq})
        self.link.publish(self.topics.source_event(source), translated.model_dump_json(), qos=1)

    def _reply(self, source: str, seq: int | None, kind: EventKind, detail: str) -> None:
        ev = RobotEvent(robot_id=self.robot_id, kind=kind, seq=seq, detail=detail,
                        trace=self._trace)
        self.link.publish(self.topics.source_event(source), ev.model_dump_json(), qos=1)

    # ------------------------------------------------------------------ watchdog
    def _alive(self, source: str, now: float) -> bool:
        seen = self._seen.get(source)
        return seen is not None and now - seen <= self.source_timeout_s

    def tick(self) -> None:
        now = self.clock()
        if self._owner is not None:
            if not self._alive(self._owner, now):
                self._halt_lost_owner()
            elif now >= self._owner_until:
                self._owner = None
        if now - self._last_beat >= HEARTBEAT_PERIOD_S and any(
            self._alive(source, now) for source in self.priority
        ):
            self._last_beat = now
            beat = Heartbeat(ts=self.wall(), session=self.session)
            self.link.publish(self.topics.cmd, beat.model_dump_json())
        self._expire(now)
        if now - self._last_status >= STATUS_PERIOD_S:
            self._last_status = now
            self.publish_status(now)

    def _expire(self, now: float) -> None:
        for key in [k for k, c in self._challenges.items() if now >= c.expires]:
            del self._challenges[key]
        for key in [k for k, p in self._pending.items()
                    if now - p.asked > self.config.challenge_ttl_s]:
            del self._pending[key]

    def _halt_lost_owner(self) -> None:
        lost, self._owner = self._owner, None
        self._performing = False
        log.warning("source %s went quiet while in control; stopping", lost)
        self._count("lost_owner")
        self._forward(Stop(ts=self.wall()), None)
        self._reply(lost, None, "link_lost", "no heartbeat from this source; robot stopped")

    def status(self, now: float) -> GatewayStatus:
        sources = {}
        for source in self.priority:
            seen = self._seen.get(source)
            excess = self._clocks[source].excess
            sources[source] = SourceStatus(
                alive=self._alive(source, now),
                age_s=None if seen is None else round(now - seen, 3),
                queue_delay_ms=round(excess * 1000, 1),
                limited=excess > self.policies[source].max_excess_delay_s,
            )
        holdoff = {s: round(until - now, 2) for s, (until, _) in self._holdoff.items()
                   if until > now}
        remaining = max(0.0, self._owner_until - now) if self._owner else 0.0
        return GatewayStatus(
            robot_id=self.robot_id, session=self.session, owner=self._owner,
            owner_remaining_s=round(remaining, 2), mode=self._mode, estop=self._estop,
            sources=sources, holdoff_s=holdoff, moves=dict(self._moves_on),
            remote_limits=self._remote_limits_view(),
            pending_challenges=len(self._challenges), counters=dict(self.counters),
        )

    def _remote_limits_view(self) -> dict[str, float]:
        ceiling = self.policies["remote"]
        speed, turn = self._remote_limits
        return {"max_speed_mps": speed, "max_wz_rps": turn,
                "ceiling_speed_mps": ceiling.max_speed_mps, "ceiling_wz_rps": ceiling.max_wz_rps}

    def publish_status(self, now: float) -> None:
        self.link.publish(self.topics.gateway_status, self.status(now).model_dump_json(), qos=1,
                          retain=True)

    # ------------------------------------------------------------------ run
    async def _pump(self) -> None:
        async for msg in self.link.messages():
            try:
                if msg.topic == self.topics.event:
                    self.on_event(msg.payload)
                elif msg.topic == self.topics.state:
                    self.on_state(msg.payload)
                elif topic_matches(self.topics.camera_filter, msg.topic):
                    self.on_camera(msg.topic.rsplit("/", 1)[-1], msg.payload)
                elif topic_matches(self.topics.request_filter, msg.topic):
                    self.on_request(msg.topic.split("/")[-2], msg.payload)
            except Exception:
                log.exception("bad message on %s", msg.topic)

    async def _ticker(self, period_s: float) -> None:
        while True:
            self.tick()
            await asyncio.sleep(period_s)

    async def run(self, tick_hz: float = 10.0) -> None:
        await asyncio.gather(self._pump(), self._ticker(1.0 / tick_hz))


def _positive(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(value) and value > 0.0
