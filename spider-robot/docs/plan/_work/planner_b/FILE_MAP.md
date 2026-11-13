# File map

Every file changed by `code.patch`, generated from the diff against the baseline, 107 files. Milestones are defined in `PLAN_13_roadmap.md`.

| Path | Action | Purpose | Owner | Node | Milestone |
|---|---|---|---|---|---|
| `.github/workflows/spider-robot.yml` | Create | CI: tests and ruff per package, bash -n on scripts | infra | GitHub | M0 |
| `spider-robot/README.md` | Change | Lists the voice package and its tests | docs | - | M2 |
| `spider-robot/body/config/robot.example.yaml` | Change | Loopback broker login, realtime, sector history, camera CPUs | body | Pi | M1 |
| `spider-robot/body/lidar_bridge/lidar_bridge.cpp` | Change | IMU averaged to about 50 Hz; rawcloud with time and ring; rawimu | body | Pi, Core 0 | M1 |
| `spider-robot/body/pyproject.toml` | Change | spider-record entry point | body | Pi | M6 |
| `spider-robot/body/src/spider_body/config.py` | Change | RealtimeCfg, broker login, history_clouds, camera cpus | body | Pi | M1 |
| `spider-robot/body/src/spider_body/hw/camera.py` | Change | OpenCV limited to one thread | body | Pi | M1 |
| `spider-robot/body/src/spider_body/hw/lidar.py` | Change | Named ZeroMQ topics; nearest return over recent clouds | body | Pi, Core 0 | M1 |
| `spider-robot/body/src/spider_body/hw/servos.py` | Change | Fixes the group move rate gate | body | Pi, Core 0 | M1 |
| `spider-robot/body/src/spider_body/main.py` | Change | Lateness metric, limp at start, realtime, broker login | body | Pi, Core 0 | M1 |
| `spider-robot/body/src/spider_body/realtime.py` | Create | GIL switch, mlock, optional SCHED_FIFO; never fatal | body | Pi, Core 0 | M1 |
| `spider-robot/body/src/spider_body/recorder.py` | Create | spider-record: SPLR recording, controlled over MQTT | body | Pi, cores 1-3 | M6 |
| `spider-robot/body/src/spider_body/robot.py` | Change | Camera worker off Core 0, staged wake, watchdog fix, lateness histogram | body | Pi, Core 0 | M1 |
| `spider-robot/body/systemd/spider-body.service` | Change | Core 0, RT limits, memory cap, OOM protection | body | Pi | M1 |
| `spider-robot/body/systemd/spider-lidar.service` | Change | Core 0, IMU_DECIMATE, memory cap | body | Pi | M1 |
| `spider-robot/body/systemd/spider-record.service` | Create | Recorder unit, idle IO priority | body | Pi | M6 |
| `spider-robot/body/tests/test_hardening.py` | Create | Tests for the body changes and recorder | body | CI | M1 |
| `spider-robot/body/uv.lock` | Change | Lock refreshed by uv | body | - | M1 |
| `spider-robot/brain/pyproject.toml` | Change | stt and aws groups; gateway as a test dependency | brain | Server | M3 |
| `spider-robot/brain/src/spider_brain/aws_job.py` | Create | Recording requests; starts the AWS worker only on request | brain | Server | M6 |
| `spider-robot/brain/src/spider_brain/config.py` | Change | human_source, worker, STT, ask route, AWS settings | brain | Server | M3 |
| `spider-robot/brain/src/spider_brain/confirm.py` | Create | Frame-and-confirm flow for Telegram and dashboard | brain | Server | M4 |
| `spider-robot/brain/src/spider_brain/main.py` | Change | Passes human_source | brain | Server | M3 |
| `spider-robot/brain/src/spider_brain/observe.py` | Create | Trace summaries and health alerts | brain | Server | M3 |
| `spider-robot/brain/src/spider_brain/robot_client.py` | Change | Two sources, preempted handling, request_confirm, message handlers | brain | Server | M3 |
| `spider-robot/brain/src/spider_brain/runner.py` | Change | Subscribes to both sources and the worker topics | brain | Server | M3 |
| `spider-robot/brain/src/spider_brain/service.py` | Change | Wires confirm, traces, health, jobs and workers | brain | Server | M3 |
| `spider-robot/brain/src/spider_brain/supervision/server.py` | Change | Dashboard release goes through the confirm flow | brain | Server | M4 |
| `spider-robot/brain/src/spider_brain/supervision/static/index.html` | Change | Confirm card, sources panel, latency panel | brain | Server | M4 |
| `spider-robot/brain/src/spider_brain/telegram.py` | Change | /release and wake with a frame; /record and /map | brain | Server | M4 |
| `spider-robot/brain/src/spider_brain/vision.py` | Change | compat route for NIM | brain | Server | M5 |
| `spider-robot/brain/src/spider_brain/workers.py` | Create | AskService and SttWorker over MQTT | brain | Server | M3 |
| `spider-robot/brain/tests/test_gateway_mode.py` | Create | Brain with the real gateway and simulated body; workers; jobs | brain | CI | M3 |
| `spider-robot/brain/uv.lock` | Change | Lock refreshed by uv | brain | - | M3 |
| `spider-robot/common/pyproject.toml` | Change | spider-health entry point; ruff for the package | common | Pi, server | M1 |
| `spider-robot/common/src/spider_common/health.py` | Create | Per-node health reporter | common | Pi, server | M1 |
| `spider-robot/common/src/spider_common/link.py` | Change | Username login, retain, reconnect ceiling | common | Pi, server | M1 |
| `spider-robot/common/src/spider_common/protocol.py` | Change | cid, confirm messages, status, voice, RPC, health, recording | common | Pi, server | M1 |
| `spider-robot/common/src/spider_common/telemetry.py` | Create | JSON logs and correlation IDs | common | Pi, server | M1 |
| `spider-robot/common/tests/test_contract.py` | Create | Rolling-update and bounds rules | common | CI | M1 |
| `spider-robot/common/tests/test_health.py` | Create | Parsers in the health reporter | common | CI | M1 |
| `spider-robot/common/uv.lock` | Change | Lock refreshed by uv | common | - | M1 |
| `spider-robot/gateway/src/spider_gateway/gateway.py` | Change | Hold-off, caps, queue delay, restamp, confirmed actions, status | gateway | Pi, cores 1-3 | M1 |
| `spider-robot/gateway/src/spider_gateway/main.py` | Change | Config, login, JSON logs | gateway | Pi, cores 1-3 | M1 |
| `spider-robot/gateway/systemd/spider-gateway.service` | Change | Resource limits | gateway | Pi | M1 |
| `spider-robot/gateway/tests/test_acl_contract.py` | Create | Checks every client's topics against the ACL file | gateway | CI | M1 |
| `spider-robot/gateway/tests/test_gateway.py` | Change | Three existing tests updated for the new rules | gateway | CI | M1 |
| `spider-robot/gateway/tests/test_gateway_policy.py` | Create | Tests for each new rule | gateway | CI | M1 |
| `spider-robot/gateway/uv.lock` | Change | Lock refreshed by uv | gateway | - | M1 |
| `spider-robot/infra/aws/worker/brain-job-policy.json` | Create | IAM: start, stop, describe on one instance | infra | AWS | M6 |
| `spider-robot/infra/aws/worker/self_stop.sh` | Create | Stops the instance when idle or over its limit | infra | AWS worker | M6 |
| `spider-robot/infra/aws/worker/spider-self-stop.service` | Create | Runs the check | infra | AWS worker | M6 |
| `spider-robot/infra/aws/worker/spider-self-stop.timer` | Create | Once a minute | infra | AWS worker | M6 |
| `spider-robot/infra/local/acl` | Change | ACL for all clients and new topics | infra | Pi | M1 |
| `spider-robot/infra/local/make_local_certs.sh` | Change | Only the server and brain certificates | infra | Offline machine | M4 |
| `spider-robot/infra/local/mosquitto.conf` | Change | Loopback plus mTLS listeners, no persistence | infra | Pi | M1 |
| `spider-robot/infra/pi/deploy.sh` | Create | Safe update with automatic rollback | infra | Pi | M1 |
| `spider-robot/infra/pi/files/gateway.env.example` | Create | Gateway settings | infra | Pi | M1 |
| `spider-robot/infra/pi/files/journald-spider.conf` | Create | Logs in RAM | infra | Pi | M1 |
| `spider-robot/infra/pi/files/mosquitto-override.conf` | Create | Broker CPU, memory, restart | infra | Pi | M1 |
| `spider-robot/infra/pi/files/nftables-spider.conf` | Create | Restricts 1883, 8883, 11434 | infra | Pi | M1 |
| `spider-robot/infra/pi/files/ollama-override.conf` | Create | Ollama loopback, CPU, memory, always loaded | infra | Pi | M2 |
| `spider-robot/infra/pi/files/record.example.yaml` | Create | Recorder settings | infra | Pi | M6 |
| `spider-robot/infra/pi/files/spider-cpus.conf` | Create | Default CPUAffinity 1-3 | infra | Pi | M1 |
| `spider-robot/infra/pi/files/spider-health.service` | Create | Health unit, Pi | infra | Pi | M1 |
| `spider-robot/infra/pi/files/wifi-powersave.conf` | Create | Wi-Fi power save off | infra | Pi | M1 |
| `spider-robot/infra/pi/mqtt_passwords.sh` | Create | One broker login per process | infra | Pi | M1 |
| `spider-robot/infra/pi/setup_pi.sh` | Change | Full Pi install with pins | infra | Pi | M1 |
| `spider-robot/infra/server/brain.env.example` | Create | Server settings | infra | Server | M3 |
| `spider-robot/infra/server/health.env.example` | Create | Health settings, server | infra | Server | M3 |
| `spider-robot/infra/server/llama-planner.service` | Create | LFM2.5-1.2B on loopback | infra | Server | M3 |
| `spider-robot/infra/server/llama-vision.service` | Create | LFM2.5-VL on loopback | infra | Server | M3 |
| `spider-robot/infra/server/setup_server.sh` | Create | Server install with pins | infra | Server | M3 |
| `spider-robot/infra/server/spider-brain.service` | Create | Brain unit, limits | infra | Server | M3 |
| `spider-robot/infra/server/spider-health.service` | Create | Health unit, server | infra | Server | M3 |
| `spider-robot/infra/slam/Dockerfile` | Create | Point-LIO image | infra | Server, AWS | M6 |
| `spider-robot/infra/slam/process_job.sh` | Create | Copies a recording and maps here or on the worker | infra | Server | M6 |
| `spider-robot/infra/slam/rec2bag.py` | Create | SPLR to ROS 1 bag | infra | Server, AWS | M6 |
| `spider-robot/infra/slam/run_slam.sh` | Create | Conversion and Point-LIO run | infra | Server, AWS | M6 |
| `spider-robot/voice/config/voice.example.yaml` | Create | All adapters and thresholds | voice | Pi | M2 |
| `spider-robot/voice/pyproject.toml` | Create | Package; Pi-only dependency group | voice | Pi | M2 |
| `spider-robot/voice/src/spider_voice/__init__.py` | Create | Package marker | voice | Pi, cores 1-3 | M2 |
| `spider-robot/voice/src/spider_voice/actions.py` | Create | Act to command | voice | Pi, cores 1-3 | M2 |
| `spider-robot/voice/src/spider_voice/adapters/__init__.py` | Create | Package marker | voice | Pi, cores 1-3 | M2 |
| `spider-robot/voice/src/spider_voice/adapters/audio.py` | Create | Microphone and killable playback | voice | Pi, cores 1-3 | M2 |
| `spider-robot/voice/src/spider_voice/adapters/fakes.py` | Create | Test adapters | voice | Pi, cores 1-3 | M2 |
| `spider-robot/voice/src/spider_voice/adapters/router.py` | Create | Ollama router, early act, schema | voice | Pi, cores 1-3 | M2 |
| `spider-robot/voice/src/spider_voice/adapters/stt_rpc.py` | Create | STT on another machine over MQTT | voice | Pi, cores 1-3 | M2 |
| `spider-robot/voice/src/spider_voice/adapters/stt_whisper.py` | Create | Local faster-whisper | voice | Pi, cores 1-3 | M2 |
| `spider-robot/voice/src/spider_voice/adapters/tts.py` | Create | Piper and espeak-ng | voice | Pi, cores 1-3 | M2 |
| `spider-robot/voice/src/spider_voice/attention.py` | Create | Wake phrase and window | voice | Pi, cores 1-3 | M2 |
| `spider-robot/voice/src/spider_voice/bench.py` | Create | Bench harness for B-V1 to B-V3 | voice | Pi, cores 1-3 | M2 |
| `spider-robot/voice/src/spider_voice/config.py` | Create | voice.yaml schema | voice | Pi, cores 1-3 | M2 |
| `spider-robot/voice/src/spider_voice/factory.py` | Create | Adapter registry | voice | Pi, cores 1-3 | M2 |
| `spider-robot/voice/src/spider_voice/grammar.py` | Create | Stop words and commands | voice | Pi, cores 1-3 | M2 |
| `spider-robot/voice/src/spider_voice/interfaces.py` | Create | STT, TTS, router, audio interfaces | voice | Pi, cores 1-3 | M2 |
| `spider-robot/voice/src/spider_voice/main.py` | Create | Entry point | voice | Pi, cores 1-3 | M2 |
| `spider-robot/voice/src/spider_voice/normalize.py` | Create | Arabic normalisation | voice | Pi, cores 1-3 | M2 |
| `spider-robot/voice/src/spider_voice/pipeline.py` | Create | The voice loop | voice | Pi, cores 1-3 | M2 |
| `spider-robot/voice/src/spider_voice/rpc.py` | Create | Request and reply over MQTT | voice | Pi, cores 1-3 | M2 |
| `spider-robot/voice/src/spider_voice/vad.py` | Create | Speech segmentation | voice | Pi, cores 1-3 | M2 |
| `spider-robot/voice/systemd/spider-voice.service` | Create | Unit, CPU, memory | voice | Pi | M2 |
| `spider-robot/voice/tests/test_language.py` | Create | Normalisation, grammar, attention | voice | CI | M2 |
| `spider-robot/voice/tests/test_pipeline.py` | Create | End-to-end voice behaviour | voice | CI | M2 |
| `spider-robot/voice/tests/test_router.py` | Create | Router contract and token budget | voice | CI | M2 |
| `spider-robot/voice/tests/test_vad.py` | Create | Segmenter | voice | CI | M2 |
| `spider-robot/voice/uv.lock` | Create | Lock file | voice | Pi | M2 |

## Files to delete later

Nothing is deleted by `code.patch`, per the agreed decision to keep AWS and EC2 files until the home server has replaced them. After gate M7 passes:

| Path | Why |
|---|---|
| `spider-robot/infra/ec2/*` | Replaced by `infra/server` |
| `spider-robot/infra/aws/iot_setup.sh`, `body-policy.json`, `brain-policy.json` | AWS IoT is dropped |
| AWS IoT block in `spider-robot/brain/.env.example` | Replaced by `infra/server/brain.env.example` |
