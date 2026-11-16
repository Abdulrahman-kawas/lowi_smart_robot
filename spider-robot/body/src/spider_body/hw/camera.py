"""Camera snapshots as JPEG bytes small enough for one MQTT message (AWS IoT limit: 128 KB).

Backends:
  opencv    - any USB/UVC webcam (V4L2), default
  picamera2 - Raspberry Pi Camera Module (needs `sudo apt install python3-picamera2` and a venv
              created with --system-site-packages)
  fake      - synthetic image for the simulator
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Protocol

import numpy as np

from ..config import CameraCfg

log = logging.getLogger(__name__)


class Camera(Protocol):
    def snapshot(self) -> bytes: ...


def encode_jpeg(frame_bgr: np.ndarray, quality: int, max_bytes: int) -> bytes:
    import cv2  # not at module level: the control process never needs OpenCV

    q = quality
    img = frame_bgr
    while True:
        ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), q])
        if not ok:
            raise RuntimeError("JPEG encoding failed")
        data = buf.tobytes()
        if len(data) <= max_bytes:
            return data
        if q > 40:
            q -= 10
        else:  # still too big: halve the resolution
            img = cv2.resize(img, (img.shape[1] // 2, img.shape[0] // 2))
            if img.shape[1] < 80:
                raise RuntimeError("cannot fit the image in max_bytes")


class OpenCvCamera:
    # A V4L2 queue stops filling once it is full, so after an idle gap the queued frames are as old
    # as the gap: on the Brave 7 LE a 20 s pause gave a 20 s old "snapshot". snapshot() therefore
    # grabs until the driver's timestamp (CLOCK_MONOTONIC) is later than the request.
    FRESH_TIMEOUT_S = 1.0
    MAX_GRABS = 10

    def __init__(self, cfg: CameraCfg) -> None:
        self.cfg = cfg
        self._cap = None
        self._lock = threading.Lock()
        self._warned_stamps = False

    def _open(self):
        import cv2

        if self._cap is None or not self._cap.isOpened():
            cap = cv2.VideoCapture(self.cfg.device, cv2.CAP_V4L2)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.cfg.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.cfg.height)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # fewer stale frames to skip; some ignore it
            if not cap.isOpened():
                dev = self.cfg.device
                name = dev if isinstance(dev, str) else f"/dev/video{dev}"
                raise RuntimeError(f"cannot open camera {name}")
            self._cap = cap
        return self._cap

    def _grab_fresh(self, cap) -> None:
        """Grab until the current frame was captured after this call started."""
        import cv2

        asked_ms = time.clock_gettime(time.CLOCK_MONOTONIC) * 1000.0
        deadline = time.monotonic() + self.FRESH_TIMEOUT_S
        for _ in range(self.MAX_GRABS):
            if not cap.grab():
                raise RuntimeError("camera read failed")
            stamp = cap.get(cv2.CAP_PROP_POS_MSEC)
            now_ms = time.clock_gettime(time.CLOCK_MONOTONIC) * 1000.0
            if asked_ms <= stamp <= now_ms + 1000.0:  # captured after the request, same clock
                return
            if time.monotonic() > deadline:
                break
        # No usable timestamp (zero, or another clock). The grabs above have drained the queue, so
        # the current frame is recent, but say so once.
        if not self._warned_stamps:
            self._warned_stamps = True
            log.warning("camera gives no CLOCK_MONOTONIC frame timestamps; freshness not proven")

    def snapshot(self) -> bytes:
        with self._lock:
            cap = self._open()
            try:
                self._grab_fresh(cap)
                ok, frame = cap.retrieve()
            except RuntimeError:
                ok = False
            if not ok:
                self._cap = None
                raise RuntimeError("camera read failed")
            return encode_jpeg(frame, self.cfg.jpeg_quality, self.cfg.max_bytes)


class Picamera2Camera:
    def __init__(self, cfg: CameraCfg) -> None:
        from picamera2 import Picamera2  # system package, see module docstring

        self.cfg = cfg
        self._cam = Picamera2()
        self._cam.configure(
            self._cam.create_still_configuration(
                main={"size": (cfg.width, cfg.height), "format": "RGB888"}
            )
        )
        self._cam.start()
        time.sleep(1.0)  # auto exposure settles
        self._lock = threading.Lock()

    def snapshot(self) -> bytes:
        with self._lock:
            frame = self._cam.capture_array()  # "RGB888" is BGR byte order, as OpenCV expects
            return encode_jpeg(frame, self.cfg.jpeg_quality, self.cfg.max_bytes)


class FakeCamera:
    def __init__(self, cfg: CameraCfg) -> None:
        self.cfg = cfg

    def snapshot(self) -> bytes:
        import cv2

        img = np.full((self.cfg.height, self.cfg.width, 3), 60, dtype=np.uint8)
        cv2.rectangle(img, (200, 150), (440, 400), (40, 120, 220), -1)  # an orange "box"
        cv2.putText(img, time.strftime("SIM %H:%M:%S"), (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
        return encode_jpeg(img, self.cfg.jpeg_quality, self.cfg.max_bytes)


class NoCamera:
    def snapshot(self) -> bytes:
        raise RuntimeError("camera disabled in robot.yaml")


def make_camera(cfg: CameraCfg) -> Camera:
    if cfg.backend == "opencv":
        return OpenCvCamera(cfg)
    if cfg.backend == "picamera2":
        return Picamera2Camera(cfg)
    if cfg.backend == "fake":
        return FakeCamera(cfg)
    return NoCamera()
