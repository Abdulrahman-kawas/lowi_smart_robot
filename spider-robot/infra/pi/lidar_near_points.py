"""Read-only: the raw L2 points near the robot, in the robot's frame, for a few seconds.

Run it on the Pi as the spider user with the body venv while spider-lidar runs. It only listens
to the bridge (a second subscriber); it sends nothing and moves nothing:

  sudo -u spider /opt/spider/spider-robot/body/.venv/bin/python -I \
    /opt/spider/spider-robot/infra/pi/lidar_near_points.py

It writes /tmp/lidar_near.csv and prints:
- per front sector, what sits just outside the footprint box the body ignores;
- the camera: the beams that hit it (everything within 0.35 m in front, above the L2's centre)
  and a lidar.camera_window for robot.yaml with a few degrees around them. Nothing else may
  be within 0.35 m in front while it runs. Run it at a few camera pans (spider-robotctl bench
  look) and take the widest window;
- anything 0.35-0.6 m in front below the camera: put a box straight ahead of the robot's nose to
  check lidar.mount_yaw_deg (its bearing should be 0).
It ignores lidar.camera_window: it shows what the L2 really sees.
"""

from __future__ import annotations

import argparse
import math
import struct
import sys
import time

import numpy as np
import zmq

from spider_body.config import load_config

CAMERA_R_M = 0.35  # the camera is closer than this; nothing else may be while it runs
MARGIN_DEG = 5.0  # around the camera's bearings
MARGIN_UP_DEG = 3.0  # below its lowest return: ghosts off its lower edge are already in


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("config", nargs="?", default="/etc/spider/robot.yaml")
    ap.add_argument("--seconds", type=float, default=3.0)
    ap.add_argument("--out", default="/tmp/lidar_near.csv")
    args = ap.parse_args()

    cfg = load_config(args.config)
    c, g = cfg.lidar, cfg.geometry
    fx, fy = g.footprint_x_m, g.footprint_y_m
    print(f"lidar: yaw {c.mount_yaw_deg}, height {c.mount_height_m}, upside_down "
          f"{c.imu_upside_down}, z band {c.z_min_m}..{c.z_max_m}; footprint +-{fx} x +-{fy}")

    sock = zmq.Context.instance().socket(zmq.SUB)
    sock.setsockopt(zmq.SUBSCRIBE, b"cloud")
    sock.connect(c.endpoint)
    clouds, end = [], time.time() + args.seconds
    while time.time() < end:
        if sock.poll(500):
            parts = sock.recv_multipart()
            if len(parts) == 3 and parts[0] == b"cloud":
                n = struct.unpack("<dII", parts[1])[2]
                clouds.append(np.frombuffer(parts[2], dtype="<f4").reshape(n, 4))
    if not clouds:
        print(f"no clouds from the bridge in {args.seconds:.0f} s: is spider-lidar running?")
        return 1

    pts = np.concatenate(clouds).astype(np.float64)
    x0, y0, z0 = pts[:, 0], pts[:, 1], pts[:, 2]
    if c.imu_upside_down:
        y0, z0 = -y0, -z0
    yaw = math.radians(c.mount_yaw_deg)
    x = math.cos(yaw) * x0 - math.sin(yaw) * y0
    y = math.sin(yaw) * x0 + math.cos(yaw) * y0
    z = z0 + c.mount_height_m
    r = np.hypot(x, y)
    bearing = np.degrees(np.arctan2(y, x))
    elevation = np.degrees(np.arctan2(z0, r))
    inside = (np.abs(x) < fx) & (np.abs(y) < fy)
    keep = (r < 0.6) & (z >= c.z_min_m) & (z <= c.z_max_m) & np.isfinite(r)
    rows = np.column_stack([x, y, z, r, bearing, inside, pts[:, 3]])[keep]
    np.savetxt(args.out, rows, fmt="%.4f", delimiter=",",
               header="x,y,z,r,bearing_deg,inside_box,intensity (robot frame, m; + left)")
    print(f"{len(clouds)} clouds, {int(keep.sum())} points within 0.6 m in the z band "
          f"-> {args.out}")

    out = keep & ~inside
    for b in range(-90, 91, 10):
        sel = out & (np.abs(((bearing - b + 180) % 360) - 180) < 5)
        if sel.any():
            print(f"  {b:+4d} deg: {int(sel.sum()):4d} outside the box, nearest "
                  f"{r[sel].min():.3f} m, x {x[sel].min():+.3f}..{x[sel].max():+.3f} "
                  f"y {y[sel].min():+.3f}..{y[sel].max():+.3f} z {z[sel].min():.2f}..")

    front = keep & (np.abs(bearing) <= 90)
    cam = front & (r < CAMERA_R_M) & (elevation > 0)
    if cam.any():
        b0, b1 = bearing[cam].min(), bearing[cam].max()
        e0, e1 = elevation[cam].min(), elevation[cam].max()
        print(f"\ncamera: {int(cam.sum())} points, bearing {b0:+.0f}..{b1:+.0f} deg (middle "
              f"{(b0 + b1) / 2:+.0f}), elevation {e0:.0f}..{e1:.0f} deg, "
              f"{r[cam].min():.2f}..{r[cam].max():.2f} m")
        lo_b, hi_b = math.floor(b0 - MARGIN_DEG), math.ceil(b1 + MARGIN_DEG)
        lo_e, hi_e = max(1, math.floor(e0 - MARGIN_UP_DEG)), math.ceil(e1 + MARGIN_DEG)
        print(f"  camera_window: {{bearing_min_deg: {lo_b}, bearing_max_deg: {hi_b}, "
              f"elevation_min_deg: {lo_e}, elevation_max_deg: {hi_e}, max_range_m: 0.6}}")
    ahead = front & (r >= CAMERA_R_M) & (elevation < 5.0)
    if ahead.any():
        print(f"\n0.35-0.6 m in front, below the camera: {int(ahead.sum())} points, bearing "
              f"{bearing[ahead].min():+.0f}..{bearing[ahead].max():+.0f} deg, middle "
              f"{np.median(bearing[ahead]):+.1f} deg, {r[ahead].min():.2f}..{r[ahead].max():.2f} m"
              " (a box straight ahead should read 0)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
