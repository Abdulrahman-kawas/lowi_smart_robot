"""Hand gestures with MediaPipe's Gesture Recognizer (Apache-2.0).

Built-in gestures: Closed_Fist, Open_Palm, Pointing_Up, Thumb_Down, Thumb_Up, Victory, ILoveYou
("None" = a hand showing nothing known). A small head trained on HaGRID landmarks
(gestures_mlp.npz) decides instead when it is there. Its gestures that MediaPipe also has are
called by MediaPipe's names, so one action table serves both; the others (call, mute, ok, rock,
four, two_up, ...) keep HaGRID's names and trigger nothing unless the owner maps them.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from .faces import FaceMatch

NOT_A_GESTURE = {"None", "no_gesture"}
CANONICAL = {"like": "Thumb_Up", "palm": "Open_Palm", "stop": "Open_Palm",
             "stop_inverted": "Open_Palm", "peace": "Victory", "one": "Pointing_Up",
             "dislike": "Thumb_Down", "fist": "Closed_Fist"}


@dataclass(frozen=True)
class HandGesture:
    label: str
    score: float
    box: tuple[float, float, float, float]  # hand box in frame pixels
    person: FaceMatch | None = None


def landmark_features(points_xy: np.ndarray, aspect: float) -> np.ndarray:
    """21 normalised (x, y) landmarks -> 42 numbers independent of hand position and size."""
    pts = np.asarray(points_xy, dtype=np.float32)[:, :2].copy()
    pts[:, 0] *= aspect  # x and y in the same unit
    pts -= pts[0]  # wrist at the origin
    scale = float(np.linalg.norm(pts[9])) or 1.0  # wrist -> middle-finger knuckle
    return (pts / scale).reshape(-1)


class LandmarkHead:
    """The MLP from train_gestures.py, run in numpy. Weights in .npz: no pickle."""

    def __init__(self, path: str) -> None:
        z = np.load(path, allow_pickle=False)
        self.layers = [(z[f"W{i}"], z[f"b{i}"]) for i in range(int(z["n_layers"]))]
        self.mean, self.std = z["mean"], z["std"]
        self.labels = [str(s) for s in z["labels"]]

    def predict(self, feats: np.ndarray) -> tuple[str, float]:
        x = (feats - self.mean) / self.std
        for i, (w, b) in enumerate(self.layers):
            x = x @ w + b
            if i < len(self.layers) - 1:
                x = np.maximum(x, 0.0)
        e = np.exp(x - x.max())
        p = e / e.sum()
        k = int(p.argmax())
        return self.labels[k], float(p[k])


class GestureReader:
    def __init__(self, model_path: str, head_path: str | None = None, min_score: float = 0.6,
                 recognizer=None, to_image=None) -> None:
        if recognizer is None:
            import mediapipe as mp

            opts = mp.tasks.vision.GestureRecognizerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=model_path),
                running_mode=mp.tasks.vision.RunningMode.IMAGE,  # frames are ~0.6 s apart
                num_hands=2,
            )
            recognizer = mp.tasks.vision.GestureRecognizer.create_from_options(opts)
            to_image = lambda rgb: mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)  # noqa: E731
        self.recognizer = recognizer
        self.to_image = to_image or (lambda rgb: rgb)
        self.head = LandmarkHead(head_path) if head_path else None
        self.min_score = min_score

    def read(self, bgr: np.ndarray) -> list[HandGesture]:
        h, w = bgr.shape[:2]
        rgb = np.ascontiguousarray(bgr[:, :, ::-1])
        result = self.recognizer.recognize(self.to_image(rgb))
        hands = []
        for i, marks in enumerate(result.hand_landmarks):
            xy = np.array([(m.x, m.y) for m in marks], dtype=np.float32)
            top = result.gestures[i][0] if i < len(result.gestures) and result.gestures[i] else None
            if self.head is not None:
                label, score = self.head.predict(landmark_features(xy, w / h))
                label = CANONICAL.get(label, label)
                if top is not None and top.category_name == label:
                    score = max(score, float(top.score))  # both models agree
            elif top is not None:
                label, score = top.category_name, float(top.score)
            else:
                continue
            if label in NOT_A_GESTURE or score < self.min_score:
                continue
            box = (float(xy[:, 0].min() * w), float(xy[:, 1].min() * h),
                   float(xy[:, 0].max() * w), float(xy[:, 1].max() * h))
            hands.append(HandGesture(label, score, box))
        return hands


def bind(hand: HandGesture, faces: list[FaceMatch], reach: float = 3.5) -> HandGesture:
    """Whose hand: the nearest face within `reach` face widths, or nobody. On HaGRID (2,521
    one-person frames) the gesture hand was within 3 face widths 99.1 % of the time, 3.5: 99.8 %."""
    hx, hy = (hand.box[0] + hand.box[2]) / 2, (hand.box[1] + hand.box[3]) / 2
    best, best_d = None, reach
    for f in faces:
        fw = max(1.0, f.box[2] - f.box[0])
        fx, fy = (f.box[0] + f.box[2]) / 2, (f.box[1] + f.box[3]) / 2
        d = float(np.hypot(hx - fx, hy - fy)) / fw
        if d < best_d:
            best, best_d = f, d
    return replace(hand, person=best)
