"""The body's state machine: commands in, servo angles out, safety in between.

Modes
  relaxed  servos limp (startup and after `relax`)       -> stand / sit
  sitting  belly near the ground, legs holding            -> stand / relax
  standing at body height, not moving                     -> move / sit / body_pose
  walking  gait running (a Move is active or ramping out)  -> stop
  estop    latched: holds the pose, ignores motion until estop_release. The latch survives a
           crash and a reboot; a process that starts latched does not know the pose, so it sends
           nothing to the servos and a release goes to relaxed.
  fallen   tilt past fall_tilt: servos limp until a new stand/sit command

tick() runs at control_hz (50 Hz). Order inside one tick:
  link watchdog -> move deadline -> tilt -> obstacle/LiDAR limits -> posture ramps -> IK -> servos
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Callable

from spider_common.link import Link
from spider_common.obs import Histogram
from spider_common.protocol import (
    PROTOCOL_VERSION,
    BodyPose,
    Command,
    EStop,
    EStopRelease,
    EventKind,
    Heartbeat,
    Move,
    Posture,
    RobotEvent,
    RobotMode,
    RobotState,
    Snapshot,
    Stop,
    Topics,
)

from .config import JOINTS, BodyConfig
from .gait import GaitEngine
from .hw.camera import Camera
from .hw.kick import NoKick
from .hw.lidar import LidarSource
from .hw.servos import ServoBank, clamp_servo
from .kinematics import IKError, LegGeometry, body_to_leg, joint_to_servo_deg, leg_ik, rotate_rpy
from .safety import EStopLatch, SafetyGuard

log = logging.getLogger(__name__)

_ACTIVE: set[str] = {"sitting", "standing", "walking", "estop"}
_POSE_RATE = math.radians(30.0)  # body roll/pitch/yaw change rate, rad/s
_HEIGHT_TOL_M = 0.003
_LATE_BUCKETS_MS = (1.0, 2.0, 5.0, 10.0, 20.0)  # upper edges of loop_late_hist
_WAKE_ORDER = ("LF", "RM", "LR", "RF", "LM", "RR")
_WAKE_TICKS_PER_LEG = 8  # 0.16 s at 50 Hz: the first command after limp cannot be slewed


def _approach(cur: float, target: float, step: float) -> float:
    return min(target, cur + step) if target > cur else max(target, cur - step)


class Robot:
    def __init__(
        self,
        cfg: BodyConfig,
        servos: ServoBank,
        lidar: LidarSource,
        camera: Camera,
        link: Link,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
        latch: EStopLatch | None = None,
    ) -> None:
        self.cfg = cfg
        self.servos, self.lidar, self.camera, self.link = servos, lidar, camera, link
        self.clock, self.wall = clock, wall
        self.topics = Topics(cfg.robot_id)
        self.gait = GaitEngine(cfg.legs, cfg.geometry, cfg.gait)
        g = cfg.geometry
        self.guard = SafetyGuard(cfg.safety, (g.footprint_x_m, g.footprint_y_m))
        self.geom = LegGeometry(g.coxa_m, g.femur_m, g.tibia_m)

        self.latch = latch
        self.estop = latch.read() if latch is not None else False
        self._cold_estop = self.estop  # latched before this process started: pose unknown
        self.mode: RobotMode = "estop" if self.estop else "relaxed"
        self.target_height = g.sit_height_m
        self.walk_height = g.body_height_m  # the height a Move is allowed at
        self.pose = [0.0, 0.0, 0.0]  # roll, pitch, yaw (rad), current
        self.pose_target = [0.0, 0.0, 0.0]
        self.move: Move | None = None
        self.move_deadline: float | None = None
        self.limiter: str | None = None
        self.last_seq = 0
        self.last_link = clock()
        self._link_lost_reported = False
        self._tilt_reported = False
        self._stale_reported = False
        self._ik_error_reported = False
        self._tasks: set[asyncio.Task] = set()
        # Ordering fence: MQTT does not guarantee order, so a Move that was sent before a
        # Stop/E-stop but arrives after it must be dropped. Per brain session.
        self._fence: dict[str, int] = {}
        self.loop_overruns = 0
        self.loop_max_ms = 0.0
        self.loop_late_max_ms = 0.0
        self.late_hist = Histogram()
        self.loop_late_hist = [0] * (len(_LATE_BUCKETS_MS) + 1)
        self._wake_tick: int | None = None  # staged wake from limp, one leg at a time
        self._latch_error_reported = False
        self.tick_hist = Histogram()
        self.rt_ok = False
        self.kick = NoKick()  # the hardware watchdog pin, when a relay board is fitted

    # ------------------------------------------------------------------ events
    def emit(
        self, kind: EventKind, seq: int | None = None, detail: str = "", trace: str = ""
    ) -> None:
        if kind in ("rejected", "error", "obstacle_stop", "fallen", "tilt", "link_lost"):
            log.warning("event %s seq=%s %s", kind, seq, detail)
        event = RobotEvent(robot_id=self.cfg.robot_id, kind=kind, seq=seq, detail=detail,
                           trace=trace)
        self.link.publish(self.topics.event, event.model_dump_json(), qos=1)

    # ------------------------------------------------------------------ commands
    def handle(self, cmd: Command) -> None:
        if cmd.v != PROTOCOL_VERSION:  # checked first: a wrong version must not feed the watchdog
            self.emit("rejected", cmd.seq,
                      f"protocol v{cmd.v} not supported (body speaks v{PROTOCOL_VERSION})")
            return
        self.last_link = self.clock()
        self._link_lost_reported = False
        if isinstance(cmd, Heartbeat):
            return
        self.last_seq = max(self.last_seq, cmd.seq)

        # Stopping is always allowed, however old. Everything else must be fresh.
        if not isinstance(cmd, (EStop, Stop)):
            age = self.wall() - cmd.ts
            if abs(age) > self.cfg.safety.max_cmd_age_s:
                self.emit("rejected", cmd.seq, f"stale command ({age:.1f} s); check NTP sync")
                return
        if isinstance(cmd, (EStop, Stop)):
            self._fence[cmd.session] = max(self._fence.get(cmd.session, -1), cmd.seq)
        elif isinstance(cmd, Move) and cmd.seq <= self._fence.get(cmd.session, -1):
            return  # sent before a Stop that already arrived: drop silently

        if isinstance(cmd, EStop):
            self._cancel_move()
            self.gait.freeze()  # hold every foot where it is: no jump
            self.estop = True
            if self.mode in _ACTIVE:
                self.mode = "estop"
            if self.latch is not None:
                self.latch.set(True)
            self.emit("estop", cmd.seq, "latched", cmd.trace)
        elif isinstance(cmd, EStopRelease):
            self._release_estop(cmd)
        elif isinstance(cmd, Stop):
            self._cancel_move()
            self._hold_ramps()
            self.emit("ack", cmd.seq, "stopping", cmd.trace)
        elif isinstance(cmd, Snapshot):
            if self.cfg.camera.external:
                return  # the spider-camera process answers on the same topic
            task = asyncio.get_running_loop().create_task(self._snapshot(cmd))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        elif self.estop:
            self.emit("rejected", cmd.seq, "estop is latched; send estop_release first")
        elif isinstance(cmd, Move):
            self._handle_move(cmd)
        elif isinstance(cmd, Posture):
            self._handle_posture(cmd)
        elif isinstance(cmd, BodyPose):
            self._handle_body_pose(cmd)

    def _release_estop(self, cmd: EStopRelease) -> None:
        self.estop = False
        if self.latch is not None:
            self.latch.set(False)
        if self._cold_estop:  # this process never knew the pose: go limp rather than guess
            self._cold_estop = False
            self.servos.relax()
            self.mode = "relaxed"
            self.emit("ack", cmd.seq, "estop released; servos relaxed", cmd.trace)
            return
        self.gait.unfreeze()
        if self.mode == "estop":
            self.mode = "standing" if self.target_height > self._sit_h() else "sitting"
        self.emit("ack", cmd.seq, "estop released", cmd.trace)

    def _hold_ramps(self) -> None:
        """Stop means stop: a height or body-pose change in progress ends where it is."""
        self.target_height = self.gait.height
        self.pose_target = list(self.pose)

    def _sit_h(self) -> float:
        return self.cfg.geometry.sit_height_m

    def _stand_h(self) -> float:
        return self.cfg.geometry.body_height_m

    def _height_reached(self) -> bool:
        return abs(self.gait.height - self.target_height) < _HEIGHT_TOL_M

    def _at_height(self, height: float) -> bool:
        return abs(self.gait.height - height) < _HEIGHT_TOL_M

    def _handle_move(self, cmd: Move) -> None:
        if self.mode not in ("standing", "walking"):
            self.emit("rejected", cmd.seq, f"cannot move while {self.mode}; stand first")
            return
        if not self._height_reached() or not self._at_height(self.walk_height):
            # A Stop during a ramp leaves the target at a mid height, so "reached" is not enough.
            self.emit("rejected", cmd.seq, "not at walking height; stand first")
            return
        new_goal = self.move is None or (cmd.vx, cmd.vy, cmd.wz, cmd.gait) != (
            self.move.vx, self.move.vy, self.move.wz, self.move.gait)
        self.move = cmd
        self.move_deadline = self.clock() + cmd.duration_s
        self.pose_target = [0.0, 0.0, 0.0]  # walk level: the LiDAR height band assumes it
        if new_goal:  # renewals of the same goal are not acked (saves 2 messages/s)
            self._stale_reported = False
            self.emit("ack", cmd.seq, "moving", cmd.trace)

    def _handle_posture(self, cmd: Posture) -> None:
        if cmd.posture == "relax":
            if self.mode == "relaxed":
                self.emit("ack", cmd.seq, "already relaxed")
            elif self.mode != "sitting" or not self._at_height(self._sit_h()):
                self.emit("rejected", cmd.seq, "sit down first, then relax")
            else:
                self.servos.relax()
                self.mode = "relaxed"
                self._wake_tick = None
                self.emit("ack", cmd.seq, "relaxed")
            return
        if self.gait.moving:
            self.emit("rejected", cmd.seq, "stop walking first")
            return
        if self.mode in ("relaxed", "fallen"):
            roll, _ = self.lidar.tilt()
            if roll is None and self.cfg.lidar.enabled and self.cfg.safety.require_lidar:
                self.emit("rejected", cmd.seq, "tilt unknown: IMU is not reporting")
                return
            # servos jump to the sit pose first: place the robot on its belly before this
            self.gait.height = self._sit_h()
            self.pose = [0.0, 0.0, 0.0]
            self.pose_target = [0.0, 0.0, 0.0]
            self._wake_tick = 0  # bring the legs in one at a time: inrush and pinch
        if cmd.posture == "stand":
            self.target_height = self.walk_height = self._stand_h()
            self.mode = "standing"
        else:
            self.target_height = self._sit_h()
            self.pose_target = [0.0, 0.0, 0.0]
            self.mode = "sitting"
        self.emit("ack", cmd.seq, cmd.posture)

    def _handle_body_pose(self, cmd: BodyPose) -> None:
        if self.mode != "standing":
            self.emit("rejected", cmd.seq, "body pose needs standing (not walking)")
            return
        if cmd.height_m is not None:
            lo, hi = self._sit_h() + 0.01, self._stand_h() + 0.04
            self.target_height = self.walk_height = max(lo, min(hi, cmd.height_m))
        self.pose_target = [math.radians(cmd.roll_deg), math.radians(cmd.pitch_deg),
                            math.radians(cmd.yaw_deg)]
        self.emit("ack", cmd.seq, "body pose")

    async def _snapshot(self, cmd: Snapshot) -> None:
        try:
            data = await asyncio.to_thread(self.camera.snapshot)
        except Exception as exc:  # camera problems must not affect walking
            self.emit("snapshot_failed", cmd.seq, f"{cmd.request_id}: {exc}")
            return
        self.link.publish(self.topics.camera(cmd.request_id), data, qos=1)

    def _cancel_move(self) -> None:
        self.move = None
        self.move_deadline = None
        self.gait.stop()

    # ------------------------------------------------------------------ control loop
    def tick(self, dt: float) -> None:
        now = self.clock()
        s = self.cfg.safety

        if self.latch is not None and self.latch.write_failed != self._latch_error_reported:
            self._latch_error_reported = self.latch.write_failed
            if self.latch.write_failed:
                self.emit("error", self.last_seq, "E-stop latch could not be saved to disk")

        # 1. link watchdog: the cloud went quiet while we were walking
        if (self.move is not None or self.gait.moving) and now - self.last_link > s.link_timeout_s:
            self._cancel_move()
            if not self._link_lost_reported:
                self._link_lost_reported = True
                self.emit("link_lost", self.last_seq, "no heartbeat; stopped")

        # 2. every Move ends by itself
        if self.move is not None and self.move_deadline is not None and now >= self.move_deadline:
            done = self.move
            self._cancel_move()
            self.emit("move_done", done.seq, "", done.trace)

        # 3. tilt / fall
        roll, pitch = self.lidar.tilt()
        tilt = self.guard.tilt_state(roll, pitch)
        if tilt == "fallen" and self.mode not in ("relaxed", "fallen"):
            self._cancel_move()
            self.gait.halt_now()
            self.servos.relax()
            self.mode = "fallen"
            self._wake_tick = None
            self.emit("fallen", self.last_seq, f"roll={roll} pitch={pitch}; servos relaxed")
            return
        if tilt == "tilt" and self.move is not None:
            self._cancel_move()
            if not self._tilt_reported:
                self._tilt_reported = True
                self.emit("tilt", self.last_seq, f"roll={roll:.0f} pitch={pitch:.0f}; stopped")
        elif tilt == "ok":
            self._tilt_reported = False

        # 4. obstacle / LiDAR limits on the active Move
        self.lidar.set_height_offset(self.gait.height - self.cfg.geometry.body_height_m)
        level = max(abs(a) for a in self.pose) <= math.radians(s.max_level_deg)
        tilt_unknown = roll is None and self.cfg.lidar.enabled and s.require_lidar
        if self.move is not None and not self.estop and (not level or tilt_unknown):
            # walk only with a level body (LiDAR height band) and a known tilt (fall check)
            self.limiter = "leveling body" if not level else "imu_stale"
            self.gait.stop()
        elif self.move is not None and not self.estop:
            summary, age = self.lidar.latest()
            lim = self.guard.limit_motion(self.move.vx, self.move.vy, self.move.wz, summary, age)
            self.limiter = lim.reason
            blocked = lim.reason is not None and (
                lim.reason.startswith("obstacle")
                or (lim.reason.startswith("too close to turn") and abs(lim.vx) + abs(lim.vy) < 1e-4)
            )
            if blocked:
                blocked_move = self.move
                self._cancel_move()
                self.emit("obstacle_stop", blocked_move.seq, lim.reason, blocked_move.trace)
            elif lim.reason == "lidar_stale" and not self._stale_reported:
                self._stale_reported = True
                self.emit("error", self.move.seq, "LiDAR data is stale; not moving")
            else:
                self.gait.set_velocity(lim.vx, lim.vy, lim.wz, self.move.gait)
        else:
            self.gait.stop()
            if self.move is None:
                self.limiter = None

        # 5. posture ramps. Frozen during an E-stop (the body must not keep moving) and during a
        # staged wake (a leg not yet powered must first arrive at the sit pose).
        g = self.cfg.gait
        if not self.estop and self._wake_tick is None:
            self.gait.height = _approach(
                self.gait.height, self.target_height, g.posture_speed_mps * dt
            )
            for i in range(3):
                self.pose[i] = _approach(self.pose[i], self.pose_target[i], _POSE_RATE * dt)

        if self.mode in ("standing", "walking"):
            self.mode = "walking" if self.gait.moving else "standing"

        # 6. kinematics -> servos
        if self._cold_estop:
            return  # latched before this process started: the pose is unknown, send nothing
        if self.mode in _ACTIVE:
            feet = self.gait.step(dt)
            angles = self.solve(feet)
            if angles is not None:
                self.servos.write(self._staged(angles))

    def _staged(self, angles: dict[str, float]) -> dict[str, float]:
        """After limp the SSC-32U ignores T on the first command, so each leg snaps to place."""
        if self._wake_tick is None:
            return angles
        legs_on = 1 + self._wake_tick // _WAKE_TICKS_PER_LEG
        if legs_on >= len(_WAKE_ORDER):
            self._wake_tick = None
            return angles
        if not self.estop:  # an E-stop during the wake must not power any further leg
            self._wake_tick += 1
        awake = set(_WAKE_ORDER[:legs_on])
        return {joint: deg for joint, deg in angles.items() if joint.split(".")[0] in awake}

    def note_wakeup(self, late_ms: float) -> None:
        """How late this tick started against its schedule (the tick duration hides this)."""
        self.late_hist.record(late_ms)
        self.loop_late_max_ms = max(self.loop_late_max_ms, late_ms)
        for i, edge in enumerate(_LATE_BUCKETS_MS):
            if late_ms < edge:
                self.loop_late_hist[i] += 1
                return
        self.loop_late_hist[-1] += 1

    def solve(self, feet: dict[str, tuple[float, float, float]]) -> dict[str, float] | None:
        g = self.cfg.geometry
        neutral = {"coxa": g.coxa_neutral_deg, "femur": g.femur_neutral_deg,
                   "tibia": g.tibia_neutral_deg}
        out: dict[str, float] = {}
        try:
            for leg in self.cfg.legs:
                p = rotate_rpy(feet[leg.name], *self.pose, inverse=True)
                lx, ly, lz = body_to_leg(p, leg.mount_x, leg.mount_y,
                                         math.radians(leg.mount_angle_deg))
                j = leg_ik(lx, ly, lz, self.geom)
                for joint, rad in zip(JOINTS, (j.coxa, j.femur, j.tibia), strict=True):
                    servo = getattr(leg, joint)
                    deg = joint_to_servo_deg(rad, neutral[joint], servo.direction, servo.trim_deg)
                    out[f"{leg.name}.{joint}"], _ = clamp_servo(servo, deg)
        except IKError as exc:
            if not self._ik_error_reported:
                self._ik_error_reported = True
                self.emit("error", self.last_seq, f"IK: {exc}; holding last pose")
            return None
        self._ik_error_reported = False
        return out

    # ------------------------------------------------------------------ telemetry
    def state(self) -> RobotState:
        summary, age = self.lidar.latest()
        roll, pitch = self.lidar.tilt()
        eff = self.gait.effective
        remaining = 0.0
        if self.move_deadline is not None:
            remaining = max(0.0, self.move_deadline - self.clock())
        return RobotState(
            robot_id=self.cfg.robot_id,
            mode=self.mode,
            vx=round(eff.vx, 4), vy=round(eff.vy, 4), wz=round(eff.wz, 4),
            move_remaining_s=round(remaining, 2),
            roll_deg=None if roll is None else round(roll, 1),
            pitch_deg=None if pitch is None else round(pitch, 1),
            lidar=summary,
            lidar_age_s=None if age is None else round(age, 2),
            last_seq=self.last_seq,
            link_ok=self.clock() - self.last_link <= self.cfg.safety.link_timeout_s,
            estop=self.estop,
            limiter=self.limiter,
            loop_overruns=self.loop_overruns,
            loop_max_ms=round(self.loop_max_ms, 2),
            loop_late_max_ms=round(self.loop_late_max_ms, 2),
            loop_late_p99_ms=round(self.late_hist.percentile(0.99), 2),
            loop_late_hist=list(self.loop_late_hist),
            rt_ok=self.rt_ok,
        )
