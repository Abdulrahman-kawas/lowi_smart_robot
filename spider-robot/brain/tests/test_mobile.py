"""Mobile API: pairing, auth, dead-man driving and confirmed E-stop release.

Unit tests drive DriveControl and PairingCodes on a fake clock. The end-to-end tests run the real
brain HTTP server on a loopback port, the real gateway and the simulated body, and talk to them
the way the app does: HTTP plus one WebSocket.
"""

import asyncio
import base64
import itertools
import json
import math
import os
import stat
import struct
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from spider_body.config import load_config
from spider_body.hw.camera import FakeCamera
from spider_body.hw.lidar import SimLidar, SimWorld
from spider_body.hw.servos import FakeServoBank
from spider_body.main import command_loop, control_loop, state_loop
from spider_body.robot import Robot
from spider_common.link import InMemoryHub
from spider_common.protocol import MOVE_NAMES, RobotState, Topics
from spider_gateway.gateway import Gateway, GatewayConfig
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from spider_brain.config import Settings
from spider_brain.mobile.devices import DeviceStore, PairingCodes, RateLimited
from spider_brain.mobile.drive import Caps, DriveControl, scale
from spider_brain.robot_client import RobotClient
from spider_brain.service import BrainService
from spider_brain.workers import worker_subscriptions

ROBOT = "spider-01"
T = Topics(ROBOT)
SIM_CFG = Path(__file__).resolve().parents[2] / "body" / "config" / "robot.sim.yaml"
CAPS = Caps(max_speed_mps=0.05, max_wz_rps=0.3, move_s=1.0)


class Clock:
    def __init__(self, t: float = 100.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


async def _until(condition, timeout_s: float) -> bool:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        if condition():
            return True
        await asyncio.sleep(0.01)
    return bool(condition())


# ----------------------------------------------------------------------------- settings
def test_settings_keep_the_app_on_the_remote_source_and_under_its_caps(tmp_path):
    with pytest.raises(ValidationError, match="gateway"):
        Settings(_env_file=None, mobile=True)  # no gateway: straight to the body
    with pytest.raises(ValidationError, match="gateway"):
        Settings(_env_file=None, mobile=True, robot_source="planner")  # owner would be planner
    ok = Settings(_env_file=None, mobile=True, robot_source="planner", human_source="remote")
    assert ok.mobile_max_speed_mps == 0.12 and ok.mobile_max_wz_rps == 0.6  # the body's limits
    assert ok.mobile_deadman_s == 0.6
    for field, value in [("mobile_max_speed_mps", 0.13), ("mobile_max_wz_rps", 0.61),
                         ("mobile_move_s", 1.5), ("mobile_deadman_s", 0.8),
                         ("mobile_max_frame_age_s", 3.0)]:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, robot_source="remote", **{field: value})


# ----------------------------------------------------------------------------- pairing
def test_pairing_code_expires_and_works_once(tmp_path):
    wall, mono = Clock(1_000.0), Clock()
    codes = PairingCodes(tmp_path, ttl_s=120.0, wall=wall, clock=mono)

    code = codes.issue()
    assert len(code) == 6 and code.isdigit()
    assert code not in (tmp_path / "pairing.json").read_text()
    assert stat.S_IMODE(os.stat(tmp_path / "pairing.json").st_mode) == 0o600
    assert codes.redeem(code)
    mono.t += 1.1
    assert not codes.redeem(code)  # works once

    code = codes.issue()
    wall.t += 121.0
    mono.t += 1.1
    assert not codes.redeem(code)  # expired

    code = codes.issue()
    wrong = f"{(int(code) + 1) % 1_000_000:06d}"
    mono.t += 1.1
    assert not codes.redeem(wrong)
    with pytest.raises(RateLimited):
        codes.redeem(code)  # one attempt per second
    for _ in range(4):  # five wrong codes in all
        mono.t += 1.1
        assert not codes.redeem(wrong)
    mono.t += 1.1
    assert not codes.redeem(code)  # thrown away after five wrong attempts


def test_device_tokens_are_stored_hashed_and_revocation_is_seen(tmp_path):
    store = DeviceStore(tmp_path)
    token = store.add("iPhone 15")
    text = (tmp_path / "devices.json").read_text()
    assert token not in text and "iPhone 15" in text
    assert stat.S_IMODE(os.stat(tmp_path / "devices.json").st_mode) == 0o600
    assert store.check(token) == "iPhone 15"
    for bad in ("", "nope", None, 42, token + "x", "x" * 500):
        assert store.check(bad) is None
    assert DeviceStore(tmp_path).revoke("iPhone 15")  # the CLI, another process
    assert store.check(token) is None


# ----------------------------------------------------------------------------- dead-man logic
class FakeRobot:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self._seq = itertools.count(1)

    def move(self, vx, vy, wz, duration_s, gait="tripod", human=False):
        self.calls.append(("move", vx, vy, wz, duration_s, human))
        return next(self._seq)

    def stop(self, human=False):
        self.calls.append(("stop", human))
        return next(self._seq)

    def cancel_motion(self):
        self.calls.append(("cancel",))
        return next(self._seq)

    def kinds(self) -> list[str]:
        return [c[0] for c in self.calls]


