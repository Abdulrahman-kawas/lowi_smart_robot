# 10. Delivery and runbooks

Nothing in this section has run on the Pi or the server. Shell scripts passed `bash -n` only [V].

## 10.1 Reproducible installs

| Item | Pin |
|---|---|
| Python packages | `uv.lock` per package, installed with `uv sync --frozen`. Pi-only and server-only extras are dependency groups with exact versions |
| uv | 0.12.17 |
| Python on the Pi | 3.12, uv-managed in `/opt/spider/python`, readable by the service user. aarch64 wheels exist for `ctranslate2` 4.8.5, `onnxruntime` 1.31.1, `piper-tts` 1.8.0, `webrtcvad-wheels` 2.0.14.post1 [V, PyPI 2026-11-09]. PyAudio builds from source with `portaudio19-dev` |
| Ollama | 0.32.6: the newest I found, dated Aug 2026. **Whether it runs LFM2.5-350M is unverified**; B-V2 confirms, and the version can be raised |
| Router model | `hf.co/LiquidAI/LFM2.5-350M-GGUF:Q4_K_M`, file checked to exist [V] |
| Piper voice | `piper-voices` tag v1.0.0, `ar_JO-kareem-low`, URLs checked [V] |
| llama.cpp | tag b12226 |
| Unitree SDK | commit `0e3c51f5` |
| Point-LIO | commit `18ed5976` |
| rosbags | 0.11.9 |

## 10.2 systemd units and limits

| Unit | Node | CPU | Memory | OOM adj | Restart |
|---|---|---|---|---|---|
| `spider-lidar` | Pi | 0 | 100 MB | -800 | 2 s |
| `spider-body` | Pi | 0, Nice -5, watchdog 1 s | 400 MB | -900 | 3 s |
| `mosquitto` | Pi | 1-3, Nice -5 | 64 MB | -800 | 1 s |
| `spider-gateway` | Pi | 1-3, Nice -5 | 150 MB | -700 | 1 s |
| `spider-voice` | Pi | 1-3 | 700 high, 900 max | +200 | 2 s |
| `ollama` | Pi | 1-3 | 800 high, 1 GB max | +500 | default |
| `spider-record` | Pi | 1-3, Nice 10, idle IO | 200 MB | +300 | 3 s |
| `spider-health` | Pi, server | Nice 10 | 80 MB | - | 5-10 s |
| `spider-brain` | server | - | 1.8 high, 2 GB max | -200 | 5 s |
| `llama-vision` | server | Nice 10 | 2.5 high, 3 GB max | +300 | 5 s |
| `llama-planner` | server | Nice 10 | 2 high, 2.5 GB max | +300 | 5 s |

System-wide on the Pi: default `CPUAffinity=1 2 3`, `irqaffinity=1-3`, journald in RAM, Wi-Fi power save off, nftables rules for 1883, 8883, 11434.

## 10.3 Config and secrets

| Item | Location | In git |
|---|---|---|
| Robot | `/etc/spider/robot.yaml`, `calibration.yaml` | Example only |
| Voice | `/etc/spider/voice.yaml` | Example only |
| Gateway | `/etc/spider/gateway.env` | Example only |
| Brain | `/etc/spider-brain/brain.env` | Example only |
| Secrets | `PLAN_07_security.md` §7.3 | Never |

Placeholders are written as `REPLACE_...`. Config is validated at start by pydantic with unknown keys refused.

## 10.4 Updating a running robot

`infra/pi/deploy.sh`:

1. Reads `gw/status`; **refuses unless the robot is `sitting` or `relaxed`**.
2. Builds a new release directory and venvs, while the old one keeps running.
3. Switches a symlink, restarts gateway, voice and body.
4. Waits 8 s and checks every unit is active.
5. On failure, switches back and restarts. Keeps three releases.

Order across machines: **Pi first, then server** (rule R2). The bridge is rebuilt only when its source changes. If `gw/status` cannot be read, the script refuses, including when the gateway is down; run the same steps by hand in that case.

Rollback by hand: `sudo ln -sfn /opt/spider/releases/<old> /opt/spider/spider-robot` and restart the three services.

Server: `git pull`, `uv sync --frozen`, `systemctl restart spider-brain`. A bad brain release cannot move the robot past the gateway's rules.

## 10.5 CI

See §9.5. Pre-merge: every package's tests and ruff.

## 10.6 Runbooks

Each is short by design: symptom, check, action.

**The robot will not move.** `spider-brain status` or `mosquitto_sub -t 'spider/+/gw/status' -C 1`. Check `limiter`: `lidar_stale` means LiDAR (`systemctl status spider-lidar`, cable, `192.168.1.x`); `imu_stale` means the bridge. E-stop latched: use the release flow. Mode `relaxed` or `fallen`: wake by voice or `/stand`. Held off: wait 2 s.

**It keeps stopping while walking.** `pre_stops` in the voice log. If it rises with no one speaking, raise `vad.min_rms_dbfs` or `aggressiveness`, or set `pre_stop.enabled: false` while diagnosing.

**It does not understand.** Look at the traces: `path`, `text`, `stt_provider`. If `text` is wrong, the mic is the problem or STT needs escalation. If `text` is right and `path: ignored`, say the wake word.

**Server is down, need control now.** SSH to the Pi over Tailscale. Voice and reflexes are unaffected.

**E-stop release fails.** Confirm the camera works with `/photo`; no frame means no release, by design. As a last resort, a person at the robot power-cycles it.

**Loop late alerts.** Check `spider-health` for heat, `pidstat -t -p $(pidof python3)`, whether something escaped to Core 0 (`ps -eo pid,psr,comm | awk '$2==0'`). Climb the ladder only after confirming the cause.

**Certificate problem.** §7.4. Local control is unaffected.

**AWS running when it should not.** `aws ec2 stop-instances --instance-ids <id>`. Check the timer: `systemctl list-timers spider-self-stop`.

**Power loss or SD failure.** Re-image, run `setup_pi.sh`, restore `/etc/spider` from the owner's backup.
