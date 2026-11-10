# Status of the judge's required changes, after the merge

Lead's record for judge round 2. "Test" names a test in the merged code, which ran on a fresh copy.
Hardware checks are written into the plan as gates and have not run.

| ID | How it was closed | Proof |
|---|---|---|
| R-01 | Body base A: `_hold_ramps`, ramp freeze in `tick`, `EStopLatch`, `_cold_estop`, guarded `sit_and_relax` | A's three named tests pass |
| R-02 | `spider-button` (`gateway/button.py`, new source `button`, `spider-button.service`, ACL user, GPIO 27). Gateway `_on_button` accepts only `estop_release`, refuses stale presses and any time a source owns the robot. Voice release stays forbidden. Limitation before M4 stated in design section 6.6 and the runbook | `test_button.py`; `test_button_*` in `test_gateway_policy.py`; gate B-E1 in M4 |
| R-03 | `pipeline._dispatch` and `_schedule`: shorts FIFO on all workers, bounded at 8; a long utterance never takes the last free worker, newest long waits. `Utterance.ended_at`, `_too_old`, `max_motion_age_s` 6.0, Stop exempt | `test_a_stop_among_many_segments_*`, `test_the_backlog_is_bounded_*`, `test_a_motion_older_*`, `test_a_stop_is_never_too_old` |
| R-04 | Gateway base B with rank hold-off, `preempted`, single-use `challenge`. A's fence and frame bookkeeping removed | B's named tests; `test_planner_stop_does_not_block_voice`, `test_a_planner_stop_cannot_undo_a_voice_stop`, `test_planner_move_soon_after_*`, `test_one_frame_cannot_release_two_estops` (A1-A4 as unit tests) |
| R-05 | B's two listeners and per-process passwords. Merged ACL covers every client including `spider-button` | `test_acl_contract.py`; gate NET5 at M2 with the clock at 2000-01-01 |
| R-06 | `min_gap = interval * 0.76` with A's `out_waiting` skip. Staged wake, ramps held until every leg on | `test_ssc_keeps_25_hz_under_tick_jitter`, `test_legs_wake_one_at_a_time_and_height_holds_*`, `test_estop_during_wake_*`; gate B1 |
| R-07 | Commissioning P05 (IMU bit, explicit NEGA choice, verify), H-02 and operating rule, warm-up in FMEA S4 and runbook | Gate HW1 at M2 |
| R-08 | Streaming `OllamaRouter`, `maxLength` 60, `num_predict` 80, `timeout_s` 10, `num_ctx` 512. `cross_check` before early act and on the final act | `test_a_stream_naming_a_motion_*`, `test_ollama_*`; gate S1 |
| R-09 | Grammar before escalation, re-check stop words on better text. `RpcStt` breaker 30 s. `WhisperLocalSTT` loads in the constructor; `prepare()` warms router and renders phrases | `test_a_grammar_hit_at_low_confidence_*`, `test_a_hanging_server_costs_only_one_timeout`, `test_whisper_loads_once_when_constructed`, `test_prepare_*`; gate B-F1 |
| R-10 | One `protocol.py`, v3, range 2-3, `trace`, `kind` string, challenge fields, RPC messages. `cid` renamed to `trace` throughout | `test_protocol.py`, `test_contract.py`, `test_v2_source_is_accepted_and_reissued_as_v3` |
| R-11 | Design sections 1.2, 4.6, 12 and report restated: local STT [E] 3-8 s, offline Stop [E] 3.3-8.3 s, online [E] 1.3-2.4 s, WER 63.4% and 90.9% | Text |
| R-12 | Removed from body, lidar, gateway, voice, button units. Mosquitto and Ollama replaced as whole units, because a drop-in cannot remove packaged dependencies | `grep` in S08 and S12; gate B-F1 |
| R-13 | `test_startup_relaxes_servos_before_the_first_tick`, `test_startup_under_a_latched_estop_does_not_touch_the_servos` | Mutation re-run by the lead: removing `servos.relax()` fails the first test |
| R-14 | One option `stop_on_speech_onset`, default false, B's cooldown and own-speech guard | `test_speech_onset_*`; gate V4 |
| R-15 | A's `policy.py`, `check_order`, YAML override | `test_policy_file_*`, `test_each_source_is_capped` |
| R-16 | `walk_height`, `_at_height`: Moves refused unless at walking height, `relax` unless at sit height | `test_move_refused_at_a_mid_height_*`, `test_relax_refused_above_the_sit_height` |
| R-17 | ADR-11, config comment, B's merge | `test_sector_*`, `test_old_return_ages_out_*`; HW1 histogram |
| R-18 | Budget table uses measured cost, `IMU_DECIMATE=10`, `NOBLOCK` first rung, `NO_HZ_FULL` statement | Section 4.1, ADR-02, RT1 |
| R-19 | `set_gil_interval`, `LimitRTTIME`, RT1 runs FIFO off then on | `test_gil_interval_is_set_from_config`; P06 |
| R-20 | `arecord --period-time=20000 --buffer-time=80000`. UVC stream left open and the interrupt rate measured in RT1 | P06 |
| R-21 | Low-disk stop; `write_failed` raises an `error` event | `test_recording_stops_when_the_disk_is_nearly_full`, `test_latch_write_failure_*` |
| R-22 | Remote topic present and the set is a subset | `test_robot_source.py` |
| R-23 | Ollama 0.40.15, llama.cpp v0.9.0 | `setup_pi.sh`, `setup_server.sh` |
| R-24 | Added to V1 | Section 9.3 |
| R-25 | B's `_speaking` not kept; A's lock | Reading |

## Changes the lead made beyond the list, with reasons

| Change | Reason |
|---|---|
| `cross_check` also refuses a negated motion | The grammar's negation guard alone would let "don't walk forward" pass through the router |
| `امشي`, `تقدم`, `ارجع` added to the lexicon | Without them the common word for "walk" could never pass the cross-check |
| A long utterance waits in a one-slot pending position instead of being ignored | R-03: dropping one could lose a stop word inside a long utterance |
| `stt.primary: whisper_server` and `ServerFirstSTT` | The judge's B P1 ruling allows this swap after B-V1. It needs code to exist |
| `HealthReport.info` | Carries the Tailscale path and failed units that A's report had no field for |
| `drain()` yields once per loop | It spun forever on Python 3.13, when a finished task was still in the set |
| Execution plan uses `apply_step.py` with SHA-256 | Removes transcription errors by a low-cost executor; the full text remains in the plan |
| No server health reporter | The judge said to drop B's `health` module and port parsers to `sysmon`, which runs on the Pi. Stated in design section 8 |

## Known limits of the merge

- `test_remote_release.py` from A is not kept: its flow no longer exists, and the challenge tests cover it.
- Tailscale ACL is in the design only; the owner applies it in the admin console.
- `spider-brain` does not set `trace` on planner commands (the field exists and is optional).
