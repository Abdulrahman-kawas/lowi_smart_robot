# File map

Every file `code.patch` creates or changes, and the files deleted at M8. Generated from the patch itself, so nothing is left out.

| Action | Path | Purpose | Owner | Node | Milestone |
|---|---|---|---|---|---|
| Create | `.github/workflows/spider-robot.yml` | CI: tests, lint, shell and JSON checks, secret scan, real bridge build | infra | CI | M0 |
| Change | `spider-robot/README.md` | Adds the voice package and the current test command | docs | Mac | M0 |
| Change | `spider-robot/common/src/spider_common/link.py` | Retain flag, will retain, inbox drop counter | common | All | M0 |
| Create | `spider-robot/common/src/spider_common/obs.py` | JSON logs, trace ids, fixed-cost histogram | common | All | M0 |
| Change | `spider-robot/common/src/spider_common/protocol.py` | Protocol v3: trace id, release proof, status, health, turns, recording | common | All | M0 |
| Change | `spider-robot/common/tests/test_protocol.py` | v3 contract and observability tests | common | Mac, CI | M0 |
| Change | `spider-robot/body/pyproject.toml` | Adds camera, recorder, sysmon entry points and the gpio extra | body | Pi | M1 |
| Create | `spider-robot/body/src/spider_body/camera_service.py` | spider-camera: capture as its own process | body | Pi, cores 1-3 | M1 |
| Change | `spider-robot/body/src/spider_body/config.py` | Real-time, recorder, sector hold, watchdog pin, external camera, corrected stop-distance check | body | Pi | M1 |
| Change | `spider-robot/body/src/spider_body/gait.py` | has_pose property, used by the cold E-stop path | body | Pi, core 0 | M1 |
| Change | `spider-robot/body/src/spider_body/hw/camera.py` | OpenCV imported only where used | body | Pi | M1 |
| Change | `spider-robot/body/src/spider_body/hw/lidar.py` | Per-sector hold, inverted mount, larger receive queue | body | Pi, core 0 | M1 |
| Change | `spider-robot/body/src/spider_body/hw/servos.py` | Short write timeout; skip a frame when USB is behind | body | Pi, core 0 | M1 |
| Change | `spider-robot/body/src/spider_body/main.py` | Real-time setup, jitter metrics and report, startup relax, E-stop-safe shutdown, kick | body | Pi, core 0 | M1 |
| Change | `spider-robot/body/src/spider_body/robot.py` | E-stop fixes, persistent latch, Stop ends ramps, trace ids, external camera, tilt guard | body | Pi, core 0 | M1 |
| Create | `spider-robot/body/src/spider_body/rt.py` | CPU pinning, SCHED_FIFO, mlockall, best-effort with reporting | body | Pi, core 0 | M1 |
| Change | `spider-robot/body/src/spider_body/safety.py` | Persistent E-stop latch, fsync off the control thread | body | Pi, core 0 | M1 |
| Create | `spider-robot/body/tests/test_safety_fixes.py` | Regression tests for the safety and timing defects | body | Mac, CI | M1 |
| Change | `spider-robot/body/uv.lock` | Lock file refreshed | body | Pi | M1 |
| Change | `spider-robot/gateway/pyproject.toml` | pyyaml, spider-robotctl entry point | gateway | Pi | M1 |
| Change | `spider-robot/gateway/src/spider_gateway/gateway.py` | Caps, lateness filter, re-stamping, release rule, status, fixes | gateway | Pi, cores 1-3 | M1 |
| Change | `spider-robot/gateway/src/spider_gateway/main.py` | Last will, policies, JSON logs | gateway | Pi, cores 1-3 | M1 |
| Create | `spider-robot/gateway/src/spider_gateway/policy.py` | Per-source caps and validation | gateway | Pi, cores 1-3 | M1 |
| Change | `spider-robot/gateway/tests/test_gateway.py` | Updated for arrival-based fencing; adds lateness, caps, release, version tests | gateway | Mac, CI | M1 |
| Change | `spider-robot/gateway/uv.lock` | Lock file refreshed | gateway | Pi | M1 |
| Change | `spider-robot/body/config/robot.example.yaml` | Local broker, latch path, real-time, recorder, external camera | body | Pi | M2 |
| Change | `spider-robot/body/lidar_bridge/lidar_bridge.cpp` | IMU decimation and averaging, 1 ms poll, recording stream, work-mode provisioning | body | Pi, core 0 | M2 |
| Create | `spider-robot/body/src/spider_body/sysmon.py` | spider-sysmon: undervoltage, temperature, memory, disk | body | Pi, cores 1-3 | M2 |
| Change | `spider-robot/body/systemd/spider-body.service` | Core 0, capabilities, locked memory, limits, hardening | body | Pi | M2 |
| Create | `spider-robot/body/systemd/spider-camera.service` | Camera service unit | body | Pi | M2 |
| Change | `spider-robot/body/systemd/spider-lidar.service` | Core 0, IMU decimation, recording socket, limits | body | Pi | M2 |
| Create | `spider-robot/body/systemd/spider-sysmon.service` | Health monitor unit | body | Pi | M2 |
| Create | `spider-robot/body/tests/test_sysmon.py` | Health assessment tests | body | Mac, CI | M2 |
| Create | `spider-robot/gateway/config/gateway.env.example` | Gateway and console settings template | gateway | Pi | M2 |
| Create | `spider-robot/gateway/src/spider_gateway/console.py` | spider-robotctl: SSH fallback console | gateway | Pi, cores 1-3 | M2 |
| Change | `spider-robot/gateway/systemd/spider-gateway.service` | Limits, hardening, required env file | gateway | Pi | M2 |
| Create | `spider-robot/gateway/tests/test_acl.py` | Static checks of the broker ACL's key promises | gateway | Mac, CI | M2 |
| Create | `spider-robot/gateway/tests/test_console.py` | Console tests against the real gateway code | gateway | Mac, CI | M2 |
| Change | `spider-robot/infra/local/acl` | Rules for every client certificate | infra | Pi | M2 |
| Change | `spider-robot/infra/local/make_local_certs.sh` | All client certificates; loopback SAN; skips existing pairs | infra | Mac | M2 |
| Change | `spider-robot/infra/local/mosquitto.conf` | No persistence, queue limits, one listener | infra | Pi | M2 |
| Create | `spider-robot/infra/pi/10-spider-cpu.conf` | Every service defaults to cores 1-3 | infra | Pi | M2 |
| Create | `spider-robot/infra/pi/bench_jitter.sh` | Gate RT1 | infra | Pi | M2 |
| Create | `spider-robot/infra/pi/journald-spider.conf` | Volatile, capped logs | infra | Pi | M2 |
| Create | `spider-robot/infra/pi/nftables-spider.conf` | Firewall | infra | Pi | M2 |
| Change | `spider-robot/infra/pi/setup_pi.sh` | Full Pi install including models and units | infra | Pi | M2 |
| Create | `spider-robot/infra/pi/spider-tune.service` | Runs the tuning at boot | infra | Pi | M2 |
| Create | `spider-robot/infra/pi/spider-tune.sh` | IRQ steering and CPU governor | infra | Pi | M2 |
| Create | `spider-robot/infra/pi/spider-update.sh` | Safe update with automatic rollback | infra | Pi | M2 |
| Create | `spider-robot/body/src/spider_body/hw/kick.py` | Hardware watchdog line | body | Pi, core 0 | M4 |
| Create | `spider-robot/infra/pi/ollama-override.conf` | Ollama on cores 1-3, loopback, kept loaded | infra | Pi | M5 |
| Create | `spider-robot/voice/config/voice.example.yaml` | Voice configuration template, every engine selectable | voice | Pi | M5 |
| Create | `spider-robot/voice/pyproject.toml` | New package definition with pinned Pi extras | voice | Pi | M5 |
| Create | `spider-robot/voice/src/spider_voice/__init__.py` | Package marker | voice | Pi, cores 1-3 | M5 |
| Create | `spider-robot/voice/src/spider_voice/actions.py` | Maps each act to one self-ending command | voice | Pi, cores 1-3 | M5 |
| Create | `spider-robot/voice/src/spider_voice/adapters/__init__.py` | Adapter package marker | voice | Pi, cores 1-3 | M5 |
| Create | `spider-robot/voice/src/spider_voice/adapters/openai_compat.py` | Vision, answers, router over the OpenAI format | voice | Pi, cores 1-3 | M5 |
| Create | `spider-robot/voice/src/spider_voice/adapters/router_ollama.py` | Router through Ollama with a JSON schema | voice | Pi, cores 1-3 | M5 |
| Create | `spider-robot/voice/src/spider_voice/adapters/stt_server.py` | Server Whisper client | voice | Pi, cores 1-3 | M5 |
| Create | `spider-robot/voice/src/spider_voice/adapters/stt_whisper.py` | faster-whisper in worker threads | voice | Pi, cores 1-3 | M5 |
| Create | `spider-robot/voice/src/spider_voice/adapters/tts_espeak.py` | espeak-ng fallback | voice | Pi, cores 1-3 | M5 |
| Create | `spider-robot/voice/src/spider_voice/adapters/tts_piper.py` | Piper streaming | voice | Pi, cores 1-3 | M5 |
| Create | `spider-robot/voice/src/spider_voice/adapters/vad_webrtc.py` | webrtcvad wrapper | voice | Pi, cores 1-3 | M5 |
| Create | `spider-robot/voice/src/spider_voice/audio.py` | arecord and aplay, RMS | voice | Pi, cores 1-3 | M5 |
| Create | `spider-robot/voice/src/spider_voice/config.py` | Voice configuration models | voice | Pi, cores 1-3 | M5 |
| Create | `spider-robot/voice/src/spider_voice/echo.py` | Half-duplex echo gate | voice | Pi, cores 1-3 | M5 |
| Create | `spider-robot/voice/src/spider_voice/grammar.py` | Motion lexicon, grammar, wake gate | voice | Pi, cores 1-3 | M5 |
| Create | `spider-robot/voice/src/spider_voice/gwclient.py` | Connection to the gateway | voice | Pi, cores 1-3 | M5 |
| Create | `spider-robot/voice/src/spider_voice/interfaces.py` | Swappable interfaces | voice | Pi, cores 1-3 | M5 |
| Create | `spider-robot/voice/src/spider_voice/main.py` | spider-voice entry point | voice | Pi, cores 1-3 | M5 |
| Create | `spider-robot/voice/src/spider_voice/pipeline.py` | The utterance pipeline | voice | Pi, cores 1-3 | M5 |
| Create | `spider-robot/voice/src/spider_voice/registry.py` | Chooses adapters from config | voice | Pi, cores 1-3 | M5 |
| Create | `spider-robot/voice/src/spider_voice/routing.py` | Router prompt, schema, parser, cross-check | voice | Pi, cores 1-3 | M5 |
| Create | `spider-robot/voice/src/spider_voice/segmenter.py` | Frames to utterances | voice | Pi, cores 1-3 | M5 |
| Create | `spider-robot/voice/src/spider_voice/stopwords.py` | Stop-word matching and stripping | voice | Pi, cores 1-3 | M5 |
| Create | `spider-robot/voice/src/spider_voice/text.py` | Arabic normalisation and fuzzy match | voice | Pi, cores 1-3 | M5 |
| Create | `spider-robot/voice/systemd/spider-voice.service` | Voice unit: cores 1-3, offline models, limits | voice | Pi | M5 |
| Create | `spider-robot/voice/tests/conftest.py` | Fixtures | voice | Mac, CI | M5 |
| Create | `spider-robot/voice/tests/test_matching.py` | Stop words, grammar, wake gate | voice | Mac, CI | M5 |
| Create | `spider-robot/voice/tests/test_pipeline.py` | Pipeline, and end to end through gateway and body | voice | Mac, CI | M5 |
| Create | `spider-robot/voice/tests/test_routing.py` | Router, adapters | voice | Mac, CI | M5 |
| Create | `spider-robot/voice/tests/test_segmenter_echo.py` | Segmenter and echo gate | voice | Mac, CI | M5 |
| Create | `spider-robot/voice/uv.lock` | Lock file | voice | Pi | M5 |
| Change | `spider-robot/brain/pyproject.toml` | stt, aws, slam extras; spider-stt entry point | brain | Server | M6 |
| Change | `spider-robot/brain/src/spider_brain/config.py` | Recording, AWS and telemetry settings | brain | Server | M6 |
| Change | `spider-robot/brain/src/spider_brain/main.py` | Teleop release shows a frame first | brain | Server | M6 |
| Change | `spider-robot/brain/src/spider_brain/robot_client.py` | Planner and remote sources, release proof, telemetry intake | brain | Server | M6 |
| Change | `spider-robot/brain/src/spider_brain/service.py` | Planner runs as the planner source; jobs; telemetry path | brain | Server | M6 |
| Create | `spider-robot/brain/src/spider_brain/stt_server.py` | spider-stt: Whisper small over HTTP with a token | brain | Server | M6 |
| Change | `spider-robot/brain/src/spider_brain/supervision/server.py` | Two-step release; /telemetry endpoint | brain | Server | M6 |
| Change | `spider-robot/brain/src/spider_brain/supervision/static/index.html` | Release confirmation, services panel, latency panel | brain | Server | M6 |
| Change | `spider-robot/brain/src/spider_brain/telegram.py` | Two-step release, /record, /map, health alerts | brain | Server | M6 |
| Create | `spider-robot/brain/src/spider_brain/telemetry.py` | Rolling voice latency and health store | brain | Server | M6 |
| Create | `spider-robot/brain/tests/test_remote_release.py` | Sources, release flow, STT server tests | brain | Mac, CI | M6 |
| Change | `spider-robot/brain/tests/test_robot_source.py` | Updated: both gateway topics are allowed | brain | Mac, CI | M6 |
| Create | `spider-robot/brain/tests/test_telemetry.py` | Telemetry and health alert tests | brain | Mac, CI | M6 |
| Change | `spider-robot/brain/uv.lock` | Lock file refreshed | brain | Server | M6 |
| Create | `spider-robot/infra/server/brain.env.example` | Brain settings template | infra | Server | M6 |
| Create | `spider-robot/infra/server/llama-planner.service` | Fallback planner unit, tailnet only, with API key | infra | Server | M6 |
| Create | `spider-robot/infra/server/llama-vision.service` | Vision unit, tailnet only, with API key | infra | Server | M6 |
| Create | `spider-robot/infra/server/llama.env.example` | API key template for llama-server | infra | Server | M6 |
| Create | `spider-robot/infra/server/setup_server.sh` | Home server install | infra | Server | M6 |
| Create | `spider-robot/infra/server/spider-brain.service` | Brain unit, no SSM | infra | Server | M6 |
| Create | `spider-robot/infra/server/spider-stt.service` | STT unit, tailnet only | infra | Server | M6 |
| Create | `spider-robot/infra/server/stt.env.example` | Token template for spider-stt | infra | Server | M6 |
| Create | `spider-robot/body/src/spider_body/recorder.py` | spider-recorder: LiDAR recording on request, .sprec format | body | Pi, cores 1-3 | M7 |
| Create | `spider-robot/body/systemd/spider-recorder.service` | Recorder unit | body | Pi | M7 |
| Create | `spider-robot/body/tests/test_recorder.py` | Recording format and job tests | body | Mac, CI | M7 |
| Create | `spider-robot/brain/src/spider_brain/jobs.py` | Recording requests, AWS worker control, job pipeline | brain | Server | M7 |
| Create | `spider-robot/brain/src/spider_brain/rec2bag.py` | Recording to ROS 1 bag | brain | Server | M7 |
| Create | `spider-robot/brain/tests/test_jobs.py` | Job pipeline and bag conversion tests | brain | Mac, CI | M7 |
| Create | `spider-robot/infra/aws/worker/Dockerfile.slam` | Point-LIO container | infra | AWS worker | M7 |
| Create | `spider-robot/infra/aws/worker/budget_alarm.sh` | Required budget alarm | infra | Mac | M7 |
| Create | `spider-robot/infra/aws/worker/run_job.sh` | One mapping job | infra | AWS worker | M7 |
| Create | `spider-robot/infra/aws/worker/run_slam.sh` | Runs inside the container | infra | AWS worker | M7 |
| Create | `spider-robot/infra/aws/worker/spider-autostop.service` | Self-stop check | infra | AWS worker | M7 |
| Create | `spider-robot/infra/aws/worker/spider-autostop.sh` | Stops the instance when idle or at the hard limit | infra | AWS worker | M7 |
| Create | `spider-robot/infra/aws/worker/spider-autostop.timer` | Runs the check every minute | infra | AWS worker | M7 |
| Create | `spider-robot/infra/aws/worker/worker-control-policy.json` | IAM policy: start, stop, describe only | infra | AWS | M7 |
| Create | `spider-robot/infra/aws/worker/worker_setup.sh` | Instance setup | infra | AWS worker | M7 |

