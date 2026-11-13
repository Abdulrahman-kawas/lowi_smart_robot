# The seven open questions, settled

## 1. Is the Python/asyncio 50 Hz loop on Core 0 good enough? What isolation does it need?

**Answer: yes, with conditions, and gate RT1 proves it or sends us down a defined ladder.**

Why Python can be enough here:

- The hexapod is statically stable in tripod gait (three feet always down, `gait.py:22`). Nothing is
  balancing at 50 Hz. Tilt and obstacle reflexes act over hundreds of milliseconds.
- Servos receive group moves at 25 Hz with 40 ms interpolation inside the SSC-32U
  (`hw/servos.py:194-195`). A few milliseconds of jitter disappears in that interpolation.
- If the loop stalls, the SSC-32U finishes its current 40 ms move and holds. The robot stops; it does
  not run away.
- Measured cost on the Mac, per tick: p50 29 µs, p99 196 µs **[V]**. Scaled by an assumed ×8 for a
  Cortex-A72 **[E]**, about 0.23 ms and 1.6 ms, against a 20 ms period.

The real risk is stalls of 100 ms or more, and their causes are all addressable:

| Stall source | Evidence | Fix |
|---|---|---|
| Page faults or swap under AI memory pressure | 4 GB Pi | `mlockall`, no swap, per-service `MemoryMax` |
| Other work on Core 0 | No affinity in `spider-body.service` or `spider-lidar.service` | `CPUAffinity=1 2 3` as a systemd default; only two units override it |
| IRQs on Core 0 | Linux default; on the Pi 4 movable per IRQ **[S]** but USB may refuse | `spider-tune.sh`; logs what would not move |
| GC pause | Comment at `main.py:175` measures 40 ms for a full collection | `gc.freeze()` (already there), higher thresholds |
| CPU-heavy thread in the process | JPEG encode at `robot.py:227` | Camera moved out of the process |
| USB write blocking | `write_timeout=0.1` at `hw/servos.py:169` | 10 ms timeout, and skip a frame when the link is behind |
| Disk fsync on the control thread | New latch would add one | The latch writes on a short-lived thread |
| asyncio timer coarseness | Community reports of about 20 ms jitter **[S]**, on an unpinned, unprioritised loop | `SCHED_FIFO`; measured by RT1 |

**Is `isolcpus` needed?** Not at first, and it cannot do what its name suggests here. The boot CPU
cannot be a full `nohz_full` CPU: the kernel documentation's rule is that the mask must not include
the boot CPU, and LKML threads from 2023-2024 report the exception that once allowed it as broken
**[S]**. On a Pi 4 the boot CPU is Core 0, so the timer tick and housekeeping stay there whatever we
do. `isolcpus=domain,managed_irq,3` would work on Core 3 instead; that is the first rung of the
ladder and `PLAN_12_adrs.md` proposes it, with evidence, as a change only if RT1 fails.

**Is IRQ affinity needed?** Yes. It is cheap and it removes the largest remaining source of Core 0
interruption.

**Is `SCHED_FIFO` needed?** Yes, on the control thread only, set after the MQTT thread exists and with
`SCHED_RESET_ON_FORK`, so helper threads stay in the normal class (`body/src/spider_body/rt.py`).

**Is PREEMPT_RT needed?** No. Published Pi 4 worst cases are about 1-2 ms on a stock kernel and tens of
microseconds with RT **[S, old kernels]**. Our limit is 18 ms. I found no official package, only
community builds, and a 2026 project found RT made one timing case worse **[S]**.

**How it is proven:** `infra/pi/bench_jitter.sh` runs for one hour with `stress-ng` loading cores 1-3
and the jitter histogram on. Pass: R-01 to R-06.

**If RT1 fails, in order:**
1. Move the control process to Core 3 with `isolcpus` and `nohz_full` on it.
2. Move the tick (IK plus gait) into a small C++ library.
3. Add an RP2040 between the Pi and the SSC-32U to run the last-resort watchdog and gait interpolation.

## 2. Real end-to-end voice latency on a Pi 4, and Arabic quality

