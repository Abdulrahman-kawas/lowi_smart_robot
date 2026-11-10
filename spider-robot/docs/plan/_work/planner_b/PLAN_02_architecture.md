# 2. Architecture

## 2.1 Context

```mermaid
flowchart LR
  person([Person near the robot]) -- speech --> robot
  owner([Owner, possibly away]) -- Telegram --> tg[Telegram cloud]
  owner -- Dashboard over Tailscale --> server
  owner -. SSH over Tailscale, fallback .-> robot
  tg -- long polling, outbound only --> server
  subgraph home[Home]
    robot[Robot: Pi 4, servos, LiDAR, camera]
    server[Home server: brain, models]
  end
  server <-- MQTT with mutual TLS over Tailscale --> robot
  server -. only when local models cannot answer .-> nim[NVIDIA NIM]
  server -. planner tiers .-> claude[Claude API]
  server -. voice notes .-> gemini[Gemini]
  server -. only for a requested job .-> aws[AWS worker]
```

## 2.2 Containers

```mermaid
flowchart TB
  subgraph pi[Raspberry Pi 4]
    subgraph c0[Core 0]
      bridge[lidar_bridge C++]
      body[spider-body: IK, gait, reflexes, watchdog]
    end
    subgraph c13[Cores 1-3]
      broker[(Mosquitto)]
      gw[spider-gateway]
      voice[spider-voice]
      ollama[Ollama + LFM2.5-350M]
      rec[spider-record, idle until asked]
      hp[spider-health]
    end
    ssc[SSC-32U]
    l2[Unitree L2]
    cam[Camera]
    mic[Mic and speaker]
  end
  subgraph srv[Home server]
    brain[spider-brain: planner, Telegram, dashboard, memory, workers]
    vis[llama-server: LFM2.5-VL]
    plan[llama-server: LFM2.5-1.2B]
    hs[spider-health]
  end
  l2 -- UDP Ethernet --> bridge
  bridge -- ZeroMQ cloud, imu --> body
  bridge -. rawcloud, rawimu .-> rec
  body -- USB serial --> ssc
  cam --> body
  mic --> voice
  voice -- HTTP loopback --> ollama
  voice -- gw/voice/cmd --> broker
  broker --> gw
  gw -- cmd, only sender --> broker
  broker --> body
  body -- state, event, camera --> broker
  brain <-- gw/remote and gw/planner, rpc --> broker
  brain -- HTTP loopback --> vis
  brain -- HTTP loopback --> plan
```

No Kubernetes, no service mesh, no time-series database. Eight small processes on the Pi, each a systemd unit, and one Python process plus two model servers at home.

## 2.3 Component responsibilities and boundaries

| Component | Owns | Must never |
|---|---|---|
| `lidar_bridge` | L2 driver; decimated `cloud` and `imu`; raw topics | Block on a subscriber |
| `spider-body` | IK, gait, servo output, reflexes, watchdog, E-stop latch, final limits | Trust any sender; wait on a network |
| `spider-gateway` | Priority, one session and sequence, source caps, hold-off, source liveness, queue delay, confirmed actions | Replace body limits; run models |
| Mosquitto | Message routing, ACL | Persist messages across restart |
| `spider-voice` | VAD, STT chain, stop words, attention, grammar, router, TTS, traces | Send to `cmd`; let an answer cause motion |
| Ollama | LFM2.5-350M inference | Listen beyond loopback |
| `spider-record` | Recording on request | Run during normal use (no socket when idle) |
| `spider-brain` | Planner with approvals, Telegram, dashboard, memory, vision routing, ask and STT workers, mapping jobs, alerts | Hold the only copy of a safety rule |
| `llama-server` x2 | Vision and stronger LLM | Listen beyond loopback |
| `spider-health` | Node facts for alerts | Decide anything |

**Rule for placing a safety check:** if a compromised or buggy brain could bypass it, it belongs on the Pi. That is why caps, hold-off and confirmation live in the gateway, and Telegram only shows the frame and sends the answer.

## 2.4 Key data flows

### Voice command, online

```mermaid
sequenceDiagram
  participant M as Mic/VAD
  participant V as spider-voice
  participant S as Worker STT
  participant G as Gateway
  participant B as Body
  participant T as TTS
  M->>V: SpeechStart (robot idle, nothing happens)
  M->>V: SpeechEnd with audio
  V->>S: rpc/stt/req with base64 PCM, cid
  S-->>V: rpc/stt/res/voice text
  V->>V: stop words, attention, grammar
  par motion
    V->>G: gw/voice/cmd Move, cid
    G->>B: cmd, renumbered, Pi clock, capped
    B-->>G: event ack
    G-->>V: gw/voice/event ack
  and speech
    V->>T: canned phrase, about 50 ms
  end
  V->>V: publish VoiceTrace with stage timings
```

### Speech while moving: the fast Stop

```mermaid
sequenceDiagram
  participant M as Mic/VAD
  participant V as spider-voice
  participant G as Gateway
  participant B as Body
  participant P as Planner
  M->>V: SpeechStart after about 100 ms of speech
  V->>G: Stop before any model
  G->>B: Stop, QoS 1
  G-->>P: preempted, and a 2 s hold-off starts
  P-xG: renewed Move is refused
  B->>B: gait ramps to zero within 0.35 s
  M->>V: SpeechEnd
  V->>V: transcript decides what happens next
```

### Remote E-stop release

```mermaid
sequenceDiagram
  participant O as Owner phone
  participant B as Brain
  participant G as Gateway
  participant R as Body and camera
  O->>B: /release
  B->>G: ConfirmRequest with request_id
  G->>R: Snapshot
  R-->>G: JPEG on camera topic
  R-->>B: the same JPEG
  G->>G: sha256, single-use challenge, 30 s
  G-->>B: event challenge
  B->>O: photo with Clear and Cancel
  O->>B: Clear
  B->>G: EStopRelease with challenge and sha256
  G->>G: checks source, action, expiry, hash
  G->>R: release
```

### Question and vision: speech only

`voice -> rpc/ask/req -> brain -> local model, then cloud if configured -> rpc/ask/res/voice -> TTS`. `AskReply` has no action field, and a test pins its exact field set (`test_ask_reply_cannot_carry_an_action`). Even an answer reading "walk forward" is only said aloud (`test_answer_from_vision_is_only_spoken`).

### Remote walk (Telegram task)

Owner -> brain planner -> policy and approval (`policy.py`) -> `gw/planner/cmd` Moves of 1 s renewed every 0.5 s (`robot_client.py:266-271`) -> gateway applies caps and queue-delay check -> body limits and reflexes.

### Mapping job

`/record 120` -> `record/cmd` -> `spider-record` opens its socket, writes SPLR to `/var/lib/spider/recordings`, stops at `max_s` -> `/map <job>` copies it to the server with rsync, converts, runs Point-LIO in Docker. `/map <job> aws` starts the worker first, copies over Tailscale, runs there, copies the map back, and shuts the worker down. Recording never depends on AWS.

## 2.5 Why these interfaces

| Choice | Why it fits one developer |
|---|---|
| MQTT is the only Pi-server channel | One login, one ACL, one thing to debug. The server opens no model ports. Moving a worker needs no change on the Pi |
| Protocols plus a registry in `factory.py` | One adapter plus one config line adds a model. Vendor SDKs are imported only in `adapters/` |
| YAML for voice, `SB_` env for the brain | Follows what exists |
| No shared database | JSONL traces and retained status cover one robot |
