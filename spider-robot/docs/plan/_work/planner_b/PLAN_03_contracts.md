# 3. Contracts

`spider_common.protocol` is the single source of every schema. Prefix: `spider/<robot_id>/`.

## 3.1 Topics

| Topic | Direction | Payload | QoS | Retain | Rate | Timeout and consumer behaviour |
|---|---|---|---|---|---|---|
| `cmd` | gateway -> body | `Command` | Move and heartbeat 0; others 1 | no | Heartbeat 4 Hz; Move on demand | Body stops after `link_timeout_s` 1.5 s while moving; rejects commands older than 1.0 s (Stop and E-stop never) |
| `state` | body -> all | `RobotState` | 0 | no | 4 Hz (0.2 Hz when idle and relaxed) | Readers treat over 1.5 s as stale |
| `event` | body -> gateway | `RobotEvent` | 1 | no | On event | - |
| `camera/<rid>` | body -> all | JPEG ≤ 120 KB | 1 | no | On request | Requester timeout 8-10 s |
| `gw/<source>/cmd` | voice, remote, planner -> gateway | `Command` | Move, heartbeat 0; others 1 | no | Heartbeat 2-4 Hz | Source timeout 1.5 s |
| `gw/<source>/event` | gateway -> source | `RobotEvent`, source's own seq | 1 | no | On event | - |
| `gw/status` | gateway -> all | `GatewayStatus` | 1 | **yes** | 1 Hz | A new subscriber sees the last status at once |
| `voice/trace` | voice -> brain | `VoiceTrace` | 0 | no | Per utterance | Best effort |
| `rpc/ask/req` | voice -> brain | `AskRequest` | 1 | no | Per escalation | Voice waits 45 s, then speaks "ما قدرت أجيب" |
| `rpc/ask/res/voice` | brain -> voice | `AskReply` | 1 | no | - | Unknown `cid` is ignored |
| `rpc/stt/req` | voice -> brain | `SttRequest`, up to 400 KB base64 | 1 | no | Per utterance | Voice waits 4 s, then falls back |
| `rpc/stt/res/voice` | brain -> voice | `SttReply` | 1 | no | - | Unknown `cid` is ignored |
| `health` | each node -> brain | `HealthReport` | 0 | no | 0.1 Hz | Missing for 60 s shows as stale |
| `record/cmd` | brain -> recorder | `RecordCommand` | 1 | no | On request | - |
| `record/status` | recorder -> brain | `RecordStatus` | 1 | no | On change | - |

ZeroMQ, Pi only: `ipc:///tmp/spider_lidar.ipc`, topics `cloud`, `imu` (about 50 Hz average), `rawcloud` (n*6 floats), `rawimu`. The body subscribes to `cloud` and `imu` by name, so raw topics are dropped at the publisher.

## 3.2 Commands

Common fields: `v`, `session` (≤64), `seq`, `ts`, `cid` (≤32). Unknown fields are rejected.

| Type | Fields | Body limits, then source caps |
|---|---|---|
| `move` | `vx`, `vy` within ±0.5, `wz` within ±2.0, `duration_s` in (0,10], `gait` | Body: max 0.12/0.08 m/s, 0.6 rad/s. Voice 0.10 m/s, 0.6 rad/s, 3.0 s. Remote and planner 0.06 m/s, 0.4 rad/s, 1.5 s |
| `stop` | - | Always passes; hold-off 2 s on equal or lower sources |
| `estop` | - | Always passes; latched in body |
| `estop_release` | `challenge`, `frame_sha256` | Remote only, with a valid challenge |
| `posture` | `posture`, optional `challenge`, `frame_sha256` | Waking from limp: voice yes, remote with a challenge, planner never |
| `body_pose` | `height_m`, `roll_deg`, `pitch_deg`, `yaw_deg` | Priority applies |
| `snapshot` | `request_id` | Passes |
| `heartbeat` | - | Valid heartbeats keep a source alive |
| `confirm_request` | `action`, `request_id` | Remote only. Consumed by the gateway, never forwarded |