Honest position: **I can only estimate latency.** I found no published figure for faster-whisper tiny
int8, LFM2.5-350M, or Piper `ar_JO-kareem-low` on a Pi 4.

| Stage | Estimate | Replaced by |
|---|---|---|
| End of speech detected | 0.3 s **[V]** configured | V1 |
| Whisper tiny | 1.0-2.5 s **[E]** | V1 |
| Grammar or stop match | under 1 ms **[E]** | V1 |
| Router | 1-2 s for the full reply **[E]** | S1 |
| Piper first audio | 0.3-0.7 s **[E]** | V3 |

- Grammar path, end of speech to motion start: **1.4-2.9 s**.
- LLM path: **2.4-4.9 s**.
- The architecture document's under-300 ms router target is not realistic on a Pi 4 as a whole reply.
  The deterministic grammar is the answer for common commands.

Whisper's encoder works on a padded window whatever the utterance length (`pad_or_trim` in
faster-whisper's `transcribe.py`, read 2026-11-09). I could not confirm whether `chunk_length` can
shorten it, so assume short clips do not get much cheaper; V1 will show it directly.

**Arabic quality:**

- Whisper tiny on Arabic FLEURS: **63.4% WER**, against 30.6% for small (arXiv 2510.23319, Table 7)
  **[S]**. Community reports of hallucination on dialects **[S]**. Tiny will not transcribe free Arabic
  reliably.
- LFM2.5-350M lists Arabic among its languages on Hugging Face (2026-11-03) **[S]**. Its Arabic output
  quality is untested **[A]**.

Consequences in the design:

- Commands are a small closed vocabulary with fuzzy matching (`text.py`, `grammar.py`).
- `initial_prompt` biases tiny toward command words. Bench V2 checks that silence does not echo it.
- Hard utterances escalate to Whisper small on the server when configured.
- A `num_predict` of 64 is **measured** against real Arabic with the real tokenizer: a 13-word sentence
  in the JSON wrapper costs 42 tokens **[V]**, leaving room for about 20 words.

**Bench V1/V2 pass criteria:** 200 recorded owner commands, 10 words, in quiet and with gait noise.
Stop-word recall ≥ 95% in quiet and ≥ 85% with gait noise; false motion 0 in 30 minutes of TV audio.
If recall misses, the fallback ladder is: `base` instead of `tiny`, then a trained keyword spotter.

## 3. Does Ollama load the LFM2.5-VL image projector, or is `llama-server` needed?

**Decision: use `llama-server` on the home server. Ollama's status is unverified.**

Evidence conflicts **[S, 2026-11-09]**: one Liquid page says the VL models "currently do not work with
Ollama", another shows `ollama run hf.co/LiquidAI/LFM2.5-VL-1.6B-GGUF`, and a community report describes
load errors when attaching the projector. Liquid documents `llama-server -hf
LiquidAI/LFM2.5-VL-1.6B-GGUF:Q4_0`, which fetches the matching `mmproj` file, and the repo lists
`mmproj-LFM2.5-VL-1.6b-Q8_0.gguf` **[V]** via the Hugging Face API.

I tried to test Ollama directly and the download was denied by the permission system, so this stays
open. It does not block anything, because vision uses an OpenAI-compatible URL. If bench V6 shows
Ollama works, switching is a one-line config change.

## 4. MQTT over Tailscale against the 1.5 s link timeout and 1.0 s age limit

The important correction: **those two limits no longer apply to the Tailscale hop.** With the gateway
in place, the body's 1.5 s link timeout (`config.py:112`) is between gateway and body over loopback.
The hop across Tailscale is judged by the gateway's per-source checks.

At baseline, however, the gateway passed the sender's timestamp through (`gateway.py:137`), so the
body's 1.0 s age check (`robot.py:123-125`) compared the server's clock with the Pi's. That budget had
to cover network delay plus clock offset. Now:

