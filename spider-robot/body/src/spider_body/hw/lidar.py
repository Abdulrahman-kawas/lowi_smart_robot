"""Unitree L2 LiDAR: point clouds arrive from the C++ lidar_bridge over ZeroMQ.

lidar_bridge (C++, uses Unitree's unilidar_sdk2) publishes multipart messages:
  [b"cloud", struct "<dII" (stamp, id, n), float32[n*4] (x, y, z, intensity)]
  [b"imu",   struct "<d"   (stamp),         float32[10] (quat xyzw, gyro xyz, accel xyz)]

Python turns each cloud into a small polar "sector map": for each 10 deg sector around the
robot, the distance to the nearest obstacle between z_min and z_max above the ground. That map
drives the on-board safety reflex and is the only LiDAR data sent to the cloud (raw clouds are
far too big for MQTT).

The front camera sits in front of the L2 and above its centre, so some beams hit it. Along those
beams the L2 sees nothing else, only the camera and ghost returns off its edges, so
lidar.camera_window drops them near the L2. Beams below and beside it are untouched.
"""

from __future__ import annotations

import asyncio
import logging
import math
import struct
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
from spider_common.protocol import LidarSummary

from ..config import LidarCfg

log = logging.getLogger(__name__)


class LidarSource(Protocol):
    def latest(self) -> tuple[LidarSummary | None, float | None]:
        """(summary, age in seconds) or (None, None) before the first cloud."""

    def tilt(self) -> tuple[float | None, float | None]:
        """(roll_deg, pitch_deg) from the LiDAR's IMU, or (None, None) if unknown/stale."""

    def set_height_offset(self, dz: float) -> None:
        """Body height minus the standing height (the LiDAR moves up/down with the body)."""

    async def run(self) -> None: ...


class LidarProcessor:
    """Point cloud -> 36-sector map of the nearest obstacle (distance from the LiDAR centre).

    Points inside the robot's own footprint box (its legs) are ignored. Anything outside the
    box, however close, is kept: the safety layer measures from the box edge. The one other
    exception is the camera window (module docstring).
    """

    def __init__(self, cfg: LidarCfg, footprint: tuple[float, float] = (0.24, 0.27)) -> None:
        self.cfg = cfg
        self.footprint = footprint
        self.height_offset = 0.0
        self.sector_deg = 360.0 / cfg.sectors
        yaw = math.radians(cfg.mount_yaw_deg)
        self._c, self._s = math.cos(yaw), math.sin(yaw)

    def process(self, pts: np.ndarray, ts: float) -> LidarSummary:
        """One cloud to one sector map. LidarFeed merges recent clouds, because one can miss."""
        c = self.cfg
        fx, fy = self.footprint
        x0, y0, z0 = pts[:, 0], pts[:, 1], pts[:, 2]
        if c.imu_upside_down:  # hung upside down: 180 deg about x, the same flip as the IMU's
            y0, z0 = -y0, -z0
        z = z0 + c.mount_height_m + self.height_offset
        x = self._c * x0 - self._s * y0
        y = self._s * x0 + self._c * y0
        r = np.hypot(x, y)
        inside_robot = (np.abs(x) < fx) & (np.abs(y) < fy)
        mask = (
            np.isfinite(r)
            & (z >= c.z_min_m)
            & (z <= c.z_max_m)
            & ~inside_robot
            & (r <= c.max_range_m)
        )
        w = c.camera_window
        if w is not None:  # beams that hit the camera, near the L2
            bearing = np.degrees(np.arctan2(y, x))
            elevation = np.degrees(np.arctan2(z0, r))
            mask &= ~(
                (bearing >= w.bearing_min_deg) & (bearing <= w.bearing_max_deg)
                & (elevation >= w.elevation_min_deg) & (elevation <= w.elevation_max_deg)
                & (r <= w.max_range_m)
            )
        sectors = np.full(c.sectors, c.max_range_m, dtype=np.float64)
        if mask.any():
            ang = np.degrees(np.arctan2(y[mask], x[mask]))
            idx = np.floor(((ang + self.sector_deg / 2) % 360.0) / self.sector_deg).astype(int)
            np.minimum.at(sectors, idx % c.sectors, r[mask])
        i = int(np.argmin(sectors))
        bearing = i * self.sector_deg
        return LidarSummary(
            ts=ts,
            sector_deg=self.sector_deg,
            sectors_m=[round(float(v), 3) for v in sectors],
            nearest_m=round(float(sectors[i]), 3),
            nearest_bearing_deg=bearing if bearing <= 180 else bearing - 360,
            points=int(mask.sum()),
        )


