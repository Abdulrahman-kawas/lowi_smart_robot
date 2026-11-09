# Graph Report - lowi_robot  (2026-11-06)

## Corpus Check
- 63 files · ~82,059 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 13 file(s) not represented in the graph (top: .service 5, .lock 3, (none) 2)

## Summary
- 1002 nodes · 2379 edges · 62 communities (41 shown, 21 thin omitted)
- Extraction: 81% EXTRACTED · 19% INFERRED · 0% AMBIGUOUS · INFERRED: 448 edges (avg confidence: 0.92)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `78ab0b76`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- lidar.py
- camera.py
- spider_body/config.py
- robot.py
- RobotClient
- 6. Step-by-step execution
- 7. Files
- BrainService
- link.py
- service.py
- graph.py
- B.2 Body (Raspberry Pi) — `spider-robot/body/`
- Supervisor
- tools.py
- B.3 Brain (AWS / local) — `spider-robot/brain/`
- test_brain.py
- lidar_bridge.cpp
- ToolCall
- ClaudePlanner
- B.4 Infrastructure — `spider-robot/infra/`
- ToolOutcome
- Settings
- B.1 Shared protocol and link — `spider-robot/common/`
- memory.py
- iot_setup.sh
- Spider robot
- spider-common
- run-brain.sh
- make_local_certs.sh
- setup_pi.sh
- setup_ec2.sh
- VoiceService
- SafetyGuard
- Robot
- TelegramBot
- LidarSummary
- Link
- spider_body/main.py
- test_safety_lidar.py
- RoutedPlanner
- test_part2.py
- WhatsAppNotifier
- LidarSource
- RoutedVision
- spider_brain/config.py
- test_telegram_owner_flow_with_approval_buttons_and_voice
- FakeSMBus
- AI tells — phrases and patterns to avoid
- test_protocol.py
- FakeServoBank
- FakePlanner
- 3. Hardware
- SimWorld
- Talking with Arabic speakers
- Talking with users in Japanese
- Robot conversation
- Talking with users in English

## God Nodes (most connected - your core abstractions)
1. `RobotClient` - 60 edges
2. `Robot` - 45 edges
3. `Settings` - 42 edges
4. `ToolOutcome` - 34 edges
5. `ToolCall` - 31 edges
6. `BrainService` - 30 edges
7. `ToolExecutor` - 30 edges
8. `BodyConfig` - 28 edges
9. `7. Files` - 27 edges
10. `make()` - 26 edges

## Surprising Connections (you probably didn't know these)
- `0.2 Owner's hardware decisions (2026-11-06) — these override earlier defaults` --references--> `SscServoBank`  [INFERRED]
  SPIDER_ROBOT_AGENT_PLAN(1).md → spider-robot/body/src/spider_body/hw/servos.py
- `S14 — Walking by hand, local only (agent + HUMAN) · Gate: drift spec` --references--> `stand()`  [INFERRED]
  SPIDER_ROBOT_AGENT_PLAN(1).md → spider-robot/body/tests/test_robot.py
- `7. Replacing the Raspberry Pi after the trial` --references--> `ServoBank`  [INFERRED]
  SPIDER_ROBOT_AGENT_PLAN(1).md → spider-robot/body/src/spider_body/hw/servos.py
- `1. Requirements` --references--> `SscServoBank`  [INFERRED]
  SPIDER_ROBOT_AGENT_PLAN(1).md → spider-robot/body/src/spider_body/hw/servos.py
- `S3 — Simulator (agent) · Gate: stands, walks, stops; ping works` --references--> `stand()`  [INFERRED]
  SPIDER_ROBOT_AGENT_PLAN(1).md → spider-robot/body/tests/test_robot.py

## Import Cycles
- None detected.

## Communities (62 total, 21 thin omitted)

### Community 0 - "lidar.py"
Cohesion: 0.20
Nodes (7): LidarCfg, LidarFeed, LidarProcessor, test_feed_parses_bridge_frames(), test_height_offset_follows_body_height(), test_imu_goes_stale(), test_imu_upside_down_flag()

### Community 1 - "camera.py"
Cohesion: 0.10
Nodes (10): 7. Replacing the Raspberry Pi after the trial, CameraCfg, Camera, encode_jpeg(), FakeCamera, make_camera(), NoCamera, OpenCvCamera (+2 more)