| Behaviour | Mechanism |
|---|---|
| Clock offset | The gateway measures each source's apparent delay and subtracts the minimum of the last 60 s. A constant offset cancels (`SourceClock`, tested with a 7.5 s skew) |
| Clock step | After 3 s of late messages that agree with each other, the window restarts |
| TCP stall, then a burst | Delays fall as the backlog drains, so they do not agree, and they are refused as late |
| Late Stop | Always accepted, however late |
| Late Move | Refused above 0.75 s of excess delay |
| Late heartbeat | Ignored, so it cannot keep a dead link "alive" (D8) |
| Body age check | Now compares two readings of one clock on one machine |

Relay latency **[S]**: Tailscale documents that relayed paths are slower than direct, and one
third-party report shows about 450 ms before a peer relay and about 300 ms after. Pi and server on one
LAN should normally connect directly; `tailscale ping` confirms it in NET1.

Worst cases for remote control: a Move lasts at most 1.0 s at 0.05 m/s. If the link dies right after
a renewal, the robot travels at most 5 cm plus 0.5 cm of braking **[V]**. On a spiky link, motion
stutters and stops on its own, which is the correct failure.

## 5. Which SLAM stack, and what recording format

**Stack: Point-LIO, using Unitree's `point_lio_unilidar`.** It explicitly supports the L2 with
`mapping_unilidar_l2.launch`, tested on Ubuntu 20.04 with ROS Noetic **[S]**. It runs in a container
from a recording, so real-time performance on this CPU is not required.

| Alternative | Why not first |
|---|---|
| FAST-LIO2 | No official L2 package found; community port only |
| Community Point-LIO ROS 2 ports | Good later, but tested on Humble, and need checking on Jazzy |
| KISS-ICP | LiDAR only; a hexapod's foot impacts make the IMU valuable |

**Recording format:** a simple append-only framed file, `.sprec`, written on the Pi
(`body/src/spider_body/recorder.py`). Each frame is `<BdII` + payload, with clouds as
`float32[n*6]` x, y, z, intensity, point time, ring, and every 500 Hz IMU sample.

- No dependencies on the Pi, and a file cut short by power loss stays readable up to its last whole
  frame **[V]** test.
- Keeps per-point time, which deskewing needs.
- Converted on the server to a ROS 1 bag with `rosbags` **[V]** round-trip test.
- Volume: 64,000 points/s × 24 bytes ≈ 1.5 MB/s, about 5.5 GB/hour **[V]** arithmetic.

Unverified until the M7 gate: Point-LIO's expected point layout, and whether the map is usable.

## 6. What runs where when each part fails alone

See the table in `PLAN_05_failure_analysis.md` section 5.1.

## 7. Wake word and barge-in

**Not hearing itself** (`echo.py`, `pipeline.py`):

- The robot is half duplex. While it speaks, plus a 250 ms tail, anything heard counts as its own voice
  unless it is at least 9 dB louder than its running level at the microphone.
- A segment that passes is a *barge-in candidate*, and can only match a stop word. It never reaches the
  router (`test_barge_in_can_stop_but_nothing_else`).
- Stop words are stripped from everything the robot says, so it cannot stop itself. This also removes
  a stop word planted in a camera image from a spoken answer (`test_vision_answer_*`).

**Not moving on background speech** (`grammar.py`):

- Motion needs the wake word, or a command within the last 8 s.
- Low-confidence transcripts are dropped, except that stop words ignore confidence.
- The LLM may only choose a motion whose words the owner actually said (`cross_check`). Hallucination
  or injection cannot invent a walk.
- Every voice Move is short and expires.

**Wake word method:** match on the transcript, with no extra model. A dedicated detector would save
CPU, but I found no Arabic model **[S]** and training one is M8 work. The cost is that all speech is
transcribed, on cores 1-3 only, bounded by "one long utterance at a time".

**Speech-onset stop:** `stop_on_speech_onset` stops the robot the moment speech begins while walking,
which is the only way to beat Whisper latency without a new model. It is **off by default**, because
servo noise may trigger VAD constantly. Bench V4 decides.

## Sources (retrieved 2026-11-09)

