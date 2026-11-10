#!/usr/bin/env bash
# Raspberry Pi 4 (4 GB) setup. OS: Raspberry Pi OS Lite 64-bit, SSH and Wi-Fi enabled in the Imager.
# Copy the spider-robot folder to the Pi, then: bash ~/spider-robot/infra/pi/setup_pi.sh
# Installs everything and starts nothing that moves. The owner enables spider-body by hand.
set -euo pipefail
SR="$(cd "$(dirname "$0")/../.." && pwd)"   # the spider-robot folder (no git needed)
LIDAR_HOST_IP="${LIDAR_HOST_IP:-192.168.1.2/24}"   # the L2 sends to 192.168.1.2 by default
ROBOT_ID="${ROBOT_ID:-spider-01}"
UNILIDAR_REF="${UNILIDAR_REF:-0e3c51f512e6b8ff60b8c32f160b412cb48445c2}"
UV_VERSION="${UV_VERSION:-0.12.17}"
OLLAMA_VERSION="${OLLAMA_VERSION:-0.40.15}"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"
ROUTER_MODEL="hf.co/LiquidAI/LFM2.5-350M-GGUF:Q4_K_M"
VOICE_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/ar/ar_JO/kareem/low"

sudo apt-get update
sudo apt-get install -y git cmake build-essential pkg-config libzmq3-dev i2c-tools chrony \
  mosquitto mosquitto-clients espeak-ng alsa-utils nftables fake-hwclock rsync stress-ng rt-tests \
  gpiod

if command -v raspi-config >/dev/null; then
  sudo raspi-config nonint do_i2c 0
  CFG=/boot/firmware/config.txt
  grep -q "i2c_arm_baudrate" "$CFG" || echo "dtparam=i2c_arm=on,i2c_arm_baudrate=400000" | sudo tee -a "$CFG"
  # Peripheral interrupts land on Core 0 by default. Move them to the other cores.
  CMD=/boot/firmware/cmdline.txt
  grep -q "irqaffinity=" "$CMD" || sudo sed -i '1s/$/ irqaffinity=1-3/' "$CMD"
fi

# Service user and folders
id spider >/dev/null 2>&1 || sudo useradd --system --create-home --home-dir /opt/spider spider
sudo usermod -aG dialout,i2c,video,audio,gpio spider
sudo mkdir -p /etc/spider /opt/spider/bin /opt/spider/models/hf /var/lib/spider/rec
sudo chown -R spider:spider /etc/spider /var/lib/spider

# Ethernet port = LiDAR only (static IP, never the default route; internet stays on Wi-Fi).
if command -v nmcli >/dev/null && ! nmcli -t -f NAME con show | grep -qx lidar; then
  sudo nmcli con add type ethernet ifname eth0 con-name lidar ipv4.method manual \
    ipv4.addresses "$LIDAR_HOST_IP" ipv4.never-default yes ipv6.method disabled
  sudo nmcli con up lidar || true
fi

# Unitree SDK + lidar_bridge
if [[ ! -d /opt/spider/unilidar_sdk2 ]]; then
  sudo git clone https://github.com/unitreerobotics/unilidar_sdk2 /opt/spider/unilidar_sdk2
fi
sudo git -c safe.directory=/opt/spider/unilidar_sdk2 -C /opt/spider/unilidar_sdk2 checkout -q "$UNILIDAR_REF"
cmake -S "$SR/body/lidar_bridge" -B /tmp/lidar_bridge_build \
  -DUNILIDAR_SDK_DIR=/opt/spider/unilidar_sdk2/unitree_lidar_sdk
cmake --build /tmp/lidar_bridge_build -j3
sudo install -m 755 /tmp/lidar_bridge_build/lidar_bridge /opt/spider/bin/lidar_bridge

# uv, then one pinned Python that the service user can read, then the packages.
if ! command -v uv >/dev/null || [[ "$(uv --version | cut -d' ' -f2)" != "$UV_VERSION" ]]; then
  curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" | sudo env UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh
fi
export UV_LINK_MODE=copy UV_PYTHON_INSTALL_DIR=/opt/spider/python
sudo install -d -o "$USER" /opt/spider/python
uv python install "$PYTHON_VERSION"
sudo rm -rf /opt/spider/spider-robot
sudo cp -r "$SR" /opt/spider/spider-robot
sudo chown -R "$USER" /opt/spider/spider-robot
for pkg in body gateway; do
  (cd "/opt/spider/spider-robot/$pkg" && uv sync --frozen --no-dev --extra gpio --python "$PYTHON_VERSION")