82 files created, 38 changed in `code.patch`.

## Deleted at M8

These are **not in `code.patch`**: the agreed architecture keeps them until the home server has replaced them.
After the M8 gate:

```bash
git rm -r spider-robot/infra/ec2
git rm spider-robot/infra/aws/iot_setup.sh spider-robot/infra/aws/body-policy.json spider-robot/infra/aws/brain-policy.json
```

| Action | Path | Why | Owner | Node | Milestone |
|---|---|---|---|---|---|
| Delete | `spider-robot/infra/ec2/liquid-planner.service` | Replaced by `infra/server/llama-planner.service` | infra | n/a | M8 |
| Delete | `spider-robot/infra/ec2/liquid-vision.service` | Replaced by `infra/server/llama-vision.service` | infra | n/a | M8 |
| Delete | `spider-robot/infra/ec2/run-brain.sh` | No SSM on the home server | infra | n/a | M8 |
| Delete | `spider-robot/infra/ec2/setup_ec2.sh` | Replaced by `infra/server/setup_server.sh` | infra | n/a | M8 |
| Delete | `spider-robot/infra/ec2/spider-brain.service` | Replaced by `infra/server/spider-brain.service` | infra | n/a | M8 |
| Delete | `spider-robot/infra/aws/iot_setup.sh` | AWS IoT is dropped | infra | n/a | M8 |
| Delete | `spider-robot/infra/aws/body-policy.json` | AWS IoT is dropped | infra | n/a | M8 |
| Delete | `spider-robot/infra/aws/brain-policy.json` | AWS IoT is dropped | infra | n/a | M8 |

