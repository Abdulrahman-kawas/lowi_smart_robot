#!/usr/bin/env bash
# Runs on the AWS instance every minute. Stops the instance when the job is done, after 15 idle
# minutes, or at a hard maximum, even if the link home is dead.
# The instance's shutdown behaviour must be "stop" (see worker_setup.sh).
set -euo pipefail
IDLE_LIMIT_S="${IDLE_LIMIT_S:-900}"
HARD_LIMIT_S="${HARD_LIMIT_S:-14400}"  # 4 hours
ACTIVITY=/run/spider-job-activity

uptime_s="$(cut -d. -f1 /proc/uptime)"
if (( uptime_s >= HARD_LIMIT_S )); then
  logger -t spider-autostop "hard limit reached; stopping"
  /sbin/shutdown -h now
  exit 0
fi

if pgrep -f run_job.sh >/dev/null; then
  touch "$ACTIVITY"
  exit 0
fi

[[ -e "$ACTIVITY" ]] || touch "$ACTIVITY"
idle_s=$(( $(date +%s) - $(stat -c %Y "$ACTIVITY") ))
if (( idle_s >= IDLE_LIMIT_S )); then
  logger -t spider-autostop "idle for ${idle_s}s; stopping"
  /sbin/shutdown -h now
fi
