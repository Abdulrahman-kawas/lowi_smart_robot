# Mission

You are the lead architect for a real Arabic-speaking hexapod robot. Produce the definitive
engineering plan that takes this repository from its current state to one coherent, production
quality system. The bar is the work of a senior team at a strong robotics company: an engineer who
has never seen this project must be able to build it from your output alone.

The system's defining qualities are **fast response, physical stability, and parts that fit
together**. Every decision must serve those.

Use the Agent tool as described below: this request explicitly asks for subagents. This is a
planning task. The only files you may create are under `spider-robot/docs/plan/`. Do not change any
other file, commit, switch branches, or use worktrees: part of the code is uncommitted and exists
only in this working tree.

# Repository

- Root: `/Users/abdulrahmankawas/Desktop/my_projects/robot_lowi`, branch
  `robot/spider-robot/part2-brain`.
- Read first: `spider-robot/docs/ARCHITECTURE.md` (agreed design), `CLAUDE.md`,
  `graphify-out/GRAPH_REPORT.md` (the graph may lag the code; the code wins).
- Packages: `common/` (protocol, MQTT link), `body/` (Pi control, safety), `gateway/` (command
  arbitration, new and uncommitted), `brain/` (planner, Telegram, WhatsApp alerts, memory, skills,
  vision, cloud voice), `infra/`.
- Run tests per package with `uv run --all-extras pytest -q`. At the time of writing: common 9,
  body 47, gateway 16, brain 33, all passing, all on simulator or in-memory links. Nothing below has
  been run on the real Pi, a real broker, or the real server.

# Hardware and environment

| Item | Fact |
|---|---|
| Robot | 6 legs, 18 DSSERVO RDS3218 servos, Raspberry Pi 4 (4 GB), camera, mic, speaker |
| Servos | Lynxmotion SSC-32U over USB. It only generates pulses |
| LiDAR | Unitree L2 with built-in IMU, Ethernet at `192.168.1.x`, via C++ `lidar_bridge` to ZeroMQ |
| Home server | i7-8700 (6C/12T, AVX2), 15 GB RAM, no GPU, Ubuntu 24.04, Wi-Fi over USB on `192.168.0.x`, Tailscale up, Docker present, Ollama not installed |
| Server caveat | About 5.7 GB RAM free in daily use, because desktop apps run on it. A later swap to a machine with an RTX 3060 12 GB or better and 32 GB RAM is possible; the plan must work without it and benefit from it |
| Clouds | Claude, Gemini, NVIDIA NIM (`moonshotai/kimi-k3.1-pro`; hosted endpoint for this ID unconfirmed) |

# Decisions already made: do not reopen

Challenge one only by giving concrete evidence of a defect, in a section called "Proposed changes
to agreed decisions".

1. Placement rule: if the network dies, safety, motion and simple voice commands must keep working.
   The cloud is never required for the robot to function.
2. Pi Core 0 is reserved for `lidar_bridge` and `spider-body` (IK, 50 Hz gait, IMU tilt, LiDAR
   reflexes, watchdog, SSC-32U). Balance and obstacle reaction never leave the Pi.
3. Pi Cores 1-3: gateway, Mosquitto, camera capture, `webrtcvad`, `faster-whisper` (`tiny`, `int8`),
   LFM2.5-350M on Ollama (`act` + `say` JSON), Piper with `ar_JO-kareem-low`, `espeak-ng` fallback.
4. Home server: brain, Telegram, WhatsApp alerts, memory, dashboard, LFM2.5-VL vision, stronger local
   LLM, better STT for hard utterances, on-demand SLAM.
5. The gateway is the only sender to the body. Priority: Stop and E-stop from anyone, then voice,
   then remote, then planner. The body keeps its own limits regardless.
6. Stop words match the transcript directly and never wait for a model.
7. Vision and cloud answers are spoken only. They never produce motion directly.
8. Remote control is required: Telegram and dashboard through Tailscale; SSH to the Pi as fallback.
   Remote motion has tighter caps than local voice, and remote E-stop release needs a fresh camera
   frame and explicit confirmation.
9. AWS is off by default. It starts automatically only for a requested LiDAR recording or mapping
   job, processes a recorded copy, and stops itself. The Pi holds no AWS credentials.
10. STT, TTS, LLM and vision sit behind swappable interfaces selected by config. Moving a service to
    another machine must be a config change. The owner wants many options available from this
    foundation without rebuilding it.

# Open questions the plan must settle with evidence

