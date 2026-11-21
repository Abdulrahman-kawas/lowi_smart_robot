import time
from types import SimpleNamespace

import cv2
import numpy as np

from spider_brain.telegram import TelegramBot

OWNER = 4242
ACTIONS = {"Open_Palm": "stop", "Thumb_Up": "greet"}


def jpeg_bytes():
    ok, data = cv2.imencode(".jpg", np.zeros((480, 640, 3), np.uint8))
    assert ok
    return data.tobytes()


class FakeWatcher:
    actions = ACTIONS
    minutes = 30.0

    def __init__(self):
        self.until = float("-inf")

    @property
    def on(self):
        return time.monotonic() < self.until

    @property
    def remaining_s(self):
        return max(0.0, self.until - time.monotonic())

    def turn_on(self):
        self.until = time.monotonic() + self.minutes * 60

    def turn_off(self):
        self.until = float("-inf")


class FakePerception:
    async def run(self, fn, *args):
        return fn(*args)

    def who(self, frame):
        return "هاد سامي"


class FakeRobot:
    def __init__(self):
        self.jpeg = jpeg_bytes()

    async def snapshot(self, **kwargs):
        return self.jpeg


def bot_with(svc):
    bot = TelegramBot(svc, "tok", {OWNER}, http=object())
    sent, uploads = [], []

    async def send(chat, text, **extra):
        sent.append((chat, text))

    async def upload(method, chat, field, name, data, mime, caption="", reply_markup=None):
        uploads.append((method, chat, caption, data))

    bot.send = send
    bot._upload = upload
    return bot, sent, uploads


async def test_watch_commands_toggle_the_watcher_and_list_gestures():
    watcher = FakeWatcher()
    svc = SimpleNamespace(watcher=watcher, perception=None, robot=FakeRobot())
    bot, sent, _uploads = bot_with(svc)

    await bot.command(OWNER, "/watch on")
    assert watcher.on and "30 min left" in sent[-1][1] and "Open_Palm: stop" in sent[-1][1]
    await bot.command(OWNER, "/watch off")
    assert not watcher.on and sent[-1][1] == "Watch off."
    await bot.command(OWNER, "/watch maybe")
    assert "Usage: /watch on" in sent[-1][1]


async def test_who_sends_the_frame_with_the_names_as_caption():
    svc = SimpleNamespace(watcher=None, perception=FakePerception(), robot=FakeRobot())
    bot, sent, uploads = bot_with(svc)

    await bot.command(OWNER, "/who")
    assert uploads[0][0] == "sendPhoto" and uploads[0][1] == OWNER
    assert uploads[0][2] == "هاد سامي" and uploads[0][3] == svc.robot.jpeg
    assert sent == []


async def test_send_owner_photo_reaches_every_owner():
    bot, _sent, uploads = bot_with(SimpleNamespace())
    jpeg = jpeg_bytes()
    await bot.send_owner_photo(jpeg, "gesture Victory")
    assert uploads == [("sendPhoto", OWNER, "gesture Victory", jpeg)]


async def test_who_without_perception_says_so():
    svc = SimpleNamespace(watcher=None, perception=None, robot=FakeRobot())
    bot, sent, uploads = bot_with(svc)
    await bot.command(OWNER, "/who")
    assert "Perception is off" in sent[-1][1] and uploads == []
