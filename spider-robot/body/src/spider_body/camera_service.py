"""spider-camera: camera capture as its own process on cores 1-3.

JPEG encoding costs milliseconds of CPU and OpenCV costs tens of megabytes, so neither belongs in
the control process on core 0. This process answers the same Snapshot command the body used to
answer: the gateway keeps publishing it on the cmd topic, and frames still leave on camera/<id>.
The gateway reads those frames itself to bind a remote E-stop release to one exact image.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import time

from pydantic import ValidationError
from spider_common.link import Link, MqttLink
from spider_common.obs import setup_logging
from spider_common.protocol import (
    EventKind,
    HealthReport,
    RobotEvent,
    Snapshot,
    Topics,
    parse_command,
)

from .config import BodyConfig, broker_settings, load_config
from .hw.camera import Camera, make_camera

log = logging.getLogger("spider_camera")
HEALTH_PERIOD_S = 5.0


class CameraService:
    def __init__(self, cfg: BodyConfig, camera: Camera, link: Link) -> None:
        self.cfg, self.camera, self.link = cfg, camera, link
        self.topics = Topics(cfg.robot_id)
        self.frames = 0
        self.failures = 0
        self.last_duration_ms = 0.0
        self._lock = asyncio.Lock()  # one capture at a time; requests wait in the pump

    def _event(self, kind: EventKind, seq: int, detail: str, trace: str) -> None:
        ev = RobotEvent(robot_id=self.cfg.robot_id, kind=kind, seq=seq, detail=detail, trace=trace)
        self.link.publish(self.topics.event, ev.model_dump_json(), qos=1)

    async def capture(self, cmd: Snapshot) -> None:
        async with self._lock:
            started = time.perf_counter()
            try:
                data = await asyncio.to_thread(self.camera.snapshot)
            except Exception as exc:  # no camera problem may take this service down
                self.failures += 1
                self._event("snapshot_failed", cmd.seq, f"{cmd.request_id}: {exc}", cmd.trace)
                return
            self.last_duration_ms = (time.perf_counter() - started) * 1000.0
            self.frames += 1
            self.link.publish(self.topics.camera(cmd.request_id), data, qos=1)

    def health(self) -> HealthReport:
        level = "degraded" if self.failures > self.frames else "ok"
        return HealthReport(
            robot_id=self.cfg.robot_id, service="camera", level=level,
            metrics={"frames": float(self.frames), "failures": float(self.failures),
                     "last_ms": round(self.last_duration_ms, 1)},
        )

    async def pump(self) -> None:
        async for msg in self.link.messages():
            if msg.topic != self.topics.cmd:
                continue
            try:
                cmd = parse_command(msg.payload)
            except ValidationError:
                continue  # malformed commands are reported by the body, not here
            if isinstance(cmd, Snapshot):
                asyncio.create_task(self.capture(cmd))

    async def health_loop(self) -> None:
        while True:
            self.link.publish(self.topics.health("camera"), self.health().model_dump_json(),
                              qos=1, retain=True)
            await asyncio.sleep(HEALTH_PERIOD_S)


def build_link(cfg: BodyConfig) -> MqttLink:
    t = Topics(cfg.robot_id)
    will = HealthReport(robot_id=cfg.robot_id, service="camera", level="down", detail="lost")
    c = cfg.camera
    return MqttLink(
        broker_settings(cfg.mqtt, c.client_id, c.username, c.password_file),
        subscriptions=[t.cmd],
        will=(t.health("camera"), will.model_dump_json().encode()),
        will_retain=True,
    )


async def run(cfg: BodyConfig) -> None:
    link = build_link(cfg)
    service = CameraService(cfg, make_camera(cfg.camera), link)
    await link.start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    tasks = [asyncio.create_task(service.pump()), asyncio.create_task(service.health_loop())]
    await stop.wait()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await link.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="spider-camera")
    parser.add_argument("--config", default="config/robot.yaml")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    setup_logging(args.log_level)
    asyncio.run(run(load_config(args.config, "/nonexistent")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
