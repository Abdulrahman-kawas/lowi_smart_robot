import numpy as np

from spider_brain.perception.faces import FaceMatch
from spider_brain.perception.gestures import (
    GestureReader,
    bind,
    landmark_features,
)


class Mark:
    def __init__(self, x, y):
        self.x, self.y = x, y


class Category:
    def __init__(self, category_name, score):
        self.category_name, self.score = category_name, score


class Result:
    def __init__(self, hands, gestures):
        self.hand_landmarks = hands
        self.gestures = gestures


def hand(x, y):
    return [Mark(x + 0.01 * i, y + 0.01 * i) for i in range(21)]


def reader(labels, score=0.9, min_score=0.6, head_path=None):
    marks = [hand(0.1, 0.1), hand(0.7, 0.6)]
    gestures = [[Category(label, score)] for label in labels]
    recognizer = type("R", (), {"recognize": lambda self, image: Result(marks, gestures)})()
    return GestureReader("unused.task", head_path, min_score, recognizer, lambda rgb: rgb)


def test_gesture_reader_reads_hands_and_skips_unknown_or_weak():
    found = reader(["Open_Palm", "None"]).read(np.zeros((480, 640, 3), np.uint8))
    assert [g.label for g in found] == ["Open_Palm"]
    assert found[0].box == (64.0, 48.0, 192.0, 144.0)  # 0.1..0.3 of a 640x480 frame

    assert reader(["Victory"], score=0.4).read(np.zeros((480, 640, 3), np.uint8)) == []


def test_landmark_head_can_override_mediapipe_names(tmp_path):
    path = tmp_path / "head.npz"
    w = np.zeros((42, 2), np.float32)
    w[:, 1] = 1.0
    np.savez(path, n_layers=np.array(1), W0=w, b0=np.zeros(2, np.float32),
             mean=np.zeros(42, np.float32), std=np.ones(42, np.float32),
             labels=np.array(["no_gesture", "palm"]))
    found = reader(["Open_Palm"], head_path=str(path)).read(np.zeros((480, 640, 3), np.uint8))
    assert [g.label for g in found] == ["palm", "palm"]


def test_landmark_features_are_position_and_size_free():
    a = landmark_features(np.array([[0.1, 0.1], [0.1, 0.5], [0.1, 0.9]] + [[0.1, 0.1]] * 18),
                          1.0)
    b = landmark_features(np.array([[0.6, 0.4], [0.6, 0.8], [0.6, 1.2]] + [[0.6, 0.4]] * 18),
                          1.0)
    assert a.shape == (42,) and np.allclose(a, b)


def test_bind_finds_the_nearest_enrolled_face_only():
    face = FaceMatch((100, 100, 200, 200), "sami", "سامي", 0.9)
    far = FaceMatch((500, 100, 600, 200), "ali", "Ali", 0.9)
    from spider_brain.perception.gestures import HandGesture

    near = HandGesture("Open_Palm", 0.9, (140, 140, 180, 180))
    assert bind(near, [far, face]).person == face
    away = HandGesture("Open_Palm", 0.9, (400, 400, 440, 440))
    assert bind(away, [face, far]).person == far
    nobody = HandGesture("Open_Palm", 0.9, (1000, 1000, 1040, 1040))
    assert bind(nobody, [face, far]).person is None
