# 3. Contracts

`common/src/spider_common/protocol.py` is the single contract. All messages are JSON, except camera
frames (raw JPEG) and the local ZeroMQ stream.

## 3.1 MQTT topics

`<id>` is the robot id, for example `spider-01`. Writers are enforced by the broker ACL
(`infra/local/acl`).

| Topic | Payload | Writer → reader | QoS | Retain | Rate | Timeout and behaviour |
|---|---|---|---|---|---|---|
| `spider/<id>/cmd` | `Command` | gateway → body, camera | Move 0; others 1 | No | Moves ≤ 2 Hz per source; heartbeat 4 Hz | Body stops 1.5 s after the last message while moving |
| `spider/<id>/gw/voice/cmd` | `Command` | voice → gateway | Move 0; others 1 | No | Heartbeat 2 Hz | Source lost after 1.5 s |
| `spider/<id>/gw/remote/cmd` | `Command` | brain, console → gateway | Move 0; others 1 | No | Heartbeat 2 Hz; Moves 2 Hz | Source lost after 1.5 s; excess delay > 0.75 s refused |
| `spider/<id>/gw/planner/cmd` | `Command` | brain → gateway | Move 0; others 1 | No | As remote | As remote |
| `spider/<id>/gw/<source>/event` | `RobotEvent` | gateway → source | 1 | No | On event | None |
| `spider/<id>/gw/status` | `GatewayStatus` | gateway → all | 1 | Yes, with last will | 1 Hz | Treat as unknown if older than 5 s |
| `spider/<id>/state` | `RobotState` | body → all | 0 | No | 4 Hz | Telemetry is stale after 1.5 s |
| `spider/<id>/event` | `RobotEvent` | body, camera → gateway | 1 | No | On event | Body's last will reports `offline` |
| `spider/<id>/camera/<request_id>` | JPEG, ≤ 120 KB | body or camera → requester | 1 | No | ≤ 2 per second per source | Requester waits 8 s |
| `spider/<id>/voice/turn` | `VoiceTurn` | voice → brain | 0 | No | Per utterance | Telemetry only |
| `spider/<id>/health/<service>` | `HealthReport` | voice, camera → all | 1 | Yes, with last will | 1 per 5 s | Treat as unknown if older than 30 s |
| `spider/<id>/rec/cmd` | `RecordRequest` | brain → recorder | 1 | No | On request | None |
| `spider/<id>/rec/event` | `RecordEvent` | recorder → brain | 1 | No | On event | None |

`max_queued_messages 20` and `persistence false` keep the broker from replaying old commands.

## 3.2 Commands

All commands share: `v`, `session` (≤ 64 chars), `seq`, `ts` (sender wall clock), `trace` (≤ 32 chars).

| `type` | Extra fields | Limits |
|---|---|---|
| `move` | `vx`, `vy` (±0.5), `wz` (±2.0), `duration_s` (0 to 10), `gait` | Protocol limits. Tighter below |
| `stop` | none | Always accepted |
| `posture` | `posture`: stand, sit, relax | |
| `body_pose` | `height_m`, `roll_deg`, `pitch_deg`, `yaw_deg` | ±20° |
| `snapshot` | `request_id` (`^[A-Za-z0-9_-]+$`) | Rate limited |
| `heartbeat` | none | |
| `estop` | none | Always accepted; latches and persists |
| `estop_release` | `frame_id`, `confirmed` | Remote only, with proof |

### Per-source policy, enforced at the gateway

| Source | Max speed | Max turn | Max duration | Late limit | Release E-stop |
|---|---|---|---|---|---|
| voice | 0.08 m/s | 0.5 rad/s | 2.0 s | 0.5 s | No |
| remote | 0.05 m/s | 0.3 rad/s | 1.0 s | 0.75 s | With fresh frame and confirmation |
| planner | 0.06 m/s | 0.45 rad/s | 1.0 s | 0.75 s | No |

The file `SG_POLICY_FILE` can override these. `check_order` refuses a configuration where remote
exceeds voice. The body's own limits still apply afterwards (`max_vx 0.12`, `max_wz 0.6`).

