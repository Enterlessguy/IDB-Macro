import random
import threading
import time

import pytest

from idb_macro.core import keys
from idb_macro.core.timing import (
    MIN_INTERVAL_MS,
    Scheduler,
    cps_to_interval_ms,
    interval_ms,
    jitter_point,
    jittered_ms,
)


@pytest.mark.parametrize("text,expected", [
    ("a", ("a",)),
    ("Ctrl+S", ("ctrl", "s")),
    ("shift + ctrl + s", ("ctrl", "shift", "s")),
    ("control+alt+delete", ("ctrl", "alt", "delete")),
    ("ctrl++", ("ctrl", "=")),
    ("+", ("=",)),
    ("shift", ("shift",)),
    ("ctrl+shift", ("ctrl", "shift")),
    ("Escape", ("esc",)),
    ("F12", ("f12",)),
    ("numadd", ("numadd",)),
    ("cmd+space", ("win", "space")),
])
def test_parse_combo(text, expected):
    assert keys.parse_combo(text) == expected


@pytest.mark.parametrize("text", ["", "   ", "ctrl+", "a+b", "ctrl+ctrl", "hyper", "ctrl++a", 5, None])
def test_parse_combo_rejects(text):
    with pytest.raises(keys.KeyComboError):
        keys.parse_combo(text)


def test_every_key_has_platform_mappings():
    assert set(keys.WIN_VK) == set(keys.X_KEYSYM)
    assert keys.WIN_EXTENDED <= keys.KNOWN_KEYS
    for name in keys.KNOWN_KEYS:
        assert "+" not in name, name


def test_x11_keysyms_resolve():
    XK = pytest.importorskip("Xlib.XK")
    import idb_macro.platform.x11  # noqa: F401 - loads the xf86 keysym group

    assert [k for k, v in keys.X_KEYSYM.items() if not XK.string_to_keysym(v)] == []


def test_display_combo():
    assert keys.display_combo("ctrl+shift+s") == "Ctrl + Shift + S"
    assert keys.display_combo("f6") == "F6"
    assert keys.display_combo("pagedown") == "PgDn"


def test_char_to_combo():
    assert keys.char_to_combo("A") == ("shift", "a")
    assert keys.char_to_combo("!") == ("shift", "1")
    assert keys.char_to_combo("\n") == ("enter",)
    assert keys.char_to_combo("é") is None


def test_interval_helpers():
    assert interval_ms(seconds=1, millis=500) == 1500
    assert interval_ms(millis=0) == MIN_INTERVAL_MS
    assert cps_to_interval_ms(20) == 50
    with pytest.raises(ValueError):
        cps_to_interval_ms(0)
    with pytest.raises(ValueError):
        interval_ms(seconds=float("nan"))


def test_jitter_stays_in_bounds():
    rng = random.Random(1)
    for _ in range(1000):
        v = jittered_ms(100, 30, rng)
        assert 70 <= v <= 130
        x, y = jitter_point(500, 500, 10, rng)
        assert (x - 500) ** 2 + (y - 500) ** 2 <= 11 ** 2
    assert jittered_ms(5, 50, rng) >= MIN_INTERVAL_MS


def test_scheduler_has_no_drift():
    stop = threading.Event()
    s = Scheduler(stop)
    start = time.perf_counter()
    for _ in range(50):
        s.advance(10)
        assert s.wait_next()
    elapsed = time.perf_counter() - start
    # 50 ticks of 10 ms; allow slack for CI noise but not per-tick drift.
    assert 0.49 <= elapsed < 0.62


def test_scheduler_stops_promptly():
    stop = threading.Event()
    s = Scheduler(stop)
    threading.Timer(0.05, stop.set).start()
    start = time.perf_counter()
    assert s.sleep(5000) is False
    assert time.perf_counter() - start < 0.5