### Community 2 - "spider_body/config.py"
Cohesion: 0.07
Nodes (16): cmd_center(), cmd_direction(), cmd_pose(), cmd_trim(), _joint_ids(), main(), apply_calibration(), BodyConfig (+8 more)

### Community 3 - "robot.py"
Cohesion: 0.07
Nodes (30): GaitCfg, GeometryCfg, LegCfg, _M, MqttCfg, PcaCfg, PulseCfg, SscCfg (+22 more)

### Community 4 - "RobotClient"
Cohesion: 0.06
Nodes (50): 0.1 What changed after the expert reviews (v1.0 → v1.1), 0.2 Owner's hardware decisions (2026-11-06) — these override earlier defaults, 0. Read this first (rules for the executing agent), 10. Troubleshooting, 11. Known limits and next steps, 2.1 Overview, 2.2 Three control layers (why the cloud can never crash the robot), 2.3 Safety layers (+42 more)

### Community 5 - "6. Step-by-step execution"
Cohesion: 0.10
Nodes (20): 6. Step-by-step execution, S10 — [HUMAN] Flash and boot the Pi, S11 — Pi setup (agent) · Gate: `spider-calibrate check` prints the SSC-32U firmware, S12 — [HUMAN] Wiring, power and torque check · Gate: power and torque, S13 — Servo calibration on a stand (agent guides, HUMAN watches) · Gate: symmetric stance, S14 — Walking by hand, local only (agent + HUMAN) · Gate: drift spec, S15 — LiDAR bring-up (agent + HUMAN) · Gate: correct sector map, S16 — Reflex tests on the floor (HUMAN watches) · Gate: all pass (+12 more)

### Community 6 - "7. Files"
Cohesion: 0.05
Nodes (42): 0. Rules for the executing agent, 2. Architecture after Part 2, 3. Cost notes, 4. Step-by-step, 5. Rollback, 6. Next steps, 7. Files, P2-1 — Files (agent) · Gate: tests green (+34 more)

### Community 7 - "BrainService"
Cohesion: 0.06
Nodes (16): _connect(), _look(), main(), _photo(), _ping(), _serve(), _status(), _teleop() (+8 more)

### Community 8 - "link.py"
Cohesion: 0.10
Nodes (6): _Inbox, InMemoryLink, Message, MqttLink, MqttSettings, topic_matches()

### Community 9 - "service.py"
Cohesion: 0.13
Nodes (7): 1. Requirements, resolve_dirs(), SkillLibrary, EventBus, make_vision(), test_repo_skills_dir_resolves_to_repo_root(), test_skills_always_on_and_index()

### Community 10 - "graph.py"
Cohesion: 0.14
Nodes (13): AgentState, build_graph(), call_model(), execute(), gate(), run_one(), _calls(), classify() (+5 more)

### Community 11 - "B.2 Body (Raspberry Pi) — `spider-robot/body/`"
Cohesion: 0.08
Nodes (24): B.2 Body (Raspberry Pi) — `spider-robot/body/`, `spider-robot/body/config/robot.example.yaml`, `spider-robot/body/config/robot.sim.yaml`, `spider-robot/body/lidar_bridge/CMakeLists.txt`, `spider-robot/body/lidar_bridge/lidar_bridge.cpp`, `spider-robot/body/pyproject.toml`, `spider-robot/body/src/spider_body/calibrate.py`, `spider-robot/body/src/spider_body/config.py` (+16 more)

### Community 12 - "Supervisor"
Cohesion: 0.09
Nodes (8): TaskSupervisor, allowed_origins(), create_app(), ws(), pump_commands(), handle(), Stopped, Supervisor

### Community 13 - "tools.py"
Cohesion: 0.24
Nodes (10): _A, BodyArgs, LookArgs, PostureArgs, RecallArgs, RememberArgs, SkillArgs, TurnArgs (+2 more)

