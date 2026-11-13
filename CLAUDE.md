> **Read `spider-robot/docs/ARCHITECTURE.md` first.** It is the agreed design and overrides this
> file where they differ (AWS is dropped, a command gateway is added, remote control is required).
>
> **Status (2026-11-09):** the architecture below is not implemented yet. The code in
> `spider-robot/` on branch `robot/spider-robot/m0-scaffold` is still an EC2/AWS IoT design with
> a Claude/LangGraph planner and no Ollama, NVIDIA NIM, messaging bots or Pi voice stack. The
> unmerged branch `origin/robot/spider-robot/part2-brain` adds a Telegram bot, WhatsApp alerts,
> brain-side voice, memory and skills. The code also differs from section 2 and 5.1 on
> one hardware point: the SSC-32U servo board is on USB and only generates pulses, while IK, gait
> and LiDAR/IMU safety all run on the Pi (`body/src/spider_body/robot.py`, 50 Hz tick).

# Robot System Architecture & Context (For Claude)

## 1. Project Overview
We are building a real-time interactive robot powered by a hybrid, distributed AI architecture across two local Linux machines (on the same LAN) plus a cloud API fallback. The primary goal is ultra-low latency for voice interaction, movement decisions, and hardware balance on the robot itself, while offloading heavy visual processing, 3D SLAM, and messaging bots to the secondary home Linux server.

---

## 2. Node 1: The Robot (Edge Device)
* **Hardware:** Raspberry Pi (4GB RAM), Camera module, Microphone & Speaker.
* **Sensors & Actuators:**
  * **Unitree 4D LiDAR L2** with built-in **IMU** (connected to the Pi for real-time balance, tilt correction, and immediate obstacle avoidance).
  * **Servo Controller Board:** Connected externally (via Serial/UART) to handle physical servo PWM and locomotion kinematics independently from the Pi's CPU.
* **Installed Software & AI Stack (Local on Pi):**
  * **OS:** Linux 64-bit.
  * **LLM Runtime:** `Ollama` configured with `CPUAffinity=1 2 3`, `OLLAMA_KEEP_ALIVE=-1`, and `OLLAMA_NUM_PARALLEL=1`.
  * **Core 0 Isolation:** Core 0 of the Raspberry Pi CPU is reserved strictly for hard real-time tasks (Unitree L2 LiDAR, IMU balance loop, and hardware serial communication).
  * **Local Fast Brain (Text/Router):** `hf.co/LiquidAI/LFM2.5-350M-GGUF` running locally on Ollama (`http://localhost:11434`). Used for instant (<300ms) offline command routing, quick conversational replies, and immediate movement decisions.
  * **Voice Input (VAD & STT):** `pyaudio` + `webrtcvad` (for instant silence detection) + `faster-whisper` (`tiny`/`int8` on CPU).
  * **Voice Output (Local TTS):** `piper-tts` (using `ar_JO-kareem-low.onnx` stored in `~/robot_brain/models/ar_voice.onnx`) and `espeak-ng` for zero-latency offline Arabic speech.
  * **Python Environment:** Located at `~/robot_brain/venv` with `faster-whisper`, `webrtcvad`, `pyaudio`, `piper-tts`, `openai`, `requests`, and `pyserial`.

---

## 3. Node 2: Home Linux Server (Heavy Compute & Offloading Node)
* **Role:** Always-on local Linux server on the same local network (`LAN_IP:11434`).
* **Installed Software & Tasks:**
  * **LLM/VLM Runtime:** `Ollama` exposed to the local network (`OLLAMA_HOST=0.0.0.0:11434`, `OLLAMA_KEEP_ALIVE=-1`).
  * **Local Vision Brain (VLM):** `hf.co/LiquidAI/LFM2.5-VL-1.6B-GGUF` (removed from the Pi to save RAM/CPU and hosted here instead). The Pi captures camera frames on demand and sends them over LAN to this server for local image understanding.
  * **Messaging Integrations:** Hosts the WhatsApp and Telegram bots, long-term memory/database, and heavy background tasks (such as 3D SLAM / point cloud mapping if needed).

---

## 4. Cloud Escalation (Deep Reasoning & Advanced Multimodal)
* **Provider:** NVIDIA NIM API (`https://integrate.api.nvidia.com/v1`) via the `openai` Python SDK.
* **Model:** `moonshotai/kimi-k3.1-pro` (Kimi K3.1 Pro).
* **Role:** Used when high-level reasoning, complex conversation, or advanced visual scene analysis is required and internet connectivity is available.

---

## 5. Execution & Routing Logic (How the System Works)
1. **Safety & Balance (Priority 0 - Pi Core 0):**
   * Unitree L2 LiDAR + IMU continuously monitor tilt and immediate obstacles. They communicate directly with the external servo controller board. AI processes must never block this loop.
2. **Real-Time Voice & Action Loop (Priority 1 - Pi Cores 1-3):**
   * Microphone listens using `webrtcvad` and cuts recording ~400ms after speech ends.
   * `faster-whisper` transcribes Arabic speech to text locally.
   * Text is sent to local `LiquidAI/LFM2.5-350M-GGUF` on the Pi (`format="json"`).
   * The model outputs a compact JSON decision: `{"act": "forward|back|left|right|stop|look|none", "say": "short Arabic response"}`.
   * Movement (`act`) and speech (`say` via Piper TTS) execute **in parallel (asynchronously)** so the robot moves and talks simultaneously.
3. **Vision & Deep Query Offloading (Priority 2 - LAN Server & Cloud):**
   * When the user asks the robot to look at something or asks a complex question, the local Pi model (`350M`) immediately replies with a filler action/phrase (e.g., `act="look"`, `say="لحظة أشوف"`) so there is zero perceived lag.
   * In the background, the Pi captures a snapshot from the camera and sends it either to:
     * **Home Linux Server (`http://<SERVER_IP>:11434`)** running `LiquidAI/LFM2.5-VL-1.6B-GGUF` for local offline vision analysis, OR
     * **NVIDIA NIM API (`moonshotai/kimi-k3.1-pro`)** for deep cloud vision/reasoning.
   * Once the response returns, the Pi speaks the detailed answer and executes any follow-up movement.

---

## 6. Instructions for Claude when Writing or Modifying Code
* **Never block the main hardware/IMU loop:** Always use non-blocking I/O, `asyncio`, or separate threads/processes for TTS, STT, camera capture, and network calls.
* **Respect RAM & CPU limits on the Pi (4GB):** Do not load vision models or heavy libraries on the Raspberry Pi. Keep all heavy vision requests pointed at the secondary Linux server IP or the Kimi API.
* **Keep Local LLM Prompts Short:** `LFM2.5-350M-GGUF` is a fast router/controller. Use strict JSON output schemas and low `temperature` (`0.1` - `0.2`) with a small token limit (`num_predict: 60`) to maintain sub-second latency.
