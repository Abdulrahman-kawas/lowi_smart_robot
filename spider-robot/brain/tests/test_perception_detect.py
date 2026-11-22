import numpy as np
import pytest

from spider_brain.perception import facts_line, is_who_question
from spider_brain.perception.detect import (
    ARABIC,
    Detection,
    ObjectDetector,
    YoloOnnx,
    iou,
    labels_from_metadata,
    letterbox,
    speak_objects,
)


class Meta:
    def __init__(self, names="{0: 'person', 1: 'chair', 2: 'sofa', 3: 'couch'}"):
        self.custom_metadata_map = {"names": names} if names else {}


class Inp:
    name = "images"
    shape = (1, 3, 640, 640)


class Session:
    def __init__(self, out, names=None):
        self.out = out
        self.meta = Meta() if names is None else (Meta("") if names is False else Meta(names))

    def get_inputs(self):
        return [Inp()]

    def get_modelmeta(self):
        return self.meta

    def run(self, _names, feed):
        assert feed["images"].shape == (1, 3, 640, 640)
        return [self.out]


def test_letterbox_pads_a_640x480_frame_by_80_pixels_top_and_bottom():
    canvas, scale, px, py = letterbox(np.zeros((480, 640, 3), np.uint8), 640)
    assert canvas.shape == (640, 640, 3)
    assert (scale, px, py) == (1, 0, 80)
    assert int(canvas[0, 0, 0]) == 114


def test_end_to_end_output_maps_boxes_back_through_the_letterbox():
    rows = np.zeros((1, 300, 6), np.float32)
    rows[0, 0] = (100, 180, 200, 300, 0.9, 1)  # y - 80 pad -> 100..220 in the frame
    found = YoloOnnx("unused", session=Session(rows)).detect(np.zeros((480, 640, 3), np.uint8))
    assert len(found) == 1
    assert found[0].label == "chair"
    assert found[0].box == (100.0, 100.0, 200.0, 220.0)
    assert found[0].side(640) == "left"
    assert found[0].distance(480) == "far"


def test_raw_output_runs_nms_and_drops_weak_classes():
    out = np.zeros((1, 6, 2), np.float32)
    out[0, :, 0] = (150, 280, 100, 120, 0.8, 0.1)  # cx, cy, w, h, person, chair
    out[0, :, 1] = (400, 300, 20, 20, 0.1, 0.9)
    found = YoloOnnx("unused", session=Session(out, names="{0: 'person', 1: 'chair'}")).detect(
        np.zeros((480, 640, 3), np.uint8))
    assert [d.label for d in found] == ["chair", "person"]  # NMS sorts by score
    assert min(d.score for d in found) >= 0.35  # the weak class in each row was dropped
    assert found[0].box == (390.0, 210.0, 410.0, 230.0)


def test_unknown_output_shape_and_missing_names_are_refused():
    with pytest.raises(ValueError, match="unknown YOLO output"):
        YoloOnnx("unused", session=Session(np.zeros((1, 5, 10), np.float32),
                                           names="{0: 'person', 1: 'chair'}")).detect(
            np.zeros((480, 640, 3), np.uint8))
    with pytest.raises(ValueError, match="no 'names' metadata"):
        labels_from_metadata(Session(np.zeros((1, 6, 1), np.float32), names=False))


def test_two_models_naming_the_same_thing_keep_the_better_detection():
    def model(label, cls, score):
        rows = np.zeros((1, 300, 6), np.float32)
        rows[0, 0] = (100, 180, 200, 300, score, cls)
        names = "{0: 'person', 1: 'chair', 2: 'sofa', 3: 'couch'}"
        return YoloOnnx("unused", session=Session(rows, names=names))

    found = ObjectDetector([model("sofa", 2, 0.6), model("couch", 3, 0.8)]).detect(
        np.zeros((480, 640, 3), np.uint8))
    assert len(found) == 1 and found[0].label == "couch"
    assert iou(found[0].box, found[0].box) == 1.0


def test_speech_and_facts_lines_stay_short_and_in_arabic():
    dets = [Detection("chair", 0.9, (0, 0, 100, 100)),
            Detection("person", 0.8, (0, 0, 100, 100))]
    assert speak_objects(dets, 640) == "شايف كرسي عاليسار وشخص عاليسار"
    assert speak_objects([], 640) == "ما شايف شي بعرفه"
    line = facts_line(dets, [], 640, 480, True)
    assert "chair (left, far, 0.90)" in line and "face" not in line
    assert facts_line([], [], 640, 480, True) == "Fast detectors found nothing they know."


def test_who_questions_are_recognised_in_arabic_and_english():
    assert is_who_question("مين هاد؟")
    assert is_who_question("who is that?")
    assert not is_who_question("شو قدامك؟")


COCO = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog",
    "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
    "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball", "kite",
    "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket", "bottle",
    "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch", "potted plant",
    "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard", "cell phone",
    "microwave", "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase", "scissors",
    "teddy bear", "hair drier", "toothbrush",
)


def test_every_coco_class_has_an_arabic_name():
    assert len(set(COCO)) == 80
    assert [n for n in COCO if n not in ARABIC] == []


def test_speech_counts_things_instead_of_repeating_them():
    chairs = [Detection("chair", 0.8, (300 + 30 * i, 200, 320 + 30 * i, 300)) for i in range(3)]
    tables = [Detection("table", 0.9, (10, 200, 60, 300)), Detection("dining table", 0.7,
                                                                      (500, 200, 600, 300))]
    said = speak_objects(chairs + tables, 640)
    assert said == "شايف طاولتين وتلات كراسي قدامي"
    assert speak_objects([Detection("chair", 0.9, (0, 0, 10, 10)),
                          Detection("chair", 0.9, (600, 0, 640, 10))], 640) == "شايف كرسيين"
    assert speak_objects([Detection("bus", 0.9, (0, 0, 640, 400))], 640) == "شايف باص قدامي"
    assert speak_objects([Detection("chair", 0.4, (0, 0, 10, 10))], 640) == "ما شايف شي بعرفه"


def test_a_box_inside_a_better_box_of_the_same_thing_is_one_object():
    rows = np.zeros((1, 300, 6), np.float32)
    rows[0, 0] = (100, 160, 300, 400, 0.6, 1)  # chair
    rows[0, 1] = (200, 170, 290, 390, 0.5, 1)  # a part of it, IoU < 0.6
    rows[0, 2] = (400, 160, 500, 400, 0.5, 1)  # another chair
    names = "{0: 'person', 1: 'chair', 2: 'sofa', 3: 'couch'}"
    found = ObjectDetector([YoloOnnx("unused", session=Session(rows, names=names))]).detect(
        np.zeros((480, 640, 3), np.uint8))
    assert len(found) == 2
