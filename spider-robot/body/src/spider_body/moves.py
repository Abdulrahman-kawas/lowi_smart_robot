"""Expressive moves: keyframes, minimum-jerk interpolation, a validator and the built-in moves.

A move is a list of keyframes. Each keyframe gives
  body  dz (m, height above the stand height), roll, pitch, yaw (deg), x, y (m, body shift)
  feet  per leg (dx, dy, lift) in metres: dx, dy from the leg's neutral foot point on the floor,
        lift = height of the foot above the floor
in the stance frame: the body frame at the moment the move starts, level, on the floor plane.
Between keyframes every value follows the same minimum-jerk curve, so each segment starts and
ends at rest. Signs follow kinematics.rotate_rpy: roll > 0 lifts the left side, pitch > 0 lowers
the nose, yaw > 0 turns left.

Times are given at the default speed 0.5. A speed s plays every segment 0.5 / s times as long,
except "fixed" segments (holds, breathing), which keep their length at every speed.

validate() samples a move every 10 ms of real time, at the speed it will run, and checks:
  * at least 3 feet on the floor, and the body centre inside their polygon by support_margin_m
  * no foot slides while it is on the floor
  * every leg reachable by IK, every servo inside its limits (BodyConfig.limits_of, no clamping)
  * every servo slower than max_joint_speed_dps
  * body height between the sit height and the stand height + 4 cm
  * body shift within max_shift_m (2 cm for attack_stance) of where the move started
  * starts and ends in the neutral stand pose, lasts at most max_duration_s
A move that fails any check is refused before it starts, never clipped halfway.

Everything is plain numpy on a few thousand samples, a few milliseconds: it runs inside
Robot.handle without holding up the 50 Hz tick. Running a move is Robot.tick's job (robot.py).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field, replace

import numpy as np
from spider_common.protocol import LidarSummary

from .config import JOINTS, LEG_NAMES, BodyConfig

BODY_KEYS = ("dz", "roll", "pitch", "yaw", "x", "y")
LEGS = LEG_NAMES  # ("LF", "LM", "LR", "RF", "RM", "RR"): the order of every feet array
_IDX = {name: i for i, name in enumerate(LEGS)}
_MIRROR = {"LF": "RF", "LM": "RM", "LR": "RR", "RF": "LF", "RM": "LM", "RR": "LR"}
TRIPOD_A = ("LF", "RM", "LR")
TRIPOD_B = ("RF", "LM", "RR")

DEFAULT_SPEED = 0.5
CHECK_DT = 0.01  # validate every 10 ms of real time
GROUND_EPS = 5e-4  # a foot lower than this is on the floor
SLIDE_EPS = 2e-4  # a foot on the floor may not move more than this per sample
MAX_RISE_M = 0.04  # body at most this far above the stand height (as BodyPose)
ATTACK_MAX_SPEED = 0.7
ATTACK_MAX_SHIFT_M = 0.02
OFFER_MAX_SPEED = 0.4
OFFER_CLEAR_M = 0.05  # offer_hand: nothing closer than this beyond the foot target
OFFER_HOLD_S = 5.0
REACH_SHORT_M = 0.01  # touch = stop this far short of the target
REACH_HOLD_S = 1.0
REACH_SECTOR_DEG = 60.0  # "nearest" looks this far either side of straight ahead
SELF_MASK_M = 0.04  # LiDAR returns this close to one of our own raised feet are our leg


class MoveError(ValueError):
    """A move cannot be built for this robot (for example a target out of reach)."""


# ------------------------------------------------------------------ keyframes
@dataclass(frozen=True)
class Keyframe:
    t: float  # seconds from the start, at the default speed
    body: tuple[float, ...]  # BODY_KEYS
    feet: tuple[tuple[float, float, float], ...]  # per leg in LEGS order
    fixed: bool = False  # the segment that ends here keeps its length at every speed


@dataclass(frozen=True)
class MoveSpec:
    name: str
    frames: tuple[Keyframe, ...]
    max_speed: float = 1.0  # a faster request runs at this speed
    max_shift_m: float | None = None  # None: cfg.moves.max_shift_m
    from_neutral: bool = True  # False only for the return from a held pose
    guard: str = "clear"  # runtime obstacle rule: clear | offer | reach | none
    guard_until: float = math.inf  # offer: the rule applies until this time (default speed)
    retract_on_stop: bool = False  # a Stop starts the return to stand at once (offer_hand)
    watch: tuple[int, float] | None = None  # reach: (sector, range) that must not come closer
    target: tuple[float, float, float] | None = None  # reach/offer: the foot target, stance frame
    detail: str = ""

    def times(self, speed: float) -> np.ndarray:
        k = DEFAULT_SPEED / speed
        out = [0.0]
        for a, b in zip(self.frames, self.frames[1:], strict=False):
            out.append(out[-1] + (b.t - a.t) * (1.0 if b.fixed else k))
        return np.array(out)

    def duration(self, speed: float) -> float:
        return float(self.times(speed)[-1])

    def arrays(self) -> tuple[np.ndarray, np.ndarray]:
        body = np.array([f.body for f in self.frames], dtype=float)
        feet = np.array([f.feet for f in self.frames], dtype=float)
        return body, feet


def _frame_at(spec: MoveSpec, t: float) -> int:
    """Index of the keyframe at time t (default speed)."""
    return min(range(len(spec.frames)), key=lambda i: abs(spec.frames[i].t - t))


def _min_jerk(tau: np.ndarray) -> np.ndarray:
    return tau**3 * (10.0 - 15.0 * tau + 6.0 * tau**2)


def sample(
    times: np.ndarray, body: np.ndarray, feet: np.ndarray, t: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Body (N, 6) and feet (N, 6, 3) at real times t, minimum-jerk between keyframes."""
    t = np.clip(np.asarray(t, dtype=float), 0.0, times[-1])
    i = np.clip(np.searchsorted(times, t, side="right") - 1, 0, len(times) - 2)
    span = times[i + 1] - times[i]
    tau = np.clip((t - times[i]) / np.where(span > 0, span, 1.0), 0.0, 1.0)
    s = _min_jerk(tau)
    b = body[i] + (body[i + 1] - body[i]) * s[:, None]
    f = feet[i] + (feet[i + 1] - feet[i]) * s[:, None, None]
    return b, f


