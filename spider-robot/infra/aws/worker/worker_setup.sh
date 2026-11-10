#!/usr/bin/env bash
# Run once on the instance (Ubuntu 22.04 or 24.04), then stop it. Join the tailnet by hand first.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
sudo apt-get update
sudo apt-get install -y docker.io rsync python3-venv
sudo usermod -aG docker "$USER"
sudo mkdir -p /opt/spider /data
sudo chown "$USER" /opt/spider /data
sudo install -m 755 "$HERE/spider-autostop.sh" /usr/local/sbin/spider-autostop.sh
sudo install -m 755 "$HERE/run_job.sh" /opt/spider/run_job.sh
sudo cp "$HERE/spider-autostop.service" "$HERE/spider-autostop.timer" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now spider-autostop.timer
sudo docker build -t spider-slam:noetic -f "$HERE/Dockerfile.slam" "$HERE"
echo "On your laptop: aws ec2 modify-instance-attribute --instance-id ID \\"
echo "  --instance-initiated-shutdown-behavior '{\"Value\":\"stop\"}'"
