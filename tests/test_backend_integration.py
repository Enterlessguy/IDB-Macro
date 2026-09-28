"""Drive a real, minimized window through the platform backend.

These tests need a desktop session (Windows, or X11/Xvfb on Linux).
"""

import os
import queue
import subprocess
import sys
import threading
import time

import pytest

from idb_macro.core.models import TargetPoint, WindowTarget

HELPER = os.path.join(os.path.dirname(__file__), "helpers", "tk_target.py")

pytestmark = pytest.mark.integration


def _backend():
    if sys.platform == "win32":
        from idb_macro.platform.windows import WindowsBackend

        return WindowsBackend()
    if sys.platform.startswith("linux") and os.environ.get("DISPLAY"):
        from idb_macro.platform.x11 import X11Backend

        return X11Backend()
    pytest.skip("needs Windows or an X11 display")


class Target:
    def __init__(self, minimized=True):
        args = [sys.executable, HELPER] + (["--minimized"] if minimized else []) + ["20000"]
        self.proc = subprocess.Popen(args, stdout=subprocess.PIPE, text=True)
        self.lines: queue.Queue[str] = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()
        ready = self.wait_for("ready").split()
        self.root, self.canvas, self.entry = (int(v) for v in ready[1:4])
        if sys.platform != "win32":
            # On X11 Tk reports the window manager's frame; use the app's own
            # top-level window, the way the picker does.
            self.root = self._x11_client()
        if minimized:
            self.wait_for("minimized")

    def _x11_client(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            for w in _backend().list_windows():
                if w.title == "IDB Macro test target":
                    return w.handle
            time.sleep(0.1)
        raise AssertionError("test window not listed by the window manager")

    def _pump(self):
        for line in self.proc.stdout:
            self.lines.put(line.strip())

    def wait_for(self, prefix, timeout=8.0):
        deadline = time.monotonic() + timeout
        seen = []
        while time.monotonic() < deadline:
            try:
                line = self.lines.get(timeout=0.1)
            except queue.Empty:
                continue
            if line.startswith(prefix):
                return line
            seen.append(line)
        raise AssertionError(f"target never reported {prefix!r}; saw {seen}")

    def window(self):
        # pid stays 0: a venv's python.exe is a launcher, so proc.pid is not
        # the process that owns the window.
        return WindowTarget(handle=self.root, child=self.entry)

    def close(self):
        self.proc.kill()
        self.proc.wait(5)


@pytest.fixture
def target():
    t = Target(minimized=True)
    yield t
    t.close()


def test_background_click_reaches_minimized_window(target, monkeypatch):
    b = _backend()
    if sys.platform == "win32":
        # Background clicks must never touch the real cursor or inject real input.
        import idb_macro.platform.windows as win

        def forbidden(*_):
            raise AssertionError("background click used real input")

        monkeypatch.setattr(win, "SetCursorPos", forbidden)
        monkeypatch.setattr(win, "SendInput", forbidden)
    point = TargetPoint(0, 0, target.canvas, 50, 60)
    b.bg_mouse(target.window(), point, "left", "click")
    assert target.wait_for("press") == "press 1 50 60"
    assert target.wait_for("release") == "release 1 50 60"
    b.bg_mouse(target.window(), point, "right", "click")
    assert target.wait_for("press") == "press 3 50 60"


def test_background_double_click(target):
    b = _backend()
    b.bg_mouse(target.window(), TargetPoint(0, 0, target.canvas, 20, 20), "left", "click", count=2)
    assert target.wait_for("double") == "double 20 20"


def test_background_text_and_keys(target):
    b = _backend()
    w = target.window()
    # Tk only accepts keys while it believes it has focus.
    b.bg_text(w, "hi", spoof_focus=True)
    assert target.wait_for("text 'hi'")
    b.bg_key(w, "x", True, spoof_focus=True)
    b.bg_key(w, "x", False)
    assert target.wait_for("text 'hix'")
    b.bg_tap_combo(w, ("shift", "y"), spoof_focus=True)
    assert target.wait_for("text 'hixY'")
    b.bg_tap_combo(w, ("backspace",), spoof_focus=True)
    assert target.wait_for("text 'hix'")
    b.bg_tap_combo(w, ("backspace",), spoof_focus=True)
    assert target.wait_for("text 'hi'")


def test_background_scroll():
    # Tk routes the wheel by on-screen position, so this target stays visible.
    b = _backend()
    t = Target(minimized=False)
    try:
        b.focus_window("IDB Macro test target")  # windows from earlier tests may be on top
        time.sleep(0.2)
        b.bg_scroll(t.window(), TargetPoint(0, 0, t.canvas, 10, 10), -1, spoof_focus=True)
        assert t.wait_for("wheel") == "wheel -120"
    finally:
        t.close()


def test_autoclicker_end_to_end(target):
    from idb_macro.core.engine import ClickerRunner, KeyRunner
    from idb_macro.core.models import ClickerConfig, KeyRepeaterConfig, RunLimit

    b = _backend()
    cfg = ClickerConfig(location="window", window=target.window(), interval_ms=20,
                        points=[TargetPoint(0, 0, target.canvas, 33, 44)], limit=RunLimit("count", 5))
    runner = ClickerRunner(b, cfg)
    runner.start()
    runner.join(10)
    assert runner.finished_reason == "Finished"
    # Fast clicks on one spot are double-clicks to Tk, as with a real mouse.
    releases = [target.wait_for("release") for _ in range(5)]
    assert releases == ["release 1 33 44"] * 5

    keys = KeyRepeaterConfig(keys=["k"], interval_ms=20, target="window", window=target.window(),
                             spoof_focus=True, limit=RunLimit("count", 3))
    runner = KeyRunner(b, keys)
    runner.start()
    runner.join(10)
    assert runner.finished_reason == "Finished"
    assert target.wait_for("text 'kkk'")


def test_pick_and_list_windows():
    b = _backend()
    t = Target(minimized=False)
    try:
        wins = b.list_windows()
        assert any(w.handle == t.root for w in wins)
        found = next(w for w in wins if w.handle == t.root)
        assert "test target" in found.title
        sx, sy = b.client_to_screen(WindowTarget(handle=t.canvas), 30, 40)
        pick = b.pick_at(sx, sy)
        assert pick.window.handle == t.root
        assert (pick.point.child, pick.point.cx, pick.point.cy) == (t.canvas, 30, 40)
    finally:
        t.close()


@pytest.mark.skipif(sys.platform != "win32", reason="the frame poller uses GetAsyncKeyState")
def test_key_repeater_taps_are_seen_by_a_frame_polling_game():
    """A game samples keys once per frame; every tap must last long enough to be seen.

    Uses F24, which no application reacts to, because this sends real input.
    """
    from idb_macro.core.engine import KeyRunner
    from idb_macro.core.keys import WIN_VK
    from idb_macro.core.models import KeyRepeaterConfig, RunLimit

    poller = subprocess.Popen([sys.executable, os.path.join(os.path.dirname(__file__), "helpers", "frame_poller.py"),
                               str(WIN_VK["f24"]), "5"], stdout=subprocess.PIPE, text=True)
    assert poller.stdout.readline().strip() == "ready"
    time.sleep(0.2)
    runner = KeyRunner(_backend(), KeyRepeaterConfig(keys=["f24"], interval_ms=150, limit=RunLimit("count", 15)))
    runner.start()
    runner.join(10)
    out = poller.communicate(timeout=15)[0]
    assert runner.finished_reason == "Finished"
    assert out.split()[-1] == "15"


def test_closed_target_is_reported():
    from idb_macro.platform.base import TargetLost

    b = _backend()
    t = Target(minimized=True)
    w = t.window()
    t.close()
    time.sleep(0.3)
    with pytest.raises(TargetLost):
        b.bg_mouse(w, TargetPoint(0, 0, 0, 1, 1), "left", "click")
