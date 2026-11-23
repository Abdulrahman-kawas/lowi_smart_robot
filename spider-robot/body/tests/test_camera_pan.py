"""The front camera's pan servo (channel 27): config, Look, glide, Stop/E-stop/relax, calibrate."""

import pytest
import yaml
from spider_common.protocol import EStop, EStopRelease, Look, Posture, Stop
from test_calibrate import FakeSerial, answers
from test_robot import events, make, run_ticks, stand

from spider_body import calibrate
from spider_body.config import CAMERA_PAN, BodyConfig, apply_calibration, save_calibration
from spider_body.hw.servos import SscServoBank

TS = 5000.0  # the wall clock make() gives the robot


def look(robot, pan, speed=1.0, seq=10):
    robot.handle(Look(pan_deg=pan, speed=speed, ts=TS, seq=seq))


def last(link, kind):
    return [e for e in events(link) if e["kind"] == kind][-1]


def test_an_old_config_without_camera_pan_still_loads(cfg):
    data = cfg.model_dump()
    data.pop("camera_pan")
    old = BodyConfig.model_validate(data)
    assert old.camera_pan is None and CAMERA_PAN not in old.servo_ids()
    apply_calibration(old, {CAMERA_PAN: {"direction": -1, "trim_deg": 3.0}})  # ignored, no crash


def test_the_pan_servo_is_a_180_degree_servo_on_channel_27(cfg):
    s = cfg.camera_pan
    assert s.channel == 27 and cfg.pulse_of(s).range_deg == 180.0
    assert cfg.pulse_of(s).pulse_us(90.0) == 1500.0 and cfg.pulse_of(s).pulse_us(0.0) == 500.0
    assert cfg.pan_range() == (-60.0, 60.0)
    assert cfg.servo_ids()[-1] == CAMERA_PAN and len(cfg.servo_ids()) == 19


def test_a_leg_channel_cannot_be_the_camera(cfg):
    data = cfg.model_dump()
    data["camera_pan"]["channel"] = 29  # LF.coxa
    with pytest.raises(ValueError, match="camera_pan: channel 29"):
        BodyConfig.model_validate(data)


def test_trim_and_direction_map_pan_to_servo_degrees(cfg):
    s = cfg.camera_pan
    s.trim_deg, s.direction = 10.0, -1
    assert cfg.pan_servo_deg(20.0) == 80.0  # mirrored: + left is a smaller servo angle
    assert cfg.pan_range() == (-60.0, 60.0)  # limits move with the trim


def test_look_is_refused_while_relaxed_and_during_an_estop(cfg):
    robot, servos, lidar, world, brain, clock = make(cfg)
    look(robot, 30)
    assert "cannot look while relaxed" in last(brain, "rejected")["detail"]
    stand(robot, lidar, world, clock)
    robot.handle(EStop(ts=TS, seq=11))
    look(robot, 30, seq=12)
    assert "estop is latched" in last(brain, "rejected")["detail"]


def test_look_glides_at_the_capped_rate_and_reports_the_pan(cfg):
    robot, servos, lidar, world, brain, clock = make(cfg)
    stand(robot, lidar, world, clock)
    assert robot.state().camera_pan_deg == 0.0
    look(robot, 45, speed=0.5)  # 90 deg/s * 0.5 = 45 deg/s
    run_ticks(robot, lidar, world, clock, 0.5)
    assert robot.state().camera_pan_deg == pytest.approx(22.5, abs=1.0)
    run_ticks(robot, lidar, world, clock, 1.0)
    assert robot.state().camera_pan_deg == 45.0
    assert servos.last[CAMERA_PAN] == pytest.approx(135.0)  # 90 + 45
    assert last(brain, "ack")["detail"] == "look +45 deg"


def test_look_is_clamped_to_the_limits(cfg):
    robot, servos, lidar, world, brain, clock = make(cfg)
    stand(robot, lidar, world, clock)
    look(robot, -90)
    run_ticks(robot, lidar, world, clock, 1.5)
    assert robot.pan_deg == -60.0 and "limited to -60..+60" in last(brain, "ack")["detail"]


def test_stop_and_estop_freeze_the_glide(cfg):
    robot, servos, lidar, world, brain, clock = make(cfg)
    stand(robot, lidar, world, clock)
    look(robot, 60, speed=0.5)
    run_ticks(robot, lidar, world, clock, 0.4)
    robot.handle(Stop(ts=TS, seq=11))
    held = robot.pan_deg
    run_ticks(robot, lidar, world, clock, 1.0)
    assert robot.pan_deg == held and 10 < held < 30
    look(robot, -60, speed=0.5, seq=12)
    run_ticks(robot, lidar, world, clock, 0.4)
    robot.handle(EStop(ts=TS, seq=13))
    held = robot.pan_deg
    run_ticks(robot, lidar, world, clock, 1.0)
    robot.handle(EStopRelease(ts=TS, seq=14))
    run_ticks(robot, lidar, world, clock, 1.0)
    assert robot.pan_deg == held  # a release does not resume the glide


