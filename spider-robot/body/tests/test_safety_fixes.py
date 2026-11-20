"""Regression tests for defects found by the real-time and safety review."""

import asyncio
import json
import os
import random
import struct
import sys

import numpy as np
import pytest
from spider_common.link import InMemoryHub
from spider_common.protocol import (
    BodyPose,
    EStop,
    EStopRelease,
    Heartbeat,
    Move,
    Posture,
    Snapshot,
    Stop,
    Topics,
)

from spider_body import main as main_module
from spider_body.camera_service import CameraService
from spider_body.config import LidarCfg, RtCfg
from spider_body.hw.camera import FakeCamera
from spider_body.hw.lidar import LidarFeed, LidarProcessor, SimLidar, SimWorld
from spider_body.hw.servos import FakeServoBank, SscServoBank
from spider_body.main import control_loop, sit_and_relax
from spider_body.robot import Robot
from spider_body.rt import enable_fifo, pin_cpu, set_gil_interval
from spider_body.safety import EStopLatch

WALL = 5000.0
FOOT = (0.24, 0.27)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def rig(cfg, latch=None, lidar_cls=SimLidar):
    clock = Clock()
    hub = InMemoryHub()
    t = Topics(cfg.robot_id)
    body = hub.endpoint([t.cmd])
    brain = hub.endpoint([t.event, t.state, t.camera_filter])
    body.connected.set()
    brain.connected.set()
    world = SimWorld(obstacles=[])
    lidar = lidar_cls(cfg.lidar, world, clock=clock)
    servos = FakeServoBank()
    robot = Robot(cfg, servos, lidar, FakeCamera(cfg.camera), body, clock=clock,
                  wall=lambda: WALL, latch=latch)
    return robot, servos, lidar, world, brain, clock


def ticks(robot, lidar, clock, seconds, hz=50, heartbeat=True):
    dt = 1 / hz
    for i in range(int(seconds * hz)):
        clock.t += dt
        if i % 10 == 0:
            lidar.scan()
            if heartbeat:
                robot.handle(Heartbeat(ts=WALL))
        robot.tick(dt)


def events(link):
    return [json.loads(m.payload) for m in link.inbox.queue._queue if m.topic.endswith("/event")]


def stand(robot, lidar, clock):
    robot.handle(Posture(posture="stand", ts=WALL))
    ticks(robot, lidar, clock, 3)
    assert robot.mode == "standing"


# ------------------------------------------------------------------ the LiDAR sector map
def sweep(azimuths_deg, r):
    pts = []
    for a in azimuths_deg:
        pts.append([r * np.cos(np.radians(a)), r * np.sin(np.radians(a)), 0.1, 5.0])
    return np.array(pts, dtype="<f4")


def cloud_parts(pts):
    return [b"cloud", struct.pack("<dII", 1.0, 1, len(pts)), pts.tobytes()]


def test_sector_not_swept_by_this_cloud_keeps_its_obstacle():
    # A partial cloud must not write "free" (8 m) over a sector another cloud just saw.
    feed = LidarFeed(LidarCfg(history_clouds=3), FOOT)
    feed.handle(cloud_parts(sweep(range(-80, 81, 2), 1.0)))
    assert feed.latest()[0].sectors_m[0] == pytest.approx(1.0)
    feed.handle(cloud_parts(sweep(range(100, 261, 2), 3.0)))
    merged = feed.latest()[0]
    assert merged.sectors_m[0] == pytest.approx(1.0)  # still there, not reset to 8 m
    assert merged.sectors_m[18] == pytest.approx(3.0)
    assert merged.nearest_m == pytest.approx(1.0)


def test_old_return_ages_out_after_the_history():
    feed = LidarFeed(LidarCfg(history_clouds=3), FOOT)
    feed.handle(cloud_parts(sweep(range(-80, 81, 2), 1.0)))
    for _ in range(3):
        feed.handle(cloud_parts(sweep(range(100, 261, 2), 3.0)))
    assert feed.latest()[0].sectors_m[0] == 8.0  # nothing has looked there for three clouds


def test_inverted_mount_sees_an_object_below_the_sensor():
    cfg = LidarCfg(imu_upside_down=True, mount_height_m=0.30, z_min_m=0.04, z_max_m=0.45)
    p = LidarProcessor(cfg, FOOT)
    # 20 cm below an inverted sensor, 1 m ahead, on the sensor's +y side: reads as the robot's right
    pts = np.array([[0.0, 1.0, 0.20, 5.0]], dtype="<f4")
    out = p.process(pts, ts=0.0)
    assert out.sectors_m[27] == pytest.approx(1.0)  # -90 deg


