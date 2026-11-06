"""spider-body entry point.

  spider-body --config config/robot.yaml            # real robot (Pi, servos, LiDAR, camera)
  spider-body --config config/robot.sim.yaml --sim  # simulator: fake servos/LiDAR/camera
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import gc
import logging
import os
import signal
import socket
import time

from pydantic import ValidationError
from spider_common.link import Link, MqttLink, MqttSettings
from spider_common.protocol import RobotEvent, parse_command

from .config import BodyConfig, load_config
from .hw.camera import FakeCamera, make_camera
from .hw.lidar import LidarFeed, NoLidar, SimLidar, SimWorld
from .hw.servos import FakeServoBank, make_servo_bank
from .robot import Robot

log = logging.getLogger("spider_body")


def build_link(cfg: BodyConfig) -> Link:
    from spider_common.protocol import Topics

    t = Topics(cfg.robot_id)
    will = RobotEvent(robot_id=cfg.robot_id, kind="offline", detail="connection lost")
    m = cfg.mqtt
    return MqttLink(
        MqttSettings(host=m.host, port=m.port, client_id=cfg.robot_id, tls=m.tls,
                     ca_path=m.ca_path, cert_path=m.cert_path, key_path=m.key_path),
        subscriptions=[t.cmd],
        will=(t.event, will.model_dump_json().encode()),
    )


def sd_notify(message: str) -> None:
    """systemd notify protocol (Type=notify + WatchdogSec) without extra dependencies."""
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    if addr.startswith("@"):
        addr = "\0" + addr[1:]
    with contextlib.suppress(OSError), socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
        s.sendto(message.encode(), addr)


MAX_TICK_ERRORS = 25  # 0.5 s of consecutive failures (e.g. I2C bus errors)


async def control_loop(robot: Robot, world: SimWorld | None = None) -> None:
    loop = asyncio.get_running_loop()
    dt = 1.0 / robot.cfg.gait.control_hz
    next_t = loop.time()
    errors = 0
    sd_notify("READY=1")
    while True:
        started = time.perf_counter()
        try:
            robot.tick(dt)
            errors = 0
        except Exception as exc:  # one bad I2C write must not make the robot collapse
            errors += 1
            if errors == 1:
                robot.emit("error", robot.last_seq, f"control tick failed: {exc!r}")
                log.exception("control tick failed")
            if errors >= MAX_TICK_ERRORS:
                robot.emit("error", robot.last_seq, "control failing repeatedly; relaxing servos")
                with contextlib.suppress(Exception):
                    robot.servos.relax()
                raise
        robot.loop_max_ms = max(robot.loop_max_ms, (time.perf_counter() - started) * 1000)
        if world is not None:
            e = robot.gait.effective
            world.integrate(e.vx, e.vy, e.wz, dt)
        sd_notify("WATCHDOG=1")  # systemd kills + restarts us if the loop stops ticking
        next_t += dt
        delay = next_t - loop.time()
        if delay < 0:  # overrun: count it, do not try to catch up with a burst of ticks
            robot.loop_overruns += 1
            next_t = loop.time()
            delay = 0
        await asyncio.sleep(delay)


async def command_loop(robot: Robot, link: Link) -> None:
    async for msg in link.messages():
        if msg.topic != robot.topics.cmd:
            continue
        try:
            cmd = parse_command(msg.payload)
        except ValidationError as exc:
            robot.emit("rejected", None, f"invalid command ({exc.error_count()} errors)")
            continue
        robot.handle(cmd)


IDLE_AFTER_S = 10.0  # no brain heartbeat for this long -> slow telemetry (saves IoT cost)
IDLE_PERIOD_S = 5.0


async def state_loop(robot: Robot, link: Link) -> None:
    period = 1.0 / robot.cfg.state_hz
    was_connected = False
    last_sent = 0.0
    while True:
        now = time.monotonic()
        idle = robot.clock() - robot.last_link > IDLE_AFTER_S and robot.mode == "relaxed"
        if link.connected.is_set():
            if not was_connected:
                robot.emit("online", None, f"mode={robot.mode}")
            if not idle or now - last_sent >= IDLE_PERIOD_S:
                link.publish(robot.topics.state, robot.state().model_dump_json())
                robot.loop_max_ms = 0.0
                last_sent = now
        was_connected = link.connected.is_set()
        await asyncio.sleep(period)


async def sit_and_relax(robot: Robot, timeout_s: float = 4.0) -> None:
    """Graceful shutdown: stop, sit down slowly, then cut the servo pulses."""
    robot._cancel_move()
    if robot.mode in ("standing", "walking", "estop"):
        robot.estop = False
        robot.mode = "sitting"
        robot.target_height = robot.cfg.geometry.sit_height_m
        robot.pose_target = [0.0, 0.0, 0.0]
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout_s
        while loop.time() < end and not robot._height_reached():
            await asyncio.sleep(0.05)
    robot.servos.relax()


async def run(cfg: BodyConfig, sim: bool) -> None:
    world: SimWorld | None = None
    if sim:
        world = SimWorld()
        servos = FakeServoBank()
        lidar = SimLidar(cfg.lidar, world)
        camera = FakeCamera(cfg.camera)
    else:
        servos = make_servo_bank(cfg)
        g = cfg.geometry
        lidar = (
            LidarFeed(cfg.lidar, (g.footprint_x_m, g.footprint_y_m), cfg.safety.imu_timeout_s)
            if cfg.lidar.enabled else NoLidar()
        )
        camera = make_camera(cfg.camera)

    link = build_link(cfg)
    robot = Robot(cfg, servos, lidar, camera, link)
    await link.start()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    tasks = [
        asyncio.create_task(control_loop(robot, world), name="control"),
        asyncio.create_task(command_loop(robot, link), name="commands"),
        asyncio.create_task(state_loop(robot, link), name="state"),
        asyncio.create_task(lidar.run(), name="lidar"),
    ]
    # Freeze everything allocated at startup out of the garbage collector: a full collection
    # of numpy/cv2/paho objects takes ~40 ms on a Pi 4 (two missed control ticks).
    gc.collect()
    gc.freeze()
    log.info("spider-body running (robot_id=%s, sim=%s)", cfg.robot_id, sim)
    waiter = asyncio.create_task(stop.wait())
    done, _ = await asyncio.wait([waiter, *tasks], return_when=asyncio.FIRST_COMPLETED)
    for t in done:
        if t is not waiter and t.exception():
            log.error("task %s crashed: %r", t.get_name(), t.exception())

    log.info("shutting down: sitting and relaxing servos")
    control = tasks[0]
    for t in tasks[1:]:
        t.cancel()
    if not control.done():
        await sit_and_relax(robot)
        control.cancel()
    else:
        servos.relax()
    with contextlib.suppress(Exception):
        await link.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="spider-body")
    parser.add_argument("--config", default="config/robot.yaml")
    parser.add_argument("--calibration", default=None)
    parser.add_argument("--sim", action="store_true", help="fake hardware (no Pi needed)")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=args.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    cfg = load_config(args.config, args.calibration)
    asyncio.run(run(cfg, args.sim))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
