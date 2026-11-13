"""Converts a spider recording (.sprec) to a ROS 1 bag for the Point-LIO container.

  python -m spider_brain.rec2bag input.sprec output.bag

Topics and frames match Unitree's point_lio_unilidar L2 launch file: unilidar/cloud and
unilidar/imu. The point fields are x, y, z, intensity, ring, time.
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

import numpy as np

MAGIC = b"SPREC1\n"
_FRAME = struct.Struct("<BdII")
KIND_CLOUD, KIND_IMU = 1, 2
POINT_DTYPE = np.dtype([("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("intensity", "<f4"),
                        ("ring", "<u2"), ("time", "<f4")], align=False)


def read_frames(path: str | Path):
    with open(path, "rb") as f:
        if f.read(len(MAGIC)) != MAGIC:
            raise ValueError(f"{path} is not a spider recording")
        while True:
            header = f.read(_FRAME.size)
            if len(header) < _FRAME.size:
                return
            kind, stamp, cloud_id, size = _FRAME.unpack(header)
            payload = f.read(size)
            if len(payload) < size:
                return
            yield kind, stamp, cloud_id, payload


def to_points(payload: bytes) -> np.ndarray:
    raw = np.frombuffer(payload, dtype="<f4").reshape(-1, 6)
    out = np.empty(len(raw), dtype=POINT_DTYPE)
    for i, name in enumerate(("x", "y", "z", "intensity")):
        out[name] = raw[:, i]
    out["time"] = raw[:, 4]
    out["ring"] = raw[:, 5].astype(np.uint16)
    return out


def convert(source: str | Path, target: str | Path) -> dict[str, int]:
    from rosbags.rosbag1 import Writer
    from rosbags.typesys import Stores, get_typestore

    store = get_typestore(Stores.ROS1_NOETIC)
    t = store.types
    cloud_type, imu_type = "sensor_msgs/msg/PointCloud2", "sensor_msgs/msg/Imu"
    time_of = t["builtin_interfaces/msg/Time"]
    header_of = t["std_msgs/msg/Header"]
    field_of = t["sensor_msgs/msg/PointField"]
    # PointField datatypes: 2 = UINT16, 7 = FLOAT32
    fields = [
        field_of(name=n, offset=POINT_DTYPE.fields[n][1], datatype=2 if n == "ring" else 7, count=1)
        for n in POINT_DTYPE.names
    ]
    counts = {"clouds": 0, "imu": 0}
    with Writer(target) as writer:
        cloud_conn = writer.add_connection("unilidar/cloud", cloud_type, typestore=store)
        imu_conn = writer.add_connection("unilidar/imu", imu_type, typestore=store)
        for kind, stamp, _cloud_id, payload in read_frames(source):
            sec, nsec = int(stamp), int((stamp % 1.0) * 1e9)
            ns = sec * 10**9 + nsec
            header = header_of(seq=0, stamp=time_of(sec=sec, nanosec=nsec),
                               frame_id="unilidar_lidar" if kind == KIND_CLOUD else "unilidar_imu")
            if kind == KIND_CLOUD:
                points = to_points(payload)
                msg = t[cloud_type](
                    header=header, height=1, width=len(points), fields=fields, is_bigendian=False,
                    point_step=POINT_DTYPE.itemsize, row_step=POINT_DTYPE.itemsize * len(points),
                    data=np.frombuffer(points.tobytes(), dtype=np.uint8), is_dense=True,
                )
                writer.write(cloud_conn, ns, store.serialize_ros1(msg, cloud_type))
                counts["clouds"] += 1
            elif kind == KIND_IMU:
                d = np.frombuffer(payload, dtype="<f4").astype(np.float64)
                quat = t["geometry_msgs/msg/Quaternion"](x=d[0], y=d[1], z=d[2], w=d[3])
                vec = t["geometry_msgs/msg/Vector3"]
                zeros = np.zeros(9, dtype=np.float64)
                msg = t[imu_type](
                    header=header, orientation=quat, orientation_covariance=zeros,
                    angular_velocity=vec(x=d[4], y=d[5], z=d[6]),
                    angular_velocity_covariance=zeros,
                    linear_acceleration=vec(x=d[7], y=d[8], z=d[9]),
                    linear_acceleration_covariance=zeros,
                )
                writer.write(imu_conn, ns, store.serialize_ros1(msg, imu_type))
                counts["imu"] += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rec2bag")
    parser.add_argument("source")
    parser.add_argument("target")
    args = parser.parse_args(argv)
    print(convert(args.source, args.target), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