def test_a_look_sent_before_a_stop_is_dropped(cfg):
    robot, servos, lidar, world, brain, clock = make(cfg)
    stand(robot, lidar, world, clock)
    robot.handle(Stop(ts=TS, seq=20))
    look(robot, 40, seq=19)
    run_ticks(robot, lidar, world, clock, 1.0)
    assert robot.pan_deg == 0.0


def test_relax_makes_the_camera_limp_and_unknown(cfg):
    robot, servos, lidar, world, brain, clock = make(cfg)
    stand(robot, lidar, world, clock)
    look(robot, 30)
    run_ticks(robot, lidar, world, clock, 1.0)
    robot.handle(Posture(posture="sit", ts=TS, seq=11))
    run_ticks(robot, lidar, world, clock, 3)
    robot.handle(Posture(posture="relax", ts=TS, seq=12))
    assert servos.relaxed and robot.state().camera_pan_deg is None
    assert robot.pan_target == 0.0  # it centres when the robot wakes


def test_the_camera_waits_for_every_leg_when_waking(cfg):
    robot, servos, lidar, world, brain, clock = make(cfg)
    robot.handle(Posture(posture="stand", ts=TS, seq=1))
    run_ticks(robot, lidar, world, clock, 0.1)
    assert CAMERA_PAN not in servos.last
    run_ticks(robot, lidar, world, clock, 2.0)
    assert servos.last[CAMERA_PAN] == pytest.approx(90.0)


def test_the_ssc_sends_the_camera_in_the_same_group_and_relaxes_it(cfg):
    ser = FakeSerial()
    bank = SscServoBank(cfg, port=ser, clock=lambda: 10.0)
    bank.write({"LF.coxa": 90.0, CAMERA_PAN: 120.0})
    assert ser.written[-1] == "#27P1833#29P1500T40\r"  # 120 deg on 180 deg: 1500 + 30 * 11.1
    bank.relax()
    assert "#27P0" in ser.written[-1]


# ------------------------------------------------------------------ spider-calibrate --camera
def test_center_the_camera_alone(cfg):
    ser = FakeSerial()
    bank = SscServoBank(cfg, port=ser, clock=lambda: 0.0)
    calibrate.cmd_center(cfg, bank, None, 2.0, ask=lambda q: "", wait=lambda s: None, camera=True)
    assert ser.written == ["#27P1500T2000\r", "#27P0\r"]


def test_direction_and_trim_for_the_camera_are_saved(cfg, tmp_path):
    out = tmp_path / "calibration.yaml"
    bank = SscServoBank(cfg, port=FakeSerial(), clock=lambda: 0.0)
    calibrate.cmd_direction(cfg, bank, out, camera=True, ask=answers("", "n"))
    calibrate.cmd_trim(cfg, bank, out, camera=True, ask=answers("+", "+", "n"))
    saved = yaml.safe_load(out.read_text())
    assert saved[CAMERA_PAN] == {"direction": -1, "trim_deg": -2.0}  # + = left, mirrored
    assert "LF.coxa" in saved  # the legs are still in the file


def test_show_lists_the_camera(cfg):
    assert any(line.startswith("camera_pan") and " 27 " in line and "180°" in line
               for line in calibrate.cmd_show(cfg))


def test_save_calibration_keeps_the_camera(cfg, tmp_path):
    cfg.camera_pan.trim_deg = 4.0
    save_calibration(cfg, tmp_path / "c.yaml")
    assert yaml.safe_load((tmp_path / "c.yaml").read_text())[CAMERA_PAN]["trim_deg"] == 4.0


def test_ctrl_c_relaxes_and_exits_non_zero(monkeypatch):
    relaxed = []

    class Bank:
        def relax(self):
            relaxed.append(True)

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(calibrate, "make_servo_bank", lambda cfg: Bank())
    monkeypatch.setattr(calibrate, "cmd_center", interrupted)
    config = str(calibrate.Path(__file__).resolve().parents[1] / "config" / "robot.sim.yaml")
    assert calibrate.main(["--config", config, "center"]) == 130 and relaxed


def test_camera_flag_needs_a_camera_action(capsys):
    config = str(calibrate.Path(__file__).resolve().parents[1] / "config" / "robot.sim.yaml")
    with pytest.raises(SystemExit):
        calibrate.main(["--config", config, "pose", "--camera"])
    with pytest.raises(SystemExit):
        calibrate.main(["--config", config, "center", "--camera", "--leg", "LF"])
