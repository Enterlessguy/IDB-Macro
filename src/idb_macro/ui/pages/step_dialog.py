"""Dialog that edits one macro step, built from the step's field specs."""

from __future__ import annotations

import shlex

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...core.keys import KeyComboError, format_combo, parse_combo
from ...core.models import BUTTONS, PROFILE_STEPS, STEP_LABELS, STEP_SPECS, Macro, Step, ValidationError
from ...core.profiles import TOOL_NAMES
from ...platform.base import PickResult
from .. import picker
from ..widgets import FieldRow, HotkeyEdit, IconButton, Message, Segmented, Toggle, button, hbox, label, spin

BUTTON_LABELS = {"left": "Left", "right": "Right", "middle": "Middle", "x1": "Back", "x2": "Forward"}
FIELD_LABELS = {
    "button": "Button", "count": "Clicks", "at": "Position", "x": "X", "y": "Y", "duration_ms": "Glide time",
    "amount": "Steps", "horizontal": "Horizontal", "combo": "Keys", "hold_ms": "Hold keys for", "text": "Text",
    "char_delay_ms": "Delay between characters", "ms": "Wait", "random_ms": "Plus a random extra up to",
    "path": "Program or file", "args": "Arguments", "title": "Window title contains",
    "profile": "Saved setup", "until": "Run",
}
# Labels that depend on the step type.
STEP_FIELD_LABELS = {("run_clicker", "ms"): "Run for", ("run_keys", "ms"): "Run for"}
HIDDEN = {"child", "cx", "cy"}


