# 8. Observability

Sized for one robot: structured logs, a few metrics in existing telemetry, one page. No Prometheus or
tracing backend; their memory cost on this hardware buys nothing at this scale.

## 8.1 Structured logs

Every service uses `spider_common.obs.setup_logging`: one JSON object per line to journald. Fields:
`ts`, `level`, `logger`, `msg`, plus any `extra={"fields": {...}}`.

On the Pi the journal is volatile and capped at 64 MB (`infra/pi/journald-spider.conf`), so routine
logging cannot stall on SD card writes. Anything worth keeping goes to the server over MQTT.

The control loop logs only on state changes, and rate-limited emissions already exist in
`robot.py:246-248,268-270`.

## 8.2 Correlation

`trace` starts when an utterance is dispatched (or a task begins), and follows it:

```
VoiceTurn.trace -> Move.trace -> gateway forwards unchanged -> RobotEvent.trace on ack, move_done,
obstacle_stop, snapshot_ok
```

To follow one utterance: `journalctl -u 'spider-*' -o cat | grep <trace>`. The planner path carries
`trace` when set by the caller; adding one per planner task is a small later step, not in this patch.

## 8.3 Metrics

| Source | Metric | Where |
|---|---|---|
| Body | `loop_overruns`, `loop_max_ms`, `loop_late_max_ms`, `loop_late_p99_ms`, `rt_ok` | `RobotState`, 4 Hz |
| Body | Full lateness and duration histograms | `--jitter-seconds` |
| Gateway | Owner, per-source alive, age, `excess_delay_ms`, `forwarded`, `rejected`, `stale_dropped` | `gw/status`, 1 Hz, retained |
| Voice | Per-utterance `stt_ms`, `route_ms`, `tts_first_ms`, `total_ms`, route, reason | `voice/turn` |
| Voice | Histograms, turns, failures | `health/voice`, every 5 s |
| Camera | Frames, failures, last duration | `health/camera` |
| Pi | Temperature, throttling flags, free memory, free disk | `health/system` |
| Brain | Rolling p50, p95, and the last 20 turns | `Telemetry`, `/telemetry` |

## 8.4 Health model

Each service reports `ok`, `degraded` or `down`. Retained, with a last will, so a dead service reads
as `down` rather than as silence. The gateway reports `online`.

| Robot-level state | Definition |
|---|---|
| **Safe to walk** | Body running, `rt_ok`, LiDAR and IMU fresh, no E-stop, gateway online, system not `down` |
| **Voice ready** | `health/voice` is `ok` and the gateway is online |
| **Remote ready** | Brain sees telemetry under 1.5 s old, gateway online |
| **Degraded** | Any service `degraded`, or cloud or server unreachable. The robot still works |

## 8.5 Alerts

Sent by the existing Telegram and WhatsApp channels. Limited to what needs a person:

| Alert | Trigger | Rate limit |
|---|---|---|
| Fell over | `fallen` event | 10 s |
| E-stop latched | `estop` event | 10 s |
| Obstacle, tilt, link lost | Events | 10 s |
| Pi undervoltage, throttling, overheating | `health/system` `down` or `degraded` | 10 s |
| Service down | `health/<service>` `down` | 10 s |
| Robot offline | `offline` event | 10 s |
| Control loop in trouble | `rt_ok` false, or overruns rising | Dashboard; not yet alerted |
| AWS budget at 80% | AWS Budgets e-mail | AWS |

A health alert fires only when a service's level changes, so a service that stays degraded does not
send a message every 10 s. WhatsApp alerts use their own list (`service.py:38`) and do not carry
health alerts in this patch.

## 8.6 Latency dashboard

The existing dashboard gains two panels (`supervision/static/index.html`), refreshed every 3 s from
`/telemetry` using the run token:

- **Services:** one pill per service, green, amber or red.
- **Voice latency:** p50 and p95 for STT, router and total, and the last five turns with their route.

The control-loop numbers are already in the robot state panel.