### Community 14 - "B.3 Brain (AWS / local) — `spider-robot/brain/`"
Cohesion: 0.10
Nodes (20): B.3 Brain (AWS / local) — `spider-robot/brain/`, `spider-robot/brain/.env.example`, `spider-robot/brain/pyproject.toml`, `spider-robot/brain/src/spider_brain/calls.py`, `spider-robot/brain/src/spider_brain/config.py`, `spider-robot/brain/src/spider_brain/graph.py`, `spider-robot/brain/src/spider_brain/__init__.py`, `spider-robot/brain/src/spider_brain/main.py` (+12 more)

### Community 15 - "test_brain.py"
Cohesion: 0.22
Nodes (13): _client_with_body(), FakeVision, _sim_body(), test_dashboard_rejects_bad_origin_and_token(), test_dashboard_stop_cancels_running_walk(), test_end_to_end_walk_look_and_obstacle_stop(), test_high_risk_without_dashboard_is_rejected_not_hung(), test_liquid_planner_parses_tool_calls() (+5 more)

### Community 16 - "lidar_bridge.cpp"
Cohesion: 0.12
Nodes (6): CloudHeader, id, n, stamp, env_or(), main()

### Community 17 - "ToolCall"
Cohesion: 0.18
Nodes (6): PlanStep, ToolCall, Planner, ScriptedPlanner, TwoCallPlanner, factory()

### Community 18 - "ClaudePlanner"
Cohesion: 0.24
Nodes (7): ClaudePlanner, _Block, FakeAnthropic, settings(), test_claude_planner_roundtrip(), test_claude_refusal_ends_task(), test_claude_task_budget_stops_the_task()

### Community 19 - "B.4 Infrastructure — `spider-robot/infra/`"
Cohesion: 0.15
Nodes (13): B.4 Infrastructure — `spider-robot/infra/`, `spider-robot/infra/aws/body-policy.json`, `spider-robot/infra/aws/brain-policy.json`, `spider-robot/infra/aws/iot_setup.sh`, `spider-robot/infra/ec2/liquid-planner.service`, `spider-robot/infra/ec2/liquid-vision.service`, `spider-robot/infra/ec2/run-brain.sh`, `spider-robot/infra/ec2/setup_ec2.sh` (+5 more)

### Community 21 - "Settings"
Cohesion: 0.12
Nodes (8): Settings, build_route(), LiquidPlanner, make_planner(), OpenAICompatPlanner, anthropic_tools(), openai_tools(), test_tool_schemas_are_strict_compatible()

### Community 22 - "B.1 Shared protocol and link — `spider-robot/common/`"
Cohesion: 0.18
Nodes (10): B.0 Project root — `spider-robot/`, B.1 Shared protocol and link — `spider-robot/common/`, Part B — Files, `spider-robot/common/pyproject.toml`, `spider-robot/common/src/spider_common/__init__.py`, `spider-robot/common/src/spider_common/link.py`, `spider-robot/common/src/spider_common/protocol.py`, `spider-robot/common/tests/test_protocol.py` (+2 more)

### Community 23 - "memory.py"
Cohesion: 0.10
Nodes (12): cfg(), Reasoning depth, Robot reasoning, Safety overrides everything, The loop, Fact, Memory, _words() (+4 more)

### Community 25 - "Spider robot"
Cohesion: 0.50
Nodes (3): Run the simulator (no hardware), Spider robot, Tests

### Community 26 - "spider-common"
Cohesion: 0.67
Nodes (3): spider-body, spider-brain, spider-common

### Community 36 - "VoiceService"
Cohesion: 0.15
Nodes (6): _transient(), VoiceService, FakeGemini, test_voice_degrades_to_text_only(), test_voice_speak_makes_ogg_with_real_ffmpeg(), test_voice_transcribe_uses_configured_model()

### Community 37 - "SafetyGuard"
Cohesion: 0.22
Nodes (11): SafetyCfg, corridor_clearance(), Limited, SafetyGuard, summary_with(), test_near_object_outside_footprint_is_seen(), test_obstacle_blocks_forward_but_not_backward(), test_slow_zone_scales_speed() (+3 more)

### Community 38 - "Robot"
Cohesion: 0.25
Nodes (3): command_loop(), sit_and_relax(), Robot

### Community 40 - "LidarSummary"
Cohesion: 0.19
Nodes (4): S3 — Simulator (agent) · Gate: stands, walks, stops; ping works, NoLidar, SimLidar, LidarSummary

