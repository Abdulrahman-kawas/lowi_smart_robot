"""Dead-man driving: motion only while a finger or a stick is held on the phone.

The app renews a drive about every 0.4 s while it is held. Each renewal becomes one Move of at
most 1 s on the remote source, so the gateway's remote caps and the body's limits apply. The brain
does not trust the phone to stop:

  * no renewal for deadman_s (0.6 s) ends the hold and stops the robot
  * a socket that drops while its device drove in the last MOTION_TAIL_S stops the robot; a phone
    that was only watching stops nothing, so a flaky viewer cannot cancel a planner task
  * Stop or E-stop from any device stops the robot first and then ends every hold
  * a refusal, preemption or safety stop ends the hold. A held stick cannot restart the robot
    after someone at the robot said stop: the app has to lift and press again (a new hold_id)
  * one device drives at a time
"""

from __future__ import annotations

import math
import time
from collections import OrderedDict, defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

MIN_MOVE_GAP_S = 0.1  # at most 10 Moves a second toward the gateway
MOTION_TAIL_S = 1.5  # a Move sent this recently may still be running (1 s Move plus margin)
CENTRED = 0.02  # an input this small counts as zero
MAX_HOLD_ID = 64
# Events on the remote source that end a hold: someone else took over, or the robot stopped itself.
ENDS_HOLD = frozenset({"preempted", "estop", "tilt", "fallen", "link_lost", "obstacle_stop"})
STILL = (0.0, 0.0, 0.0)


class RobotLike(Protocol):
    def move(self, vx: float, vy: float, wz: float, duration_s: float, gait: str = "tripod",
             human: bool = False) -> int: ...

    def stop(self, human: bool = False) -> int: ...

    def cancel_motion(self) -> int: ...


@dataclass(frozen=True)
class Caps:
    max_speed_mps: float
    max_wz_rps: float
    move_s: float


def _fraction(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) \
            or not 0.0 < value <= 1.0:
        raise ValueError(f"{name} must be a number greater than 0 and at most 1")
    return float(value)


def scale(x: object, y: object, turn: object, caps: Caps, speed: object = 1.0,
          turn_speed: object = 1.0) -> tuple[float, float, float]:
    """App inputs (-1..1; x forward, y left, turn + = left) to velocities within the caps.

    speed and turn_speed are the app's walking and turning setting (Slow, Normal, Fast), each a
    fraction of the caps: 0 < f <= 1. An older app sends neither, which is 1.
    """
    walk, spin = _fraction(speed, "speed"), _fraction(turn_speed, "turn_speed")
    values = []
    for v in (x, y, turn):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError("drive values must be finite numbers")
        v = max(-1.0, min(1.0, float(v)))
        values.append(0.0 if abs(v) < CENTRED else v)
    x, y, turn = values
    r = math.hypot(x, y)
    if r > 1.0:
        x, y = x / r, y / r
    top = caps.max_speed_mps * walk
    vx, vy = x * top, y * top
    norm = math.hypot(vx, vy)
    if norm > top:  # float rounding: stay under the cap, or the gateway clamps
        k = top / norm * (1.0 - 1e-9)
        vx, vy = vx * k, vy * k
    return vx, vy, turn * caps.max_wz_rps * spin


@dataclass
class _Hold:
    device: str
    hold_id: str
    renewed: float
    want: tuple[float, float, float]
    sent: tuple[float, float, float] | None = None
    sent_at: float = -math.inf
    pending: bool = True


# notify(device or None for everyone, kind, detail, refusal, hold_id the event is about)
Notify = Callable[[str | None, str, str, bool, str | None], None]