def make_drive(preflight=None):
    clock, robot, notes = Clock(), FakeRobot(), []
    drive = DriveControl(robot, CAPS, 0.6, preflight or (lambda device: None),
                         lambda *note: notes.append(note), clock=clock)
    return drive, robot, clock, notes


def test_drive_is_clamped_to_the_remote_caps():
    assert scale(1, 0, 0, CAPS) == (0.05, 0.0, 0.0)
    vx, vy, wz = scale(5.0, 5.0, -9.0, CAPS)
    assert math.hypot(vx, vy) <= 0.05 and wz == pytest.approx(-0.3)
    vx, vy, _ = scale(0.7071068, 0.7071068, 0, CAPS)  # rounds to just over 1: still under the cap
    assert math.hypot(vx, vy) <= 0.05
    assert scale(0.01, -0.01, 0.015, CAPS) == (0.0, 0.0, 0.0)  # centred
    for bad in (float("nan"), float("inf"), True, "1", None):
        with pytest.raises(ValueError):
            scale(bad, 0, 0, CAPS)

    drive, robot, clock, notes = make_drive()
    drive.drive("phone", 3.0, -3.0, 2.0, "h1")
    kind, vx, vy, wz, duration, human = robot.calls[-1]
    assert kind == "move" and human  # the remote source, never the planner's
    assert math.hypot(vx, vy) <= 0.05 and wz == pytest.approx(0.3) and duration == 1.0
    drive.drive("phone", float("nan"), 0, 0, "h2")
    assert robot.kinds() == ["move"] and notes[-1][1] == "drive_refused"


def test_drive_speed_and_turn_speed_are_fractions_of_the_caps():
    assert scale(1, 0, 0, CAPS, speed=0.5) == pytest.approx((0.025, 0.0, 0.0))
    assert scale(0, 0, -1, CAPS, turn_speed=0.4)[2] == pytest.approx(-0.12)
    assert scale(1, 0, 1, CAPS) == pytest.approx((0.05, 0.0, 0.3))  # an older app: 1 and 1
    vx, vy, _ = scale(0.7071068, 0.7071068, 0, CAPS, speed=0.7)
    assert math.hypot(vx, vy) <= 0.05 * 0.7
    for bad in (0, -0.5, 1.5, float("nan"), float("inf"), True, "0.5", None):
        with pytest.raises(ValueError):
            scale(1, 0, 0, CAPS, speed=bad)
        with pytest.raises(ValueError):
            scale(1, 0, 0, CAPS, turn_speed=bad)

    drive, robot, clock, notes = make_drive()
    drive.drive("phone", 1, 0, 1, "h1", speed=0.5, turn_speed=0.4)
    kind, vx, vy, wz, duration, human = robot.calls[-1]
    assert vx == pytest.approx(0.025) and wz == pytest.approx(0.12)
    drive.drive("phone", 1, 0, 0, "h2", speed=2)
    assert notes[-1][:2] == ("phone", "drive_refused") and notes[-1][4] == "h2"
    assert "speed must be a number greater than 0 and at most 1" in notes[-1][2]
    assert robot.kinds() == ["move"]


def test_deadman_stops_the_robot_after_0_6_s_without_renewal():
    drive, robot, clock, notes = make_drive()
    drive.drive("phone", 1, 0, 0, "h")
    for _ in range(5):  # renewed every 0.4 s: the hold lives on
        clock.t += 0.4
        drive.tick()
        drive.drive("phone", 1, 0, 0, "h")
    assert "cancel" not in robot.kinds() and robot.kinds().count("move") == 6
    clock.t += 0.59
    drive.tick()
    assert "cancel" not in robot.kinds()
    clock.t += 0.02
    drive.tick()
    assert robot.calls[-1] == ("cancel",) and drive.hold is None
    assert notes[-1][1] == "drive_ended" and "dead-man" in notes[-1][2]
    clock.t += 0.1
    drive.drive("phone", 1, 0, 0, "h")  # the same press cannot come back
    assert robot.calls[-1] == ("cancel",)


def test_stop_beats_drive():
    drive, robot, clock, notes = make_drive()
    drive.drive("phone", 1, 0, 0, "h")
    drive.stop_all("ipad")  # any device's stop
    assert robot.calls[-1] == ("cancel",) and drive.hold is None
    assert notes[-1][:3] == ("phone", "drive_ended", "stopped by ipad")
    for _ in range(3):  # the stick is still held: renewals of that press are ignored
        clock.t += 0.4
        drive.drive("phone", 1, 0, 0, "h")
        drive.tick()
    assert robot.kinds() == ["move", "cancel"]
    drive.drive("phone", 1, 0, 0, "h2")  # lift and press again
    assert robot.kinds() == ["move", "cancel", "move"]