done
(cd /opt/spider/spider-robot/voice && uv sync --frozen --no-dev --extra pi --python "$PYTHON_VERSION")
sudo chown -R "$USER" /opt/spider/models
curl -fsSL -o /opt/spider/models/ar_JO-kareem-low.onnx "$VOICE_BASE/ar_JO-kareem-low.onnx"
curl -fsSL -o /opt/spider/models/ar_JO-kareem-low.onnx.json "$VOICE_BASE/ar_JO-kareem-low.onnx.json"
HF_HOME=/opt/spider/models/hf /opt/spider/spider-robot/voice/.venv/bin/python - <<'PY'
from faster_whisper import WhisperModel
WhisperModel("tiny", device="cpu", compute_type="int8")
PY
sudo chown -R spider:spider /opt/spider/spider-robot /opt/spider/models /opt/spider/python

# Ollama, pinned, loopback only. The installer writes its own unit, so ours goes in afterwards.
curl -fsSL https://ollama.com/install.sh | sudo env OLLAMA_VERSION="$OLLAMA_VERSION" sh
sudo install -m 644 "$SR/infra/pi/ollama.service" /etc/systemd/system/ollama.service
sudo systemctl daemon-reload
sudo systemctl restart ollama
sleep 3
ollama pull "$ROUTER_MODEL"

# Broker: loopback passwords only for now. The Tailscale listener is added once certificates exist.
sudo install -d /etc/mosquitto/spider
sudo install -m 644 "$SR/infra/local/acl" /etc/mosquitto/spider/acl
sudo install -m 644 "$SR/infra/local/mosquitto.conf" /etc/mosquitto/conf.d/spider.conf
sudo install -m 644 "$SR/infra/pi/mosquitto.service" /etc/systemd/system/mosquitto.service
ROBOT_ID="$ROBOT_ID" bash "$SR/infra/pi/mqtt_passwords.sh"

# Isolation, logging, network
sudo install -D -m 644 "$SR/infra/pi/files/spider-cpus.conf" /etc/systemd/system.conf.d/10-spider-cpus.conf
sudo install -D -m 644 "$SR/infra/pi/files/journald-spider.conf" /etc/systemd/journald.conf.d/10-spider.conf
sudo install -D -m 644 "$SR/infra/pi/files/wifi-powersave.conf" /etc/NetworkManager/conf.d/10-spider-wifi.conf
sudo install -D -m 644 "$SR/infra/pi/files/nftables-spider.conf" /etc/nftables.d/spider.conf
grep -q 'nftables.d/spider.conf' /etc/nftables.conf || echo 'include "/etc/nftables.d/spider.conf"' | sudo tee -a /etc/nftables.conf
sudo install -m 755 "$SR/infra/pi/spider-tune.sh" /usr/local/sbin/spider-tune.sh
sudo install -m 644 "$SR/infra/pi/spider-tune.service" /etc/systemd/system/spider-tune.service
sudo systemctl disable --now dphys-swapfile 2>/dev/null || true
sudo swapoff -a || true
sudo systemctl enable --now nftables

# Config and services. Nothing that can move the robot is enabled here.
# As root with -o: the spider user may not be able to read this user's home directory.
[[ -f /etc/spider/robot.yaml ]] || sudo install -o spider -g spider -m 640 "$SR/body/config/robot.example.yaml" /etc/spider/robot.yaml
[[ -f /etc/spider/voice.yaml ]] || sudo install -o spider -g spider -m 640 "$SR/voice/config/voice.example.yaml" /etc/spider/voice.yaml
[[ -f /etc/spider/gateway.env ]] || sudo install -o spider -g spider -m 640 "$SR/gateway/config/gateway.env.example" /etc/spider/gateway.env
sudo install -m 755 "$SR/infra/pi/spider-robotctl" /usr/local/bin/spider-robotctl
for unit in body/systemd/spider-lidar body/systemd/spider-body body/systemd/spider-camera \
            body/systemd/spider-recorder body/systemd/spider-sysmon \
            gateway/systemd/spider-gateway gateway/systemd/spider-button voice/systemd/spider-voice; do
  sudo cp "$SR/$unit.service" /etc/systemd/system/
done
sudo systemctl daemon-reload
sudo systemctl enable mosquitto ollama spider-tune spider-lidar spider-gateway spider-sysmon
sudo systemctl restart mosquitto
echo "Installed. Reboot once so the IRQ and CPU settings take effect."
echo "Next: set ssc.port in /etc/spider/robot.yaml, provision the L2 IMU, calibrate, then follow the first-motion HUMAN STEP."
