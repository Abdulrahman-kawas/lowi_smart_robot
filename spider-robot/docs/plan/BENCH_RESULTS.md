## P05, 2026-11-11

- Work mode: factory mode 0 confirmed from the SDK README bit table (bit0 FOV, bit1 2D, bit2 IMU off, bit3 serial, bit4 wait). IMU already enabled; no provisioning was needed. NEGA choice deferred until the mount is decided.
- IMU: arrives at about 101 msg/s with IMU_DECIMATE=10 (504-505 per 5 s), so the raw IMU rate is about 1 kHz, not 500 Hz. Design expects 50 Hz; needs IMU_DECIMATE=20 (follow-up).
- Clouds: 60 per 5 s (12 Hz), about 2,690 points each, each covering 350-360 deg of azimuth.
- Warm-up: 23 minutes from cold power-on (12:03) to continuous clouds, cold room in winter; the LiDAR started and stopped repeatedly while warming.
- Body with servo power disconnected: mode relaxed, roll -0.7, pitch -1.8, lidar_age 0.03, rt_ok True, loop_overruns 1.
- Fix applied on the Pi by the owner: /dev/ttyUSB0 (SSC-32U, FTDI 0403:6001) was group plugdev and spider-body could not open it. Added /etc/udev/rules.d/99-spider-ssc32u.rules setting GROUP="dialout", MODE="0660". Needs adding to the repo (follow-up).
- Low and narrow object test: inconclusive. Cluttered room, the LiDAR was at REPLACE_HEIGHT cm, and the operator's body near the sensor dominated the readings. To repeat after mounting on the robot (P09).
- Mount decision: deferred to the robot build; inverted mast mount recommended, plus downward cliff sensors as a planned addition.
## P06, 2026-11-11

P06 RT1 deferred. Run 1 (rt disabled, 10 min): not completed. The shipped-setting run is still to do and must pass before P08.
## P07, 2026-11-11

- B-F1 PASS: Wi-Fi off, clock 2000-01-01. All local services active (mosquitto, spider-gateway, spider-lidar, spider-sysmon), spider-body active with rt_ok=True, a Stop sent by spider-robotctl reached the body (event kind ack, detail stopping), and the gateway boot chain has no network-online.target. Wi-Fi and NTP restored afterwards.
- LiDAR after reboot: the new restart logic worked ("no clouds for 3 s; sent start rotation again", then clouds resumed); stable afterwards (4800 clouds continuous, 60 clouds and 252 imu per 5 s).
- FI1 PASS: kill -9 spider-body, back after 4680 ms.
- FI2 PARTIAL: kill -STOP spider-body, systemd restarted it after 5559 ms (target 2 s). Servos hold their last pose meanwhile; the M4 hardware watchdog covers this case. Follow-up: consider a shorter RestartSec.
- FI3 PASS: kill -9 lidar_bridge, back after 2158 ms. The body's idle state period (5 s) was too slow to show the stale gap; stale-data blocking is covered by simulator tests.
- FI4 PASS: kill -9 spider-gateway, offline last will published (1), gateway back active.
- FI5 PASS: mosquitto stopped, the body logged the disconnect; after start, status shows mode=relaxed and gateway online.
- B-F2: deferred by the owner (risk of SD/SSD corruption); to run before relying on the robot.
Note: spider-robotctl is not on cron's PATH; use /usr/local/bin/spider-robotctl in boot scripts.
## Hardware session, 2026-11-17

Servos not fitted (boards only) for the whole session. No Move, Posture, Perform, Reach or EStopRelease was sent. spider-body ran only in owner-started windows.

### Part 1, Pi inventory

- Pi 4: kernel 6.18.60, throttled=0x0, 30-35 C, 3.3 GiB available, root on the USB SSD (2% used), no failed units.
- Services: gateway, lidar, mosquitto, sysmon, ollama active and enabled; body, camera, recorder, voice, button off.
- Cameras: AKASO Brave 7 LE (USB, behind two chained USB 2.0 hubs, /dev/v4l/by-id/usb-AKASO_Brave_7_LE_00.00.01-video-index0). OV5647 5 MP ribbon camera (CSI, found only after a power cycle; it was plugged in live). With the ribbon camera fitted, unicam takes /dev/video0 and the Brave moves to /dev/video1.
- Audio: the only microphone is the Brave's built-in one; playback is HDMI and the 3.5 mm jack only. Microphone and speaker deferred by the owner.
- SSC-32U: FTDI FT232R on /dev/ttyUSB0. LiDAR: Ethernet unplugged at the start, connected later.

