from pathlib import Path
from types import SimpleNamespace

from spider_common.link import InMemoryHub

import spider_brain.perception as perception
from spider_brain.config import Settings
from spider_brain.mobile.devices import BRAIN_ROOT
from spider_brain.perception import make_perception, perception_dir
from spider_brain.robot_client import RobotClient
from spider_brain.service import BrainService


def test_relative_perception_dir_is_under_the_gitignored_brain_data():
    path = perception_dir(SimpleNamespace(perception_dir="data/perception"))
    assert path == BRAIN_ROOT / "data" / "perception"
    assert path.parent.parent == Path(__file__).resolve().parents[1]  # spider-robot/brain


def test_absolute_perception_dir_is_kept(tmp_path):
    assert perception_dir(SimpleNamespace(perception_dir=str(tmp_path))) == tmp_path


def _settings(tmp_path, **kw):
    return Settings(_env_file=None, dashboard=False, perception=True,
                    perception_dir=str(tmp_path), **kw)


def test_missing_models_leave_perception_empty_instead_of_failing(tmp_path):
    p = make_perception(_settings(tmp_path))
    try:
        assert p.objects is None and p.faces is None and p.gestures is None
    finally:
        p.close()


def test_a_broken_object_model_is_skipped(tmp_path):
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "yolo26n.onnx").write_bytes(b"not an onnx file")
    p = make_perception(_settings(tmp_path))
    try:
        assert p.objects is None
    finally:
        p.close()


async def _service(settings):
    link = InMemoryHub().endpoint(RobotClient.subscriptions("spider-01"))
    await link.start()
    return BrainService(settings, link=link, vision=object(), planner_factory=lambda tier: None)


async def test_brain_starts_when_perception_cannot(tmp_path, monkeypatch):
    def boom(_settings):
        raise ImportError("No module named 'mediapipe'")

    monkeypatch.setattr(perception, "make_perception", boom)
    svc = await _service(_settings(tmp_path))
    assert svc.perception is None and svc.watcher is None
    assert "mediapipe" in svc.perception_error


async def test_brain_with_perception_and_no_models_still_has_watch_mode(tmp_path):
    svc = await _service(_settings(tmp_path))
    try:
        assert svc.perception is not None and svc.watcher is not None
        assert svc.perception_error is None
    finally:
        svc.perception.close()