- Is the Python/asyncio 50 Hz loop on Core 0 good enough, and how would that be proven on the Pi?
  Does real isolation need `isolcpus`, IRQ affinity, or `SCHED_FIFO`?
- Real end-to-end voice latency on a Pi 4, and Arabic quality of `whisper tiny` and LFM2.5-350M.
  State what you can only estimate and define the bench test that replaces the estimate.
- Does Ollama load the LFM2.5-VL image projector, or is `llama-server` needed?
- Safe behaviour of MQTT over Tailscale under relay latency, against the body's 1.5 s link timeout
  and 1.0 s command age limit.
- Which SLAM stack fits the L2 and this CPU, and what the recording format is.
- What runs where when the home server, Wi-Fi, internet, gateway, or broker each fail alone.
- Wake word and barge-in: how the robot avoids hearing itself and avoids moving on background speech.

# Team and process

Spawn fresh `general-purpose` agents with `model: opus` and `effort: xhigh`. Give each the whole of this file, and tell each to read the
actual code and to check current facts by web search. Each writes to
`spider-robot/docs/plan/_work/`. None may modify anything else.

**Phase 1: two independent planners, run in parallel, unable to see each other's work.** Both write
a complete plan against the required contents below.

- *Planner A: principal robotics and real-time systems engineer.* 15+ years shipping legged robots
  and embedded Linux. Optimises for determinism, physical safety and failure containment.
- *Planner B: principal distributed systems and edge ML engineer.* 15+ years on production IoT and
  on-device inference. Optimises for interface quality, operability, and fast delivery by one
  developer.

**Phase 2: one judge, a fresh agent.** A VP-level engineer who has run safety-critical robotics
programmes and design reviews. The judge must:

- Verify each plan's claims against the code, citing `file:line`. Treat unverified claims as wrong.
- Attack both plans: find what breaks first on real hardware.
- Score each plan 1-10 per criterion with one sentence of evidence: safety, real-time behaviour,
  latency, coherence between parts, failure handling, security, feasibility for one developer on this
  hardware, testability, operability, code correctness, extensibility.
- Decide per area which plan wins, or how to merge them. Do not average. Record every rejected idea
  and why.
- Output a binding list of required changes.

**Phase 3: revision.** The two planners jointly produce nothing further; you, the lead, merge the
winning parts and apply every required change. Return the merged plan to the judge once. Stop when
the judge has no remaining blocking finding, or after two rounds; list what remains unresolved.

# Required system design contents

Apply each item at the size this project needs. One robot does not need Kubernetes, Kafka, a service
mesh, or microservices for their own sake. A reviewer should find each part justified.

1. **Requirements:** functional, plus numeric targets for every non-functional one, stating how each
   is measured. Include voice stage latencies, Stop-to-motion-halt time, control loop jitter,
   availability per failure mode, and memory and CPU ceilings.
2. **Architecture:** context and container diagrams (Mermaid), component responsibilities, ownership
   boundaries, and the data flow for each key scenario.
3. **Contracts:** every topic, message and interface with schema, QoS, rate, direction, timeout and
   versioning rule. Backward compatibility rules between Pi and server.
4. **Budgets:** per-core CPU and per-process RAM on the Pi; CPU, RAM and optional GPU on the server;
   bandwidth; latency budget by stage, summing to the end-to-end target.
5. **Failure analysis:** an FMEA table of failure, detection, automatic response, recovery, and the
   test that proves it. Network partitions, process crashes, sensor loss, clock skew, power and
   thermal throttling must be included.
6. **Physical safety:** hazard analysis in the style of ISO 12100 and ISO 13482, as guidance and not
   a certification claim. Define states and transitions, and what the E-stop actually cuts.
7. **Security:** STRIDE threat model covering Telegram account takeover, MQTT, Ollama exposure,
   prompt injection through camera and voice, secrets, and certificate rotation.
8. **Observability:** structured logs, metrics, correlation IDs from utterance to motion, the health
   model, the alerts that matter, and a latency dashboard.
9. **Testing:** unit, contract, simulator, hardware-in-the-loop, fault injection and soak tests. Each
   milestone has a pass/fail gate.
10. **Delivery:** CI, reproducible installs, systemd units with resource limits, config and secret
    management, safe updates of a running robot, rollback, and runbooks.
11. **Cost:** monthly cost at home-only, typical use, and heavy AWS use, with sources and dates.
12. **ADRs:** one per significant decision, with alternatives and consequences.
13. **Roadmap:** ordered milestones, each independently testable, leaving the robot working. Start
    from the current code and reuse what exists. State what is kept, changed, or deleted.

