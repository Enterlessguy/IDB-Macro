"""Saved setups (profiles) bar and the smart-mode panel shared by the tool pages."""

from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFileDialog, QFrame, QInputDialog, QMenu, QMessageBox, QVBoxLayout, QWidget

from ...core.models import ValidationError
from ...core.presets import Preset
from ...core.profiles import TOOL_NAMES, Profile
from ...core.storage import export_profiles, import_bundle
from ..widgets import FlowLayout, HotkeyEdit, Message, button, hbox, label

NOT_SAVED = ""


class ProfileBar(QFrame):
    """Pick, save and manage saved setups for one tool.

    ``get_config`` returns the page's current settings; ``apply_config`` loads
    a config into the page.
    """

    def __init__(self, controller, tool: str, get_config: Callable, apply_config: Callable):
        super().__init__()
        self.setObjectName("Card")
        self.c = controller
        self.tool = tool
        self.get_config = get_config
        self.apply_config = apply_config
        self._loading = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 14, 22, 14)
        lay.setSpacing(8)
        self.combo = QComboBox()
        self.combo.setMinimumWidth(260)
        self.combo.setToolTip("Saved setups. Choosing one loads it; your edits don't change it until you Save.")
        self.dirty = label("● Unsaved changes", "warning")
        self.save_btn = button("Save", "primary", "Overwrite the selected setup with the current settings")
        self.save_as_btn = button("Save as new…")
        self.more_btn = button("More ▾")
        self.hotkey = HotkeyEdit("", placeholder="No hotkey")
        self.hotkey.setToolTip("Starts and stops this saved setup from anywhere, without opening the app.")
        lay.addLayout(hbox(label("Saved setup", "muted"), self.combo, self.dirty, None, label("Hotkey", "muted"),
                           self.hotkey, self.save_btn, self.save_as_btn, self.more_btn, spacing=10))
        self.error = Message("error")
        lay.addWidget(self.error)

        menu = QMenu(self)
        menu.addAction("Rename…").triggered.connect(self.rename)
        menu.addAction("Delete").triggered.connect(self.delete)
        menu.addSeparator()
        menu.addAction("Import setups…").triggered.connect(self.import_file)
        menu.addAction("Export this setup…").triggered.connect(self.export_file)
        self.more_btn.setMenu(menu)

        self.combo.currentIndexChanged.connect(self._chosen)
        self.save_btn.clicked.connect(self.save)
        self.save_as_btn.clicked.connect(self.save_as)
        self.hotkey.changed.connect(self._set_hotkey)
        controller.profiles_changed.connect(self.reload)
        self.reload()

    # ---- state --------------------------------------------------------------

    def selected(self) -> Profile | None:
        return self.c.find_profile(self.combo.currentData() or "")

    def mine(self) -> list[Profile]:
        return [p for p in self.c.profiles if p.tool == self.tool]

    def reload(self) -> None:
        wanted = self.c.settings.selected_profiles.get(self.tool, "")
        self._loading = True
        self.combo.clear()
        self.combo.addItem("Current settings (not saved)", NOT_SAVED)
        for p in self.mine():
            self.combo.addItem(p.name, p.id)
        index = self.combo.findData(wanted)
        self.combo.setCurrentIndex(max(0, index))
        self._loading = False
        self._refresh()

    def _refresh(self) -> None:
        p = self.selected()
        self.save_btn.setEnabled(p is not None)
        self.hotkey.setEnabled(p is not None)
        self.hotkey.setValue(p.hotkey if p else "")
        self.refresh_dirty()

    def refresh_dirty(self) -> None:
        p = self.selected()
        self.dirty.setVisible(p is not None and p.config.to_dict() != self.get_config().to_dict())

    def _remember(self, profile_id: str) -> None:
        self.c.settings.selected_profiles[self.tool] = profile_id
        self.c.save_settings()

    def _chosen(self, _index: int) -> None:
        if self._loading:
            return
        self.error.setText("")
        p = self.selected()
        self._remember(p.id if p else NOT_SAVED)
        if p is not None:
            self.apply_config(p.copy_config())
        self._refresh()

    def select(self, profile_id: str) -> None:
        self.combo.setCurrentIndex(max(0, self.combo.findData(profile_id)))

    # ---- actions ------------------------------------------------------------

    def save(self) -> None:
        p = self.selected()
        if p is None:
            self.save_as()
            return
        p.config = copy.deepcopy(self.get_config())
        self.c.save_profiles()

    def save_as(self) -> None:
        name, ok = QInputDialog.getText(self, "Save setup", f"Name for this {TOOL_NAMES[self.tool]} setup:")
        name = name.strip()[:100]
        if not ok or not name:
            return
        p = Profile(self.tool, name, copy.deepcopy(self.get_config()))
        self.c.profiles.append(p)
        self._remember(p.id)
        self.c.save_profiles()

    def rename(self) -> None:
        p = self.selected()
        if p is None:
            return
        name, ok = QInputDialog.getText(self, "Rename setup", "New name:", text=p.name)
        if ok and name.strip():
            p.name = name.strip()[:100]
            self.c.save_profiles()

    def delete(self) -> None:
        p = self.selected()
        if p is None:
            return
        users = [m.name for m in self.c.macros for s in m.steps if s.params.get("profile") == p.id]
        extra = f"\n\nThese macros use it and will stop at that step: {', '.join(users[:5])}" if users else ""
        box = QMessageBox(QMessageBox.Icon.Question, "Delete setup", f'Delete "{p.name}"?{extra}',
                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
        box.setTextFormat(Qt.TextFormat.PlainText)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        self.c.profiles.remove(p)
        self._remember(NOT_SAVED)
        self.c.save_profiles()

    def _set_hotkey(self, combo: str) -> None:
        p = self.selected()
        if p is None:
            return
        clash = self.c.hotkey_conflicts(combo, ignore=f"profile:{p.id}")
        if clash:
            self.error.setText(f"That hotkey is already used by {clash}.")
            self.hotkey.setValue(p.hotkey)
            return
        self.error.setText("")
        p.hotkey = combo
        self.c.save_profiles()

    def export_file(self) -> None:
        p = self.selected()
        if p is None:
            self.error.setText("Save the setup first, then export it.")
            return
        safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in p.name).strip() or "setup"
        path, _ = QFileDialog.getSaveFileName(self, "Export setup", str(Path.home() / f"{safe}.json"),
                                              "IDB-Macro files (*.json)")
        if path:
            try:
                export_profiles(Path(path), [p])
            except OSError as exc:
                self.error.setText(str(exc))

    def import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import setups", str(Path.home()), "IDB-Macro files (*.json)")
        if not path:
            return
        try:
            _macros, profiles = import_bundle(Path(path))
        except (ValidationError, OSError) as exc:
            self.error.setText(f"That file could not be imported: {exc}")
            return
        mine = [p for p in profiles if p.tool == self.tool]
        if not mine:
            self.error.setText(f"That file has no {TOOL_NAMES[self.tool]} setups.")
            return
        self.c.profiles.extend(mine)
        self._remember(mine[0].id)
        self.c.save_profiles()


