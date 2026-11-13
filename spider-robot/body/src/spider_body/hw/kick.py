"""The kick line for the external hardware watchdog.

The SSC-32U keeps its last pulses forever, so if the Pi hangs the servos hold torque with nothing in
charge. A retriggerable timer on the relay board keeps servo power on only while this pin toggles.
"""

from __future__ import annotations

from typing import Protocol

from ..config import WatchdogGpioCfg


class Kick(Protocol):
    def toggle(self) -> None: ...


class NoKick:
    def toggle(self) -> None:
        pass


class GpioKick:
    """libgpiod v2 line. One ioctl per tick; a failure here counts as a failed tick."""

    def __init__(self, cfg: WatchdogGpioCfg, request=None) -> None:
        self.line = cfg.line
        self._high = False
        if request is None:
            import gpiod
            from gpiod.line import Direction

            request = gpiod.request_lines(
                cfg.chip, consumer="spider-body",
                config={cfg.line: gpiod.LineSettings(direction=Direction.OUTPUT)},
            )
        self.request = request

    def toggle(self) -> None:
        from gpiod.line import Value

        self._high = not self._high
        self.request.set_value(self.line, Value.ACTIVE if self._high else Value.INACTIVE)


def make_kick(cfg: WatchdogGpioCfg | None) -> Kick:
    return NoKick() if cfg is None else GpioKick(cfg)
