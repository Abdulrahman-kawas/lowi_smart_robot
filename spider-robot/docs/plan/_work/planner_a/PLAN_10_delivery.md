# 10. Delivery

## 10.1 CI

`.github/workflows/spider-robot.yml`. Per package: `uv sync --all-extras --frozen`, `ruff check`,
`pytest`. Also: `bash -n` on all shell scripts, JSON validity of IAM policies, a scan for key patterns,
and a real build of `lidar_bridge` against the actual Unitree SDK. That build is the check I could not
run locally. CI has not been run; the workflow itself is unverified.

## 10.2 Reproducible installs

| Item | Pin | Source of the version |
|---|---|---|
| Python packages | `uv.lock` in each package, `--frozen` everywhere | Generated here |
| uv | 0.12.17 | As used here |
| `faster-whisper` | 1.2.1 | PyPI, 2026-11-09 |
| `ctranslate2` | 4.8.5 | PyPI, 2026-11-09 |
| `piper-tts` | 1.8.0 | PyPI, 2026-11-09 |
| `webrtcvad-wheels` | 2.0.14.post1 | PyPI, 2026-11-09 |
| Ollama | v0.40.15 | GitHub API, 2026-11-09 |
| llama.cpp | tag v0.9.0 | GitHub API, 2026-11-09 |
| LFM2.5-350M | `hf.co/LiquidAI/LFM2.5-350M-GGUF:Q4_K_M` | Hugging Face |
| LFM2.5-VL-1.6B | `LiquidAI/LFM2.5-VL-1.6B-GGUF:Q4_0` | Hugging Face |
| Piper voice | `ar_JO-kareem-low`, `rhasspy/piper-voices` tag v1.0.0 | Hugging Face |

Known gap: an `hf.co/...:TAG` reference names a quantisation, not an immutable revision. After the
first working download, keep the model files as a local backup.

Disk: the Ollama ARM64 archive is 1.6 GB **[V]** via the GitHub API. Plan for a 32 GB card or larger.

## 10.3 systemd

| Unit | CPU | Priority | MemoryMax | Restart |
|---|---|---|---|---|
| `spider-tune` (one-shot) | | | | Boot |
| `spider-lidar` | 0 | Nice −10 | 64M | Always, 2 s |
| `spider-body` | 0 | FIFO 50 on one thread; watchdog 1 s | 400M | Always, 3 s |
| `spider-gateway` | 1-3 | Nice −5 | 128M | Always, 1 s |
| `mosquitto` | 1-3 by default | | system | Distro default |
| `spider-voice` | 1-3 | Nice 0 | 900M | Always, 2 s |
| `ollama` | 1-3 | Nice 5 | 900M | Distro default |
| `spider-camera` | 1-3 | Nice 5 | 256M | Always, 2 s |
| `spider-recorder` | 1-3 | Nice 10, idle I/O | 200M | Always, 5 s |
| `spider-sysmon` | 1-3 | Nice 10 | 96M | Always, 5 s |

`/etc/systemd/system.conf.d/10-spider-cpu.conf` makes cores 1-3 the default for every service, so
something forgotten cannot land on Core 0.

## 10.4 Configuration and secrets

| File | Holds | Mode |
|---|---|---|
| `/etc/spider/robot.yaml` | Body config | 644 |
| `/etc/spider/calibration.yaml` | Servo trims | 644 |
| `/etc/spider/voice.yaml` | Engine choices, and tokens when used | 640 |
| `/etc/spider/gateway.env` | Broker, certificates | 640 |
| `/etc/spider/certs/` | Keys | 750 directory, 600 keys |
| `/etc/spider-brain/brain.env` | API keys, Telegram token | 600 |
| `/etc/spider-brain/llama.env`, `stt.env` | `LLAMA_API_KEY`, `SPIDER_STT_TOKEN` | 600 |

The repository holds only `*.example` files with `REPLACE_WITH_...` placeholders.

## 10.5 Safe updates of a running robot

`infra/pi/spider-update.sh`:

1. Refuses if the robot is standing or walking.
2. Builds the new release in `/opt/spider/releases/<timestamp>`, next to the old one.
3. Installs dependencies with `--frozen`.
4. Switches one symlink atomically.
5. Restarts services and checks they stay up for 15 s.
6. On failure, switches the symlink back and restarts.
7. Keeps the last three releases.

**Order: Pi first, then server** (`PLAN_03_contracts.md` 3.6).

Protocol-changing updates: stop the brain, update the Pi, verify with `spider-robotctl status`, then
update the server.

## 10.6 Rollback

- Pi: `sudo ln -sfn /opt/spider/releases/<old> /opt/spider/spider-robot && sudo systemctl restart
  'spider-*'`.
- Server: `git checkout <old tag>`, `uv sync --frozen`, restart.
- Calibration and config sit outside releases, so they are not affected.

## 10.7 Runbooks

### The robot will not walk

1. `spider-robotctl status`. Read `mode`, `limiter`, and `estop`.
2. `limiter=imu_stale` or `stand` refused with "tilt unknown": the IMU is off. Run the work-mode
   provisioning step, then power-cycle the L2.
3. `limiter=lidar_stale`: `systemctl status spider-lidar`; check the Ethernet link. Below 30 °C the L2
   warms up first and sends nothing **[S]**.
4. `estop=True`: see below.

### E-stop

- Software E-stop: Telegram `/release`, look at the photo, press Confirm. Over SSH: `spider-robotctl
  release`.
- If the process restarted while latched, a release leaves the robot **relaxed**. Place it on its
  belly before standing.
- After the physical E-stop: fix the cause, twist to release, then restart the body service.

### Telegram account compromised

1. Log out other sessions in Telegram. Enable two-step verification.
2. BotFather: revoke the token. Update `/etc/spider-brain/brain.env`.
3. Press the physical E-stop if the robot is at risk. Restart `spider-brain`.

### AWS worker left running

1. `aws ec2 describe-instances --instance-ids <id>`.
2. `aws ec2 stop-instances --instance-ids <id>`.
3. Find out why `spider-autostop` did not fire: `journalctl -t spider-autostop` on the instance.

### Undervoltage or throttling alert

Check `spider-robotctl status`, and then `vcgencmd get_throttled`. Sit the robot down. Fix the supply or
the cooling before continuing.

### SD card failure

Flash a new card, run `setup_pi.sh`, then restore `/etc/spider/` (including `calibration.yaml`) from
the owner's backup. **Back up `/etc/spider/` after calibration.** The E-stop latch is in
`/var/lib/spider`, so a new card starts un-latched: check the robot before powering servos.

### Certificates

Check expiry quarterly with `openssl x509 -checkend 5184000 -noout -in <file>`, then follow
`PLAN_07_security.md` 7.3.
