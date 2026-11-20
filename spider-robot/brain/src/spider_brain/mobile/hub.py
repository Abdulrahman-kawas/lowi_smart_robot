"""The brain side of the app: sessions, live state, dead-man driving, confirmations and photos.

Stop and E-stop are handled synchronously, before anything that waits, and stop the robot before
any bookkeeping. Every other command goes out as the remote source.
"""

from __future__ import annotations

import asyncio
import base64
import itertools
import json
import logging
import math
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from spider_common.protocol import MOVE_NAMES

from ..robot_client import TELEMETRY_STALE_S, RobotOffline
from .camera import Frame, FrameFeed
from .devices import DeviceStore, PairingCodes
from .drive import Caps, DriveControl
from .talk import TalkService

if TYPE_CHECKING:
    from fastapi import WebSocket

    from ..service import BrainService

log = logging.getLogger(__name__)

API_VERSION = 1
TICK_S = 0.05
LOOK_GAP_S = 0.2  # the app sends targets while dragging; the gateway also caps Looks at 5/s
STATE_KEEPALIVE_S = 1.0  # send state at least this often, so the app sees "offline" too
REVOKE_CHECK_S = 1.0
QUEUE_MAX = 64  # outgoing messages per socket; a link this far behind is closed
CLOSE_REVOKED = 4401
CLOSE_TOO_SLOW = 1013
GATEWAY_STALE_S = 3.0  # it publishes status at 1 Hz
ALERTS = frozenset({"obstacle_stop", "tilt", "fallen", "link_lost", "estop", "offline", "health"})
REFUSALS = frozenset({"rejected", "preempted", "perform_rejected"})
QUIET = frozenset({"ack", "move_done", "challenge"})
DRIVE_MODES = frozenset({"standing", "walking"})
POSTURES = frozenset({"stand", "sit", "relax"})


class Busy(RuntimeError):
    pass


def pack_frame(frame: Frame, age_ms: float) -> bytes:
    """[u32 big-endian header length][header JSON][JPEG], one binary WebSocket message."""
    header = json.dumps({"type": "frame", "n": frame.n, "age_ms": round(age_ms, 1)}).encode()
    return struct.pack(">I", len(header)) + header + frame.jpeg


@dataclass(eq=False)
class Session:
    id: int
    device: str
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=QUEUE_MAX))
    video: bool = False
    frame_queued: bool = False
    last_frame_at: float | None = None  # asked_at of the newest frame sent here
    close_code: int | None = None
    closing: asyncio.Event = field(default_factory=asyncio.Event)

    def put(self, item: dict | Frame) -> None:
        try:
            self.queue.put_nowait(item)
        except asyncio.QueueFull:
            self.close(CLOSE_TOO_SLOW)

    def close(self, code: int) -> None:
        if self.close_code is None:
            self.close_code = code
        self.closing.set()


