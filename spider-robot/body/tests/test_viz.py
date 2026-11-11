import asyncio
import json
import math

import pytest

from spider_body.config import JOINTS
from spider_body.hw.lidar import SimWorld
from spider_body.kinematics import LegGeometry, body_to_leg, joint_to_servo_deg, leg_ik
from spider_body.viz.fk import all_legs, leg_points, servo_to_joint_rad
from spider_body.viz.server import SimSession, ViewerServer

FRAME_KEYS = {"mode", "estop", "limiter", "world", "pose", "legs", "lidar", "obstacles", "events"}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def set_calibration(cfg, direction):
    """Every servo gets `direction` and a different, non-zero trim."""
    for i, leg in enumerate(cfg.legs):
        for k, joint in enumerate(JOINTS):
            servo = getattr(leg, joint)
            servo.direction = direction
            servo.trim_deg = 1.5 * (k - 1) + 0.7 * (i + 1) * direction


def session(cfg, obstacles=()):
    clock = Clock()
    return SimSession(cfg, world=SimWorld(obstacles=list(obstacles)), clock=clock), clock


def advance(s, clock, seconds, hz=50):
    """The control tick as main.control_loop does it, plus the LiDAR scan and the heartbeat."""
    dt = 1 / hz
    for i in range(round(seconds * hz)):
        clock.t += dt
        if i % 5 == 0:
            s.lidar.scan()
            s.heartbeat()
        s.robot.tick(dt)
        e = s.robot.gait.effective
        s.world.integrate(e.vx, e.vy, e.wz, dt)


def kinds(s):
    s.drain_events()
    return [e["kind"] for e in s.events]


# ------------------------------------------------------------------ forward kinematics
@pytest.mark.parametrize("v", [0.0, 37.0, 90.0, 151.5])
@pytest.mark.parametrize("direction", [1, -1])
def test_servo_to_joint_inverts_joint_to_servo(v, direction):
    rad = servo_to_joint_rad(v, 90.0, direction, 2.5)
    assert joint_to_servo_deg(rad, 90.0, direction, 2.5) == pytest.approx(v)


@pytest.mark.parametrize("direction", [1, -1])
def test_fk_round_trip(cfg, direction):
    set_calibration(cfg, direction)
    g = cfg.geometry
    geom = LegGeometry(g.coxa_m, g.femur_m, g.tibia_m)
    neutral = {"coxa": g.coxa_neutral_deg, "femur": g.femur_neutral_deg,
               "tibia": g.tibia_neutral_deg}
    # (radial offset, sideways offset, z) around the neutral foot of each leg
    offsets = [(0.0, 0.0, -0.09), (0.03, 0.02, -0.09), (-0.02, -0.03, -0.06),
               (0.01, 0.0, -0.035), (0.0, 0.025, -0.12), (0.035, -0.035, -0.055)]
    for leg in cfg.legs:
        a = math.radians(leg.mount_angle_deg)
        for dr, ds, z in offsets:
            r = g.stance_radius_m + dr
            target = (leg.mount_x + r * math.cos(a) - ds * math.sin(a),
                      leg.mount_y + r * math.sin(a) + ds * math.cos(a), z)
            j = leg_ik(*body_to_leg(target, leg.mount_x, leg.mount_y, a), geom)
            servo_deg = {}
            for joint, rad in zip(JOINTS, (j.coxa, j.femur, j.tibia), strict=True):
                s = getattr(leg, joint)
                servo_deg[f"{leg.name}.{joint}"] = joint_to_servo_deg(
                    rad, neutral[joint], s.direction, s.trim_deg)
            pts = leg_points(leg, g, servo_deg)
            assert math.dist(pts[3], target) < 1e-3, (leg.name, target, pts[3])
            assert math.dist(pts[0], (leg.mount_x, leg.mount_y, 0.0)) < 1e-9
            # the links keep their lengths
            assert math.dist(pts[0], pts[1]) == pytest.approx(g.coxa_m)
            assert math.dist(pts[1], pts[2]) == pytest.approx(g.femur_m)
            assert math.dist(pts[2], pts[3]) == pytest.approx(g.tibia_m)


