# 5. Failure analysis (FMEA)

Severity S: 1 nuisance, 2 feature lost, 3 uncontrolled motion or damage possible. Automated tests named here are in `code.patch` and pass in simulation [V]. FI tests are hardware or integration tests from `PLAN_09_testing.md` and have not run.

## Network

| ID | Failure | S | Detection | Automatic response | Recovery | Proof |
|---|---|---|---|---|---|---|
| N-1 | Home Wi-Fi down | 2 | Paho disconnect at the brain; `tailscale_path: none` | Pi keeps working on loopback. Remote Move ends in ≤1.5 s. Server STT times out to local | On reconnect | FI-6, FI-7 |
| N-2 | Internet down, LAN up | 1 | Cloud call errors | Local models answer; Telegram stops | Automatic | FI-7 |
| N-3 | Tailscale relayed | 1 | `tailscale_path: relay`; queue delay rises | Works if stable; Moves over 400 ms late refused | Back to direct by itself | FI-7 |
| N-4 | Link stalls 2 s then bursts | 3 | Source age over 1.5 s; queue delay | Owner lost, Stop sent. Burst of old Moves refused | Owner re-issues | `test_move_stuck_in_a_network_queue_is_refused`, FI-7 |
| N-5 | Partition during remote walk | 3 | Source timeout | Stop within 1.75 s; `link_lost` event to the source | Reconnect, new command | `test_simulated_body_stops_when_remote_source_disappears` |
| N-6 | Partition mid-confirmation | 1 | Challenge expiry, 30 s | E-stop stays latched | Ask again | `test_challenge_expires` |
| N-7 | Clock skew between Pi and server | 2 | Base one-way delay on status | No effect: gateway restamps | - | `test_forwarded_commands_carry_the_pi_clock` |
| N-8 | Source clock jumps forward or back | 2 | Queue delay spike | Moves refused until the window passes; fails safe | Automatic ≤30 s | `test_delay_tracker_*`, FI-8 |
| N-9 | Pi boots with no RTC and no network | 2 | Wall clock old | Local works: all local parties share one clock, and loopback login needs no certificate | Chrony syncs later | B-F1 |
| N-10 | Certificate expired or clock wrong on the remote listener | 2 | TLS failure in brain log, alert | Remote lost, local unaffected | Rotate, §7.4 | FI-14 |

## Process crashes

| ID | Failure | S | Detection | Automatic response | Recovery | Proof |
|---|---|---|---|---|---|---|
| P-1 | Gateway dies | 3 | Body heartbeat stops | Body stops in ≤1.5 s | systemd ≤1 s; new session | FI-2 |
| P-2 | Broker dies | 3 | All links drop | Body stops in ≤1.5 s; no replay (`persistence false`) | systemd 1 s; reconnect ≤2 s | FI-5 |
| P-3 | Body dies or hangs | 3 | Watchdog at 1 s; `offline` will message | Process killed. Servos keep last pulses, so the robot holds its pose. On restart they are set limp | ≤15 s; a person must re-stand it | FI-1 |
| P-4 | Bridge dies | 3 | `lidar_age` over 0.5 s; IMU stale over 0.3 s | Motion refused | systemd 2 s | FI-9 |
| P-5 | Voice dies | 2 | Heartbeat stops | If it owned a Move, Stop; others unaffected | systemd 2 s | FI-3 |
| P-6 | Ollama dies or is slow | 1 | HTTP error or 10 s timeout | Grammar still works; router failure spoken | systemd | `test_router_failure_is_spoken_and_harmless`, FI-12 |
| P-7 | STT model fails | 2 | Exception | Fallback adapter, else trace `error` and no motion | - | `test_both_stt_failing_*` |
| P-8 | TTS fails | 1 | Exception | espeak-ng | - | `test_tts_failure_falls_back_to_espeak` |
| P-9 | Brain dies during a walk | 3 | Source timeout | Stop in 1.75 s | systemd 5 s | FI-6 |
| P-10 | Router outputs garbage | 2 | Parse failure | `none`, no motion | - | `test_garbage_output_means_no_action` |
| P-11 | Vision or NIM hangs | 1 | Deadline | Reply `ok=false`, spoken apology | - | `test_ask_reports_failure_*` |