class Choreo:
    """Builds keyframes. Each call adds one segment; values not named keep their last value."""

    def __init__(self, body: Iterable[float] | None = None, feet: np.ndarray | None = None):
        self.t = 0.0
        self.body = dict(zip(BODY_KEYS, body if body is not None else [0.0] * 6, strict=True))
        start = feet if feet is not None else np.zeros((6, 3))
        self.feet = {leg: tuple(float(v) for v in start[i]) for i, leg in enumerate(LEGS)}
        self.frames: list[Keyframe] = [self._frame(False)]

    def _frame(self, fixed: bool) -> Keyframe:
        return Keyframe(round(self.t, 6), tuple(self.body[k] for k in BODY_KEYS),
                        tuple(self.feet[leg] for leg in LEGS), fixed)

    def to(self, dt: float, fixed: bool = False, **values: float | tuple[float, float, float]
           ) -> Choreo:
        """to(0.4, pitch=8, LF=(0.02, 0.0, 0.06)): body keys and leg names, absolute values."""
        if dt <= 0:
            raise ValueError("segments need a positive duration")
        for key, v in values.items():
            if key in self.body:
                self.body[key] = float(v)  # type: ignore[arg-type]
            elif key in self.feet:
                self.feet[key] = tuple(float(c) for c in v)  # type: ignore[union-attr]
            else:
                raise KeyError(key)
        self.t += dt
        self.frames.append(self._frame(fixed))
        return self

    def hold(self, dt: float, fixed: bool = False) -> Choreo:
        return self.to(dt, fixed)

    def lift(self, dt: float, legs: Iterable[str], height: float) -> Choreo:
        """Straight up or down: a foot leaves and meets the floor without sliding."""
        return self.to(dt, **{leg: (*self.feet[leg][:2], height) for leg in legs})

    def step(self, leg: str, dx: float, dy: float, height: float = 0.025,
             dt: float = 0.3) -> Choreo:
        """Lift, move in the air, put down: a foot on the floor never slides."""
        self.lift(dt, [leg], height)
        self.to(dt, **{leg: (dx, dy, height)})
        return self.lift(dt, [leg], 0.0)

    def home_body(self, dt: float) -> Choreo:
        return self.to(dt, **dict.fromkeys(BODY_KEYS, 0.0))

    def spec(self, name: str, **kw) -> MoveSpec:
        return MoveSpec(name, tuple(self.frames), **kw)


def mirror(spec: MoveSpec) -> MoveSpec:
    """Left <-> right: legs swap sides, and y, roll and yaw change sign."""
    sign = np.array([1.0, -1.0, 1.0, -1.0, 1.0, -1.0])  # dz roll pitch yaw x y
    frames = []
    for f in spec.frames:
        body = tuple(float(v) for v in np.array(f.body) * sign)
        feet = tuple((f.feet[_IDX[_MIRROR[leg]]][0], -f.feet[_IDX[_MIRROR[leg]]][1],
                      f.feet[_IDX[_MIRROR[leg]]][2]) for leg in LEGS)
        frames.append(Keyframe(f.t, body, feet, f.fixed))
    target = spec.target
    if target is not None:
        target = (target[0], -target[1], target[2])
    return replace(spec, frames=tuple(frames), target=target)


