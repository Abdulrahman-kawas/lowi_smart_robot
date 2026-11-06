"""The brain's view of the robot: telemetry cache + high-level actions over the link.

Every motion is sent as short Move commands (1 s) renewed every 0.5 s. If the brain, AWS or
the network dies, the body stops on its own within about a second (Move expiry + heartbeat
watchdog). Distances are estimated by integrating the velocity the body reports, so they are
approximate (legged odometry drifts).
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import logging
import math
import time
import uuid
from collections import deque
from dataclasses import dataclass

from spider_common.link import Link, topic_matches
from spider_common.protocol import (
    PROTOCOL_VERSION,
    BodyPose,
    EStop,
    EStopRelease,
    Heartbeat,
    LidarSummary,
    Move,
    Posture,
    RobotEvent,
    RobotState,
    Snapshot,
    Stop,
    Topics,
)

from .supervision.events import EventBus

log = logging.getLogger(__name__)

_DIRS = {"forward": (1.0, 0.0), "backward": (-1.0, 0.0), "left": (0.0, 1.0), "right": (0.0, -1.0)}
# events that stop ANY motion, whatever command caused them
_GLOBAL_STOPPERS = {"tilt", "fallen", "link_lost", "estop"}
# events that stop a motion only when they refer to one of its own Move commands
_OWN_STOPPERS = {"obstacle_stop", "error", "rejected"}
TELEMETRY_STALE_S = 1.5
COMPASS = [
    ("front", 0), ("front-left", 45), ("left", 90), ("back-left", 135),
    ("back", 180), ("back-right", -135), ("right", -90), ("front-right", -45),
]


class RobotOffline(RuntimeError):
    pass


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
    def __init__(self, link: Link, robot_id: str, bus: EventBus | None = None) -> None:
        self.link = link
        self.topics = Topics(robot_id)
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
    def subscriptions(robot_id: str) -> list[str]:
        t = Topics(robot_id)
        return [t.state, t.event, t.camera_filter]

    # ------------------------------------------------------------------ inbound
    async def run(self) -> None:
        async for msg in self.link.messages():
            try:
                if msg.topic == self.topics.state:
                    self._on_state(RobotState.model_validate_json(msg.payload))
                elif msg.topic == self.topics.event:
                    self._on_event(RobotEvent.model_validate_json(msg.payload))
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

    def _on_event(self, ev: RobotEvent) -> None:
        n = next(self._event_no)
        self._last_event_no = n
        self.events.append((n, ev))
        self._event_arrived.set()
        if ev.kind == "snapshot_failed":
            rid = ev.detail.split(":", 1)[0]
            fut = self._snapshots.pop(rid, None)
            if fut is not None and not fut.done():
                fut.set_exception(RuntimeError(ev.detail))
        if self.bus is not None:
            self.bus.publish("robot_event", event=ev.kind, seq=ev.seq, detail=ev.detail)

    async def heartbeat_loop(self, hz: float) -> None:
        while True:
            if self.link.connected.is_set():
                self.link.publish(self.topics.cmd, Heartbeat(ts=time.time()).model_dump_json())
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
    def _send(self, cmd, qos: int = 1) -> int:
        """Send one command. Returns its seq, or -1 if it could not be sent (link down)."""
        seq = next(self._seq)
        cmd = cmd.model_copy(update={"seq": seq, "ts": time.time(), "session": self.session})
        ok = self.link.publish(self.topics.cmd, cmd.model_dump_json(), qos=qos)
        return seq if ok else -1

    def stop(self) -> None:
        self._send(Stop())

    def cancel_motion(self) -> None:
        """Owner pressed Stop/Pause/E-STOP: end the running walk/turn now and stop the robot."""
        self._abort.set()
        self.stop()

    def move(self, vx: float, vy: float, wz: float, duration_s: float, gait: str = "tripod") -> int:
        """Raw velocity command (teleop). The body clamps it and stops after duration_s."""
        return self._send(Move(vx=vx, vy=vy, wz=wz, duration_s=duration_s, gait=gait), qos=0)

    def estop(self) -> None:
        self._send(EStop())

    def estop_release(self) -> None:
        self._send(EStopRelease())

    def _events_since(self, mark: int) -> list[RobotEvent]:
        return [ev for n, ev in self.events if n > mark]

    async def _wait_ack(self, seq: int, mark: int, timeout_s: float = 3.0) -> RobotEvent | None:
        end = time.monotonic() + timeout_s
        while (left := end - time.monotonic()) > 0:
            for ev in self._events_since(mark):
                if ev.seq == seq and ev.kind in ("ack", "rejected", "estop"):
                    return ev
            self._event_arrived.clear()
            with contextlib.suppress(TimeoutError):  # wake on the next event, not on a timer
                await asyncio.wait_for(self._event_arrived.wait(), left)
        return None

    async def posture(self, posture: str) -> str:
        self.require_state()
        mark = self._last_event_no
        seq = self._send(Posture(posture=posture))
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

    async def snapshot(self, timeout_s: float = 8.0) -> bytes:
        self.require_state()
        rid = uuid.uuid4().hex[:12]
        fut: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()
        self._snapshots[rid] = fut
        self._send(Snapshot(request_id=rid))
        try:
            return await asyncio.wait_for(fut, timeout_s)
        finally:
            self._snapshots.pop(rid, None)

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
