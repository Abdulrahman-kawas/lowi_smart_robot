"""camera.device takes a stable /dev/v4l/by-id path as well as a /dev/videoN number."""

import pytest

from spider_body.config import CameraCfg

BRAVE = "/dev/v4l/by-id/usb-AKASO_Brave_7_LE_00.00.01-video-index0"


def test_device_number_still_works():
    assert CameraCfg().device == 0
    assert CameraCfg.model_validate({"device": 1}).device == 1


def test_device_path_is_kept_as_a_string():
    assert CameraCfg.model_validate({"device": BRAVE}).device == BRAVE


def test_open_failure_names_the_path():
    pytest.importorskip("cv2")
    from spider_body.hw.camera import OpenCvCamera

    missing = "/dev/v4l/by-id/no-such-camera-video-index0"
    with pytest.raises(RuntimeError, match=missing):
        OpenCvCamera(CameraCfg(device=missing))._open()


def test_open_failure_names_the_number():
    pytest.importorskip("cv2")
    from spider_body.hw.camera import OpenCvCamera

    with pytest.raises(RuntimeError, match="/dev/video99"):
        OpenCvCamera(CameraCfg(device=99))._open()