**Priority (agreed decision 5):** Stop and E-stop from anyone; then voice; then remote; then planner. A
Stop blocks Moves from *other* sources for 0.75 s, measured on the gateway's clock.

## 3.3 Telemetry

`RobotState` (additions in v3 are optional): `v`, `robot_id`, `ts`, `mode`, `vx`, `vy`, `wz`,
`move_remaining_s`, `roll_deg`, `pitch_deg`, `lidar`, `lidar_age_s`, `last_seq`, `link_ok`, `estop`,
`limiter`, `loop_overruns`, `loop_max_ms`, `loop_late_max_ms`, `loop_late_p99_ms`, `rt_ok`.

`RobotEvent`: `v`, `robot_id`, `ts`, `kind`, `seq`, `detail`, `trace`.
Kinds: `ack`, `rejected`, `obstacle_stop`, `tilt`, `fallen`, `link_lost`, `estop`, `move_done`,
`online`, `offline`, `error`, `snapshot_failed`, `snapshot_ok`, `clamped`.

`GatewayStatus`, `HealthReport`, `VoiceTurn`, `RecordRequest`, `RecordEvent`: see `protocol.py`.

## 3.4 Local interfaces

| Interface | Format | Notes |
|---|---|---|
| Bridge → body | ZeroMQ `ipc:///tmp/spider_lidar.ipc`: `["cloud", <dII, f32[n*4]]`, `["imu", <d, f32[10]]` | IMU averaged to 100 Hz |
| Bridge → recorder | ZeroMQ `ipc:///tmp/spider_lidar_rec.ipc`: `["cloudx", <dII, f32[n*6]]`, `["imux", <d, f32[10]]` | Full rate |
| Body → SSC-32U | ASCII group move, 115200 baud | `#<ch>P<us>...T40\r`; `P0` for off **[S: community, not the manual]** |
| Voice → Ollama | `POST /api/chat`: `format` schema, `keep_alive -1`, `num_predict 64`, `temperature 0.1`, `num_ctx 512`, `num_thread 3` | 3 s timeout |
| Voice, brain → `llama-server` | OpenAI `POST /chat/completions` with API key | 60 s for vision |
| Voice → `spider-stt` | `POST /stt?rate=16000`, raw PCM, bearer token | 6 s |

### Router output schema

```json
{"type":"object",
 "properties":{"act":{"type":"string","enum":["forward","back","left","right","stop","look","none"]},
               "say":{"type":"string","maxLength":90}},
 "required":["act","say"]}
```

## 3.5 Software interfaces

`STT.transcribe(pcm16, rate)`, `TTS.synthesize(text)`, `Router.route(transcript)`, `Vision.ask(jpeg,
question)`, `Answerer.answer(question)`, `AudioOut.play(chunks, rate)`, and `AudioOut.cut()`. Each is
in `voice/src/spider_voice/interfaces.py`. Body-side: `ServoBank`, `LidarSource`, `Camera`, `Kick`.

## 3.6 Versioning and compatibility

The gateway is the compatibility boundary.

- `PROTOCOL_VERSION = 3`. `MIN_SOURCE_PROTOCOL = 2`.
- A source may send any version from 2 to 3. The gateway always re-emits 3 to the body. The body
  rejects anything else.
- Body and gateway deploy together, on the Pi.
- **Upgrade order: Pi first, then server.** A v2 brain keeps working against a v3 gateway, except that
  it cannot release an E-stop, which fails safe. A v3 brain cannot talk to a v2 gateway, because the
  v2 parser forbids the new `trace` field.
- **Additive** (no bump): a new optional field on telemetry; a new optional field on a command, as
  long as both ends of that hop are upgraded together; a new event kind. Receivers log and ignore what
  they cannot parse.
- **Breaking** (bump): removing a field, changing a field's meaning or unit, changing a default that
  affects motion.
- The range the gateway accepts widens only for one version: when `PROTOCOL_VERSION` goes to 4,
  `MIN_SOURCE_PROTOCOL` becomes 3.
- A `RobotState` with a different `v` is not acted on by the brain (`robot_client.py:124-127`).