@pytest.mark.parametrize("direction", [1, -1])
def test_fk_inverts_robot_solve_with_body_pose(cfg, direction):
    set_calibration(cfg, direction)
    s, _ = session(cfg)
    s.robot.pose = [math.radians(4), math.radians(-3), math.radians(6)]
    neutral = s.robot.gait.neutral
    feet = {name: (nx + 0.01, ny - 0.008, -0.085) for name, (nx, ny) in neutral.items()}
    servo_deg = s.robot.solve(feet)
    assert servo_deg is not None
    legs = all_legs(cfg, servo_deg, tuple(s.robot.pose))
    assert set(legs) == {leg.name for leg in cfg.legs}
    for name, pts in legs.items():
        assert math.dist(pts[3], feet[name]) < 1e-3, name


def test_all_legs_skips_legs_without_commands(cfg):
    s, _ = session(cfg)
    servo_deg = s.robot.solve({n: (x, y, -0.09) for n, (x, y) in s.robot.gait.neutral.items()})
    partial = {k: v for k, v in servo_deg.items() if not k.startswith("RR.")}
    del partial["LF.tibia"]
    assert set(all_legs(cfg, partial)) == {"LM", "LR", "RF", "RM"}


# ------------------------------------------------------------------ simulated robot
def test_stand_puts_feet_under_the_body(cfg):
    s, clock = session(cfg)
    f = s.frame()
    assert f["mode"] == "relaxed" and f["legs"] == {}
    s.command({"type": "posture", "posture": "stand"})
    advance(s, clock, 3.0)
    f = s.frame()
    assert f["mode"] == "standing"
    assert f["servos_relaxed"] is False
    assert len(f["legs"]) == 6
    h = cfg.geometry.body_height_m
    assert f["pose"]["body_z_m"] == pytest.approx(h, abs=1e-3)
    for name, pts in f["legs"].items():
        base, foot = pts[0], pts[3]
        assert foot[2] < base[2] - 0.05, name  # below the body
        assert foot[2] == pytest.approx(-h, abs=1e-3), name  # on the floor


def test_forward_move_drives_the_world_pose(cfg):
    s, clock = session(cfg)
    s.command({"type": "posture", "posture": "stand"})
    advance(s, clock, 3.0)
    s.command({"type": "move", "vx": 0.06, "duration_s": 1.0})
    advance(s, clock, 0.5)
    assert s.frame()["mode"] == "walking"
    advance(s, clock, 1.5)
    f = s.frame()
    assert f["world"]["x"] > 0.03
    assert abs(f["world"]["y"]) < 0.005 and abs(f["world"]["yaw"]) < 0.01
    assert "move_done" in kinds(s)


def test_obstacle_ahead_stops_the_move(cfg):
    s, clock = session(cfg, obstacles=[(0.42, 0.0, 0.05)])  # 0.13 m from the legs
    s.command({"type": "posture", "posture": "stand"})
    advance(s, clock, 3.0)
    s.command({"type": "move", "vx": 0.06, "duration_s": 1.0})
    advance(s, clock, 1.0)
    assert "obstacle_stop" in kinds(s)
    assert s.world.x < 0.005


def test_stop_then_move_is_not_fenced(cfg):
    """The viewer numbers its commands: a Move after a Stop must still be accepted."""
    s, clock = session(cfg)
    s.command({"type": "posture", "posture": "stand"})
    advance(s, clock, 3.0)
    s.command({"type": "stop"})
    s.command({"type": "move", "vx": 0.06, "duration_s": 1.0})
    assert s.robot.move is not None


def test_session_rejects_bad_commands(cfg):
    from pydantic import ValidationError

    s, _ = session(cfg)
    with pytest.raises(ValidationError):
        s.command({"type": "move", "vx": 3.0})
    with pytest.raises(ValidationError):
        s.command({"type": "teleport"})
    with pytest.raises(ValueError, match="does not forward"):
        s.command({"type": "snapshot", "request_id": "x"})
    with pytest.raises(ValueError):
        s.command(["move"])