# ------------------------------------------------------------------ E-stop
def test_estop_freezes_body_pose_ramp(cfg):
    robot, servos, lidar, _, _, clock = rig(cfg)
    stand(robot, lidar, clock)
    robot.handle(BodyPose(pitch_deg=15, ts=WALL))
    ticks(robot, lidar, clock, 0.1)
    robot.handle(EStop())
    pose = list(robot.pose)
    before = dict(servos.last)
    ticks(robot, lidar, clock, 1.0)
    assert robot.pose == pose  # the body stops moving at once, not at the end of the ramp
    assert max(abs(servos.last[k] - before[k]) for k in before) < 0.5


def test_release_after_estop_during_height_ramp_does_not_jump(cfg):
    robot, servos, lidar, _, _, clock = rig(cfg)
    robot.handle(Posture(posture="stand", ts=WALL))
    ticks(robot, lidar, clock, 0.5)  # part way up
    height = robot.gait.height
    assert height < cfg.geometry.body_height_m - 0.005
    robot.handle(EStop())
    ticks(robot, lidar, clock, 3.0)
    assert robot.gait.height == height  # the ramp did not run on under the E-stop
    before = dict(servos.last)
    robot.handle(EStopRelease(ts=WALL))
    ticks(robot, lidar, clock, 0.06)
    assert max(abs(servos.last[k] - before[k]) for k in before) < 3.0  # degrees: smooth, no jump


def test_latch_survives_restart_and_cold_process_sends_nothing(cfg, tmp_path):
    latch = EStopLatch(tmp_path / "estop.latch")
    robot, _, lidar, _, _, clock = rig(cfg, latch)
    stand(robot, lidar, clock)
    robot.handle(EStop())
    latch.wait()
    assert latch.read()

    latch2 = EStopLatch(tmp_path / "estop.latch")
    robot2, servos2, lidar2, _, brain2, clock2 = rig(cfg, latch2)
    assert robot2.estop and robot2.mode == "estop"
    ticks(robot2, lidar2, clock2, 0.5)
    assert servos2.writes == 0  # the pose is unknown: never guess
    robot2.handle(Posture(posture="stand", ts=WALL))
    assert events(brain2)[-1]["kind"] == "rejected"
    robot2.handle(EStopRelease(ts=WALL))
    latch2.wait()
    assert not latch2.read()
    assert robot2.mode == "relaxed" and servos2.relaxed
    ticks(robot2, lidar2, clock2, 0.2)
    assert servos2.writes == 0


async def test_shutdown_under_estop_does_not_move_or_clear_the_latch(cfg, tmp_path):
    latch = EStopLatch(tmp_path / "estop.latch")
    robot, servos, lidar, _, _, clock = rig(cfg, latch)
    stand(robot, lidar, clock)
    robot.handle(EStop())
    latch.wait()
    height = robot.target_height
    await sit_and_relax(robot)
    assert robot.estop and robot.mode == "estop" and robot.target_height == height
    assert not servos.relaxed
    assert latch.read()


# ------------------------------------------------------------------ the link and stopping
def test_wrong_version_heartbeat_does_not_feed_the_watchdog(cfg):
    robot, _, _, _, _, clock = rig(cfg)
    before = robot.last_link
    clock.t += 5
    robot.handle(Heartbeat(ts=WALL, v=1))
    assert robot.last_link == before


def test_stop_ends_a_height_change(cfg):
    robot, _, lidar, _, _, clock = rig(cfg)
    robot.handle(Posture(posture="stand", ts=WALL))
    ticks(robot, lidar, clock, 0.5)
    robot.handle(Stop(ts=WALL))
    stopped_at = robot.gait.height
    ticks(robot, lidar, clock, 1.0)
    assert robot.gait.height == pytest.approx(stopped_at, abs=1e-6)


def test_stand_is_refused_when_tilt_is_unknown(cfg):
    class NoImu(SimLidar):
        def tilt(self):
            return None, None

    robot, _, _, _, brain, _ = rig(cfg, lidar_cls=NoImu)
    robot.handle(Posture(posture="stand", ts=WALL))
    assert robot.mode == "relaxed"
    assert "tilt unknown" in events(brain)[-1]["detail"]


