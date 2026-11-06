#!/usr/bin/env bash
# Raspberry Pi 4 (4 GB) setup. OS: Raspberry Pi OS Lite 64-bit (Trixie or Bookworm), SSH + Wi-Fi enabled
# in Raspberry Pi Imager. The same steps work on a Pi 5 or any arm64/x86_64 Debian/Ubuntu board.
# Copy the spider-robot folder to the Pi (rsync, see the plan), then:
#   bash ~/spider-robot/infra/pi/setup_pi.sh
set -euo pipefail
SR="$(cd "$(dirname "$0")/../.." && pwd)"   # the spider-robot folder (no git needed)
LIDAR_HOST_IP="${LIDAR_HOST_IP:-192.168.1.2/24}"   # the L2 sends to 192.168.1.2 by default

sudo apt-get update
sudo apt-get install -y git cmake build-essential pkg-config libzmq3-dev i2c-tools chrony mosquitto
sudo systemctl disable --now mosquitto   # only started by hand for bench tests (port 1884)

# The SSC-32U servo controller is a USB serial device (group "dialout", set above).
# I2C is only needed for the PCA9685 alternative; enabling it is harmless.
# I2C at 400 kHz for the two PCA9685 boards
if command -v raspi-config >/dev/null; then
  sudo raspi-config nonint do_i2c 0
  CFG=/boot/firmware/config.txt
  grep -q "i2c_arm_baudrate" "$CFG" || echo "dtparam=i2c_arm=on,i2c_arm_baudrate=400000" | sudo tee -a "$CFG"
fi

# Service user and folders
id spider >/dev/null 2>&1 || sudo useradd --system --create-home --home-dir /opt/spider \
  --groups dialout,i2c,video spider
sudo mkdir -p /etc/spider/certs /opt/spider/bin
sudo chown -R spider:spider /etc/spider
sudo chmod 750 /etc/spider/certs

# Ethernet port = LiDAR only (static IP, never the default route; internet stays on Wi-Fi).
# If your Wi-Fi LAN is also 192.168.1.x, change the LiDAR network first (see the plan, step P3).
if command -v nmcli >/dev/null && ! nmcli -t -f NAME con show | grep -qx lidar; then
  sudo nmcli con add type ethernet ifname eth0 con-name lidar ipv4.method manual \
    ipv4.addresses "$LIDAR_HOST_IP" ipv4.never-default yes ipv6.method disabled
  sudo nmcli con up lidar || true
fi

# Unitree SDK + lidar_bridge
if [[ ! -d /opt/spider/unilidar_sdk2 ]]; then
  sudo git clone --depth 1 https://github.com/unitreerobotics/unilidar_sdk2 /opt/spider/unilidar_sdk2
fi
cmake -S "$SR/body/lidar_bridge" -B /tmp/lidar_bridge_build \
  -DUNILIDAR_SDK_DIR=/opt/spider/unilidar_sdk2/unitree_lidar_sdk
cmake --build /tmp/lidar_bridge_build -j4
sudo install -m 755 /tmp/lidar_bridge_build/lidar_bridge /opt/spider/bin/lidar_bridge

# Python body. uv goes to /usr/local/bin so the "spider" service user can run it too.
if ! command -v uv >/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | sudo env UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh
fi
export UV_LINK_MODE=copy   # no hardlinks into the installing user's cache (chown below)
sudo rm -rf /opt/spider/spider-robot
sudo cp -r "$SR" /opt/spider/spider-robot
sudo chown -R "$USER" /opt/spider/spider-robot
# system Python (3.11+ on Bookworm) so the "spider" service user can run the venv
(cd /opt/spider/spider-robot/body && uv sync --no-dev --python /usr/bin/python3)
sudo chown -R spider:spider /opt/spider/spider-robot

# Config + services
[[ -f /etc/spider/robot.yaml ]] || sudo -u spider cp "$SR/body/config/robot.example.yaml" /etc/spider/robot.yaml
sudo cp "$SR/body/systemd/spider-lidar.service" "$SR/body/systemd/spider-body.service" /etc/systemd/system/
sudo systemctl daemon-reload
echo "Installed. Next: set ssc.port in /etc/spider/robot.yaml (ls /dev/serial/by-id/),"
echo "certificates into /etc/spider/certs,"
echo "calibrate the servos, then: sudo systemctl enable --now spider-lidar spider-body"
echo "Reboot once so the I2C speed change takes effect."
