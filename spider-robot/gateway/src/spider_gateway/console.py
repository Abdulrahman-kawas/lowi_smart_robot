"""spider-robotctl: the fallback console, for use over SSH when the server is down.

  spider-robotctl status
  spider-robotctl stop
  spider-robotctl estop
  spider-robotctl release     asks the gateway for a fresh photo, saves it, asks you, then releases
  spider-robotctl bench stand|sit|relax
  spider-robotctl bench walk --vx 0.05 --seconds 5
  spider-robotctl bench look 30
   spider-robotctl bench perform wave --speed 0.4 --leg RF
                                 only with SG_BENCH=1 on the gateway and a person at the robot

It is a remote operator like any other: it goes through the gateway on the remote source, so the

caps and the fresh-frame rule apply to it too.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import itertools
import os
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from spider_common.link import Link, MqttLink, MqttSettings
from spider_common.protocol import (
    MOVE_NAMES,
    Command,
    ConfirmChallenge,
    ConfirmRequest,
    EStop,
    EStopRelease,
    GatewayStatus,
    Heartbeat,
    Look,
    Move,
    Perform,
    Posture,
    RobotEvent,
    RobotState,
    Stop,
    Topics,
)

SOURCE = "remote"
BENCH_SOURCE = "bench"
TIMEOUT_S = 8.0
BEAT_S = 0.25
RENEW_S = 0.5  # a bench Move lasts 1 s and is renewed, so it stops by itself if this process dies
POSE_WAIT_S = 6.0  # a posture ramp needs the source alive until it finishes


def _target(value: str) -> float | str:
    try:
        return float(value)
    except ValueError:
        return value


class Console:
    def __init__(self, link: Link, robot_id: str, source: str = SOURCE) -> None:
        self.link = link
        self.source = source
        self.topics = Topics(robot_id)
        self.session = uuid.uuid4().hex[:12]
        self._seq = itertools.count(1)

    @staticmethod
    def subscriptions(robot_id: str, source: str = SOURCE) -> list[str]:
        t = Topics(robot_id)
        return [t.state, t.gateway_status, t.source_event(source), t.camera_filter]

    def send(self, cmd: Command) -> int:
        seq = next(self._seq)
        out = cmd.model_copy(update={"seq": seq, "ts": time.time(), "session": self.session})
        self.link.publish(self.topics.request(self.source), out.model_dump_json(), qos=1)
        return seq

    async def _beat_for(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.send(Heartbeat())
            await asyncio.sleep(BEAT_S)

    async def bench_posture(self, posture: str, wait_s: float = POSE_WAIT_S) -> None:
        self.send(Heartbeat())
        self.send(Posture(posture=posture))
        await self._beat_for(wait_s)

    async def bench_look(self, pan_deg: float, speed: float = 0.5) -> str:
        """Turn the camera on the bench source and report the body's ack or refusal."""
        self.send(Heartbeat())
        seq = self.send(Look(pan_deg=pan_deg, speed=speed))
        topic = self.topics.source_event(self.source)

        def check(msg):
            if msg.topic != topic:
                return None
            ev = RobotEvent.model_validate_json(msg.payload)
            if ev.seq == seq and ev.kind in ("ack", "rejected"):
                return f"{ev.kind}: {ev.detail}"
            return None

        beat = asyncio.create_task(self._beat_for(2.0))
        try:
            return await self.wait_for(check, 2.0) or "no answer from the robot"
        finally:
            beat.cancel()

    async def bench_perform(
        self, name: str, speed: float, leg: str | None, wait_s: float = 25.0
    ) -> str:
        self.send(Heartbeat())
        seq = self.send(Perform(name=name, speed=speed, leg=leg))
        events = self.topics.source_event(self.source)
        ends = {"perform_done", "perform_rejected", "rejected", "preempted", "link_lost",
                "estop", "obstacle_stop", "tilt", "fallen"}

        def check(msg):
            if msg.topic != events:
                return None
            ev = RobotEvent.model_validate_json(msg.payload)
            if ev.seq is not None and ev.seq != seq:
                return None
            if ev.kind in ("perform_started", "clamped"):
                print(f"{ev.kind}: {ev.detail}", flush=True)
            return f"{ev.kind}: {ev.detail}" if ev.kind in ends else None

        beat = asyncio.create_task(self._beat_for(wait_s))
        finished = False
        try:
            result = await self.wait_for(check, wait_s)
            finished = result is not None
            return result or "no answer from the robot"
        finally:
            beat.cancel()
            if not finished:
                self.send(Stop())

    async def bench_walk(self, vx: float, vy: float, wz: float, seconds: float) -> None:
        """Renews a short Move until the time is up. Always ends with a Stop, even on Ctrl-C."""
        end = time.monotonic() + seconds
        try:
            while time.monotonic() < end:
                self.send(Move(vx=vx, vy=vy, wz=wz, duration_s=1.0))
                await self._beat_for(RENEW_S)
        finally:
            self.send(Stop())

    async def wait_for(self, predicate: Callable, timeout_s: float = TIMEOUT_S):
        """The first non-None predicate(message), or None at the timeout."""
        async def scan():
            async for msg in self.link.messages():
                result = predicate(msg)
                if result is not None:
                    return result

        with contextlib.suppress(TimeoutError):
            return await asyncio.wait_for(scan(), timeout_s)
        return None

    async def status(self) -> str:
        state = await self.wait_for(
            lambda m: RobotState.model_validate_json(m.payload)
            if m.topic == self.topics.state else None
        )
        if state is None:
            return "no telemetry from the robot"
        pan = "unknown" if state.camera_pan_deg is None else f"{state.camera_pan_deg:+.0f} deg"
        return (f"mode={state.mode} estop={state.estop} limiter={state.limiter} "
                f"link_ok={state.link_ok} overruns={state.loop_overruns} rt_ok={state.rt_ok} "
                f"camera_pan={pan}")

    async def release(
        self, confirm: Callable[[Path], bool], out_dir: Path = Path("/tmp")
    ) -> str:
        rid = uuid.uuid4().hex[:12]
        self.send(ConfirmRequest(action="estop_release", request_id=rid))
        frame_topic, event_topic = self.topics.camera(rid), self.topics.source_event(SOURCE)
        got: dict[str, object] = {}

        def collect(msg):
            if msg.topic == frame_topic:
                got["jpeg"] = msg.payload
            elif msg.topic == self.topics.state:
                pan = RobotState.model_validate_json(msg.payload).camera_pan_deg
                if pan is not None:
                    got["pan"] = pan
            elif msg.topic == event_topic:
                ev = RobotEvent.model_validate_json(msg.payload)
                if ev.kind == "challenge":
                    got["challenge"] = ConfirmChallenge.model_validate_json(ev.detail)
                elif ev.kind == "rejected":
                    got["refused"] = ev.detail
                    return True
            return True if "jpeg" in got and "challenge" in got else None

        if await self.wait_for(collect) is None or "refused" in got:
            return f"no camera frame: cannot release ({got.get('refused', 'timed out')})"
        path = out_dir / f"release-{rid}.jpg"
        path.write_bytes(got["jpeg"])
        pan = got.get("pan")
        if isinstance(pan, (int, float)) and abs(pan) > 10:
            print(f"WARNING: the camera is turned {pan:+.0f} deg (+ = left); "
                  "this photo does not show straight ahead")
        if not confirm(path):
            return "E-stop kept"
        challenge = got["challenge"]
        self.send(EStopRelease(challenge=challenge.id, frame_sha256=challenge.sha256))
        ev = await self.wait_for(
            lambda m: RobotEvent.model_validate_json(m.payload)
            if m.topic == self.topics.source_event(SOURCE) else None
        )
        return f"{ev.kind}: {ev.detail}" if ev is not None else "no answer from the robot"