class DriveControl:
    def __init__(
        self, robot: RobotLike, caps: Caps, deadman_s: float,
        preflight: Callable[[str], str | None], notify: Notify,
        clock: Callable[[], float] = time.monotonic, gait: str = "tripod",
    ) -> None:
        self.robot, self.caps, self.deadman_s = robot, caps, deadman_s
        self.preflight, self.notify, self.clock, self.gait = preflight, notify, clock, gait
        self.hold: _Hold | None = None
        self._ended: defaultdict[str, deque[str]] = defaultdict(lambda: deque(maxlen=32))
        self._last_motion: dict[str, float] = {}
        self._seqs: OrderedDict[int, float] = OrderedDict()  # Move seq -> sent at
        self.cmd_rtt_ms: float | None = None

    @property
    def holder(self) -> str | None:
        return self.hold.device if self.hold is not None else None

    def in_flight(self, device: str) -> bool:
        """A Move of this device may still be running on the robot."""
        return self.clock() - self._last_motion.get(device, -math.inf) < MOTION_TAIL_S

    # ------------------------------------------------------------------ from the app
    def drive(self, device: str, x: object, y: object, turn: object, hold_id: object,
              speed: object = 1.0, turn_speed: object = 1.0) -> None:
        if not isinstance(hold_id, str) or not 0 < len(hold_id) <= MAX_HOLD_ID:
            self.notify(device, "drive_refused", "a drive needs a hold_id", True, None)
            return
        if hold_id in self._ended[device]:
            return  # this press already ended and was reported once: lift and press again
        try:
            want = scale(x, y, turn, self.caps, speed, turn_speed)
        except ValueError as exc:
            self._refuse(device, hold_id, str(exc))
            return
        hold = self.hold
        if hold is not None and hold.device != device:
            self._refuse(device, hold_id, f"{hold.device} is driving")
            return
        if hold is not None and hold.hold_id != hold_id:  # a new press replaces the old one
            self._ended[device].append(hold.hold_id)
            self.hold = hold = None
        why = self.preflight(device)
        if why:
            if hold is not None:
                self._end(why, stop=True)
            else:
                self._refuse(device, hold_id, why)
            return
        now = self.clock()
        if hold is None:
            hold = self.hold = _Hold(device, hold_id, now, want)
        hold.renewed, hold.want, hold.pending = now, want, True
        self._flush(now)

    def stop_all(self, by: str) -> int:
        """Stop or E-stop from any device: the robot is stopped first, then every hold ends."""
        seq = self.robot.cancel_motion()
        if self.hold is not None:
            self._end(f"stopped by {by}", stop=False, refusal=False)
        return seq

    def disconnect(self, device: str) -> None:
        """The device's last socket closed."""
        if self.hold is not None and self.hold.device == device:
            self._end("the app disconnected", stop=True)
        elif self.in_flight(device):
            self.robot.cancel_motion()

    # ------------------------------------------------------------------ from the robot
    def on_event(self, kind: str, seq: int | None, detail: str) -> None:
        """An event the gateway sent to the remote source."""
        sent_at = self._seqs.get(seq) if seq is not None else None
        if kind == "ack" and sent_at is not None:
            self.cmd_rtt_ms = round((self.clock() - sent_at) * 1000.0, 1)
        if self.hold is None:
            return
        if kind == "rejected" and sent_at is not None:
            self._end(f"refused by the robot: {detail}", stop=False)
        elif kind in ENDS_HOLD:
            self._end(f"{kind}: {detail}".strip(": "), stop=False)

    def tick(self) -> None:
        hold = self.hold
        if hold is None:
            return
        now = self.clock()
        if now - hold.renewed > self.deadman_s:
            self._end(f"dead-man: no drive renewal for {self.deadman_s:g} s", stop=True)
            return
        why = self.preflight(hold.device)  # the frame can go stale while the stick is held
        if why:
            self._end(why, stop=True)
            return
        self._flush(now)

    # ------------------------------------------------------------------ inside
    def _flush(self, now: float) -> None:
        hold = self.hold
        if hold is None or not hold.pending or now - hold.sent_at < MIN_MOVE_GAP_S:
            return
        hold.pending, hold.sent_at = False, now
        if hold.want == STILL:  # finger down but centred: stand still, keep the hold
            if hold.sent not in (None, STILL):
                self.robot.stop(human=True)
            hold.sent = STILL
            return
        seq = self.robot.move(*hold.want, duration_s=self.caps.move_s, gait=self.gait, human=True)
        hold.sent = hold.want
        if seq < 0:
            self._end("the brain is not connected to the robot", stop=False)
            return
        self._last_motion[hold.device] = now
        self._seqs[seq] = now
        while len(self._seqs) > 256:
            self._seqs.popitem(last=False)

    def _end(self, why: str, stop: bool, refusal: bool = True) -> None:
        hold, self.hold = self.hold, None
        if hold is None:
            return
        self._ended[hold.device].append(hold.hold_id)
        if stop and self.in_flight(hold.device):
            self.robot.cancel_motion()
        self.notify(hold.device, "drive_ended", why, refusal, hold.hold_id)

    def _refuse(self, device: str, hold_id: str, why: str) -> None:
        self._ended[device].append(hold_id)
        self.notify(device, "drive_refused", why, True, hold_id)