class StepDialog(QDialog):
    def __init__(self, parent: QWidget, controller, macro: Macro, step: Step):
        super().__init__(parent)
        self.c = controller
        self.macro = macro
        self.step = step
        self.hidden = {k: step.get(k) for k in STEP_SPECS[step.type] if k in HIDDEN}
        self.setWindowTitle(STEP_LABELS[step.type])
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(12)
        lay.addWidget(label(STEP_LABELS[step.type], "title"))
        self.fields: dict[str, object] = {}
        spec = STEP_SPECS[step.type]
        for name, field_spec in spec.items():
            if name in HIDDEN:
                continue
            widget = self._make(name, field_spec, step.get(name))
            self.fields[name] = widget
            lay.addWidget(FieldRow(STEP_FIELD_LABELS.get((step.type, name)) or FIELD_LABELS.get(name, name), widget))
        if "x" in spec:
            self.pick_btn = IconButton("target", "Pick position on screen")
            self.pick_btn.clicked.connect(self._pick)
            lay.addWidget(self.pick_btn)
        if step.type == "launch":
            lay.addWidget(label("Starts the program directly, never through a shell. Documents open in "
                                "their default app.", "faint", wrap=True))
        if macro.target == "window" and step.type in ("move", "focus"):
            lay.addWidget(label("This step uses real input and ignores the macro's background window.",
                                "warning", wrap=True))
        self.error = Message("error")
        lay.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        if "at" in self.fields:
            self.fields["at"].changed.connect(self._sync_position)
            self._sync_position()
        if step.type in PROFILE_STEPS:
            tool = PROFILE_STEPS[step.type]
            self.fields["until"].changed.connect(self._sync_until)
            self._sync_until()
            note = (f"Runs a setup saved on the {TOOL_NAMES[tool]} page, exactly as saved (including its own "
                    "target window). Stopping the macro stops it too.")
            if not any(p.tool == tool for p in self.c.profiles):
                note = f"Save a setup on the {TOOL_NAMES[tool]} page first (Saved setup → Save as new)."
            self.layout().insertWidget(self.layout().count() - 2, label(note, "faint", wrap=True))

    def _make(self, name: str, spec: tuple, value):
        kind, _default, extra = spec
        if name == "button":
            return Segmented([(b, BUTTON_LABELS[b]) for b in BUTTONS], value)
        if name == "at":
            return Segmented([("point", "At a position"), ("cursor", "Wherever the cursor is")], value)
        if kind == "id":
            return self._profile_picker(value)
        if name == "until":
            return Segmented([("time", "For a set time"), ("own", "Until its own stop condition")], value)
        if kind == "choice":
            box = QComboBox()
            box.addItems(list(extra))
            box.setCurrentText(value)
            return box
        if kind == "bool":
            return Toggle("", value)
        if kind == "int":
            lo, hi = extra
            suffix = " ms" if name.endswith("ms") else " px" if name in ("x", "y") else ""
            return spin(max(lo, -2_000_000_000), min(hi, 2_000_000_000), value, suffix, 150)
        if kind == "combo":
            edit = HotkeyEdit(value, allow_empty=False)
            typed = QLineEdit(value)
            typed.setPlaceholderText("ctrl+shift+s")
            typed.setFixedWidth(150)
            edit.changed.connect(typed.setText)
            wrapper = QWidget()
            wrapper.setLayout(hbox(edit, typed))
            wrapper.value = typed.text  # type: ignore[attr-defined]
            return wrapper
        if name == "text":
            edit = QPlainTextEdit(value)
            edit.setFixedHeight(90)
            edit.setMinimumWidth(260)
            return edit
        if kind == "args":
            edit = QLineEdit(shlex.join(value))
            edit.setPlaceholderText('--flag "a value with spaces"')
            edit.setMinimumWidth(260)
            return edit
        if name == "path":
            edit = QLineEdit(value)
            edit.setMinimumWidth(220)
            browse = button("Browse…")
            browse.clicked.connect(lambda: self._browse(edit))
            wrapper = QWidget()
            wrapper.setLayout(hbox(edit, browse))
            wrapper.value = edit.text  # type: ignore[attr-defined]
            return wrapper
        edit = QLineEdit(value)
        edit.setMinimumWidth(240)
        return edit

    def _browse(self, edit: QLineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose a program or file")
        if path:
            edit.setText(path)

    def _sync_position(self, *_) -> None:
        at_point = self.fields["at"].value() == "point"
        for name in ("x", "y"):
            self.fields[name].setEnabled(at_point)
        if hasattr(self, "pick_btn"):
            self.pick_btn.setEnabled(at_point)

    def _pick(self) -> None:
        window_mode = self.macro.target == "window" and self.step.type != "move"
        picker.pick(self.c.backend, "Click the position for this step", window_mode, self._picked, hide=self)

    def _picked(self, result, error: str) -> None:
        if error:
            self.error.setText(error)
            return
        if result is None:
            return
        if isinstance(result, PickResult):
            target = self.macro.window
            if target is not None and result.window.handle != target.handle:
                self.error.setText("That position is in a different window than this macro's target.")
                return
            p = result.point
            x, y = p.x, p.y
            self.hidden.update(child=p.child, cx=p.cx, cy=p.cy)
        else:
            x, y = result
        self.fields["x"].setValue(x)
        self.fields["y"].setValue(y)
        if "at" in self.fields:
            self.fields["at"].setValue("point")

    def _profile_picker(self, value: str) -> QComboBox:
        tool = PROFILE_STEPS[self.step.type]
        box = QComboBox()
        box.setMinimumWidth(260)
        for p in self.c.profiles:
            if p.tool == tool:
                box.addItem(p.name, p.id)
        if box.count() == 0:
            box.addItem(f"No saved {TOOL_NAMES[tool]} setups yet", "")
        box.setCurrentIndex(max(0, box.findData(value)))
        return box

    def _sync_until(self, *_) -> None:
        self.fields["ms"].setEnabled(self.fields["until"].value() == "time")

    def _value(self, name: str, widget):
        if isinstance(widget, Segmented):
            return widget.value()
        if isinstance(widget, QComboBox):
            return widget.currentData() if name == "profile" else widget.currentText()
        if isinstance(widget, Toggle):
            return widget.isChecked()
        if isinstance(widget, QPlainTextEdit):
            return widget.toPlainText()
        if hasattr(widget, "value") and callable(widget.value):
            return widget.value()
        if name == "args":
            return shlex.split(widget.text())
        return widget.text()

    def _accept(self) -> None:
        params = dict(self.hidden)
        try:
            for name, widget in self.fields.items():
                params[name] = self._value(name, widget)
            if "profile" in params and not params["profile"]:
                raise ValidationError("choose a saved setup for this step")
            if "combo" in params:
                params["combo"] = format_combo(parse_combo(params["combo"]))
            new = Step.from_dict({"type": self.step.type, "params": params, "enabled": self.step.enabled,
                                  "note": self.step.note})
        except (ValueError, ValidationError, KeyComboError) as exc:
            self.error.setText(str(exc).capitalize())
            return
        self.step.params = new.params
        self.accept()
