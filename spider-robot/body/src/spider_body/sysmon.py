"""spider-sysmon: the Pi's own health, published every 5 s. Runs on cores 1-3.

Undervoltage and thermal throttling are the two quiet killers of a robot like this: both slow or
reset the computer without any error message from the program that suffers.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

from spider_common.link import Link, MqttLink
from spider_common.obs import setup_logging
from spider_common.protocol import HealthLevel, HealthReport, Topics

from .config import BodyConfig, broker_settings, load_config

log = logging.getLogger("spider_sysmon")
PERIOD_S = 5.0
THROTTLED = Path("/sys/devices/platform/soc/soc:firmware/get_throttled")
THERMAL = Path("/sys/class/thermal/thermal_zone0/temp")
MEMINFO = Path("/proc/meminfo")
UNDERVOLT_NOW, THROTTLED_NOW, SOFT_TEMP_NOW = 0x1, 0x4, 0x8
UNDERVOLT_EVER = 0x10000
TEMP_WARN_C, TEMP_BAD_C = 75.0, 80.0
MIN_FREE_MEM_MB, MIN_FREE_DISK_MB = 300.0, 1024.0
WATCHED_UNITS = ("spider-", "mosquitto", "ollama", "tailscaled", "llama-")


def run_tool(argv: list[str]) -> str | None:
    if shutil.which(argv[0]) is None:
        return None
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=4.0, check=False).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None


def parse_failed_units(text: str | None) -> list[str]:
    if not text:
        return []
    units = [line.split()[0] for line in text.splitlines() if line.strip()]
    return [u for u in units if u.startswith(WATCHED_UNITS)]


def parse_tailscale_path(text: str | None, peer: str) -> str | None:
    """direct, relay, or none when the peer is offline. None means Tailscale is not available."""
    if not text or not peer:
        return None
    try:
        peers = json.loads(text).get("Peer") or {}
    except ValueError:
        return None
    for node in peers.values():
        if node.get("HostName") == peer or node.get("DNSName", "").startswith(f"{peer}."):
            if not node.get("Online"):
                return "none"
            if node.get("CurAddr"):
                return "direct"
            if node.get("PeerRelay"):
                return "peer-relay"
            return "relay" if node.get("Relay") else "none"
    return "none"


def assess(
    flags: int, temp_c: float | None, mem_mb: float | None, disk_mb: float | None
) -> tuple[HealthLevel, str]:
    """The worst condition present decides the level. Unknown values are not treated as good."""
    problems: list[str] = []
    level: HealthLevel = "ok"
    if flags & UNDERVOLT_NOW:
        problems.append("undervoltage now")
        level = "down"
    if flags & THROTTLED_NOW:
        problems.append("CPU throttled")
        level = "down"
    if temp_c is not None and temp_c >= TEMP_BAD_C:
        problems.append(f"{temp_c:.0f} C")
        level = "down"
    if level != "down":
        if flags & (SOFT_TEMP_NOW | UNDERVOLT_EVER):
            problems.append("soft temperature limit or earlier undervoltage")
            level = "degraded"
        if temp_c is None:
            problems.append("temperature unknown")
            level = "degraded"
        elif temp_c >= TEMP_WARN_C:
            problems.append(f"{temp_c:.0f} C")
            level = "degraded"
        if mem_mb is not None and mem_mb < MIN_FREE_MEM_MB:
            problems.append(f"{mem_mb:.0f} MB free")
            level = "degraded"
        if disk_mb is not None and disk_mb < MIN_FREE_DISK_MB:
            problems.append(f"disk {disk_mb:.0f} MB free")
            level = "degraded"
    return level, "; ".join(problems)


def read_int(path: Path, base: int = 10) -> int | None:
    try:
        return int(path.read_text("ascii").strip(), base)
    except (OSError, ValueError):
        return None


def available_mem_mb(path: Path = MEMINFO) -> float | None:
    try:
        for line in path.read_text("ascii").splitlines():
            if line.startswith("MemAvailable:"):
                return float(line.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        return None
    return None


def sample(robot_id: str, state_dir: str = "/var/lib/spider", peer: str = "") -> HealthReport:
    flags = read_int(THROTTLED, 16) or 0
    milli = read_int(THERMAL)
    temp = None if milli is None else milli / 1000.0
    mem = available_mem_mb()
    disk = None
    if os.path.isdir(state_dir):
        disk = shutil.disk_usage(state_dir).free / 1_000_000.0
    level, detail = assess(flags, temp, mem, disk)
    metrics = {"throttled_flags": float(flags)}
    if temp is not None:
        metrics["temp_c"] = temp
    if mem is not None:
        metrics["mem_available_mb"] = round(mem, 1)
    if disk is not None:
        metrics["disk_free_mb"] = round(disk, 1)
    info: dict[str, str] = {}
    failed = parse_failed_units(run_tool(["systemctl", "--failed", "--plain", "--no-legend"]))
    if failed:
        info["failed_units"] = ",".join(failed)
        metrics["failed_units"] = float(len(failed))
    path = parse_tailscale_path(run_tool(["tailscale", "status", "--json"]), peer)
    if path is not None:
        info["tailscale_path"] = path
    return HealthReport(robot_id=robot_id, service="system", level=level, detail=detail,
                        metrics=metrics, info=info)


async def run_loop(link: Link, robot_id: str, peer: str = "") -> None:
    topic = Topics(robot_id).health("system")
    while True:
        report = await asyncio.to_thread(sample, robot_id, "/var/lib/spider", peer)
        link.publish(topic, report.model_dump_json(), qos=1, retain=True)
        await asyncio.sleep(PERIOD_S)


def build_link(cfg: BodyConfig) -> MqttLink:
    t = Topics(cfg.robot_id)
    will = HealthReport(robot_id=cfg.robot_id, service="system", level="down", detail="lost")
    s = cfg.sysmon
    return MqttLink(
        broker_settings(cfg.mqtt, s.client_id, s.username, s.password_file),
        subscriptions=[],
        will=(t.health("system"), will.model_dump_json().encode()),
        will_retain=True,
    )


async def _main(cfg: BodyConfig) -> None:
    link = build_link(cfg)
    await link.start()
    await run_loop(link, cfg.robot_id, cfg.sysmon.server_tailscale_name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="spider-sysmon")
    parser.add_argument("--config", default="/etc/spider/robot.yaml")
    args = parser.parse_args(argv)
    setup_logging("INFO")
    asyncio.run(_main(load_config(args.config, "/nonexistent")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
