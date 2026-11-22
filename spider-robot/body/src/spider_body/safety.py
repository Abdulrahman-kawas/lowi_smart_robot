"""On-board safety reflexes. They run on the Pi at 50 Hz and never wait for the cloud.

All distances are measured from the EDGE of the robot's footprint box (legs included), not
from the LiDAR centre, so a "0.15 m stop distance" really means 15 cm between the leg tips
and the obstacle.

1. Corridor reflex : the robot sweeps a corridor as wide as its footprint (+ margin) in the
                     direction of travel. An obstacle in that corridor closer than
                     stop_distance cancels the move; closer than slow_distance scales speed.
2. Turn reflex     : no turning in place when anything is inside the swept turning circle
                     (footprint corner radius) + turn_clearance.
3. LiDAR stale     : no motion if the map is older than lidar_timeout (unless require_lidar is
                     false, for bench tests on a stand). Unknown tilt (stale IMU) also blocks.
4. Tilt            : stop walking past max_tilt; relax the servos past fall_tilt. A walk
                     also stops on a lean past walk_tilt that lasts walk_tilt_s (robot.py).
(The link watchdog, command fencing and level-body checks live in robot.py.)
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from spider_common.protocol import LidarSummary

from .config import SafetyCfg

log = logging.getLogger(__name__)

TiltState = Literal["ok", "tilt", "fallen"]


class EStopLatch:
    """An E-stop that survives a crash, a restart and a reboot. File present = latched.

    set() returns at once; the disk write and fsync happen on a short-lived thread so a slow SD
    card can never stall the control loop. Only the newest value is written.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._want: bool | None = None
        self._thread: threading.Thread | None = None
        self.write_failed = False  # read by the control tick, which emits the error event

    def read(self) -> bool:
        return self.path.exists()

    def set(self, latched: bool) -> None:
        with self._lock:
            self._want = latched
        thread = threading.Thread(target=self._flush, name="estop-latch", daemon=True)
        thread.start()
        self._thread = thread

    def wait(self, timeout_s: float = 2.0) -> None:
        if self._thread is not None:
            self._thread.join(timeout_s)

    def _flush(self) -> None:
        with self._lock:
            want, self._want = self._want, None
            if want is None:
                return
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if want:
                    tmp = self.path.with_suffix(".tmp")
                    with tmp.open("w", encoding="utf-8") as f:
                        f.write(str(time.time()))
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp, self.path)
                else:
                    self.path.unlink(missing_ok=True)
                fd = os.open(self.path.parent, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
                self.write_failed = False
            except OSError:
                self.write_failed = True
                log.exception("could not persist the E-stop latch at %s", self.path)


@dataclass(frozen=True)
class Limited:
    vx: float
    vy: float
    wz: float
    reason: str | None  # None = not limited


def corridor_clearance(
    lidar: LidarSummary, bearing_deg: float, footprint: tuple[float, float], margin: float
) -> float:
    """Free distance ahead of the footprint edge inside the swept corridor.

    The footprint box (half-extents fx, fy) moving along `bearing_deg` sweeps a corridor of
    half-width = box support perpendicular to the motion (+ margin). Each sector's nearest
    point is projected onto the motion direction; points inside the corridor count.
    """
    fx, fy = footprint
    b = math.radians(bearing_deg)
    ux, uy = math.cos(b), math.sin(b)
    front = abs(ux) * fx + abs(uy) * fy  # box support along the motion
    half_width = abs(uy) * fx + abs(ux) * fy + margin  # box support across the motion
    best = math.inf
    for i, d in enumerate(lidar.sectors_m):
        a = math.radians(i * lidar.sector_deg)
        px, py = d * math.cos(a), d * math.sin(a)
        along = px * ux + py * uy
        across = -px * uy + py * ux
        if along > 0 and abs(across) <= half_width:
            best = min(best, along - front)
    return best


class SafetyGuard:
    def __init__(self, cfg: SafetyCfg, footprint: tuple[float, float]) -> None:
        self.cfg = cfg
        self.footprint = footprint
        self.turn_radius = math.hypot(*footprint) + cfg.turn_clearance_m

    def limit_motion(
        self,
        vx: float,
        vy: float,
        wz: float,
        lidar: LidarSummary | None,
        lidar_age_s: float | None,
    ) -> Limited:
        c = self.cfg
        reason: str | None = None
        fresh = lidar is not None and lidar_age_s is not None and lidar_age_s <= c.lidar_timeout_s

        if math.hypot(vx, vy) > 1e-4:
            if not fresh:
                if c.require_lidar:
                    return Limited(0.0, 0.0, 0.0, "lidar_stale")
            else:
                assert lidar is not None
                bearing = math.degrees(math.atan2(vy, vx))
                free = corridor_clearance(lidar, bearing, self.footprint, c.corridor_margin_m)
                if free <= c.stop_distance_m:
                    vx, vy = 0.0, 0.0
                    reason = f"obstacle {max(free, 0.0):.2f} m from the legs at {bearing:.0f} deg"
                elif free < c.slow_distance_m:
                    k = (free - c.stop_distance_m) / (c.slow_distance_m - c.stop_distance_m)
                    k = max(0.25, k)  # keep creeping so the stop distance is really reached
                    vx, vy, reason = vx * k, vy * k, f"slowing: obstacle {free:.2f} m from the legs"

        if abs(wz) > 1e-4:
            if not fresh:
                if c.require_lidar:
                    return Limited(vx, vy, 0.0, "lidar_stale")
            elif lidar is not None and lidar.nearest_m < self.turn_radius:
                wz = 0.0
                reason = (f"too close to turn: {lidar.nearest_m:.2f} m "
                          f"< {self.turn_radius:.2f} m turning circle")

        return Limited(vx, vy, wz, reason)

    def tilt_state(self, roll_deg: float | None, pitch_deg: float | None) -> TiltState:
        if roll_deg is None or pitch_deg is None:
            return "ok"  # unknown tilt is handled in robot.py (blocks motion)
        worst = max(abs(roll_deg), abs(pitch_deg))
        if worst >= self.cfg.fall_tilt_deg:
            return "fallen"
        if worst >= self.cfg.max_tilt_deg:
            return "tilt"
        return "ok"