def _settings() -> MqttSettings:
    env = os.environ.get
    secret = env("SC_PASSWORD_FILE")
    return MqttSettings(
        host=env("SG_MQTT_HOST", "127.0.0.1"), port=int(env("SG_MQTT_PORT", "1883")),
        client_id=f"spider-console-{os.getpid()}", tls=env("SG_MQTT_TLS", "0") == "1",
        ca_path=env("SG_MQTT_CA_PATH"), username=env("SC_USERNAME"),
        password=Path(secret).read_text("utf-8").strip() if secret else None,
    )


def _ask(path: Path) -> bool:
    return input(f"Look at {path}. Type yes to release the E-stop: ").strip().lower() == "yes"


async def _run(action: str, args: argparse.Namespace) -> int:
    robot_id = os.environ.get("SG_ROBOT_ID", "spider-01")
    source = BENCH_SOURCE if action == "bench" else SOURCE
    link = MqttLink(_settings(), Console.subscriptions(robot_id, source))
    console = Console(link, robot_id, source)
    await link.start()
    await asyncio.wait_for(link.connected.wait(), TIMEOUT_S)
    await asyncio.sleep(0.2)  # let the subscriptions land
    try:
        if action == "bench":
            if args.bench_action == "walk":
                await console.bench_walk(args.vx, args.vy, args.wz, min(args.seconds, 60.0))
            elif args.bench_action == "look":
                print(await console.bench_look(args.target, args.speed))
            elif args.bench_action == "perform":
                print(await console.bench_perform(args.target, args.speed, args.leg))
            else:
                await console.bench_posture(args.bench_action)
            print("bench command finished")
        elif action == "stop":
            console.send(Stop())
            print("stop sent")
        elif action == "estop":
            console.send(EStop())
            print("E-stop sent")
        elif action == "status":
            print(await console.status())
            gw = await console.wait_for(
                lambda m: GatewayStatus.model_validate_json(m.payload)
                if m.topic == console.topics.gateway_status else None, 2.0)
            print("gateway:", "online" if gw and gw.online else "offline or unknown")
        else:
            print(await console.release(_ask))
        await asyncio.sleep(0.2)  # let QoS 1 complete
    finally:
        await link.stop()
    return 0


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="spider-robotctl")
    parser.add_argument("action", choices=["status", "stop", "estop", "release", "bench"])
    parser.add_argument("bench_action", nargs="?",
                        choices=["stand", "sit", "relax", "walk", "look", "perform"])
    parser.add_argument("target", nargs="?", type=_target)
    parser.add_argument("--vx", type=float, default=0.0)
    parser.add_argument("--vy", type=float, default=0.0)
    parser.add_argument("--wz", type=float, default=0.0)
    parser.add_argument("--seconds", type=float, default=3.0)
    parser.add_argument("--speed", type=float, default=0.5)
    parser.add_argument("--leg", choices=["LF", "RF"])
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    if args.action == "bench" and args.bench_action is None:
        parser.error("bench needs one of: stand, sit, relax, walk, look, perform")
    if args.action == "bench" and args.bench_action in ("look", "perform"):
        if not 0.0 < args.speed <= 1.0:
            parser.error("--speed must be greater than 0 and at most 1")
    if args.action == "bench" and args.bench_action == "look":
        if not isinstance(args.target, (int, float)) or not -90.0 <= args.target <= 90.0:
            parser.error("bench look needs a target between -90 and 90 degrees")
    if args.action == "bench" and args.bench_action == "perform":
        if args.target not in MOVE_NAMES:
            parser.error("bench perform needs one of: " + ", ".join(MOVE_NAMES))
        if args.leg is not None and args.target not in ("wave", "hi", "offer_hand"):
            parser.error("--leg is only for wave, hi and offer_hand")
    return asyncio.run(_run(args.action, args))


if __name__ == "__main__":
    raise SystemExit(main())