# ------------------------------------------------------------------ robot geometry
@dataclass
class Geometry:
    """The numbers of one BodyConfig the moves need, as arrays in LEGS order."""

    cfg: BodyConfig
    neutral: np.ndarray = field(init=False)  # (6, 2) neutral foot points
    mounts: np.ndarray = field(init=False)  # (6, 2)
    angles: np.ndarray = field(init=False)  # (6,) mount angles, rad
    direction: np.ndarray = field(init=False)  # (6, 3)
    trim: np.ndarray = field(init=False)
    lo: np.ndarray = field(init=False)
    hi: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        g, legs = self.cfg.geometry, {leg.name: leg for leg in self.cfg.legs}
        ordered = [legs[name] for name in LEGS]
        self.angles = np.radians([leg.mount_angle_deg for leg in ordered])
        self.mounts = np.array([(leg.mount_x, leg.mount_y) for leg in ordered])
        self.neutral = self.mounts + g.stance_radius_m * np.stack(
            [np.cos(self.angles), np.sin(self.angles)], axis=1)
        servo = [[getattr(leg, j) for j in JOINTS] for leg in ordered]
        self.direction = np.array([[s.direction for s in row] for row in servo], dtype=float)
        self.trim = np.array([[s.trim_deg for s in row] for row in servo])
        limits = np.array([[self.cfg.limits_of(s) for s in row] for row in servo])
        self.lo, self.hi = limits[..., 0], limits[..., 1]
        self.joint_neutral = np.array([g.coxa_neutral_deg, g.femur_neutral_deg,
                                       g.tibia_neutral_deg])
        self.stand = g.body_height_m
        self.sit = g.sit_height_m
        self.links = (g.coxa_m, g.femur_m, g.tibia_m)
        self.footprint = (g.footprint_x_m, g.footprint_y_m)

    def feet_level(self, body: np.ndarray, feet: np.ndarray) -> np.ndarray:
        """Feet (N, 6, 3) relative to the body centre, level frame: what Robot.solve takes."""
        h = self.stand + body[:, 0]
        x = self.neutral[None, :, 0] + feet[:, :, 0] - body[:, None, 4]
        y = self.neutral[None, :, 1] + feet[:, :, 1] - body[:, None, 5]
        z = -h[:, None] + feet[:, :, 2]
        return np.stack([x, y, z], axis=2)

    def servo_deg(self, body: np.ndarray, feet: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Servo degrees (N, 6, 3) and reachable (N, 6). Same maths as Robot.solve, no clamp."""
        p = self.feet_level(body, feet)
        r, pi_, yw = (np.radians(body[:, k]) for k in (1, 2, 3))
        cr, sr, cp, sp, cy, sy = np.cos(r), np.sin(r), np.cos(pi_), np.sin(pi_), np.cos(yw), \
            np.sin(yw)
        rot = np.empty((len(body), 3, 3))  # Rz(yaw) Ry(pitch) Rx(roll), as rotate_rpy
        rot[:, 0] = np.stack([cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr], axis=1)
        rot[:, 1] = np.stack([sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr], axis=1)
        rot[:, 2] = np.stack([-sp, cp * sr, cp * cr], axis=1)
        pb = np.einsum("nji,nkj->nki", rot, p)  # R transposed: level frame -> body frame
        dx = pb[:, :, 0] - self.mounts[None, :, 0]
        dy = pb[:, :, 1] - self.mounts[None, :, 1]
        c, s = np.cos(-self.angles), np.sin(-self.angles)
        lx, ly, lz = c * dx - s * dy, s * dx + c * dy, pb[:, :, 2]
        coxa_m, femur_m, tibia_m = self.links
        coxa = np.arctan2(ly, lx)
        rr = np.hypot(lx, ly) - coxa_m
        d = np.hypot(rr, lz)
        ok = (d <= femur_m + tibia_m - 1e-6) & (d >= abs(femur_m - tibia_m) + 1e-6)
        dd = np.where(d > 1e-9, d, 1e-9)
        a2 = np.arccos(np.clip((femur_m**2 + dd**2 - tibia_m**2) / (2 * femur_m * dd), -1, 1))
        femur = np.arctan2(lz, rr) + a2
        gamma = np.arccos(np.clip((femur_m**2 + tibia_m**2 - dd**2) / (2 * femur_m * tibia_m),
                                  -1, 1))
        joints = np.degrees(np.stack([coxa, femur, math.pi - gamma], axis=2))
        deg = 90.0 + self.direction * (joints - self.joint_neutral) + self.trim
        return deg, ok

    def to_robot(self, body: np.ndarray, feet: np.ndarray
                 ) -> tuple[dict[str, tuple[float, float, float]], list[float], float]:
        """One frame -> (feet for Robot.solve, pose [roll, pitch, yaw] rad, body height)."""
        p = self.feet_level(body[None], feet[None])[0]
        pts = {leg: (float(p[i, 0]), float(p[i, 1]), float(p[i, 2])) for i, leg in enumerate(LEGS)}
        pose = [math.radians(float(body[k])) for k in (1, 2, 3)]
        return pts, pose, self.stand + float(body[0])


# ------------------------------------------------------------------ validation
@dataclass
class Report:
    ok: bool
    reason: str = ""
    duration_s: float = 0.0
    speed: float = 0.0
    max_joint_dps: float = 0.0
    min_margin_m: float = math.inf
    max_shift_m: float = 0.0
    t: np.ndarray | None = None  # the samples, for tests and tools
    body: np.ndarray | None = None
    feet: np.ndarray | None = None


def support_margin(points: np.ndarray, on: np.ndarray, centre: np.ndarray) -> np.ndarray:
    """Signed distance (N,) of centre inside the convex hull of the feet that are on the floor.

    An edge (i, j) of the hull has every other grounded foot on one side. Negative = outside.
    Fewer than 3 feet, or all in a line, gives -inf.
    """
    n = len(points)
    margin = np.full(n, np.inf)
    found = np.zeros(n, dtype=bool)
    for i in range(6):
        for j in range(i + 1, 6):
            pair = on[:, i] & on[:, j]
            e = points[:, j] - points[:, i]
            length = np.hypot(e[:, 0], e[:, 1])
            rel = points - points[:, i][:, None, :]
            cross = e[:, None, 0] * rel[:, :, 1] - e[:, None, 1] * rel[:, :, 0]
            others = on.copy()
            others[:, [i, j]] = False
            eps = 1e-9
            left = np.all(~others | (cross >= -eps), axis=1) & np.any(others & (cross > eps),
                                                                        axis=1)
            right = np.all(~others | (cross <= eps), axis=1) & np.any(others & (cross < -eps),
                                                                        axis=1)
            c = centre - points[:, i]
            dist = (e[:, 0] * c[:, 1] - e[:, 1] * c[:, 0]) / np.where(length > 0, length, 1.0)
            edge = pair & (length > 1e-6) & (left | right)
            signed = np.where(left, dist, -dist)
            margin = np.where(edge, np.minimum(margin, signed), margin)
            found |= edge
    return np.where(found & (on.sum(axis=1) >= 3), margin, -np.inf)


def validate(geo: Geometry, spec: MoveSpec, speed: float, keep: bool = False) -> Report:
    m = geo.cfg.moves
    speed = min(speed, spec.max_speed)
    times = spec.times(speed)
    duration = float(times[-1])
    rep = Report(ok=False, duration_s=duration, speed=speed)
    if not 0.0 < speed <= 1.0:
        rep.reason = f"speed {speed} is outside (0, 1]"
        return rep
    if duration > m.max_duration_s + 1e-9:
        rep.reason = (f"{spec.name} would take {duration:.1f} s at speed {speed:g} "
                      f"(at most {m.max_duration_s:g} s)")
        return rep
    body, feet = spec.arrays()
    if spec.from_neutral and (np.abs(body[0]).max() > 1e-9 or np.abs(feet[0]).max() > 1e-9):
        rep.reason = f"{spec.name} does not start in the neutral stand pose"
        return rep
    if np.abs(body[-1]).max() > 1e-9 or np.abs(feet[-1]).max() > 1e-9:
        rep.reason = f"{spec.name} does not end in the neutral stand pose"
        return rep

    t = np.arange(0.0, duration, CHECK_DT)
    if duration - t[-1] > 1e-9:
        t = np.append(t, duration)
    b, f = sample(times, body, feet, t)
    if keep:
        rep.t, rep.body, rep.feet = t, b, f

    def at(i: int) -> str:
        return f"at {t[i]:.2f} s"

    h = geo.stand + b[:, 0]
    bad = np.flatnonzero((h < geo.sit - 1e-6) | (h > geo.stand + MAX_RISE_M + 1e-6))
    if bad.size:
        rep.reason = f"body height {h[bad[0]]:.3f} m is outside the safe range {at(bad[0])}"
        return rep

    shift = np.hypot(b[:, 4], b[:, 5])
    rep.max_shift_m = float(shift.max())
    limit = spec.max_shift_m if spec.max_shift_m is not None else m.max_shift_m
    if rep.max_shift_m > limit + 1e-9:
        i = int(np.argmax(shift))
        rep.reason = (f"body moves {shift[i] * 100:.1f} cm from where it started {at(i)} "
                      f"(at most {limit * 100:.0f} cm)")
        return rep

    if np.any(f[:, :, 2] < -1e-9):
        i = int(np.flatnonzero((f[:, :, 2] < -1e-9).any(axis=1))[0])
        rep.reason = f"a foot goes below the floor {at(i)}"
        return rep
    on = f[:, :, 2] <= GROUND_EPS
    ground = geo.neutral[None] + f[:, :, :2]
    stays = on[1:] & on[:-1]
    slid = np.hypot(*(ground[1:] - ground[:-1]).transpose(2, 0, 1)) > SLIDE_EPS
    if np.any(stays & slid):
        i, leg = np.argwhere(stays & slid)[0]
        rep.reason = f"{LEGS[leg]} slides on the floor {at(int(i) + 1)}"
        return rep
    few = np.flatnonzero(on.sum(axis=1) < 3)
    if few.size:
        rep.reason = f"fewer than 3 feet on the floor {at(few[0])}"
        return rep
    margin = support_margin(ground, on, b[:, 4:6])
    rep.min_margin_m = float(margin.min())
    if rep.min_margin_m < m.support_margin_m - 1e-9:
        i = int(np.argmin(margin))
        rep.reason = (f"body centre {max(margin[i], 0.0) * 100:.1f} cm inside the feet "
                      f"{at(i)} (needs {m.support_margin_m * 100:.0f} cm)")
        return rep

    deg, ok = geo.servo_deg(b, f)
    if not ok.all():
        i, leg = np.argwhere(~ok)[0]
        rep.reason = f"{LEGS[leg]} cannot reach its foot point {at(int(i))}"
        return rep
    low, high = deg < geo.lo[None] - 1e-6, deg > geo.hi[None] + 1e-6
    if np.any(low | high):
        i, leg, j = np.argwhere(low | high)[0]
        rep.reason = (f"{LEGS[leg]}.{JOINTS[j]} would need {deg[i, leg, j]:.1f} deg, outside "
                      f"{geo.lo[leg, j]:g}..{geo.hi[leg, j]:g} {at(int(i))}")
        return rep
    rate = np.abs(np.diff(deg, axis=0)) / np.diff(t)[:, None, None]
    rep.max_joint_dps = float(rate.max()) if rate.size else 0.0
    if rep.max_joint_dps > m.max_joint_speed_dps + 1e-6:
        i, leg, j = np.unravel_index(int(np.argmax(rate)), rate.shape)
        rep.reason = (f"{LEGS[leg]}.{JOINTS[j]} would turn at {rep.max_joint_dps:.0f} deg/s "
                      f"{at(int(i))} (at most {m.max_joint_speed_dps:g}); try a lower speed")
        return rep
    rep.ok = True
    return rep


def fit_timing(geo: Geometry, spec: MoveSpec, headroom: float = 0.92) -> MoveSpec:
    """Lengthen each segment that would be too fast for max_joint_speed_dps at speed 1.0.

    A segment's shape does not depend on its length, so its peak joint speed scales exactly with
    1 / length: one pass is enough. Fixed segments (holds, breathing) keep their length; they
    are checked by validate() like everything else.
    """
    limit = geo.cfg.moves.max_joint_speed_dps * headroom
    times = spec.times(1.0)
    body, feet = spec.arrays()
    n = 24  # samples per segment
    tau = np.linspace(0.0, 1.0, n)
    starts, spans = times[:-1], np.diff(times)
    t = (starts[:, None] + spans[:, None] * tau[None, :]).ravel()
    b, f = sample(times, body, feet, t)
    deg, ok = geo.servo_deg(b, f)
    deg = deg.reshape(len(spans), n, 6, 3)
    ok = ok.reshape(len(spans), n, 6)
    step = np.abs(np.diff(deg, axis=1)).max(axis=3)
    step = np.where(ok[:, 1:] & ok[:, :-1], step, 0.0)  # out of reach: validate() says so
    dt = (spans / (n - 1))[:, None]
    peak = (step.max(axis=2) / np.where(dt > 0, dt, 1)).max(axis=1)
    stretch = np.maximum(1.0, peak / limit)
    frames, t_new = [spec.frames[0]], 0.0
    for k, (a, b_) in enumerate(zip(spec.frames, spec.frames[1:], strict=False)):
        gap = b_.t - a.t
        t_new += gap if b_.fixed else gap * float(stretch[k])
        frames.append(replace(b_, t=round(t_new, 6)))
    guard_until = spec.guard_until
    if math.isfinite(guard_until):
        guard_until = frames[_frame_at(spec, guard_until)].t
    return replace(spec, frames=tuple(frames), guard_until=guard_until)


# ------------------------------------------------------------------ obstacles
def _points(summary: LidarSummary) -> np.ndarray:
    a = np.radians(np.arange(len(summary.sectors_m)) * summary.sector_deg)
    r = np.array(summary.sectors_m)
    return np.stack([r * np.cos(a), r * np.sin(a)], axis=1)


def _unmasked(pts: np.ndarray, own_feet: np.ndarray | None) -> np.ndarray:
    if own_feet is None or not len(own_feet):
        return np.ones(len(pts), dtype=bool)
    d = np.hypot(pts[:, None, 0] - own_feet[None, :, 0], pts[:, None, 1] - own_feet[None, :, 1])
    return d.min(axis=1) > SELF_MASK_M


def edge_clearance(summary: LidarSummary, footprint: tuple[float, float],
                   own_feet: np.ndarray | None = None) -> tuple[float, float]:
    """(distance from the footprint edge to the nearest return, its bearing in deg)."""
    pts = _points(summary)
    fx, fy = footprint
    d = np.hypot(np.maximum(np.abs(pts[:, 0]) - fx, 0.0), np.maximum(np.abs(pts[:, 1]) - fy, 0.0))
    d = np.where(_unmasked(pts, own_feet), d, np.inf)
    i = int(np.argmin(d))
    bearing = i * summary.sector_deg
    return float(d[i]), bearing if bearing <= 180 else bearing - 360


def nearest_within(summary: LidarSummary, radius: float,
                   own_feet: np.ndarray | None = None) -> float | None:
    """Range of the nearest return closer than radius to the body centre, or None."""
    r = np.array(summary.sectors_m)
    r = np.where(_unmasked(_points(summary), own_feet), r, np.inf)
    i = int(np.argmin(r))
    return float(r[i]) if r[i] < radius else None


def raised_feet(geo: Geometry, body: np.ndarray, feet: np.ndarray) -> np.ndarray:
    """Floor points (k, 2), body frame now, of the feet in the air: the LiDAR sees them."""
    up = feet[:, 2] > GROUND_EPS
    pts = geo.neutral[up] + feet[up, :2] - body[4:6]
    yaw = -math.radians(float(body[3]))
    c, s = math.cos(yaw), math.sin(yaw)
    return np.stack([c * pts[:, 0] - s * pts[:, 1], s * pts[:, 0] + c * pts[:, 1]], axis=1)


# ------------------------------------------------------------------ building blocks
# This leg geometry cannot lift a foot more than about 4 cm straight up before the femur reaches
# its limit, so a high foot always goes out along the leg's own direction as it rises.
def _radial(geo: Geometry, leg: str, out: float, side: float = 0.0) -> tuple[float, float]:
    """A foot offset `out` along the leg's mount direction and `side` across it (CCW)."""
    a = geo.angles[_IDX[leg]]
    return (out * math.cos(a) - side * math.sin(a), out * math.sin(a) + side * math.cos(a))


def _wave_leg(c: Choreo, geo: Geometry, leg: str, waves: int, seg: float, nod: float = 0.0,
              tilt: float = 0.0, fast: bool = False, out: float = 0.08,
              high: float = 0.09) -> Choreo:
    """Shift away, lift a front leg high, wave it side to side, put it down, come back."""
    side = 1.0 if leg.startswith("L") else -1.0
    k = 0.8 if fast else 1.0
    c.to(0.5 * k, x=-0.02, y=-0.02 * side, roll=-tilt * side)
    c.lift(0.4 * k, [leg], 0.03)
    c.to(0.45 * k, **{leg: (*_radial(geo, leg, out), high)})
    for _ in range(waves):
        c.to(seg, pitch=nod, **{leg: (*_radial(geo, leg, out, 0.025), high + 0.005)})
        c.to(seg, pitch=0.0, **{leg: (*_radial(geo, leg, out, -0.025), high)})
    c.to(0.45 * k, **{leg: (0.0, 0.0, 0.03)})
    c.lift(0.35 * k, [leg], 0.0)
    return c.home_body(0.45 * k)


def _bounce(c: Choreo, pulses: int, half: float, depth: float = 0.012) -> Choreo:
    for _ in range(pulses):
        c.to(half, dz=-depth)
        c.to(half, dz=0.0)
    return c


def _shimmy(c: Choreo, swings: int, half: float, deg: float = 5.0) -> Choreo:
    for k in range(swings):
        c.to(half, yaw=deg if k % 2 == 0 else -deg)
    return c.to(half, yaw=0.0)


def _body_wave(c: Choreo, loops: int, quarter: float, deg: float = 7.0) -> Choreo:
    c.to(quarter, roll=deg)
    for _ in range(loops):
        c.to(quarter, roll=0.0, pitch=deg)
        c.to(quarter, roll=-deg, pitch=0.0)
        c.to(quarter, roll=0.0, pitch=-deg)
        c.to(quarter, roll=deg, pitch=0.0)
    return c.to(quarter, roll=0.0, pitch=0.0)


def _stomp(c: Choreo, up: float, down: float, rest: float, height: float = 0.03) -> Choreo:
    for tripod in (TRIPOD_A, TRIPOD_B):
        c.lift(up, tripod, height)
        c.lift(down, tripod, 0.0)  # firmer: faster down than up
        c.hold(rest)
    return c


def _bow(c: Choreo, down: float, hold: float, up: float, deg: float = 12.0) -> Choreo:
    c.to(down, pitch=deg, dz=-0.005)
    c.hold(hold)
    return c.to(up, pitch=0.0, dz=0.0)


def _crab(c: Choreo, cycles: int, half: float, shift: float = 0.025) -> Choreo:
    for _ in range(cycles):
        for side, tap in ((1.0, "RM"), (-1.0, "LM")):  # lean one way, tap the far middle leg
            c.to(half, y=shift * side, roll=-4.0 * side)
            c.lift(half * 0.75, [tap], 0.02)
            c.lift(half * 0.75, [tap], 0.0)
    return c.to(half, y=0.0, roll=0.0)


def _lowest(geo: Geometry, build, top: float) -> tuple[MoveSpec, float]:
    """The lowest body height (dz, 5 mm steps from the sit height up to `top`) that validates."""
    dz = geo.sit - geo.stand
    while dz <= top + 1e-9:
        spec = fit_timing(geo, build(dz))
        if validate(geo, spec, 1.0).ok and validate(geo, spec, DEFAULT_SPEED).ok:
            return spec, dz
        dz += 0.005
    return build(top), top


# ------------------------------------------------------------------ the built-in moves
def _wave(geo: Geometry) -> MoveSpec:
    return _wave_leg(Choreo(), geo, "LF", waves=3, seg=0.4).spec("wave")


def _hi(geo: Geometry) -> MoveSpec:
    """About 4 s: tilt toward the waving side, three waves with a small nod on each."""
    return _wave_leg(Choreo(), geo, "LF", waves=3, seg=0.26, nod=5.0, tilt=5.0, fast=True,
                     out=0.07, high=0.07).spec("hi")


def _double_hi(geo: Geometry) -> MoveSpec:
    c = Choreo()
    _wave_leg(c, geo, "LF", waves=2, seg=0.24, fast=True, out=0.065, high=0.06)
    _wave_leg(c, geo, "RF", waves=2, seg=0.24, fast=True, out=0.065, high=0.06)
    return c.spec("double_hi")


def _bow_move(geo: Geometry) -> MoveSpec:
    c = Choreo()
    _bow(c, 1.2, 0.8, 1.2)
    return c.hold(0.3).spec("bow")


def _body_wave_move(geo: Geometry) -> MoveSpec:
    return _body_wave(Choreo(), loops=2, quarter=0.6).spec("body_wave")


def _shimmy_move(geo: Geometry) -> MoveSpec:
    return _shimmy(Choreo(), swings=10, half=0.3, deg=4.5).spec("shimmy")


def _leg_ripple(geo: Geometry) -> MoveSpec:
    c = Choreo()
    for leg in ("LR", "LM", "LF", "RF", "RM", "RR"):  # around the body, one leg at a time
        c.lift(0.4, [leg], 0.03)
        c.lift(0.4, [leg], 0.0)
    return c.spec("leg_ripple")


def _stomp_move(geo: Geometry) -> MoveSpec:
    return _stomp(Choreo(), up=0.6, down=0.45, rest=0.3).spec("stomp")


def _dance(geo: Geometry) -> MoveSpec:
    """16 s at the default 100 bpm: bounce, shimmy, body wave, stomp, wave, bow."""
    beat = 60.0 / geo.cfg.moves.dance_bpm
    c = Choreo()
    _bounce(c, 2, beat)  # 4 beats
    _shimmy(c, 5, beat * 2 / 3)  # 4 beats
    _body_wave(c, 1, beat * 2 / 3)  # 4 beats
    _stomp(c, beat, beat * 0.75, beat * 0.25)  # 4 beats
    _wave_leg(c, geo, "LF", waves=2, seg=beat * 0.5, fast=True, out=0.065, high=0.06)
    _bow(c, beat, beat / 2, beat)  # 2.5 beats
    spec = fit_timing(geo, c.spec("dance"))
    end = 16.0 * 100.0 / geo.cfg.moves.dance_bpm
    last = spec.frames[-1]
    if end > last.t + 1e-6:  # finish on the bar: hold the stand pose until 16 s
        spec = replace(spec, frames=(*spec.frames, replace(last, t=end, fixed=False)))
    return spec


def _attack_stance(geo: Geometry) -> MoveSpec:
    """Threat display. The body never moves toward anything: its origin stays within 2 cm."""
    c = Choreo()
    c.step("LM", 0.03, 0.0)  # middle feet forward: support for two raised front legs
    c.step("RM", 0.03, 0.0)
    c.step("LR", *_radial(geo, "LR", 0.03))  # rear feet out: room for the rear to go down
    c.step("RR", *_radial(geo, "RR", 0.03))
    c.to(0.9, x=-0.015, pitch=-12.0)  # rear down, front up
    c.lift(0.5, ["LF", "RF"], 0.03)
    claws = {leg: (*_radial(geo, leg, 0.08, 0.02 if leg == "LF" else -0.02), 0.10)
             for leg in ("LF", "RF")}
    strike = {leg: (*_radial(geo, leg, 0.09), 0.085) for leg in ("LF", "RF")}
    c.to(0.6, **claws)  # claws up and spread
    for _ in range(4):  # strikes in the air
        c.to(0.3, **strike)
        c.to(0.35, **claws)
    c.to(0.6, LF=(0.0, 0.0, 0.03), RF=(0.0, 0.0, 0.03))
    c.lift(0.4, ["LF", "RF"], 0.0)
    c.to(0.9, x=0.0, pitch=0.0)
    for leg in ("LR", "RR", "LM", "RM"):
        c.step(leg, 0.0, 0.0)
    return c.spec("attack_stance", max_speed=ATTACK_MAX_SPEED, max_shift_m=ATTACK_MAX_SHIFT_M)


def _defense_at(geo: Geometry, low: float) -> MoveSpec:
    c = Choreo()
    c.to(1.2, dz=low)
    c.step("LM", 0.03, -0.015, height=0.02)  # legs in; the middle ones also a little forward
    c.step("RM", 0.03, 0.015, height=0.02)
    for leg in ("LR", "RR"):
        c.step(leg, *_radial(geo, leg, -0.015), height=0.02)
    c.to(0.5, x=-0.015)
    c.lift(0.4, ["LF", "RF"], 0.03)
    c.to(0.6, LF=(*_radial(geo, "LF", 0.05, -0.04), 0.06),
         RF=(*_radial(geo, "RF", 0.05, 0.04), 0.06))  # a shield in front
    for yaw in (10.0, -10.0, 10.0, -10.0):  # slow scan
        c.to(1.2, yaw=yaw)
    c.to(0.8, yaw=0.0)
    c.to(0.6, LF=(0.0, 0.0, 0.03), RF=(0.0, 0.0, 0.03))
    c.lift(0.4, ["LF", "RF"], 0.0)
    c.to(0.5, x=0.0)
    for leg in ("LM", "RM", "LR", "RR"):
        c.step(leg, 0.0, 0.0, height=0.02)
    c.to(1.2, dz=0.0)
    return c.spec("defense_stance")


def _defense_stance(geo: Geometry) -> MoveSpec:
    """Crouch as low as the servos allow (the sit height itself is past the femur limit)."""
    spec, dz = _lowest(geo, lambda d: _defense_at(geo, d), top=0.0)
    return replace(spec, detail=f"crouched to {(geo.stand + dz) * 1000:.0f} mm")


def _alert_at(rise: float) -> MoveSpec:
    c = Choreo()
    c.to(1.0, dz=rise)
    for yaw in (15.0, -15.0):
        c.to(1.2, yaw=yaw)
        c.hold(0.8, fixed=True)  # freeze and look
    c.to(1.0, yaw=0.0)
    c.to(1.0, dz=0.0)
    return c.spec("alert")


def _alert(geo: Geometry) -> MoveSpec:
    """As high as this robot can safely stand: the highest rise that passes at full speed."""
    for mm in range(int(MAX_RISE_M * 1000), 0, -5):
        spec = fit_timing(geo, _alert_at(mm / 1000.0))
        if validate(geo, spec, 1.0).ok and validate(geo, spec, DEFAULT_SPEED).ok:
            return replace(spec, detail=f"raised {mm} mm")
    return _alert_at(0.005)


def _crab_move(geo: Geometry) -> MoveSpec:
    return _crab(Choreo(), cycles=4, half=0.45).spec("crab_sway")


def _stretch(geo: Geometry) -> MoveSpec:
    c = Choreo()
    for leg in ("LF", "LM", "LR", "RR", "RM", "RF"):
        a = geo.angles[_IDX[leg]]
        ux, uy = math.cos(a), math.sin(a)
        # lean away from the leg: shift the other way, tilt down on the other side
        c.to(0.5, x=-0.02 * ux, y=-0.02 * uy, roll=4.0 * uy, pitch=4.0 * ux)
        c.lift(0.3, [leg], 0.02)
        c.to(0.5, **{leg: (*_radial(geo, leg, 0.05), 0.035)})
        c.hold(0.3)
        c.to(0.5, **{leg: (0.0, 0.0, 0.02)})
        c.lift(0.3, [leg], 0.0)
    c.home_body(0.5)
    return c.spec("stretch")


def _sleep_at(geo: Geometry, low: float) -> MoveSpec:
    c = Choreo()
    c.to(2.0, dz=low + 0.005)
    pairs = (("LF", "RR"), ("LM", "RM"), ("LR", "RF"))  # opposite legs: four feet stay down
    for pair in pairs:  # fold in
        c.lift(0.3, pair, 0.012)
        c.to(0.3, **{leg: (*_radial(geo, leg, -0.015), 0.012) for leg in pair})
        c.lift(0.3, pair, 0.0)
    for _ in range(3):  # breathing: 5 mm, 6 s whatever the speed
        c.to(1.0, fixed=True, dz=low)
        c.to(1.0, fixed=True, dz=low + 0.005)
    for pair in pairs:
        c.lift(0.3, pair, 0.012)
        c.to(0.3, **{leg: (0.0, 0.0, 0.012) for leg in pair})
        c.lift(0.3, pair, 0.0)
    c.to(2.0, dz=0.0)
    return c.spec("sleep")


def _sleep(geo: Geometry) -> MoveSpec:
    spec, dz = _lowest(geo, lambda d: _sleep_at(geo, d), top=0.0)
    return replace(spec, detail=f"settled to {(geo.stand + dz) * 1000:.0f} mm")


def _celebrate(geo: Geometry) -> MoveSpec:
    c = Choreo()
    _bounce(c, 4, 0.3, depth=0.01)
    _wave_leg(c, geo, "LF", waves=2, seg=0.26, fast=True, out=0.07, high=0.07)
    _wave_leg(c, geo, "RF", waves=2, seg=0.26, fast=True, out=0.07, high=0.07)
    return c.spec("celebrate")


def _offer_hand(geo: Geometry) -> MoveSpec:
    """The foot goes straight forward to a fixed point, holds, shakes gently, holds, returns."""
    m = geo.cfg.moves
    i = _IDX["LF"]
    tx = geo.footprint[0] + m.offer_hand_ahead_m
    ty = float(geo.neutral[i, 1])
    dx = tx - geo.neutral[i, 0]
    lift = m.offer_hand_height_m
    c = Choreo()
    c.to(0.6, x=-0.015, y=-0.01)  # back and away from the leg first
    c.lift(0.4, ["LF"], 0.03)
    c.to(0.7, LF=(*_radial(geo, "LF", 0.05), lift))  # up, clear of the floor
    extend_end = c.to(1.0, LF=(dx, 0.0, lift)).t  # to the fixed point, at the fixed height
    c.hold(0.4)
    for _ in range(2):  # gentle shake: 2 cm up and back
        c.to(0.5, LF=(dx, 0.0, lift + 0.02))
        c.to(0.5, LF=(dx, 0.0, lift))
    c.hold(OFFER_HOLD_S, fixed=True)
    c.to(0.9, LF=(*_radial(geo, "LF", 0.05), lift))
    c.to(0.6, LF=(0.0, 0.0, 0.03))
    c.lift(0.4, ["LF"], 0.0)
    c.home_body(0.5)
    return c.spec("offer_hand", max_speed=OFFER_MAX_SPEED, guard="offer",
                  guard_until=extend_end, retract_on_stop=True,
                  target=(tx, ty, lift - geo.stand))


BUILDERS = {
    "wave": _wave, "bow": _bow_move, "body_wave": _body_wave_move, "shimmy": _shimmy_move,
    "leg_ripple": _leg_ripple, "stomp": _stomp_move, "dance": _dance,
    "attack_stance": _attack_stance, "defense_stance": _defense_stance, "alert": _alert,
    "crab_sway": _crab_move, "stretch": _stretch, "sleep": _sleep, "celebrate": _celebrate,
    "hi": _hi, "double_hi": _double_hi, "offer_hand": _offer_hand,
}
SIDED = frozenset({"wave", "hi", "offer_hand"})  # these take a leg: LF (default) or RF


class MoveLibrary:
    """The built-in moves for one robot, built once each and kept."""

    def __init__(self, cfg: BodyConfig) -> None:
        self.geo = Geometry(cfg)
        self._cache: dict[tuple[str, str], MoveSpec] = {}

    def get(self, name: str, leg: str | None = None) -> MoveSpec:
        side = (leg or "LF") if name in SIDED else "LF"
        key = (name, side)
        if key not in self._cache:
            spec = fit_timing(self.geo, BUILDERS[name](self.geo))
            self._cache[key] = mirror(spec) if side == "RF" else spec
        return self._cache[key]

    # -------------------------------------------------------------- reach
    def reach(self, leg: str | None, target: tuple[float, float, float],
              watch: tuple[int, float] | None = None) -> MoveSpec:
        """Shift away, lift, approach to REACH_SHORT_M short of target, hold, come back."""
        geo = self.geo
        tx, ty, tz = target
        leg = leg or ("LF" if ty >= 0 else "RF")
        side = 1.0 if leg == "LF" else -1.0
        i = _IDX[leg]
        lift_t = tz + geo.stand  # target height above the floor
        if lift_t < 0.01:
            raise MoveError("the target is at or below the floor")
        pre = np.array([geo.neutral[i, 0], geo.neutral[i, 1], max(lift_t, 0.03)])
        goal = np.array([tx, ty, lift_t])
        gap = goal - pre
        dist = float(np.linalg.norm(gap))
        if dist <= REACH_SHORT_M:
            raise MoveError("the target is where the foot already is")
        stop = pre + gap * (1.0 - REACH_SHORT_M / dist)
        off = (float(stop[0] - geo.neutral[i, 0]), float(stop[1] - geo.neutral[i, 1]),
               float(stop[2]))
        c = Choreo()
        c.to(0.6, x=-0.015, y=-0.02 * side)
        c.lift(0.5, [leg], float(pre[2]))
        c.to(1.2, **{leg: off})
        c.hold(REACH_HOLD_S, fixed=True)
        c.to(0.8, **{leg: (0.0, 0.0, float(pre[2]))})
        c.lift(0.5, [leg], 0.0)
        c.home_body(0.5)
        return c.spec("reach", guard="reach", watch=watch, target=(tx, ty, lift_t),
                      detail=f"{leg} to ({tx:.2f}, {ty:.2f}, {tz:.2f})")

    def reach_nearest(self, leg: str | None, summary: LidarSummary, speed: float
                      ) -> tuple[MoveSpec, Report]:
        """The closest LiDAR return ahead that the leg can reach and that passes validation."""
        z = self.geo.cfg.moves.reach_touch_height_m - self.geo.stand
        pts = _points(summary)
        order = np.argsort(summary.sectors_m)
        reasons = []
        for k in order:
            bearing = (k * summary.sector_deg + 180.0) % 360.0 - 180.0
            if abs(bearing) > REACH_SECTOR_DEG:
                continue
            x, y = float(pts[k, 0]), float(pts[k, 1])
            if leg is not None and (y < 0) != (leg == "RF") and abs(y) > 0.02:
                continue  # the other side of the body
            mount = self.geo.mounts[_IDX[leg or ("LF" if y >= 0 else "RF")]]
            if math.hypot(x - mount[0], y - mount[1]) > sum(self.geo.links):
                continue  # beyond the leg in any pose
            spec = self.reach(leg, (x, y, z), watch=(int(k), float(summary.sectors_m[k])))
            rep = validate(self.geo, spec, speed)
            if rep.ok:
                return spec, rep
            reasons.append(rep.reason)
        why = f" ({reasons[0]})" if reasons else ""
        raise MoveError(f"nothing within reach of a front leg{why}")

    # -------------------------------------------------------------- the way back
    def _recovery_via(self, body: np.ndarray, feet: np.ndarray, out: float, high: float
                      ) -> MoveSpec:
        c = Choreo(body=body, feet=feet)
        touching = [leg for leg in LEGS if 0.0 < c.feet[leg][2] <= GROUND_EPS]
        if touching:  # caught just above the floor: straight down first
            c.lift(0.1, touching, 0.0)
        up = [leg for leg in LEGS if c.feet[leg][2] > GROUND_EPS]
        if up:  # raised feet come in along the leg's own line, then drop near the body
            if out > 0.0:
                c.to(0.8, **{leg: (*_radial(self.geo, leg, out), min(high, c.feet[leg][2]))
                             for leg in up})
            c.to(0.8, **{leg: (0.0, 0.0, min(0.03, c.feet[leg][2])) for leg in up})
            c.lift(0.5, up, 0.0)
        if max(abs(v) for v in c.body.values()) > 1e-9:
            c.home_body(1.0)
        for leg in LEGS:  # feet left off their neutral point: one at a time
            dx, dy, _ = c.feet[leg]
            if math.hypot(dx, dy) > 1e-6:
                c.step(leg, 0.0, 0.0, height=0.02)
        if len(c.frames) == 1:
            c.hold(0.1)
        return fit_timing(self.geo, c.spec("recover", from_neutral=False, guard="none"))

    def recovery(self, body: np.ndarray, feet: np.ndarray) -> tuple[MoveSpec, Report]:
        """From a held pose back to the neutral stand: the first path that validates."""
        rep = None
        for out, high in ((0.06, 0.07), (0.08, 0.08), (0.05, 0.05), (0.0, 0.03)):
            spec = self._recovery_via(body, feet, out, high)
            rep = validate(self.geo, spec, DEFAULT_SPEED)
            if rep.ok:
                return spec, rep
        assert rep is not None
        return spec, rep


# ------------------------------------------------------------------ running
class Runner:
    """One move in progress. Robot.tick calls advance(dt) once per tick."""

    def __init__(self, spec: MoveSpec, speed: float, seq: int | None = None, trace: str = ""):
        self.spec = spec
        self.speed = min(speed, spec.max_speed)
        self.times = spec.times(self.speed)
        self.body, self.feet = spec.arrays()
        self.duration = float(self.times[-1])
        self.elapsed = 0.0
        self.seq, self.trace = seq, trace
        self.guard_until = math.inf
        if math.isfinite(spec.guard_until):
            self.guard_until = float(self.times[_frame_at(spec, spec.guard_until)])

    def frame(self) -> tuple[np.ndarray, np.ndarray]:
        b, f = sample(self.times, self.body, self.feet, np.array([self.elapsed]))
        return b[0], f[0]

    def advance(self, dt: float) -> tuple[np.ndarray, np.ndarray]:
        self.elapsed = min(self.duration, self.elapsed + dt)
        return self.frame()

    @property
    def done(self) -> bool:
        return self.elapsed >= self.duration - 1e-9

    @property
    def guarding(self) -> bool:
        return self.elapsed < self.guard_until
