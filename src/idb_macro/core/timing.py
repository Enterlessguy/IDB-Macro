"""Interval maths and a drift-free, interruptible scheduler."""

from __future__ import annotations

import contextlib
import math
import random
import sys
import threading
import time
from collections.abc import Iterator

MIN_INTERVAL_MS = 1.0
MAX_INTERVAL_MS = 24 * 60 * 60 * 1000.0
# Event.wait overshoots by up to a timer tick; the last stretch is spun.
_SPIN_WINDOW_S = 0.002


def interval_ms(hours: float = 0, minutes: float = 0, seconds: float = 0, millis: float = 0) -> float:
    total = ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis
    if not math.isfinite(total):
        raise ValueError("interval must be a finite number")
    return clamp_interval(total)


def clamp_interval(ms: float) -> float:
    if not math.isfinite(ms):
        raise ValueError("interval must be a finite number")
    return min(MAX_INTERVAL_MS, max(MIN_INTERVAL_MS, float(ms)))


def cps_to_interval_ms(cps: float) -> float:
    if not math.isfinite(cps) or cps <= 0:
        raise ValueError("clicks per second must be positive")
    return clamp_interval(1000.0 / cps)


def interval_to_cps(ms: float) -> float:
    return 1000.0 / clamp_interval(ms)


def jittered_ms(base_ms: float, jitter_ms: float, rng: random.Random | None = None) -> float:
    """Return ``base_ms`` shifted by a uniform random amount in ``±jitter_ms``."""
    if jitter_ms <= 0:
        return clamp_interval(base_ms)
    r = rng or random
    return clamp_interval(base_ms + r.uniform(-jitter_ms, jitter_ms))


def jitter_point(x: int, y: int, radius: int, rng: random.Random | None = None) -> tuple[int, int]:
    """Uniformly pick a point inside a circle of ``radius`` pixels around (x, y)."""
    if radius <= 0:
        return x, y
    r = rng or random
    dist = radius * math.sqrt(r.random())
    angle = r.uniform(0, 2 * math.pi)
    return x + round(dist * math.cos(angle)), y + round(dist * math.sin(angle))


class Scheduler:
    """Waits until absolute deadlines so per-tick work never accumulates drift."""

    def __init__(self, stop: threading.Event, clock=time.perf_counter):
        self.stop = stop
        self.clock = clock
        self.next_deadline = clock()

    def reset(self) -> None:
        self.next_deadline = self.clock()

    def advance(self, ms: float) -> None:
        self.next_deadline += ms / 1000.0
        now = self.clock()
        # After a long stall (sleep, debugger, busy target) do not burst to
        # catch up; resume the cadence from now.
        if self.next_deadline < now - 0.25:
            self.next_deadline = now

    def wait_next(self) -> bool:
        """Block until the current deadline. Returns False if stopped."""
        return self.wait_until(self.next_deadline)

    def sleep(self, ms: float) -> bool:
        """Interruptible relative sleep. Returns False if stopped."""
        return self.wait_until(self.clock() + max(0.0, ms) / 1000.0)

    def wait_until(self, deadline: float) -> bool:
        while True:
            if self.stop.is_set():
                return False
            remaining = deadline - self.clock()
            if remaining <= 0:
                return True
            if remaining > _SPIN_WINDOW_S:
                self.stop.wait(remaining - _SPIN_WINDOW_S)
            else:
                time.sleep(0)


@contextlib.contextmanager
def high_resolution_timer() -> Iterator[None]:
    """Raise the Windows timer resolution to 1 ms for the duration of a run."""
    if sys.platform != "win32":
        yield
        return
    import ctypes

    winmm = ctypes.WinDLL("winmm")
    raised = winmm.timeBeginPeriod(1) == 0
    try:
        yield
    finally:
        if raised:
            winmm.timeEndPeriod(1)
