# 12. Architecture decision records

Each records the status, the decision, what was rejected, and the consequence.

## ADR-01 The gateway is the enforcement point for human-safety rules
**Accepted.** Caps, hold-off, source liveness and confirmation live in the gateway on the Pi.
**Alternatives:** in the brain (a compromised brain bypasses them); in the body (mixes source policy into the control loop on Core 0).
**Consequence:** a bad brain release or a stolen Telegram session is still bound by the rules. The gateway is now a real component with real logic, and it is tested as one.

## ADR-02 MQTT is the only channel between Pi and server
**Accepted.** STT and questions travel as request and reply over the broker.
**Alternatives:** HTTP from Pi to server models (a token, a port on the tailnet, and a second failure path); gRPC (a new dependency for two calls).
**Consequence:** no model port is open beyond loopback. STT audio is base64, a third larger, about 43 KB per second, which fits. MQTT is not designed for large payloads, so audio is capped at about 18 s.

## ADR-03 Loopback passwords on the Pi, mutual TLS only for the remote link
**Accepted.** Local clients use `127.0.0.1:1883` with one password each. The brain uses 8883 with a client certificate.
**Alternatives:** mutual TLS for every client (uniform, but a wrong clock or expired certificate would stop local control, against Decision 1); anonymous loopback (no ACL identity, so the "gateway only" rule would be empty).
**Consequence:** the robot works with no network and a wrong clock. Two authentication methods to keep correct, both exercised by `test_acl_contract.py`. Bound to `0.0.0.0` so the broker still starts without `tailscale0`, with nftables doing the restriction.

## ADR-04 Keep Python and asyncio for the control loop, with an escalation ladder
**Accepted for now.** Evidence in `PLAN_00_index.md` Q1.
**Alternatives:** rewrite IK and gait in C++ now (days of work, new bugs in the safest code in the repo, with no evidence yet that it is needed); PREEMPT_RT now (no packaged kernel path for a Pi 4 that I confirmed, and it can make some timing worse).
**Consequence:** the main risk is measured instead of guessed. If B1 fails at every rung, C++ is the answer and costs days.

## ADR-05 Stop on speech onset, before any model
**Accepted.** Any detected speech while moving sends Stop.
**Alternatives:** wait for the transcript (3-8 s offline); a keyword spotter (better precision, but needs training data for Arabic, and is still a model).
**Consequence:** a Stop in about 0.13 s, independent of network. False stops happen from noise and cost only a pause; B-V4 measures the rate, and a config switch turns it off. It adds to Decision 6 and changes nothing in it.

## ADR-06 A deterministic grammar before the LLM
**Accepted.** Common commands match a phrase table.
**Alternatives:** LLM for everything (adds 1-2.5 s and allows hallucinated actions).
**Consequence:** the most common commands are the fastest and most predictable. The table must be extended by hand as the owner's dialect shows gaps.

## ADR-07 STT order decided by a bench, not by guess
**Proposed, see P1.** The code supports both orders in three config lines.

## ADR-08 Wake phrase in the transcript first; a detector later
**Accepted.**
**Alternatives:** openWakeWord now (a real gain in idle CPU, but custom Arabic models need training data I cannot produce here); Porcupine (needs an account-bound access key, which does not suit an offline-first robot).
**Consequence:** every speech segment costs an STT run. Heavy background talk uses CPU and heat; B-V4 decides whether the detector is needed.

## ADR-09 Half-duplex audio with a bounded deaf window
**Accepted.**
**Alternatives:** echo cancellation now (speexdsp needs mic and speaker on one clock, and depends on hardware not yet chosen).
**Consequence:** a blind window of about 1.45 s during motion. Stop words are still honoured in what is transcribed afterwards.

## ADR-10 `llama-server` for LFM2.5-VL
**Accepted.** Evidence in Q3.
**Alternatives:** Ollama (support unconfirmed; conflicting sources).
**Consequence:** two runtimes exist in the system, Ollama on the Pi per Decision 3 and llama-server at home. Both are behind adapters.

## ADR-11 Queue delay from a one-way-delay minimum, no synchronised clocks required
**Accepted.**
**Alternatives:** trust NTP across Tailscale (the Pi may have no internet and has no RTC); explicit ping-pong messages (more protocol for the same information).
**Consequence:** a clock step upward looks like delay for up to 30 s and refuses motion, which is the safe direction. Constant high latency is not detected as delay, by design: it does not make a Move stale.

## ADR-12 Confirmation bound to the frame hash, checked at the gateway
**Accepted.**
**Alternatives:** a Telegram button alone (nothing proves the owner saw the current scene, and the rule would live in the brain); a timed lockout (does not show the scene).
**Consequence:** a release is impossible without a working camera. A person at the robot can power-cycle it. A stolen Telegram account can still confirm, so the physical E-stop and two-step verification are still needed.

## ADR-13 Stop means hold-off for equal and lower priority sources
**Accepted.** 2 s, longer than the 0.5 s renewal.
**Alternatives:** a latch until a new explicit intent (stronger, but needs a new "intent" concept in every client); broadcast and trust the clients (a buggy client restarts motion).
**Consequence:** after a voice Stop, a planner cannot move for 2 s and has been told why. An existing test that expected immediate passage was changed, and the change is listed.

## ADR-14 Point-LIO on recordings, in a container, with a small custom format on the Pi
**Accepted.** Evidence in Q5.
**Alternatives:** FAST-LIO2 (works on many LiDARs but has no vendor L2 config); ROS on the Pi (heavy, and against the no-heavy-libraries rule); MCAP on the Pi (a good format, but adds a dependency for no gain here); KISS-ICP (kept as the LiDAR-only fallback).
**Consequence:** mapping is offline only. Point-LIO was developed for steadier platforms than a walking hexapod; whether it holds up here is unknown until a real recording.

## ADR-15 Release directories and a symlink, not images
**Accepted.**
**Alternatives:** A/B partitions or OSTree (strong, but days of work for one robot); `git pull` in place (no rollback).
**Consequence:** rollback in under a minute. The OS is not covered, and the SD card remains the single point of failure.

## ADR-16 No metrics database
**Accepted.** Status, traces and JSON logs.
**Alternatives:** Prometheus and Grafana (standard, but 500 MB more on a server already short of memory, and more to run).
**Consequence:** history is limited to JSONL files. Prometheus can be added later by exposing the same data.

## ADR-17 The planner never wakes a limp robot
**Accepted.** Only voice, or remote with a confirmed frame.
**Alternatives:** approval at the policy layer only.
**Consequence:** a planner task that needs to stand from limp fails and reports it. An owner standing by has to say it or confirm it.