# ------------------------------------------------------------------ camera out of the body
async def test_body_ignores_snapshot_when_camera_is_external(cfg):
    cfg.camera.external = True
    robot, _, _, _, brain, _ = rig(cfg)
    robot.handle(Snapshot(request_id="abc", ts=WALL))
    await asyncio.sleep(0.05)
    assert brain.inbox.queue.empty()


async def test_camera_service_answers_and_confirms_the_frame(cfg):
    hub = InMemoryHub()
    t = Topics(cfg.robot_id)
    service_link = hub.endpoint([t.cmd])
    consumer = hub.endpoint([t.event, t.camera_filter])
    await service_link.start()
    await consumer.start()
    service = CameraService(cfg, FakeCamera(cfg.camera), service_link)
    await service.capture(Snapshot(request_id="f42", seq=9, trace="tr"))
    camera = consumer.inbox.queue.get_nowait()
    assert camera.topic == t.camera("f42") and camera.payload[:2] == b"\xff\xd8"
    assert service.health().metrics["frames"] == 1.0


async def test_camera_service_reports_failure_without_dying(cfg):
    class Broken:
        def snapshot(self):
            raise RuntimeError("no device")

    hub = InMemoryHub()
    t = Topics(cfg.robot_id)
    link, consumer = hub.endpoint([t.cmd]), hub.endpoint([t.event])
    await link.start()
    await consumer.start()
    service = CameraService(cfg, Broken(), link)
    await service.capture(Snapshot(request_id="x"))
    assert json.loads(consumer.inbox.queue.get_nowait().payload)["kind"] == "snapshot_failed"
    assert service.health().level == "degraded"


def test_control_process_does_not_import_opencv():
    import subprocess
    import sys

    code = (
        "import sys; import spider_body.robot; import spider_body.main; "
        "print('cv2' in sys.modules)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


# ------------------------------------------------------------------ timing and real-time setup
async def test_control_loop_records_lateness(cfg):
    robot, _, lidar, _, _, _ = rig(cfg)
    lidar.scan()
    task = asyncio.create_task(control_loop(robot))
    await asyncio.sleep(0.2)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert robot.late_hist.total > 3
    assert robot.tick_hist.total > 3
    assert robot.state().loop_late_p99_ms >= 0.0


class FakeSys:
    SCHED_FIFO = 1

    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def sched_setaffinity(self, pid, cpus):
        self.calls.append(("affinity", set(cpus)))

    def sched_param(self, priority):
        return priority

    def sched_setscheduler(self, pid, policy, param):
        if self.fail:
            raise PermissionError("not allowed")
        self.calls.append(("fifo", policy & 0xff, param))


def test_realtime_setup_order_and_reset_on_fork():
    sys = FakeSys()
    assert pin_cpu(RtCfg(cpu=0), sys) is True
    assert enable_fifo(RtCfg(priority=50), sys, lock=lambda: None) is True
    assert sys.calls == [("affinity", {0}), ("fifo", 1, 50)]


def test_realtime_setup_reports_failure_and_keeps_running():
    assert enable_fifo(RtCfg(), FakeSys(fail=True), lock=lambda: None) is False
    assert enable_fifo(RtCfg(enabled=False), FakeSys()) is False
    assert enable_fifo(RtCfg(), object()) is False  # a laptop without SCHED_FIFO


# ------------------------------------------------------------------ the servo link
def test_ssc_skips_a_frame_when_the_usb_link_is_behind(cfg):
    class Port:
        def __init__(self):
            self.out_waiting = 0
            self.sent = []

        def write(self, data):
            self.sent.append(data)

    port = Port()
    now = [0.0]
    bank = SscServoBank(cfg, port=port, clock=lambda: now[0])
    bank.write({"LF.coxa": 90.0})
    assert len(port.sent) == 1
    port.out_waiting = 10_000
    now[0] = 1.0
    bank.write({"LF.coxa": 100.0})
    assert len(port.sent) == 1  # the frame was skipped, not queued behind stale ones
    port.out_waiting = 0
    now[0] = 2.0
    bank.write({"LF.coxa": 100.0})
    assert len(port.sent) == 2


def test_latch_write_does_not_touch_the_disk_on_the_caller(tmp_path, monkeypatch):
    latch = EStopLatch(tmp_path / "estop.latch")
    calls = []
    real = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (calls.append(1), real(fd))[1])
    latch.set(True)
    latch.wait()
    assert calls and latch.read()


