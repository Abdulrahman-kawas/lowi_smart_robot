"""Servo drivers for the 18 leg servos.

* SscServoBank - Lynxmotion SSC-32U over USB serial (the owner's chosen controller).
* PcaServoBank - two PCA9685 16-channel PWM boards on I2C (0x40, 0x41), the alternative.

PCA9685 notes:

Minimal register-level driver on smbus2, so there is no Adafruit Blinka / GPIO dependency.
Wiring: Pi 3V3 -> VCC, GND -> GND, SDA (GPIO2) -> SDA, SCL (GPIO3) -> SCL on both boards;
servo power (V+) comes from a separate 5-7.4 V high-current BEC, never from the Pi.
"""

from __future__ import annotations

import logging
import time
from typing import Protocol

from ..config import JOINTS, BodyConfig, ServoCfg

log = logging.getLogger(__name__)

_MODE1, _MODE2, _PRESCALE, _LED0, _ALL_LED_OFF_H = 0x00, 0x01, 0xFE, 0x06, 0xFD


class PCA9685:
    def __init__(self, bus, address: int, freq_hz: float = 50.0, osc_hz: float = 25e6) -> None:
        self.bus, self.address = bus, address
        self.ticks: list[int | None] = [None] * 16  # last value written per channel
        prescale = int(round(osc_hz / (4096.0 * freq_hz))) - 1
        self.period_us = 1e6 / (osc_hz / (4096.0 * (prescale + 1)))
        old = bus.read_byte_data(address, _MODE1)
        bus.write_byte_data(address, _MODE1, (old & 0x7F) | 0x10)  # sleep to set prescale
        bus.write_byte_data(address, _PRESCALE, prescale)
        bus.write_byte_data(address, _MODE1, old & 0xEF)  # wake
        time.sleep(0.005)
        bus.write_byte_data(address, _MODE1, (old & 0xEF) | 0xA0)  # restart + auto-increment
        bus.write_byte_data(address, _MODE2, 0x04)  # totem-pole outputs
        self.all_off()

    def to_ticks(self, pulse_us: float) -> int:
        return max(0, min(4095, int(round(pulse_us * 4096.0 / self.period_us))))

    def set_pulse_us(self, channel: int, pulse_us: float) -> None:
        self.write_channels({channel: self.to_ticks(pulse_us)})

    def write_channels(self, changes: dict[int, int]) -> None:
        """Write several channels in ONE I2C transaction (registers auto-increment).

        Only the span between the lowest and highest changed channel is sent; unchanged
        channels inside the span are re-sent with their cached value (unused ones = full off).
        """
        if not changes:
            return
        from smbus2 import i2c_msg

        lo, hi = min(changes), max(changes)
        data = [_LED0 + 4 * lo]
        for ch in range(lo, hi + 1):
            t = changes.get(ch, self.ticks[ch])
            data += [0, 0, 0, 0x10] if t is None else [0, 0, t & 0xFF, t >> 8]
        msg = i2c_msg.write(self.address, data)
        try:
            self.bus.i2c_rdwr(msg)
        except OSError:  # one retry: a single noisy transfer is common on long servo wiring
            self.bus.i2c_rdwr(i2c_msg.write(self.address, data))
        for ch, t in changes.items():
            self.ticks[ch] = t

    def off(self, channel: int) -> None:
        self.bus.write_i2c_block_data(self.address, _LED0 + 4 * channel, [0, 0, 0, 0x10])
        self.ticks[channel] = None

    def all_off(self) -> None:
        self.bus.write_byte_data(self.address, _ALL_LED_OFF_H, 0x10)
        self.ticks = [None] * 16


class ServoBank(Protocol):
    def write(self, servo_deg: dict[str, float]) -> None:
        """joint id ("LF.coxa") -> servo command in degrees (0..180, already calibrated)."""

    def relax(self) -> None:
        """Stop sending pulses: servos go limp (no holding torque)."""


def clamp_servo(cfg: ServoCfg, deg: float) -> tuple[float, bool]:
    clamped = max(cfg.min_deg, min(cfg.max_deg, deg))
    return clamped, clamped != deg


class PcaServoBank:
    def __init__(self, cfg: BodyConfig, bus=None) -> None:
        if bus is None:
            from smbus2 import SMBus

            bus = SMBus(cfg.pca.i2c_bus)
        self.cfg = cfg
        self.bus = bus
        self.boards = [
            PCA9685(self.bus, addr, cfg.pca.freq_hz, cfg.pca.osc_hz) for addr in cfg.pca.addresses
        ]
        self.servos: dict[str, ServoCfg] = {
            f"{leg.name}.{j}": getattr(leg, j) for leg in cfg.legs for j in JOINTS
        }

    def _pulse(self, deg: float) -> float:
        return self.cfg.pulse.pulse_us(deg)

    def write(self, servo_deg: dict[str, float]) -> None:
        """Only channels whose 12-bit value changed are sent; at most one transfer per board.

        Standing still therefore costs no I2C traffic, and walking costs 2 transfers per tick
        instead of 18 (about 1.5 ms instead of ~4 ms at 400 kHz on a Pi 4).
        """
        changes: dict[int, dict[int, int]] = {}
        for joint_id, deg in servo_deg.items():
            s = self.servos[joint_id]
            deg, _ = clamp_servo(s, deg)
            board = self.boards[s.board]
            t = board.to_ticks(self._pulse(deg))
            if board.ticks[s.channel] != t:
                changes.setdefault(s.board, {})[s.channel] = t
        for b, ch in changes.items():
            self.boards[b].write_channels(ch)

    def write_raw(self, joint_id: str, deg: float) -> None:
        """Calibration only: no trims, no direction, only the 0..180 clamp."""
        s = self.servos[joint_id]
        self.boards[s.board].set_pulse_us(s.channel, self._pulse(max(0.0, min(180.0, deg))))

    def relax(self) -> None:
        for board in self.boards:
            board.all_off()


