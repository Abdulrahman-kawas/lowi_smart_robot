# 8. Observability

Sized for one robot and one person: JSON lines, one retained status, a page on the existing dashboard, and a handful of alerts. No metrics database.

## 8.1 Structured logs

`spider_common.telemetry.setup_logging(service)` writes one JSON object per line to stderr, and journald collects it. Fields: `ts`, `lvl`, `svc`, `log`, `msg`, plus any `extra`, including `cid`.

```bash
journalctl -u spider-voice -o cat | jq 'select(.cid=="abc123")'
```

On the Pi, journald is RAM-only with a 64 MB cap, to protect the SD card and avoid write stalls. Crash context survives until reboot. On the server, journald persists.

## 8.2 Correlation from utterance to motion

```
SpeechStart: voice creates cid
  -> VoiceTrace.cid (voice/trace)
  -> command.cid (gw/voice/cmd)
  -> gateway forwards it on cmd, so the body sees the same cid
  -> AskRequest.cid and SttRequest.cid
  -> worker logs extra={"cid": ...}
```

The body's events carry a seq, and the gateway maps that seq to the source and its command.

## 8.3 Metrics

| Source | Signal | Where it appears |
|---|---|---|
| Body | `loop_late_max_ms`, `loop_late_hist`, `loop_overruns`, `loop_max_ms`, `lidar_age_s`, `limiter`, mode | `state` at 4 Hz |
| Gateway | Owner, per-source alive, age, queue delay, hold-off, pending challenges; counters `preempted`, `held_off`, `late_move`, `capped`, `busy`, `lost_owner` | `gw/status`, retained, 1 Hz |
| Voice | Stages per utterance in ms from end of speech: `stt`, `command`, `router_first_act`, `router`, `first_audio`; path; provider | `voice/trace` |
| Voice | `pre_stops`, `dropped` | Log |
| Each node | CPU temperature, throttle flags, memory, swap, disk, failed units, Tailscale path | `health` every 10 s |

`loop_late_hist` buckets are cumulative counters, so a soak's percentile can be computed from two readings without keeping every sample.

## 8.4 Health model

| Layer | Healthy when | Source |
|---|---|---|
| Body | `state` under 1.5 s old, `loop_late_max_ms` under 20, `lidar_age_s` under 0.5 | `state` |
| Gateway | `gw/status` under 3 s old | `gw/status` |
| Sources | Each expected source alive | `gw/status` |
| Voice | Alive at the gateway, recent trace when there has been speech | `gw/status`, `voice/trace` |
| Node | No throttle now, temperature under 80 °C, memory over 300 MB, no failed unit | `health` |
| Remote link | `tailscale_path` is direct or peer-relay; queue delay under 200 ms | `health`, `gw/status` |

Overall state on the dashboard: **OK** all healthy; **Degraded** robot safe but something is reduced (server down, relay, thermal warning); **Unsafe to move** body, LiDAR or IMU unhealthy.

## 8.5 Alerts that matter

Sent by Telegram, and by WhatsApp where configured. Anything else is on the dashboard only.

| Alert | Condition | Cooldown |
|---|---|---|
| Robot fell | `fallen` event | 10 s |
| Tilt, obstacle stop, link lost, E-stop | Event | 10 s |
| Offline | Will message | 10 s |
| CPU hot | ≥ 80 °C | 5 min |
| Under-voltage or throttled now | Throttle bits 0-2 | 5 min |
| Memory low | Under 300 MB | 5 min |
| Disk low | Under 1 GB | 5 min |
| Service failed | Failed unit list | 5 min |
| No path to peer | `tailscale_path: none` | 5 min |
| Certificate near expiry | Under 30 days | Weekly (M4) |

Past throttling (bits 16-19) is deliberately not an alert (`test_past_throttle_is_not_an_alert`), or the first boot's history would page forever.

## 8.6 Latency dashboard

The existing dashboard gains three panels through the existing authenticated websocket, so no new route or token exists:

- **Voice latency:** p50, p95 and count per stage over the last 2000 utterances, plus counts per path.
- **Sources:** owner, each source's state, and queue delay.
- **Confirmations:** the frame with Confirm and Cancel.

Traces also go to `voice_traces.jsonl` with one rotation at 10 MB, which is what bench reports are computed from.
