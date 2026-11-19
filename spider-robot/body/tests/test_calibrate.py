"""spider-calibrate center: all joints at once, or one leg at a time, slowly (owner, 2026-11-19)."""

import pytest

from spider_body import calibrate
from spider_body.hw.servos import SscServoBank


class FakeSerial:
    def __init__(self):
        self.written: list[str] = []

    def write(self, data):
        self.written.append(bytes(data).decode())
        return len(data)


def ssc(cfg):
    ser = FakeSerial()
    return SscServoBank(cfg, port=ser, clock=lambda: 0.0), ser


def test_a_raw_move_can_glide(cfg):
    bank, ser = ssc(cfg)
    bank.write_raw("LF.coxa", 90.0, 2000)
    bank.write_raw("LF.femur", 90.0)
    assert ser.written == ["#29P1500T2000\r", "#30P1500\r"]


def test_one_leg_joint_by_joint_slowly_then_only_that_leg_relaxes(cfg):
    bank, ser = ssc(cfg)
    asked, waited = [], []
    calibrate.cmd_center(cfg, bank, ["LF"], 3.0, ask=lambda q: asked.append(q) or "",
                         wait=waited.append)
    assert ser.written[:4] == ["#29P1500T3000\r", "#30P1500T3000\r", "#31P1500T3000\r",
                               "#29P0#30P0#31P0\r"]
    assert waited == [3.0, 3.0, 3.0] and len(asked) == 4  # Enter before each joint, then relax
    assert "channel 29" in asked[0] and "Attach its horns" in asked[3]


def test_legs_go_in_the_order_asked_and_the_180_degree_servo_centres_too(cfg):
    bank, ser = ssc(cfg)
    calibrate.cmd_center(cfg, bank, ["LR", "RR"], 1.0, ask=lambda q: "", wait=lambda s: None)
    moves = [w for w in ser.written if "T1000" in w]
    assert moves == ["#19P1500T1000\r", "#18P1500T1000\r", "#16P1500T1000\r",  # 16: 180-degree
                     "#1P1500T1000\r", "#2P1500T1000\r", "#3P1500T1000\r"]


def test_without_a_leg_every_joint_centres_at_once(cfg):
    bank, ser = ssc(cfg)
    calibrate.cmd_center(cfg, bank, None, 2.0, ask=lambda q: "", wait=lambda s: None)
    assert len([w for w in ser.written if w.endswith("T2000\r")]) == 18
    assert ser.written[-1].count("P0") == 18  # then everything relaxes


def test_the_command_line(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(calibrate, "make_servo_bank", lambda cfg: object())
    monkeypatch.setattr(calibrate, "cmd_center",
                        lambda cfg, bank, legs, seconds: seen.update(legs=legs, seconds=seconds))
    config = str(calibrate.Path(__file__).resolve().parents[1] / "config" / "robot.sim.yaml")
    calibrate.main(["--config", config, "center", "--leg", "LF", "--leg", "RM", "--seconds", "3"])
    assert seen == {"legs": ["LF", "RM"], "seconds": 3.0}
    with pytest.raises(SystemExit):
        calibrate.main(["--config", config, "center", "--seconds", "20"])


def answers(*seq):
    it = iter(seq)
    return lambda q: next(it)


def test_trim_one_leg_saves_it_and_keeps_the_other_legs(cfg, tmp_path):
    import yaml

    out = tmp_path / "calibration.yaml"
    cfg.servo("RF.coxa").trim_deg = 3.0  # already calibrated earlier
    bank, ser = ssc(cfg)
    calibrate.cmd_trim(cfg, bank, out, ["LF"], ask=answers("+", "+", "n", "n", "-", "n"))
    saved = yaml.safe_load(out.read_text())
    assert saved["LF.coxa"]["trim_deg"] == 2.0 and saved["LF.femur"]["trim_deg"] == 0.0
    assert saved["LF.tibia"]["trim_deg"] == -1.0 and saved["RF.coxa"]["trim_deg"] == 3.0
    assert "#29P1515\r" in ser.written  # +2 deg on a 270-degree servo = +15 us


def test_direction_one_leg(cfg, tmp_path):
    import yaml

    out = tmp_path / "calibration.yaml"
    bank, ser = ssc(cfg)
    calibrate.cmd_direction(cfg, bank, out, ["RR"], ask=answers("", "y", "", "n", "", "y"))
    saved = yaml.safe_load(out.read_text())
    assert [saved[f"RR.{j}"]["direction"] for j in ("coxa", "femur", "tibia")] == [1, -1, 1]


def test_show_compares_every_servo_without_moving_anything(cfg, monkeypatch, capsys):
    cfg.servo("LF.femur").trim_deg = 4.0
    lines = calibrate.cmd_show(cfg)
    lr_tibia = next(line for line in lines if line.startswith("LR.tibia"))
    assert " 16 " in lr_tibia and "180°" in lr_tibia and "1500 us" in lr_tibia
    assert any(line.startswith("LF.femur") and "+4.00°" in line and "1530 us" in line
               for line in lines)
    assert "femur: trims from +0.00° to +4.00° (spread 4.00°)" in lines

    def no_board(cfg):
        raise AssertionError("show must not open the servo board")

    monkeypatch.setattr(calibrate, "make_servo_bank", no_board)
    config = str(calibrate.Path(__file__).resolve().parents[1] / "config" / "robot.sim.yaml")
    assert calibrate.main(["--config", config, "show"]) == 0
    assert "LF.coxa" in capsys.readouterr().out
