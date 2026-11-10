#!/usr/bin/env bash
# The real-time gate (test RT1 in the plan). Run on the Pi, with the robot on its stand.
#   sudo bash bench_jitter.sh 3600
# Loads cores 1-3 as hard as the voice stack can, then reports control-loop timing on core 0.
# Run it twice: once with a copy of robot.yaml that has "rt: {enabled: false}" as the second
# argument, once with the shipped file. The gate is judged on the shipped setting.
set -euo pipefail
SECONDS_TO_RUN="${1:-3600}"
CONFIG="${2:-/etc/spider/robot.yaml}"
BODY=/opt/spider/spider-robot/body/.venv/bin/spider-body
command -v stress-ng >/dev/null || { echo "apt install stress-ng rt-tests"; exit 2; }

systemctl stop spider-body
trap 'systemctl start spider-body' EXIT

taskset -c 1-3 stress-ng --cpu 3 --vm 1 --vm-bytes 2G --io 1 --timeout "${SECONDS_TO_RUN}s" &
systemd-run --pipe --wait -p CPUAffinity=0 -p User=spider -p LimitRTPRIO=60 \
  -p LimitMEMLOCK=infinity -p "AmbientCapabilities=CAP_SYS_NICE CAP_IPC_LOCK" \
  "$BODY" --config "$CONFIG" --jitter-seconds "$SECONDS_TO_RUN" --text-logs
wait
echo "Pass: late p99.9 <= 5 ms, max <= 18 ms, overruns <= 1 per 10000 ticks, rt_ok true."
