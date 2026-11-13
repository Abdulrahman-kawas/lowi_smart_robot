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
