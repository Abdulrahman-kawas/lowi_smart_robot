"""spider-body entry point.

  spider-body --config config/robot.yaml            # real robot (Pi, servos, LiDAR, camera)
  spider-body --config config/robot.sim.yaml --sim  # simulator: fake servos/LiDAR/camera
  spider-body --config ... --jitter-seconds 3600    # run, then print the timing histograms
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import gc
import json
import logging
import os
import signal
import socket
import time

from pydantic import ValidationError
from spider_common.link import Link, MqttLink
from spider_common.obs import setup_logging
from spider_common.protocol import RobotEvent, parse_command

from .config import BodyConfig, broker_settings, load_config
from .hw.camera import FakeCamera, make_camera
from .hw.kick import make_kick
from .hw.lidar import LidarFeed, NoLidar, SimLidar, SimWorld
from .hw.servos import FakeServoBank, make_servo_bank
from .robot import Robot
from .rt import enable_fifo, pin_cpu, set_gil_interval
from .safety import EStopLatch

log = logging.getLogger("spider_body")


def build_link(cfg: BodyConfig) -> Link:
    from spider_common.protocol import Topics

    t = Topics(cfg.robot_id)
    will = RobotEvent(robot_id=cfg.robot_id, kind="offline", detail="connection lost")
    return MqttLink(
        broker_settings(cfg.mqtt, cfg.robot_id),
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
        late_ms = max(0.0, (loop.time() - next_t) * 1000.0)  # how late this tick started
        robot.note_wakeup(late_ms)
        try:
            robot.tick(dt)
            robot.kick.toggle()  # only after a good tick: no kick, and the relay drops
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
        tick_ms = (time.perf_counter() - started) * 1000
        robot.tick_hist.record(tick_ms)
        robot.loop_max_ms = max(robot.loop_max_ms, tick_ms)
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
                robot.loop_late_max_ms = 0.0
                last_sent = now
        was_connected = link.connected.is_set()
        await asyncio.sleep(period)


async def sit_and_relax(robot: Robot, timeout_s: float = 4.0) -> None:
    """Graceful shutdown: stop, sit down slowly, then cut the servo pulses.

    Never under a latched E-stop: the robot must not move, and the latch must stay set for the
    next process. In that case the servos keep their last position until power is cut.
    """
    robot._cancel_move()
    if robot.estop:
        return
    if robot.mode in ("standing", "walking"):
        robot.mode = "sitting"
        robot.target_height = robot.cfg.geometry.sit_height_m
        robot.pose_target = [0.0, 0.0, 0.0]
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout_s
        while loop.time() < end and not robot._height_reached():
            await asyncio.sleep(0.05)
    robot.servos.relax()


async def jitter_report(robot: Robot, seconds: float, stop: asyncio.Event) -> None:
    """Bench measurement: run for a fixed time, print the histograms as one JSON line, exit."""
    await asyncio.sleep(seconds)
    print(json.dumps({
        "late_ms": robot.late_hist.snapshot(),
        "tick_ms": robot.tick_hist.snapshot(),
        "overruns": robot.loop_overruns,
        "rt_ok": robot.rt_ok,
    }), flush=True)
    stop.set()


async def run(cfg: BodyConfig, sim: bool, jitter_seconds: float | None = None) -> None:
    pinned = (not sim) and pin_cpu(cfg.rt)  # before any thread starts, so all of them inherit it
    if not sim:
        set_gil_interval(cfg.rt)
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
    latch = EStopLatch(cfg.estop_latch_path) if cfg.estop_latch_path else None
    robot = Robot(cfg, servos, lidar, camera, link, latch=latch)
    robot.kick = make_kick(None if sim else cfg.watchdog_gpio)
    if not robot.estop:
        # The SSC-32U keeps its last pulses when the previous process dies. Start from "no torque"
        # so the mode matches reality and a later stand cannot jump from an unknown pose.
        servos.relax()
    await link.start()
    # After link.start(): the MQTT thread already exists, so it stays out of the FIFO class.
    robot.rt_ok = bool(pinned) and (not sim) and enable_fifo(cfg.rt)

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
    if jitter_seconds is not None:
        tasks.append(asyncio.create_task(jitter_report(robot, jitter_seconds, stop), name="jitter"))
    # Freeze everything allocated at startup out of the garbage collector: a full collection
    # of numpy/cv2/paho objects takes ~40 ms on a Pi 4 (two missed control ticks).
    gc.collect()
    gc.freeze()
    gc.set_threshold(20000, 50, 100)  # rarer collections; everything long-lived is frozen above
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
    parser.add_argument("--jitter-seconds", type=float, default=None)
    parser.add_argument("--text-logs", action="store_true", help="human logs instead of JSON")
    args = parser.parse_args(argv)
    setup_logging(args.log_level, json_logs=not args.text_logs)
    cfg = load_config(args.config, args.calibration)
    asyncio.run(run(cfg, args.sim, args.jitter_seconds))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
