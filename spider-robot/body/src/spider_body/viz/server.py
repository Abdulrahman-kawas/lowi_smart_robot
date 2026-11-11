"""spider-sim-view: the body simulator with a 3D view in the browser.

  spider-sim-view --config config/robot.sim.yaml [--calibration PATH] [--port 8770]

Runs the real Robot class in this process, with FakeServoBank, SimLidar and SimWorld, ticked by
main.control_loop exactly as `spider-body --sim` does. Every command from the page goes through
parse_command and Robot.handle, so all body safety rules apply. The page draws the legs with
forward kinematics from the servo degrees the robot really sent (viz/fk.py), so a wrong
direction, trim or mount angle shows up here before the servos are powered.

Standard library HTTP on 127.0.0.1 only:
  GET  /          the page (viz/static/index.html)
  GET  /events    Server-Sent Events, one JSON frame about 25 times a second
  GET  /state     one JSON frame
  POST /cmd       one command as JSON {"type": ..., fields}; seq and session are filled in

Nothing here touches MQTT, the E-stop latch file or any hardware.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import math
import time
from collections import deque
from collections.abc import Callable
from http import HTTPStatus
from importlib.resources import files
from typing import Any

from pydantic import ValidationError
from spider_common.link import InMemoryHub
from spider_common.obs import setup_logging
from spider_common.protocol import Command, Heartbeat, Topics, parse_command

from ..config import BodyConfig, load_config
from ..hw.camera import FakeCamera
from ..hw.lidar import SimLidar, SimWorld
from ..hw.servos import FakeServoBank
from ..main import control_loop
from ..robot import Robot
from .fk import all_legs

log = logging.getLogger("spider_body.viz")

HOST = "127.0.0.1"
DEFAULT_PORT = 8770
FRAME_HZ = 25.0
HEARTBEAT_S = 0.25  # well inside safety.link_timeout_s: the viewer stands in for the brain
MAX_BODY_BYTES = 4096
EVENT_LOG = 40
EVENTS_PER_FRAME = 15
SESSION = "viewer"
# Snapshot and confirm_request need a camera or the gateway; the viewer has neither.
VIEWER_COMMANDS = frozenset(
    {"move", "stop", "posture", "body_pose", "estop", "estop_release", "heartbeat"}
)


def _r(v: float, n: int = 4) -> float:
    return round(float(v), n)


class SimSession:
    """One simulated robot: Robot + fake servos + simulated LiDAR room + an event log."""

    def __init__(
        self,
        cfg: BodyConfig,
        world: SimWorld | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
    ) -> None:
        self.cfg = cfg
        self.world = world if world is not None else SimWorld()
        self.servos = FakeServoBank()
        self.lidar = SimLidar(cfg.lidar, self.world, clock=clock)
        self.hub = InMemoryHub()
        topics = Topics(cfg.robot_id)
        self.link = self.hub.endpoint([topics.cmd])
        self._event_link = self.hub.endpoint([topics.event])
        self.link.connected.set()
        self._event_link.connected.set()
        # No E-stop latch: the viewer must never read or write the real robot's latch file.
        self.robot = Robot(cfg, self.servos, self.lidar, FakeCamera(cfg.camera), self.link,
                           clock=clock, wall=wall)
        self.servos.relax()  # as main.run: start from "no torque"
        self.events: deque[dict[str, Any]] = deque(maxlen=EVENT_LOG)
        self._seq = 0

    def command(self, data: Any) -> Command:
        """Validate one command with parse_command and hand it to Robot.handle.

        Raises pydantic.ValidationError for a bad command, ValueError for one the viewer does not
        forward. seq counts up per command unless given: the body drops a Move whose seq is not
        above the last Stop's, so the page must never send seq 0 twice.
        """
        if not isinstance(data, dict):
            raise ValueError("a command must be a JSON object")
        data = dict(data)
        if "seq" not in data:
            data["seq"] = self._seq + 1
        data.setdefault("session", SESSION)
        cmd = parse_command(json.dumps(data))
        if cmd.type not in VIEWER_COMMANDS:
            raise ValueError(f"the viewer does not forward {cmd.type!r} commands")
        self._seq = max(self._seq, cmd.seq)
        self.robot.handle(cmd)
        return cmd

    def heartbeat(self) -> None:
        self.robot.handle(Heartbeat(session=SESSION))

    def drain_events(self) -> None:
        q = self._event_link.inbox.queue
        while not q.empty():
            msg = q.get_nowait()
            try:
                e = json.loads(msg.payload)
            except ValueError:
                continue
            self.events.append({"ts": e.get("ts"), "kind": e.get("kind"), "seq": e.get("seq"),
                                "detail": e.get("detail", "")})

    def frame(self) -> dict[str, Any]:
        """Everything the page draws, as one JSON-ready dict."""
        self.drain_events()
        r, w, g = self.robot, self.world, self.cfg.geometry
        roll, pitch, yaw = r.pose
        legs = all_legs(self.cfg, self.servos.last, (roll, pitch, yaw))
        feet_z = [pts[3][2] for pts in legs.values()]
        # The lowest foot stands on the floor; with no legs commanded yet, assume the belly.
        body_z = -min(feet_z) if feet_z else g.sit_height_m
        summary, age = self.lidar.latest()
        eff = r.gait.effective
        return {
            "t": round(time.time(), 3),
            "mode": r.mode,
            "estop": r.estop,
            "limiter": r.limiter,
            "servos_relaxed": self.servos.relaxed,
            "world": {"x": _r(w.x), "y": _r(w.y), "yaw": _r(w.yaw), "half_size": w.half_size},
            "pose": {
                "roll_deg": _r(math.degrees(roll), 2),
                "pitch_deg": _r(math.degrees(pitch), 2),
                "yaw_deg": _r(math.degrees(yaw), 2),
                "height_m": _r(r.gait.height),
                "body_z_m": _r(body_z),
            },
            "velocity": {"vx": _r(eff.vx), "vy": _r(eff.vy), "wz": _r(eff.wz)},
            "legs": {name: [[_r(c) for c in p] for p in pts] for name, pts in legs.items()},
            "servo_deg": {k: _r(v, 2) for k, v in sorted(self.servos.last.items())},
            "lidar": {
                "sector_deg": summary.sector_deg if summary else 360.0 / self.cfg.lidar.sectors,
                "sectors_m": list(summary.sectors_m) if summary else [],
                "age_s": None if age is None else _r(age, 3),
            },
            "obstacles": [[_r(x), _r(y), _r(rad)] for x, y, rad in w.obstacles],
            "geometry": {"footprint_x_m": g.footprint_x_m, "footprint_y_m": g.footprint_y_m,
                         "body_height_m": g.body_height_m,
                         "lidar_height_m": self.cfg.lidar.mount_height_m},
            "events": list(self.events)[-EVENTS_PER_FRAME:],
        }


def _page() -> bytes:
    return files("spider_body.viz").joinpath("static/index.html").read_bytes()


class ViewerServer:
    """Runs a SimSession (control loop, simulated LiDAR, heartbeat) and serves it over HTTP."""

    def __init__(
        self, session: SimSession, host: str = HOST, port: int = DEFAULT_PORT,
        frame_hz: float = FRAME_HZ,
    ) -> None:
        self.session = session
        self.host, self.port = host, port
        self.period = 1.0 / frame_hz
        self.page = _page()
        self._server: asyncio.Server | None = None
        self._tasks: list[asyncio.Task] = []
        self._writers: set[asyncio.StreamWriter] = set()

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    async def start(self) -> None:
        s = self.session
        self._tasks = [
            asyncio.create_task(control_loop(s.robot, s.world), name="control"),
            asyncio.create_task(s.lidar.run(), name="lidar"),
            asyncio.create_task(self._heartbeat(), name="heartbeat"),
        ]
        self._server = await asyncio.start_server(self._client, self.host, self.port)
        self.port = self._server.sockets[0].getsockname()[1]

    async def wait(self) -> None:
        """Until a background task ends (only on a crash: they all run forever)."""
        done, _ = await asyncio.wait(self._tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            if not t.cancelled() and t.exception() is not None:
                log.error("task %s crashed: %r", t.get_name(), t.exception())

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
        for w in list(self._writers):
            w.close()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._server is not None:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._server.wait_closed(), 2.0)

    async def _heartbeat(self) -> None:
        while True:
            self.session.heartbeat()
            await asyncio.sleep(HEARTBEAT_S)

    # ------------------------------------------------------------------ HTTP
    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._writers.add(writer)
        try:
            await self._request(reader, writer)
        except (ConnectionError, asyncio.IncompleteReadError, asyncio.LimitOverrunError,
                TimeoutError):
            pass
        finally:
            self._writers.discard(writer)
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    def _host_ok(self, host: str) -> bool:
        """Refuse other Host names (DNS rebinding: a web page pointing its name at 127.0.0.1)."""
        return host in (f"127.0.0.1:{self.port}", f"localhost:{self.port}")

    async def _request(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10.0)
        lines = head.decode("latin-1").split("\r\n")
        try:
            method, target, _version = lines[0].split(" ", 2)
        except ValueError:
            await _send_json(writer, 400, {"ok": False, "error": "bad request line"})
            return
        headers = {}
        for line in lines[1:]:
            key, sep, value = line.partition(":")
            if sep:
                headers[key.strip().lower()] = value.strip()
        if not self._host_ok(headers.get("host", "")):
            await _send_json(writer, 403, {"ok": False, "error": "unexpected Host header"})
            return
        path = target.split("?", 1)[0]

        if path in ("/", "/index.html"):
            if method != "GET":
                await _send_json(writer, 405, {"ok": False, "error": "use GET"})
            else:
                await _send(writer, 200, self.page, "text/html; charset=utf-8")
        elif path == "/state":
            if method != "GET":
                await _send_json(writer, 405, {"ok": False, "error": "use GET"})
            else:
                await _send_json(writer, 200, self.session.frame())
        elif path == "/events":
            if method != "GET":
                await _send_json(writer, 405, {"ok": False, "error": "use GET"})
            else:
                await self._events(writer)
        elif path == "/cmd":
            if method != "POST":
                await _send_json(writer, 405, {"ok": False, "error": "use POST"})
            else:
                await self._cmd(reader, writer, headers)
        else:
            await _send_json(writer, 404, {"ok": False, "error": "not found"})

    async def _events(self, writer: asyncio.StreamWriter) -> None:
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nCache-Control: no-store\r\n"
            b"Connection: keep-alive\r\n\r\n"
        )
        while not writer.is_closing():
            data = json.dumps(self.session.frame(), separators=(",", ":"))
            writer.write(b"data: " + data.encode() + b"\n\n")
            await writer.drain()
            await asyncio.sleep(self.period)

    async def _cmd(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, headers: dict[str, str]
    ) -> None:
        # Requiring JSON forces a CORS preflight on cross-site requests, which is never answered.
        if not headers.get("content-type", "").startswith("application/json"):
            await _send_json(writer, 415, {"ok": False, "error": "send application/json"})
            return
        try:
            length = int(headers.get("content-length", ""))
        except ValueError:
            await _send_json(writer, 411, {"ok": False, "error": "Content-Length required"})
            return
        if not 0 <= length <= MAX_BODY_BYTES:
            await _send_json(writer, 413, {"ok": False, "error": "command too large"})
            return
        body = await asyncio.wait_for(reader.readexactly(length), 10.0)
        try:
            cmd = self.session.command(json.loads(body))
        except ValidationError as exc:
            await _send_json(writer, 400, {
                "ok": False, "error": f"invalid command ({exc.error_count()} errors)",
                "details": json.loads(exc.json(include_url=False)),
            })
            return
        except ValueError as exc:  # also json.JSONDecodeError
            await _send_json(writer, 400, {"ok": False, "error": str(exc)})
            return
        await _send_json(writer, 200, {"ok": True, "type": cmd.type, "seq": cmd.seq})


async def _send(writer: asyncio.StreamWriter, status: int, body: bytes, ctype: str) -> None:
    head = (
        f"HTTP/1.1 {status} {HTTPStatus(status).phrase}\r\nContent-Type: {ctype}\r\n"
        f"Content-Length: {len(body)}\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n"
    )
    writer.write(head.encode("latin-1") + body)
    await writer.drain()


async def _send_json(writer: asyncio.StreamWriter, status: int, obj: Any) -> None:
    await _send(writer, status, json.dumps(obj).encode(), "application/json")


async def serve(cfg: BodyConfig, port: int = DEFAULT_PORT) -> None:
    server = ViewerServer(SimSession(cfg), port=port)
    try:
        await server.start()
    except OSError as exc:
        raise SystemExit(f"spider-sim-view: cannot listen on {HOST}:{port} ({exc}); "
                         "try another --port") from exc
    print(f"spider-sim-view: open {server.url}  (Ctrl+C to quit)", flush=True)
    try:
        await server.wait()
    finally:
        await server.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="spider-sim-view",
                                     description="3D motion viewer for the body simulator")
    parser.add_argument("--config", default="config/robot.sim.yaml")
    parser.add_argument("--calibration", default=None,
                        help="calibration.yaml (default: next to --config, if present)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--log-level", default="WARNING")
    args = parser.parse_args(argv)
    setup_logging(args.log_level, json_logs=False)
    cfg = load_config(args.config, args.calibration)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(serve(cfg, args.port))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
