from types import SimpleNamespace

import cv2
import numpy as np
from spider_common.protocol import RobotState

from spider_brain.perception import Seen
from spider_brain.perception.faces import FaceMatch
from spider_brain.perception.gestures import HandGesture
from spider_brain.perception.watch import Debouncer, Watcher

ACTIONS = {"Open_Palm": "stop", "Thumb_Up": "greet", "Victory": "photo",
           "Pointing_Up": "describe", "ILoveYou": "say:مرحبا"}


def jpeg_bytes():
    ok, data = cv2.imencode(".jpg", np.zeros((480, 640, 3), np.uint8))
    assert ok
    return data.tobytes()


class Robot:
    def __init__(self):
        self.state = None
        self.stops = 0
        self.snapshots = 0
        self.jpeg = jpeg_bytes()

    def camera_free(self):
        return True

    def stop(self):
        self.stops += 1

    async def snapshot(self, **kwargs):
        self.snapshots += 1
        return self.jpeg


class Perception:
    def __init__(self, labels=()):
        self.labels = labels

    async def run(self, fn, *args):
        return fn(*args)

    def see(self, frame):
        faces = [FaceMatch((0, 0, 100, 100), "sami", "سامي", 0.9)]
        hands = [HandGesture(label, 0.9, (40, 40, 80, 80), faces[0]) for label in self.labels]
        return Seen(faces, hands)

    def describe(self, frame):
        return "شايف طاولة"


def watcher(robot, perception, **kw):
    said, photos = [], []
    w = Watcher(robot, perception, ACTIONS, {"stop"},
                lambda text: _record(said, text), lambda jpeg, caption: _record(photos, caption),
                clock=lambda: 0.0, **kw)
    return w, said, photos


async def _record(bucket, value):
    bucket.append(value)


def test_debouncer_needs_two_frames_and_a_cooldown():
    d = Debouncer(need=2, window=3, cooldown_s={"Open_Palm": 1.0}, default_cooldown_s=6.0)
    assert d.push({"Open_Palm"}, 0.0) == []
    assert d.push({"Open_Palm"}, 0.1) == ["Open_Palm"]
    assert d.push({"Open_Palm"}, 0.2) == []  # held: no second Stop
    assert d.push(set(), 0.3) == []  # released
    assert d.push({"Open_Palm"}, 0.4) == []  # cooldown
    assert d.push({"Open_Palm"}, 1.5) == ["Open_Palm"]


async def test_only_stop_can_touch_motion_and_others_speak_or_send_photos():
    robot = Robot()
    w, said, photos = watcher(robot, Perception())
    face = FaceMatch((0, 0, 100, 100), "sami", "سامي", 0.9)
    frame = np.zeros((480, 640, 3), np.uint8)

    await w.act("Open_Palm", face, robot.jpeg, frame)
    assert robot.stops == 1 and said == [] and photos == []
    await w.act("Thumb_Up", face, robot.jpeg, frame)
    assert said == ["أهلين سامي"] and robot.stops == 1
    await w.act("Victory", face, robot.jpeg, frame)
    assert photos == ["gesture Victory by sami"]
    await w.act("Pointing_Up", face, robot.jpeg, frame)
    assert said[-1] == "شايف طاولة"
    await w.act("ILoveYou", face, robot.jpeg, frame)
    assert said[-1] == "مرحبا"

    await w.act("Thumb_Up", None, robot.jpeg, frame)  # not enrolled: only Stop is for anyone
    assert len(said) == 3
    await w.act("Open_Palm", None, robot.jpeg, frame)
    assert robot.stops == 2


async def test_step_reuses_a_fresh_live_view_frame():
    robot = Robot()
    feed = SimpleNamespace(latest=SimpleNamespace(jpeg=robot.jpeg), age_s=lambda: 0.1)
    w, _said, _photos = watcher(robot, Perception(["Open_Palm"]), feed=feed)

    await w.step()
    await w.step()  # two frames: the debouncer fires once
    assert robot.snapshots == 0 and robot.stops == 1

    w.feed.age_s = lambda: 30.0
    await w.step()
    assert robot.snapshots == 1


async def test_watch_halves_its_rate_when_the_control_loop_is_late():
    robot = Robot()
    w, _said, _photos = watcher(robot, Perception(), period_s=0.6)
    assert w.effective_period_s() == 0.6
    for ts in (1.0, 2.0, 3.0):
        robot.state = RobotState(robot_id="r", mode="standing", ts=ts, loop_late_max_ms=12.0)
        rate = w.effective_period_s()
    assert rate == 1.2


def test_turn_on_and_off_are_owner_only_state():
    now = [0.0]
    robot = Robot()
    w, _said, _photos = watcher(robot, Perception(), minutes=2.0)
    w.clock = lambda: now[0]
    assert not w.on
    w.turn_on()
    assert w.on and abs(w.remaining_s - 120.0) < 0.01
    now[0] = 121.0
    assert not w.on
    w.turn_on()
    w.turn_off()
    assert not w.on