class SmartPanel(QFrame):
    """Smart-mode presets for common uses, plus tips about the current settings."""

    def __init__(self, presets: list[Preset], on_preset: Callable[[Preset], None]):
        super().__init__()
        self.setObjectName("Card")
        self.setProperty("smart", True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 16, 22, 18)
        lay.setSpacing(10)
        title = label("✦  Smart mode", None)
        title.setObjectName("CardTitle")
        from ..explainer import bulb

        lay.addLayout(hbox(title, bulb(self, "smart", "How do the safety checks work?"), None, spacing=8))
        lay.addWidget(label("Start from a setup made for your use case. It only changes timing and click "
                            "style; your keys, spots and window stay as they are.", "faint", wrap=True))
        chips = QWidget()
        flow = FlowLayout(chips, spacing=8)
        for preset in presets:
            b = button(preset.name.replace("&", "&&"))  # a single & would become a shortcut marker
            b.setProperty("preset", True)
            b.setToolTip(preset.description)
            b.clicked.connect(lambda _=False, p=preset: on_preset(p))
            flow.addWidget(b)
        lay.addWidget(chips)
        self.applied = Message("muted")
        lay.addWidget(self.applied)
        self.tips_box = QVBoxLayout()
        self.tips_box.setSpacing(4)
        lay.addLayout(self.tips_box)
        self._tips: list[Message] = []

    def set_tips(self, tips: list[str]) -> None:
        for w in self._tips:
            w.setParent(None)
            w.deleteLater()
        self._tips = []
        for text in tips:
            m = Message("warning")
            m.setText(f"•  {text}")
            self.tips_box.addWidget(m)
            self._tips.append(m)
