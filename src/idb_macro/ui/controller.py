"""Owns the backend, settings, macro library, runners and hotkeys."""

from __future__ import annotations

import copy
import logging

from PySide6.QtCore import QObject, Qt, Signal

from ..core.engine import ClickerRunner, KeyRunner, MacroRunner, Runner
from ..core.guard import SmartGuard
from ..core.keys import parse_combo
from ..core.models import Macro
from ..core.profiles import Profile
from ..core.storage import Store
from ..hotkeys import HotkeyManager
from ..platform.base import Backend

log = logging.getLogger(__name__)

TOOLS = ("clicker", "keys", "macro")


class Controller(QObject):
    # tool, running, message
    state_changed = Signal(str, bool, str)
    macros_changed = Signal()
    record_requested = Signal()
    hotkeys_updated = Signal()
    profiles_changed = Signal()
    modes_changed = Signal()
    _hotkey = Signal(str)
    _runner_event = Signal(object, str, str)

    def __init__(self, backend: Backend, store: Store):
        super().__init__()
        self.backend = backend
        self.store = store
        self.settings = store.load_settings()
        self.macros: list[Macro] = store.load_macros()
        self.profiles: list[Profile] = store.load_profiles()
        self.runners: dict[str, Runner | None] = dict.fromkeys(TOOLS)
        self.last_message: dict[str, str] = dict.fromkeys(TOOLS, "")
        self.hotkeys = HotkeyManager(self._hotkey.emit)
        self._hotkey.connect(self._on_hotkey, Qt.ConnectionType.QueuedConnection)
        self._runner_event.connect(self._on_runner_event, Qt.ConnectionType.QueuedConnection)
        self.bad_hotkeys: list[str] = []


    def start(self) -> None:
        self.apply_hotkeys()
        try:
            self.hotkeys.start()
        except Exception as exc:
            log.warning("global hotkeys unavailable: %s", exc)

    def shutdown(self) -> None:
        self.stop_all()
        for runner in self.runners.values():
            if runner is not None:
                runner.join(1.0)
        self.hotkeys.stop()
        self.save_settings()
        self.backend.close()

    def save_settings(self) -> None:
        try:
            self.store.save_settings(self.settings)
        except OSError as exc:
            log.error("could not save settings: %s", exc)

    def save_macros(self) -> None:
        try:
            self.store.save_macros(self.macros)
        except OSError as exc:
            log.error("could not save macros: %s", exc)
        self.apply_hotkeys()
        self.macros_changed.emit()

    def save_profiles(self) -> None:
        try:
            self.store.save_profiles(self.profiles)
        except OSError as exc:
            log.error("could not save profiles: %s", exc)
        self.apply_hotkeys()
        self.profiles_changed.emit()

    def find_profile(self, profile_id: str) -> Profile | None:
        return next((p for p in self.profiles if p.id == profile_id), None)

    def profile_names(self) -> dict[str, str]:
        return {p.id: p.name for p in self.profiles}

    def set_smart_mode(self, on: bool) -> None:
        self.settings.smart_mode = on
        self.save_settings()
        self.modes_changed.emit()

    def set_dumb_mode(self, on: bool) -> None:
        if self.is_running("clicker"):
            self.stop("clicker")
        self.settings.dumb_mode = on
        self.save_settings()
        self.modes_changed.emit()

    def make_guard(self) -> SmartGuard | None:
        s = self.settings
        if not s.smart_mode or not (s.smart_focus_lock or s.smart_avoid_shell):
            return None
        return SmartGuard(self.backend, s.smart_focus_lock, s.smart_avoid_shell)


    def apply_hotkeys(self) -> None:
        bindings = dict(self.settings.hotkeys)
        for m in self.macros:
            if m.hotkey:
                bindings[f"macro:{m.id}"] = m.hotkey
        for p in self.profiles:
            if p.hotkey:
                bindings[f"profile:{p.id}"] = p.hotkey
        self.bad_hotkeys = self.hotkeys.set_bindings(bindings)
        self.hotkeys_updated.emit()

    def hotkey_conflicts(self, combo: str, ignore: str = "") -> str | None:
        """Name of whatever already uses ``combo``, if anything."""
        if not combo:
            return None
        wanted = parse_combo(combo)
        names = {"clicker": "Autoclicker toggle", "keys": "Key Repeater toggle", "macro": "Play macro",
                 "record": "Record macro", "panic": "Stop everything"}
        for name, other in self.settings.hotkeys.items():
            if name != ignore and other and parse_combo(other) == wanted:
                return names.get(name, name)
        for m in self.macros:
            if f"macro:{m.id}" != ignore and m.hotkey and parse_combo(m.hotkey) == wanted:
                return f'macro "{m.name}"'
        for p in self.profiles:
            if f"profile:{p.id}" != ignore and p.hotkey and parse_combo(p.hotkey) == wanted:
                return f'saved setup "{p.name}"'
        return None

    def reserved_keys(self) -> set[tuple[str, ...]]:
        return {parse_combo(c) for c in self.settings.hotkeys.values() if c}

    def _on_hotkey(self, name: str) -> None:
        if name == "panic":
            self.stop_all()
        elif name == "clicker":
            self.toggle("clicker")
        elif name == "keys":
            self.toggle("keys")
        elif name == "macro":
            self.toggle_macro(self.settings.selected_macro)
        elif name == "record":
            self.record_requested.emit()
        elif name.startswith("macro:"):
            self.toggle_macro(name.split(":", 1)[1])
        elif name.startswith("profile:"):
            self.toggle_profile(name.split(":", 1)[1])


    def failsafe(self) -> bool:
        if not self.settings.failsafe_corner:
            return False
        try:
            x, y = self.backend.cursor_pos()
        except Exception:
            return False
        return x <= 1 and y <= 1

    def is_running(self, tool: str) -> bool:
        r = self.runners.get(tool)
        return r is not None and r.is_alive()

    def toggle(self, tool: str) -> None:
        if self.is_running(tool):
            self.stop(tool)
        elif tool == "clicker":
            # Dumb mode has its own simple setup so it never disturbs the full one.
            cfg = self.settings.dumb if self.settings.dumb_mode else self.settings.clicker
            self.start_tool("clicker", copy.deepcopy(cfg))
        elif tool == "keys":
            self.start_tool("keys", copy.deepcopy(self.settings.keys))
        elif tool == "macro":
            self.toggle_macro(self.settings.selected_macro)

    def start_tool(self, tool: str, config, profile_id: str = "") -> None:
        runner_type = ClickerRunner if tool == "clicker" else KeyRunner
        guard = None if self.settings.dumb_mode else self.make_guard()
        runner = runner_type(self.backend, config, failsafe=self.failsafe, guard=guard)
        runner.profile_id = profile_id
        self.start_runner(tool, runner)

    def toggle_profile(self, profile_id: str) -> None:
        """Start or stop a saved setup straight from its hotkey."""
        profile = self.find_profile(profile_id)
        if profile is None:
            return
        current = self.runners.get(profile.tool)
        if self.is_running(profile.tool):
            self.stop(profile.tool)
            if getattr(current, "profile_id", "") == profile_id:
                return
        self.start_tool(profile.tool, profile.copy_config(), profile_id)

    def toggle_macro(self, macro_id: str) -> None:
        current = self.runners.get("macro")
        if self.is_running("macro"):
            same = isinstance(current, MacroRunner) and current.macro.id == macro_id
            self.stop("macro")
            if same or not macro_id:
                return
        macro = self.find_macro(macro_id)
        if macro is None:
            self._report("macro", False, "Select a macro to play first.")
            return
        profiles = {p.id: copy.deepcopy(p) for p in self.profiles}
        guard_factory = self.make_guard if self.settings.smart_mode else None
        self.start_runner("macro", MacroRunner(self.backend, copy.deepcopy(macro), profiles=profiles,
                                               guard_factory=guard_factory, failsafe=self.failsafe))

    def find_macro(self, macro_id: str) -> Macro | None:
        return next((m for m in self.macros if m.id == macro_id), None)

    def start_runner(self, tool: str, runner: Runner) -> None:
        if self.is_running(tool):
            self.stop(tool)
        runner.on_event = lambda kind, msg, r=runner: self._runner_event.emit(r, kind, msg)
        self.runners[tool] = runner
        runner.start()

    def stop(self, tool: str) -> None:
        r = self.runners.get(tool)
        if r is not None:
            r.stop()

    def stop_all(self) -> None:
        for tool in TOOLS:
            self.stop(tool)

    def _on_runner_event(self, runner: Runner, kind: str, message: str) -> None:
        tool = runner.tool
        if self.runners.get(tool) is not runner:
            return
        running = kind == "started"
        self._report(tool, running, message)

    def _report(self, tool: str, running: bool, message: str) -> None:
        self.last_message[tool] = message
        self.state_changed.emit(tool, running, message)
