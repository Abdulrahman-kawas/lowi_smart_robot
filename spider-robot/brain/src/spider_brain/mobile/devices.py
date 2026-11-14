"""Paired phones and the one-time codes that pair them. Only hashes are stored.

`spider-brain pair` runs as its own process and writes the code's hash to pairing.json; the
running brain checks attempts against that file. `spider-brain devices revoke` edits devices.json,
and the running brain notices the change on the next request and within a second for open
sockets.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import secrets
import time
import unicodedata
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

BRAIN_ROOT = Path(__file__).resolve().parents[3]  # spider-robot/brain
CODE_DIGITS = 6
MAX_CODE_ATTEMPTS = 5  # wrong codes before the code is thrown away
MIN_ATTEMPT_GAP_S = 1.0  # one attempt per second, from anyone
MAX_TOKEN_CHARS = 200
MAX_NAME_CHARS = 40


class RateLimited(RuntimeError):
    pass


def data_dir(configured: str) -> Path:
    """SB_MOBILE_DATA_DIR, relative to the brain folder like the other data paths."""
    path = Path(configured).expanduser()
    return path if path.is_absolute() else BRAIN_ROOT / path


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_private(path: Path, data: dict) -> None:
    """Atomic write, readable by the owner only."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(path.parent, 0o700)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def clean_name(name: object) -> str | None:
    """A device name to show and to revoke by: 1-40 printable characters, any script."""
    if not isinstance(name, str):
        return None
    name = " ".join(name.split())
    if not 1 <= len(name) <= MAX_NAME_CHARS:
        return None
    if any(unicodedata.category(ch).startswith("C") for ch in name):
        return None
    return name


@dataclass(frozen=True)
class Device:
    name: str
    token_sha256: str
    paired_at: float


class DeviceStore:
    def __init__(self, directory: Path, wall: Callable[[], float] = time.time) -> None:
        self.path = directory / "devices.json"
        self.wall = wall
        self._stamp: tuple[int, int] | None = None
        self._devices: dict[str, Device] = {}

    def _load(self) -> None:
        try:
            st = self.path.stat()
        except FileNotFoundError:
            self._stamp, self._devices = None, {}
            return
        stamp = (st.st_mtime_ns, st.st_size)  # size too: two writes within one mtime tick
        if stamp == self._stamp:
            return
        data = json.loads(self.path.read_text("utf-8") or "{}")
        self._devices = {d["name"]: Device(**d) for d in data.get("devices", [])}
        self._stamp = stamp

    def _save(self) -> None:
        _write_private(self.path, {"devices": [asdict(d) for d in self._devices.values()]})
        self._stamp = None  # reload our own write next time

    def add(self, name: str) -> str:
        """Pair a device and return its token. Pairing again under the same name replaces it."""
        self._load()
        token = secrets.token_urlsafe(32)
        self._devices[name] = Device(name, _sha256(token), self.wall())
        self._save()
        return token

    def check(self, token: object) -> str | None:
        """The device name for a token, or None. Compares against every device in constant time."""
        if not isinstance(token, str) or not 0 < len(token) <= MAX_TOKEN_CHARS:
            return None
        self._load()
        presented = _sha256(token)
        found = None
        for device in self._devices.values():
            if hmac.compare_digest(presented, device.token_sha256):
                found = device.name
        return found

    def known(self, name: str) -> bool:
        self._load()
        return name in self._devices

    def list(self) -> list[Device]:
        self._load()
        return sorted(self._devices.values(), key=lambda d: d.paired_at)

    def revoke(self, name: str) -> bool:
        self._load()
        if self._devices.pop(name, None) is None:
            return False
        self._save()
        return True


class PairingCodes:
    def __init__(
        self, directory: Path, ttl_s: float = 120.0, wall: Callable[[], float] = time.time,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.path = directory / "pairing.json"
        self.ttl_s = ttl_s
        self.wall, self.clock = wall, clock
        self._attempts: dict[str, int] = {}
        self._last_attempt = -float("inf")

    def issue(self) -> str:
        """A new 6-digit code. It replaces any earlier one."""
        code = f"{secrets.randbelow(10**CODE_DIGITS):0{CODE_DIGITS}d}"
        salt = secrets.token_hex(16)
        _write_private(self.path, {"id": secrets.token_hex(8), "salt": salt,
                                   "sha256": _sha256(salt + code),
                                   "expires": self.wall() + self.ttl_s})
        return code

    def _discard(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()

    def redeem(self, code: object) -> bool:
        """True once for the right code before it expires. Raises RateLimited if too fast."""
        now = self.clock()
        if now - self._last_attempt < MIN_ATTEMPT_GAP_S:
            raise RateLimited("one pairing attempt per second")
        self._last_attempt = now
        try:
            pending = json.loads(self.path.read_text("utf-8"))
        except (FileNotFoundError, ValueError):
            return False
        if self.wall() >= pending.get("expires", 0.0):
            self._discard()
            return False
        tries = self._attempts.get(pending["id"], 0) + 1
        self._attempts[pending["id"]] = tries
        if tries > MAX_CODE_ATTEMPTS:
            self._discard()
            return False
        presented = code if isinstance(code, str) and len(code) <= 16 else ""
        if not hmac.compare_digest(_sha256(pending["salt"] + presented), pending["sha256"]):
            if tries == MAX_CODE_ATTEMPTS:
                self._discard()
            return False
        self._discard()  # works once
        return True