# ------------------------------------------------------------------ hardware watchdog line
async def test_kick_runs_only_after_a_good_tick(cfg):
    robot, _, lidar, _, _, _ = rig(cfg)
    lidar.scan()

    class Count:
        n = 0

        def toggle(self):
            Count.n += 1

    robot.kick = Count()
    task = asyncio.create_task(control_loop(robot))
    await asyncio.sleep(0.1)
    good = Count.n
    assert good > 1

    def boom(dt):
        raise RuntimeError("bus error")

    robot.tick = boom
    await asyncio.sleep(0.1)
    assert Count.n <= good + 1  # a failing tick stops the kicks, so the relay drops
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_a_failing_kick_line_counts_as_a_failed_tick(cfg):
    robot, servos, lidar, _, _, _ = rig(cfg)
    lidar.scan()

    class Broken:
        def toggle(self):
            raise OSError("gpio gone")

    robot.kick = Broken()
    with pytest.raises(OSError):
        await asyncio.wait_for(control_loop(robot), 30.0)
    assert servos.relaxed


def test_config_counts_lidar_detection_time_in_the_stop_distance(cfg):
    from pydantic import ValidationError

    from spider_body.config import BodyConfig

    data = cfg.model_dump()
    data["safety"]["stop_distance_m"] = 0.05  # enough for braking alone, not with detection
    with pytest.raises(ValidationError):
        BodyConfig.model_validate(data)


# ------------------------------------------------------------------ merged behaviours
JOINT_IDS = [f"{leg}.{j}" for leg in ("LF", "LM", "LR", "RF", "RM", "RR")
             for j in ("coxa", "femur", "tibia")]


class _Serial:
    def __init__(self, clock):
        self.clock, self.at = clock, []

    def write(self, data):
        self.at.append(self.clock())
        return len(data)


def test_ssc_keeps_25_hz_under_tick_jitter(cfg):
    random.seed(3)
    t = [0.0]
    ser = _Serial(lambda: t[0])
    bank = SscServoBank(cfg, port=ser, clock=lambda: t[0])
    for k in range(2000):
        t[0] = k * 0.02 + abs(random.gauss(0, 0.001))
        bank.write({n: 90.0 + (k % 100) / 10.0 for n in JOINT_IDS})
    gaps = [(b - a) * 1000 for a, b in zip(ser.at, ser.at[1:], strict=False)]
    assert sum(gaps) / len(gaps) < 41.0
    assert max(gaps) < 45.0


def test_legs_wake_one_at_a_time_and_height_holds_until_all_are_on(cfg):
    robot, servos, lidar, _, _, clock = rig(cfg)
    sit = cfg.geometry.sit_height_m
    robot.handle(Posture(posture="stand", ts=WALL))
    lidar.scan()
    seen_legs: list[int] = []
    first_command: dict[str, float] = {}
    for _ in range(6 * 8):
        clock.t += 0.02
        robot.handle(Heartbeat(ts=WALL))
        robot.tick(0.02)
        seen_legs.append(len(servos.last))
        for joint, deg in servos.last.items():
            first_command.setdefault(joint, deg)
        if robot._wake_tick is not None:
            assert robot.gait.height == pytest.approx(sit)
    assert seen_legs[0] == 3
    assert seen_legs == sorted(seen_legs)
    # Every joint's first command is the sit pose: no leg arrives at a lower body height.
    reference = robot.solve(robot.gait.step(0.0))
    robot.gait.height = sit
    sit_pose = robot.solve(robot.gait.step(0.0))
    assert reference is not None and sit_pose is not None
    for joint, deg in first_command.items():
        if joint != "camera_pan":  # the camera is not a leg: it comes last, centred
            assert deg == pytest.approx(sit_pose[joint], abs=0.01)
    for _ in range(40):
        clock.t += 0.02
        robot.handle(Heartbeat(ts=WALL))
        robot.tick(0.02)
    assert robot._wake_tick is None and len(servos.last) == 19  # the camera comes last
    assert robot.gait.height > sit


