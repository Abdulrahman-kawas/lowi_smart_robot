# 4. Budgets

The Pi numbers are estimates until bench B1, B-V2 and B-S2 replace them. Measured inputs are from an Apple M2 (Python 3.13.9) and are [V] there; the Pi figures multiply them by 6-10x, which is an **assumption [A]** with no fetched benchmark behind it. B1 replaces it.

## 4.1 Measured on the M2 [V]

| Operation | Result |
|---|---|
| `Robot.tick` while walking | mean 60 µs, p50 42, p99 199, max 278 |
| `LidarProcessor.process`, 2666 points | p50 107 µs |
| `RobotState` to JSON | p50 6.3 µs |
| `parse_command` | p50 1.2 µs |
| `feed.handle(imu)` | p50 0.9 µs |
| `zmq.asyncio` receive and handle, separate publisher, 500 Hz | 256 µs per message, 9.1% of a core |
| Same at 100 Hz | 343 µs per message, 2.5% of a core |

The surprise is the last two rows: the IMU's cost is the event loop's receive path, not the Python math.

## 4.2 Pi, Core 0 [E]

| Consumer | Work | Load |
|---|---|---|
| Control tick | 50 Hz at 0.4-0.6 ms | 2-3% |
| IMU messages after decimation | 50 Hz at 2-3.4 ms | 10-17% |
| Cloud messages | 12 Hz at 2-3.4 ms, plus 0.6-1.1 ms processing | 3-5% |
| Commands, state, MQTT thread | About 10 messages/s | 2-3% |
| SSC serial write | 25 Hz | under 1% |
| `lidar_bridge` | 64,000 points/s parsed in C++ | 8-15% [A] |
| Residual IRQs after `irqaffinity=1-3` | | up to 3% |
| **Total** | | **28-47%**, ceiling 60% (N29) |

Without decimation, IMU alone would be 77-128% of the core [E]. L2 cloud rate of 12 Hz is derived [V]: 216 vertical scans/s (manual) divided by `cloud_scan_num` 18 (`lidar_bridge.cpp:71`).

## 4.3 Pi, Cores 1-3 (300% available) [E]

| Consumer | Idle | Burst | Duration |
|---|---|---|---|
| Mosquitto, gateway, health | 2-4% | 5% | - |
| Voice (VAD at 50 frames/s) | 3-6% | 10% | - |
| Tailscale | 1-3% | 20% during camera or audio transfer | short |
| Whisper local | 0 | 300% | 3-8 s, offline only |
| Router | 0 | 300% | 1-3 s, sequential with STT |
| Piper | 0 | 100% | 0.3-1 s |
| Camera capture and JPEG | 0 | 30% | 0.2 s |

One utterance is processed at a time, so STT and the router never overlap. Sustained load is bounded by how much people talk, but background speech does consume STT time, which is the reason B-V4 exists.

## 4.4 Pi RAM (4 GB) [E]

| Process | RSS | `MemoryMax` |
|---|---|---|
| OS, systemd, journald (in RAM) | 220 MB | - |
| tailscaled | 50 MB | - |
| Mosquitto | 8 MB | 64 MB |
| `lidar_bridge` | 30 MB | 100 MB |
| `spider-body` (numpy, cv2) | 150-250 MB | 400 MB |
| `spider-gateway` | 40-60 MB | 150 MB |
| `spider-health` | 30 MB | 80 MB |
| `spider-voice` (ctranslate2, onnxruntime, tiny, Piper low) | 300-500 MB | 900 MB |
| Ollama + LFM2.5-350M Q4_K_M (229 MB file) | 350-550 MB | 1 GB |
| `spider-record` when used | 50 MB | 200 MB |
| **Total** | **1.3-1.8 GB** (ceiling 2.2 GB, N30) | |

OOM order, by `OOMScoreAdjust`: Ollama (+500), recorder (+300), voice (+200), then gateway, broker, bridge, body (-700 to -900). Under memory pressure the voice stack dies before anything that can stop the robot.

## 4.5 Server

Free in daily use: about 5.7 GB [V, brief]. The ARCHITECTURE target of 8 GB free is not required by this budget but gives headroom.

| Service | CPU | RAM [E] | `MemoryMax` |
|---|---|---|---|
| `spider-brain` plus Whisper `small` | 6 threads for 1-2 s per utterance | 0.5 + 0.6 GB | 2 GB |
| `llama-vision` (Q4_0 plus projector) | 6 threads, Nice 10 | 1.5 GB | 3 GB |
| `llama-planner` (Q4_K_M) | 6 threads, Nice 10 | 1.0 GB | 2.5 GB |
| **Total** | | **3.6 GB** (ceiling 5.0 GB, N32) | |

If the three peak together, 18 threads compete for 12. `AskService` and `SttWorker` are single-flight, and vision and planner run at Nice 10, so voice and the desktop keep priority. SLAM must not run together with vision: `process_job.sh` gets 4 CPUs and 4 GB through Docker limits, and the owner runs it on request.

With an RTX 3060 12 GB, change `SB_STT_DEVICE=cuda` and add `-ngl 99` to both llama units. Then Whisper `medium` and faster vision become possible. No code changes.

## 4.6 Bandwidth

| Flow | Size | Rate | Average |
|---|---|---|---|
| `state` | about 1 KB | 4 Hz | 4 KB/s |
| Heartbeats, two sources | about 150 B | 2 Hz each | under 1 KB/s |
| Gateway status | about 600 B | 1 Hz | under 1 KB/s |
| STT audio, base64 | 43 KB per second of speech | per utterance | bursts |
| Camera frame | up to 120 KB | on request | bursts |
| LiDAR raw, recording only | 64,000 x 24 B | - | 1.5 MB/s on disk, 5.5 GB/h. It stays on the Pi until copied |

Normal Tailscale traffic stays under 10 KB/s, so a relayed link has room for it.

## 4.7 Latency budgets

All in ms. The sum is the path target.

**Speech onset to Stop (N8) and to zero velocity**

| Stage | Budget |
|---|---|
| Speech detected: `start_ms` 100 plus one frame 20 | 120 |
| Publish, broker, gateway, broker, body | 10 |
| Next control tick | 20 |
| **To Stop handled** | **150** |
| Ramp at 0.25 m/s², from 0.08 m/s | 320 |
| **To zero velocity** | **470** |

**Grammar command, online (target p95 2500)**

| Stage | Budget |
|---|---|
| VAD close | 300 |
| MQTT to worker and back | 50 |
| Server STT | 2000 |
| Grammar | 5 |
| Gateway to body | 30 |
| Margin | 115 |
| **Total** | **2500** |

**Router command, online (target p95 3600, to first act)**

| Stage | Budget |
|---|---|
| VAD close | 300 |
| MQTT and server STT | 2050 |
| Router to first act | 1200 |
| Gateway to body | 30 |
| Margin | 20 |
| **Total** | **3600** |

**Offline grammar (target p95 8500)**: VAD 300, local STT 8000, grammar 5, gateway to body 30, margin 165.

**Vision answer**: filler at under 100 ms; total under 30 s (N23), measured in B-S1.
