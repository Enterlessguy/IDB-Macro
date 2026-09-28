"""Settings page: hotkeys, behaviour and information."""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from ... import __version__
from ...core.keys import display_combo
from ...core.storage import DEFAULT_HOTKEYS
from ..widgets import Card, FieldRow, HotkeyEdit, Message, Toggle, button, hbox, label
from .common import Page, stack

HOTKEY_LABELS = [
    ("clicker", "Start / stop the Autoclicker"),
    ("keys", "Start / stop the Key Repeater"),
    ("macro", "Play / stop the selected macro"),
    ("record", "Start / stop recording a macro"),
    ("panic", "Stop everything"),
]
REPO_URL = "https://github.com/Enterlessguy/IDB-Macro"


class SettingsPage(Page):
    def __init__(self, controller, on_always_on_top):
        super().__init__("Settings", "Hotkeys work system-wide, even while another app is focused.")
        self.c = controller
        self.on_always_on_top = on_always_on_top
        s = controller.settings
        grid = self.grid(2)

        keys = Card("Hotkeys", "Click a field, then press the keys. Backspace clears, Esc cancels.")
        self.hotkey_edits: dict[str, HotkeyEdit] = {}
        for name, text in HOTKEY_LABELS:
            edit = HotkeyEdit(s.hotkeys.get(name, ""))
            edit.changed.connect(lambda combo, n=name: self._set_hotkey(n, combo))
            self.hotkey_edits[name] = edit
            keys.add(FieldRow(text, edit, caption_width=230))
        self.hotkey_error = Message("error")
        keys.add(self.hotkey_error)
        reset = button("Reset to defaults", "ghost")
        reset.clicked.connect(self._reset_hotkeys)
        keys.add(hbox(None, reset))
        grid.addWidget(keys, 0, 0)

        general = Card("Behaviour")
        self.toggles = {
            "show_splash": Toggle("Show the startup animation", s.show_splash),
            "always_on_top": Toggle("Keep I-DB Macro above other windows", s.always_on_top),
            "close_to_tray": Toggle("Closing the window keeps it running in the tray", s.close_to_tray),
            "failsafe_corner": Toggle("Fail-safe: slam the cursor into the top-left corner to stop",
                                      s.failsafe_corner),
            "minimize_while_recording": Toggle("Minimize while recording a macro", s.minimize_while_recording),
        }
        for name, toggle in self.toggles.items():
            toggle.toggled.connect(lambda on, n=name: self._set_flag(n, on))
            general.add(toggle)
        smart = Card("Smart mode", "Presets for common uses, tips about your settings, and these safety checks "
                                   "for the Autoclicker, Key Repeater and saved setups run by macros.")
        self.smart_on = Toggle("Smart mode", s.smart_mode)
        self.smart_on.toggled.connect(self.c.set_smart_mode)
        smart.add(self.smart_on)
        self.smart_flags = {
            "smart_focus_lock": Toggle("Only click and type in the window you started in (pauses when you switch "
                                       "apps, and lets go of held keys)", s.smart_focus_lock),
            "smart_avoid_shell": Toggle("Never click the taskbar, the desktop or I-DB Macro itself",
                                        s.smart_avoid_shell),
        }
        for name, toggle in self.smart_flags.items():
            toggle.toggled.connect(lambda on, n=name: self._set_flag(n, on))
            smart.add(toggle)
        grid.addLayout(stack(general, smart), 0, 1)
        controller.modes_changed.connect(self._sync_smart)

        about = Card("About")
        backend = controller.backend
        about.add(label(f"I-DB Macro {__version__}  ·  Intelligence Database", "muted"))
        about.add(label(f"Input engine: {backend.name}  ·  background input "
                        f"{'available' if backend.supports_background else 'not available'}", "faint"))
        if backend.notice:
            about.add(label(backend.notice, "warning", wrap=True))
        about.add(label(f"Settings and macros are stored in {controller.store.dir}", "faint", wrap=True))
        folder = button("Open data folder")
        folder.clicked.connect(self._open_folder)
        repo = button("Source code", "ghost")
        repo.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(REPO_URL)))
        about.add(hbox(folder, repo, None))
        about.add(label("No telemetry. The only network use is checking GitHub for updates. MIT licensed.", "faint"))
        grid.addWidget(about, 1, 0, 1, 2)
        self.body.addStretch(1)

    def _set_hotkey(self, name: str, combo: str) -> None:
        clash = self.c.hotkey_conflicts(combo, ignore=name)
        if clash:
            self.hotkey_error.setText(f"{display_combo(combo)} is already used by {clash}.")
            self.hotkey_edits[name].setValue(self.c.settings.hotkeys.get(name, ""))
            return
        self.hotkey_error.setText("")
        self.c.settings.hotkeys[name] = combo
        self.c.save_settings()
        self.c.apply_hotkeys()

    def _reset_hotkeys(self) -> None:
        self.c.settings.hotkeys = dict(DEFAULT_HOTKEYS)
        for name, edit in self.hotkey_edits.items():
            edit.setValue(DEFAULT_HOTKEYS[name])
        self.hotkey_error.setText("")
        self.c.save_settings()
        self.c.apply_hotkeys()

    def _set_flag(self, name: str, on: bool) -> None:
        setattr(self.c.settings, name, on)
        self.c.save_settings()
        if name == "always_on_top":
            self.on_always_on_top(on)

    def _sync_smart(self) -> None:
        self.smart_on.blockSignals(True)
        self.smart_on.setChecked(self.c.settings.smart_mode)
        self.smart_on.blockSignals(False)
        self.smart_on.update()

    def _open_folder(self) -> None:
        self.c.store.dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.c.store.dir)))

