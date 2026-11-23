"""Stand the robot higher or lower: one BodyPose on the bench source.

Run it on the Pi like spider-robotctl (gateway venv and settings, SG_BENCH=1 on the gateway),
with the robot standing:

  sudo -u spider bash -c 'set -a; . /etc/spider/gateway.env; set +a; exec \
    /opt/spider/spider-robot/gateway/.venv/bin/python -I \
    /opt/spider/spider-robot/infra/pi/body_height.py 0.12'

The height is ground to the coxa joints, in metres. The normal stand is geometry.body_height_m
(0.09); the body accepts from just above the sit height up to the stand height + 4 cm and limits
anything outside that. The robot walks at the new height; "spider-robotctl bench stand" brings it
back to the normal stand. Expressive moves need the normal stand height.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from spider_common.link import MqttLink
from spider_common.protocol import BodyPose, Heartbeat, RobotEvent

from spider_gateway.console import BENCH_SOURCE, Console, _settings

RAMP_S = 3.0  # keep the bench source alive while the height changes (4 cm/s, at most 4 cm)


async def set_height(console: Console, height_m: float, pitch_deg: float = 0.0,
                     ramp_s: float = RAMP_S) -> str:
    """Send the pose, wait for the body's answer, and keep the source alive during the ramp:
    if the source went quiet, the gateway would stop the robot and the height would end halfway.
    """
    events = console.topics.source_event(console.source)
    console.send(Heartbeat())
    seq = console.send(BodyPose(height_m=height_m, pitch_deg=pitch_deg))

    def answer(msg):
        if msg.topic != events:
            return None
        ev = RobotEvent.model_validate_json(msg.payload)
        if ev.seq == seq and ev.kind in ("ack", "rejected"):
            return f"{ev.kind}: {ev.detail}"
        return None

    beat = asyncio.create_task(console._beat_for(ramp_s))
    try:
        result = await console.wait_for(answer, 3.0) or "no answer from the robot"
        if result.startswith("ack"):
            await beat
        return result
    finally:
        beat.cancel()


async def run(height_m: float, pitch_deg: float) -> int:
    robot_id = os.environ.get("SG_ROBOT_ID", "spider-01")
    link = MqttLink(_settings(), Console.subscriptions(robot_id, BENCH_SOURCE))
    console = Console(link, robot_id, BENCH_SOURCE)
    await link.start()
    await asyncio.wait_for(link.connected.wait(), 8.0)
    await asyncio.sleep(0.2)
    try:
        result = await set_height(console, height_m, pitch_deg)
        print(result)
        await asyncio.sleep(0.2)  # let QoS 1 complete
    finally:
        await link.stop()
    return 0 if result.startswith("ack") else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="body_height.py", description=__doc__.split("\n")[0])
    p.add_argument("height_m", type=float, help="ground to coxa joints, m (normal stand 0.09)")
    p.add_argument("--pitch", type=float, default=0.0, help="nose up (+) or down, deg (+-20)")
    args = p.parse_args(argv)
    if not 0.03 <= args.height_m <= 0.20:
        p.error("height_m must be 0.03..0.20 (the body then limits it to what it can do)")
    if not -20.0 <= args.pitch <= 20.0:
        p.error("--pitch must be -20..20")
    return asyncio.run(run(args.height_m, args.pitch))


if __name__ == "__main__":
    sys.exit(main())
