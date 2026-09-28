"""Macros page: library, step editor, recorder and playback."""

from __future__ import annotations

import copy
import uuid
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFileDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QWidget,
)

from ...core.keys import display_combo, parse_combo
from ...core.models import FOREGROUND_ONLY_STEPS, STEP_LABELS, STEP_SPECS, Macro, Step, ValidationError
from ...core.recorder import RecordOptions, events_to_steps
from ...core.storage import describe_import, export_macros, import_bundle
from ...hotkeys import InputRecorder
from ...platform.base import BackendError
from .. import theme
from ..widgets import (
    Card,
    FieldRow,
    HotkeyEdit,
    IconButton,
    Message,
    Segmented,
    Toggle,
    button,
    dspin,
    hbox,
    label,
    restyle,
    spin,
    vbox,
)
from .common import Page, RunBar, WindowTargetPanel, format_elapsed
from .step_dialog import StepDialog

STEP_MENU = [
    ("Mouse", ["click", "mouse_down", "mouse_up", "move", "scroll"]),
    ("Keyboard", ["key", "key_down", "key_up", "text"]),
    ("Flow", ["wait", "focus", "launch"]),
    ("Saved setups", ["run_clicker", "run_keys"]),
]


class RecordToast(QWidget):
    """Small always-on-top notice shown while recording."""

    def __init__(self, stop_hint: str, on_stop):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setObjectName("Card")
        self.setStyleSheet(f"QWidget#Card {{ background: {theme.SURFACE_STRONG}; border: 1px solid "
                           f"{theme.DANGER}; border-radius: 12px; }}")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        stop = IconButton("stop", "Stop", "danger")
        stop.clicked.connect(on_stop)
        self.setLayout(hbox(label("●  Recording"), label(stop_hint, "faint"), None, stop,
                            spacing=10, margins=(14, 10, 10, 10)))
        self.resize(380, 54)
        screen = self.screen().availableGeometry()
        self.move(screen.right() - self.width() - 24, screen.top() + 24)


