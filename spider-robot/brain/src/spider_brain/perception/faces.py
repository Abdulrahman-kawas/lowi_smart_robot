"""Who is in a frame. YuNet finds faces, SFace turns each into 128 numbers, and those are compared
with the people the owner enrolled from photos. No training: enrolling is computing the numbers
once. Photos and numbers stay in brain/data/perception on the home server.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

# Measured on LFW (5 people enrolled with 12 photos each, 12,000 stranger photos), faces 45 to
# 130 px tall in a 640x480 JPEG frame: scoring each person by the mean of their TOP_K best photos
# at threshold 0.42 named 99.4-100 % of enrolled faces correctly and 0.1-0.2 % of strangers. Their
# single best photo at OpenCV's published 0.363 named 3 % of strangers.
MIN_FACE_PX = 45  # smaller faces were not measured: say "someone", not a name
TOP_K = 3
MAX_PHOTO_SIDE = 1600
PHOTO_TYPES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


@dataclass(frozen=True)
class FaceMatch:
    box: tuple[float, float, float, float]  # x1, y1, x2, y2 in frame pixels
    person_id: str | None  # None: unknown, unsure or too small
    spoken: str  # the name to say; "" when unknown
    score: float  # best cosine similarity


class FaceModels:
    """The two OpenCV Zoo networks, apart from FaceBook so tests can replace them."""

    def __init__(self, yunet_path: str, sface_path: str, min_conf: float = 0.8) -> None:
        import cv2

        self.detector = cv2.FaceDetectorYN.create(yunet_path, "", (320, 320), min_conf, 0.3, 50)
        self.recognizer = cv2.FaceRecognizerSF.create(sface_path, "")

    def faces(self, bgr: np.ndarray) -> list[np.ndarray]:
        """Rows of 15: x, y, w, h, five landmark points, score."""
        h, w = bgr.shape[:2]
        self.detector.setInputSize((w, h))
        _, rows = self.detector.detect(bgr)
        return [] if rows is None else list(rows)

    def embed(self, bgr: np.ndarray, row: np.ndarray) -> np.ndarray:
        v = self.recognizer.feature(self.recognizer.alignCrop(bgr, row)).reshape(-1)
        v = v.astype(np.float32)
        return v / (np.linalg.norm(v) + 1e-9)


class FaceBook:
    def __init__(self, models, emb: np.ndarray, owner: np.ndarray, ids: list[str],
                 spoken: list[str], threshold: float = 0.42, margin: float = 0.05) -> None:
        self.models, self.emb, self.owner = models, emb, owner
        self.ids, self.spoken = ids, spoken
        self.threshold, self.margin = threshold, margin

    @classmethod
    def load(cls, models, path: Path, threshold: float, margin: float) -> FaceBook:
        if not Path(path).exists():
            log.info("no %s: nobody is enrolled", path)
            return cls(models, np.zeros((0, 128), np.float32), np.zeros(0, np.int32), [], [],
                       threshold, margin)
        z = np.load(path, allow_pickle=False)
        return cls(models, z["emb"], z["owner"], [str(s) for s in z["ids"]],
                   [str(s) for s in z["spoken"]], threshold, margin)

    def per_person(self, v: np.ndarray) -> np.ndarray:
        """Each enrolled person's score: the mean similarity of their TOP_K closest photos. One
        look-alike photo is not enough to name a stranger."""
        sims = self.emb @ v
        out = np.full(len(self.ids), -1.0, dtype=np.float32)
        for p in range(len(self.ids)):
            mine = np.sort(sims[self.owner == p])
            if len(mine):
                out[p] = float(mine[-TOP_K:].mean())
        return out

    def identify(self, bgr: np.ndarray) -> list[FaceMatch]:
        out = []
        for row in self.models.faces(bgr):
            x, y, w, h = (float(v) for v in row[:4])
            box = (x, y, x + w, y + h)
            if h < MIN_FACE_PX or not self.ids:
                out.append(FaceMatch(box, None, "", 0.0))
                continue
            sims = self.per_person(self.models.embed(bgr, row))
            order = np.argsort(sims)[::-1]
            best = float(sims[order[0]])
            second = float(sims[order[1]]) if len(order) > 1 else -1.0
            if best >= self.threshold and best - second >= self.margin:
                i = int(order[0])
                out.append(FaceMatch(box, self.ids[i], self.spoken[i], best))
            else:
                out.append(FaceMatch(box, None, "", best))
        return out


def enroll(models, people_dir: Path, out_path: Path) -> list[str]:
    """people_dir/<person_id>/*.jpg (+ name.txt with the spoken name) -> out_path. Returns notes."""
    import cv2

    emb: list[np.ndarray] = []
    owner: list[int] = []
    ids: list[str] = []
    spoken: list[str] = []
    notes: list[str] = []
    for person in sorted(p for p in Path(people_dir).iterdir() if p.is_dir()):
        name_file = person / "name.txt"
        name = name_file.read_text(encoding="utf-8").strip() if name_file.exists() else person.name
        used = 0
        for photo in sorted(person.iterdir()):
            if photo.suffix.lower() not in PHOTO_TYPES:
                continue
            img = cv2.imread(str(photo))  # applies the EXIF rotation
            if img is None:
                notes.append(f"{person.name}/{photo.name}: cannot read it")
                continue
            if max(img.shape[:2]) > MAX_PHOTO_SIDE:
                s = MAX_PHOTO_SIDE / max(img.shape[:2])
                img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
            rows = models.faces(img)
            if not rows:
                notes.append(f"{person.name}/{photo.name}: no face found")
                continue
            if len(rows) > 1:
                notes.append(f"{person.name}/{photo.name}: {len(rows)} faces, used the largest")
            row = max(rows, key=lambda r: float(r[2]) * float(r[3]))
            emb.append(models.embed(img, row))
            owner.append(len(ids))
            used += 1
        if used == 0:
            notes.append(f"{person.name}: no usable photo, not enrolled")
            continue
        if used < 8:
            notes.append(f"{person.name}: only {used} photos; 10-20 recognise better")
        ids.append(person.name)
        spoken.append(name)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(out_path.stem + ".tmp.npz")
    np.savez(tmp, emb=np.stack(emb) if emb else np.zeros((0, 128), np.float32),
             owner=np.array(owner, dtype=np.int32),
             ids=np.array(ids, dtype=str), spoken=np.array(spoken, dtype=str))
    os.replace(tmp, out_path)
    notes.append(f"enrolled {len(ids)} people from {len(emb)} photos")
    return notes


def forget(path: Path, person_id: str) -> bool:
    """Remove one person's numbers from the book. Their photo folder is left on the server."""
    if not Path(path).exists():
        return False
    z = np.load(path, allow_pickle=False)
    ids = [str(s) for s in z["ids"]]
    if person_id not in ids:
        return False
    keep = np.array([i for i, pid in enumerate(ids) if pid != person_id])
    emb, owner = z["emb"], z["owner"]
    selected = np.flatnonzero(np.isin(owner, keep))
    remap = {int(old): new for new, old in enumerate(keep)}
    new_owner = np.array([remap[int(o)] for o in owner[selected]], dtype=np.int32)
    tmp = Path(path).with_name(Path(path).stem + ".tmp.npz")
    np.savez(tmp, emb=emb[selected], owner=new_owner,
             ids=np.array([ids[i] for i in keep], dtype=str),
             spoken=np.array([str(s) for i, s in enumerate(z["spoken"]) if i in keep], dtype=str))
    os.replace(tmp, path)
    return True


def check(book: FaceBook) -> list[str]:
    """Leave-one-out: how close each person is to themselves and to the nearest other person."""
    lines = []
    for p, pid in enumerate(book.ids):
        mine = np.flatnonzero(book.owner == p)
        own, other = [], []
        for i in mine:
            sims = book.emb @ book.emb[i]
            same = [s for j, s in enumerate(sims) if j != i and book.owner[j] == p]
            diff = [s for j, s in enumerate(sims) if book.owner[j] != p]
            if same:
                own.append(max(same))
            if diff:
                other.append(max(diff))
        lo = min(own) if own else float("nan")
        hi = max(other) if other else float("nan")
        warn = "  <- looks like someone else" if other and hi > book.threshold else ""
        lines.append(f"{pid}: worst own match {lo:.2f}, closest other person {hi:.2f}{warn}")
    return lines
