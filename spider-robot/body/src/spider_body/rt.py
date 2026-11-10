"""Real-time setup for the control process.

Order matters: pin_cpu() runs first, while there is still only one thread, so every thread created
later (the MQTT network thread, the executor) stays on the reserved core. enable_fifo() runs after
the MQTT thread exists, and uses SCHED_RESET_ON_FORK, so only this thread is real-time.

Every step is best-effort: on a machine that does not support it (a development laptop) the process
keeps running and reports rt_ok=False in RobotState, where the health model can see it.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys as _python_sys
from typing import Any

from .config import RtCfg

log = logging.getLogger(__name__)

SCHED_RESET_ON_FORK = 0x40000000
MCL_CURRENT, MCL_FUTURE = 1, 2


def _mlockall() -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.mlockall(MCL_CURRENT | MCL_FUTURE) != 0:
        raise OSError(ctypes.get_errno(), "mlockall failed")


def set_gil_interval(cfg: RtCfg) -> None:
    """Another thread (MQTT, ZeroMQ) may hold the interpreter for at most this long."""
    _python_sys.setswitchinterval(cfg.gil_switch_ms / 1000.0)


def pin_cpu(cfg: RtCfg, sys: Any = os) -> bool:
    if not cfg.enabled:
        return False
    if not hasattr(sys, "sched_setaffinity"):
        log.warning("CPU pinning is not available on this platform")
        return False
    try:
        sys.sched_setaffinity(0, {cfg.cpu})
    except OSError as exc:
        log.warning("could not pin to CPU %d: %s", cfg.cpu, exc)
        return False
    return True


def enable_fifo(cfg: RtCfg, sys: Any = os, lock: Any = _mlockall) -> bool:
    """SCHED_FIFO for this thread and, optionally, locked memory. True only if both worked."""
    if not cfg.enabled:
        return False
    if not hasattr(sys, "sched_setscheduler"):
        log.warning("SCHED_FIFO is not available on this platform")
        return False
    locked = True
    if cfg.lock_memory:
        try:
            lock()
        except OSError as exc:
            locked = False
            log.warning("could not lock memory: %s", exc)
    try:
        sys.sched_setscheduler(0, sys.SCHED_FIFO | SCHED_RESET_ON_FORK,
                               sys.sched_param(cfg.priority))
    except OSError as exc:
        log.warning("could not switch to SCHED_FIFO: %s", exc)
        return False
    return locked
