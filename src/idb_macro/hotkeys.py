"""System-wide hotkeys and input recording through pynput listeners.

Both ignore injected events, so input produced by a running macro can never
trigger a hotkey or end up in a recording.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from .core.keys import MODIFIERS, KeyComboError, parse_combo
from .core.recorder import RawEvent
from .input_names import button_name, key_name, keyboard, mouse

log = logging.getLogger(__name__)


class HotkeyManager:
    """Fires ``on_trigger(name)`` from the listener thread when a combo is pressed."""

    def __init__(self, on_trigger: Callable[[str], None]):
        self.on_trigger = on_trigger
        self.bindings: dict[str, tuple[str, ...]] = {}
        self.pressed: set[str] = set()
        self.lock = threading.Lock()
        self.listener: keyboard.Listener | None = None
        self.paused = False

    def set_bindings(self, bindings: dict[str, str]) -> list[str]:
        """Replace all bindings. Returns names whose combo was invalid."""
        parsed: dict[str, tuple[str, ...]] = {}
        bad = []
        for name, combo in bindings.items():
            if not combo:
                continue
            try:
                parsed[name] = parse_combo(combo)
            except KeyComboError:
                bad.append(name)
        with self.lock:
            self.bindings = parsed
        return bad

    def start(self) -> None:
        if self.listener is None:
            self.listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
            self.listener.daemon = True
            self.listener.start()

    def stop(self) -> None:
        if self.listener is not None:
            self.listener.stop()
            self.listener = None

    def _on_press(self, key, injected: bool) -> None:
        if injected:
            return
        name = key_name(key)
        if name is None:
            return
        with self.lock:
            repeat = name in self.pressed
            self.pressed.add(name)
            if repeat or self.paused or name in MODIFIERS:
                return
            # Only held modifiers count: a release lost to e.g. Win+L would
            # otherwise leave a stale key that blocks every hotkey.
            down = {k for k in self.pressed if k in MODIFIERS} | {name}
            matches = [n for n, combo in self.bindings.items() if combo[-1] == name and set(combo) == down]
        for match in matches:
            try:
                self.on_trigger(match)
            except Exception:
                log.exception("hotkey handler failed")

    def _on_release(self, key, injected: bool) -> None:
        if injected:
            return
        name = key_name(key)
        with self.lock:
            self.pressed.discard(name)


class InputRecorder:
    """Collects real (non-injected) mouse and keyboard events with timestamps."""

    def __init__(self, record_moves: bool = False):
        self.record_moves = record_moves
        self.events: list[RawEvent] = []
        self.lock = threading.Lock()
        self._kb: keyboard.Listener | None = None
        self._mouse: mouse.Listener | None = None
        self.started = 0.0

    def start(self) -> None:
        self.events = []
        self.started = time.perf_counter()
        self._kb = keyboard.Listener(on_press=self._key_down, on_release=self._key_up)
        self._mouse = mouse.Listener(on_click=self._click, on_scroll=self._scroll,
                                     on_move=self._move if self.record_moves else None)
        for listener in (self._kb, self._mouse):
            listener.daemon = True
            listener.start()

    def stop(self) -> list[RawEvent]:
        for listener in (self._kb, self._mouse):
            if listener is not None:
                listener.stop()
        self._kb = self._mouse = None
        with self.lock:
            return list(self.events)

    def _add(self, event: RawEvent) -> None:
        with self.lock:
            self.events.append(event)

    def _now(self) -> float:
        return time.perf_counter() - self.started

    def _key_down(self, key, injected: bool) -> None:
        name = key_name(key)
        if not injected and name:
            self._add(RawEvent(self._now(), "key_down", key=name))

    def _key_up(self, key, injected: bool) -> None:
        name = key_name(key)
        if not injected and name:
            self._add(RawEvent(self._now(), "key_up", key=name))

    def _click(self, x, y, button, pressed, injected: bool) -> None:
        name = button_name(button)
        if not injected and name:
            self._add(RawEvent(self._now(), "mouse_down" if pressed else "mouse_up", int(x), int(y), button=name))

    def _scroll(self, x, y, dx, dy, injected: bool) -> None:
        if injected:
            return
        if dy:
            self._add(RawEvent(self._now(), "scroll", int(x), int(y), amount=int(dy)))
        if dx:
            self._add(RawEvent(self._now(), "scroll", int(x), int(y), amount=int(dx), horizontal=True))

    def _move(self, x, y, injected: bool) -> None:
        if not injected:
            self._add(RawEvent(self._now(), "move", int(x), int(y)))
