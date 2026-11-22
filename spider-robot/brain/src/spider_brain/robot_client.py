"""The brain's view of the robot: telemetry cache + high-level actions over the link.

Every motion is sent as short Move commands (1 s) renewed every 0.5 s. If the brain, AWS or
the network dies, the body stops on its own within about a second (Move expiry + heartbeat
watchdog). Distances are estimated by integrating the velocity the body reports, so they are
approximate (legged odometry drifts).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import itertools
import json
import logging
import math
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from spider_common.link import Link, topic_matches
from spider_common.protocol import (
    PROTOCOL_VERSION,
    BodyPose,
    ConfirmChallenge,
    ConfirmRequest,
    EStop,
    EStopRelease,
    Heartbeat,
    LidarSummary,
    Look,
    Move,
    MovesSwitch,
    Perform,
    Posture,
    RobotEvent,
    RobotState,
    Snapshot,
    SpeedLimit,
    Stop,
    Topics,
)

from .supervision.events import EventBus

log = logging.getLogger(__name__)

_DIRS = {"forward": (1.0, 0.0), "backward": (-1.0, 0.0), "left": (0.0, 1.0), "right": (0.0, -1.0)}
# events that stop ANY motion, whatever command caused them
_GLOBAL_STOPPERS = {"tilt", "fallen", "link_lost", "estop", "preempted"}
# events that stop a motion only when they refer to one of its own Move commands
_OWN_STOPPERS = {"obstacle_stop", "error", "rejected"}
TELEMETRY_STALE_S = 1.5
# The gateway lets the remote source ask for one camera frame per 0.5 s, counting snapshots and
# confirmation frames together. Asking at 0.6 s leaves room for network jitter.
CAMERA_GAP_S = 0.6  # above the gateway's min_snapshot_period_s (0.5 s) per source
COMPASS = [
    ("front", 0), ("front-left", 45), ("left", 90), ("back-left", 135),
    ("back", 180), ("back-right", -135), ("right", -90), ("front-right", -45),
]


class RobotOffline(RuntimeError):
    pass


class ConfirmRefused(RuntimeError):
    """The gateway would not issue a challenge, or the frame did not match it."""


class SnapshotRefused(RuntimeError):
    """The gateway refused a Snapshot, for example for its rate limit."""


class _CameraGate:
    """One gateway source's snapshot allowance: callers queue here instead of being refused."""

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.waiting = 0
        self.last = -math.inf


@dataclass(frozen=True)
class Confirmation:
    """A fresh frame and the single-use challenge the gateway bound to it."""

    id: str
    action: str
    sha256: str
    ttl_s: float
    jpeg: bytes
    asked_at: float = 0.0  # monotonic time of the request: the frame cannot be older than this


@dataclass
class MotionResult:
    done: float  # metres or degrees actually done (estimated)
    requested: float
    stopped_by: str | None  # event kind + detail, or None if completed

    @property
    def completed(self) -> bool:
        return self.stopped_by is None


def cone_min(lidar: LidarSummary, bearing: float, half: float = 22.5) -> float:
    best = math.inf
    for i, d in enumerate(lidar.sectors_m):
        diff = (i * lidar.sector_deg - bearing + 180.0) % 360.0 - 180.0
        if abs(diff) <= half:
            best = min(best, d)
    return best


