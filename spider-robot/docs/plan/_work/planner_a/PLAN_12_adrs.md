# 12. Architecture decision records

## ADR-01: Keep Python for the 50 Hz loop

**Context:** the loop is in asyncio on a Pi. **Decision:** keep it, conditional on gate RT1.
**Alternatives:** C++ tick (more determinism; a large rewrite before there is evidence it is needed);
microcontroller (best isolation; more hardware and firmware). **Consequences:** fast iteration, and a
measured gate rather than a belief. The ladder in `PLAN_14_open_questions.md` applies if RT1 fails.

## ADR-02: Isolate with systemd defaults, IRQ steering, FIFO and mlockall

**Decision:** `CPUAffinity=1 2 3` as a global default; `spider-tune.sh` for IRQs and governor; FIFO on
the control thread only. **Alternatives:** `isolcpus` on Core 0 (cannot fully isolate the boot CPU);
PREEMPT_RT (no official package found; limits here are milliseconds). **Consequences:** no kernel
changes, reversible. Some kernel work remains on Core 0, and RT1 measures how much.

## ADR-03: Bound motion at the source

**Decision:** every Move expires by itself; voice ≤ 2 s, remote and planner ≤ 1 s, enforced in the
gateway. **Alternatives:** relying on fast Stop (voice Stop takes seconds here); a continuous enable
signal only (still fails when the link fails oddly). **Consequences:** the worst-case travel after any
failure is a known number. Long walks need renewals, which the brain already does.

## ADR-04: Judge lateness without trusting clocks

**Decision:** gateway minimum-delay filter per source; re-stamp commands. **Alternatives:** require NTP
(fails silently, and the Pi has no RTC); sender-side sequence windows (cannot see age). **Consequences:**
no NTP dependency. A permanent long delay is indistinguishable from a clock offset; the caps bound the
effect of that case.

## ADR-05: Persistent E-stop; a cold process sends nothing

**Decision:** latch file with fsync off the control thread. A process starting latched writes nothing
to the servos, and a release goes to relaxed. **Alternatives:** tmpfs latch (lost on reboot); persist
the last pose and resume (more failure modes for little gain). **Consequences:** after a crash under
E-stop the owner must place the robot before standing it.

## ADR-06: A physical power cut is required before untethered walking

**Decision:** switch and relay upstream of both UBECs; hardware watchdog on the same relay.
**Alternatives:** software only (cannot be relied on: servo behaviour without pulses is unknown, and a
hung Pi does nothing). **Consequences:** a small hardware addition before M4, and the only true
Category 0 stop on the robot.

## ADR-07: Deterministic grammar before the LLM, and the LLM cannot invent motion

**Decision:** stop words → grammar → LLM with `cross_check`. **Alternatives:** LLM for everything (slow
and hallucination-prone on noisy Arabic). **Consequences:** common commands skip the model entirely. A
valid phrasing outside the lexicon gets a spoken reply rather than motion. That is the right trade.

## ADR-08: Wake word from the transcript

**Decision:** match wake words on Whisper's output. **Alternatives:** openWakeWord or Porcupine (lower
CPU; no Arabic model found, training needed); Vosk (large Arabic model). **Consequences:** every
utterance costs an STT pass on cores 1-3. A dedicated detector can be added at M8 without changing the
pipeline.

## ADR-09: `llama-server` for vision

**Decision:** use the route Liquid documents, with an API key on the tailnet address. **Alternatives:**
Ollama (sources conflict on projector support, untested). **Consequences:** a second runtime on the
server. Vision is a URL, so this is easy to reverse.

## ADR-10: Camera as its own process

**Decision:** `spider-camera` on cores 1-3 answers the same Snapshot command. **Alternatives:** keep it
in the body (violates agreed decision 3). **Consequences:** one more service; OpenCV leaves the control
process, which a test confirms.

## ADR-11: LiDAR sectors hold until swept again

**Decision:** per-sector values with a 0.45 s hold. **Alternatives:** raise `cloud_scan_num` so each
cloud is a full revolution (slower updates; relies on undocumented behaviour). **Consequences:** correct
whatever the sweep pattern. A moving object can linger for up to 0.45 s, which errs on the safe side.

## ADR-12: One mTLS listener, firewall for reachability

**Decision:** a single TLS listener, and nftables to limit it to loopback and the tailnet.
**Alternatives:** binding to `tailscale0` (fails at boot if Tailscale is late); a plaintext loopback
listener (loses certificate identity, and with it the ACLs). **Consequences:** small TLS cost on
loopback, uniform identity everywhere.

## ADR-13: Half-duplex echo gate instead of an echo canceller

**Decision:** energy-based gate during playback; barge-in can only be a stop word. **Alternatives:**
PipeWire or WebRTC AEC (better barge-in; more CPU and integration risk on the Pi). **Consequences:**
simple and testable. Barge-in needs a raised voice. Revisit after V3.

## ADR-14: Point-LIO from a plain recording format

**Decision:** `.sprec` on the Pi, converted to a bag on the server; Point-LIO in a container.
**Alternatives:** record rosbag on the Pi (needs ROS or heavy libraries there); FAST-LIO2 (no official
L2 support found). **Consequences:** nothing ROS-related on the robot. Depends on a ROS 1 image.

## ADR-15: Audio through `arecord` and `aplay`

**Decision:** subprocesses, not PortAudio. **Alternatives:** `sounddevice` (one more native dependency,
in-process). **Consequences:** killing `aplay` is the barge-in. A process per utterance adds a few
milliseconds.

## ADR-16: Two sources, one MQTT client in the brain

**Decision:** a context variable marks planner work, so one client sends as `remote` or `planner`.
**Alternatives:** two links (two connections and certificates for little benefit). **Consequences:**
each task's commands carry the right priority. Both sources must heartbeat.

---

# Proposed changes to agreed decisions

Only two, both raised with evidence. Neither blocks the plan: the code implements the decision as
agreed, with the change available as configuration.

## P-1: Decision 2 (Core 0 reserved), allow moving it to Core 3 if RT1 fails

**Evidence of the defect:** Core 0 on Linux is the boot CPU. Kernel documentation and LKML discussions
from 2023-2024 say the boot CPU cannot be `nohz_full`; timekeeping and housekeeping stay there. Core 0
is therefore the one core that cannot be fully isolated.

**Proposal:** keep Core 0 as agreed. If RT1 fails, move to Core 3 with `isolcpus` and `nohz_full`.
Implementation: `rt.cpu` in `robot.yaml` and `CPUAffinity=` in two unit files, with no code change.

## P-2: Decision 6 (stop words on the transcript), keep it, and add a faster path later

**Evidence of the defect:** Whisper runs before any stop word can match. Latency is estimated at 1.4-2.9 s
to braking, and Whisper tiny's Arabic WER is 63.4% on FLEURS **[S]**. The decision as written cannot
deliver a fast or highly reliable voice Stop on this hardware.

**Proposal:** keep the decision exactly as written. Do not treat voice Stop as the primary protection;
that role belongs to expiring Moves and the physical E-stop. Decide after V4 whether to enable
`stop_on_speech_onset`, and at M8 whether to train a keyword spotter. A spotter would be an addition
running beside the transcript match, not a replacement for it.