### Part 2, home server and Lowi

- Server: up 16 days, 9.0 GiB available, / 30%, /data 1%, /backup 4%, CPU 28 C, no failed units. llama-planner (LFM2.5-1.2B) 0.46 s cold, 0.30 s warm; llama-vision (LFM2.5-VL-1.6B) 0.33 s, 0.19 s; about 42 tokens/s each.
- Lowi was still on AWS. Its WhatsApp session got a LOGOUT from WhatsApp on 2026-11-16 09:42 JST (the home copy was not running).
- Moved home at 07:31 JST: 20 AWS user units stopped and disabled (list saved on AWS); 1,259 changed files (87.6 MB) copied, key memory files byte-identical, overwritten home files kept in /backup/lowi/pre-cutover-2026-11-17; linger on; 13 services and 8 timers running. Fixes on the way: Lowi's virtual screen moved from display :1 (taken by the GNOME desktop) to :99 in 5 unit files; three stale Chromium Singleton links (AWS hostname) removed; WhatsApp relinked by QR at 07:33:54.
- Checks from the owner's phone: Telegram first reply 9.2 s and 9.7 s; WhatsApp voice note answered in about 9 s; memory present. Lowi's health check 15/15. 7.4 GiB available with brain, both models and Lowi.
- Telegram voice notes failed: tools/office_files.py read /home/ka/Desktop/hunt_job/.env, which user ubuntu may not read. Fixed in the jobhunt repo on the server (commit 0f02b9b, not pushed); transcription then took 4.8-8.1 s.

### Part 3, cameras

- Eye: the Brave 7 LE, set by its by-id path in /etc/spider/robot.yaml (backup robot.yaml.bak-2026-11-17). Code: camera.device accepts a path (6925d71).
- Bug found and fixed (68593e8): after an idle gap OpenCvCamera returned a frame as old as the gap (0.6 s idle: 494 ms old; 20 s idle: 19.9 s old). Now one buffer and a timestamp check: 21-24 ms old at any gap, 29-54 ms per snapshot.
- Loop under capture every 0.6 s, 2 min each, LiDAR off: no camera 2.13 ms max lateness, 0 overruns, core 0 4.8%; Brave 2.17 ms, 0 overruns, core 0 8.6%, 200/200 snapshots, 42 ms mean, 1.4% of one core; ribbon (picamera2, system Python) 2.59 ms, 0 overruns, core 0 7.6%, 200/200, 70 ms mean, 2.3% of one core. rt_ok true throughout.
- The ribbon camera is not usable by the robot code yet: the body venv cannot import picamera2.

### Part 4, broker files

- /etc/mosquitto/spider/acl (644 root:root) and passwords (640 root:mosquitto) set to 640 mosquitto:mosquitto; mosquitto 2.0.21 warnings after restart: 0 (11 restarts with 4 warnings each before). Gateway, sysmon and the home brain (TLS over Tailscale) reconnected. setup_pi.sh and mqtt_passwords.sh fixed (d2f8a8a).
- Microphone and speaker checks (hw_check.sh) deferred: not connected.

### Part 5, LiDAR

