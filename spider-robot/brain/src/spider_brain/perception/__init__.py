"""Perception on the home server: objects, people and hand gestures in camera frames.

Everything here is observation. The only robot command it can lead to is Stop (a gesture), and
answers are spoken. Heavy libraries load only when SB_PERCEPTION=true.
"""

from __future__ import annotations

import asyncio
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .detect import Detection, ObjectDetector, YoloOnnx, speak_objects
from .faces import FaceBook, FaceMatch, FaceModels
from .gestures import GestureReader, HandGesture, bind

log = logging.getLogger(__name__)

YUNET = "models/face_detection_yunet_2023mar.onnx"
SFACE = "models/face_recognition_sface_2021dec.onnx"
GESTURES = "models/gesture_recognizer.task"

_WHO_WORDS = frozenset({"هاد", "هذا", "ذا", "قدام", "قدامك", "القدام", "هنا", "بالصورة", "هي"})
_WORD = re.compile(r"[\w']+")


@dataclass(frozen=True)
class Seen:
    faces: list[FaceMatch]
    gestures: list[HandGesture]


def perception_dir(settings) -> Path:
    """Private models and photos live under brain/data, never under the repo's source tree."""
    path = Path(settings.perception_dir).expanduser()
    return path if path.is_absolute() else Path(__file__).resolve().parents[2] / path


def decode_jpeg(jpeg: bytes) -> np.ndarray:
    import cv2

    img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("camera frame is not a readable JPEG")
    return img


def is_who_question(text: str) -> bool:
    """Arabic and English 'who is this / who is in front of you' questions."""
    words = set(_WORD.findall(text.lower()))
    if "who" in words or "whos" in words:
        return True
    if "مين" not in words and "من" not in words:
        return False
    return len(words) <= 3 or bool(words & _WHO_WORDS)


def facts_line(dets: list[Detection], faces: list, width: int, height: int,
               with_names: bool) -> str:
    """For the VLM: what the fast models saw. They can be wrong; the VLM is told so."""
    parts = [f"{d.label} ({d.side(width)}, {d.distance(height)}, {d.score:.2f})"
             for d in dets[:12]]
    for face in faces:
        who = face.spoken if (with_names and face.person_id) else "a person"
        parts.append(f"face: {who}")
    if not parts:
        return "Fast detectors found nothing they know."
    return "Fast detectors (they can be wrong) found: " + "; ".join(parts) + "."


class Perception:
    def __init__(self, objects: ObjectDetector | None, faces: Any = None,
                 gestures: Any = None) -> None:
        self.objects, self.faces, self.gestures = objects, faces, gestures
        # The models are not thread-safe and share the CPU with the VLM: one frame at a time.
        self._pool = ThreadPoolExecutor(1, thread_name_prefix="perception")

    async def run(self, fn, *args):
        return await asyncio.get_running_loop().run_in_executor(self._pool, fn, *args)

    def see(self, bgr: np.ndarray) -> Seen:
        faces = self.faces.identify(bgr) if self.faces else []
        hands = self.gestures.read(bgr) if self.gestures else []
        return Seen(faces, [bind(h, faces) for h in hands])

    def facts(self, bgr: np.ndarray, with_names: bool = True) -> str:
        dets = self.objects.detect(bgr) if self.objects else []
        faces = self.faces.identify(bgr) if self.faces else []
        return facts_line(dets, faces, bgr.shape[1], bgr.shape[0], with_names)

    def describe(self, bgr: np.ndarray) -> str:
        dets = self.objects.detect(bgr) if self.objects else []
        return speak_objects(dets, bgr.shape[1])

    def who(self, bgr: np.ndarray) -> str:
        faces = self.faces.identify(bgr) if self.faces else []
        names = [f.spoken for f in faces if f.person_id]
        if names:
            return "هاد " + " و".join(names)
        return "في حدا بس ما بعرفه" if faces else "ما شايف حدا"

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


def make_perception(settings) -> Perception:
    import cv2

    cv2.setNumThreads(1)
    base = perception_dir(settings)
    objects = ObjectDetector([
        YoloOnnx(str(base / p), settings.perception_min_score, settings.perception_threads)
        for p in settings.perception_detectors
    ])
    faces = None
    if (base / YUNET).exists() and (base / SFACE).exists():
        models = FaceModels(str(base / YUNET), str(base / SFACE))
        faces = FaceBook.load(models, base / "faces.npz", settings.face_threshold,
                              settings.face_margin)
    else:
        log.warning("face models are missing under %s: nobody can be named", base)
    gestures = None
    if (base / GESTURES).exists():
        head = str(base / settings.gesture_head) if settings.gesture_head else None
        if head and not Path(head).exists():
            log.warning("gesture head %s is missing; using MediaPipe's built-in names", head)
            head = None
        gestures = GestureReader(str(base / GESTURES), head, settings.gesture_min_score)
    else:
        log.warning("gesture model %s is missing: watch mode has no gestures", GESTURES)
    return Perception(objects, faces, gestures)
