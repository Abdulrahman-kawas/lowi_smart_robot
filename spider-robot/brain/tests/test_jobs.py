import struct
from types import SimpleNamespace

import numpy as np
import pytest
from spider_common.link import InMemoryHub
from spider_common.protocol import RecordEvent, RecordRequest, Topics

from spider_brain.jobs import AwsWorker, JobManager
from spider_brain.rec2bag import MAGIC, convert, to_points

ROBOT = "spider-01"
T = Topics(ROBOT)


class FakeEc2:
    def __init__(self, state="running"):
        self.state, self.started, self.stopped = state, 0, 0

    def start_instances(self, InstanceIds):
        self.started += 1

    def stop_instances(self, InstanceIds):
        self.stopped += 1

    def describe_instances(self, InstanceIds):
        return {"Reservations": [{"Instances": [{"State": {"Name": self.state}}]}]}


class Recorder:
    def __init__(self, fail_on=None):
        self.calls, self.fail_on = [], fail_on

    async def __call__(self, *argv):
        self.calls.append(argv)
        if self.fail_on and any(self.fail_on in a for a in argv):
            raise RuntimeError("boom")


async def manager(tmp_path, ec2=None, runner=None, target="spider@pi"):
    hub = InMemoryHub()
    link = hub.endpoint([])
    watcher = hub.endpoint([T.record_cmd])
    await link.start()
    await watcher.start()
    robot = SimpleNamespace(link=link, topics=T)
    settings = SimpleNamespace(pi_ssh_target=target, recordings_dir=str(tmp_path))
    worker = AwsWorker(ec2, "i-1", "ubuntu@worker", poll_s=0.0) if ec2 else None
    jobs = JobManager(robot, settings, worker, runner=runner or Recorder(),
                      converter=lambda source, target: None)
    return jobs, robot, watcher


def finished(job_id="j1"):
    return RecordEvent(job_id=job_id, state="finished", path=f"/var/lib/spider/rec/{job_id}.sprec")


async def test_start_recording_publishes_a_valid_request(tmp_path):
    jobs, _, watcher = await manager(tmp_path)
    job_id = jobs.start_recording(30.0)
    req = RecordRequest.model_validate_json(watcher.inbox.queue.get_nowait().payload)
    assert req.action == "start" and req.job_id == job_id and req.duration_s == 30.0


async def test_unfinished_recording_is_not_processed(tmp_path):
    runner = Recorder()
    jobs, *_ = await manager(tmp_path, runner=runner)
    assert "has not finished" in await jobs.process("nope")
    assert runner.calls == []


async def test_without_a_worker_the_recording_is_just_saved(tmp_path):
    jobs, robot, _ = await manager(tmp_path)
    jobs.on_status(T.record_event, finished().model_dump_json().encode())
    assert "No AWS worker" in await jobs.process("j1")


async def test_full_job_starts_runs_and_always_stops_the_worker(tmp_path):
    ec2, runner = FakeEc2(), Recorder()
    jobs, robot, _ = await manager(tmp_path, ec2, runner)
    jobs.on_status(T.record_event, finished().model_dump_json().encode())
    assert "Map ready" in await jobs.process("j1")
    assert ec2.started == 1 and ec2.stopped == 1
    assert any("run_job.sh" in " ".join(c) for c in runner.calls)


async def test_a_failed_job_keeps_the_recording_and_still_stops_the_worker(tmp_path):
    ec2, runner = FakeEc2(), Recorder(fail_on="run_job.sh")
    jobs, robot, _ = await manager(tmp_path, ec2, runner)
    jobs.on_status(T.record_event, finished().model_dump_json().encode())
    result = await jobs.process("j1")
    assert "safe at" in result and ec2.stopped == 1


async def test_failed_conversion_never_starts_the_worker(tmp_path):
    def broken(source, target):
        raise ValueError("not a recording")

    ec2 = FakeEc2()
    jobs, robot, _ = await manager(tmp_path, ec2)
    jobs.converter = broken
    jobs.on_status(T.record_event, finished().model_dump_json().encode())
    assert "Could not convert" in await jobs.process("j1")
    assert ec2.started == 0


async def test_worker_that_will_not_start_loses_nothing(tmp_path):
    class Broken(FakeEc2):
        def start_instances(self, InstanceIds):
            raise RuntimeError("capacity")

    ec2 = Broken()
    jobs, robot, _ = await manager(tmp_path, ec2)
    jobs.on_status(T.record_event, finished().model_dump_json().encode())
    assert "did not start" in await jobs.process("j1")
    assert ec2.stopped == 0


def test_points_are_packed_for_point_lio():
    raw = np.array([[1, 2, 3, 40, 0.5, 7]], dtype="<f4")
    p = to_points(raw.tobytes())
    assert p["ring"][0] == 7 and p["time"][0] == pytest.approx(0.5) and p["x"][0] == 1.0


def _sample(path):
    frame = struct.Struct("<BdII")
    cloud = np.array([[1, 2, 3, 40, 0.5, 7]], dtype="<f4").tobytes()
    imu = np.arange(10, dtype="<f4").tobytes()
    path.write_bytes(MAGIC + frame.pack(1, 12.5, 3, len(cloud)) + cloud
                     + frame.pack(2, 12.6, 0, len(imu)) + imu)


def test_recording_converts_to_a_readable_bag(tmp_path):
    pytest.importorskip("rosbags")
    from rosbags.rosbag1 import Reader
    from rosbags.typesys import Stores, get_typestore

    src, dst = tmp_path / "a.sprec", tmp_path / "a.bag"
    _sample(src)
    assert convert(src, dst) == {"clouds": 1, "imu": 1}
    store = get_typestore(Stores.ROS1_NOETIC)
    with Reader(dst) as reader:
        seen = {}
        for conn, _ts, raw in reader.messages():
            seen[conn.topic] = store.deserialize_ros1(raw, conn.msgtype)
    assert seen["unilidar/cloud"].width == 1 and seen["unilidar/imu"].linear_acceleration.z == 9.0
    assert [f.name for f in seen["unilidar/cloud"].fields][-2:] == ["ring", "time"]