def test_refusals_and_safety_events_end_the_hold_for_good():
    drive, robot, clock, notes = make_drive()
    drive.drive("phone", 1, 0, 0, "h1")
    drive.on_event("ack", 1, "moving")
    drive.on_event("rejected", 1, "held off after a stop from voice")
    assert drive.hold is None and notes[-1][3] is True  # a refusal: the app buzzes
    clock.t += 2.5  # the gateway's hold-off is over, the stick still held
    drive.drive("phone", 1, 0, 0, "h1")
    assert robot.kinds() == ["move"]  # it does not start again by itself
    drive.drive("phone", 1, 0, 0, "h2")
    drive.on_event("obstacle_stop", None, "obstacle 0.18 m ahead")
    assert drive.hold is None
    drive.drive("phone", 1, 0, 0, "h3")
    drive.on_event("preempted", None, "stopped by voice")
    assert drive.hold is None and robot.kinds() == ["move", "move", "move"]


def test_one_device_drives_at_a_time_and_a_centred_stick_stands_still():
    drive, robot, clock, notes = make_drive()
    drive.drive("phone", 1, 0, 0, "a")
    drive.drive("ipad", 0, 1, 0, "b")
    assert notes[-1][:2] == ("ipad", "drive_refused") and "phone is driving" in notes[-1][2]
    assert notes[-1][4] == "b"  # the app ends only the press the event is about
    clock.t += 0.2
    drive.drive("phone", 0, 0, 0, "a")  # finger down, stick centred
    assert robot.calls[-1] == ("stop", True) and drive.holder == "phone"


def test_a_watching_phone_that_drops_stops_nothing_a_driving_one_stops_the_robot():
    drive, robot, clock, notes = make_drive()
    drive.disconnect("viewer")
    assert robot.calls == []  # a running planner task is left alone
    drive.drive("phone", 1, 0, 0, "h")
    drive.disconnect("phone")
    assert robot.calls[-1] == ("cancel",)
    drive.drive("phone", 1, 0, 0, "h2")
    drive.stop_all("phone")  # released, but its last Move may still be running
    clock.t += 0.5
    drive.disconnect("phone")
    assert robot.kinds()[-1] == "cancel" and robot.kinds().count("cancel") == 3


def test_a_stale_frame_while_driving_stops_the_robot():
    why = {"phone": None}
    drive, robot, clock, notes = make_drive(lambda device: why[device])
    drive.drive("phone", 1, 0, 0, "h")
    why["phone"] = "camera frame is 2.1 s old"
    clock.t += 0.05
    drive.tick()
    assert robot.calls[-1] == ("cancel",) and notes[-1][2] == "camera frame is 2.1 s old"


def test_live_view_slows_down_only_for_a_control_loop_that_keeps_running_late():
    from types import SimpleNamespace

    from spider_brain.mobile.camera import FrameFeed

    robot = SimpleNamespace(state=None)
    feed = FrameFeed(robot, lambda frame: None, lambda kind, detail: None)
    for i, late_ms in enumerate([1.2, 16.0, 1.2, 1.1, 7.9, 1.2, 1.2, 1.2]):  # the simulator
        robot.state = SimpleNamespace(ts=float(i), loop_late_max_ms=late_ms)
        assert not feed.control_loop_late()
    for i, late_ms in enumerate([12.0, 1.0, 14.0, 11.0], start=10):
        robot.state = SimpleNamespace(ts=float(i), loop_late_max_ms=late_ms)
        feed.control_loop_late()
    assert feed.control_loop_late()


# ----------------------------------------------------------------------------- over the wire
def mobile_settings(tmp_path, **kw) -> Settings:
    base = dict(robot_source="planner", human_source="remote", mobile=True, dashboard=False,
                port=0, mobile_data_dir=str(tmp_path / "mobile"),
                memory_path=str(tmp_path / "memory.jsonl"),
                traces_path=str(tmp_path / "traces.jsonl"), online_timeout_s=5)
    base.update(kw)
    return Settings(_env_file=None, **base)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class FakeVision:
    async def ask(self, jpeg, question):
        return f"an orange box ({question})"