## Sensors and actuators

| ID | Failure | S | Detection | Automatic response | Recovery | Proof |
|---|---|---|---|---|---|---|
| H-1 | L2 loses power | 3 | Cloud and IMU stale | Stop; motion refused | Reconnect | FI-9 |
| H-2 | L2 cloud gaps | 2 | Per-sector hit rate | Nearest return kept over 3 clouds | - | `test_sector_map_*`, B2 |
| H-3 | IMU silent, cloud alive | 3 | IMU age over 0.3 s | Tilt unknown blocks motion | Automatic | FI-10 |
| H-4 | SSC-32U USB drops | 3 | Serial exception | After 25 failed ticks: relax attempt, process exits and restarts | Reconnect | FI-11 |
| H-5 | Servo stalls or overheats | 3 | Not detected: the SSC-32U has no feedback | Mitigated by caps and short Moves; **residual risk** | Inspect | B6 |
| H-6 | Camera fails | 1 | Snapshot exception | `snapshot_failed`; release is impossible without a frame | Replug | `test_snapshot_failure_reaches_the_requester`, FI-15 |
| H-7 | Mic fails or is noisy | 2 | No frames; `pre_stops` rate | Voice inert; remote and physical stop remain | Replug | B-V4 |
| H-8 | Fall past 55° | 3 | IMU | Servos limp; only voice, or remote with a frame, can wake it | Person rights it | FI-13 |
| H-9 | False obstacle from a leg | 1 | Footprint filter | Motion stops | Tune | B5 |

## Compute, power and storage

| ID | Failure | S | Detection | Automatic response | Recovery | Proof |
|---|---|---|---|---|---|---|
| R-1 | Thermal throttle at 80 °C | 2 | `throttled_hex`, temperature | Alert. Loop keeps running, slower. Requires active cooling | Stop voice load | B3 |
| R-2 | Under-voltage from servo surge | 3 | Bit 0 of `get_throttled` | Alert. Separate regulator is the actual fix | Wiring | B4 |
| R-3 | Control loop overruns | 2 | `loop_late_hist`, `loop_overruns` | Alert at over 40 ms. Move up the ladder | L1 to L3 | B1 |
| R-4 | Memory pressure | 2 | `MemAvailable` | cgroup limits, then OOM order kills Ollama first | Restart | FI-16 |
| R-5 | Disk full | 2 | Health under 1 GB | Recorder stops itself at 1 GB free; logs are in RAM | Copy off | `test_recorder_stops_when_the_disk_is_nearly_full` |
| R-6 | SD card corruption after power cut | 3 | Boot failure | Logs and broker write nothing in normal use | Re-image; keep a spare card | B-F2 |
| R-7 | Battery runs out | 2 | Not measured today | Under-voltage alert only; robot sits on a falling rail | Fit a voltage monitor before unattended use | Open item |
| R-8 | Restart while standing | 3 | - | Limp at startup | Person re-stands it | `run()` in `main.py`, FI-1 |

## Logic

| ID | Failure | S | Detection | Automatic response | Recovery | Proof |
|---|---|---|---|---|---|---|
| L-1 | Stop undone by a renewal | 3 | Was silent | Hold-off and `preempted` | - | `test_voice_stop_ends_a_planner_walk_for_good` |
| L-2 | Late Move overtakes a Stop | 3 | Sequence fence | Dropped | - | `test_late_move_*` |
| L-3 | Robot hears itself | 2 | Deaf flag | Stop words only | - | `test_own_voice_cannot_command`, `test_speech_that_began_during_playback_*` |
| L-4 | Background speech moves it | 3 | Attention | Refused without wake word | - | `test_background_speech_never_moves_the_robot` |
| L-5 | "Don't walk" taken as "walk" | 3 | Negation guard | Goes to the router | - | `test_negated_motion_is_not_a_command` |
| L-6 | Text in a camera image commands motion | 3 | Structural | `AskReply` cannot act | - | `test_answer_from_vision_is_only_spoken` |
| L-7 | Failed snapshot leaves a confirmation pending | 1 | Event | Requester told | - | `test_snapshot_failure_reaches_the_requester` |