def test_estop_during_wake_powers_no_further_leg(cfg):
    robot, servos, lidar, _, _, clock = rig(cfg)
    robot.handle(Posture(posture="stand", ts=WALL))
    lidar.scan()
    for _ in range(9):
        clock.t += 0.02
        robot.tick(0.02)
    legs = len(servos.last)
    robot.handle(EStop(ts=WALL))
    for _ in range(100):
        clock.t += 0.02
        robot.tick(0.02)
    assert len(servos.last) == legs


def test_late_histogram_buckets(cfg):
    robot, *_ = rig(cfg)
    for ms in (0.5, 1.5, 4.0, 9.0, 19.0, 40.0):
        robot.note_wakeup(ms)
    assert robot.loop_late_hist == [1, 1, 1, 1, 1, 1]
    assert robot.loop_late_max_ms == 40.0
    assert len(robot.state().loop_late_hist) == 6
    assert robot.state().loop_late_p99_ms > 0


def test_move_refused_at_a_mid_height_left_by_a_stop(cfg):
    robot, _, lidar, _, brain, clock = rig(cfg)
    robot.handle(Posture(posture="stand", ts=WALL))
    ticks(robot, lidar, clock, 1.3)  # past the staged wake, partway up
    assert cfg.geometry.sit_height_m < robot.gait.height < cfg.geometry.body_height_m - 0.003
    robot.handle(Stop(ts=WALL, seq=1))
    ticks(robot, lidar, clock, 0.2)
    robot.handle(Move(vx=0.05, duration_s=1.0, ts=WALL, seq=2))  # a later seq: not fenced
    assert robot.move is None
    assert any(e["kind"] == "rejected" and "height" in e["detail"] for e in events(brain))


def test_relax_refused_above_the_sit_height(cfg):
    robot, servos, lidar, _, brain, clock = rig(cfg)
    stand(robot, lidar, clock)
    robot.handle(Posture(posture="sit", ts=WALL))
    ticks(robot, lidar, clock, 0.3)
    robot.handle(Stop(ts=WALL))
    ticks(robot, lidar, clock, 0.1)
    assert robot.gait.height > cfg.geometry.sit_height_m + 0.003
    robot.handle(Posture(posture="relax", ts=WALL))
    assert robot.mode == "sitting" and not servos.relaxed


def test_latch_write_failure_raises_an_error_event(cfg, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    latch = EStopLatch(blocker / "sub" / "estop")  # the parent is a file: mkdir must fail
    robot, _, lidar, _, brain, clock = rig(cfg, latch=latch)
    robot.handle(EStop(ts=WALL))
    latch.wait()
    assert latch.write_failed
    ticks(robot, lidar, clock, 0.1)
    assert any(e["kind"] == "error" and "latch" in e["detail"] for e in events(brain))


def test_gil_interval_is_set_from_config():
    previous = sys.getswitchinterval()
    try:
        set_gil_interval(RtCfg(gil_switch_ms=2.0))
        assert sys.getswitchinterval() == pytest.approx(0.002)
    finally:
        sys.setswitchinterval(previous)


class _SpyServos(FakeServoBank):
    log: list[str] = []

    def relax(self) -> None:
        _SpyServos.log.append("relax")
        super().relax()


async def _run_briefly(cfg, monkeypatch):
    hub = InMemoryHub()
    _SpyServos.log = []
    original = Robot.tick

    def spy_tick(self, dt):
        _SpyServos.log.append("tick")
        original(self, dt)

    monkeypatch.setattr(main_module, "FakeServoBank", _SpyServos)
    monkeypatch.setattr(Robot, "tick", spy_tick)
    monkeypatch.setattr(main_module, "build_link", lambda c: hub.endpoint([Topics(c.robot_id).cmd]))
    await main_module.run(cfg, sim=True, jitter_seconds=0.06)


async def test_startup_relaxes_servos_before_the_first_tick(cfg, monkeypatch):
    await _run_briefly(cfg, monkeypatch)
    assert _SpyServos.log[0] == "relax"
    assert "tick" in _SpyServos.log


async def test_startup_under_a_latched_estop_does_not_touch_the_servos(cfg, monkeypatch, tmp_path):
    path = tmp_path / "estop"
    path.write_text("latched")
    cfg.estop_latch_path = str(path)
    await _run_briefly(cfg, monkeypatch)
    assert "relax" not in _SpyServos.log
    assert "tick" in _SpyServos.log
    assert path.exists()
