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


def head(path, label):
    w0 = np.eye(42, dtype=np.float32)
    w1 = np.zeros((42, 2), np.float32)
    w1[:, 1] = 1.0
    np.savez(path, n_layers=np.array(2), W0=w0, b0=np.zeros(42, np.float32),
             W1=w1, b1=np.zeros(2, np.float32),
             mean=np.zeros(42, np.float32), std=np.ones(42, np.float32),
             labels=np.array(["no_gesture", label]))
    return str(path)


def test_landmark_head_decides_and_speaks_mediapipe_names(tmp_path):
    frame = np.zeros((480, 640, 3), np.uint8)
    found = reader(["Thumb_Up"], head_path=head(tmp_path / "a.npz", "palm")).read(frame)
    assert [g.label for g in found] == ["Open_Palm", "Open_Palm"]  # HaGRID palm, the head wins
    found = reader(["Thumb_Up"], head_path=head(tmp_path / "b.npz", "call")).read(frame)
    assert [g.label for g in found] == ["call", "call"]  # no MediaPipe twin: no default action


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


def test_head_and_mediapipe_agreeing_lift_a_weak_head_score(tmp_path):
    frame = np.zeros((480, 640, 3), np.uint8)
    weak = str(tmp_path / "w.npz")  # zero weights: the head says "like" at 0.5, under 0.6
    np.savez(weak, n_layers=np.array(1), W0=np.zeros((42, 2), np.float32),
             b0=np.zeros(2, np.float32), mean=np.zeros(42, np.float32),
             std=np.ones(42, np.float32), labels=np.array(["like", "no_gesture"]))
    found = reader(["Thumb_Up", "Victory"], score=0.8, head_path=weak).read(frame)
    assert [(g.label, g.score) for g in found] == [("Thumb_Up", 0.8)]  # agreed; the other not