# ------------------------------------------------------------------ HTTP
async def http(port, method, path, body=None, headers=None):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    hdrs = {"Host": f"127.0.0.1:{port}", **(headers or {})}
    data = b""
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        hdrs.setdefault("Content-Type", "application/json")
        hdrs["Content-Length"] = str(len(data))
    head = f"{method} {path} HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in hdrs.items())
    writer.write(head.encode() + b"\r\n" + data)
    await writer.drain()
    raw = await asyncio.wait_for(reader.read(), 5.0)
    writer.close()
    status_line, _, rest = raw.partition(b"\r\n")
    _, _, payload = rest.partition(b"\r\n\r\n")
    return int(status_line.split()[1]), payload


async def test_sse_frame_and_cmd_endpoint(cfg):
    server = ViewerServer(SimSession(cfg), port=0)
    await server.start()
    try:
        port = server.port
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(f"GET /events HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n".encode())
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5.0)
        assert head.startswith(b"HTTP/1.1 200")
        assert b"text/event-stream" in head
        line = await asyncio.wait_for(reader.readline(), 5.0)
        assert line.startswith(b"data: ")
        frame = json.loads(line[len(b"data: "):])
        assert FRAME_KEYS <= frame.keys()
        assert {"x", "y", "yaw"} <= frame["world"].keys()
        assert "sectors_m" in frame["lidar"]
        assert frame["mode"] == "relaxed" and frame["estop"] is False
        assert [list(o) for o in frame["obstacles"]] == [[1.2, 0.0, 0.15], [-0.8, 1.0, 0.25]]
        writer.close()

        status, body = await http(port, "POST", "/cmd", {"type": "move", "vx": 9.0})
        assert status == 400 and json.loads(body)["ok"] is False
        status, _ = await http(port, "POST", "/cmd", {"type": "fly"})
        assert status == 400
        status, _ = await http(port, "POST", "/cmd", b"{not json")
        assert status == 400
        status, _ = await http(port, "POST", "/cmd", {"type": "stop"},
                               headers={"Content-Type": "text/plain"})
        assert status == 415
        status, _ = await http(port, "POST", "/cmd", {"type": "stop"},
                               headers={"Host": "evil.example:80"})
        assert status == 403

        status, body = await http(port, "POST", "/cmd", {"type": "posture", "posture": "stand"})
        assert status == 200 and json.loads(body)["type"] == "posture"
        # the live control loop picks it up and starts writing servo degrees
        for _ in range(100):
            if server.session.servos.writes:
                break
            await asyncio.sleep(0.02)
        assert server.session.servos.writes > 0

        status, body = await http(port, "GET", "/")
        assert status == 200 and b"three@0.160.0" in body
        status, body = await http(port, "GET", "/state")
        assert status == 200 and FRAME_KEYS <= json.loads(body).keys()
        status, _ = await http(port, "GET", "/nope")
        assert status == 404
    finally:
        await server.stop()


def test_viewer_forwards_moves_and_shows_them(cfg):
    s, clock = session(cfg)
    s.command({"type": "posture", "posture": "stand"})
    advance(s, clock, 3.0)
    s.command({"type": "perform", "name": "hi", "speed": 0.5, "leg": "RF"})
    advance(s, clock, 1.0)
    f = s.frame()
    assert f["perform"] == "hi" and f["holding"] is False
    assert f["world"]["shift"][1] > 0.005  # shifted away from RF, to the left
    assert f["legs"]["RF"][3][2] > f["legs"]["LF"][3][2] + 0.01  # RF foot is up
    s.command({"type": "stop"})
    advance(s, clock, 0.1)
    assert s.frame()["holding"] is True
    with pytest.raises(ValueError):
        s.command({"type": "perform", "name": "moonwalk"})
    s.command({"type": "reach", "target": "nearest"})
    assert kinds(s)[-1] == "perform_rejected"
