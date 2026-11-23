#!/usr/bin/env bash
# Updates a running robot, run on the Pi from an unpacked copy of spider-robot:
#   bash infra/pi/deploy.sh
# Refuses unless the robot is sitting or relaxed. Keeps the previous release and goes back to it
# by itself if a service does not come up. The gateway restarts before voice and body.
set -euo pipefail
SR="$(cd "$(dirname "$0")/../.." && pwd)"
ROOT=/opt/spider
LINK="$ROOT/spider-robot"
RELEASES="$ROOT/releases"
ROBOT_ID="${ROBOT_ID:-spider-01}"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"
SERVICES=(spider-gateway spider-voice spider-body spider-camera spider-recorder spider-sysmon spider-button)
SECRET="$(sudo cat /etc/spider/secrets/spider-console.mqtt)"

mode() {  # the gateway's retained status, one message, 3 s at most; no answer means unknown
  mosquitto_sub -h 127.0.0.1 -p 1883 -u spider-console -P "$SECRET" -C 1 -W 3 \
    -t "spider/$ROBOT_ID/gw/status" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["mode"] if d["online"] else "offline")'
}

# With spider-body stopped nothing can move, so there is no posture to check.
if systemctl is-active --quiet spider-body; then
  current_mode="$(mode || echo unknown)"
  case "$current_mode" in
    relaxed|sitting) ;;
    *) echo "refusing: the robot is '$current_mode'. Sit it down first."; exit 1 ;;
  esac
fi

# Restart only what the owner turned on. A deploy never starts spider-body, voice or the camera.
RUN=()
for svc in "${SERVICES[@]}"; do
  if systemctl is-active --quiet "$svc" || systemctl is-enabled --quiet "$svc"; then
    RUN+=("$svc")
  fi
done
echo "services to restart: ${RUN[*]:-none}"

sudo install -d -o "$USER" "$RELEASES"
if [[ -d "$LINK" && ! -L "$LINK" ]]; then   # first deploy after setup_pi.sh
  sudo mv "$LINK" "$RELEASES/initial"
  sudo ln -s "$RELEASES/initial" "$LINK"
fi
previous="$(readlink -f "$LINK")"
release="$RELEASES/$(date +%Y%m%d-%H%M%S)"
rsync -a --exclude .venv --exclude __pycache__ --exclude .ruff_cache --exclude docs \
  --exclude infra/local/local-certs "$SR/" "$release/"
export UV_LINK_MODE=copy UV_PYTHON_INSTALL_DIR=/opt/spider/python
for pkg in body gateway; do
  (cd "$release/$pkg" && uv sync --frozen --no-dev --extra gpio --python "$PYTHON_VERSION")
done
(cd "$release/voice" && uv sync --frozen --no-dev --extra pi --python "$PYTHON_VERSION")
sudo chown -R spider:spider "$release"

activate() {
  sudo ln -sfn "$1" "$LINK"
  [[ ${#RUN[@]} -gt 0 ]] || return 0
  sudo systemctl restart "${RUN[@]}"
  sleep 8
  for svc in "${RUN[@]}"; do
    systemctl is-active --quiet "$svc" || return 1
  done
}

# Keep the three newest releases, by NAME: they are timestamps, and "initial" (from setup_pi.sh) is
# the oldest. Never the live one or the one to go back to. Directory times are no guide: rsync -a
# copies the laptop folder's time onto every release, so sorting by time once deleted the live
# release (2026-11-19).
prune_releases() {
  local all=() dir drop
  [[ -d "$RELEASES/initial" ]] && all+=("$RELEASES/initial")
  while IFS= read -r dir; do all+=("$dir"); done < <(find "$RELEASES" -mindepth 1 -maxdepth 1 \
    -type d -name '[0-9]*' | sort)
  drop=$(( ${#all[@]} - 3 ))
  (( drop > 0 )) || return 0
  for dir in "${all[@]:0:drop}"; do
    [[ "$dir" == "$release" || "$dir" == "$previous" ]] || sudo rm -rf "$dir"
  done
}

if activate "$release"; then
  echo "deployed $release (previous: $previous)"
  prune_releases
elif [[ -d "$previous" ]]; then
  echo "a service failed; going back to $previous"
  activate "$previous"
  exit 1
else
  echo "a service failed, and the previous release $previous is gone: staying on $release"
  exit 1
fi
