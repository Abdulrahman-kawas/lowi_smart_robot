#!/usr/bin/env bash
# Runs one mapping job on the worker: recording in, point cloud map out.
#   /opt/spider/run_job.sh <job id>
set -euo pipefail
JOB="$1"
[[ "$JOB" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "bad job id"; exit 2; }
DATA=/data
[[ -s "$DATA/$JOB.bag" ]] || { echo "no recording uploaded"; exit 2; }
docker run --rm -v "$DATA:/data" spider-slam:noetic /run_slam.sh "$JOB"
[[ -s "$DATA/$JOB.pcd" ]] || { echo "SLAM produced no map"; exit 3; }