class MacrosPage(Page):
    tool = "macro"

    def __init__(self, controller):
        super().__init__("Macros", "Record or build step-by-step automations for any app: clicks, keys, "
                                   "text, waits, launching programs. Play them in the active app or in a "
                                   "background window.", "macro")
        self.c = controller
        self.current: Macro | None = None
        self.recorder: InputRecorder | None = None
        self.toast: RecordToast | None = None
        self.stopped_from_toast = False
        self._last_step_marker = -1
        self._loading = False

        self.bar = RunBar("macro", ["Loop", "Step", "Elapsed"])
        self.bar.toggled.connect(self.play)
        self.body.addWidget(self.bar)

        grid = self.grid(2)
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 5)

        library = Card("Library")
        self.library = QListWidget()
        self.library.setMinimumHeight(280)
        library.add(self.library)
        self.new_btn = button("New", "primary")
        self.dup_btn = button("Duplicate")
        self.del_btn = button("Delete", "ghost")
        self.import_btn = button("Import…")
        self.export_btn = button("Export…")
        library.add(hbox(self.new_btn, self.dup_btn, None, self.del_btn))
        library.add(hbox(self.import_btn, self.export_btn, None))
        grid.addWidget(library, 0, 0)

        self.editor = QWidget()
        editor_lay = vbox(spacing=16)
        self.editor.setLayout(editor_lay)

        settings = Card("Macro")
        self.name = QLineEdit()
        self.name.setMaxLength(100)
        self.name.setMinimumWidth(320)
        self.hotkey = HotkeyEdit("", placeholder="No hotkey")
        self.repeat = spin(0, 1_000_000, 1, "", 110)
        self.repeat.setSpecialValueText("Forever")
        self.speed = dspin(0.1, 20, 1.0, 2, "×", 100)
        settings.add(FieldRow("Name", self.name))
        settings.add(FieldRow("Hotkey", self.hotkey, "Plays or stops this macro from anywhere."))
        settings.add(FieldRow("Repeat", self.repeat, "How many times to run the steps. 0 repeats forever."))
        settings.add(FieldRow("Speed", self.speed, "Scales every wait. 2× plays twice as fast."))
        self.target = Segmented([("foreground", "Active window"), ("window", "Window (background)")])
        settings.add(FieldRow("Send input to", self.target))
        self.window_panel = WindowTargetPanel(controller, self)
        settings.add(self.window_panel)
        self.spoof = Toggle("Pretend the window is focused")
        settings.add(self.spoof)
        self.hotkey_error = Message("error")
        settings.add(self.hotkey_error)
        editor_lay.addWidget(settings)

        steps = Card("Steps")
        self.steps = QListWidget()
        self.steps.setMinimumHeight(300)
        self.steps.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.steps.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.steps.model().rowsMoved.connect(self._rows_moved)
        self.steps.itemDoubleClicked.connect(lambda _: self.edit_step())
        self.steps.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.steps.customContextMenuRequested.connect(self._step_menu)
        self.add_step_btn = button("+ Add step  ▾", "primary")
        self.add_step_btn.setMenu(self._build_add_menu())
        self.record_btn = IconButton("record", "Record", "danger")
        self.record_btn.setToolTip("Records your clicks and keys into this macro. Everything you type is saved "
                                   "as plain text, so don't type passwords while recording.")
        self.edit_btn = button("Edit")
        self.toggle_btn = button("Enable/disable")
        self.up_btn = button("↑")
        self.down_btn = button("↓")
        self.delete_step_btn = button("Delete", "ghost")
        for b in (self.up_btn, self.down_btn):
            b.setFixedWidth(40)
        steps.add(hbox(self.add_step_btn, self.record_btn, None, self.edit_btn, self.toggle_btn, self.up_btn,
                       self.down_btn, self.delete_step_btn))
        steps.add(self.steps)
        self.rec_moves = Toggle("Record mouse movement", False)
        self.rec_text = Toggle("Merge typing into text steps", False)
        self.rec_text.setToolTip("Turns runs of typed characters into one Type text step. Leave it off for "
                                 "games, which need real key presses.")
        steps.add(hbox(self.rec_moves, self.rec_text, None, spacing=18))
        self.step_count = label("", "faint")
        steps.add(self.step_count)
        editor_lay.addWidget(steps)

        grid.addWidget(self.editor, 0, 1, Qt.AlignmentFlag.AlignTop)
        self.body.addStretch(1)

        if not controller.backend.supports_background:
            self.target.setOptionEnabled("window", False, "Background input is not available on this system.")

        self.library.currentRowChanged.connect(self._select_row)
        self.new_btn.clicked.connect(self.new_macro)
        self.dup_btn.clicked.connect(self.duplicate_macro)
        self.del_btn.clicked.connect(self.delete_macro)
        self.import_btn.clicked.connect(self.import_file)
        self.export_btn.clicked.connect(self.export_file)
        self.edit_btn.clicked.connect(self.edit_step)
        self.toggle_btn.clicked.connect(self.toggle_steps)
        self.up_btn.clicked.connect(lambda: self.move_step(-1))
        self.down_btn.clicked.connect(lambda: self.move_step(1))
        self.delete_step_btn.clicked.connect(self.delete_steps)
        self.record_btn.clicked.connect(self.toggle_record)
        self.name.editingFinished.connect(self.save_meta)
        self.hotkey.changed.connect(self.save_meta)
        self.repeat.valueChanged.connect(self.save_meta)
        self.speed.valueChanged.connect(self.save_meta)
        self.target.changed.connect(self.save_meta)
        self.window_panel.changed.connect(self.save_meta)
        self.spoof.toggled.connect(self.save_meta)
        controller.record_requested.connect(self.toggle_record)
        controller.macros_changed.connect(self._refresh_library_names)
        controller.profiles_changed.connect(self._render_steps)

        if not controller.macros:
            controller.macros.append(self._example_macro())
            controller.save_macros()
        self._reload_library(controller.settings.selected_macro)

    # ---- library ------------------------------------------------------------

    @staticmethod
    def _example_macro() -> Macro:
        return Macro(name="Example: copy and paste", steps=[
            Step.new("key", combo="ctrl+a"),
            Step.new("wait", ms=100),
            Step.new("key", combo="ctrl+c"),
            Step.new("wait", ms=100),
            Step.new("key", combo="end"),
            Step.new("key", combo="enter"),
            Step.new("key", combo="ctrl+v"),
        ])

    def _reload_library(self, select_id: str = "") -> None:
        self.library.blockSignals(True)
        self.library.clear()
        for m in self.c.macros:
            item = QListWidgetItem(self._library_text(m), self.library)
            item.setData(Qt.ItemDataRole.UserRole, m.id)
        self.library.blockSignals(False)
        ids = [m.id for m in self.c.macros]
        row = ids.index(select_id) if select_id in ids else (0 if ids else -1)
        self.library.setCurrentRow(row)
        self._select_row(row)

    @staticmethod
    def _library_text(m: Macro) -> str:
        return f"{m.name}\n{len(m.steps)} steps" + (f"  ·  {display_combo(m.hotkey)}" if m.hotkey else "")

    def _refresh_library_names(self) -> None:
        for i, m in enumerate(self.c.macros):
            item = self.library.item(i)
            if item is not None:
                item.setText(self._library_text(m))

    def _select_row(self, row: int) -> None:
        self.current = self.c.macros[row] if 0 <= row < len(self.c.macros) else None
        self.editor.setEnabled(self.current is not None)
        self.c.settings.selected_macro = self.current.id if self.current else ""
        self.c.save_settings()
        self._load_editor()

    def _load_editor(self) -> None:
        m = self.current
        self._loading = True
        if m is not None:
            self.name.setText(m.name)
            self.hotkey.setValue(m.hotkey)
            self.repeat.setValue(m.repeat)
            self.speed.setValue(m.speed)
            self.target.setValue(m.target)
            self.window_panel.set_target(m.window)
            self.spoof.setChecked(m.spoof_focus)
        self._loading = False
        self.hotkey_error.setText("")
        self._sync_target()
        self._render_steps()

    def _sync_target(self) -> None:
        bg = self.target.value() == "window"
        self.window_panel.setVisible(bg)
        self.spoof.setVisible(bg)

    def new_macro(self) -> None:
        m = Macro(name=f"Macro {len(self.c.macros) + 1}")
        self.c.macros.append(m)
        self.c.save_macros()
        self._reload_library(m.id)
        self.name.setFocus()
        self.name.selectAll()

    def duplicate_macro(self) -> None:
        if self.current is None:
            return
        m = copy.deepcopy(self.current)
        m.id = uuid.uuid4().hex
        m.name = f"{m.name} (copy)"[:100]
        m.hotkey = ""
        self.c.macros.insert(self.c.macros.index(self.current) + 1, m)
        self.c.save_macros()
        self._reload_library(m.id)

    def delete_macro(self) -> None:
        if self.current is None:
            return
        answer = QMessageBox.question(self, "Delete macro", f'Delete "{self.current.name}"? This cannot be undone.')
        if answer != QMessageBox.StandardButton.Yes:
            return
        index = self.c.macros.index(self.current)
        self.c.macros.remove(self.current)
        self.c.save_macros()
        remaining = self.c.macros
        self._reload_library(remaining[min(index, len(remaining) - 1)].id if remaining else "")

    def import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import macros", str(Path.home()), "I-DB Macro files (*.json)")
        if not path:
            return
        try:
            macros, profiles = import_bundle(Path(path))
        except (ValidationError, OSError) as exc:
            QMessageBox.warning(self, "Import failed", f"That file could not be imported.\n\n{exc}")
            return
        if not macros:
            QMessageBox.information(self, "Nothing to import", "That file contains no macros.")
            return
        box = QMessageBox(QMessageBox.Icon.Warning, "Import macros?",
                          "A macro can press any key, type anything and click anywhere, which is as powerful "
                          "as running a program. Only import files from people you trust.\n\n"
                          f"{describe_import(macros, profiles)}\n\n"
                          "Hotkeys from the file are removed; assign your own after checking the steps.",
                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        self.c.macros.extend(macros)
        if profiles:
            self.c.profiles.extend(profiles)
            self.c.save_profiles()
        self.c.save_macros()
        self._reload_library(macros[0].id)
        self.window().statusBar().showMessage(f"Imported {len(macros)} macro(s). Review the steps before "
                                              "playing them.", 8000)

    def export_file(self) -> None:
        if self.current is None:
            return
        safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in self.current.name).strip() or "macro"
        path, _ = QFileDialog.getSaveFileName(self, "Export macro", str(Path.home() / f"{safe}.json"),
                                              "I-DB Macro files (*.json)")
        if not path:
            return
        try:
            export_macros(Path(path), [self.current], self.c.profiles)
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
            return
        self.window().statusBar().showMessage(f"Exported to {path}", 6000)

    # ---- macro settings -----------------------------------------------------

    def save_meta(self, *_) -> None:
        m = self.current
        if m is None or self._loading:
            return
        m.name = self.name.text().strip()[:100] or "Macro"
        combo = self.hotkey.value()
        clash = self.c.hotkey_conflicts(combo, ignore=f"macro:{m.id}")
        if clash:
            self.hotkey_error.setText(f"{display_combo(combo)} is already used by {clash}.")
            self.hotkey.setValue(m.hotkey)
        else:
            self.hotkey_error.setText("")
            m.hotkey = combo
        m.repeat = self.repeat.value()
        m.speed = self.speed.value()
        m.target = self.target.value()
        m.window = self.window_panel.target
        m.spoof_focus = self.spoof.isChecked()
        self._sync_target()
        self.c.save_macros()
        self._render_steps()

    # ---- steps --------------------------------------------------------------

    def _build_add_menu(self) -> QMenu:
        menu = QMenu(self)
        for group, types in STEP_MENU:
            menu.addSection(group)
            for t in types:
                menu.addAction(STEP_LABELS[t]).triggered.connect(lambda _=False, t=t: self.add_step(t))
        return menu

    def _step_menu(self, pos) -> None:
        menu = QMenu(self)
        menu.addAction("Edit…").triggered.connect(self.edit_step)
        menu.addAction("Duplicate").triggered.connect(self.duplicate_steps)
        menu.addAction("Enable / disable").triggered.connect(self.toggle_steps)
        menu.addSeparator()
        menu.addAction("Delete").triggered.connect(self.delete_steps)
        menu.exec(self.steps.mapToGlobal(pos))

    def _render_steps(self) -> None:
        self.steps.clear()
        m = self.current
        if m is None:
            self.step_count.setText("")
            return
        for i, s in enumerate(m.steps):
            item = QListWidgetItem(self._step_text(i, s, names=self.c.profile_names()), self.steps)
            if not s.enabled:
                item.setForeground(QColor(theme.FAINT))
            elif m.target == "window" and s.type in FOREGROUND_ONLY_STEPS:
                item.setForeground(QColor(theme.WARNING))
                item.setToolTip("Uses real input even though this macro targets a background window.")
        enabled = sum(s.enabled for s in m.steps)
        self.step_count.setText(f"{len(m.steps)} steps, {enabled} enabled. Drag to reorder, double-click to "
                                "edit.")
        self._last_step_marker = -1

    @staticmethod
    def _step_text(i: int, s: Step, running: bool = False, names: dict[str, str] | None = None) -> str:
        marker = "▶ " if running else ""
        off = "   (disabled)" if not s.enabled else ""
        return f"{marker}{i + 1:>3}.   {s.summary(names)}{off}"

    def _selected_rows(self) -> list[int]:
        return sorted(self.steps.row(i) for i in self.steps.selectedItems())

    def add_step(self, step_type: str) -> None:
        if self.current is None:
            return
        params = {}
        if "x" in STEP_SPECS[step_type]:
            x, y = self.c.backend.cursor_pos()
            if self.current.target == "window" and self.current.window is not None and step_type != "move":
                try:
                    x, y = self.c.backend.screen_to_client(self.current.window, x, y)
                except BackendError:
                    x, y = 0, 0
            params.update(x=x, y=y)
        step = Step.new(step_type, **params)
        if StepDialog(self, self.c, self.current, step).exec():
            rows = self._selected_rows()
            at = rows[-1] + 1 if rows else len(self.current.steps)
            self.current.steps.insert(at, step)
            self.c.save_macros()
            self._render_steps()
            self.steps.setCurrentRow(at)

    def edit_step(self) -> None:
        rows = self._selected_rows()
        if self.current is None or not rows:
            return
        step = self.current.steps[rows[0]]
        if StepDialog(self, self.c, self.current, step).exec():
            self.c.save_macros()
            self._render_steps()
            self.steps.setCurrentRow(rows[0])

    def duplicate_steps(self) -> None:
        rows = self._selected_rows()
        if self.current is None or not rows:
            return
        copies = [copy.deepcopy(self.current.steps[r]) for r in rows]
        at = rows[-1] + 1
        self.current.steps[at:at] = copies
        self.c.save_macros()
        self._render_steps()

    def toggle_steps(self) -> None:
        rows = self._selected_rows()
        if self.current is None or not rows:
            return
        for r in rows:
            self.current.steps[r].enabled = not self.current.steps[r].enabled
        self.c.save_macros()
        self._render_steps()
        for r in rows:
            self.steps.item(r).setSelected(True)

    def delete_steps(self) -> None:
        rows = self._selected_rows()
        if self.current is None or not rows:
            return
        for r in reversed(rows):
            del self.current.steps[r]
        self.c.save_macros()
        self._render_steps()
        self.steps.setCurrentRow(min(rows[0], len(self.current.steps) - 1))

    def move_step(self, delta: int) -> None:
        rows = self._selected_rows()
        if self.current is None or len(rows) != 1:
            return
        r = rows[0]
        n = r + delta
        if not 0 <= n < len(self.current.steps):
            return
        s = self.current.steps
        s[r], s[n] = s[n], s[r]
        self.c.save_macros()
        self._render_steps()
        self.steps.setCurrentRow(n)

    def _rows_moved(self, _parent, start: int, end: int, _dest, row: int) -> None:
        if self.current is None:
            return
        s = self.current.steps
        moving = s[start:end + 1]
        del s[start:end + 1]
        insert_at = row if row < start else row - len(moving)
        s[insert_at:insert_at] = moving
        self.c.save_macros()
        QTimer.singleShot(0, self._render_steps)

    # ---- recording ----------------------------------------------------------

    def toggle_record(self) -> None:
        if self.recorder is not None:
            self.stop_record()
            return
        if self.c.is_running("macro"):
            self.window().statusBar().showMessage("Stop the running macro before recording.", 5000)
            return
        if self.current is None:
            self.new_macro()
        hotkey = self.c.settings.hotkeys.get("record", "")
        hint = f"{display_combo(hotkey)} or Stop to finish" if hotkey else "press Stop to finish"
        self.toast = RecordToast(hint, self._stop_from_toast)
        self.recorder = InputRecorder(record_moves=self.rec_moves.isChecked())
        self.record_btn.setText("      Stop recording")
        self.record_btn.set_icon("stop")
        if self.c.settings.minimize_while_recording:
            self.window().showMinimized()
        self.toast.show()
        self.stopped_from_toast = False
        self.recorder.start()

    def _stop_from_toast(self) -> None:
        self.stopped_from_toast = True
        self.stop_record()

    def stop_record(self) -> None:
        recorder, self.recorder = self.recorder, None
        if recorder is None:
            return
        events = recorder.stop()
        if self.toast is not None:
            self.toast.close()
            self.toast = None
        self.record_btn.setText("      Record")
        self.record_btn.set_icon("record")
        restyle(self.record_btn)
        if self.stopped_from_toast:
            # Drop the click on the Stop button itself.
            while events and events[-1].kind in ("mouse_down", "mouse_up", "move"):
                events.pop()
        hotkey = self.c.settings.hotkeys.get("record", "")
        drop = parse_combo(hotkey) if hotkey else ()
        opts = RecordOptions(record_moves=self.rec_moves.isChecked(), merge_text=self.rec_text.isChecked(),
                             drop_keys=drop, transform=self._record_transform())
        steps = events_to_steps(events, opts)
        win = self.window()
        win.showNormal()
        win.raise_()
        win.activateWindow()
        if self.current is None:
            return
        self.current.steps.extend(steps)
        self.c.save_macros()
        self._render_steps()
        self.window().statusBar().showMessage(f"Recorded {len(steps)} steps.", 6000)

    def _record_transform(self):
        m = self.current
        if m is None or m.target != "window" or m.window is None:
            return None
        backend, target = self.c.backend, m.window

        def transform(x: int, y: int):
            try:
                cx, cy = backend.screen_to_client(target, x, y)
                pick = backend.pick_at(x, y)
                if pick.window.handle == target.handle:
                    return cx, cy, pick.point.child, pick.point.cx, pick.point.cy
                return cx, cy, 0, 0, 0
            except BackendError:
                return x, y, 0, 0, 0

        return transform

    # ---- playback -----------------------------------------------------------

    def play(self) -> None:
        if self.current is None:
            return
        if self.recorder is not None:
            return
        self.c.settings.selected_macro = self.current.id
        self.c.toggle_macro(self.current.id)

    def on_state(self, running: bool, message: str) -> None:
        self.bar.set_running(running, message)
        self.record_btn.setEnabled(not running)
        if not running:
            self._mark_step(-1)

    def _mark_step(self, index: int) -> None:
        if self.current is None or index == self._last_step_marker:
            return
        for i, running in ((self._last_step_marker, False), (index, True)):
            if 0 <= i < len(self.current.steps) and self.steps.item(i) is not None:
                self.steps.item(i).setText(self._step_text(i, self.current.steps[i], running,
                                                           self.c.profile_names()))
        self._last_step_marker = index

    def tick(self) -> None:
        r = self.c.runners.get("macro")
        if r is None or r.started_at is None:
            return
        total = r.macro.repeat
        self.bar.set_stat("Loop", f"{min(r.count + 1, total) if total else r.count + 1:,}"
                                  + (f" / {total:,}" if total else ""))
        self.bar.set_stat("Step", f"{r.current_step + 1} / {len(r.macro.steps)}")
        self.bar.set_stat("Elapsed", format_elapsed(r.elapsed))
        self.bar.set_note(r.nested.status if r.nested is not None else r.status)
        if r.is_alive() and self.current is not None and r.macro.id == self.current.id:
            self._mark_step(r.current_step)