| Topic | Source |
|---|---|
| L2 rates, FOV, IMU, factory defaults, warm-up | [Unitree L2 User Manual](https://oss-global-cdn.unitree.com/static/Unitree%204D%20LiDAR%20L2%20User%20Manual.pdf) |
| SDK signatures, `cloud_scan_num` default, work-mode bits | [unilidar_sdk2 header](https://raw.githubusercontent.com/unitreerobotics/unilidar_sdk2/main/unitree_lidar_sdk/include/unitree_lidar_sdk.h), [README](https://github.com/unitreerobotics/unilidar_sdk2) |
| LFM2.5-350M languages and files | [Hugging Face API](https://huggingface.co/api/models/LiquidAI/LFM2.5-350M), last modified 2026-11-03; [GGUF repo](https://huggingface.co/LiquidAI/LFM2.5-350M-GGUF) |
| LFM2.5-VL files; llama.cpp and Ollama routes | [GGUF API](https://huggingface.co/api/models/LiquidAI/LFM2.5-VL-1.6B-GGUF); [Liquid llama.cpp docs](https://docs.liquid.ai/deployment/on-device/llama-cpp/multimodal); [Liquid Ollama docs](https://docs.liquid.ai/lfm/inference/ollama) |
| Whisper tiny Arabic WER | [Arabic Little STT, arXiv 2510.23319](https://arxiv.org/pdf/2510.23319), Table 7 |
| Whisper tiny on Arabic dialects, qualitative | [arabicagenticai](https://arabicagenticai.pages.dev/speech/whisper-arabic/) |
| Piper voice size; Piper API | [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices/tree/main/ar/ar_JO/kareem); [piper1-gpl API](https://raw.githubusercontent.com/OHF-Voice/piper1-gpl/main/docs/API_PYTHON.md) |
| faster-whisper parameters | [transcribe.py](https://raw.githubusercontent.com/SYSTRAN/faster-whisper/master/faster_whisper/transcribe.py) |
| Ollama API | [structured outputs](https://docs.ollama.com/capabilities/structured-outputs) |
| Boot CPU and `nohz_full` | [LKML thread](https://lore.kernel.org/lkml/20190116175440.GB26169@lenoir/T/); [2024 report](https://lkml.iu.edu/hypermail/linux/kernel/2404.0/08090.html); [openEuler patches](https://mailweb.openeuler.org/archives/list/kernel@openeuler.org/thread/WKFP5SS7H2IAAAT65MV2FG5DELGZKGSG) |
| Pi 4 IRQ affinity | [OpenWrt forum](https://forum.openwrt.org/t/raspberry-pi-4-system-is-freezing-up/109970/30) |
| PREEMPT_RT on the Pi 4 | [Pi 4 latency report](https://spinics.net/lists/linux-rt-users/msg25944.html); [2026 RT field report](https://git.supported.systems/warehack.ing/cuckoo-escapement/src/tag/2026.07.14/kernel/README.md) |
| asyncio jitter | [discuss.python.org](https://discuss.python.org/t/16153) |
| SSC-32U commands | [User guide](https://cdn.robotshop.com/media/d/dsp/rb-dsp-07/pdf/lynxmotion_ssc-32u_usb_user_guide.pdf); `P0`: [RobotShop forum](https://community.robotshop.com/forum/t/servo-release-with-ssc-32u/25501) |
| Digital servos on signal loss | [Pololu forum](https://forum.pololu.com/t/power-down-digital-servos/3764) |
| Tailscale paths | [Connection types](https://tailscale.com/docs/reference/connection-types); [third-party latency report](https://www.sitepoint.com/tailscale-peer-relays-nat-traversal-derp/) |
| Point-LIO for the L2 | [point_lio_unilidar](https://github.com/unitreerobotics/point_lio_unilidar) |
| NVIDIA NIM models | [kimi-k3](https://build.nvidia.com/moonshotai/kimi-k3); [kimi-k3.1-pro](https://build.nvidia.com/moonshotai/kimi-k3_1-pro.md), page updated 2026-11-04 |
| Wake words | [openWakeWord](https://pypi.org/project/openwakeword/0.4.0/) |
| Versions | PyPI JSON API and GitHub Releases API, queried 2026-11-09 |
