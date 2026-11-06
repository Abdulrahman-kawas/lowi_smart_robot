"""spider-brain CLI.

  spider-brain status                          print robot status once
  spider-brain teleop                          drive by hand (line commands)
  spider-brain ping --n 100                    command round-trip latency (p50/p95)
  spider-brain look "what is in front?"        photo + Liquid vision answer
  spider-brain run "walk to the orange box"    autonomous task with the dashboard
      --tier simple|default (simple = cheap model, escalates when needed)
  spider-brain serve                           long-running brain: dashboard + Telegram bot +
                                               WhatsApp alerts + memory + skills + voice
      --planner claude|liquid --autonomy supervised|guarded|autonomous
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import math
import sys
import time
from pathlib import Path

from pydantic import ValidationError

from .config import Settings
from .robot_client import RobotClient, RobotOffline
from .runner import build_link, run_task
from .vision import VisionClient

TELEOP_HELP = """commands (then Enter):
  w/s/a/d [sec]  forward/back/left/right (default 1 s)   q/e [sec]  turn left/right
  x stop | stand | sit | relax | estop | release | status | scan | photo [question] | quit"""


async def _connect(settings: Settings, role: str) -> tuple[RobotClient, list[asyncio.Task]]:
    link = build_link(settings, role)
    robot = RobotClient(link, settings.robot_id)
    await link.start()
    tasks = [asyncio.create_task(robot.run()),
             asyncio.create_task(robot.heartbeat_loop(settings.heartbeat_hz))]
    if not await robot.wait_online(settings.online_timeout_s):
        raise RobotOffline("no telemetry: is spider-body running and connected?")
    return robot, tasks


async def _status(settings: Settings) -> int:
    robot, tasks = await _connect(settings, "status")
    print(robot.status_text())
    for t in tasks:
        t.cancel()
    return 0


async def _photo(robot: RobotClient, settings: Settings, question: str | None) -> None:
    jpeg = await robot.snapshot()
    out = Path("photos") / time.strftime("%Y%m%d-%H%M%S.jpg")
    out.parent.mkdir(exist_ok=True)
    out.write_bytes(jpeg)
    print(f"saved {out} ({len(jpeg)} bytes)")
    if question:
        vision = VisionClient(settings.vision_url, settings.vision_model, settings.vision_timeout_s)
        try:
            print("vision:", await vision.ask(jpeg, question))
        finally:
            await vision.aclose()


async def _look(settings: Settings, question: str) -> int:
    robot, tasks = await _connect(settings, "look")
    await _photo(robot, settings, question)
    for t in tasks:
        t.cancel()
    return 0


async def _ping(settings: Settings, n: int) -> int:
    """Command round-trip latency (brain -> broker -> body -> ack -> brain), one clock."""
    robot, tasks = await _connect(settings, "ping")
    rtts = sorted(await robot.ping(n))
    for t in tasks:
        t.cancel()
    if not rtts:
        print("no acks received")
        return 1
    def pct(p: float) -> float:
        return rtts[min(len(rtts) - 1, int(p * len(rtts)))]
    print(f"acks {len(rtts)}/{n}  p50 {pct(0.5):.0f} ms  p95 {pct(0.95):.0f} ms  "
          f"max {rtts[-1]:.0f} ms")
    return 0


async def _teleop(settings: Settings) -> int:
    robot, tasks = await _connect(settings, "teleop")
    print(TELEOP_HELP)
    v, wz = settings.walk_speed_normal, math.radians(settings.turn_speed_dps)
    moves = {"w": (v, 0, 0), "s": (-v, 0, 0), "a": (0, v, 0), "d": (0, -v, 0),
             "q": (0, 0, wz), "e": (0, 0, -wz)}
    try:
        while True:
            line = (await asyncio.to_thread(input, "> ")).strip()
            if not line:
                continue
            word, _, rest = line.partition(" ")
            if word in moves:
                secs = float(rest) if rest else 1.0
                robot.move(*moves[word], duration_s=max(0.2, min(5.0, secs)), gait=settings.gait)
            elif word == "x":
                robot.stop()
            elif word in ("stand", "sit", "relax"):
                print(await robot.posture(word))
            elif word == "estop":
                robot.estop()
            elif word == "release":
                robot.estop_release()
            elif word == "status":
                print(robot.status_text())
            elif word == "scan":
                print(robot.surroundings_text())
            elif word == "photo":
                await _photo(robot, settings, rest or None)
            elif word in ("quit", "exit"):
                break
            else:
                print(TELEOP_HELP)
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        robot.stop()
        await asyncio.sleep(0.3)
        for t in tasks:
            t.cancel()
    return 0


async def _serve(settings: Settings) -> int:
    import signal

    from .service import BrainService

    svc = BrainService(settings)
    await svc.start()
    print(f"spider-brain serving robot {settings.robot_id}: "
          f"telegram={'on' if svc.telegram else 'off'}, "
          f"whatsapp={'on' if svc.whatsapp else 'off'}, voice={'on' if svc.voice else 'off'}, "
          f"skills={len(svc.skills.skills)}, memory={len(svc.memory.facts)} facts")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    await svc.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="spider-brain")
    sub = p.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="autonomous task")
    run.add_argument("task")
    run.add_argument("--planner", choices=["claude", "liquid"])
    run.add_argument("--autonomy", choices=["autonomous", "guarded", "supervised"])
    run.add_argument("--model")
    run.add_argument("--max-steps", type=int)
    run.add_argument("--no-dashboard", action="store_true")
    run.add_argument("--tier", choices=["simple", "default"], default="default")
    sub.add_parser("serve", help="long-running brain (dashboard, Telegram, alerts)")
    sub.add_parser("status")
    sub.add_parser("teleop")
    ping = sub.add_parser("ping", help="measure command round-trip latency")
    ping.add_argument("--n", type=int, default=100)
    look = sub.add_parser("look")
    look.add_argument("question")
    p.add_argument("--log-level", default="WARNING")
    args = p.parse_args(argv)
    logging.basicConfig(
        level=args.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    overrides: dict = {}
    if args.command == "run":
        for field in ("planner", "autonomy"):
            if getattr(args, field):
                overrides[field] = getattr(args, field)
        if args.model:
            overrides["route_default"] = f"anthropic:{args.model}"
            overrides["route_simple"] = f"anthropic:{args.model}"
        if args.max_steps:
            overrides["max_steps"] = args.max_steps
        if args.no_dashboard:
            overrides["dashboard"] = False
    try:
        settings = Settings(**overrides)
    except ValidationError as exc:
        for err in exc.errors():
            print(f"config error: {err['msg']}", file=sys.stderr)
        return 2

    try:
        if args.command == "status":
            return asyncio.run(_status(settings))
        if args.command == "teleop":
            return asyncio.run(_teleop(settings))
        if args.command == "ping":
            return asyncio.run(_ping(settings, args.n))
        if args.command == "look":
            return asyncio.run(_look(settings, args.question))
        if args.command == "serve":
            return asyncio.run(_serve(settings))
        if settings.planner == "claude" and not settings.anthropic_api_key:
            print("ANTHROPIC_API_KEY is not set (or use --planner liquid).", file=sys.stderr)
            return 2
        print(f"Task: {args.task}\nplanner={settings.planner} autonomy={settings.autonomy}")
        with contextlib.suppress(KeyboardInterrupt):
            summary = asyncio.run(run_task(args.task, settings, tier=args.tier))
            print("\n=== Summary ===\n" + summary)
        return 0
    except RobotOffline as exc:
        print(f"robot offline: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