# 18 channels x len("#31P2500") + len("T40\r"): the longest group move this code sends.
MAX_GROUP_BYTES = 18 * 8 + 4


class FakeServoBank:
    """Records commands; used by tests and the simulator."""

    def __init__(self) -> None:
        self.last: dict[str, float] = {}
        self.relaxed = True
        self.writes = 0

    def write(self, servo_deg: dict[str, float]) -> None:
        self.last.update(servo_deg)
        self.relaxed = False
        self.writes += 1

    def write_raw(self, joint_id: str, deg: float) -> None:
        self.write({joint_id: deg})

    def relax(self) -> None:
        self.relaxed = True


class SscServoBank:
    """Lynxmotion SSC-32U (32 channels) over USB serial.

    Sends one group move per update: "#0P1500#1P1620 ... T40<CR>". Only changed channels are
    sent, at most `ssc.update_hz` times per second, and each move glides over T = 1/update_hz,
    so the 50 Hz gait stays smooth while the serial line carries ~4 KB/s (115200 baud = 11.5).
    """

    def __init__(self, cfg: BodyConfig, port=None, clock=time.monotonic) -> None:
        if port is None:
            import serial  # pyserial

            # A short write timeout: a stalled USB link must not hold up the 20 ms control tick.
            port = serial.Serial(cfg.ssc.port, cfg.ssc.baud, timeout=0.3, write_timeout=0.01)
        self.cfg = cfg
        self.ser = port
        self.clock = clock
        self.interval = 1.0 / cfg.ssc.update_hz
        # A tick that wakes 0.1 ms early against the last one must still send, or the group move
        # slips a whole tick and servos rest between glides. Tolerate up to about a quarter.
        self.min_gap = self.interval * 0.76
        self.servos: dict[str, ServoCfg] = {
            f"{leg.name}.{j}": getattr(leg, j) for leg in cfg.legs for j in JOINTS
        }
        self._sent: dict[int, int] = {}  # channel -> last pulse sent (us)
        self._pending: dict[int, int] = {}
        self._last_send = -1e9

    def _us(self, deg: float) -> int:
        return int(round(self.cfg.pulse.pulse_us(deg)))

    def write(self, servo_deg: dict[str, float]) -> None:
        for joint_id, deg in servo_deg.items():
            s = self.servos[joint_id]
            deg, _ = clamp_servo(s, deg)
            us = self._us(deg)
            if self._sent.get(s.channel) != us:
                self._pending[s.channel] = us
            else:
                self._pending.pop(s.channel, None)
        now = self.clock()
        if self._pending and now - self._last_send >= self.min_gap:
            if getattr(self.ser, "out_waiting", 0) > 2 * MAX_GROUP_BYTES:
                return  # the USB link is behind: skip this frame instead of queueing stale poses
            self._send(self._pending, int(round(self.interval * 1000)))
            self._last_send = now

    def _send(self, moves: dict[int, int], t_ms: int | None) -> None:
        cmd = "".join(f"#{ch}P{us}" for ch, us in sorted(moves.items()))
        if t_ms:
            cmd += f"T{t_ms}"
        self.ser.write((cmd + "\r").encode("ascii"))
        self._sent.update(moves)
        moves.clear()

    def write_raw(self, joint_id: str, deg: float) -> None:
        """Calibration only: no trims, no direction, only the 0..180 clamp; sent at once."""
        s = self.servos[joint_id]
        self._send({s.channel: self._us(max(0.0, min(180.0, deg)))}, None)

    def relax(self) -> None:
        """P0 stops the pulses on a channel (servo goes limp). Verify on the bench (S13)."""
        channels = sorted({s.channel for s in self.servos.values()})
        self.ser.write(("".join(f"#{ch}P0" for ch in channels) + "\r").encode("ascii"))
        self._sent.clear()
        self._pending.clear()

    def version(self) -> str:
        """Ask the board for its firmware version (connectivity check)."""
        self.ser.reset_input_buffer()
        self.ser.write(b"VER\r")
        return self.ser.read_until(b"\r").decode("ascii", "replace").strip()


def make_servo_bank(cfg: BodyConfig):
    return SscServoBank(cfg) if cfg.servo_driver == "ssc32u" else PcaServoBank(cfg)
