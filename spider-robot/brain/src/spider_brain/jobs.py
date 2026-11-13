"""On-demand LiDAR recording and mapping. AWS is off by default and only ever processes a copy.

Recording happens on the robot and never depends on AWS; if the worker cannot start, the recording
stays on the home server and the job can be retried. The worker instance stops itself: that timer
lives on the instance (infra/aws/worker), so a stop still happens if this server dies mid-job. The
stop call here is the fast path. The AWS credentials exist only on this server, and the Pi has none.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path

from spider_common.protocol import RecordEvent, RecordRequest

log = logging.getLogger(__name__)
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]
START_TIMEOUT_S = 300.0


class AwsWorker:
    """Start, stop and describe one instance. Nothing else is possible with its credentials."""

    def __init__(self, ec2, instance_id: str, ssh_target: str, poll_s: float = 5.0) -> None:
        self.ec2, self.instance_id, self.ssh_target = ec2, instance_id, ssh_target
        self.poll_s = poll_s

    @classmethod
    def from_settings(cls, settings) -> AwsWorker | None:
        if not settings.aws_worker_instance_id:
            return None
        import boto3

        return cls(boto3.client("ec2", region_name=settings.aws_region),
                   settings.aws_worker_instance_id, settings.aws_worker_ssh_target)

    def _state(self) -> str:
        reply = self.ec2.describe_instances(InstanceIds=[self.instance_id])
        return reply["Reservations"][0]["Instances"][0]["State"]["Name"]

    async def start(self) -> None:
        await asyncio.to_thread(self.ec2.start_instances, InstanceIds=[self.instance_id])
        end = time.monotonic() + START_TIMEOUT_S
        while time.monotonic() < end:
            if await asyncio.to_thread(self._state) == "running":
                return
            await asyncio.sleep(self.poll_s)
        raise TimeoutError("the AWS worker did not start in time")

    async def stop(self) -> None:
        await asyncio.to_thread(self.ec2.stop_instances, InstanceIds=[self.instance_id])


async def _run(*argv: str) -> None:
    """Fixed argv, no shell."""
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"{argv[0]} failed: {err.decode(errors='replace')[:300]}")


def _convert(source: Path, target: Path) -> None:
    from .rec2bag import convert  # needs the "slam" extra; only this server has it

    convert(source, target)


class JobManager:
    def __init__(
        self, robot, settings, worker: AwsWorker | None, runner=_run, converter=_convert
    ) -> None:
        self.robot, self.settings, self.worker = robot, settings, worker
        self.runner, self.converter = runner, converter
        self.events: dict[str, RecordEvent] = {}

    def on_status(self, _topic: str, payload: bytes) -> None:
        ev = RecordEvent.model_validate_json(payload)
        self.events[ev.job_id] = ev
        log.info("recording %s: %s %s", ev.job_id, ev.state, ev.detail)

    def start_recording(self, seconds: float) -> str:
        job_id = time.strftime("rec-%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        req = RecordRequest(action="start", job_id=job_id, duration_s=seconds)
        self.robot.link.publish(self.robot.topics.record_cmd, req.model_dump_json(), qos=1)
        return job_id

    async def process(self, job_id: str) -> str:
        """Fetch the recording, then run the mapping job. The recording survives any failure."""
        s = self.settings
        ev = self.events.get(job_id)
        if ev is None or ev.state != "finished":
            return f"Recording {job_id} has not finished."
        if not s.pi_ssh_target:
            return "SB_PI_SSH_TARGET is not set."
        local_dir = Path(s.recordings_dir).expanduser()
        local_dir.mkdir(parents=True, exist_ok=True)
        local = local_dir / f"{job_id}.sprec"
        try:
            await self.runner("rsync", "-az", "--partial", "-e", " ".join(["ssh", *SSH_OPTS]),
                              f"{s.pi_ssh_target}:{ev.path}", str(local))
        except RuntimeError as exc:
            return f"Could not copy the recording from the Pi: {exc}"
        if self.worker is None:
            return f"Recording saved at {local}. No AWS worker is configured."
        bag = local.with_suffix(".bag")
        try:  # before the worker starts: a conversion failure should not cost an instance hour
            await asyncio.to_thread(self.converter, local, bag)
        except Exception as exc:
            return f"Could not convert the recording ({exc}). It is safe at {local}."
        try:
            await self.worker.start()
        except Exception as exc:
            return f"The AWS worker did not start ({exc}). The recording is safe at {local}."
        target = self.worker.ssh_target
        try:
            await self.runner("rsync", "-az", "--partial", "-e", " ".join(["ssh", *SSH_OPTS]),
                              str(bag), f"{target}:/data/{job_id}.bag")
            await self.runner("ssh", *SSH_OPTS, target, "/opt/spider/run_job.sh", job_id)
            await self.runner("rsync", "-az", "-e", " ".join(["ssh", *SSH_OPTS]),
                              f"{target}:/data/{job_id}.pcd", str(local_dir))
        except RuntimeError as exc:
            return f"Mapping failed ({exc}). The recording is safe at {local}."
        finally:
            await self.worker.stop()
        return f"Map ready at {local_dir / (job_id + '.pcd')}."