- Warm-up 18 min (cold room). Clouds 12.6 Hz, about 2,690 points each; IMU 52.8 Hz (IMU_DECIMATE=20). lidar_age_s with the body running: 0.01-0.08 s.
- Box test (an air fryer, LiDAR upright, roll 2-3 deg by the body's accelerometer formula): detected at two placements, about 27-30 cm wide, nearest point 0.18-0.29 m. Distance accuracy not established (hand estimate about 0.12-0.14 m to the optical centre). The owner's "front" was at about -60 deg in the LiDAR frame: mount_yaw_deg must be set after mounting.
- Note: the L2's IMU quaternion is in a different frame from the body's accelerometer formula; read roll and pitch with the body's formula.

### Part 6, P06

- Not run. The LiDAR was switched off afterwards at the owner's request (heat); P06 needs about 2.5 h with the LiDAR warm.

### Part 7, whole chain

- MQTT over Tailscale with mTLS from the home server; gateway online; brain sources remote and planner alive (0.16 s, 3-4 ms queue delay); brain state under 0.1 s old.
- Stop from the brain: 20/20 acks, p50 12 ms, max 91 ms; owner-priority Stop acked in 9 ms. Stop from spider-robotctl: ack stopping.
- Photo through the brain with server vision: 7.0 s total, answer correct.
- E-stop from the brain: latched in 23 ms; still latched 1 min later and after the body stopped (/var/lib/spider/estop.latch, 08:21 JST). Not released.
- Voice not installed: not tested.

### Part 8, mobile app

- Brain on the server updated from the mobile-app branch (backup ~/spider-robot-backup-2026-11-17.tgz, brain.env.bak-2026-11-17), SB_MOBILE=true, `tailscale serve --bg 8765` (tailnet only; HTTPS certificates enabled by the owner). /v1/hello 200, /v1/state 401 without a token.
- App built from Xcode on the owner's iPhone (free Apple team: the signing expires 2026-11-24). The iPhone joined the tailnet; pairing worked at 09:17.
- Hold to talk added on the owner's request: brain e657cb2 and 73a282d, app 83d0a2d. On the server with real Whisper small and the local model: "مرحبا لوي، شو عم تعمل هلق" heard exactly, answered in 4.6 s; "قف" -> STOP in 1.0 s; "قف قف" -> STOP in 1.1 s; silence and room noise -> no speech without Whisper. A lone "قف" was misheard ("ونشاهدوا") until short clips got 0.5 s padding and a stop-word prompt; that prompt makes Whisper invent "وقف" loops on silence, hence the loudness gate.
- Not yet done on the phone: LIVE link, frame age, photo, STOP and E-stop with the body running, and talking from the device.

### Open problems and proposed fixes

1. P06 not run: run it before P08 with the LiDAR warm (about 2.5 h).
2. E-stop latched since 08:21 JST: the owner releases it (app, with a fresh photo) before P08.
3. No speaker, and only the camera's microphone: connect a USB microphone and speaker, then run hw_check.sh.
4. hw_check.sh takes the first /dev/video*, now the ribbon camera: make it use camera.device from robot.yaml.
5. spider-camera is not enabled at boot, so the app and the brain get no frames after a Pi reboot: enable it.
6. The Brave switches off on power loss and needs "PC Camera" picked by hand: use a plain UVC webcam as the eye, or accept the manual step.
7. Ribbon camera unusable from the body venv: recreate the venv with --system-site-packages (or a .pth to dist-packages) if a rear camera is wanted.
8. Core 0 load rises 3-4 points with a camera on: check /proc/interrupts during P06 and move the USB or CSI interrupt off core 0 if needed.
9. LiDAR mount: set and verify mount_yaw_deg after mounting; repeat the box test with a tape measure at 0.5, 1 and 2 m (P09).
10. spider-body logs "shutting down: sitting and relaxing servos" under a latched E-stop although it does neither: log the E-stop case separately.
11. Talk answers from LFM2.5-1.2B are weak: put a stronger route first in SB_TALK_ROUTES (anthropic, gemini or compat), and add the lowi route once Lowi is connected to the robot. Note: "بس" and "خلاص" inside a sentence also stop the robot (same lists as the Pi voice loop, the safe direction).
12. App signing expires 2026-11-24 (free team): run it from Xcode again each week, or use a paid developer account.
13. Lowi follow-ups: the jobhunt repo's deploy units still use display :1 (make it a setting); snap desktop integration adds portal and keyring errors for user ubuntu (disable it for that user); push or merge jobhunt 0f02b9b; snapshot the AWS server and stop it after a few calm days.
14. The jobhunt CLAUDE.md section 6 blueprint was written against commit 899a672, which is not the code that runs (the orchestrator runs from ~/voice-agent, 6,238 lines, not 704): re-audit against ~/voice-agent and ~/jobhunt before applying any of it, and move section 6 out of CLAUDE.md.
