"""Offline face book and frame-grab commands for the home server. Private data stays there."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import numpy as np

from . import SFACE, YUNET, perception_dir


def _models(settings):
    from .faces import FaceModels

    base = perception_dir(settings)
    yunet, sface = base / YUNET, base / SFACE
    if not yunet.exists() or not sface.exists():
        raise SystemExit(f"face models are missing under {base}; copy them there first")
    return FaceModels(str(yunet), str(sface))


def faces(settings, action: str, person: str | None) -> int:
    from .faces import FaceBook, check, enroll, forget

    base = perception_dir(settings)
    book_path = base / "faces.npz"
    if action == "enroll":
        people = base / "people"
        if not people.is_dir():
            raise SystemExit(f"no photo folders under {people}")
        for note in enroll(_models(settings), people, book_path):
            print(note)
        print("restart spider-brain so it loads the new faces.npz")
    elif action == "list":
        if not book_path.exists():
            print("nobody is enrolled")
            return 0
        z = np.load(book_path, allow_pickle=False)
        for pid, spoken in zip(z["ids"], z["spoken"], strict=False):
            print(f"{str(pid)}: {str(spoken)}")
    elif action == "check":
        if not book_path.exists():
            print("nobody is enrolled")
            return 0
        book = FaceBook.load(_models(settings), book_path, settings.face_threshold,
                             settings.face_margin)
        for line in check(book):
            print(line)
    elif action == "forget":
        if not person:
            raise SystemExit("forget needs a person id")
        print("removed from faces.npz" if forget(book_path, person)
              else f"{person} is not in faces.npz (their photo folder was left alone)")
    return 0


async def grab(robot, out: Path, count: int, every: float) -> int:
    """Save raw robot frames for labelling; nothing here moves the robot."""
    out.mkdir(parents=True, exist_ok=True)
    for n in range(count):
        jpeg = await robot.snapshot(timeout_s=3.0, human=True)
        (out / f"{time.strftime('%Y%m%d-%H%M%S')}-{n:03d}.jpg").write_bytes(jpeg)
        print(f"saved {out} ({n + 1}/{count})")
        if n + 1 < count:
            await asyncio.sleep(every)
    return 0
