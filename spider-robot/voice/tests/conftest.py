import pytest

from spider_voice.config import VoiceConfig


@pytest.fixture
def cfg():
    return VoiceConfig()