class RobotClient:
    def __init__(
        self, link: Link, robot_id: str, bus: EventBus | None = None, source: str | None = None,
        human_source: str | None = None,
    ) -> None:
        self.link = link
        self.topics = Topics(robot_id)
        self.via_gateway = source is not None
        self._cmd_topic = self.topics.request(source) if source else self.topics.cmd
        self._human_topic = self.topics.request(human_source) if human_source else self._cmd_topic
        self._event_topics = (
            {self.topics.source_event(s) for s in (source, human_source) if s}
            or {self.topics.event}
        )
        self.human_source = human_source or source  # None: straight to the body, no gateway
        # The gateway allows each source one Snapshot per min_snapshot_period_s and refuses the
        # rest. Every frame a source asks for, from any caller (live view, watch mode, a voice
        # question, a photo), takes its turn here instead.
        self._camera_gates = {
            topic: _CameraGate() for topic in {self._cmd_topic, self._human_topic}
            if topic != self.topics.cmd
        }
        self._snapshot_seqs: dict[int, str] = {}  # Snapshot seq -> request id
        self.handlers: list[tuple[str, Callable[[str, bytes], None]]] = []  # topic filter, handler
        self.bus = bus
        self.state: RobotState | None = None
        self.state_rx: float | None = None
        self.events: deque[tuple[int, RobotEvent]] = deque(maxlen=500)
        self._event_no = itertools.count(1)
        self._last_event_no = 0
        self._seq = itertools.count(1)
        self._snapshots: dict[str, asyncio.Future[bytes]] = {}
        self._online = asyncio.Event()
        self._last_bus_state = 0.0
        self.session = uuid.uuid4().hex[:12]  # the body orders commands per session
        self._abort = asyncio.Event()  # set by the owner's Stop/Pause: ends the active motion
        self.version_error: str | None = None
        self._event_arrived = asyncio.Event()

    @staticmethod
    def subscriptions(
        robot_id: str, source: str | None = None, human_source: str | None = None
    ) -> list[str]:
        t = Topics(robot_id)
        events = sorted({t.source_event(s) for s in (source, human_source) if s}) or [t.event]
        return [t.state, *events, t.camera_filter]

    # ------------------------------------------------------------------ inbound
    async def run(self) -> None:
        async for msg in self.link.messages():
            try:
                handler = next(
                    (fn for flt, fn in self.handlers if topic_matches(flt, msg.topic)), None
                )
                if handler is not None:
                    handler(msg.topic, msg.payload)
                elif msg.topic == self.topics.state:
                    self._on_state(RobotState.model_validate_json(msg.payload))
                elif msg.topic in self._event_topics:
                    source = msg.topic.split("/")[-2] if self.via_gateway else None
                    self._on_event(RobotEvent.model_validate_json(msg.payload), source)
                elif topic_matches(self.topics.camera_filter, msg.topic):
                    rid = msg.topic.rsplit("/", 1)[-1]
                    fut = self._snapshots.pop(rid, None)
                    if fut is not None and not fut.done():
                        fut.set_result(msg.payload)
            except Exception:
                log.exception("bad message on %s", msg.topic)

    def _on_state(self, st: RobotState) -> None:
        if st.v != PROTOCOL_VERSION:
            self.version_error = f"robot speaks protocol v{st.v}, brain v{PROTOCOL_VERSION}"
            log.error(self.version_error)
            return  # never act on telemetry we may misread
        self.state = st
        self.state_rx = time.monotonic()
        self._online.set()
        if self.bus is not None and time.monotonic() - self._last_bus_state > 0.4:
            self._last_bus_state = time.monotonic()
            self.bus.publish("robot_state", state=json.loads(st.model_dump_json()))

    def _on_event(self, ev: RobotEvent, source: str | None = None) -> None:
        n = next(self._event_no)
        self._last_event_no = n
        self.events.append((n, ev))
        self._event_arrived.set()
        if ev.kind == "snapshot_failed":
            rid = ev.detail.split(":", 1)[0]
            fut = self._snapshots.pop(rid, None)
            if fut is not None and not fut.done():
                fut.set_exception(RuntimeError(ev.detail))
        elif ev.kind == "rejected" and ev.seq in self._snapshot_seqs:
            fut = self._snapshots.pop(self._snapshot_seqs.pop(ev.seq), None)
            if fut is not None and not fut.done():
                fut.set_exception(SnapshotRefused(ev.detail or "snapshot refused"))
        if self.bus is not None:
            self.bus.publish("robot_event", event=ev.kind, seq=ev.seq, detail=ev.detail,
                             source=source)

    async def heartbeat_loop(self, hz: float) -> None:
        while True:
            if self.link.connected.is_set():
                for topic in {self._cmd_topic, self._human_topic}:
                    self.link.publish(topic, Heartbeat(ts=time.time()).model_dump_json())
            await asyncio.sleep(1.0 / hz)

    async def wait_online(self, timeout_s: float) -> bool:
        try:
            await asyncio.wait_for(self._online.wait(), timeout_s)
            return True
        except TimeoutError:
            return False

    def require_state(self, max_age_s: float = 3.0) -> RobotState:
        if self.version_error:
            raise RobotOffline(self.version_error)
        if self.state is None or self.state_rx is None:
            raise RobotOffline("no telemetry from the robot yet")
        if time.monotonic() - self.state_rx > max_age_s:
            raise RobotOffline(f"robot telemetry is {time.monotonic() - self.state_rx:.0f} s old")
        return self.state

    # ------------------------------------------------------------------ outbound
    def _send(self, cmd, qos: int = 1, human: bool = False) -> int:
        """Send one command. Returns its seq, or -1 if it could not be sent (link down)."""
        seq = next(self._seq)
        cmd = cmd.model_copy(update={"seq": seq, "ts": time.time(), "session": self.session})
        topic = self._human_topic if human else self._cmd_topic
        ok = self.link.publish(topic, cmd.model_dump_json(), qos=qos)
        return seq if ok else -1

    def stop(self, human: bool = False) -> int:
        return self._send(Stop(), human=human)

    def cancel_motion(self) -> int:
        """Owner pressed Stop/Pause/E-STOP: end the running walk/turn now and stop the robot."""
        self._abort.set()
        return self._send(Stop(), human=True)

    def move(
        self, vx: float, vy: float, wz: float, duration_s: float, gait: str = "tripod",
        human: bool = False,
    ) -> int:
        """Raw velocity command (teleop). The body clamps it and stops after duration_s."""
        return self._send(Move(vx=vx, vy=vy, wz=wz, duration_s=duration_s, gait=gait), qos=0,
                          human=human)

    def look(self, pan_deg: float, speed: float = 0.5, human: bool = False) -> int:
        """Camera pan (deg, + left). Fire and forget: the ack or refusal comes as an event."""
        return self._send(Look(pan_deg=pan_deg, speed=speed), human=human)

    def perform(self, name: str, speed: float = 0.5, leg: str | None = None,
                human: bool = False) -> int:
        """One built-in expressive move. The body's own checks still apply."""
        return self._send(Perform(name=name, speed=speed, leg=leg), human=human)

    def moves_switch(self, voice: bool | None, remote: bool | None) -> int:
        return self._send(MovesSwitch(voice=voice, remote=remote), human=True)

    def speed_limit(self, max_speed_mps: float, max_wz_rps: float) -> int:
        """The app's top speed and turn rate. The gateway keeps it, up to its remote ceiling."""
        return self._send(SpeedLimit(max_speed_mps=max_speed_mps, max_wz_rps=max_wz_rps),
                          human=True)

    def estop(self) -> int:
        return self._send(EStop(), human=True)

    def estop_release(self, confirmation: Confirmation | None = None) -> int:
        """Through the gateway a release needs a Confirmation, or it is refused."""
        if confirmation is None:
            return self._send(EStopRelease(), human=True)
        return self._send(EStopRelease(challenge=confirmation.id,
                                       frame_sha256=confirmation.sha256), human=True)

    def posture_confirmed(self, posture: str, confirmation: Confirmation) -> int:
        return self._send(Posture(posture=posture, challenge=confirmation.id,
                                  frame_sha256=confirmation.sha256), human=True)

    # ------------------------------------------------------------------ camera allowance
    async def _camera_turn(self, topic: str) -> None:
        """Wait until this source may ask for another frame. No-op straight to the body."""
        gate = self._camera_gates.get(topic)
        if gate is None:
            return
        gate.waiting += 1
        try:
            async with gate.lock:
                wait = gate.last + CAMERA_GAP_S - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                gate.last = time.monotonic()
        finally:
            gate.waiting -= 1

    def camera_free(self, human: bool = True) -> bool:
        """A frame may be asked for now on this source without delaying anyone already waiting
        (a photo or a confirmation on the owner's source, a voice question on the brain's)."""
        gate = self._camera_gates.get(self._human_topic if human else self._cmd_topic)
        if gate is None:
            return True
        return (gate.waiting == 0 and not gate.lock.locked()
                and time.monotonic() - gate.last >= CAMERA_GAP_S)

    async def request_confirm(self, action: str, timeout_s: float = 10.0) -> Confirmation:
        """Ask the gateway for a fresh frame and a challenge bound to it."""
        self.require_state()
        rid = uuid.uuid4().hex[:12]
        frame: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()
        await self._camera_turn(self._human_topic)
        self._snapshots[rid] = frame
        mark = self._last_event_no
        asked_at = time.monotonic()
        seq = self._send(ConfirmRequest(action=action, request_id=rid), human=True)
        try:
            ev = await self._wait_ack(seq, mark, timeout_s)
            if ev is None:
                raise ConfirmRefused("no answer from the gateway")
            if ev.kind != "challenge":
                raise ConfirmRefused(ev.detail or ev.kind)
            challenge = ConfirmChallenge.model_validate_json(ev.detail)
            jpeg = await asyncio.wait_for(frame, timeout_s)
        except TimeoutError as exc:
            raise ConfirmRefused("the camera frame did not arrive") from exc
        finally:
            self._snapshots.pop(rid, None)
        if hashlib.sha256(jpeg).hexdigest() != challenge.sha256:
            raise ConfirmRefused("the received frame does not match the challenge")
        return Confirmation(challenge.id, challenge.action, challenge.sha256, challenge.ttl_s, jpeg,
                            asked_at)

    def _events_since(self, mark: int) -> list[RobotEvent]:
        return [ev for n, ev in self.events if n > mark]

    def event_mark(self) -> int:
        """Pass to wait_ack to look only at events that arrive after this point."""
        return self._last_event_no

    async def wait_ack(self, seq: int, mark: int, timeout_s: float = 3.0) -> RobotEvent | None:
        """The ack, rejection or E-stop event for one command, or None after timeout_s."""
        return await self._wait_ack(seq, mark, timeout_s)

    async def _wait_ack(self, seq: int, mark: int, timeout_s: float = 3.0) -> RobotEvent | None:
        end = time.monotonic() + timeout_s
        while (left := end - time.monotonic()) > 0:
            for ev in self._events_since(mark):
                if ev.seq == seq and ev.kind in ("ack", "rejected", "estop", "challenge"):
                    return ev
            self._event_arrived.clear()
            with contextlib.suppress(TimeoutError):  # wake on the next event, not on a timer
                await asyncio.wait_for(self._event_arrived.wait(), left)
        return None

    async def posture(self, posture: str, human: bool = False) -> str:
        self.require_state()
        mark = self._last_event_no
        seq = self._send(Posture(posture=posture), human=human)
        ev = await self._wait_ack(seq, mark)
        if ev is None:
            return "No answer from the robot (is it online?)."
        if ev.kind == "rejected":
            return f"Rejected by the robot: {ev.detail}"
        # wait for the height change to finish
        target = {"stand": "standing", "sit": "sitting", "relax": "relaxed"}[posture]
        end = time.monotonic() + 8.0
        await asyncio.sleep(0.3)
        while time.monotonic() < end:
            st = self.state
            if st is not None and st.mode == target and time.monotonic() - (self.state_rx or 0) < 1:
                break
            await asyncio.sleep(0.2)
        await asyncio.sleep(1.5 if posture != "relax" else 0.0)  # body is still moving its legs
        return f"Robot is now {self.state.mode if self.state else 'unknown'}."

    async def body_pose(self, height_m: float | None, pitch_deg: float, roll_deg: float) -> str:
        self.require_state()
        mark = self._last_event_no
        seq = self._send(BodyPose(height_m=height_m, pitch_deg=pitch_deg, roll_deg=roll_deg))
        ev = await self._wait_ack(seq, mark)
        if ev is None:
            return "No answer from the robot."
        if ev.kind == "rejected":
            return f"Rejected by the robot: {ev.detail}"
        await asyncio.sleep(1.0)
        return "Body pose adjusted."

    async def _motion(
        self, vx: float, vy: float, wz: float, amount: float, rate_of, gait: str
    ) -> MotionResult:
        """Renew 1 s Moves every 0.5 s until `amount` is done (rate_of(state) per second)."""
        st = self.require_state()
        if st.mode not in ("standing", "walking"):
            return MotionResult(0.0, amount, f"robot is {st.mode}; stand up first")
        if st.estop:
            return MotionResult(0.0, amount, "estop is latched")
        expected_rate = rate_of(Move(vx=vx, vy=vy, wz=wz))  # same fields as RobotState
        max_time = amount / max(expected_rate, 1e-6) * 2.5 + 4.0
        mark = self._last_event_no
        done, stopped_by = 0.0, None
        my_seqs: set[int] = set()
        self._abort.clear()
        start = time.monotonic()
        last_state_ts = st.ts
        try:
            while done < amount and stopped_by is None:
                now = time.monotonic()
                if now - start > max_time:
                    stopped_by = "timeout (robot is moving slower than expected)"
                    break
                seq = self._send(Move(vx=vx, vy=vy, wz=wz, duration_s=1.0, gait=gait), 0)
                if seq < 0:
                    stopped_by = "link down: could not send the move"
                    break
                my_seqs.add(seq)
                renew_at = now + 0.5
                while time.monotonic() < renew_at and done < amount:
                    await asyncio.sleep(0.05)
                    t = time.monotonic()
                    if self._abort.is_set():
                        stopped_by = "cancelled by the owner"
                        break
                    if self.state_rx is None or t - self.state_rx > TELEMETRY_STALE_S:
                        # never count distance we cannot see (network partition)
                        stopped_by = "telemetry lost: robot position unknown"
                        break
                    st_now = self.state
                    if st_now is not None and st_now.ts > last_state_ts:
                        # integrate only over fresh telemetry, from the robot's own clock
                        done += rate_of(st_now) * (st_now.ts - last_state_ts)
                        last_state_ts = st_now.ts
                    for ev in self._events_since(mark):
                        if ev.kind in _GLOBAL_STOPPERS or (
                            ev.kind in _OWN_STOPPERS and ev.seq in my_seqs
                        ):
                            stopped_by = f"{ev.kind}: {ev.detail}".strip(": ")
                    if stopped_by:
                        break
        finally:
            self.stop()
        await self._wait_still(3.0)
        return MotionResult(min(done, amount), amount, stopped_by)

    async def _wait_still(self, timeout_s: float) -> None:
        end = time.monotonic() + timeout_s
        await asyncio.sleep(0.3)
        while time.monotonic() < end:
            st = self.state
            if st is not None and st.mode != "walking":
                return
            await asyncio.sleep(0.1)

    async def walk(
        self, direction: str, distance_m: float, speed: float, gait: str
    ) -> MotionResult:
        ux, uy = _DIRS[direction]
        return await self._motion(
            ux * speed, uy * speed, 0.0, distance_m, lambda s: math.hypot(s.vx, s.vy), gait
        )

    async def turn(self, angle_deg: float, speed_dps: float, gait: str) -> MotionResult:
        wz = math.copysign(math.radians(speed_dps), angle_deg)
        res = await self._motion(
            0.0, 0.0, wz, math.radians(abs(angle_deg)), lambda s: abs(s.wz), gait
        )
        return MotionResult(math.degrees(res.done), abs(angle_deg), res.stopped_by)

    async def ping(self, n: int = 50, interval_s: float = 0.2) -> list[float]:
        """Round-trip times (ms) of Stop -> ack. Safe: Stop is harmless when standing still."""
        rtts: list[float] = []
        for _ in range(n):
            mark = self._last_event_no
            t0 = time.monotonic()
            seq = self._send(Stop())
            ev = await self._wait_ack(seq, mark, timeout_s=2.0)
            if ev is not None:
                rtts.append((time.monotonic() - t0) * 1000)
            await asyncio.sleep(interval_s)
        return rtts

    async def snapshot(self, timeout_s: float = 8.0, human: bool = False) -> bytes:
        jpeg, _ = await self.snapshot_timed(timeout_s, human)
        return jpeg

    async def snapshot_timed(
        self, timeout_s: float = 8.0, human: bool = False
    ) -> tuple[bytes, float]:
        """A frame and the monotonic time it was asked for, an upper bound on its age.

        A refusal from the gateway ends the wait at once and is retried one turn later, so a
        caller that lost a race for the camera does not sit out its whole timeout."""
        self.require_state()
        topic = self._human_topic if human else self._cmd_topic
        deadline = time.monotonic() + timeout_s
        for attempt in (1, 2):
            await self._camera_turn(topic)
            rid = uuid.uuid4().hex[:12]
            fut: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()
            self._snapshots[rid] = fut
            asked_at = time.monotonic()
            seq = self._send(Snapshot(request_id=rid), human=human)
            self._snapshot_seqs[seq] = rid
            try:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise TimeoutError("no time left for a camera frame")
                return await asyncio.wait_for(fut, left), asked_at
            except SnapshotRefused as exc:
                if attempt == 2:
                    raise
                log.info("snapshot refused (%s); asking once more", exc)
            finally:
                self._snapshots.pop(rid, None)
                self._snapshot_seqs.pop(seq, None)
        raise AssertionError("unreachable")

    # ------------------------------------------------------------------ text views
    def surroundings_text(self) -> str:
        st = self.require_state()
        if st.lidar is None:
            return "No LiDAR data."
        lines = [
            f"{name:12s} {cone_min(st.lidar, bearing):5.2f} m" for name, bearing in COMPASS
        ]
        age = f"{st.lidar_age_s:.1f}s" if st.lidar_age_s is not None else "?"
        return (
            "Nearest obstacle per direction (LiDAR, 8 m = nothing seen):\n"
            + "\n".join(lines)
            + f"\nNearest overall: {st.lidar.nearest_m:.2f} m at {st.lidar.nearest_bearing_deg:.0f}"
            f" deg (0 = front, + = left). LiDAR age {age}."
        )

    def status_text(self) -> str:
        st = self.require_state()
        tilt = (
            f"roll {st.roll_deg:.0f} deg, pitch {st.pitch_deg:.0f} deg"
            if st.roll_deg is not None and st.pitch_deg is not None else "tilt unknown"
        )
        recent = [f"{ev.kind}({ev.detail})" for _, ev in list(self.events)[-5:]]
        parts = [
            f"Mode: {st.mode}. E-stop: {'LATCHED' if st.estop else 'off'}. {tilt}.",
            f"Velocity: vx={st.vx:.2f} m/s vy={st.vy:.2f} m/s wz={st.wz:.2f} rad/s.",
            f"Motion limiter: {st.limiter or 'none'}. Link ok: {st.link_ok}.",
            f"Control loop: {st.loop_overruns} overruns since boot, worst tick "
            f"{st.loop_max_ms:.1f} ms (budget 20 ms).",
            "Recent robot events: " + (", ".join(recent) if recent else "none"),
        ]
        if st.lidar is not None:
            parts.append(self.surroundings_text())
        return "\n".join(parts)