## 3.3 Telemetry and events

`RobotState` adds `loop_late_max_ms` and `loop_late_hist` (six cumulative buckets: <1, <2, <5, <10, <20, ≥20 ms).

`RobotEvent.kind`: `ack`, `rejected`, `obstacle_stop`, `tilt`, `fallen`, `link_lost`, `estop`, `move_done`, `online`, `offline`, `error`, `snapshot_failed`, `preempted`, `challenge`. The model field is a plain string so that older readers tolerate new kinds.

Routing: `ack`, `rejected`, `move_done`, `snapshot_failed` go only to the source that sent the command, with its own seq. Everything else reaches every source.

## 3.4 Rules the gateway applies, in order

1. Unknown source: ignored. Invalid payload: `rejected`, and does **not** count as a sign of life.
2. Record the queue-delay sample. Heartbeat ends here.
3. Stop or E-stop: fence, clear owner, start hold-off, forward, tell the displaced owner.
4. Move: drop if fenced; refuse if held off; refuse if queue delay over 400 ms; apply caps; claim by priority; forward.
5. Posture: apply the wake rule; claim; forward.
6. Everything forwarded is renumbered and stamped with the Pi's clock.

## 3.5 Swappable interfaces

```python
class SpeechToText(Protocol):
    name: str
    async def transcribe(self, pcm: bytes, rate: int, cid: str) -> Transcript: ...

class TextToSpeech(Protocol):
    name: str; rate: int
    def stream(self, text: str) -> AsyncIterator[bytes]: ...

class Router(Protocol):
    name: str
    async def decide(self, text: str, on_act: Callable[[str], None] | None = None) -> Decision: ...
```

Vision and text on the server keep the existing shape: `async ask(...) -> str`. Routes are strings: `liquid`, `anthropic:<model>`, `compat:<model>`.

| Move | Change |
|---|---|
| STT to the server first | `stt.primary` in `voice.yaml` |
| Vision to another machine | `SB_VISION_URL` |
| Add cloud escalation | `SB_ASK_FALLBACK`, `SB_VISION_FALLBACK`, `SB_COMPAT_BASE_URL` |
| GPU server | `SB_STT_DEVICE=cuda`, `-ngl 99` in the two llama units |
| Router on another machine | `router.url` in `voice.yaml` |

## 3.6 Router contract

JSON schema, `format` field of `/api/chat`: `act` enum of `forward, back, left, right, stop, look, ask, none`; `say` string, `maxLength` 60. Options: temperature 0.1 (config refuses outside 0.1-0.2), `num_predict` 80, `num_thread` 3, `keep_alive` -1. Output that does not parse means `none`. Prompt is 64 tokens [V, real tokenizer].

Whether Ollama passes `maxLength` through to its grammar is **unverified**. Check in bench B-V2; if it does not, the reply can be cut at `num_predict`, and the early `act` still works.

## 3.7 Versioning and Pi-server compatibility

`PROTOCOL_VERSION` stays 2 because every change above is additive.

| Rule | Detail |
|---|---|
| R1 Additive only within a version | New fields have defaults. Tested: `test_commands_from_the_previous_build_still_parse` |
| R2 Update the Pi first | A new Pi accepts an old brain. An old Pi rejects the new `cid` field, because commands forbid unknown fields |
| R3 Tolerant readers | Unknown event kinds and state fields are ignored. Tested |
| R4 Strict writers | Commands reject unknown fields, so a typo cannot silently do nothing |
| R5 Bump only when incompatible | Removing or re-typing a field, or changing a unit. The body already rejects other versions (`robot.py:113-116`) |
| R6 During a major bump | The Pi and the server are updated in the same maintenance window, robot sitting |
| R7 Pi-internal contract | Body, gateway and voice ship together from one release directory |
