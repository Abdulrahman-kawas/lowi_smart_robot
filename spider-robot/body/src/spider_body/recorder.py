"""spider-recorder: writes the full LiDAR and IMU stream to disk, on request, from cores 1-3.

It subscribes to the bridge's recording socket only while a job runs, so an idle recorder costs
nothing, and it can never affect the control loop. Recording works with no network and no AWS.

File format: the magic bytes, then frames of (header, payload).

  header  "<BdII"   kind (1 cloud, 2 IMU), sensor time, cloud id, payload bytes
  cloud   float32[n*6]   x, y, z, intensity, point time, ring
  IMU     float32[10]    quaternion xyzw, gyro xyz, accel xyz

A file cut short by a crash or power loss stays readable up to its last complete frame.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import signal
import struct
import time
from collections.abc import Iterator
from pathlib import Path

from pydantic import ValidationError
from spider_common.link import Link, MqttLink
from spider_common.obs import setup_logging
from spider_common.protocol import RecordEvent, RecordRequest, Topics

from .config import BodyConfig, RecorderCfg, broker_settings, load_config

log = logging.getLogger("spider_recorder")
MAGIC = b"SPREC1\n"
FRAME = struct.Struct("<BdII")
KIND_CLOUD, KIND_IMU = 1, 2
_CLOUD_HEADER = struct.Struct("<dII")
_STAMP = struct.Struct("<d")
FLUSH_BYTES = 256 * 1024
DISK_CHECK_FRAMES = 500


def encode_frame(parts: list[bytes]) -> bytes | None:
    """One multipart message from the bridge as one file frame. None for anything unexpected."""
    if len(parts) != 3:
        return None
    if parts[0] == b"cloudx" and len(parts[1]) == _CLOUD_HEADER.size:
        stamp, cloud_id, _n = _CLOUD_HEADER.unpack(parts[1])
        return FRAME.pack(KIND_CLOUD, stamp, cloud_id, len(parts[2])) + parts[2]
    if parts[0] == b"imux" and len(parts[1]) == _STAMP.size:
        stamp = _STAMP.unpack(parts[1])[0]
        return FRAME.pack(KIND_IMU, stamp, 0, len(parts[2])) + parts[2]
    return None


def read_frames(path: str | Path) -> Iterator[tuple[int, float, int, bytes]]:
    """Yield (kind, stamp, cloud id, payload), stopping at the first incomplete frame."""
    with open(path, "rb") as f:
        if f.read(len(MAGIC)) != MAGIC:
            raise ValueError(f"{path} is not a spider recording")
        while True:
            header = f.read(FRAME.size)
            if len(header) < FRAME.size:
                return
            kind, stamp, cloud_id, size = FRAME.unpack(header)
            payload = f.read(size)
            if len(payload) < size:
                return
            yield kind, stamp, cloud_id, payload


class Recording:
    """One open recording file with a write buffer. Writes happen off the event loop."""

    def __init__(self, path: Path, max_bytes: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.max_bytes = max_bytes
        self.size = len(MAGIC)
        self._buffer = bytearray()
        self._file = open(path, "wb")  # noqa: SIM115 - closed in close(), lives across awaits
        self._file.write(MAGIC)

    @property
    def full(self) -> bool:
        return self.size >= self.max_bytes

    def add(self, frame: bytes) -> bool:
        self._buffer += frame
        self.size += len(frame)
        return len(self._buffer) >= FLUSH_BYTES

    def flush(self) -> None:
        self._file.write(bytes(self._buffer))
        self._buffer.clear()
        self._file.flush()

    def close(self) -> None:
        self.flush()
        self._file.close()


class Recorder:
    def __init__(self, cfg: RecorderCfg, link: Link, robot_id: str, free_bytes=None) -> None:
        self.cfg, self.link = cfg, link
        self._free = free_bytes or (lambda path: shutil.disk_usage(path).free)
        self.topics = Topics(robot_id)
        self.job_id: str | None = None
        self._task: asyncio.Task | None = None

    def _event(self, job_id: str, state, detail: str = "", rec: Recording | None = None) -> None:
        ev = RecordEvent(job_id=job_id, state=state, detail=detail,
                         path=str(rec.path) if rec else "", size_bytes=rec.size if rec else 0)
        self.link.publish(self.topics.record_event, ev.model_dump_json(), qos=1)

    def on_request(self, payload: bytes | str) -> None:
        try:
            req = RecordRequest.model_validate_json(payload)
        except ValidationError:
            log.warning("invalid recording request")
            return
        if req.action == "stop":
            if self._task is not None and req.job_id == self.job_id:
                self._task.cancel()
            return
        if self._task is not None and not self._task.done():
            self._event(req.job_id, "failed", f"busy with {self.job_id}")
            return
        self.job_id = req.job_id
        self._task = asyncio.create_task(self.record(req.job_id, req.duration_s))

    async def record(self, job_id: str, duration_s: float) -> None:
        import zmq
        import zmq.asyncio

        rec = Recording(Path(self.cfg.out_dir) / f"{job_id}.sprec", self.cfg.max_bytes)
        sock = zmq.asyncio.Context.instance().socket(zmq.SUB)
        sock.setsockopt(zmq.SUBSCRIBE, b"")
        sock.setsockopt(zmq.RCVHWM, 2048)
        sock.connect(self.cfg.endpoint)
        self._event(job_id, "recording", rec=rec)
        deadline = time.monotonic() + duration_s
        detail = "time limit reached"
        frames = 0
        try:
            while (left := deadline - time.monotonic()) > 0 and not rec.full:
                frames += 1
                if frames % DISK_CHECK_FRAMES == 1 and (
                    await asyncio.to_thread(self._free, self.cfg.out_dir)
                ) < self.cfg.min_free_bytes:
                    detail = "disk nearly full"
                    break
                try:
                    parts = await asyncio.wait_for(sock.recv_multipart(), min(left, 1.0))
                except TimeoutError:
                    continue
                frame = encode_frame(parts)
                if frame is not None and rec.add(frame):
                    await asyncio.to_thread(rec.flush)
            if rec.full:
                detail = "size limit reached"
        except asyncio.CancelledError:
            detail = "stopped on request"
        finally:
            sock.close(linger=0)
            await asyncio.to_thread(rec.close)
        self._event(job_id, "finished", detail, rec)

    async def pump(self) -> None:
        async for msg in self.link.messages():
            if msg.topic == self.topics.record_cmd:
                self.on_request(msg.payload)


def build_link(cfg: BodyConfig) -> MqttLink:
    r = cfg.recorder
    return MqttLink(
        broker_settings(cfg.mqtt, r.client_id, r.username, r.password_file),
        subscriptions=[Topics(cfg.robot_id).record_cmd],
    )


async def run(cfg: BodyConfig) -> None:
    link = build_link(cfg)
    recorder = Recorder(cfg.recorder, link, cfg.robot_id)
    await link.start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    pump = asyncio.create_task(recorder.pump())
    await stop.wait()
    pump.cancel()
    await asyncio.gather(pump, return_exceptions=True)
    await link.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="spider-recorder")
    parser.add_argument("--config", default="config/robot.yaml")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    setup_logging(args.log_level)
    asyncio.run(run(load_config(args.config, "/nonexistent")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
