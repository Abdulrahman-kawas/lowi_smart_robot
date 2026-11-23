import asyncio
from types import SimpleNamespace

import numpy as np

from spider_brain.perception import cli


def settings(tmp_path):
    return SimpleNamespace(perception_dir=str(tmp_path), face_threshold=0.363, face_margin=0.05)


def book(path):
    np.savez(path, emb=np.eye(128, dtype=np.float32)[:2], owner=np.array([0, 1], np.int32),
             ids=np.array(["ali", "sami"]), spoken=np.array(["Ali", "سامي"]))


def test_faces_cli_lists_and_forgets_without_needing_model_files(tmp_path, capsys):
    path = tmp_path / "faces.npz"
    book(path)
    cfg = settings(tmp_path)

    assert cli.faces(cfg, "list", None) == 0
    out = capsys.readouterr().out
    assert "ali: Ali" in out and "sami: سامي" in out

    assert cli.faces(cfg, "forget", "ali") == 0
    assert "removed" in capsys.readouterr().out
    assert [str(s) for s in np.load(path, allow_pickle=False)["ids"]] == ["sami"]

    assert cli.faces(cfg, "forget", "ali") == 0
    assert "not in faces.npz" in capsys.readouterr().out


def test_faces_cli_reports_an_empty_book(tmp_path, capsys):
    assert cli.faces(settings(tmp_path), "list", None) == 0
    assert "nobody is enrolled" in capsys.readouterr().out


def test_grab_saves_frames_without_calling_any_motion(tmp_path):
    calls = []

    class Robot:
        async def snapshot(self, **kwargs):
            calls.append(kwargs)
            return b"jpeg"

    out = tmp_path / "frames"
    assert asyncio.run(cli.grab(Robot(), out, 2, 0)) == 0
    assert len(list(out.glob("*.jpg"))) == 2
    assert calls == [{"timeout_s": 3.0, "human": True}] * 2
