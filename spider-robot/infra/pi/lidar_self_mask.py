#!/usr/bin/env python3
"""Measure where the L2 sees the robot's own front camera, for lidar.self_mask_file.

Run it on the Pi with the gateway's venv and settings, like spider-robotctl. The gateway needs
SG_BENCH=1 and the robot sits or stands (on the tripod is fine). A furnished room is fine: only
what CHANGES as the camera turns is taken for the camera, so things that stay put are never
masked, however near. Nothing may move during the sweep: people stay still, at least 1 m away.
Walls all around help: a sector that sees nothing at all is taken as hidden.

  sudo -u spider bash -c 'set -a; . /etc/spider/gateway.env; set +a; exec \
    /opt/spider/spider-robot/gateway/.venv/bin/python \
    /opt/spider/spider-robot/infra/pi/lidar_self_mask.py'

It turns the camera from -60 to +60 deg in 10-deg steps (a bench Look, nothing else moves),
reads the LiDAR sector map at each pan and writes, per pan:
  mask:   front-half sectors nearer than 0.6 m AND nearer than that sector reads at another pan
          (the room behind the camera): the camera, ignored up to that distance
  shadow: sectors with no return at all: the camera hides them
It writes /tmp/lidar_self_mask.yaml only after you type yes, and prints how to install it.

Two passes:
1. With no mask: lidar.self_mask_file unset in /etc/spider/robot.yaml and spider-body restarted,
   or it measures through the old mask.
2. With the new mask installed, again with --extend /etc/spider/lidar_self_mask.yaml. The map
   only holds the NEAREST return per sector, so the first pass cannot see how deep the camera
   is, nor which sectors it empties. --extend adds what still shows through the mask; repeat
   until it says nothing is left.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import os
import statistics
import sys
import time
from pathlib import Path

import yaml

NEAR_M = 0.6  # the body refuses a mask past this: nothing that far is the robot
MAX_RANGE_M = 8.0  # lidar.max_range_m: a sector at this distance saw nothing
SECTORS = 36
PAN_MATCH_DEG = 0.5
MAP_WAIT_S = 20.0  # the L2 can drop out for a few seconds; wait this long for fresh maps
SAME_M = 0.03  # range noise: a sector this close to its farthest reading has not changed


def bearing(sector: int) -> int:
    """Sector index -> degrees, + left, -170..180."""
    deg = sector * 360 // SECTORS
    return deg if deg <= 180 else deg - 360


def front_half(sector: int) -> bool:
    """The camera is in front of the L2: a near return behind it is something else."""
    return abs(bearing(sector)) <= 90


def merge(samples: list[list[float]]) -> list[float]:
    """Nearest return per sector over several sector maps."""
    return [min(column) for column in zip(*samples, strict=True)]


def empty(d: float) -> bool:
    return d >= MAX_RANGE_M - 1e-3


def old_shadows(old_pans: dict, pan: float) -> set[int]:
    return {int(i) for i in (find_old(old_pans, pan) or {}).get("shadow") or []}


def room_of(maps: dict[float, list[float]], old_pans: dict | None = None) -> list[float]:
    """Per sector, its farthest reading over all pans: the room, where the camera was away.
    Empty readings and old shadows (they read their neighbour's value) do not count."""
    room = [0.0] * SECTORS
    for pan, sectors_m in maps.items():
        hidden = old_shadows(old_pans or {}, pan)
        for i, d in enumerate(sectors_m):
            if not empty(d) and i not in hidden:
                room[i] = max(room[i], d)
    return room


def entry_for(sectors_m: list[float], old: dict | None = None,
              room: list[float] | None = None) -> tuple[dict, list[str]]:
    """One pan's mask entry from its measured map, added to the old entry (--extend).

    Only a return nearer than the same sector's room (room_of) is the camera; something that
    reads the same at every pan stays an obstacle. Returns the entry and the problems that
    make the measurement unusable.
    """
    old = old or {}
    room = room or [MAX_RANGE_M] * SECTORS
    mask = {int(k): float(v) for k, v in (old.get("mask") or {}).items()}
    old_shadow = {int(i) for i in old.get("shadow") or []}
    shadow = set(old_shadow)
    problems = []
    for i, d in enumerate(sectors_m):
        if empty(d):
            shadow.add(i)  # in a room with walls only the camera leaves a sector empty
        elif d < NEAR_M and d < room[i] - SAME_M and i not in old_shadow:
            # an old shadow reads its neighbour's value, not its own
            if not front_half(i):
                problems.append(f"something moved {d:.2f} m away at {bearing(i):+d} deg, "
                                "behind the robot: that is not the camera; keep still and "
                                "run again")
                continue
            mask[i] = max(mask.get(i, 0.0), math.ceil(d * 1000) / 1000)
    return {"mask": dict(sorted(mask.items())), "shadow": sorted(shadow)}, problems


def same_everywhere(maps: dict[float, list[float]]) -> list[int]:
    """Sectors near at every pan and unchanged: the room (or a fixed part of the camera mount),
    kept as an obstacle."""
    out = []
    for i in range(SECTORS):
        ds = [m[i] for m in maps.values()]
        if len(ds) > 2 and max(ds) < NEAR_M and max(ds) - min(ds) <= SAME_M:
            out.append(i)
    return out


def blind_everywhere(maps: dict[float, list[float]]) -> list[int]:
    return [i for i in range(SECTORS)
            if maps and all(m[i] >= MAX_RANGE_M - 1e-3 for m in maps.values())]


def find_old(old_pans: dict, pan: float) -> dict | None:
    for key, value in old_pans.items():
        if abs(float(key) - pan) <= PAN_MATCH_DEG:
            return value
    return None


def build(maps: dict[float, list[float]], margin_m: float, old: dict | None = None
          ) -> tuple[dict, list[str]]:
    old_pans = (old or {}).get("pans") or {}
    room = room_of(maps, old_pans)
    pans, problems = {}, []
    for pan in sorted(maps):
        entry, issues = entry_for(maps[pan], find_old(old_pans, pan), room)
        pans[pan] = entry
        problems += [f"pan {pan:+.0f}: {p}" for p in issues]
    for key, value in old_pans.items():  # an old pan this sweep did not reach stays as it was
        if all(abs(float(key) - p) > PAN_MATCH_DEG for p in pans):
            pans[float(key)] = value
    margin = float((old or {}).get("margin_m", margin_m))
    return {"margin_m": margin, "pans": dict(sorted(pans.items()))}, problems


def to_yaml(table: dict, note: str) -> str:
    lines = [f"# {note}", "# pan_deg (+ left) -> sector -> ignore points up to r_m (+ margin_m);",
             "# shadow: sectors the camera hides. Sector i is bearing i*10 deg, + left.",
             f"margin_m: {table['margin_m']}", "pans:"]
    for pan, entry in table["pans"].items():
        mask = ", ".join(f"{i}: {r}" for i, r in entry["mask"].items())
        shadow = ", ".join(str(i) for i in entry["shadow"])
        lines.append(f"  {pan:g}: {{mask: {{{mask}}}, shadow: [{shadow}]}}")
    return "\n".join(lines) + "\n"


def changes(old: dict | None, new: dict) -> list[str]:
    """What --extend added; empty when the mask already covers everything."""
    out = []
    old_pans = (old or {}).get("pans") or {}
    for pan, entry in new["pans"].items():
        before = find_old(old_pans, pan) or {}
        bm = {int(k): float(v) for k, v in (before.get("mask") or {}).items()}
        for i, r in entry["mask"].items():
            if bm.get(i) != r:
                out.append(f"pan {pan:+.0f}: {bearing(i):+d} deg masked to {r:.3f} m"
                           + ("" if i not in bm else f" (was {bm[i]:.3f})"))
        for i in sorted(set(entry["shadow"]) - {int(s) for s in before.get("shadow") or []}):
            out.append(f"pan {pan:+.0f}: {bearing(i):+d} deg is hidden")
    return out


def table_text(maps: dict[float, list[float]], table: dict) -> str:
    rows = []
    for pan, entry in table["pans"].items():
        if pan not in maps:
            continue
        mask = "  ".join(f"{bearing(i):+d}:{r:.2f}" for i, r in entry["mask"].items()) or "-"
        shadow = " ".join(f"{bearing(i):+d}" for i in entry["shadow"]) or "-"
        rows.append(f"  pan {pan:+4.0f}   camera at (deg:m) {mask}   hidden {shadow}")
    return "\n".join(rows)


# --------------------------------------------------------------------------- on the robot
async def read_maps(console, count: int, after: float, timeout_s: float):
    """`count` fresh RobotStates sent after `after` (wall clock), and the last state seen."""
    from spider_common.protocol import RobotState

    got: list = []
    last: list = []

    def collect(msg):
        if msg.topic != console.topics.state:
            return None
        s = RobotState.model_validate_json(msg.payload)
        if s.ts < after:
            return None
        last[:] = [s]
        if s.lidar is None or s.lidar_age_s is None or s.lidar_age_s > 0.5:
            return None
        got.append(s)
        return got if len(got) >= count else None

    await console.wait_for(collect, timeout_s)
    return got, (last[0] if last else None)


def describe(state) -> str:
    if state is None:
        return "no telemetry from the robot at all"
    age = "none" if state.lidar_age_s is None else f"{state.lidar_age_s:.1f} s"
    return f"mode {state.mode}, lidar age {age}, limiter {state.limiter}"


async def sweep(console, pans: list[float], settle_s: float, samples: int):
    maps: dict[float, list[float]] = {}
    try:
        for want in pans:
            answer = await console.bench_look(want, 1.0)
            if not answer.startswith("ack"):
                raise RuntimeError(f"look {want:+.0f}: {answer}")
            await asyncio.sleep(settle_s)
            states, last = await read_maps(console, samples, time.time(), MAP_WAIT_S)
            if len(states) < samples:
                raise RuntimeError(f"pan {want:+.0f}: {len(states)} of {samples} fresh LiDAR "
                                   f"maps in {MAP_WAIT_S:.0f} s; last state: {describe(last)}")
            seen = [s.camera_pan_deg for s in states]
            if any(p is None for p in seen) or max(seen) - min(seen) > PAN_MATCH_DEG:
                raise RuntimeError(f"pan {want:+.0f}: the camera did not hold still ({seen})")
            pan = round(statistics.median(seen), 1)  # the body may have limited it
            if pan in maps:
                continue
            maps[pan] = merge([s.lidar.sectors_m for s in states])
            print(f"  pan {pan:+5.1f}: nearest " + " ".join(
                f"{bearing(i):+d}:{d:.2f}" for i, d in enumerate(maps[pan]) if d < 1.2)
                + "  nothing at " + (" ".join(
                    f"{bearing(i):+d}" for i, d in enumerate(maps[pan]) if empty(d)) or "-"),
                flush=True)
    finally:
        print("camera back to 0:", await console.bench_look(0.0, 1.0))
    return maps


async def run(args: argparse.Namespace) -> int:
    from spider_common.link import MqttLink

    from spider_gateway.console import BENCH_SOURCE, Console, _settings

    old = None
    if args.extend:
        old = yaml.safe_load(Path(args.extend).read_text("utf-8")) or {}
    robot_id = os.environ.get("SG_ROBOT_ID", "spider-01")
    link = MqttLink(_settings(), Console.subscriptions(robot_id, BENCH_SOURCE))
    console = Console(link, robot_id, BENCH_SOURCE)
    await link.start()
    await asyncio.wait_for(link.connected.wait(), 8.0)
    await asyncio.sleep(0.2)
    try:
        pans = [float(p) for p in range(args.start, args.stop + 1, args.step)]
        print(f"measuring at {len(pans)} pans, {args.settle:.0f} s each ...", flush=True)
        maps = await sweep(console, pans, args.settle, args.samples)
    except RuntimeError as e:
        print(f"stopped: {e}", file=sys.stderr)
        return 1
    finally:
        await link.stop()

    table, problems = build(maps, args.margin, old)
    print("\nwhat the L2 sees of the camera (deg: + left, 0 = straight ahead):")
    print(table_text(maps, table))
    if problems:
        print("\ncannot use this measurement:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    fixed = same_everywhere(maps)
    if fixed:
        print("\nkept as obstacles (nearer than 0.6 m but the same at every pan, so not the "
              "moving camera): " + ", ".join(f"{bearing(i):+d} deg" for i in fixed))
    blind = blind_everywhere(maps)
    if blind:
        print("\nCHECK: no return at any pan, written as hidden (an open door?): "
              + ", ".join(f"{bearing(i):+d} deg" for i in blind))
    if old is not None:
        added = changes(old, table)
        if not added:
            print("\nnothing new: the mask covers the camera. Done.")
            return 0
        print("\nstill seen through the mask, added now:\n  " + "\n  ".join(added))
    if not args.yes and input(f"\nType yes to write {args.out}: ").strip().lower() != "yes":
        print("nothing written")
        return 1
    note = (f"infra/pi/lidar_self_mask.py, {time.strftime('%Y-%m-%d %H:%M')}"
            + (" (extended)" if old is not None else ""))
    Path(args.out).write_text(to_yaml(table, note), "utf-8")
    print(f"\nwrote {args.out}. Install it and restart spider-body (robot sitting):\n"
          f"  sudo install -m 644 {args.out} /etc/spider/lidar_self_mask.yaml\n"
          "  and in /etc/spider/robot.yaml under lidar:\n"
          "    self_mask_file: /etc/spider/lidar_self_mask.yaml\n"
          "Then run this again with --extend /etc/spider/lidar_self_mask.yaml.")
    return 0


def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lidar_self_mask.py", description=__doc__.split("\n")[0])
    p.add_argument("--start", type=int, default=-60)
    p.add_argument("--stop", type=int, default=60)
    p.add_argument("--step", type=int, default=10)
    p.add_argument("--settle", type=float, default=2.0, help="seconds after each turn")
    p.add_argument("--samples", type=int, default=5, help="LiDAR maps per pan (4 a second)")
    p.add_argument("--margin", type=float, default=0.05, help="margin_m for a new file")
    p.add_argument("--extend", help="the installed mask file: add what still shows through it")
    p.add_argument("--out", default="/tmp/lidar_self_mask.yaml")
    p.add_argument("--yes", action="store_true", help="write without asking")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    if not -90 <= args.start < args.stop <= 90 or args.step <= 0:
        parser.error("pans must run upwards within -90..90")
    if not 0.0 <= args.margin <= 0.1:
        parser.error("--margin must be 0..0.1 m")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
