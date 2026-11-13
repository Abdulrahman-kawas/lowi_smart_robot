# 5. Failure analysis

"Test" names a unit test that exists in `code.patch`, or a bench or fault test from
`PLAN_09_testing.md`. Unit tests ran on simulated hardware; bench tests have not run.

## 5.1 What runs where when one thing fails

| Failed alone | Body, reflexes | Voice Stop | Voice motion | Telegram, dashboard | SSH | Vision, hard questions |
|---|---|---|---|---|---|---|
| Home server | ✓ | ✓ | ✓ | ✗ | ✓ | Spoken failure; cloud if configured on the Pi |
| Wi-Fi | ✓ | ✓ | ✓ | ✗ | ✗ | Spoken failure |
| Internet only | ✓ | ✓ | ✓ | Dashboard on LAN or tailnet if direct; Telegram ✗ | ✓ on LAN | Server ✓; cloud ✗ |
| Gateway | Stops ≤ 1.5 s after the last heartbeat | ✗ until restart (≤ 3 s) | ✗ | ✗ commands | ✓ | n/a |
| Broker | Stops ≤ 1.5 s after the last heartbeat | ✗ until restart (≤ 5 s) | ✗ | ✗ | ✓ | n/a |
| `spider-voice` | ✓ | ✗ until restart | ✗ | ✓ | ✓ | Brain only |
| Ollama | ✓ | ✓ | Grammar ✓; free-form says it failed | ✓ | ✓ | ✓ |
| `spider-body` | Servos hold pose; systemd restarts in ≈ 4 s | ✗ | ✗ | Telemetry stale | ✓ | ✓ |

Physical E-stop works in every row: it does not depend on software.

## 5.2 FMEA

### Network

| ID | Failure | Detection | Automatic response | Recovery | Test |
|---|---|---|---|---|---|
| N1 | Wi-Fi lost while walking under voice | None needed | Voice Moves expire by themselves; voice path is entirely local | Automatic | NET3 |
| N2 | Wi-Fi lost while walking under remote | Gateway sees no heartbeat from remote | Move expires ≤ 1.0 s; gateway issues Stop at ≤ 1.75 s, `link_lost` to source | Owner re-issues | `test_lost_owner_stops_robot_*`, NET2 |
| N3 | Tailscale falls back to relay | `tailscale status`; gateway `excess_delay_ms` | Commands continue; caps bound motion | Automatic upgrade to direct | NET2 |
| N4 | TCP stall, backlog delivered in a burst | Gateway `SourceClock` excess delay | Late Moves refused; late heartbeats ignored; Stops pass | Automatic | `test_late_*` |
| N5 | Internet down, LAN up | Cloud timeouts | Cloud answers fail, spoken message; server and Pi fine | Automatic | NET4 |
| N6 | Asymmetric partition: commands arrive, telemetry does not | Brain telemetry stale after 1.5 s | Brain ends the motion (`robot_client.py:278-281`) | Automatic | Existing brain tests, NET2 |

### Processes

| ID | Failure | Detection | Automatic response | Recovery | Test |
|---|---|---|---|---|---|
| P1 | `spider-body` crashes while walking | systemd | SSC-32U holds last pose. Restart in 3 s, starts by cutting pulses (D10 fix) | Owner stands it again | `test_control_process_*`, FI1 |
| P2 | `spider-body` hangs | `WatchdogSec=1` | systemd kills and restarts it | As P1 | FI2 |
| P3 | `spider-body` hangs and systemd is dead too | Hardware watchdog line stops toggling | Relay board cuts servo power at ≥ 200 ms | Power cycle | `test_kick_*`, HW3 |
| P4 | Control tick raises | `MAX_TICK_ERRORS` | Relaxes after 0.5 s of consecutive failures, process exits, restarts | systemd | Existing, FI1 |
| P5 | `lidar_bridge` dies | LiDAR data ages past 0.5 s, IMU past 0.3 s | No motion (`lidar_stale`, `imu_stale`) | systemd in 2 s | `test_stale_lidar_blocks_motion`, FI3 |
| P6 | Gateway dies | No heartbeats reach the body | Body stops at 1.5 s; last will publishes offline status | systemd in 1 s | `test_simulated_body_*`, FI4 |
| P7 | Broker dies | Clients disconnect | Body stops at 1.5 s | systemd; clients reconnect | FI5 |
| P8 | `spider-voice` dies | Last will on health topic | Other sources unaffected; gateway stops its motion if it owned any | systemd in 2 s | FI6 |
| P9 | Ollama hangs | 3 s HTTP timeout | Speaks failure; no motion | Next utterance retries | `test_router_failure_*`, FI7 |
| P10 | Whisper hangs | 8 s timeout | Turn recorded as failed; next utterance can run on the second worker | systemd if the pool is exhausted | `test_stt_failure_*`, FI7 |
| P11 | `spider-camera` dies | Last will | `snapshot_failed` or timeout; release is blocked (no frame) | systemd in 2 s | `test_camera_service_*` |
| P12 | Brain dies during a walk | Gateway sees heartbeats stop | As N2 | systemd | Brain tests, FI8 |
| P13 | Recorder dies mid-job | Job never reports `finished` | The file is readable to its last whole frame | Owner restarts the job | `test_a_truncated_file_*` |
| P14 | Out of memory on the Pi | `MemoryMax`; `spider-sysmon` free memory | The offending service is killed and restarted; the control process's memory is locked and it has its own limit | systemd | S2 soak |