class LidarFeed:
    """Subscribes to lidar_bridge and keeps the latest sector map and tilt."""

    def __init__(
        self, cfg: LidarCfg, footprint: tuple[float, float] = (0.24, 0.27),
        imu_timeout_s: float = 0.3,
    ) -> None:
        self.cfg = cfg
        self.proc = LidarProcessor(cfg, footprint)
        yaw = math.radians(cfg.mount_yaw_deg)
        self._c, self._s = math.cos(yaw), math.sin(yaw)
        self.imu_timeout_s = imu_timeout_s
        self._summary: LidarSummary | None = None
        self._rx: float | None = None
        self._roll: float | None = None
        self._pitch: float | None = None
        self._imu_rx: float | None = None
        self._history: deque[list[float]] = deque(maxlen=cfg.history_clouds)

    def latest(self) -> tuple[LidarSummary | None, float | None]:
        if self._summary is None or self._rx is None:
            return None, None
        return self._summary, time.monotonic() - self._rx

    def _merge(self, summary: LidarSummary) -> LidarSummary:
        """Nearest return per sector over the last few clouds; one cloud can miss sectors."""
        self._history.append(summary.sectors_m)
        if len(self._history) == 1:
            return summary
        merged = np.min(np.array(self._history, dtype=np.float64), axis=0)
        i = int(np.argmin(merged))
        bearing = i * summary.sector_deg
        return summary.model_copy(update={
            "sectors_m": [round(float(v), 3) for v in merged],
            "nearest_m": round(float(merged[i]), 3),
            "nearest_bearing_deg": bearing if bearing <= 180 else bearing - 360,
        })

    def tilt(self) -> tuple[float | None, float | None]:
        if self._imu_rx is None or time.monotonic() - self._imu_rx > self.imu_timeout_s:
            return None, None  # bridge dead or IMU silent: tilt is unknown, not "level"
        return self._roll, self._pitch

    def set_height_offset(self, dz: float) -> None:
        self.proc.height_offset = dz

    def handle(self, parts: list[bytes]) -> None:
        if len(parts) != 3:
            return
        if parts[0] == b"cloud":
            _stamp, _cid, n = struct.unpack("<dII", parts[1])
            pts = np.frombuffer(parts[2], dtype="<f4")
            if pts.size != n * 4:
                log.warning("cloud size mismatch: header %d, payload %d floats", n, pts.size)
                return
            self._summary = self._merge(self.proc.process(pts.reshape(-1, 4), time.time()))
            self._rx = time.monotonic()
        elif parts[0] == b"imu":
            d = np.frombuffer(parts[2], dtype="<f4")
            if d.size != 10:
                return
            ax, ay, az = float(d[7]), float(d[8]), float(d[9])
            if self.cfg.imu_upside_down:  # rotated 180 deg about x: y and z flip
                ay, az = -ay, -az
            # into the robot's frame like the points, so a turned L2 still reads nose down as
            # nose down (at 180 deg both signs flipped; at 90 roll and pitch swapped)
            ax, ay = self._c * ax - self._s * ay, self._s * ax + self._c * ay
            roll = math.degrees(math.atan2(ay, az))
            pitch = math.degrees(math.atan2(-ax, math.hypot(ay, az)))
            a = 0.2  # low-pass: footsteps shake the IMU
            self._roll = roll if self._roll is None else (1 - a) * self._roll + a * roll
            self._pitch = pitch if self._pitch is None else (1 - a) * self._pitch + a * pitch
            self._imu_rx = time.monotonic()

    async def run(self) -> None:
        import zmq
        import zmq.asyncio

        ctx = zmq.asyncio.Context.instance()
        sock = ctx.socket(zmq.SUB)
        sock.setsockopt(zmq.RCVHWM, 8)  # small, but IMU and clouds share it: 2 could drop clouds
        sock.setsockopt(zmq.SUBSCRIBE, b"")
        sock.connect(self.cfg.endpoint)
        log.info("LiDAR feed listening on %s", self.cfg.endpoint)
        while True:
            parts = await sock.recv_multipart()
            try:
                self.handle(parts)
            except Exception:  # a bad frame must never kill the safety loop
                log.exception("bad lidar frame")


