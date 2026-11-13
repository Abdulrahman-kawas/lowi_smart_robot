# Spider robot architecture

Status: agreed target, 2026-11-09. Built on branch `robot/spider-robot/part2-brain`.
Sections mark what **exists** today and what is **to build**. Where this file and the root
`CLAUDE.md` disagree, this file wins.

## Rule for placing anything

> If the network dies, what must keep working?

Safety, motion and simple voice commands stay on the robot. Anything heavy that can wait a
second or more leaves the robot. The cloud is never required for the robot to function.

## Where everything runs

### Robot: Raspberry Pi 4, 4 GB

| Core | Runs | State |
|---|---|---|
| 0 | `lidar_bridge`, `spider-body` (IK, gait at 50 Hz, IMU tilt, LiDAR reflexes, watchdog, SSC-32U over USB) | exists; affinity to add |
| 1-3 | command gateway, Mosquitto broker, camera capture | to build / configure |
| 1-3 | `webrtcvad`, `faster-whisper` (`tiny`, `int8`), LFM2.5-350M on Ollama, Piper TTS | to build |

The SSC-32U only generates servo pulses. Kinematics and balance are Pi software, so the Core 0
loop is the thing to protect. Every other robot service must set `CPUAffinity=1 2 3`; pinning
Ollama alone leaves Core 0 open to Whisper and Piper.

### Home server: i7-8700, 12 threads, 15 GB RAM, no GPU, Ubuntu 24.04

| Service | State |
|---|---|
| Brain: `spider-brain serve` (planner, routing, skills, memory, dashboard) | exists; move from EC2 |
| Telegram bot, WhatsApp alerts | exists |
| Vision: LFM2.5-VL-1.6B | client exists; server to install |
| Stronger local LLM (LFM2.5-1.2B) as planner fallback | client exists; server to install |
| Better STT for hard utterances (Whisper `small` or `medium`) | to build |
| 3D SLAM, on demand only (it competes with vision for the CPU) | later |

All models run on CPU. Expect vision to take seconds per image; measure before setting timeouts.

### Cloud: escalation only

| Service | Use | State |
|---|---|---|
| Kimi K3.1 Pro on NVIDIA NIM | deep reasoning and vision | reachable through the existing `compat:<model>` route; hosted endpoint for this ID unconfirmed |
| Claude | planner tiers | exists |
| Gemini | Telegram voice notes | exists |

AWS IoT and always-on EC2 are dropped from the base design. Keep `infra/aws` and `infra/ec2` until
the home server has replaced them. AWS may return later for off-site backups.

### On-demand AWS worker (to build)

Off by default. It starts only when the owner asks for a LiDAR recording or mapping job.

- **Trigger:** an owner command reaches the brain on the home server, which starts one instance.
  Its AWS credentials allow only start, stop and describe on that instance. The Pi holds no AWS
  credentials.
- **AWS only processes.** Recording happens on the robot and home server and never depends on AWS.
  Data is uploaded over Tailscale. If AWS fails to start, the recording is kept and the job waits.
- **The instance stops itself:** when the job ends, after 15 idle minutes, and at a hard maximum
  runtime. The timer runs on the instance so it still fires if the link home dies. Set
  instance-initiated shutdown behaviour to `stop`.
- **Costs:** billed per running hour; a stopped instance still bills its disk. A budget alarm is
  required before first use.

## Network

```
phone ── Telegram (outbound long polling, no open ports) ─┐
phone ── tailscale serve ── dashboard ────────────────────┤
                                                          ▼
                                                    home server
                                                    (brain, vision)
                                                          │ MQTT + mTLS over Tailscale
                                                          ▼
Pi: voice ──► command gateway ──► Mosquitto ──► spider-body
```

- Pi and server both join the tailnet and address each other by Tailscale name. This survives
  DHCP changes and keeps working when the robot is not on the home Wi-Fi.
- The broker runs on the Pi so voice control works with no network at all.
- The LiDAR stays on Ethernet at `192.168.1.x`; the home LAN is `192.168.0.x`, so they do not clash.
- Ollama on the server has no authentication. Allow only the Pi, never expose it publicly.

## Command gateway (exists: `gateway/`; simulator-tested, not yet run on the Pi or a real broker)

Sources send commands to `spider/<id>/gw/<source>/cmd` and read events from
`spider/<id>/gw/<source>/event`, where `<source>` is `voice`, `remote` or `planner`. The brain
joins by setting `SB_ROBOT_SOURCE`. A source must heartbeat at about 2 Hz or the gateway treats it
as lost.

