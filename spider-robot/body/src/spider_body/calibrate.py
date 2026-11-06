"""Servo calibration tool. Run it with the robot on a stand (legs in the air).

  spider-calibrate check       controller answers? (SSC-32U: prints its firmware version)
  spider-calibrate center      all 18 servos to raw 90 deg: now attach the horns so that
                               coxa points straight out, femur is horizontal, tibia is vertical
  spider-calibrate trim        fine-tune each joint around that neutral pose
  spider-calibrate direction   find which servos are mounted mirrored
  spider-calibrate pose sit|stand   check the result with real IK
  spider-calibrate relax       cut all servo pulses

Results go to config/calibration.yaml (loaded automatically next to robot.yaml).
"""

from __future__ import annotations

import argparse
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


def _joint_ids(cfg: BodyConfig) -> list[str]:
    return [f"{leg.name}.{j}" for leg in cfg.legs for j in JOINTS]


def cmd_center(cfg: BodyConfig, bank) -> None:
    for jid in _joint_ids(cfg):
        bank.write_raw(jid, 90.0)
    print("All servos at raw 90 deg. Attach horns: coxa straight out from the body, femur "
          "horizontal, tibia vertical. Press Enter to relax.")
    input()
    bank.relax()


def cmd_trim(cfg: BodyConfig, bank, out: Path) -> None:
    print("Commands: + / - (1 deg), ++ / -- (5 deg), . / , (0.25 deg), n = next, q = save+quit")
    for jid in _joint_ids(cfg):
        servo = cfg.servo(jid)
        while True:
            bank.write_raw(jid, 90.0 + servo.trim_deg)
            ans = input(f"{jid} trim={servo.trim_deg:+.2f} > ").strip()
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
    bank.relax()
    print(f"saved {out}")


def cmd_direction(cfg: BodyConfig, bank, out: Path) -> None:
    for jid in _joint_ids(cfg):
        servo = cfg.servo(jid)
        joint = jid.split(".")[1]
        bank.write_raw(jid, 90.0 + servo.trim_deg)
        input(f"{jid}: watch the joint, press Enter")
        bank.write_raw(jid, 90.0 + servo.trim_deg + 15.0)
        ans = input(f"Did {jid} {_POSITIVE[joint]}? [y/n] ").strip().lower()
        servo.direction = 1 if ans.startswith("y") else -1
        bank.write_raw(jid, 90.0 + servo.trim_deg)
    save_calibration(cfg, out)
    bank.relax()
    print(f"saved {out}")


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
    p.add_argument("action", choices=["check", "center", "trim", "direction", "pose", "relax"])
    p.add_argument("pose", nargs="?", default="stand", choices=["stand", "sit"])
    args = p.parse_args(argv)
    cfg = load_config(args.config)
    out = Path(args.config).with_name("calibration.yaml")
    bank = make_servo_bank(cfg)
    try:
        if args.action == "check":
            if hasattr(bank, "version"):
                print("SSC-32U firmware:", bank.version() or "(no answer: check port and baud)")
            else:
                print("PCA9685 boards initialised on I2C")
        elif args.action == "center":
            cmd_center(cfg, bank)
        elif args.action == "trim":
            cmd_trim(cfg, bank, out)
        elif args.action == "direction":
            cmd_direction(cfg, bank, out)
        elif args.action == "pose":
            cmd_pose(cfg, bank, args.pose)
        else:
            bank.relax()
    except KeyboardInterrupt:
        bank.relax()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