# --------------------------------------------------------------------------- simulation
@dataclass
class SimWorld:
    """A 4 m x 4 m room with round obstacles. The robot pose integrates the effective twist."""

    half_size: float = 2.0
    obstacles: list[tuple[float, float, float]] = field(
        default_factory=lambda: [(1.2, 0.0, 0.15), (-0.8, 1.0, 0.25)]
    )
    x: float = 0.0
    y: float = 0.0
    yaw: float = 0.0

    def integrate(self, vx: float, vy: float, wz: float, dt: float) -> None:
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        self.x += (c * vx - s * vy) * dt
        self.y += (s * vx + c * vy) * dt
        self.yaw = (self.yaw + wz * dt + math.pi) % (2 * math.pi) - math.pi

    def ray(self, angle: float, max_range: float) -> float:
        dx, dy = math.cos(angle), math.sin(angle)
        best = max_range
        h = self.half_size
        for t in (
            (h - self.x) / dx if dx > 1e-9 else math.inf,
            (-h - self.x) / dx if dx < -1e-9 else math.inf,
            (h - self.y) / dy if dy > 1e-9 else math.inf,
            (-h - self.y) / dy if dy < -1e-9 else math.inf,
        ):
            if 0 < t < best:
                best = t
        for ox, oy, rad in self.obstacles:
            fx, fy = self.x - ox, self.y - oy
            b = fx * dx + fy * dy
            cc = fx * fx + fy * fy - rad * rad
            disc = b * b - cc
            if disc >= 0:
                t = -b - math.sqrt(disc)
                if 0 < t < best:
                    best = t
        return best


class SimLidar:
    def __init__(self, cfg: LidarCfg, world: SimWorld, clock=time.monotonic) -> None:
        self.cfg, self.world, self.clock = cfg, world, clock
        self.sector_deg = 360.0 / cfg.sectors
        self._summary: LidarSummary | None = None
        self._rx: float | None = None

    def scan(self) -> None:
        sectors = [
            round(self.world.ray(self.world.yaw + math.radians(i * self.sector_deg),
                                 self.cfg.max_range_m), 3)
            for i in range(self.cfg.sectors)
        ]
        i = min(range(len(sectors)), key=sectors.__getitem__)
        bearing = i * self.sector_deg
        self._summary = LidarSummary(
            ts=time.time(), sector_deg=self.sector_deg, sectors_m=sectors,
            nearest_m=sectors[i], nearest_bearing_deg=bearing if bearing <= 180 else bearing - 360,
            points=len(sectors),
        )
        self._rx = self.clock()

    def latest(self) -> tuple[LidarSummary | None, float | None]:
        if self._summary is None or self._rx is None:
            return None, None
        return self._summary, self.clock() - self._rx

    def tilt(self) -> tuple[float | None, float | None]:
        return 0.0, 0.0

    def set_height_offset(self, dz: float) -> None:
        pass

    async def run(self) -> None:
        while True:
            self.scan()
            await asyncio.sleep(0.1)


class NoLidar:
    def latest(self) -> tuple[LidarSummary | None, float | None]:
        return None, None

    def tilt(self) -> tuple[float | None, float | None]:
        return None, None

    def set_height_offset(self, dz: float) -> None:
        pass

    async def run(self) -> None:
        await asyncio.Event().wait()
