#!/usr/bin/env bash
# Creates one broker login per process on the Pi. Safe to run again: existing secrets are kept.
# Each secret is readable by the spider user and written to the broker's password file hashed.
set -euo pipefail
ROBOT_ID="${ROBOT_ID:-spider-01}"
DIR=/etc/spider/secrets
PW=/etc/mosquitto/spider/passwords
sudo install -d -m 750 -o spider -g spider "$DIR"
sudo install -d -m 750 -o root -g mosquitto /etc/mosquitto/spider
sudo touch "$PW"
for user in "$ROBOT_ID" spider-gateway spider-voice spider-camera spider-recorder spider-sysmon \
            spider-console spider-button; do
  file="$DIR/$user.mqtt"
  if ! sudo test -s "$file"; then
    openssl rand -hex 24 | sudo tee "$file" >/dev/null
    sudo chown spider:spider "$file"
    sudo chmod 400 "$file"
  fi
  sudo mosquitto_passwd -b "$PW" "$user" "$(sudo cat "$file")"
done
sudo chown mosquitto:mosquitto "$PW"  # mosquitto 2.0.16+ warns otherwise, later versions refuse
sudo chmod 640 "$PW"
