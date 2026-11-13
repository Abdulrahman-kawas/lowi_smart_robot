# Spider robot: file map

Every file the plan creates or changes, generated from the merged code, so it cannot disagree with
`04_EXECUTION_PLAN.md`. Total: 135 files, 92 created and
43 changed. "Node" is where the file runs. Code steps all
execute on the Mac; the Pi and server receive the files later, in steps P02 and Q01.

| Path | Action | Purpose | Owner package | Node | Milestone, step |
|---|---|---|---|---|---|
| `.github/workflows/spider-robot.yml` | Create | name: spider-robot | ci | Mac / CI | M0, S02 |
| `spider-robot/README.md` | Change | A six-legged walking robot (18 servos: 6 legs x coxa/femur/tibia) with a Unitree L2 4D LiDAR, | repo | Mac / CI | M0, S02 |
| `spider-robot/body/config/robot.example.yaml` | Change | Spider robot body configuration (Raspberry Pi 4). Copy to robot.yaml and edit. | body | Pi | M1, S04 |
| `spider-robot/body/lidar_bridge/lidar_bridge.cpp` | Change | lidar_bridge: Unitree L2 (unilidar_sdk2, Ethernet/UDP) -> ZeroMQ PUB for the Python body. | body | Pi | M1, S08 |
| `spider-robot/body/pyproject.toml` | Change | Package metadata, dependencies and entry points | body | Pi | M1, S04 |
| `spider-robot/body/src/spider_body/camera_service.py` | Create | spider-camera: camera capture as its own process on cores 1-3. | body | Pi | M1, S07 |
| `spider-robot/body/src/spider_body/config.py` | Change | Body configuration: robot.yaml (+ calibration.yaml for per-servo trims and directions). | body | Pi | M1, S04 |
| `spider-robot/body/src/spider_body/gait.py` | Change | Periodic gait generator for a hexapod. | body | Pi | M1, S05 |
| `spider-robot/body/src/spider_body/hw/camera.py` | Change | Camera snapshots as JPEG bytes small enough for one MQTT message (AWS IoT limit: 128 KB). | body | Pi | M1, S05 |
| `spider-robot/body/src/spider_body/hw/kick.py` | Create | The kick line for the external hardware watchdog. | body | Pi | M1, S05 |
| `spider-robot/body/src/spider_body/hw/lidar.py` | Change | Unitree L2 LiDAR: point clouds arrive from the C++ lidar_bridge over ZeroMQ. | body | Pi | M1, S05 |
| `spider-robot/body/src/spider_body/hw/servos.py` | Change | Servo drivers for the 18 leg servos. | body | Pi | M1, S05 |
| `spider-robot/body/src/spider_body/main.py` | Change | spider-body entry point. | body | Pi | M1, S06 |
| `spider-robot/body/src/spider_body/recorder.py` | Create | spider-recorder: writes the full LiDAR and IMU stream to disk, on request, from cores 1-3. | body | Pi | M1, S07 |
| `spider-robot/body/src/spider_body/robot.py` | Change | The body's state machine: commands in, servo angles out, safety in between. | body | Pi | M1, S06 |
| `spider-robot/body/src/spider_body/rt.py` | Create | Real-time setup for the control process. | body | Pi | M1, S04 |
| `spider-robot/body/src/spider_body/safety.py` | Change | On-board safety reflexes. They run on the Pi at 50 Hz and never wait for the cloud. | body | Pi | M1, S04 |
| `spider-robot/body/src/spider_body/sysmon.py` | Create | spider-sysmon: the Pi's own health, published every 5 s. Runs on cores 1-3. | body | Pi | M1, S07 |
| `spider-robot/body/systemd/spider-body.service` | Change | systemd unit: Spider robot - body controller (servos, gait, safety) | body | Pi | M1, S08 |
| `spider-robot/body/systemd/spider-camera.service` | Create | systemd unit: Spider robot - camera capture (separate from the control process) | body | Pi | M1, S08 |
| `spider-robot/body/systemd/spider-lidar.service` | Change | systemd unit: Spider robot - Unitree L2 LiDAR bridge (UDP -> ZeroMQ) | body | Pi | M1, S08 |
| `spider-robot/body/systemd/spider-recorder.service` | Create | systemd unit: Spider robot - LiDAR recorder (idle until the brain requests a job) | body | Pi | M1, S08 |
| `spider-robot/body/systemd/spider-sysmon.service` | Create | systemd unit: Spider robot - Pi health (undervoltage, temperature, memory, disk) | body | Pi | M1, S08 |
| `spider-robot/body/tests/test_recorder.py` | Create | Tests: recorder | body | Mac / CI | M1, S09 |
| `spider-robot/body/tests/test_robot.py` | Change | Tests: robot | body | Mac / CI | M1, S09 |
| `spider-robot/body/tests/test_safety_fixes.py` | Create | Regression tests for defects found by the real-time and safety review. | body | Mac / CI | M1, S09 |
| `spider-robot/body/tests/test_sysmon.py` | Create | Tests: sysmon | body | Mac / CI | M1, S09 |
| `spider-robot/body/uv.lock` | Change | Pinned dependency versions | body | Mac / CI | M1, S04 |
| `spider-robot/brain/pyproject.toml` | Change | Package metadata, dependencies and entry points | brain | Home server | M1, S18 |
| `spider-robot/brain/src/spider_brain/config.py` | Change | Brain settings from environment variables (prefix SB_) or a .env file. | brain | Home server | M1, S18 |
| `spider-robot/brain/src/spider_brain/confirm.py` | Create | Fresh frame, then an explicit yes. Shared by Telegram and the dashboard. | brain | Home server | M1, S18 |
| `spider-robot/brain/src/spider_brain/jobs.py` | Create | On-demand LiDAR recording and mapping. AWS is off by default and only ever processes a copy. | brain | Home server | M1, S18 |
| `spider-robot/brain/src/spider_brain/main.py` | Change | spider-brain CLI. | brain | Home server | M1, S19 |
| `spider-robot/brain/src/spider_brain/observe.py` | Create | Latency summaries from voice turns, and alerts from service health reports. | brain | Home server | M1, S18 |
| `spider-robot/brain/src/spider_brain/rec2bag.py` | Create | Converts a spider recording (.sprec) to a ROS 1 bag for the Point-LIO container. | brain | Home server | M1, S18 |
| `spider-robot/brain/src/spider_brain/robot_client.py` | Change | The brain's view of the robot: telemetry cache + high-level actions over the link. | brain | Home server | M1, S19 |
| `spider-robot/brain/src/spider_brain/runner.py` | Change | Entry points: MQTT link factory and the one-shot `run_task` (used by `spider-brain run`). | brain | Home server | M1, S19 |
| `spider-robot/brain/src/spider_brain/service.py` | Change | BrainService: the long-running brain. | brain | Home server | M1, S19 |
| `spider-robot/brain/src/spider_brain/supervision/server.py` | Change | Remote supervision dashboard: one page + one websocket (pattern from desktop-agent). | brain | Home server | M1, S19 |
| `spider-robot/brain/src/spider_brain/supervision/static/index.html` | Change | <!doctype html> | brain | Home server | M1, S19 |
| `spider-robot/brain/src/spider_brain/telegram.py` | Change | Owner-only Telegram bot for the robot brain (official Bot API, long polling, no webhook). | brain | Home server | M1, S19 |
| `spider-robot/brain/src/spider_brain/vision.py` | Change | Vision with Liquid AI LFM2.5-VL served by llama.cpp's llama-server (OpenAI-compatible API). | brain | Home server | M1, S19 |
| `spider-robot/brain/src/spider_brain/workers.py` | Create | Workers the Pi's voice loop calls over MQTT: questions, vision, and better speech recognition. | brain | Home server | M1, S18 |
| `spider-robot/brain/tests/test_gateway_mode.py` | Create | The brain, the real gateway and the simulated body working together. | brain | Mac / CI | M1, S20 |
| `spider-robot/brain/tests/test_jobs.py` | Create | Tests: jobs | brain | Mac / CI | M1, S20 |
| `spider-robot/brain/tests/test_robot_source.py` | Change | Tests: robot source | brain | Mac / CI | M1, S20 |
| `spider-robot/brain/uv.lock` | Change | Pinned dependency versions | brain | Mac / CI | M1, S18 |
| `spider-robot/common/pyproject.toml` | Change | Package metadata, dependencies and entry points | common | Pi | M1, S03 |
| `spider-robot/common/src/spider_common/link.py` | Change | Message transport. One async interface, three implementations: | common | Pi | M1, S03 |
| `spider-robot/common/src/spider_common/obs.py` | Create | Observability helpers shared by every process: JSON logs, trace ids, fixed-cost histograms. | common | Pi | M1, S03 |
| `spider-robot/common/src/spider_common/protocol.py` | Change | Wire protocol between every process of the spider robot. The single contract. | common | Pi | M1, S03 |
| `spider-robot/common/tests/test_contract.py` | Create | Contract tests: the rules Pi and server rely on during a rolling update. | common | Mac / CI | M1, S03 |
| `spider-robot/common/tests/test_protocol.py` | Change | Tests: protocol | common | Mac / CI | M1, S03 |
| `spider-robot/common/uv.lock` | Change | Pinned dependency versions | common | Mac / CI | M1, S03 |
| `spider-robot/gateway/config/gateway.env.example` | Create | etc/spider/gateway.env (mode 640, owner spider). The gateway reaches the Pi's own broker on the | gateway | Pi | M1, S10 |
| `spider-robot/gateway/pyproject.toml` | Change | Package metadata, dependencies and entry points | gateway | Pi | M1, S10 |
| `spider-robot/gateway/src/spider_gateway/button.py` | Create | spider-button: the physical E-stop release, for when there is no network at all. | gateway | Pi | M1, S11 |
| `spider-robot/gateway/src/spider_gateway/console.py` | Create | spider-robotctl: the fallback console, for use over SSH when the server is down. | gateway | Pi | M1, S11 |
| `spider-robot/gateway/src/spider_gateway/gateway.py` | Change | The only process allowed to send commands to the robot body. | gateway | Pi | M1, S11 |
| `spider-robot/gateway/src/spider_gateway/main.py` | Change | Run the command gateway. Settings come from SG_* environment variables. | gateway | Pi | M1, S11 |
| `spider-robot/gateway/src/spider_gateway/policy.py` | Create | Per-source limits the gateway enforces before anything reaches the body. | gateway | Pi | M1, S10 |
| `spider-robot/gateway/systemd/spider-button.service` | Create | systemd unit: Spider robot - physical E-stop release button (needs no network) | gateway | Pi | M1, S12 |
| `spider-robot/gateway/systemd/spider-gateway.service` | Change | systemd unit: Spider robot - command gateway (the only sender of commands to the body) | gateway | Pi | M1, S12 |
| `spider-robot/gateway/tests/test_acl_contract.py` | Create | Every client's real topics, checked against the ACL file the broker will load. | gateway | Mac / CI | M1, S13 |
| `spider-robot/gateway/tests/test_button.py` | Create | Tests: button | gateway | Mac / CI | M1, S13 |
| `spider-robot/gateway/tests/test_console.py` | Create | Tests: console | gateway | Mac / CI | M1, S13 |
| `spider-robot/gateway/tests/test_gateway.py` | Change | Tests: gateway | gateway | Mac / CI | M1, S13 |
| `spider-robot/gateway/tests/test_gateway_policy.py` | Create | Behaviour added by the hardening milestone: each test names the defect or decision it covers. | gateway | Mac / CI | M1, S13 |
| `spider-robot/gateway/uv.lock` | Change | Pinned dependency versions | gateway | Mac / CI | M1, S10 |
| `spider-robot/infra/aws/worker/Dockerfile.slam` | Create | Point-LIO for the Unitree L2. Pin the source to a commit before first use: this file is | infra | AWS worker | M1, S22 |
| `spider-robot/infra/aws/worker/budget_alarm.sh` | Create | Required before first use of the worker: e-mail at 80% of a small monthly budget. | infra | AWS worker | M1, S22 |
| `spider-robot/infra/aws/worker/run_job.sh` | Create | Runs one mapping job on the worker: recording in, point cloud map out. | infra | AWS worker | M1, S22 |
| `spider-robot/infra/aws/worker/run_slam.sh` | Create | Inside the container: replay the bag through Point-LIO and keep the accumulated map. | infra | AWS worker | M1, S22 |
| `spider-robot/infra/aws/worker/spider-autostop.service` | Create | systemd unit: Stop this instance when idle or past its time limit | infra | AWS worker | M1, S22 |
| `spider-robot/infra/aws/worker/spider-autostop.sh` | Create | Runs on the AWS instance every minute. Stops the instance when the job is done, after 15 idle | infra | AWS worker | M1, S22 |
| `spider-robot/infra/aws/worker/spider-autostop.timer` | Create | systemd unit: Check once a minute whether this instance should stop | infra | AWS worker | M1, S22 |
| `spider-robot/infra/aws/worker/worker-control-policy.json` | Create | "Version": "2012-10-17", | infra | AWS worker | M1, S22 |
| `spider-robot/infra/aws/worker/worker_setup.sh` | Create | Run once on the instance (Ubuntu 22.04 or 24.04), then stop it. Join the tailnet by hand first. | infra | AWS worker | M1, S22 |
| `spider-robot/infra/local/acl` | Change | Mosquitto ACL. Identity is the username on the loopback listener and the certificate CN on the | infra | Pi | M1, S10 |
| `spider-robot/infra/local/make_local_certs.sh` | Change | A private CA and certificates for the Tailscale listener of the broker on the Pi. | infra | Mac / CI | M1, S21 |
| `spider-robot/infra/local/mosquitto-tls.conf` | Create | etc/mosquitto/conf.d/z-spider-tls.conf. The brain over Tailscale, mutual TLS. | infra | Pi | M1, S21 |
| `spider-robot/infra/local/mosquitto.conf` | Change | The broker on the Pi. /etc/mosquitto/conf.d/spider.conf (see infra/pi/setup_pi.sh) | infra | Pi | M1, S21 |
| `spider-robot/infra/pi/bench_jitter.sh` | Create | The real-time gate (test RT1 in the plan). Run on the Pi, with the robot on its stand. | infra | Pi | M1, S21 |
| `spider-robot/infra/pi/deploy.sh` | Create | Updates a running robot, run on the Pi from an unpacked copy of spider-robot: | infra | Pi | M1, S21 |
| `spider-robot/infra/pi/files/journald-spider.conf` | Create | etc/systemd/journald.conf.d/10-spider.conf | infra | Pi | M1, S21 |
| `spider-robot/infra/pi/files/nftables-spider.conf` | Create | etc/nftables.d/spider.conf. Only these ports are restricted; everything else is unchanged. | infra | Pi | M1, S21 |
| `spider-robot/infra/pi/files/spider-cpus.conf` | Create | etc/systemd/system.conf.d/10-spider-cpus.conf | infra | Pi | M1, S21 |
| `spider-robot/infra/pi/files/wifi-powersave.conf` | Create | etc/NetworkManager/conf.d/10-spider-wifi.conf | infra | Pi | M1, S21 |
| `spider-robot/infra/pi/mosquitto.service` | Create | systemd unit: Mosquitto MQTT broker for the spider robot | infra | Pi | M1, S21 |
| `spider-robot/infra/pi/mqtt_passwords.sh` | Create | Creates one broker login per process on the Pi. Safe to run again: existing secrets are kept. | infra | Pi | M1, S21 |
| `spider-robot/infra/pi/ollama.service` | Create | systemd unit: Ollama for the spider robot router (loopback only) | infra | Pi | M1, S21 |
| `spider-robot/infra/pi/setup_pi.sh` | Change | Raspberry Pi 4 (4 GB) setup. OS: Raspberry Pi OS Lite 64-bit, SSH and Wi-Fi enabled in the Imager. | infra | Pi | M1, S21 |
| `spider-robot/infra/pi/spider-robotctl` | Create | Runs as the spider user with the gateway's settings, because the broker passwords are readable | infra | Pi | M1, S21 |
| `spider-robot/infra/pi/spider-tune.service` | Create | systemd unit: Spider robot - move interrupts off core 0, fix the CPU governor | infra | Pi | M1, S21 |
| `spider-robot/infra/pi/spider-tune.sh` | Create | Keeps kernel work off core 0 and CPU frequency steady. Safe to run repeatedly. | infra | Pi | M1, S21 |
| `spider-robot/infra/server/brain.env.example` | Create | etc/spider-brain/brain.env (mode 600). Secrets go in /etc/spider-brain/secrets.env. | infra | Home server | M1, S22 |
| `spider-robot/infra/server/llama-planner.service` | Create | systemd unit: Liquid LFM2.5-1.2B planner and question answering (llama-server, loopback, port 8080) | infra | Home server | M1, S22 |
| `spider-robot/infra/server/llama-vision.service` | Create | systemd unit: Liquid LFM2.5-VL-1.6B vision (llama-server, loopback, port 8081) | infra | Home server | M1, S22 |
| `spider-robot/infra/server/setup_server.sh` | Create | Home server (Ubuntu 24.04, no GPU). Run as the normal user: bash infra/server/setup_server.sh | infra | Home server | M1, S22 |
| `spider-robot/infra/server/spider-brain.service` | Create | systemd unit: Spider robot brain (dashboard, Telegram, alerts, memory, voice workers) | infra | Home server | M1, S22 |
| `spider-robot/voice/config/voice.example.yaml` | Create | etc/spider/voice.yaml. Every engine is chosen here; moving one to another machine is a config change. | voice | Pi | M1, S14 |
| `spider-robot/voice/pyproject.toml` | Create | Package metadata, dependencies and entry points | voice | Pi | M1, S14 |
| `spider-robot/voice/src/spider_voice/__init__.py` | Create | Voice loop on the Raspberry Pi. | voice | Pi | M1, S14 |
| `spider-robot/voice/src/spider_voice/actions.py` | Create | Each spoken act maps to one short, self-ending command. | voice | Pi | M1, S14 |
| `spider-robot/voice/src/spider_voice/adapters/__init__.py` | Create | Vendor adapters. Nothing outside this package imports a speech or LLM SDK. | voice | Pi | M1, S15 |
| `spider-robot/voice/src/spider_voice/adapters/ask_rpc.py` | Create | Vision and hard questions, answered by the brain over MQTT. | voice | Pi | M1, S15 |
| `spider-robot/voice/src/spider_voice/adapters/router_ollama.py` | Create | LFM2.5-350M (or any model) through Ollama's chat API: one JSON decision, streamed. | voice | Pi | M1, S15 |
| `spider-robot/voice/src/spider_voice/adapters/stt_chain.py` | Create | Server first, local if the server cannot answer. Selected with stt.primary: whisper_server. | voice | Pi | M1, S15 |
| `spider-robot/voice/src/spider_voice/adapters/stt_rpc.py` | Create | The bigger Whisper on the server, for utterances the local model was unsure about. | voice | Pi | M1, S15 |
| `spider-robot/voice/src/spider_voice/adapters/stt_whisper.py` | Create | faster-whisper (CTranslate2) on the Pi. Runs in worker threads; never blocks the event loop. | voice | Pi | M1, S15 |
| `spider-robot/voice/src/spider_voice/adapters/tts_espeak.py` | Create | espeak-ng: robotic but instant and always available, the offline fallback. | voice | Pi | M1, S15 |
| `spider-robot/voice/src/spider_voice/adapters/tts_piper.py` | Create | Piper TTS. Synthesis runs on a worker thread and chunks are handed over as they are ready. | voice | Pi | M1, S15 |
| `spider-robot/voice/src/spider_voice/adapters/vad_webrtc.py` | Create | webrtcvad: a per-frame speech decision in microseconds. | voice | Pi | M1, S15 |
| `spider-robot/voice/src/spider_voice/audio.py` | Create | Microphone and speaker through arecord and aplay. | voice | Pi | M1, S15 |
| `spider-robot/voice/src/spider_voice/bench.py` | Create | Bench harness: replaces the plan's voice estimates with numbers measured on the real Pi. | voice | Pi | M1, S16 |
| `spider-robot/voice/src/spider_voice/config.py` | Create | Voice configuration. Every engine is chosen here, so swapping one needs no code change. | voice | Pi | M1, S14 |
| `spider-robot/voice/src/spider_voice/echo.py` | Create | Keeps the robot from hearing itself, without an echo canceller. | voice | Pi | M1, S14 |
| `spider-robot/voice/src/spider_voice/grammar.py` | Create | The closed-vocabulary motion grammar and the wake-word gate. | voice | Pi | M1, S14 |
| `spider-robot/voice/src/spider_voice/gwclient.py` | Create | The voice loop's connection to the command gateway. Voice never talks to the body directly. | voice | Pi | M1, S15 |
| `spider-robot/voice/src/spider_voice/interfaces.py` | Create | The swappable parts. Moving a service to another machine is a config change. | voice | Pi | M1, S14 |
| `spider-robot/voice/src/spider_voice/main.py` | Create | spider-voice entry point: microphone, pipeline, gateway connection, health. | voice | Pi | M1, S16 |
| `spider-robot/voice/src/spider_voice/pipeline.py` | Create | The voice loop: microphone frames in, stop / move / speak out. | voice | Pi | M1, S16 |
| `spider-robot/voice/src/spider_voice/registry.py` | Create | Builds the engines named in the config. The only place that chooses an adapter. | voice | Pi | M1, S16 |
| `spider-robot/voice/src/spider_voice/routing.py` | Create | The router prompt, its JSON schema, and the only code allowed to interpret its output. | voice | Pi | M1, S14 |
| `spider-robot/voice/src/spider_voice/rpc.py` | Create | Request and reply over MQTT. The worker can run on any machine with a broker login. | voice | Pi | M1, S15 |
| `spider-robot/voice/src/spider_voice/segmenter.py` | Create | Turns 20 ms microphone frames into utterances using a voice-activity decision per frame. | voice | Pi | M1, S14 |
| `spider-robot/voice/src/spider_voice/stopwords.py` | Create | Stop words: the most important command never waits for a model. | voice | Pi | M1, S14 |
| `spider-robot/voice/src/spider_voice/text.py` | Create | Arabic text normalisation for matching noisy transcripts against small word lists. | voice | Pi | M1, S14 |
| `spider-robot/voice/systemd/spider-voice.service` | Create | systemd unit: Spider robot - voice loop (VAD, Whisper, router, Piper) | voice | Pi | M1, S14 |
| `spider-robot/voice/tests/conftest.py` | Create | Tests: conftest | voice | Mac / CI | M1, S17 |
| `spider-robot/voice/tests/test_matching.py` | Create | Tests: matching | voice | Mac / CI | M1, S17 |
| `spider-robot/voice/tests/test_pipeline.py` | Create | Tests: pipeline | voice | Mac / CI | M1, S17 |
| `spider-robot/voice/tests/test_routing.py` | Create | Tests: routing | voice | Mac / CI | M1, S17 |
| `spider-robot/voice/tests/test_segmenter_echo.py` | Create | Tests: segmenter echo | voice | Mac / CI | M1, S17 |
| `spider-robot/voice/uv.lock` | Create | Pinned dependency versions | voice | Mac / CI | M1, S14 |

## Files added only as tools of the plan

| Path | Action | Purpose | Node | Step |
|---|---|---|---|---|
| `spider-robot/docs/plan/tools/apply_step.py` | Create | Writes each step's file blocks and verifies them by SHA-256 | Mac | M0, S01 |
| `spider-robot/docs/plan/PROGRESS.md` | Create | Last finished step, so a new session can resume | Mac | M0, S01 |
| `spider-robot/docs/plan/BENCH_RESULTS.md` | Create | Real bench results, added by the owner | Mac | M2 onward |

## Deleted

Nothing is deleted until M8. Then, once M6 has run for two weeks and the owner approves (step Q05):

| Path | Why |
|---|---|
| `spider-robot/infra/ec2/` | Replaced by the home server |
| `spider-robot/infra/aws/iot_setup.sh`, `body-policy.json`, `brain-policy.json` | AWS IoT is dropped from the base design |

The architecture says to keep these until the home server has replaced them.

## Kept unchanged

`body/src/spider_body/kinematics.py`, `calibrate.py`; the corridor logic in `safety.py`; the brain's
planner, graph, tools, policy, memory, skills and dashboard server structure; `infra/local/mosquitto-sim.conf`.
