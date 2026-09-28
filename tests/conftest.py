import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from idb_macro.core.models import WindowTarget  # noqa: E402
from idb_macro.platform.base import Backend, TargetLost  # noqa: E402


class FakeBackend(Backend):
    name = "fake"
    supports_background = True

    def __init__(self):
        self.calls = []
        self.times = []
        self.pos = (500, 500)  # away from the fail-safe corner
        self.alive = True
        self.lock = threading.Lock()

    def _log(self, *entry):
        with self.lock:
            self.calls.append(entry)
            self.times.append(time.perf_counter())

    def gap(self, first, second):
        """Seconds between the first calls matching two entries."""
        return self.times[self.calls.index(second)] - self.times[self.calls.index(first)]

    def cursor_pos(self):
        return self.pos

    def move(self, x, y):
        self.pos = (x, y)
        self._log("move", x, y)

    def mouse_down(self, button):
        self._log("down", button)

    def mouse_up(self, button):
        self._log("up", button)

    def scroll(self, amount, horizontal=False):
        self._log("scroll", amount, horizontal)

    def key_down(self, key):
        self._log("kdown", key)

    def key_up(self, key):
        self._log("kup", key)

    def type_text(self, text):
        self._log("type", text)

    def window_alive(self, target):
        return self.alive

    def reacquire(self, target):
        return None

    def focus_window(self, title_contains):
        self._log("focus", title_contains)
        return title_contains == "ok"

    def bg_mouse(self, target, point, button, action, count=1, spoof_focus=False):
        if not self.alive:
            raise TargetLost("gone")
        self._log("bg_mouse", action, button, point.x, point.y, count)

    def bg_scroll(self, target, point, amount, horizontal=False, spoof_focus=False):
        self._log("bg_scroll", amount)

    def bg_key(self, target, key, down, held=(), spoof_focus=False):
        if not self.alive:
            raise TargetLost("gone")
        self._log("bg_kdown" if down else "bg_kup", key, held)

    def bg_text(self, target, text, spoof_focus=False):
        self._log("bg_text", text)

    def kinds(self):
        return [c[0] for c in self.calls]


@pytest.fixture
def backend():
    return FakeBackend()


@pytest.fixture
def window():
    return WindowTarget(handle=1, title="Test", process="test.exe")
