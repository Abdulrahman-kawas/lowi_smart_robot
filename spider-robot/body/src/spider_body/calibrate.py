"""Servo calibration tool. Run it with the robot on a stand (legs in the air).

  spider-calibrate check       controller answers? (SSC-32U: prints its firmware version)
  spider-calibrate center      all 18 servos to raw 90 deg: now attach the horns so that
                               coxa points straight out, femur is horizontal, tibia is vertical
  spider-calibrate center --leg LF [--leg LM ...] [--seconds 3]
                               the same, one leg at a time and one joint at a time (Enter
                               between joints), each gliding to the middle over --seconds
  spider-calibrate trim        fine-tune each joint around that neutral pose
  spider-calibrate direction   find which servos are mounted mirrored
     trim and direction take --leg too (one leg at a time, saved after each leg)
  spider-calibrate show        every servo: channel, range, direction, trim and its real
                               centre pulse, to compare how far each one is off
  spider-calibrate pose sit|stand   check the result with real IK
  spider-calibrate relax       cut all servo pulses

Results go to config/calibration.yaml (loaded automatically next to robot.yaml).
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Callable
from pathlib import Path

from spider_common.link import InMemoryHub

from .config import JOINTS, BodyConfig, load_config, save_calibration
from .hw.camera import NoCamera
from .hw.lidar import NoLidar
from .hw.servos import make_servo_bank
from .robot import Robot

_POSITIVE = {
    "coxa": "rotate COUNTER-CLOCKWISE seen from above",
    "femur": "lift UP",
    "tibia": "bend the foot further DOWN / IN toward the body",
}


def _joint_ids(cfg: BodyConfig, legs: list[str] | None = None) -> list[str]:
    names = legs or [leg.name for leg in cfg.legs]
    return [f"{name}.{j}" for name in names for j in JOINTS]


def _by_leg(jids: list[str]) -> list[list[str]]:
    out: dict[str, list[str]] = {}
    for jid in jids:
        out.setdefault(jid.split(".")[0], []).append(jid)
    return list(out.values())


FIRST_MOVE = ("Legs in the air. The first move after the servo board powers up can go at full "
              "speed (the board does not know where a servo is yet): turn each joint near its "
              "middle by hand first.")


def cmd_center(cfg: BodyConfig, bank, legs: list[str] | None = None, seconds: float = 2.0,
               ask: Callable[[str], str] = input,
               wait: Callable[[float], None] = time.sleep) -> None:
    """Raw 90 deg (the pulse centre) on every joint, or one leg at a time: coxa, femur, tibia,
    each after Enter and gliding over `seconds`, then that leg relaxes."""
    t_ms = int(round(seconds * 1000)) or None
    if not legs:
        for jid in _joint_ids(cfg):
            bank.write_raw(jid, 90.0, t_ms)
        print("All servos at raw 90 deg. Attach horns: coxa straight out from the body, femur "
              "horizontal, tibia vertical. Press Enter to relax.")
        ask("")
        bank.relax()
        return
    print(FIRST_MOVE)
    for name in legs:
        leg = next(leg for leg in cfg.legs if leg.name == name)
        jids = [f"{name}.{j}" for j in JOINTS]
        chans = ", ".join(f"{j} {getattr(leg, j).channel}" for j in JOINTS)
        print(f"{name}: {chans}")
        for jid in jids:
            joint = jid.split(".")[1]
            ask(f"{jid} (channel {getattr(leg, joint).channel}): Enter to move it to the "
                f"middle over {seconds:g} s ")
            bank.write_raw(jid, 90.0, t_ms)
            wait(seconds)
        ask(f"{name} at raw 90 deg. Attach its horns: coxa straight out, femur horizontal, "
            f"tibia vertical. Enter to relax {name} ")
        bank.relax_joints(jids)
    bank.relax()


def cmd_trim(cfg: BodyConfig, bank, out: Path, legs: list[str] | None = None,
             ask: Callable[[str], str] = input) -> None:
    """Each joint until it sits exactly at its reference; saved after every leg, so stopping
    halfway keeps the legs already done (the other legs keep their saved trims)."""
    print("Commands: + / - (1 deg), ++ / -- (5 deg), . / , (0.25 deg), n = next, q = save+quit")
    for leg_jids in _by_leg(_joint_ids(cfg, legs)):
        for jid in leg_jids:
            servo = cfg.servo(jid)
            while True:
                bank.write_raw(jid, 90.0 + servo.trim_deg)
                ans = ask(f"{jid} (channel {servo.channel}) trim={servo.trim_deg:+.2f} > ").strip()
                step = {"+": 1, "-": -1, "++": 5, "--": -5, ".": 0.25, ",": -0.25}.get(ans)
                if step is not None:
                    servo.trim_deg = max(-30.0, min(30.0, servo.trim_deg + step))
                elif ans == "n":
                    break
                elif ans == "q":
                    save_calibration(cfg, out)
                    bank.relax()
                    print(f"saved {out}")
                    return
        save_calibration(cfg, out)
        print(f"{leg_jids[0].split('.')[0]} saved to {out}")
    bank.relax()


def cmd_show(cfg: BodyConfig) -> list[str]:
    """One line per servo, and how far apart the trims are, to compare the calibration."""
    lines = [f"{'joint':10s} {'ch':>3s} {'range':>5s} {'dir':>4s} {'trim':>7s} {'centre':>7s}"]
    trims: dict[str, list[float]] = {}
    for jid in _joint_ids(cfg):
        s = cfg.servo(jid)
        pulse = cfg.pulse_of(s)
        centre = pulse.pulse_us(90.0 + s.trim_deg)
        lines.append(f"{jid:10s} {s.channel:3d} {pulse.range_deg:4.0f}° {s.direction:+4d} "
                     f"{s.trim_deg:+6.2f}° {centre:5.0f} us")
        trims.setdefault(jid.split(".")[1], []).append(s.trim_deg)
    for joint, values in trims.items():
        lines.append(f"{joint}: trims from {min(values):+.2f}° to {max(values):+.2f}° "
                     f"(spread {max(values) - min(values):.2f}°)")
    return lines


def cmd_direction(cfg: BodyConfig, bank, out: Path, legs: list[str] | None = None,
                  ask: Callable[[str], str] = input) -> None:
    for leg_jids in _by_leg(_joint_ids(cfg, legs)):
        for jid in leg_jids:
            servo = cfg.servo(jid)
            joint = jid.split(".")[1]
            bank.write_raw(jid, 90.0 + servo.trim_deg)
            ask(f"{jid} (channel {servo.channel}): watch the joint, press Enter")
            bank.write_raw(jid, 90.0 + servo.trim_deg + 15.0)
            ans = ask(f"Did {jid} {_POSITIVE[joint]}? [y/n] ").strip().lower()
            servo.direction = 1 if ans.startswith("y") else -1
            bank.write_raw(jid, 90.0 + servo.trim_deg)
        save_calibration(cfg, out)
        print(f"{leg_jids[0].split('.')[0]} saved to {out}")
    bank.relax()


def cmd_pose(cfg: BodyConfig, bank, which: str) -> None:
    robot = Robot(cfg, bank, NoLidar(), NoCamera(), InMemoryHub().endpoint([]))
    g = cfg.geometry
    robot.gait.height = g.body_height_m if which == "stand" else g.sit_height_m
    angles = robot.solve(robot.gait.step(0.0))
    if angles is None:
        raise SystemExit("IK failed for this geometry: check geometry in robot.yaml")
    for jid, deg in sorted(angles.items()):
        print(f"{jid:10s} {deg:6.1f}")
    bank.write(angles)
    input("Holding pose. Press Enter to relax.")
    bank.relax()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="spider-calibrate")
    p.add_argument("--config", default="config/robot.yaml")
    p.add_argument("action",
                   choices=["check", "center", "trim", "direction", "pose", "relax", "show"])
    p.add_argument("pose", nargs="?", default="stand", choices=["stand", "sit"])
    p.add_argument("--leg", action="append", choices=["LF", "LM", "LR", "RF", "RM", "RR"],
                   help="center, trim, direction: only this leg (repeat for more, in order)")
    p.add_argument("--seconds", type=float, default=2.0,
                   help="center: time each joint takes to glide to the middle (SSC-32U)")
    args = p.parse_args(argv)
    if not 0.0 <= args.seconds <= 10.0:
        p.error("--seconds must be between 0 and 10")
    cfg = load_config(args.config)
    out = Path(args.config).with_name("calibration.yaml")
    if args.action == "show":  # reads the files only: no servo board needed, nothing moves
        print("\n".join(cmd_show(cfg)))
        return 0
    bank = make_servo_bank(cfg)
    try:
        if args.action == "check":
            if hasattr(bank, "version"):
                print("SSC-32U firmware:", bank.version() or "(no answer: check port and baud)")
            else:
                print("PCA9685 boards initialised on I2C")
        elif args.action == "center":
            cmd_center(cfg, bank, args.leg, args.seconds)
        elif args.action == "trim":
            cmd_trim(cfg, bank, out, args.leg)
        elif args.action == "direction":
            cmd_direction(cfg, bank, out, args.leg)
        elif args.action == "pose":
            cmd_pose(cfg, bank, args.pose)
        else:
            bank.relax()
    except KeyboardInterrupt:
        bank.relax()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
