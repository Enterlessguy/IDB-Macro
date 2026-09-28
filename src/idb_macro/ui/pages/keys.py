"""Key Repeater page: the autoclicker idea, for keyboards."""

from __future__ import annotations

from PySide6.QtWidgets import QLineEdit

from ...core.keys import KeyComboError, display_combo, format_combo, parse_combo
from ...core.models import KeyRepeaterConfig
from ...core.presets import KEY_PRESETS, apply_preset, keys_tips
from ...platform.base import BackendError
from ..widgets import Card, FieldRow, HotkeyEdit, KeyChips, Message, Segmented, Toggle, button, hbox, spin
from .common import (
    IntervalEditor,
    LimitEditor,
    Page,
    RunBar,
    WindowTargetPanel,
    format_elapsed,
    minimized_note,
    stack,
    two_columns,
)
from .profile_bar import ProfileBar, SmartPanel


class KeysPage(Page):
    tool = "keys"

    def __init__(self, controller):
        super().__init__("Key Repeater", "Press a key or a combination over and over, hold it down, or cycle "
                                         "through several, in the active app or a background window.", "keys")
        self.c = controller
        self._loading = False
        cfg: KeyRepeaterConfig = controller.settings.keys

        self.bar = RunBar("repeating", ["Presses", "Rate", "Elapsed"])
        self.bar.toggled.connect(lambda: self.c.toggle("keys"))
        self.body.addWidget(self.bar)
        self.profiles = ProfileBar(controller, "keys", lambda: self.c.settings.keys, self.apply_config)
        self.body.addWidget(self.profiles)
        self.smart = SmartPanel(KEY_PRESETS, self._apply_preset)
        self.body.addWidget(self.smart)
        controller.modes_changed.connect(self._sync_smart)
        grid = self.grid(2)

        keys = Card("Keys", "Add one or more keys or combinations such as Ctrl + S. Click a key to remove it.")
        self.chips = KeyChips("No keys yet. Add one below.")
        keys.add(self.chips)
        self.capture = HotkeyEdit("", allow_empty=False, placeholder="+ Press to add a key")
        self.capture.setProperty("variant", "primary")
        self.typed = QLineEdit()
        self.typed.setPlaceholderText("or type one, e.g. ctrl+shift+s")
        self.add_typed = button("Add")
        keys.add(hbox(self.capture, self.typed, self.add_typed))
        self.key_error = Message("error")
        keys.add(self.key_error)
        self.sequence = Segmented([("cycle", "One after another"), ("together", "All at once")], cfg.sequence)
        keys.add(FieldRow("With several keys", self.sequence))

        press = Card("Press style")
        self.action = Segmented([("tap", "Tap"), ("hold", "Hold down")],
                                cfg.action)
        press.add(self.action)
        self.action_hint = Message("faint")
        press.add(self.action_hint)
        self.hold = spin(0, 3_600_000, int(cfg.hold_ms), " ms", 120)
        self.hold_row = FieldRow("Press length", self.hold,
                                 "How long each tap holds the key. Games read keys once per frame, so keep this at "
                                 "30 ms or more for them.")
        press.add(self.hold_row)
        self.interval = IntervalEditor(cfg.interval_ms, cfg.jitter_ms, "presses")
        press.add(self.interval)
        grid.addWidget(press, 0, 1)

        target = Card("Send keys to")
        self.target = Segmented([("foreground", "Active window"), ("window", "Window (background)")], cfg.target)
        target.add(self.target)
        self.target_hint = Message("faint")
        target.add(self.target_hint)
        self.window_panel = WindowTargetPanel(controller, self)
        self.window_panel.set_target(cfg.window)
        self.spoof = Toggle("Pretend the window is focused", cfg.spoof_focus)
        self.spoof.setToolTip("Many apps only accept keys while they think they have focus.")
        self.test_btn = button("Send one test press")
        self.test_result = Message("faint")
        self.target_columns = two_columns([self.window_panel], [self.spoof, self.test_btn, self.test_result])
        target.add(self.target_columns)

        stop = Card("Stop condition")
        self.limit = LimitEditor(cfg.limit, "presses")
        stop.add(self.limit)
        grid.addLayout(stack(keys, stop), 0, 0)
        grid.addWidget(target, 1, 0, 1, 2)
        self.body.addStretch(1)

        if not controller.backend.supports_background:
            self.target.setOptionEnabled("window", False, "Background input is not available on this system.")

        self.keys: list[str] = list(cfg.keys)
        self._render_keys()
        self.capture.changed.connect(self._add_key)
        self.add_typed.clicked.connect(lambda: self._add_key(self.typed.text()))
        self.typed.returnPressed.connect(lambda: self._add_key(self.typed.text()))
        self.chips.removed.connect(self._remove_key)
        for sig in (self.sequence.changed, self.action.changed, self.target.changed, self.interval.changed,
                    self.limit.changed, self.window_panel.changed):
            sig.connect(self.save)
        self.hold.valueChanged.connect(self.save)
        self.spoof.toggled.connect(self.save)
        self.test_btn.clicked.connect(self.test_press)
        self._sync_visibility()
        self._sync_smart()

    def apply_config(self, cfg: KeyRepeaterConfig) -> None:
        """Load a whole setup (saved profile or preset) into the page."""
        self._loading = True
        try:
            self.keys = list(cfg.keys)
            self._render_keys()
            self.sequence.setValue(cfg.sequence)
            self.action.setValue(cfg.action)
            self.hold.setValue(int(cfg.hold_ms))
            self.interval.set_values(cfg.interval_ms, cfg.jitter_ms)
            self.limit.set_value(cfg.limit)
            self.target.setValue(cfg.target)
            self.window_panel.set_target(cfg.window)
            self.spoof.setChecked(cfg.spoof_focus)
        finally:
            self._loading = False
        self.save()

    def _apply_preset(self, preset) -> None:
        self.apply_config(apply_preset(self.c.settings.keys, preset))
        self.smart.applied.setText(f"Applied “{preset.name}”: {preset.description}")

    def _sync_smart(self) -> None:
        self.smart.setVisible(self.c.settings.smart_mode)
        if self.c.settings.smart_mode:
            self.smart.set_tips(keys_tips(self.c.settings.keys, self.c.backend))

    def _render_keys(self) -> None:
        self.chips.set_items([display_combo(k) for k in self.keys])

    def _add_key(self, text: str) -> None:
        self.capture.setValue("")
        try:
            combo = format_combo(parse_combo(text))
        except KeyComboError as exc:
            self.key_error.setText(str(exc).capitalize())
            return
        self.key_error.setText("")
        self.typed.clear()
        if len(self.keys) >= 32:
            self.key_error.setText("That is the maximum of 32 keys.")
            return
        self.keys.append(combo)
        self._render_keys()
        self.save()

    def _remove_key(self, row: int) -> None:
        if 0 <= row < len(self.keys):
            del self.keys[row]
            self._render_keys()
            self.save()

    def _sync_visibility(self) -> None:
        action = self.action.value()
        self.hold_row.setVisible(action == "tap")
        self.action_hint.setText({
            "tap": "Presses and releases the keys each time.",
            "hold": "Holds the keys down until you stop. In background mode the key-down is repeated at the "
                    "speed below, the way a held key auto-repeats.",
        }[action])
        bg = self.target.value() == "window"
        self.target_columns.setVisible(bg)
        self.target_hint.setText(
            "Keys go to the picked window only. You can keep typing elsewhere, and the window can stay "
            "minimized if the app accepts background input." if bg else
            "Keys go to whichever window is active, exactly like pressing them yourself.")

    def save(self, *_) -> None:
        if self._loading:
            return
        cfg = self.c.settings.keys
        cfg.keys = list(self.keys)
        cfg.sequence = self.sequence.value()
        cfg.action = self.action.value()
        cfg.hold_ms = float(self.hold.value())
        cfg.interval_ms = self.interval.interval_ms()
        cfg.jitter_ms = self.interval.jitter_ms()
        cfg.limit = self.limit.value()
        cfg.target = self.target.value()
        cfg.window = self.window_panel.target
        cfg.spoof_focus = self.spoof.isChecked()
        self._sync_visibility()
        self.c.save_settings()
        self.profiles.refresh_dirty()
        self._sync_smart()

    def test_press(self) -> None:
        cfg = self.c.settings.keys
        if cfg.window is None or not cfg.keys:
            self.test_result.setText("Pick a window and add a key first.")
            return
        try:
            target = self.c.backend.ensure_target(cfg.window)
            self.c.backend.bg_tap_combo(target, parse_combo(cfg.keys[0]), cfg.spoof_focus)
            self.test_result.setText(f"Sent {display_combo(cfg.keys[0])}. If the app did not react, try "
                                     "“Pretend the window is focused”." + minimized_note(self.c.backend, target))
        except BackendError as exc:
            self.test_result.setText(str(exc))

    def on_state(self, running: bool, message: str) -> None:
        self.bar.set_running(running, message)

    def tick(self) -> None:
        r = self.c.runners.get("keys")
        if r is None or r.started_at is None:
            return
        elapsed = r.elapsed
        self.bar.set_stat("Presses", f"{r.count:,}")
        self.bar.set_stat("Rate", f"{r.count / elapsed:,.1f}/s" if elapsed > 0.2 else "—")
        self.bar.set_stat("Elapsed", format_elapsed(elapsed))
        self.bar.set_note(r.status)