class App:
    """Speaks the app's protocol: auth first, a heartbeat every second, frames as binary."""

    def __init__(self, ws) -> None:
        self.ws = ws
        self.events: list[dict] = []
        self.states: list[dict] = []
        self.frames: list[dict] = []
        self.other: list[dict] = []
        self._tasks = [asyncio.create_task(self._read()), asyncio.create_task(self._beat())]

    @classmethod
    async def open(cls, base: str, token: str) -> "App":
        ws = await connect(base.replace("http://", "ws://") + "/v1/live")
        await ws.send(json.dumps({"type": "auth", "token": token}))
        return cls(ws)

    async def _read(self) -> None:
        try:
            async for raw in self.ws:
                if isinstance(raw, bytes):
                    n = struct.unpack(">I", raw[:4])[0]
                    header = json.loads(raw[4:4 + n])
                    assert raw[4 + n:4 + n + 2] == b"\xff\xd8"
                    self.frames.append(header)
                    continue
                msg = json.loads(raw)
                {"event": self.events, "state": self.states}.get(msg["type"], self.other) \
                    .append(msg)
        except ConnectionClosed:
            pass

    async def _beat(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            await self.send(type="heartbeat", t=time.monotonic())

    async def send(self, **msg) -> None:
        await self.ws.send(json.dumps(msg))

    def kinds(self) -> list[str]:
        return [e["kind"] for e in self.events]

    async def close(self) -> None:
        for task in self._tasks:
            task.cancel()
        await self.ws.close()


@dataclass
class Stack:
    body: Robot | None
    gateway: Gateway | None
    svc: BrainService
    base: str
    token: str
    cancels: list[float]
    http: httpx.AsyncClient


async def _start_brain(s: Settings, link) -> tuple[BrainService, list[float]]:
    svc = BrainService(s, link=link, vision=FakeVision(), planner_factory=lambda tier: None)
    cancels: list[float] = []
    real = svc.robot.cancel_motion

    def spy() -> int:
        cancels.append(time.monotonic())
        return real()

    svc.robot.cancel_motion = spy
    await svc.start()
    return svc, cancels


@pytest.fixture
async def brain(tmp_path):
    """The brain alone, with no robot: enough for auth and pairing."""
    s = mobile_settings(tmp_path)
    hub = InMemoryHub()
    svc, cancels = await _start_brain(s, hub.endpoint(RobotClient.subscriptions(
        ROBOT, "planner", "remote")))
    base = f"http://127.0.0.1:{svc.http_port}"
    async with httpx.AsyncClient(base_url=base, timeout=10.0) as http:
        yield Stack(None, None, svc, base, svc.mobile.devices.add("phone"), cancels, http)
    await svc.stop()


@pytest.fixture
async def stack(tmp_path):
    """Brain, real gateway and simulated body, all in this process."""
    cfg = load_config(SIM_CFG, calibration="/nonexistent")
    cfg.state_hz = 20
    cfg.gait.posture_speed_mps = 0.2
    hub = InMemoryHub()
    world = SimWorld(obstacles=[])
    body_link = hub.endpoint([T.cmd])
    body = Robot(cfg, FakeServoBank(), SimLidar(cfg.lidar, world), FakeCamera(cfg.camera),
                 body_link)
    gw_link = hub.endpoint(Gateway.subscriptions(ROBOT))
    gateway = Gateway(gw_link, ROBOT,
                      config=GatewayConfig(state_dir=tmp_path / "gateway-state"))
    for link in (body_link, gw_link):
        await link.start()
    tasks = [asyncio.create_task(c) for c in (
        control_loop(body, world), command_loop(body, body_link), state_loop(body, body_link),
        body.lidar.run(), gateway.run(tick_hz=20.0))]
    s = mobile_settings(tmp_path)
    svc, cancels = await _start_brain(s, hub.endpoint(
        RobotClient.subscriptions(ROBOT, "planner", "remote") + worker_subscriptions(s)))
    assert await svc.robot.wait_online(5.0)
    base = f"http://127.0.0.1:{svc.http_port}"
    async with httpx.AsyncClient(base_url=base, timeout=15.0) as http:
        yield Stack(body, gateway, svc, base, svc.mobile.devices.add("phone"), cancels, http)
    await svc.stop()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def confirm(st: Stack, path: str, token: str | None = None, **body) -> dict:
    """Start a confirmed action, check the frame that came with it, approve it."""
    r = await st.http.post(path, json=body or None, headers=bearer(token or st.token))
    assert r.status_code == 200, r.text
    challenge = r.json()
    assert base64.b64decode(challenge["frame_jpeg"])[:2] == b"\xff\xd8"
    assert 0 <= challenge["frame_age_ms"] < 2_000
    r = await st.http.post("/v1/confirm", json={"challenge_id": challenge["challenge_id"],
                                                "approved": True},
                           headers=bearer(token or st.token))
    assert r.status_code == 200, r.text
    return {**r.json(), "challenge_id": challenge["challenge_id"]}


async def stand(st: Stack) -> None:
    """The robot starts limp: a remote stand needs a fresh frame and a confirmation."""
    assert st.body.mode == "relaxed"
    done = await confirm(st, "/v1/wake", posture="stand")
    assert done["result"] == "posture_sent", done
    assert await _until(lambda: st.body.mode == "standing" and st.body._height_reached(), 10.0)


def refused(app: App, text: str) -> bool:
    return any(e["refusal"] and text in e["detail"] for e in app.events)


async def live_view(st: Stack) -> App:
    app = await App.open(st.base, st.token)
    await app.send(type="video", on=True)
    assert await _until(lambda: app.frames, 5.0)
    return app


async def test_missing_or_bad_token_is_refused(brain):
    http = brain.http
    assert (await http.get("/v1/hello")).json()["service"] == "spider-brain"
    for headers in ({}, bearer("nope"), {"Authorization": brain.token},
                    {"Authorization": f"Basic {brain.token}"}):
        for method, path in [("GET", "/v1/state"), ("POST", "/v1/stop"), ("POST", "/v1/estop"),
                             ("POST", "/v1/estop/release"), ("POST", "/v1/photo")]:
            r = await http.request(method, path, headers=headers)
            assert r.status_code == 401, (method, path, headers)
    assert brain.cancels == []  # nothing reached the robot
    r = await http.get("/v1/state", headers=bearer(brain.token))
    assert r.status_code == 200 and r.json()["online"] is False

    ws_url = brain.base.replace("http://", "ws://") + "/v1/live"
    for first in ({"type": "auth", "token": "nope"}, {"type": "stop"}, {"token": brain.token}):
        async with connect(ws_url) as ws:
            await ws.send(json.dumps(first))
            with pytest.raises(ConnectionClosed) as exc:
                await asyncio.wait_for(ws.recv(), 5.0)
            assert exc.value.rcvd.code == 4401
    async with connect(ws_url, origin="http://evil.example") as ws:  # a browser page
        with pytest.raises(ConnectionClosed) as exc:  # closed before it can even send
            await ws.send(json.dumps({"type": "auth", "token": brain.token}))
            await asyncio.wait_for(ws.recv(), 5.0)
        assert exc.value.rcvd.code == 4403
    assert brain.cancels == []


async def test_pairing_over_http_and_revocation_closes_the_socket(brain):
    http = brain.http
    code = brain.svc.mobile.codes.issue()
    r = await http.post("/v1/pair", json={"code": code, "device_name": "Lowi\x07Pad"})
    assert r.status_code == 400  # a control character in the name; the code is not spent
    r = await http.post("/v1/pair", json={"code": code, "device_name": " テスト用\n iPad "})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    assert r.json()["device_name"] == "テスト用 iPad"
    assert r.json()["caps"] == {"max_speed_mps": 0.05, "max_wz_rps": 0.3, "move_s": 1.0,
                                "moves": list(MOVE_NAMES)}
    assert (await http.get("/v1/state", headers=bearer(token))).status_code == 200
    r = await http.post("/v1/pair", json={"code": code, "device_name": "again"})
    assert r.status_code == 429  # within a second
    await asyncio.sleep(1.05)
    r = await http.post("/v1/pair", json={"code": code, "device_name": "again"})
    assert r.status_code == 401  # used

    app = await App.open(brain.base, token)
    assert await _until(lambda: any(m["type"] == "hello" for m in app.other), 3.0)
    DeviceStore(Path(brain.svc.settings.mobile_data_dir)).revoke("テスト用 iPad")
    assert await _until(lambda: app.ws.close_code is not None, 2.5)
    assert app.ws.close_code == 4401
    assert (await http.get("/v1/state", headers=bearer(token))).status_code == 401
    await app.close()


async def test_driving_needs_a_standing_robot_and_a_fresh_frame(stack):
    app = await App.open(stack.base, stack.token)
    await app.send(type="drive", x=1, y=0, turn=0, hold_id="a")
    assert await _until(lambda: refused(app, "stand it up first"), 2.0)
    await stand(stack)
    await app.send(type="drive", x=1, y=0, turn=0, hold_id="b")
    assert await _until(lambda: refused(app, "turn the live view on"), 2.0)
    assert stack.body.move is None
    await app.close()


async def test_socket_drop_cancels_motion_within_0_6_s(stack):
    await stand(stack)
    app = await live_view(stack)
    await app.send(type="drive", x=1, y=1, turn=-1, hold_id="h")
    assert await _until(lambda: stack.body.move is not None, 2.0)
    move = stack.body.move
    assert math.hypot(move.vx, move.vy) <= 0.05 and abs(move.wz) <= 0.3
    assert move.duration_s <= 1.0
    assert "capped" not in stack.gateway.counters  # the brain already kept to the caps
    before = len(stack.cancels)
    dropped = time.monotonic()
    app.ws.transport.abort()  # no close handshake: the phone just vanished
    assert await _until(lambda: len(stack.cancels) > before, 0.6)
    assert stack.cancels[before] - dropped < 0.6
    assert await _until(lambda: stack.body.move is None, 1.0)
    for task in app._tasks:
        task.cancel()


async def test_no_renewal_stops_the_robot_within_a_second(stack):
    await stand(stack)
    app = await live_view(stack)
    before = len(stack.cancels)
    await app.send(type="drive", x=1, y=0, turn=0, hold_id="h")
    sent = time.monotonic()
    assert await _until(lambda: stack.body.move is not None, 1.0)
    assert await _until(lambda: len(stack.cancels) > before, 1.0)  # socket still open
    assert 0.55 < stack.cancels[before] - sent < 0.75
    assert await _until(lambda: stack.body.move is None, 1.0 - (time.monotonic() - sent))
    assert await _until(lambda: any("dead-man" in e["detail"] and e.get("hold_id") == "h"
                                    for e in app.events), 1.0)
    await app.close()


async def test_stop_beats_drive_over_the_socket(stack):
    await stand(stack)
    app = await live_view(stack)
    await app.send(type="drive", x=1, y=0, turn=0, hold_id="h")
    await app.send(type="stop")
    await app.send(type="drive", x=1, y=0, turn=0, hold_id="h")
    await asyncio.sleep(0.3)
    assert stack.body.move is None
    for _ in range(4):  # the finger is still down and the app keeps renewing that press
        await app.send(type="drive", x=1, y=0, turn=0, hold_id="h")
        await asyncio.sleep(0.35)
        assert stack.body.move is None
    await app.send(type="drive", x=1, y=0, turn=0, hold_id="h2")  # a new press drives
    assert await _until(lambda: stack.body.move is not None, 1.0)
    r = await stack.http.post("/v1/stop", headers=bearer(stack.token))  # the HTTP fallback
    assert r.json() == {"sent": True}
    assert await _until(lambda: stack.body.move is None, 1.0)
    await app.close()


async def test_estop_release_needs_a_confirmation_that_works_once(stack):
    await stand(stack)
    app = await live_view(stack)  # the live view must not starve the confirmation frame
    await app.send(type="estop")
    assert await _until(lambda: stack.body.estop and stack.svc.robot.state.estop, 2.0)
    r = await stack.http.post("/v1/confirm", json={"challenge_id": "made-up", "approved": True},
                              headers=bearer(stack.token))
    assert r.status_code == 409 and stack.body.estop

    r = await stack.http.post("/v1/estop/release", headers=bearer(stack.token))
    assert r.status_code == 200, r.text
    challenge = r.json()["challenge_id"]
    r = await stack.http.post("/v1/confirm", json={"challenge_id": challenge, "approved": False},
                              headers=bearer(stack.token))
    assert r.json()["result"] == "cancelled" and stack.body.estop

    other = stack.svc.mobile.devices.add("ipad")
    r = await stack.http.post("/v1/estop/release", headers=bearer(stack.token))
    challenge = r.json()["challenge_id"]
    r = await stack.http.post("/v1/confirm", json={"challenge_id": challenge, "approved": True},
                              headers=bearer(other))
    assert r.status_code == 409 and stack.body.estop  # only the phone that saw the frame
    r = await stack.http.post("/v1/confirm", json={"challenge_id": challenge, "approved": True},
                              headers=bearer(stack.token))
    assert r.json()["result"] == "released", r.text
    assert await _until(lambda: not stack.body.estop and not stack.svc.robot.state.estop, 2.0)
    r = await stack.http.post("/v1/confirm", json={"challenge_id": challenge, "approved": True},
                              headers=bearer(stack.token))
    assert r.status_code == 409  # used
    r = await stack.http.post("/v1/estop/release", headers=bearer(stack.token))
    assert r.status_code == 409  # nothing to release
    assert stack.gateway.counters.get("snapshot_limited", 0) == 0
    await app.close()


async def test_state_lidar_events_and_photo(stack):
    app = await live_view(stack)
    assert await _until(lambda: any(m["type"] == "lidar" for m in app.other), 2.0)
    lidar = next(m for m in app.other if m["type"] == "lidar")
    assert len(lidar["sectors_m"]) == 36
    state = app.states[-1]
    assert state["online"] and state["robot"]["mode"] == "relaxed"
    assert "battery" not in json.dumps(state)
    assert state["gateway"]["online"] and state["caps"]["max_speed_mps"] == 0.05
    assert app.frames[-1]["age_ms"] < 2_000
    await app.send(type="heartbeat", t=12.5)
    assert await _until(lambda: {"type": "pong", "t": 12.5} in app.other, 2.0)
    await app.send(type="posture", posture="stand")  # limp: the app must confirm instead
    assert await _until(lambda: "needs_confirm" in app.kinds(), 2.0)

    r = await stack.http.post("/v1/photo", json={"question": "what is ahead?"},
                              headers=bearer(stack.token))
    assert r.status_code == 200, r.text
    assert r.json()["answer"] == "an orange box (what is ahead?)"
    assert base64.b64decode(r.json()["frame_jpeg"])[:2] == b"\xff\xd8"
    assert stack.gateway.counters.get("snapshot_limited", 0) == 0
    await app.close()


async def test_the_app_switches_moves_and_sees_the_gateway_state(stack):
    app = await live_view(stack)
    assert app.states[-1]["gateway"]["moves"] == {"voice": True, "remote": False}

    await app.send(type="moves_switch", remote=True)
    assert await _until(
        lambda: app.states[-1]["gateway"]["moves"] == {"voice": True, "remote": True}, 2.0)
    assert stack.gateway.status(time.monotonic()).moves == {"voice": True, "remote": True}

    await app.send(type="moves_switch", voice=False, remote=False)
    assert await _until(
        lambda: app.states[-1]["gateway"]["moves"] == {"voice": False, "remote": False}, 2.0)
    await app.close()


async def test_the_app_refuses_an_invalid_moves_switch(brain):
    app = await App.open(brain.base, brain.token)
    await app.send(type="moves_switch", voice="yes")
    assert await _until(lambda: any(e["kind"] == "moves_switch" for e in app.events), 2.0)
    assert app.events[-1]["detail"] == "voice must be true, false or null"
    assert app.events[-1]["refusal"] is True
    await app.close()


async def test_talk_needs_a_token_and_a_spoken_stop_reaches_the_robot(brain):
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as clip:
        clip.setnchannels(1)
        clip.setsampwidth(2)
        clip.setframerate(16_000)
        square = (3000 if (i // 36) % 2 else -3000 for i in range(16_000))  # loud: not silence
        clip.writeframes(b"".join(v.to_bytes(2, "little", signed=True) for v in square))
    body = {"audio_b64": base64.b64encode(buf.getvalue()).decode(), "mime": "audio/wav"}
    assert (await brain.http.post("/v1/talk", json=body)).status_code == 401

    class Engine:  # stands in for Whisper: the owner said "stop"
        async def transcribe(self, pcm, language, prompt):
            return "قف", 0.9

    brain.svc.mobile.talk.engine = Engine()
    r = await brain.http.post("/v1/talk", json=body, headers=bearer(brain.token))
    assert r.status_code == 200, r.text
    assert r.json()["action"] == "stop" and r.json()["reply"] == "وقفت."
    assert brain.cancels  # the STOP went to the robot client
    bad = await brain.http.post("/v1/talk", json={"audio_b64": "@" * 12},
                                headers=bearer(brain.token))
    assert bad.status_code == 400


def _looks(stack):
    out = []
    for m in stack.svc.robot.link.published:
        if m.topic != T.request("remote"):
            continue
        data = json.loads(m.payload)
        if data.get("type") == "look":
            out.append(data)
    return out


def _requests(stack, kind):
    return [data for data in (json.loads(m.payload) for m in stack.svc.robot.link.published
                              if m.topic == T.request("remote")) if data.get("type") == kind]


def _drain(session):
    out = []
    while not session.queue.empty():
        out.append(session.queue.get_nowait())
    return out


async def test_a_look_message_sends_one_look_on_the_remote_source(brain):
    session = brain.svc.mobile.connect("phone")
    _drain(session)
    brain.svc.mobile.handle(session, {"type": "look", "pan_deg": 30.0, "speed": 0.5})
    looks = _looks(brain)
    assert len(looks) == 1 and looks[0]["pan_deg"] == 30.0 and looks[0]["speed"] == 0.5


async def test_ten_look_targets_send_one_now_and_the_last_one_later(brain):
    session = brain.svc.mobile.connect("phone")
    _drain(session)
    for pan in range(1, 11):
        brain.svc.mobile.handle(session, {"type": "look", "pan_deg": pan})
    assert [c["pan_deg"] for c in _looks(brain)] == [1.0]
    assert await _until(lambda: len(_looks(brain)) == 2, 1.0)
    assert _looks(brain)[-1]["pan_deg"] == 10.0


async def test_bad_look_values_are_refused_without_sending(brain):
    session = brain.svc.mobile.connect("phone")
    _drain(session)
    for msg in ({"pan_deg": 100}, {"pan_deg": "30"}, {"pan_deg": 30, "speed": 0},
                {"pan_deg": 30, "speed": 1.5}, {"pan_deg": float("nan")}):
        brain.svc.mobile.handle(session, {"type": "look", **msg})
    assert _looks(brain) == []
    refusals = [m for m in _drain(session) if m.get("kind") == "look"]
    assert len(refusals) == 5 and all(m["refusal"] for m in refusals)


def _performs(brain):
    out = []
    for m in brain.svc.robot.link.published:
        if m.topic != T.request("remote"):
            continue
        data = json.loads(m.payload)
        if data.get("type") == "perform":
            out.append(data)
    return out


def _fresh_standing(brain, lidar_age_s=0.2):
    brain.svc.robot.state = RobotState(robot_id=ROBOT, mode="standing", lidar_age_s=lidar_age_s)
    brain.svc.robot.state_rx = time.monotonic()


async def test_fresh_lidar_is_enough_to_send_one_perform(brain):
    session = brain.svc.mobile.connect("phone")
    _drain(session)
    _fresh_standing(brain)
    brain.svc.mobile.handle(session, {"type": "perform", "name": "dance", "speed": 0.75,
                                      "leg": None})
    assert await _until(lambda: _performs(brain), 1.0)
    assert _performs(brain)[0]["name"] == "dance"
    assert _performs(brain)[0]["speed"] == 0.75


async def test_perform_without_live_view_or_lidar_is_refused(brain):
    session = brain.svc.mobile.connect("phone")
    _drain(session)
    _fresh_standing(brain, lidar_age_s=None)
    brain.svc.mobile.handle(session, {"type": "perform", "name": "dance"})
    assert await _until(lambda: not session.queue.empty(), 1.0)
    assert _performs(brain) == []
    refusals = [m for m in _drain(session) if m.get("kind") == "perform_rejected"]
    assert len(refusals) == 1 and "live view" in refusals[0]["detail"]


async def test_bad_perform_values_are_refused_without_sending(brain):
    session = brain.svc.mobile.connect("phone")
    _drain(session)
    _fresh_standing(brain)
    for msg in ({"name": "nope"}, {"name": "wave", "leg": "RR"},
                {"name": "wave", "speed": 0}, {"name": "wave", "speed": 1.5}):
        brain.svc.mobile.handle(session, {"type": "perform", **msg})
    assert await _until(lambda: session.queue.qsize() >= 4, 1.0)
    assert _performs(brain) == []
    refusals = [m for m in _drain(session) if m.get("kind") == "perform_rejected"]
    assert len(refusals) == 4 and all(m["refusal"] for m in refusals)


async def test_hello_advertises_every_move(brain):
    session = brain.svc.mobile.connect("phone")
    hello = _drain(session)[0]
    assert hello["caps"]["moves"] == list(MOVE_NAMES)


async def test_a_speed_limit_message_sends_one_speed_limit_on_the_remote_source(brain):
    session = brain.svc.mobile.connect("phone")
    _drain(session)
    brain.svc.mobile.handle(session, {"type": "speed_limit", "max_speed_mps": 0.08,
                                      "max_wz_rps": 0.4})
    out = _requests(brain, "speed_limit")
    assert len(out) == 1 and (out[0]["max_speed_mps"], out[0]["max_wz_rps"]) == (0.08, 0.4)
    for bad in ({"max_speed_mps": 0, "max_wz_rps": 0.4},
                {"max_speed_mps": "0.1", "max_wz_rps": 0.4},
                {"max_speed_mps": 0.08},
                {"max_speed_mps": True, "max_wz_rps": 0.4},
                {"max_speed_mps": 0.08, "max_wz_rps": float("nan")},
                {"max_speed_mps": 0.13, "max_wz_rps": 0.4},
                {"max_speed_mps": 0.08, "max_wz_rps": 0.7}):
        brain.svc.mobile.handle(session, {"type": "speed_limit", **bad})
    assert len(_requests(brain, "speed_limit")) == 1
    refusals = [m for m in _drain(session) if m.get("kind") == "speed_limit"]
    assert len(refusals) == 7 and all(m["refusal"] for m in refusals)
    assert refusals[-1]["detail"] == "above the brain's caps of 0.12 m/s and 0.6 rad/s"


async def test_caps_are_the_lower_of_the_brain_and_the_gateway(brain):
    hub = brain.svc.mobile
    view = hub.caps_view()
    assert (view["max_speed_mps"], view["max_wz_rps"]) == (0.05, 0.3)  # no gateway heard yet
    status = {"remote_limits": {"max_speed_mps": 0.09, "max_wz_rps": 0.45,
                                "ceiling_speed_mps": 0.12, "ceiling_wz_rps": 0.6}}
    hub._on_bus({"kind": "gateway_status", "status": status})
    assert (hub.caps_view()["max_speed_mps"], hub.drive.caps.max_wz_rps) == (0.09, 0.45)
    assert hub.state_view()["gateway"]["remote_limits"]["ceiling_speed_mps"] == 0.12
    hub._on_bus({"kind": "gateway_status", "status": {"online": True}})  # an older gateway
    assert hub.caps_view()["max_speed_mps"] == 0.05
    assert hub.state_view()["gateway"]["remote_limits"] is None
    hub.brain_caps = Caps(0.07, 0.6, 1.0)  # as if SB_MOBILE_MAX_SPEED_MPS=0.07
    hub._on_bus({"kind": "gateway_status", "status": status})
    assert hub.caps_view()["max_speed_mps"] == 0.07


async def test_the_app_sets_its_top_speed_and_drives_at_a_fraction_of_it(stack):
    await stand(stack)
    app = await live_view(stack)
    assert app.states[-1]["gateway"]["remote_limits"]["max_speed_mps"] == 0.05
    await app.send(type="speed_limit", max_speed_mps=0.08, max_wz_rps=0.4)
    assert await _until(lambda: app.states[-1]["caps"]["max_speed_mps"] == 0.08, 3.0)
    limits = app.states[-1]["gateway"]["remote_limits"]
    assert (limits["max_wz_rps"], limits["ceiling_speed_mps"]) == (0.4, 0.12)
    await app.send(type="drive", x=1, y=0, turn=0, hold_id="h", speed=0.5)
    assert await _until(lambda: stack.body.move is not None, 2.0)
    assert stack.body.move.vx == pytest.approx(0.04)
    assert "capped" not in stack.gateway.counters  # the brain kept to the new limit
    await app.send(type="stop")
    await app.send(type="drive", x=1, y=0, turn=0, hold_id="h2", speed=0)
    assert await _until(lambda: refused(app, "speed must be a number"), 2.0)
    await app.close()
