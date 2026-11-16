"""OpenCvCamera.snapshot returns a frame captured after the request, even after an idle gap.

On the Brave 7 LE the V4L2 queue held frames as old as the pause before the snapshot (20 s pause,
20 s old photo). FakeCap mimics that queue with driver timestamps on CLOCK_MONOTONIC.
"""

import time

import numpy as np
import pytest

pytest.importorskip("cv2")

from spider_body.config import CameraCfg  # noqa: E402
from spider_body.hw.camera import OpenCvCamera  # noqa: E402


def now_ms() -> float:
    return time.clock_gettime(time.CLOCK_MONOTONIC) * 1000.0


class FakeCap:
    """Queued frames come out first, at once; after that each grab waits for a new frame."""

    def __init__(self, queued_ages_ms=(), stamp=None, fail=False):
        t = now_ms()
        self.queue = [t - age for age in queued_ages_ms]
        self.fixed_stamp = stamp  # a driver that reports this for every frame
        self.fail = fail
        self.grabs = 0
        self.current = None

    def isOpened(self):
        return True

    def grab(self):
        if self.fail:
            return False
        self.grabs += 1
        if self.queue:
            self.current = self.queue.pop(0)
        else:
            time.sleep(0.002)  # the next frame arrives
            self.current = now_ms()
        return True

    def get(self, prop):
        return self.fixed_stamp if self.fixed_stamp is not None else self.current

    def retrieve(self):
        return True, np.zeros((48, 64, 3), np.uint8)


def camera_with(cap) -> OpenCvCamera:
    cam = OpenCvCamera(CameraCfg(device=0))
    cam._cap = cap
    return cam


def test_after_an_idle_gap_the_frame_is_newer_than_the_request():
    cap = FakeCap(queued_ages_ms=(20_000, 19_967))  # what a 20 s pause leaves in the queue
    asked = now_ms()
    assert camera_with(cap).snapshot()
    assert cap.current >= asked
    assert cap.grabs == 3  # two stale frames skipped, one fresh


def test_back_to_back_takes_one_grab():
    cap = FakeCap()
    camera_with(cap).snapshot()
    assert cap.grabs == 1


def test_unusable_timestamps_still_drain_the_queue():
    for stamp in (0.0, 1.79e12):  # no timestamp, or wall-clock milliseconds
        cap = FakeCap(queued_ages_ms=(5_000,), stamp=stamp)
        assert camera_with(cap).snapshot()
        assert cap.grabs == OpenCvCamera.MAX_GRABS


def test_a_failed_grab_drops_the_capture():
    cam = camera_with(FakeCap(fail=True))
    with pytest.raises(RuntimeError, match="camera read failed"):
        cam.snapshot()
    assert cam._cap is None
