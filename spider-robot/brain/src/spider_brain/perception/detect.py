"""Objects in camera frames: Ultralytics YOLO models exported to ONNX, run with onnxruntime.

No model file is in the repo (export one with perception-train/export_yolo.py). Two output layouts
are accepted, so any Ultralytics detect or YOLOE export works:
  end-to-end (1, N, 6[+32]):    x1, y1, x2, y2, score, class; no duplicates (YOLO26)
  raw        (1, 4+nc[+32], A): cx, cy, w, h, one score per class; NMS is done here
Detections are observations to speak. Nothing here may lead to motion.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

import numpy as np

IOU_NMS = 0.45
IOU_SAME = 0.6  # two models name the same thing in the same place: keep the higher score
MASK_COEFS = 32  # extra columns of segmentation exports (YOLOE-seg)


@dataclass(frozen=True)
class Detection:
    label: str
    score: float
    box: tuple[float, float, float, float]  # x1, y1, x2, y2 in frame pixels

    def side(self, width: int) -> str:
        cx = (self.box[0] + self.box[2]) / 2 / width
        return "left" if cx < 0.35 else "right" if cx > 0.65 else "centre"

    def distance(self, height: int) -> str:
        """Coarse, for speech only. The camera is ~15 cm up, so a floor object's bottom edge goes
        down the frame as it comes closer. The LiDAR, not this, is the distance truth."""
        bottom = self.box[3] / height
        return "near" if bottom > 0.85 else "far" if bottom < 0.6 else "middle"


def iou(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def letterbox(img: np.ndarray, size: int) -> tuple[np.ndarray, float, int, int]:
    """Resize keeping the aspect ratio and pad to size x size, as Ultralytics does."""
    import cv2

    h, w = img.shape[:2]
    scale = min(size / w, size / h)
    nw, nh = round(w * scale), round(h * scale)
    pad_x, pad_y = (size - nw) // 2, (size - nh) // 2
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    canvas[pad_y:pad_y + nh, pad_x:pad_x + nw] = cv2.resize(
        img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    return canvas, scale, pad_x, pad_y


def labels_from_metadata(session) -> list[str]:
    """Ultralytics writes {0: 'person', 1: 'bicycle', ...} into the ONNX metadata as 'names'."""
    raw = session.get_modelmeta().custom_metadata_map.get("names")
    if not raw:
        raise ValueError("the ONNX file has no 'names' metadata; export it with Ultralytics")
    names = ast.literal_eval(raw)
    return [str(names[i]) for i in sorted(names)]


class YoloOnnx:
    def __init__(self, path: str, min_score: float = 0.35, threads: int = 2,
                 session=None) -> None:
        if session is None:
            import onnxruntime as ort

            opts = ort.SessionOptions()
            opts.intra_op_num_threads = threads
            opts.inter_op_num_threads = 1
            session = ort.InferenceSession(path, opts, providers=["CPUExecutionProvider"])
        self.session = session
        inp = session.get_inputs()[0]
        self.input_name = inp.name
        self.size = inp.shape[2] if isinstance(inp.shape[2], int) else 640
        self.labels = labels_from_metadata(session)
        self.min_score = min_score

    def detect(self, bgr: np.ndarray) -> list[Detection]:
        canvas, scale, pad_x, pad_y = letterbox(bgr, self.size)
        x = np.ascontiguousarray(canvas[:, :, ::-1].transpose(2, 0, 1)[None], dtype=np.float32)
        out = self.session.run(None, {self.input_name: x / 255.0})[0]
        h, w = bgr.shape[:2]
        found = []
        for x1, y1, x2, y2, score, cls in self._rows(np.asarray(out)):
            box = (float(np.clip((x1 - pad_x) / scale, 0, w)),
                   float(np.clip((y1 - pad_y) / scale, 0, h)),
                   float(np.clip((x2 - pad_x) / scale, 0, w)),
                   float(np.clip((y2 - pad_y) / scale, 0, h)))
            if box[2] > box[0] and box[3] > box[1]:
                found.append(Detection(self.labels[int(cls)], float(score), box))
        return found

    def _rows(self, out: np.ndarray) -> np.ndarray:
        nc = len(self.labels)
        if out.ndim != 3 or out.shape[0] != 1:
            raise ValueError(f"unexpected YOLO output shape {out.shape}")
        if out.shape[1] in (4 + nc, 4 + nc + MASK_COEFS):  # raw, channels first
            return self._nms(out[0].T[:, :4 + nc])
        if out.shape[2] in (6, 6 + MASK_COEFS):  # end-to-end
            rows = out[0, :, :6]
            return rows[rows[:, 4] >= self.min_score]
        raise ValueError(f"unknown YOLO output {out.shape} for {nc} classes")

    def _nms(self, pred: np.ndarray) -> np.ndarray:
        import cv2

        scores = pred[:, 4:]
        cls = scores.argmax(axis=1)
        best = scores[np.arange(len(scores)), cls]
        keep = best >= self.min_score
        pred, cls, best = pred[keep], cls[keep], best[keep]
        if len(pred) == 0:
            return np.zeros((0, 6), dtype=np.float32)
        xywh = np.stack([pred[:, 0] - pred[:, 2] / 2, pred[:, 1] - pred[:, 3] / 2,
                         pred[:, 2], pred[:, 3]], axis=1)
        idx = np.asarray(cv2.dnn.NMSBoxesBatched(
            xywh.tolist(), best.tolist(), cls.tolist(), self.min_score, IOU_NMS), dtype=int)
        idx = idx.reshape(-1)
        b = xywh[idx]
        return np.stack([b[:, 0], b[:, 1], b[:, 0] + b[:, 2], b[:, 1] + b[:, 3],
                         best[idx], cls[idx]], axis=1)


class ObjectDetector:
    """Several models (COCO + home classes) as one; cross-model duplicates removed."""

    def __init__(self, models: list[YoloOnnx]) -> None:
        self.models = models

    def detect(self, bgr: np.ndarray) -> list[Detection]:
        found = sorted((d for m in self.models for d in m.detect(bgr)), key=lambda d: -d.score)
        kept: list[Detection] = []
        for d in found:
            same = ALIASES.get(d.label, d.label)
            if not any(ALIASES.get(k.label, k.label) == same and iou(k.box, d.box) > IOU_SAME
                       for k in kept):
                kept.append(d)
        return kept


ALIASES = {"sofa": "couch", "dining table": "table"}  # COCO vs HomeObjects names

ARABIC = {
    "person": "شخص", "chair": "كرسي", "couch": "كنباية", "sofa": "كنباية", "bed": "تخت",
    "dining table": "طاولة", "table": "طاولة", "tv": "تلفزيون", "laptop": "لابتوب",
    "potted plant": "نبتة", "bottle": "قنينة", "cup": "كاسة", "book": "كتاب", "door": "باب",
    "window": "شباك", "lamp": "أباجورة", "wardrobe": "خزانة", "photo frame": "برواز",
    "cat": "بسة", "dog": "كلب", "backpack": "شنتة", "cell phone": "موبايل", "remote": "ريموت",
    "clock": "ساعة", "refrigerator": "براد", "sink": "مجلى", "keyboard": "كيبورد",
    "mouse": "ماوس", "vase": "مزهرية", "handbag": "جزدان", "suitcase": "شنتة سفر",
}
SIDE_AR = {"left": "عاليسار", "right": "عاليمين", "centre": "قدامي"}


def speak_objects(dets: list[Detection], width: int, limit: int = 4) -> str:
    """Short Levantine sentence for Piper. Unknown labels are said in English."""
    things = [d for d in dets if d.label != "person"][:limit]
    if not things:
        return "ما شايف شي بعرفه"
    return "شايف " + " و".join(f"{ARABIC.get(d.label, d.label)} {SIDE_AR[d.side(width)]}"
                               for d in things)
