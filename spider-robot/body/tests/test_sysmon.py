import json

import pytest

from spider_body.sysmon import (
    SOFT_TEMP_NOW,
    THROTTLED_NOW,
    UNDERVOLT_EVER,
    UNDERVOLT_NOW,
    assess,
    available_mem_mb,
    parse_failed_units,
    parse_tailscale_path,
    read_int,
)


def test_healthy():
    assert assess(0, 55.0, 2000.0, 9000.0) == ("ok", "")


@pytest.mark.parametrize(
    ("flags", "temp", "level"),
    [
        (UNDERVOLT_NOW, 50.0, "down"),
        (THROTTLED_NOW, 50.0, "down"),
        (0, 80.0, "down"),
        (SOFT_TEMP_NOW, 50.0, "degraded"),
        (UNDERVOLT_EVER, 50.0, "degraded"),
        (0, 76.0, "degraded"),
        (0, None, "degraded"),
    ],
)
def test_levels(flags, temp, level):
    assert assess(flags, temp, 2000.0, 9000.0)[0] == level


def test_low_memory_and_disk_are_reported():
    assert "MB free" in assess(0, 50.0, 100.0, 9000.0)[1]
    assert "disk" in assess(0, 50.0, 2000.0, 100.0)[1]


def test_read_int_handles_hex_and_missing(tmp_path):
    f = tmp_path / "v"
    f.write_text("0x50005\n")
    assert read_int(f, 16) == 0x50005
    assert read_int(tmp_path / "missing") is None


def test_available_memory_parsing(tmp_path):
    f = tmp_path / "meminfo"
    f.write_text("MemTotal: 4000000 kB\nMemAvailable: 2048000 kB\n")
    assert available_mem_mb(f) == 2000.0
    assert available_mem_mb(tmp_path / "missing") is None


def _status(**node):
    return json.dumps({"Peer": {"k": {"HostName": "server", "Online": True, **node}}})


def test_tailscale_paths():
    assert parse_tailscale_path(_status(CurAddr="1.2.3.4:41641"), "server") == "direct"
    assert parse_tailscale_path(_status(Relay="tok", CurAddr=""), "server") == "relay"
    assert parse_tailscale_path(_status(Online=False), "server") == "none"
    assert parse_tailscale_path(_status(), "other") == "none"
    assert parse_tailscale_path(None, "server") is None


def test_failed_units_keep_only_ours():
    text = "spider-voice.service loaded failed failed x\nsnapd.service loaded failed failed y\n"
    assert parse_failed_units(text) == ["spider-voice.service"]
