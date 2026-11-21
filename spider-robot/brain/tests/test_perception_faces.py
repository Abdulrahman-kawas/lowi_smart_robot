import cv2
import numpy as np

from spider_brain.perception.faces import FaceBook, check, enroll, forget


class FakeModels:
    """Face rows and vectors driven by pixel values, so tests need no model files."""

    def __init__(self, vectors=None):
        self.vectors = vectors or {}

    def vector(self, code):
        v = next((v for k, v in self.vectors.items() if abs(code - k) < 8),
                 np.eye(128, dtype=np.float32)[code % 128])
        return v / np.linalg.norm(v)

    def faces(self, bgr):
        code = int(bgr[50, 50, 0])
        if code < 10:
            return []
        if code < 20:
            return [np.array([0, 0, 40, 80] + [0] * 10, np.float32),
                    np.array([50, 0, 40, 80] + [0] * 10, np.float32)]
        side = 20 if code < 30 else 80
        return [np.array([0, 0, side, side] + [0] * 10, np.float32)]

    def embed(self, bgr, _row):
        return self.vector(int(bgr[50, 50, 1]))


def photo(path, face_code, person_code):
    img = np.zeros((100, 100, 3), np.uint8)
    img[:, :, 0], img[:, :, 1] = face_code, person_code
    assert cv2.imwrite(str(path), img)
    return path


def frame(path, face_code, person_code):
    return cv2.imread(str(photo(path, face_code, person_code)))


def test_enroll_reads_photo_folders_and_writes_a_pickle_free_book(tmp_path):
    people = tmp_path / "people"
    sami = people / "sami"
    sami.mkdir(parents=True)
    (sami / "name.txt").write_text("سامي\n", encoding="utf-8")
    photo(sami / "01.jpg", 60, 100)
    photo(sami / "02.jpg", 60, 100)
    photo(sami / "03.jpg", 15, 100)  # two faces: the largest is used
    photo(sami / "noface.jpg", 5, 100)
    (sami / "broken.jpg").write_bytes(b"not a jpeg")
    (sami / "notes.txt").write_text("ignored")
    ali = people / "ali"
    ali.mkdir()
    photo(ali / "01.jpg", 60, 110)

    book_path = tmp_path / "faces.npz"
    notes = enroll(FakeModels(), people, book_path)
    assert any("2 faces, used the largest" in n for n in notes)
    assert any("cannot read it" in n for n in notes)
    assert any("only 1 photos" in n for n in notes)
    assert notes[-1] == "enrolled 2 people from 4 photos"

    z = np.load(book_path, allow_pickle=False)
    assert [str(s) for s in z["ids"]] == ["ali", "sami"]
    assert [str(s) for s in z["spoken"]] == ["ali", "سامي"]
    assert z["emb"].shape == (4, 128)
    assert sorted(set(int(o) for o in z["owner"])) == [0, 1]


def test_identify_uses_threshold_margin_and_minimum_face_size(tmp_path):
    v10 = np.eye(128, dtype=np.float32)[10]
    v11 = v10 + 0.1 * np.eye(128, dtype=np.float32)[11]
    models = FakeModels({100: v10, 110: v11})
    people = tmp_path / "people"
    for pid, code in (("sami", 100), ("ali", 110)):
        folder = people / pid
        folder.mkdir(parents=True)
        photo(folder / "01.jpg", 60, code)
    (people / "sami" / "name.txt").write_text("سامي\n", encoding="utf-8")
    book_path = tmp_path / "faces.npz"
    enroll(models, people, book_path)

    book = FaceBook.load(models, book_path, 0.9, 0.05)
    matches = book.identify(frame(tmp_path / "frame.jpg", 60, 100))
    assert len(matches) == 1
    assert matches[0].person_id is None  # ali is too close: the margin refuses both

    models.vectors[110] = np.eye(128, dtype=np.float32)[30]
    other_path = tmp_path / "faces2.npz"
    enroll(models, people, other_path)
    book = FaceBook.load(models, other_path, 0.9, 0.05)
    matches = book.identify(frame(tmp_path / "frame.jpg", 60, 100))
    assert matches[0].person_id == "sami" and matches[0].spoken == "سامي"

    small = np.zeros((100, 100, 3), np.uint8)
    small[:, :, 0], small[:, :, 1] = 25, 100  # code 25 here means a 20 px face
    assert FaceBook.load(models, book_path, 0.9, 0.05).identify(small)[0].person_id is None


def test_unenrolled_face_is_reported_without_a_name():
    models = FakeModels()
    book = FaceBook.load(models, "/no/such/npz", 0.363, 0.05)
    match = book.identify(np.full((100, 100, 3), 60, np.uint8))[0]
    assert match.person_id is None and match.spoken == ""


def test_check_and_forget_work_on_the_private_book(tmp_path):
    v10 = np.eye(128, dtype=np.float32)[10]
    models = FakeModels({100: v10, 110: v10 + 0.1 * np.eye(128, dtype=np.float32)[11]})
    people = tmp_path / "people"
    for pid, code in (("sami", 100), ("ali", 110)):
        folder = people / pid
        folder.mkdir(parents=True)
        photo(folder / "01.jpg", 60, code)
    book_path = tmp_path / "faces.npz"
    enroll(models, people, book_path)
    book = FaceBook.load(models, book_path, 0.363, 0.05)
    assert any("looks like someone else" in line for line in check(book))

    assert forget(book_path, "ali")
    assert not forget(book_path, "ali")
    z = np.load(book_path, allow_pickle=False)
    assert [str(s) for s in z["ids"]] == ["sami"] and len(z["emb"]) == 1
