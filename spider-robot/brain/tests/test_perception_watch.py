import asyncio
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
        self.free = True
        self.jpeg = jpeg_bytes()

    def camera_free(self, human=True):
        assert human is False  # watch mode asks on the brain's own source
        return self.free

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


def live_view(robot, n=1, age=0.1, wanted=True):
    return SimpleNamespace(latest=SimpleNamespace(n=n, jpeg=robot.jpeg), age_s=lambda: age,
                           wanted=wanted)


async def test_one_live_view_frame_is_looked_at_once_and_cannot_fire_alone():
    robot = Robot()
    feed = live_view(robot)
    w, _said, _photos = watcher(robot, Perception(["Open_Palm"]), feed=feed)

    assert await w.step() is True
    assert await w.step() is False  # the same frame again: not a second sighting
    assert await w.step() is False
    assert robot.stops == 0 and robot.snapshots == 0

    feed.latest = SimpleNamespace(n=2, jpeg=robot.jpeg)  # the next camera frame
    assert await w.step() is True
    assert robot.stops == 1 and robot.snapshots == 0


async def test_watch_reads_the_live_view_even_while_its_camera_turn_is_taken():
    robot = Robot()
    robot.free = False  # the live view keeps the camera busy
    w, _said, _photos = watcher(robot, Perception(["Open_Palm"]), feed=live_view(robot))
    assert await w.step() is True
    assert robot.snapshots == 0


async def test_own_snapshots_only_when_the_live_view_is_off():
    robot = Robot()
    feed = live_view(robot, age=30.0)
    w, _said, _photos = watcher(robot, Perception(), feed=feed)
    assert await w.step() is False  # live view on but stale: wait for it, never compete
    assert robot.snapshots == 0
    feed.wanted = False
    assert await w.step() is True
    assert robot.snapshots == 1


async def test_watch_halves_its_rate_when_the_control_loop_is_late():
    robot = Robot()
    w, _said, _photos = watcher(robot, Perception(), period_s=0.6)
    assert w.effective_period_s() == 0.6
    for ts in (1.0, 2.0, 3.0):
        robot.state = RobotState(robot_id="r", mode="standing", ts=ts, loop_late_max_ms=12.0)
        rate = w.effective_period_s()
    assert rate == 1.2


async def test_no_snapshot_while_a_voice_question_waits_for_the_camera():
    robot = Robot()
    robot.free = False
    w, _said, _photos = watcher(robot, Perception(["Open_Palm"]))
    w.turn_on()
    task = asyncio.create_task(w.run())
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert robot.snapshots == 0


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
