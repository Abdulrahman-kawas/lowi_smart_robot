#!/usr/bin/env bash
# Brain host setup on EC2, Ubuntu 24.04 (x86_64 or Graviton arm64). Also works on a local
# Ubuntu PC for phase 2. Run as the "ubuntu" user (SSM: `sudo -iu ubuntu` first):
#   bash ~/spider-robot/infra/ec2/setup_ec2.sh            # CPU build
#   GPU=1 bash ~/spider-robot/infra/ec2/setup_ec2.sh      # NVIDIA instance (CUDA toolkit)
# Local PC without SSM: FETCH_CERTS_FROM_SSM=0 bash ~/spider-robot/infra/ec2/setup_ec2.sh
set -euo pipefail
SR="$(cd "$(dirname "$0")/../.." && pwd)"   # the spider-robot folder (no git needed)

sudo apt-get update
sudo apt-get install -y build-essential cmake git curl libcurl4-openssl-dev pkg-config chrony
command -v aws >/dev/null || sudo snap install aws-cli --classic   # run-brain.sh reads SSM

# uv (Python package manager used by every spider-robot package), system-wide
if ! command -v uv >/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | sudo env UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh
fi

# llama.cpp -> llama-server (serves the Liquid AI models with an OpenAI-compatible API)
if [[ ! -x /usr/local/bin/llama-server ]]; then
  git clone --depth 1 https://github.com/ggml-org/llama.cpp "$HOME/llama.cpp"
  EXTRA=()
  [[ "${GPU:-0}" == "1" ]] && EXTRA+=(-DGGML_CUDA=ON)
  cmake -S "$HOME/llama.cpp" -B "$HOME/llama.cpp/build" -DCMAKE_BUILD_TYPE=Release \
        -DLLAMA_CURL=ON "${EXTRA[@]}"
  cmake --build "$HOME/llama.cpp/build" -j"$(nproc)" --target llama-server
  sudo install -m 755 "$HOME/llama.cpp/build/bin/llama-server" /usr/local/bin/llama-server
fi

# Model cache + services (models download from Hugging Face on first start)
sudo mkdir -p /var/lib/liquid
sudo chown "$USER" /var/lib/liquid
for unit in liquid-planner liquid-vision; do
  sed "s/__USER__/$USER/g" "$SR/infra/ec2/$unit.service" | sudo tee "/etc/systemd/system/$unit.service" >/dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable --now liquid-vision liquid-planner

# Brain
(cd "$SR/brain" && uv sync)
sudo mkdir -p /etc/spider-brain/certs
sudo chown -R "$USER" /etc/spider-brain
chmod 700 /etc/spider-brain/certs

# Phase 1 (EC2): the brain certificate comes from SSM Parameter Store (no SSH, no copying).
# On the laptop, once:  aws ssm put-parameter --type SecureString --name /spider/brain/cert \
#   --value file://certs/spider-brain.cert.pem   (same for /spider/brain/key)
if [[ "${FETCH_CERTS_FROM_SSM:-1}" == "1" ]] && command -v aws >/dev/null; then
  for item in cert:spider-brain.cert.pem key:spider-brain.private.key; do
    aws ssm get-parameter --name "/spider/brain/${item%%:*}" --with-decryption \
      --query Parameter.Value --output text > "/etc/spider-brain/certs/${item##*:}" \
      || echo "WARN: /spider/brain/${item%%:*} not found in SSM"
  done
  chmod 600 /etc/spider-brain/certs/*.key 2>/dev/null || true
  curl -fsSL -o /etc/spider-brain/certs/AmazonRootCA1.pem https://www.amazontrust.com/repository/AmazonRootCA1.pem
fi
[[ -f /etc/spider-brain/brain.env ]] || cp "$SR/brain/.env.example" /etc/spider-brain/brain.env
chmod 600 /etc/spider-brain/brain.env
echo "Next: edit /etc/spider-brain/brain.env (IoT endpoint), then: $SR/infra/ec2/run-brain.sh status"
