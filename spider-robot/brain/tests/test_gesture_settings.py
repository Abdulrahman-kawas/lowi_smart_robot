import pytest
from pydantic import ValidationError

from spider_brain.config import Settings


@pytest.mark.parametrize("action", ["perform:hi", "walk", "sit", "estop_release"])
def test_moving_gesture_actions_are_refused(action):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, gesture_actions={"Open_Palm": action})


def test_safe_gesture_actions_are_allowed():
    settings = Settings(_env_file=None, gesture_actions={
        "Open_Palm": "stop", "Victory": "say:مرحبا",
    })
    assert settings.gesture_actions["Open_Palm"] == "stop"
    assert settings.gesture_actions["Victory"] == "say:مرحبا"