class MobileHub:
    def __init__(self, svc: BrainService, data_dir: Path) -> None:
        s = svc.settings
        self.robot, self.bus, self.confirm = svc.robot, svc.bus, svc.confirm
        self.supervisor, self.vision = svc.supervisor, svc.vision
        self.robot_id = s.robot_id
        self.max_frame_age_s = s.mobile_max_frame_age_s
        self.source = self.robot.human_source  # "remote": the settings refuse anything else
        self.devices = DeviceStore(data_dir)
        self.codes = PairingCodes(data_dir, s.mobile_pair_code_s)
        self.caps = Caps(s.mobile_max_speed_mps, s.mobile_max_wz_rps, s.mobile_move_s)
        self.drive = DriveControl(self.robot, self.caps, s.mobile_deadman_s, self._preflight,
                                  self._notify, gait=s.gait)
        self.feed = FrameFeed(self.robot, self._on_frame,
                              lambda kind, detail: self._notify(None, kind, detail, False))
        self.sessions: dict[int, Session] = {}
        self._ids = itertools.count(1)
        self.gateway: dict[str, Any] | None = None
        self._gateway_rx: float | None = None
        self._limiter: str | None = None
        self._state_rx_sent: float | None = None
        self._state_sent_at = -math.inf
        self._photo = asyncio.Lock()
        self._look_pending: tuple[float, float] | None = None
        self._last_look_at = -math.inf
        self._tasks: set[asyncio.Task] = set()
        stt = getattr(svc, "stt", None)
        self.talk = TalkService(s, stop=self.stop, estop=self.estop, context=self._talk_context,
                                engine=stt.engine if stt is not None else None,
                                voice=getattr(svc, "voice", None))

    def start(self) -> list[asyncio.Task]:
        return [asyncio.create_task(self._pump_bus(), name="mobile-bus"),
                asyncio.create_task(self._ticker(), name="mobile-tick"),
                asyncio.create_task(self.feed.run(), name="mobile-video")]

    # ------------------------------------------------------------------ sessions
    def connect(self, device: str) -> Session:
        session = Session(next(self._ids), device)
        self.sessions[session.id] = session
        session.put({"type": "hello", "api": API_VERSION, "device": device,
                     "robot_id": self.robot_id, "caps": self.caps_view()})
        session.put({"type": "state", **self.state_view()})
        return session

    def disconnect(self, session: Session) -> None:
        if self.sessions.pop(session.id, None) is None:
            return
        self._video_changed()
        if not any(s.device == session.device for s in self.sessions.values()):
            self.drive.disconnect(session.device)

    def handle(self, session: Session, msg: object) -> None:
        """One message from the app. Stop and E-stop come first and never wait."""
        kind = msg.get("type") if isinstance(msg, dict) else None
        if kind == "stop":
            self.stop(session.device)
        elif kind == "estop":
            self.estop(session.device)
        elif kind == "drive":
            self.drive.drive(session.device, msg.get("x", 0.0), msg.get("y", 0.0),
                             msg.get("turn", 0.0), msg.get("hold_id"))
        elif kind == "heartbeat":
            t = msg.get("t")
            session.put({"type": "pong", "t": t if isinstance(t, (int, float)) else None})
        elif kind == "video":
            session.video = bool(msg.get("on"))
            self._video_changed()
        elif kind == "look":
            self._look(session.device, msg.get("pan_deg"), msg.get("speed", 0.5))
        elif kind == "perform":
            self._spawn(self._perform(session, msg))
        elif kind == "moves_switch":
            self._moves_switch(session, msg)
        elif kind == "posture":
            self._spawn(self._posture(session, msg.get("posture")))
        else:
            self._notify(session.device, "bad_message", f"unknown message type {kind!r}", True)

    def stop(self, device: str) -> int:
        return self.drive.stop_all(device)

    def _talk_context(self) -> str:
        """What a talk answer may know about the robot: a line of facts, never instructions."""
        st = self.robot.state
        if st is None:
            return "Robot state: offline (no telemetry from the body)."
        near = (f"{st.lidar.nearest_m:.2f} m at {st.lidar.nearest_bearing_deg:+.0f} deg"
                if st.lidar is not None else "unknown")
        return (f"Robot state: mode {st.mode}, E-stop {'latched' if st.estop else 'off'}, "
                f"nearest obstacle {near}.")

    def estop(self, device: str) -> int:
        seq = self.robot.estop()
        self.drive.stop_all(device)
        self.supervisor.stop()
        return seq

    def _video_changed(self) -> None:
        self.feed.wanted = any(s.video for s in self.sessions.values())

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _posture(self, session: Session, posture: object) -> None:
        if posture not in POSTURES:
            self._notify(session.device, "posture", f"unknown posture {posture!r}", True)
            return
        if self.confirm.needs_wake(posture):
            self._notify(session.device, "needs_confirm",
                         f"wake_from_limp:{posture}", False)
            return
        try:
            text = await self.robot.posture(posture, human=True)
        except RobotOffline as exc:
            self._notify(session.device, "posture", f"robot offline: {exc}", True)
            return
        self._notify(session.device, "posture", text,
                     text.startswith(("Rejected", "No answer")))

    def _look(self, device: str, pan: object, speed: object) -> None:
        if not self._number(pan) or not -90.0 <= pan <= 90.0:
            self._notify(device, "look", "camera direction must be a number from -90 to 90", True)
            return
        if not self._number(speed) or not 0.0 < speed <= 1.0:
            self._notify(device, "look", "camera speed must be greater than 0 and at most 1", True)
            return
        self._look_pending = (pan, speed)
        self._flush_look()

    async def _perform(self, session: Session, msg: dict[str, Any]) -> None:
        name, speed, leg = msg.get("name"), msg.get("speed", 0.5), msg.get("leg")
        if name not in MOVE_NAMES:
            self._notify(session.device, "perform_rejected", f"unknown move {name!r}", True)
            return
        if leg not in (None, "LF", "RF"):
            self._notify(session.device, "perform_rejected", "leading leg must be LF or RF", True)
            return
        if not self._number(speed) or not 0.0 < speed <= 1.0:
            self._notify(session.device, "perform_rejected",
                         "move speed must be greater than 0 and at most 1", True)
            return
        why = self._move_preflight(session.device)
        if why is not None:
            self._notify(session.device, "perform_rejected", why, True)
            return
        self.robot.perform(name, speed, leg, human=True)

    def _moves_switch(self, session: Session, msg: dict[str, Any]) -> None:
        values: dict[str, bool | None] = {}
        for name in ("voice", "remote"):
            value = msg.get(name)
            if value is not None and not isinstance(value, bool):
                self._notify(session.device, "moves_switch",
                             f"{name} must be true, false or null", True)
                return
            values[name] = value
        self.robot.moves_switch(values["voice"], values["remote"])

    @staticmethod
    def _number(value: object) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool) \
            and math.isfinite(value)

    def _move_preflight(self, device: str) -> str | None:
        """Why this device may not start a move now, or None. The body checks again."""
        if self.robot.version_error:
            return self.robot.version_error
        st, rx = self.robot.state, self.robot.state_rx
        now = time.monotonic()
        if st is None or rx is None or now - rx > TELEMETRY_STALE_S:
            return "no fresh telemetry from the robot"
        if st.estop:
            return "the E-stop is latched"
        if st.mode != "standing":
            return f"the robot is {st.mode}; stand it up first"
        mine = [s for s in self.sessions.values() if s.device == device and s.video]
        sent = [s.last_frame_at for s in mine if s.last_frame_at is not None]
        if sent and now - max(sent) <= self.max_frame_age_s:
            return None
        if st.lidar_age_s is not None and st.lidar_age_s <= 0.5:
            return None
        return "turn the live view on, or wait for the LiDAR"

    def _flush_look(self) -> None:
        if self._look_pending is None:
            return
        now = time.monotonic()
        if now - self._last_look_at < LOOK_GAP_S:
            return
        pan, speed = self._look_pending
        self._look_pending = None
        self._last_look_at = now
        self.robot.look(pan, speed, human=True)

    # ------------------------------------------------------------------ outgoing
    def _notify(self, device: str | None, kind: str, detail: str, refusal: bool,
                hold_id: str | None = None) -> None:
        level = "alert" if kind in ALERTS else "warn" if refusal else "info"
        msg = {"type": "event", "kind": kind, "detail": detail, "level": level,
               "refusal": refusal}
        if hold_id is not None:
            msg["hold_id"] = hold_id
        for s in list(self.sessions.values()):
            if device is None or s.device == device:
                s.put(msg)

    def _on_frame(self, frame: Frame) -> None:
        for s in list(self.sessions.values()):
            if s.video and not s.frame_queued:
                s.frame_queued = True
                s.put(frame)

    async def send(self, session: Session, socket: WebSocket) -> None:
        while True:
            item = await session.queue.get()
            if isinstance(item, Frame):
                session.frame_queued = False
                age_ms = (time.monotonic() - item.asked_at) * 1000.0
                await socket.send_bytes(pack_frame(item, age_ms))
                session.last_frame_at = item.asked_at
            else:
                await socket.send_json(item)

    # ------------------------------------------------------------------ views
    def caps_view(self) -> dict[str, Any]:
        return {"max_speed_mps": self.caps.max_speed_mps, "max_wz_rps": self.caps.max_wz_rps,
                "move_s": self.caps.move_s, "moves": list(MOVE_NAMES)}

    def _gateway_view(self, now: float) -> dict[str, Any]:
        g = self.gateway
        if g is None or self._gateway_rx is None or now - self._gateway_rx > GATEWAY_STALE_S:
            return {"online": False, "owner": None, "owner_remaining_s": 0.0, "estop": None,
                    "remote_alive": False, "moves": {}}
        return {"online": bool(g.get("online", True)), "owner": g.get("owner"),
                "owner_remaining_s": g.get("owner_remaining_s", 0.0), "estop": g.get("estop"),
                "remote_alive": bool(g.get("sources", {}).get(self.source, {}).get("alive")),
                "moves": g.get("moves", {})}

    def state_view(self) -> dict[str, Any]:
        now = time.monotonic()
        st, rx = self.robot.state, self.robot.state_rx
        age = None if rx is None else now - rx
        frame_age = self.feed.age_s()
        return {
            "robot": None if st is None else st.model_dump(exclude={"lidar", "loop_late_hist"}),
            "robot_age_ms": None if age is None else round(age * 1000.0),
            "online": age is not None and age <= TELEMETRY_STALE_S and not self.robot.version_error,
            "gateway": self._gateway_view(now),
            "drive": {"holder": self.drive.holder},
            "latency": {"robot_cmd_rtt_ms": self.drive.cmd_rtt_ms,
                        "frame_rtt_ms": self.feed.rtt_ms},
            "frame_age_ms": None if frame_age is None else round(frame_age * 1000.0),
            "caps": self.caps_view(),
        }

    def _lidar_view(self) -> dict[str, Any] | None:
        st = self.robot.state
        if st is None or st.lidar is None:
            return None
        lid = st.lidar
        return {"type": "lidar", "sector_deg": lid.sector_deg, "sectors_m": lid.sectors_m,
                "nearest_m": lid.nearest_m, "nearest_bearing_deg": lid.nearest_bearing_deg,
                "age_ms": None if st.lidar_age_s is None else round(st.lidar_age_s * 1000.0)}

    # ------------------------------------------------------------------ checks
    def _preflight(self, device: str) -> str | None:
        """Why this device may not drive now, or None. The gateway and body check again."""
        if self.robot.version_error:
            return self.robot.version_error
        st, rx = self.robot.state, self.robot.state_rx
        now = time.monotonic()
        if st is None or rx is None or now - rx > TELEMETRY_STALE_S:
            return "no fresh telemetry from the robot"
        if st.estop:
            return "the E-stop is latched"
        if st.mode not in DRIVE_MODES:
            return f"the robot is {st.mode}; stand it up first"
        mine = [s for s in self.sessions.values() if s.device == device and s.video]
        if not mine:
            return "turn the live view on to drive"
        sent = [s.last_frame_at for s in mine if s.last_frame_at is not None]
        if not sent:
            return "waiting for the first camera frame"
        age = now - max(sent)
        if age > self.max_frame_age_s:
            return f"camera frame is {age:.1f} s old"
        return None

    # ------------------------------------------------------------------ loops
    async def _pump_bus(self) -> None:
        async for ev in self.bus.subscribe():
            try:
                self._on_bus(ev)
            except Exception:
                log.exception("mobile: bad bus event %s", ev.get("kind"))

    def _on_bus(self, ev: dict[str, Any]) -> None:
        kind = ev.get("kind")
        if kind == "gateway_status":
            self.gateway, self._gateway_rx = ev.get("status") or {}, time.monotonic()
        elif kind == "robot_event" and ev.get("source") in (None, self.source):
            name, seq, detail = ev.get("event", ""), ev.get("seq"), ev.get("detail", "")
            if ev.get("source") == self.source:
                self.drive.on_event(name, seq, detail)
            if name not in QUIET:
                self._notify(None, name, detail, name in REFUSALS)

    async def _ticker(self) -> None:
        last_revoke_check = -math.inf
        while True:
            now = time.monotonic()
            self.drive.tick()
            if self._look_pending is not None and now - self._last_look_at >= LOOK_GAP_S:
                self._flush_look()
            rx = self.robot.state_rx
            fresh = rx is not None and rx != self._state_rx_sent
            if fresh or now - self._state_sent_at >= STATE_KEEPALIVE_S:
                self._broadcast_state(fresh)
            if now - last_revoke_check >= REVOKE_CHECK_S:
                last_revoke_check = now
                for s in list(self.sessions.values()):
                    if not self.devices.known(s.device):
                        s.close(CLOSE_REVOKED)
            await asyncio.sleep(TICK_S)

    def _broadcast_state(self, fresh: bool) -> None:
        self._state_rx_sent, self._state_sent_at = self.robot.state_rx, time.monotonic()
        if not self.sessions:
            return
        msgs = [{"type": "state", **self.state_view()}]
        lidar = self._lidar_view() if fresh else None
        if lidar is not None:
            msgs.append(lidar)
        st = self.robot.state
        if fresh and st is not None and st.limiter != self._limiter:
            self._limiter = st.limiter
            msgs.append({"type": "event", "kind": "limiter", "detail": st.limiter or "",
                         "level": "info", "refusal": False})
        for s in list(self.sessions.values()):
            for m in msgs:
                s.put(m)

    # ------------------------------------------------------------------ HTTP actions
    async def begin_confirm(self, device: str, action: str, posture: str | None = None) -> dict:
        conf = await self.confirm.begin(action, posture, owner=device)
        return {"challenge_id": conf.id, "action": conf.action, "ttl_s": conf.ttl_s,
                "frame_jpeg": base64.b64encode(conf.jpeg).decode("ascii"),
                "frame_age_ms": round((time.monotonic() - conf.asked_at) * 1000.0)}

    async def finish_confirm(self, device: str, challenge_id: str, approved: bool) -> dict | None:
        """None if the challenge is unknown, used, expired or another device's."""
        taken = self.confirm.take(challenge_id, owner=device)
        if taken is None:
            return None
        conf, posture = taken
        if not approved:
            return {"result": "cancelled", "detail": ""}
        mark = self.robot.event_mark()
        if conf.action == "estop_release":
            seq, done = self.robot.estop_release(conf), "released"
        else:
            seq, done = self.robot.posture_confirmed(posture or "stand", conf), "posture_sent"
        if seq < 0:
            return {"result": "refused", "detail": "the brain is not connected to the robot"}
        ev = await self.robot.wait_ack(seq, mark, 4.0)
        if ev is None:
            return {"result": "refused", "detail": "no answer from the robot"}
        if ev.kind != "ack":
            return {"result": "refused", "detail": ev.detail or ev.kind}
        return {"result": done, "detail": ev.detail}

    async def photo(self, question: str | None) -> dict:
        if self._photo.locked():
            raise Busy("a photo is already being taken")
        async with self._photo:
            jpeg = await self.robot.snapshot(timeout_s=8.0, human=True)
            answer = error = None
            if question:
                if self.vision is None:
                    error = "vision is not configured"
                else:
                    try:
                        answer = await self.vision.ask(jpeg, question)
                    except Exception as exc:  # the photo is still worth returning
                        error = str(exc)[:300] or type(exc).__name__
            return {"frame_jpeg": base64.b64encode(jpeg).decode("ascii"), "answer": answer,
                    "vision_error": error}
