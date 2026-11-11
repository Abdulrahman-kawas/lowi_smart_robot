## P05, 2026-11-11

- Work mode: factory mode 0 confirmed from the SDK README bit table (bit0 FOV, bit1 2D, bit2 IMU off, bit3 serial, bit4 wait). IMU already enabled; no provisioning was needed. NEGA choice deferred until the mount is decided.
- IMU: arrives at about 101 msg/s with IMU_DECIMATE=10 (504-505 per 5 s), so the raw IMU rate is about 1 kHz, not 500 Hz. Design expects 50 Hz; needs IMU_DECIMATE=20 (follow-up).
- Clouds: 60 per 5 s (12 Hz), about 2,690 points each, each covering 350-360 deg of azimuth.
- Warm-up: 23 minutes from cold power-on (12:03) to continuous clouds, cold room in winter; the LiDAR started and stopped repeatedly while warming.
- Body with servo power disconnected: mode relaxed, roll -0.7, pitch -1.8, lidar_age 0.03, rt_ok True, loop_overruns 1.
- Fix applied on the Pi by the owner: /dev/ttyUSB0 (SSC-32U, FTDI 0403:6001) was group plugdev and spider-body could not open it. Added /etc/udev/rules.d/99-spider-ssc32u.rules setting GROUP="dialout", MODE="0660". Needs adding to the repo (follow-up).
- Low and narrow object test: inconclusive. Cluttered room, the LiDAR was at REPLACE_HEIGHT cm, and the operator's body near the sensor dominated the readings. To repeat after mounting on the robot (P09).
- Mount decision: deferred to the robot build; inverted mast mount recommended, plus downward cliff sensors as a planned addition.
