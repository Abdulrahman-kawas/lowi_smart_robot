#!/usr/bin/env bash
# Home server (Ubuntu 24.04, no GPU). Run as the normal user: bash infra/server/setup_server.sh
set -euo pipefail
SR="$(cd "$(dirname "$0")/../.." && pwd)"
LLAMA_TAG="${LLAMA_TAG:-v0.9.0}"
UV_VERSION="${UV_VERSION:-0.12.17}"

sudo apt-get update
sudo apt-get install -y build-essential cmake git curl libcurl4-openssl-dev pkg-config chrony ffmpeg rsync

if ! command -v uv >/dev/null || [[ "$(uv --version | cut -d' ' -f2)" != "$UV_VERSION" ]]; then
  curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" | sudo env UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh
fi

if [[ ! -x /usr/local/bin/llama-server ]]; then
  git clone --depth 1 --branch "$LLAMA_TAG" https://github.com/ggml-org/llama.cpp "$HOME/llama.cpp"
  cmake -S "$HOME/llama.cpp" -B "$HOME/llama.cpp/build" -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=ON
  cmake --build "$HOME/llama.cpp/build" -j"$(nproc)" --target llama-server
  sudo install -m 755 "$HOME/llama.cpp/build/bin/llama-server" /usr/local/bin/llama-server
fi

sudo mkdir -p /var/lib/liquid /var/lib/spider-brain/recordings /etc/spider-brain/certs
sudo chown -R "$USER" /var/lib/liquid /var/lib/spider-brain /etc/spider-brain
chmod 700 /etc/spider-brain/certs
(cd "$SR/brain" && uv sync --frozen --no-dev --extra voice --extra slam --group stt --group aws)
[[ -f /etc/spider-brain/brain.env ]] || cp "$SR/infra/server/brain.env.example" /etc/spider-brain/brain.env
[[ -f /etc/spider-brain/secrets.env ]] || install -m 600 /dev/null /etc/spider-brain/secrets.env
chmod 600 /etc/spider-brain/brain.env
for unit in llama-vision llama-planner spider-brain; do
  sed -e "s#__USER__#$USER#g" -e "s#__SR__#$SR#g" "$SR/infra/server/$unit.service" \
    | sudo tee "/etc/systemd/system/$unit.service" >/dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable --now llama-vision llama-planner
echo "Next: certificates into /etc/spider-brain/certs, secrets into secrets.env, then:"
echo "  sudo systemctl enable --now spider-brain"