# Code requirements

- A file map listing every file to create, change or delete, with path, purpose, owner package, node
  it runs on, and milestone.
- Complete code for every new or changed file. No placeholders, pseudocode, `TODO`, `...`, or "rest
  unchanged". For changes to existing files give exact, applicable patches.
- Match the repo's conventions: Python 3.11+, `uv`, `ruff` at 100 columns, pydantic, asyncio,
  `spider_common.protocol` as the single contract, and tests in each package.
- Code must run. Copy the repo to a temp directory outside it, apply your code, and run `pytest` and
  `ruff` for all packages. Report the real output. Label anything you could not run, such as code
  needing the Pi, as unverified. Never claim a result you did not observe.
- Nothing blocks the control loop. No vision models or heavy libraries on the Pi. Router prompts stay
  short, with a JSON schema, temperature 0.1-0.2, and a token limit tested against real Arabic.
- All code goes inside `04_EXECUTION_PLAN.md`. Never shorten code to fit.
- Any git commit message in this repo must be plain and carry no AI attribution of any kind.

# Handoff to a low-cost executor

The owner will give `04_EXECUTION_PLAN.md` to a free, less capable coding agent. Assume that agent
has a small context window, no memory between sessions, no knowledge of this project, and no ability
to make design decisions. All thinking happens now; the executor only transcribes and runs.

The file must be self-contained, with all code written inside it:

- **Opening rules for the executor:** follow steps in order; change nothing that is not listed; never
  improvise, refactor, upgrade or "improve"; never skip a verification; on any mismatch or failure,
  stop and report the step ID and exact output.
- **Index:** every step with its ID and the line range in the file, so the executor can read one step
  at a time. Each step must be understandable with no other step in view.
- **Progress:** the executor records each finished step in `docs/plan/PROGRESS.md`, so a new session
  can resume.
- **Step 0:** show `git status`, then make a baseline commit of the existing uncommitted work, so
  every later step can be rolled back.
- **Every step states:** ID, goal, machine (Mac, Pi or server), exact working directory, preconditions,
  files touched, exact commands, expected output, how to roll back, when to stop, and a plain commit
  message.
- **File content:** the full text of every new file. For an existing file, use exact search-and-replace
  blocks whose search text occurs once, or give the full replacement file when it is short.
- **Small steps:** a few files each, ending in a passing check. Pin every dependency and model version;
  never write "latest".
- **Secrets:** placeholders only, each with the exact place the owner puts the real value.
- **`HUMAN STEP` blocks:** the executor must stop for anything physical or owner-only: wiring,
  credentials, account setup, and every first powered test. The first servo motion happens with the
  robot on a stand, the owner present, and a tested way to cut power. The executor never starts robot
  motion on real hardware by itself.

**Dry run before finishing.** Spawn a fresh agent with `model: sonnet` and `effort: low`, closer to
the free executor, given only `04_EXECUTION_PLAN.md` and a clean copy
of the repo in a temp directory, including the uncommitted work. It acts as the literal executor and
runs every step possible without hardware. Each place it must guess is a defect in the plan: fix it
and rerun the affected steps. Record the results in `06_VALIDATION.md`, and mark every step that needs
the Pi, server or robot as `NOT VALIDATED`.

# Deliverables in `spider-robot/docs/plan/`

| File | Content | Language |
|---|---|---|
| `00_REPORT.md` | For the owner: what is being built, key decisions, judge's verdict, top risks, cost, what to do first | English |
| `01_SYSTEM_DESIGN.md` | Required contents 1-12 | English |
| `02_FILE_MAP.md` | Every file and where it goes | English |
| `03_ROADMAP.md` | Milestones, gates, step-by-step build order | English |
| `04_EXECUTION_PLAN.md` | The one file handed to the executor: every step, command and line of code | English |
| `05_JUDGE_VERDICT.md` | Scores, evidence, merge decisions, rejected ideas, unresolved items | English |
| `06_VALIDATION.md` | Commands run, actual results, and everything still unverified | English |
| `_work/` | Both original plans and the judge's rounds | English |

# Honesty rules

Separate what is verified, what is estimated, and what is assumed, everywhere. Give estimates a basis
and a test that would replace them. Cite sources for prices and model availability. If something
cannot meet its target on this hardware, say so and offer the best achievable alternative.

Write everything in English, including the final reply. When finished, reply with: the verdict in a few lines, the top risks, the file list, what
was and was not tested, and the single first step for the owner.
