from pathlib import Path

import pytest

from spider_body.config import load_config

CONFIG = Path(__file__).resolve().parents[1] / "config" / "robot.sim.yaml"


@pytest.fixture
def cfg():
    return load_config(CONFIG, calibration="/nonexistent")
