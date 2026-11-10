import asyncio
import json
import struct

import numpy as np
import pytest
import zmq
import zmq.asyncio
from spider_common.link import InMemoryHub
from spider_common.protocol import RecordRequest, Topics

from spider_body.config import RecorderCfg
from spider_body.recorder import (
    KIND_CLOUD,
    KIND_IMU,
    MAGIC,
    Recorder,
    Recording,
    encode_frame,
    read_frames,
)


def cloud_parts(stamp=1.5, cloud_id=7, n=2):
    points = np.arange(n * 6, dtype="<f4")
    return [b"cloudx", struct.pack("<dII", stamp, cloud_id, n), points.tobytes()]


def imu_parts(stamp=2.5):
    return [b"imux", struct.pack("<d", stamp), np.arange(10, dtype="<f4").tobytes()]


def test_frames_round_trip(tmp_path):
    rec = Recording(tmp_path / "a.sprec", 10**9)
    rec.add(encode_frame(cloud_parts()))
    rec.add(encode_frame(imu_parts()))
    rec.close()
    frames = list(read_frames(tmp_path / "a.sprec"))
    assert [f[0] for f in frames] == [KIND_CLOUD, KIND_IMU]
    assert frames[0][1:3] == (1.5, 7) and frames[1][1] == 2.5
    assert np.frombuffer(frames[0][3], dtype="<f4")[-1] == 11.0


def test_a_truncated_file_stays_readable_up_to_the_last_full_frame(tmp_path):
    path = tmp_path / "b.sprec"
    rec = Recording(path, 10**9)
    rec.add(encode_frame(imu_parts(1.0)))
    rec.add(encode_frame(imu_parts(2.0)))
    rec.close()
    path.write_bytes(path.read_bytes()[:-5])
    assert [f[1] for f in read_frames(path)] == [1.0]


def test_rejects_a_file_that_is_not_a_recording(tmp_path):
    bad = tmp_path / "x"
    bad.write_bytes(b"nope")
    with pytest.raises(ValueError):
        list(read_frames(bad))
    assert MAGIC.startswith(b"SPREC")


def test_unexpected_messages_are_skipped():
    assert encode_frame([b"cloud", b"", b""]) is None
    assert encode_frame([b"cloudx", b"short", b""]) is None
    assert encode_frame([b"x"]) is None


def test_size_limit(tmp_path):
    rec = Recording(tmp_path / "c.sprec", 10)
    rec.add(encode_frame(imu_parts()))
    assert rec.full
    rec.close()


def _recorder(tmp_path):
    hub = InMemoryHub()
    t = Topics("r1")
    link = hub.endpoint([t.record_cmd])
    brain = hub.endpoint([t.record_event])
    return Recorder(RecorderCfg(out_dir=str(tmp_path)), link, "r1"), link, brain, t


async def test_second_job_is_refused_while_one_runs(tmp_path):
    recorder, link, brain, _ = _recorder(tmp_path)
    await link.start()
    await brain.start()

    async def forever(job_id, duration_s):
        await asyncio.Event().wait()

    recorder.record = forever
    recorder.on_request(RecordRequest(action="start", job_id="one").model_dump_json())
    await asyncio.sleep(0)
    recorder.on_request(RecordRequest(action="start", job_id="two").model_dump_json())
    event = json.loads(brain.inbox.queue.get_nowait().payload)
    assert event["job_id"] == "two" and event["state"] == "failed"
    recorder._task.cancel()
    await asyncio.gather(recorder._task, return_exceptions=True)


async def test_invalid_request_is_ignored(tmp_path):
    recorder, link, _, _ = _recorder(tmp_path)
    await link.start()
    recorder.on_request(b'{"action": "start", "job_id": "../../etc"}')
    assert recorder._task is None


async def test_recording_stops_when_the_disk_is_nearly_full(tmp_path):
    hub = InMemoryHub()
    t = Topics("r1")
    link = hub.endpoint([t.record_event])
    await link.start()
    cfg = RecorderCfg(endpoint="ipc:///tmp/spider_test_lowdisk.ipc", out_dir=str(tmp_path),
                      min_free_bytes=1000)
    recorder = Recorder(cfg, link, "r1", free_bytes=lambda _path: 10)
    sock = zmq.asyncio.Context.instance().socket(zmq.PUB)
    sock.bind(cfg.endpoint)
    task = asyncio.create_task(recorder.record("j1", 5.0))
    for _ in range(20):
        await asyncio.sleep(0.01)
        await sock.send_multipart([b"imux", struct.pack("<d", 1.0), b"\0" * 40])
        if task.done():
            break
    await asyncio.wait_for(task, 30.0)
    sock.close(linger=0)
    finished = [m for m in link.published if b'"finished"' in m.payload]
    assert finished and b"disk nearly full" in finished[0].payload