### Sensors and actuators

| ID | Failure | Detection | Automatic response | Recovery | Test |
|---|---|---|---|---|---|
| S1 | LiDAR stops sending clouds | Age > 0.5 s | No translation or turn | Automatic | Existing, FI3 |
| S2 | IMU silent or disabled | Tilt age > 0.3 s | No motion; `stand` refused from relaxed (D19 path) | Provisioning step sets the work mode | `test_stand_is_refused_*`, HW1 |
| S3 | Partial LiDAR sweep | Handled by design | Per-sector hold (D1 fix) | n/a | `test_sector_*`, HW1 |
| S4 | LiDAR warming up | Same as S1; manual says no clouds until warm below 30 °C **[S]** | No motion until data flows | Automatic | HW1 |
| S5 | Low obstacle or drop not visible | Not detectable by software | **None.** See H-02 | Mechanical change | HW1 |
| S6 | Microphone fails | `arecord` exits, capture task ends the process | systemd restart loop; health down | Fix the device | FI6 |
| S7 | Camera fails | `snapshot_failed` | Spoken failure | Automatic on return | Test above |
| A1 | USB to SSC-32U unplugged | `SerialException` on write | Relax attempted; exit after 25 failed ticks; restart loop. The SSC holds its last pulses | Replug | FI9 |
| A2 | USB stalls | `out_waiting` high; 10 ms write timeout | Frame skipped | Automatic | `test_ssc_skips_a_frame_*` |
| A3 | Servo stalled or overheating | **Not detected.** SSC-32U has no current feedback | Fuse. Hardware E-stop | Inspect | HW4, residual risk |
| A4 | Servo power brown-out | Mechanically visible; no sensor | Physical; Pi on a separate BEC | Battery | HW4 |
| A5 | Servo ignores loss of signal | Bench | Software "relax" may not remove torque. **Only the power cut is reliable** | n/a | HW2 |

### Clocks

| ID | Failure | Detection | Automatic response | Recovery | Test |
|---|---|---|---|---|---|
| C1 | Pi clock wrong at boot, no RTC | Irrelevant to the local path: all stamps come from one clock | Nothing depends on it | chrony | `test_a_constant_clock_offset_*` |
| C2 | Server clock skewed | Gateway measures offset | Minimum-delay filter cancels it | n/a | Same |
| C3 | Clock step on either side | Consistent lateness for 3 s | Refused until the window restarts, then normal | Automatic in 3 s | `test_clock_step_*` |

### Power and thermal

| ID | Failure | Detection | Automatic response | Recovery | Test |
|---|---|---|---|---|---|
| T1 | Pi undervoltage | `spider-sysmon` reads firmware flags | Health `down`; alert to owner | Fix supply | `test_levels`, HW5 |
| T2 | Thermal throttling | Same, plus temperature | Health `down` at 80 °C; alert. AI gets slower; Core 0 budget has headroom, tested in RT1 under load | Cooling | HW5 |
| T3 | Battery low | **No sensor in this design** | Hardware low-voltage alarm, fitted at M4 | Recharge | HW4, residual risk |
| T4 | Servo supply lost suddenly | None | Robot sinks to its belly. Software sees nothing | Restore; relaxes on next process start | HW2 |
| T5 | Power loss during E-stop latch write | Latch is written with fsync, then renamed | Old value or new value, never a torn file | n/a | `test_latch_*` |
| T6 | SD card failure | Filesystem errors, sysmon free disk | Logs are volatile, so normal running barely writes to it | Replace; reinstall from `setup_pi.sh` | Runbook |

### Decisions and input

| ID | Failure | Detection | Automatic response | Recovery | Test |
|---|---|---|---|---|---|
| D1 | False stop word from noise | `VoiceTurn` | Robot stops; safe | Re-issue | V2 measures the rate |
| D2 | False motion from background speech | Wake gate, confidence gate | Ignored | n/a | `test_background_speech_*`, V2 |
| D3 | LLM returns garbage or invents motion | Parser; `cross_check` | `none` | n/a | `test_anything_unparsable_*`, `test_router_cannot_invent_*` |
| D4 | Robot hears itself | Echo gate | Dropped unless clearly louder; then only stop words | n/a | `test_own_voice_*`, V3 |
| D5 | Instruction written in the camera's view | Vision answers are spoken only | Stop words are stripped from the speech | n/a | `test_vision_answer_*` |
| D6 | Remote release with an old frame | Gateway check | Refused | New `/release` | `test_remote_release_*` |
| D7 | Restart during E-stop | Persistent latch | Stays latched; no servo output until released | Release | `test_latch_survives_*` |
| D8 | Service restart under E-stop | `sit_and_relax` returns at once | No motion | n/a | `test_shutdown_under_estop_*` |
