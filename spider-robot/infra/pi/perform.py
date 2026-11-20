"""Play one built-in move from the bench, or come back to the stand: table, wave, ... or stand.

Run it on the Pi like spider-robotctl (gateway venv and settings, SG_BENCH=1 on the gateway),
with the robot standing:

  sudo -u spider bash -c 'set -a; . /etc/spider/gateway.env; set +a; exec \
    /opt/spider/spider-robot/gateway/.venv/bin/python -I \
    /opt/spider/spider-robot/infra/pi/perform.py table'

It keeps the bench source alive until the body says the move is over (a quiet source would make
the gateway stop the robot halfway) and prints what the body said. "stand" brings a held pose
(table, or a move stopped halfway) back to the normal stand. Ctrl+C sends Stop: the robot then
holds where it is until "stand".
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from spider_common.link import MqttLink
from spider_common.protocol import MOVE_NAMES, Heartbeat, Perform, Posture, RobotEvent, Stop

from spider_gateway.console import BENCH_SOURCE, Console, _settings

WAIT_S = 25.0  # the longest move is 20 s; the way back from a held pose is under 10 s
_ENDS = {"perform_done", "perform_rejected", "rejected", "preempted", "link_lost", "estop",
         "obstacle_stop", "tilt", "fallen", "error"}


async def play(console: Console, name: str, speed: float, wait_s: float = WAIT_S) -> str:
    events = console.topics.source_event(console.source)
    console.send(Heartbeat())
    if name == "stand":
        seq = console.send(Posture(posture="stand"))
    else:
        seq = console.send(Perform(name=name, speed=speed))
    started: list[bool] = []

    def check(msg):
        if msg.topic != events:
            return None
        ev = RobotEvent.model_validate_json(msg.payload)
        if ev.seq != seq:
            return None
        if ev.kind == "perform_started":
            started.append(True)
            print(f"perform_started: {ev.detail}", flush=True)
            return None
        if ev.kind == "ack" and name == "stand" and "first" not in ev.detail:
            return f"ack: {ev.detail}"  # not holding anything: a plain stand
        return f"{ev.kind}: {ev.detail}" if ev.kind in _ENDS else None

    beat = asyncio.create_task(console._beat_for(wait_s))
    finished = False
    try:
        result = await console.wait_for(check, wait_s)
        finished = result is not None
        if name == "stand" and finished and result.startswith("ack"):
            await asyncio.sleep(3.0)  # the plain stand ramps; keep the source alive meanwhile
        return result or "no answer from the robot"
    finally:
        beat.cancel()
        if not finished:
            console.send(Stop())


async def run(name: str, speed: float) -> int:
    robot_id = os.environ.get("SG_ROBOT_ID", "spider-01")
    link = MqttLink(_settings(), Console.subscriptions(robot_id, BENCH_SOURCE))
    console = Console(link, robot_id, BENCH_SOURCE)
    await link.start()
    await asyncio.wait_for(link.connected.wait(), 8.0)
    await asyncio.sleep(0.2)
    try:
        result = await play(console, name, speed)
        print(result)
        await asyncio.sleep(0.2)  # let QoS 1 complete
    finally:
        await link.stop()
    return 0 if result.split(":")[0] in ("perform_done", "ack") else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="perform.py", description=__doc__.split("\n")[0])
    p.add_argument("name", help="a move (" + ", ".join(MOVE_NAMES) + ") or stand")
    p.add_argument("--speed", type=float, default=0.5, help="0 < speed <= 1 (default 0.5)")
    args = p.parse_args(argv)
    if args.name != "stand" and args.name not in MOVE_NAMES:
        p.error(f"unknown move {args.name!r}")
    if not 0.0 < args.speed <= 1.0:
        p.error("--speed must be greater than 0 and at most 1")
    return asyncio.run(run(args.name, args.speed))


if __name__ == "__main__":
    sys.exit(main())
