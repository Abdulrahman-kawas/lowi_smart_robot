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

Expressive moves (moves.py) run while standing: Perform and Reach are validated whole before they
start, then played by tick() one frame per tick through the same IK and servo path. The mode stays
"standing" and state().perform names the move. Stop or E-stop ends a move within one tick: the
body holds that frame (each frame is statically stable) until a stand or sit command brings it
back to the neutral pose with a validated return. offer_hand retracts at once on a Stop instead.

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
    Look,
    Move,
    Perform,
    Posture,
    Reach,
    RobotEvent,
    RobotMode,
    RobotState,
    Snapshot,
    Stop,
    Topics,
)

from .config import CAMERA_PAN, JOINTS, BodyConfig
from .gait import GaitEngine
from .hw.camera import Camera
from .hw.kick import NoKick
from .hw.lidar import LidarSource
from .hw.servos import ServoBank, clamp_servo
from .kinematics import IKError, LegGeometry, body_to_leg, joint_to_servo_deg, leg_ik, rotate_rpy
from .moves import (
    DEFAULT_SPEED,
    OFFER_CLEAR_M,
    MoveError,
    MoveLibrary,
    MoveSpec,
    Runner,
    edge_clearance,
    nearest_within,
    raised_feet,
    validate,
)
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
        self.moves = MoveLibrary(cfg)
        self.perform: Runner | None = None
        self._frame = None  # (body, feet) of the move pose being sent, while it runs or holds
        self._after_recover: str | None = None  # "sit": sit down once back in the stand pose
        # Front camera pan (Look): deg, + left. None while the servos are limp: nobody knows
        # where the camera hangs, and the first command after limp snaps to pan_target.
        self.pan_deg: float | None = None
        self.pan_target = 0.0
        self._pan_rate = 0.0  # deg/s of the glide in progress

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
        elif isinstance(cmd, (Move, Look)) and cmd.seq <= self._fence.get(cmd.session, -1):
            return  # sent before a Stop that already arrived: drop silently

        if isinstance(cmd, EStop):
            self._cancel_move("estop")
            self.gait.freeze()  # hold every foot where it is: no jump
            self._hold_pan()  # and the camera where it is
            self.estop = True
            if self.mode in _ACTIVE:
                self.mode = "estop"
            if self.latch is not None:
                self.latch.set(True)
            self.emit("estop", cmd.seq, "latched", cmd.trace)
        elif isinstance(cmd, EStopRelease):
            self._release_estop(cmd)
        elif isinstance(cmd, Stop):
            self._cancel_move("stop")
            self._hold_ramps()
            self.emit("ack", cmd.seq, "stopping", cmd.trace)
        elif isinstance(cmd, Snapshot):
            if self.cfg.camera.external:
                return  # the spider-camera process answers on the same topic
            task = asyncio.get_running_loop().create_task(self._snapshot(cmd))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        elif isinstance(cmd, (Perform, Reach)):
            self._handle_perform(cmd)
        elif isinstance(cmd, Look):
            self._handle_look(cmd)
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
            self._pan_limp()
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
        self._hold_pan()

    def _hold_pan(self) -> None:
        """Stop and E-stop end a camera glide where it is, like a leg."""
        if self.pan_deg is not None:
            self.pan_target = self.pan_deg

    def _pan_limp(self) -> None:
        """The servos were cut: the camera hangs where it is. It centres on the next wake."""
        self.pan_deg, self.pan_target = None, 0.0

    def _sit_h(self) -> float:
        return self.cfg.geometry.sit_height_m

    def _stand_h(self) -> float:
        return self.cfg.geometry.body_height_m

    def _height_reached(self) -> bool:
        return abs(self.gait.height - self.target_height) < _HEIGHT_TOL_M

    def _at_height(self, height: float) -> bool:
        return abs(self.gait.height - height) < _HEIGHT_TOL_M

    def _move_busy(self) -> str | None:
        if self.perform is not None:
            return f"{self.perform.spec.name} is running; send stop first"
        if self._frame is not None:
            return "holding the last move pose; send stand first"
        return None

    def _handle_move(self, cmd: Move) -> None:
        busy = self._move_busy()
        if busy:
            self.emit("rejected", cmd.seq, busy)
            return
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
        if self.perform is not None:
            self.emit("rejected", cmd.seq, f"{self.perform.spec.name} is running; send stop first")
            return
        if self._frame is not None:  # a move was stopped part way: return to the stand first
            if cmd.posture == "relax":
                self.emit("rejected", cmd.seq, "holding a move pose; send stand, then sit")
                return
            why = self._start_recover(cmd.seq, cmd.trace, then=cmd.posture)
            if why:
                self.emit("rejected", cmd.seq, why)
            else:
                self.emit("ack", cmd.seq, f"{cmd.posture}: back to the stand pose first")
            return
        if cmd.posture == "relax":
            if self.mode == "relaxed":
                self.emit("ack", cmd.seq, "already relaxed")
            elif self.mode != "sitting" or not self._at_height(self._sit_h()):
                self.emit("rejected", cmd.seq, "sit down first, then relax")
            else:
                self.servos.relax()
                self._pan_limp()
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
        busy = self._move_busy()
        if busy:
            self.emit("rejected", cmd.seq, busy)
            return
        if self.mode != "standing":
            self.emit("rejected", cmd.seq, "body pose needs standing (not walking)")
            return
        if cmd.height_m is not None:
            lo, hi = self._sit_h() + 0.01, self._stand_h() + 0.04
            self.target_height = self.walk_height = max(lo, min(hi, cmd.height_m))
        self.pose_target = [math.radians(cmd.roll_deg), math.radians(cmd.pitch_deg),
                            math.radians(cmd.yaw_deg)]
        self.emit("ack", cmd.seq, "body pose")

    def _handle_look(self, cmd: Look) -> None:
        """Turn the camera: one absolute target, reached by a capped glide in tick()."""
        pan = self.cfg.camera_pan
        if pan is None:
            self.emit("rejected", cmd.seq, "no camera pan servo in robot.yaml", cmd.trace)
            return
        if self.estop:
            self.emit("rejected", cmd.seq, "estop is latched; send estop_release first", cmd.trace)
            return
        if self.mode not in ("sitting", "standing", "walking"):
            self.emit("rejected", cmd.seq, f"cannot look while {self.mode}; sit or stand first",
                      cmd.trace)
            return
        lo, hi = self.cfg.pan_range()
        self.pan_target = max(lo, min(hi, cmd.pan_deg))
        self._pan_rate = pan.max_rate_dps * cmd.speed
        note = "" if self.pan_target == cmd.pan_deg else f" (limited to {lo:+.0f}..{hi:+.0f})"
        self.emit("ack", cmd.seq, f"look {self.pan_target:+.0f} deg{note}", cmd.trace)

    async def _snapshot(self, cmd: Snapshot) -> None:
        try:
            data = await asyncio.to_thread(self.camera.snapshot)
        except Exception as exc:  # camera problems must not affect walking
            self.emit("snapshot_failed", cmd.seq, f"{cmd.request_id}: {exc}")
            return
        self.link.publish(self.topics.camera(cmd.request_id), data, qos=1)

    def _cancel_move(self, reason: str = "stop") -> None:
        self.move = None
        self.move_deadline = None
        self.gait.stop()
        if self.perform is not None:
            self._interrupt(reason)

    # ------------------------------------------------------------------ expressive moves
    def _move_blocker(self) -> str | None:
        """Why no move may start now, or None. Checked before anything is built."""
        s = self.cfg.safety
        if self.estop:
            return "estop is latched; send estop_release first"
        if self.mode != "standing":
            return f"cannot start a move while {self.mode}; stand first"
        busy = self._move_busy()
        if busy:
            return busy
        if self.gait.moving:
            return "stop walking first"
        if self._wake_tick is not None:
            return "still waking up"
        if not self._at_height(self._stand_h()) or not self._height_reached():
            return "not at the stand height; send stand first"
        if max(abs(a) for a in (*self.pose, *self.pose_target)) > 1e-3:
            return "the body pose is not neutral; send body_pose with zeros first"
        roll, pitch = self.lidar.tilt()
        if roll is None or pitch is None:
            return "tilt unknown: IMU is not reporting"
        if max(abs(roll), abs(pitch)) > s.max_level_deg:
            return f"not level (roll {roll:.1f}, pitch {pitch:.1f} deg)"
        summary, age = self.lidar.latest()
        if summary is None or age is None or age > s.lidar_timeout_s:
            return "LiDAR data is stale"
        return None

    def _obstacle_blocker(self, spec: MoveSpec, summary, own=None) -> str | None:
        m = self.cfg.moves
        if spec.guard == "clear":
            d, bearing = edge_clearance(summary, self.moves.geo.footprint, own)
            if d < m.clear_radius_m:
                return (f"obstacle {d:.2f} m from the legs at {bearing:.0f} deg "
                        f"(moves need {m.clear_radius_m:.2f} m clear)")
        elif spec.guard == "offer" and spec.target is not None:
            radius = math.hypot(spec.target[0], spec.target[1]) + OFFER_CLEAR_M
            r = nearest_within(summary, radius, own)
            if r is not None:
                return (f"something {r:.2f} m away, within 5 cm of where the foot would go "
                        f"({radius:.2f} m)")
        elif spec.guard == "reach" and spec.watch is not None:
            k, planned = spec.watch
            if summary.sectors_m[k] < planned - 0.03:
                return "the target moved closer"
        return None

    def _handle_perform(self, cmd: Perform | Reach) -> None:
        what = cmd.name if isinstance(cmd, Perform) else "reach"

        def refuse(reason: str) -> None:
            self.emit("perform_rejected", cmd.seq, f"{what}: {reason}", cmd.trace)

        why = self._move_blocker()
        if why:
            refuse(why)
            return
        summary, _ = self.lidar.latest()
        assert summary is not None
        try:
            if isinstance(cmd, Perform):
                spec = self.moves.get(cmd.name, cmd.leg)
            elif cmd.target == "nearest":
                spec, _ = self.moves.reach_nearest(cmd.leg, summary, cmd.speed)
            else:
                spec = self.moves.reach(cmd.leg, cmd.target)
        except MoveError as exc:
            refuse(str(exc))
            return
        why = self._obstacle_blocker(spec, summary)
        if why:
            refuse(why)
            return
        report = validate(self.moves.geo, spec, cmd.speed)
        if not report.ok:
            refuse(report.reason)
            return
        self.perform = Runner(spec, cmd.speed, cmd.seq, cmd.trace)
        self._frame = self.perform.frame()
        capped = f" (limited to {spec.max_speed:g})" if cmd.speed > spec.max_speed else ""
        extra = f", {spec.detail}" if spec.detail else ""
        self.emit("perform_started", cmd.seq,
                  f"{what}: {report.duration_s:.1f} s at speed {report.speed:g}{capped}{extra}",
                  cmd.trace)

    def _start_recover(self, seq: int | None, trace: str, then: str | None = None) -> str | None:
        """Back from a held move pose to the neutral stand, validated like any move."""
        assert self._frame is not None
        spec, report = self.moves.recovery(*self._frame)
        if not report.ok:
            return f"cannot plan a safe way back to stand ({report.reason}); lift the robot"
        self.perform = Runner(spec, DEFAULT_SPEED, seq, trace)
        self._after_recover = then
        self.emit("perform_started", seq, f"recover: {report.duration_s:.1f} s", trace)
        return None

    def _interrupt(self, reason: str) -> None:
        r = self.perform
        assert r is not None
        self.perform = None
        self.emit("perform_done", r.seq, f"{r.spec.name} interrupted: {reason}", r.trace)
        if reason == "fallen":
            self._frame = None
            return
        if r.spec.retract_on_stop and reason != "estop" and self._frame is not None:
            why = self._start_recover(r.seq, r.trace)
            if why:
                self.emit("error", r.seq, why)

    def _guard_perform(self) -> None:
        """Runtime checks while a move plays. Any failure ends it like a Stop."""
        r = self.perform
        assert r is not None and self._frame is not None
        if r.spec.guard == "none":
            return
        s = self.cfg.safety
        summary, age = self.lidar.latest()
        roll, _ = self.lidar.tilt()
        if summary is None or age is None or age > s.lidar_timeout_s:
            seq = r.seq
            self._cancel_move("LiDAR data is stale")
            self.emit("error", seq, "LiDAR data is stale; move stopped")
            return
        if roll is None:
            seq = r.seq
            self._cancel_move("tilt unknown")
            self.emit("error", seq, "tilt unknown: IMU is not reporting; move stopped")
            return
        if r.spec.guard == "offer" and not r.guarding:
            return  # the hand is out: someone may come close now, the foot does not move to them
        why = self._obstacle_blocker(r.spec, summary, raised_feet(self.moves.geo, *self._frame))
        if why:
            seq, trace = r.seq, r.trace
            self._cancel_move("obstacle")
            self.emit("obstacle_stop", seq, why, trace)

    def _finish_perform(self) -> None:
        r = self.perform
        assert r is not None
        self.perform = None
        self._frame = None
        self.pose = [0.0, 0.0, 0.0]
        self.pose_target = [0.0, 0.0, 0.0]
        self.gait.height = self.target_height = self.walk_height = self._stand_h()
        then, self._after_recover = self._after_recover, None
        if r.spec.name == "recover" and then == "sit":
            self.target_height = self._sit_h()
            self.mode = "sitting"
        self.emit("perform_done", r.seq, f"{r.spec.name} done", r.trace)

    @property
    def body_shift(self) -> tuple[float, float]:
        """Body translation of the move in progress (stance frame), for the viewer."""
        if self._frame is None:
            return (0.0, 0.0)
        return (float(self._frame[0][4]), float(self._frame[0][5]))

    # ------------------------------------------------------------------ control loop
    def tick(self, dt: float) -> None:
        now = self.clock()
        s = self.cfg.safety

        if self.latch is not None and self.latch.write_failed != self._latch_error_reported:
            self._latch_error_reported = self.latch.write_failed
            if self.latch.write_failed:
                self.emit("error", self.last_seq, "E-stop latch could not be saved to disk")

        # 1. link watchdog: the cloud went quiet while we were walking
        if (self.move is not None or self.gait.moving or self.perform is not None) and \
                now - self.last_link > s.link_timeout_s:
            self._cancel_move("link lost")
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
            self._cancel_move("fallen")
            self._frame = None
            self.gait.halt_now()
            self.servos.relax()
            self._pan_limp()
            self.mode = "fallen"
            self._wake_tick = None
            self.emit("fallen", self.last_seq, f"roll={roll} pitch={pitch}; servos relaxed")
            return
        if tilt == "tilt" and (self.move is not None or self.perform is not None):
            self._cancel_move("tilt")
            if not self._tilt_reported:
                self._tilt_reported = True
                self.emit("tilt", self.last_seq, f"roll={roll:.0f} pitch={pitch:.0f}; stopped")
        elif tilt == "ok":
            self._tilt_reported = False

        # 4. obstacle / LiDAR limits on the active Move
        self.lidar.set_height_offset(self.gait.height - self.cfg.geometry.body_height_m)
        self.lidar.set_camera_pan(self.pan_deg)  # the self-mask follows the camera
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
        elif self.perform is not None and not self.estop:
            self.gait.stop()
            self.limiter = None
            self._guard_perform()
        else:
            self.gait.stop()
            if self.move is None:
                self.limiter = None if self._frame is None else "holding a move pose; send stand"

        # 4b. the move in progress: one frame per tick
        if self.perform is not None and not self.estop:
            self._frame = self.perform.advance(dt)
            if self.perform.done:
                self._finish_perform()

        # 5. posture ramps. Frozen during an E-stop (the body must not keep moving) and during a
        # staged wake (a leg not yet powered must first arrive at the sit pose).
        g = self.cfg.gait
        if not self.estop and self._wake_tick is None and self._frame is None:
            self.gait.height = _approach(
                self.gait.height, self.target_height, g.posture_speed_mps * dt
            )
            for i in range(3):
                self.pose[i] = _approach(self.pose[i], self.pose_target[i], _POSE_RATE * dt)

        # 5b. camera pan: a capped glide, frozen under an E-stop like the legs
        if self.cfg.camera_pan is not None and self.mode in _ACTIVE and not self.estop:
            if self.pan_deg is None:  # first command after limp: the board snaps there anyway
                self.pan_deg = self.pan_target
            else:
                self.pan_deg = _approach(self.pan_deg, self.pan_target, self._pan_rate * dt)

        if self.mode in ("standing", "walking"):
            self.mode = "walking" if self.gait.moving else "standing"

        # 6. kinematics -> servos
        if self._cold_estop:
            return  # latched before this process started: the pose is unknown, send nothing
        if self.mode in _ACTIVE:
            if self._frame is not None:  # a move frame (held still under an E-stop)
                feet, self.pose, self.gait.height = self.moves.geo.to_robot(*self._frame)
            else:
                feet = self.gait.step(dt)
            angles = self.solve(feet)
            if angles is not None:
                if self.cfg.camera_pan is not None and self.pan_deg is not None:
                    angles[CAMERA_PAN] = self.cfg.pan_servo_deg(self.pan_deg)
                self.servos.write(self._staged(angles))
            elif self.perform is not None:  # validated, so this is a bug: stop the move
                self._cancel_move("IK failed")

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
        awake = set(_WAKE_ORDER[:legs_on])  # the camera ("camera_pan") waits for every leg
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
                    out[f"{leg.name}.{joint}"], _ = clamp_servo(self.cfg, servo, deg)
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
            perform=self.perform.spec.name if self.perform is not None else None,
            camera_pan_deg=None if self.pan_deg is None else round(self.pan_deg, 1),
        )