`spider-body` assumes a single brain. Its stop fence is per session (`robot.py:128-129`), so a
Stop from one sender does not fence a late Move from another, and any sender's heartbeat keeps
the link alive. With voice and server both commanding, one process must be the only sender.

The gateway runs on the Pi and is the only client allowed to publish to `spider/<id>/cmd`.

- **Priority:** E-stop and Stop from any source, then local voice, then remote owner, then the
  autonomous planner.
- **One session and one sequence** toward the body, so a Stop fences every earlier Move.
- **Heartbeat per source:** forward a heartbeat to the body only while the source that owns the
  current motion is alive. If the server drops during a remote Move, the robot must stop. Local
  voice must keep working regardless.
- **Validation:** every command goes through `spider_common.protocol`. The body still applies its
  own limits; the gateway never replaces them.

Broker ACLs change to match: server and voice publish to gateway topics, the gateway alone
publishes to `cmd`.

## Voice loop on the Pi (to build)

```
mic ─ VAD ─ Whisper tiny ─┬─ stop words ──────────► gateway Stop (no LLM)
                          └─ LFM2.5-350M ─ {act, say}
                                 ├─ act ─► gateway
                                 └─ say ─► Piper (in parallel)
```

- Stop words match the transcript directly. The most important command never waits for a model.
- Pass a JSON schema to Ollama with `act` as an enum. Output that does not parse means `none`.
- `say` must fit `num_predict`; Arabic is token-heavy, so test the limit rather than assume 60.
- Each `act` maps to a short `Move` with a fixed duration, or to `Snapshot` for `look`.

## Escalation

1. Pi router answers, or says a filler such as "لحظة أشوف".
2. Home server handles vision and harder questions.
3. Cloud handles what the server cannot, when internet is available.

Every step has a timeout. On failure the robot says it could not answer; motion is unaffected.

**Vision and cloud answers are spoken only.** They never produce motion directly, because a camera
can read text that tries to give orders. Motion comes from the owner's voice, or from the planner
through the risk policy and approvals.

## Remote control

Remote is a first-class requirement. All remote control ends at the brain on the server; the phone
never speaks MQTT.

| Channel | Use | State |
|---|---|---|
| Telegram | tasks, status, photos, approvals, alerts, E-stop | exists |
| Dashboard through `tailscale serve` | live supervision; still binds to loopback | exists; serve to configure |
| SSH over Tailscale to the Pi | maintenance, and the fallback when the server is down | to configure |

Nobody may be near the robot during remote use, so:

- Remote motion uses lower speed and duration caps than local voice.
- Keep autonomy at `guarded`, with approval for longer walks.
- Releasing an E-stop remotely needs a fresh camera frame and an explicit confirmation.
- Only `SB_TELEGRAM_OWNER_IDS` are served, so that Telegram account is effectively the robot's key.
  Turn on two-step verification.

## Swappable parts (to build)

STT, TTS, LLM and Vision each sit behind one small interface and are chosen in config:

```yaml
stt:     {primary: whisper_local, escalate: whisper_server}
tts:     {primary: piper}
router:  {url: http://localhost:11434, model: LFM2.5-350M}
vision:  {primary: server_vl, escalate: nim_kimi}
```

Moving a service to another machine is a URL change. Adding a model is one adapter plus config.
Nothing outside an adapter imports a vendor SDK.

## Measure from day one

Log each stage per utterance: VAD end, STT, router, first TTS audio, server, cloud. Watch
`loop_overruns` and `loop_max_ms` in `RobotState`, which already exist; they show whether AI load
is reaching the balance loop. The <300 ms router target is unproven on a Pi 4.

## Build order

1. Gateway and Pi broker, tested against the simulator.
2. Pi voice loop with swappable STT, TTS and router.
3. Brain on the home server: config, services, vision.
4. Tailscale, remote caps and E-stop release rule.
5. Cloud escalation to Kimi, then SLAM.

## Open items

- Server has 5.8 GB RAM free and nearly full swap; aim for about 8 GB free before loading models.
- Confirm Ollama loads the LFM2.5-VL image projector; otherwise use `llama-server`.
- Confirm a hosted NIM endpoint for `kimi-k3.1-pro`.
- Test Arabic quality of `whisper tiny` and LFM2.5-350M on the real Pi.
