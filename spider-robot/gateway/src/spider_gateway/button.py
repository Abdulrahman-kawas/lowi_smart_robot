"""spider-button: the physical E-stop release, for when there is no network at all.

The E-stop latch survives a reboot, voice may never release it, and every other release path goes
through the network. A person standing at the robot holds this button for three seconds instead.
It publishes one EStopRelease on its own gateway source, which the broker ACL gives to this client
alone, and the gateway accepts nothing else from it.
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import logging
import os
import time
import uuid
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Protocol

from spider_common.link import Link, MqttLink, MqttSettings
from spider_common.obs import setup_logging
from spider_common.protocol import EStopRelease, Topics

from .gateway import BUTTON_SOURCE

log = logging.getLogger("spider_button")
HOLD_S = 3.0
POLL_S = 0.05


class HoldDetector:
    """True once per press, at the moment it has been held continuously for hold_s."""

    def __init__(self, hold_s: float = HOLD_S) -> None:
        self.hold_s = hold_s
        self._since: float | None = None
        self._fired = False

    def update(self, pressed: bool, now: float) -> bool:
        if not pressed:
            self._since, self._fired = None, False
            return False
        if self._since is None:
            self._since = now
        if not self._fired and now - self._since >= self.hold_s:
            self._fired = True
            return True
        return False


class Button(Protocol):
    def pressed(self) -> bool: ...


class GpioButton:
    """libgpiod v2 input, active low with the internal pull-up: the button shorts the pin to GND."""

    def __init__(self, chip: str, line: int) -> None:
        import gpiod
        from gpiod.line import Bias, Direction

        self.line = line
        self.request = gpiod.request_lines(
            chip, consumer="spider-button",
            config={line: gpiod.LineSettings(
                direction=Direction.INPUT, bias=Bias.PULL_UP, active_low=True,
                debounce_period=timedelta(milliseconds=20),
            )},
        )

    def pressed(self) -> bool:
        from gpiod.line import Value

        return self.request.get_value(self.line) == Value.ACTIVE


def send_release(link: Link, topics: Topics, session: str, seq: int) -> bool:
    release = EStopRelease(session=session, seq=seq, ts=time.time())
    return link.publish(topics.request(BUTTON_SOURCE), release.model_dump_json(), qos=1)


async def run_loop(
    button: Button, link: Link, robot_id: str, clock: Callable[[], float] = time.monotonic,
    poll_s: float = POLL_S,
) -> None:
    topics = Topics(robot_id)
    detector = HoldDetector()
    session = uuid.uuid4().hex[:12]
    seq = itertools.count(1)
    while True:
        if detector.update(button.pressed(), clock()):
            sent = send_release(link, topics, session, next(seq))
            log.warning("release button held: %s", "sent" if sent else "broker not connected")
        await asyncio.sleep(poll_s)


def _settings() -> MqttSettings:
    env = os.environ.get
    secret = env("SB_MQTT_PASSWORD_FILE")
    return MqttSettings(
        host=env("SG_MQTT_HOST", "127.0.0.1"), port=int(env("SG_MQTT_PORT", "1883")),
        client_id="spider-button", tls=False, username=env("SB_MQTT_USERNAME", "spider-button"),
        password=Path(secret).read_text("utf-8").strip() if secret else None, reconnect_max_s=2,
    )


async def _run() -> None:
    link = MqttLink(_settings(), [])
    button = GpioButton(
        os.environ.get("SB_BUTTON_CHIP", "/dev/gpiochip0"),
        int(os.environ.get("SB_BUTTON_LINE", "27")),
    )
    await link.start()
    try:
        await run_loop(button, link, os.environ.get("SG_ROBOT_ID", "spider-01"))
    finally:
        await link.stop()


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(prog="spider-button").parse_args(argv)
    setup_logging(os.environ.get("SG_LOG_LEVEL", "INFO"), service="spider-button")
    asyncio.run(_run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
