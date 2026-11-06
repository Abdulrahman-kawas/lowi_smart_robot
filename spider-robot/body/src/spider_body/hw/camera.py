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

import cv2
import numpy as np

from ..config import CameraCfg

log = logging.getLogger(__name__)


class Camera(Protocol):
    def snapshot(self) -> bytes: ...


def encode_jpeg(frame_bgr: np.ndarray, quality: int, max_bytes: int) -> bytes:
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
    def __init__(self, cfg: CameraCfg) -> None:
        self.cfg = cfg
        self._cap: cv2.VideoCapture | None = None
        self._lock = threading.Lock()

    def _open(self) -> cv2.VideoCapture:
        if self._cap is None or not self._cap.isOpened():
            cap = cv2.VideoCapture(self.cfg.device, cv2.CAP_V4L2)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.cfg.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.cfg.height)
            if not cap.isOpened():
                raise RuntimeError(f"cannot open camera /dev/video{self.cfg.device}")
            self._cap = cap
        return self._cap

    def snapshot(self) -> bytes:
        with self._lock:
            cap = self._open()
            for _ in range(3):  # drop buffered (old) frames
                cap.grab()
            ok, frame = cap.read()
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