### Community 41 - "Link"
Cohesion: 0.18
Nodes (4): state_loop(), Link, Topics, test_topics()

### Community 42 - "spider_body/main.py"
Cohesion: 0.28
Nodes (5): build_link(), control_loop(), main(), run(), sd_notify()

### Community 43 - "test_safety_lidar.py"
Cohesion: 0.23
Nodes (7): FakeSerial, test_config_rejects_unsafe_stop_distance(), test_corridor_catches_side_obstacle_a_cone_missed(), test_corridor_measures_from_footprint_edge(), test_processor_builds_sector_map(), test_ssc32u_group_moves_changed_only_and_rate_limited(), test_ssc_rejects_9600_baud()

### Community 44 - "RoutedPlanner"
Cohesion: 0.27
Nodes (5): _is_provider_failure(), RoutedPlanner, test_router_budget_counts_all_models(), test_router_escalates_simple_tier_after_errors(), test_router_falls_back_when_provider_is_down()

### Community 48 - "RoutedVision"
Cohesion: 0.25
Nodes (3): RoutedVision, DownVision, test_vision_falls_back_to_backup()

### Community 50 - "test_telegram_owner_flow_with_approval_buttons_and_voice"
Cohesion: 0.32
Nodes (3): FakeTelegram, msg(), test_telegram_owner_flow_with_approval_buttons_and_voice()

### Community 52 - "AI tells — phrases and patterns to avoid"
Cohesion: 0.29
Nodes (6): AI tells — phrases and patterns to avoid, Arabic, English, Japanese (in chat with the user), Quick self-check before sending, Structural tells (all languages)

### Community 53 - "test_protocol.py"
Cohesion: 0.33
Nodes (3): parse_command(), test_bad_commands_rejected(), test_parse_move_roundtrip()

### Community 56 - "3. Hardware"
Cohesion: 0.40
Nodes (5): 3.1 Bill of materials, 3.2 Power (owner's design) and rules, 3.3 Wiring table, 3.4 LiDAR and camera mounting, 3. Hardware

### Community 58 - "Talking with Arabic speakers"
Cohesion: 0.40
Nodes (4): Examples, Pick the register from the user's own words, Rules of thumb, Talking with Arabic speakers

### Community 59 - "Talking with users in Japanese"
Cohesion: 0.40
Nodes (4): Chat register, Examples, Mixed-language users, Talking with users in Japanese

### Community 60 - "Robot conversation"
Cohesion: 0.40
Nodes (4): Avoid, Habits, Language files, Robot conversation

## Knowledge Gaps
- **7 isolated node(s):** `stamp`, `id`, `n`, `spider-body`, `spider-brain` (+2 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 400 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **21 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Spider Robot — Execution Plan for a Coding Agent` connect `RobotClient` to `camera.py`, `6. Step-by-step execution`, `service.py`, `B.1 Shared protocol and link — `spider-robot/common/``, `3. Hardware`?**
  _High betweenness centrality (0.140) - this node is a cross-community bridge._
- **Are the 25 inferred relationships involving `RobotClient` (e.g. with `_photo()` and `EventBus`) actually correct?**
  _`RobotClient` has 25 INFERRED edges - model-reasoned connections that need verification._
- **What connects `stamp`, `id`, `n` to the rest of the system?**
  _7 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `camera.py` be split into smaller, more focused modules?**
  _Cohesion score 0.1010752688172043 - nodes in this community are weakly interconnected._
- **Why does `Part B — Files` connect `B.1 Shared protocol and link — `spider-robot/common/`` to `B.4 Infrastructure — `spider-robot/infra/``, `B.2 Body (Raspberry Pi) — `spider-robot/body/``, `B.3 Brain (AWS / local) — `spider-robot/brain/``?**
  _High betweenness centrality (0.114) - this node is a cross-community bridge._
- **Are the 26 inferred relationships involving `Robot` (e.g. with `command_loop()` and `control_loop()`) actually correct?**
  _`Robot` has 26 INFERRED edges - model-reasoned connections that need verification._
- **Should `spider_body/config.py` be split into smaller, more focused modules?**
  _Cohesion score 0.07337526205450734 - nodes in this community are weakly interconnected._