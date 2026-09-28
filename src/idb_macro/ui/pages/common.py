"""Building blocks shared by the tool pages."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...core.keys import display_combo
from ...core.models import RunLimit, TargetPoint, WindowTarget
from ...core.timing import MAX_INTERVAL_MS, MIN_INTERVAL_MS, interval_to_cps
from ...platform.base import PickResult
from .. import picker
from ..widgets import (
    Card,
    FieldRow,
    IconButton,
    Segmented,
    StatTile,
    StatusDot,
    button,
    dspin,
    hbox,
    label,
    restyle,
    spin,
    vbox,
)

MAX_CONTENT_WIDTH = 1240


class Page(QWidget):
    """Header + scrolling body."""

    def __init__(self, title: str, subtitle: str, explainer: str = ""):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        # A centred column with a maximum width keeps lines short and the
        # layout balanced on wide screens.
        canvas = QWidget()
        row = QHBoxLayout(canvas)
        row.setContentsMargins(36, 30, 36, 32)
        column = QWidget()
        column.setMaximumWidth(MAX_CONTENT_WIDTH)
        row.addStretch(0)
        row.addWidget(column, 1)
        row.addStretch(0)
        self.body = QVBoxLayout(column)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(18)
        head = QVBoxLayout()
        head.setSpacing(6)
        if explainer:
            from ..explainer import bulb

            head.addLayout(hbox(label(title, "title"), bulb(self, explainer), None, spacing=10))
        else:
            head.addWidget(label(title, "title"))
        head.addWidget(label(subtitle, "subtitle", wrap=True))
        self.body.addLayout(head)
        self.body.addSpacing(4)
        scroll.setWidget(canvas)

    def grid(self, columns: int = 2) -> QGridLayout:
        g = QGridLayout()
        g.setSpacing(18)
        for c in range(columns):
            g.setColumnStretch(c, 1)
        self.body.addLayout(g)
        return g


class RunBar(QFrame):
    """Start/stop button, live stats and the status line."""

    toggled = Signal()

    def __init__(self, noun: str, stats: list[str]):
        super().__init__()
        self.setObjectName("Card")
        self.noun = noun
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 16)
        lay.setSpacing(12)
        self.run = IconButton("play", f"Start {noun}", "run")
        self.run.setMinimumWidth(200)
        self.run.setMinimumHeight(64)
        self.run.clicked.connect(lambda: self.toggled.emit())
        self.tiles = {name: StatTile(name, "—") for name in stats}
        row = hbox(self.run, spacing=14)
        for tile in self.tiles.values():
            row.addWidget(tile, 1)
        self.tiles_list = list(self.tiles.values())
        lay.addLayout(row)
        self.dot = StatusDot()
        self.status = label("Idle", "muted")
        self.hint = label("", "faint")
        lay.addLayout(hbox(self.dot, self.status, None, self.hint, spacing=6))

    def set_hotkey(self, combo: str) -> None:
        self.hint.setText(f"{display_combo(combo)} starts and stops, even in other apps" if combo else
                          "No hotkey set")

    def set_running(self, running: bool, message: str = "") -> None:
        self.run.setText(("      Stop " if running else "      Start ") + self.noun)
        self.run.set_icon("stop" if running else "play")
        self.run.setProperty("running", "true" if running else "false")
        restyle(self.run)
        for tile in self.tiles_list:
            tile.set_active(running)
        if running:
            self.dot.set_state("running")
            self.status.setText("Running")
            self.status.setProperty("role", "muted")
        else:
            finished = message in ("", "Stopped", "Finished")
            self.dot.set_state("idle" if finished else "error")
            self.status.setText(message or "Idle")
            self.status.setProperty("role", "muted" if finished else "error")
        restyle(self.status)

    def set_stat(self, name: str, text: str) -> None:
        self.tiles[name].set(text)

    def set_note(self, note: str) -> None:
        """While running, show why input is held back (smart mode), or plain "Running"."""
        if self.dot.state not in ("running", "armed"):
            return
        self.dot.set_state("armed" if note else "running")
        self.status.setText(note or "Running")


def format_elapsed(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class IntervalEditor(QWidget):
    """Interval as h/m/s/ms, or as a rate per second."""

    changed = Signal()

    def __init__(self, interval_ms: float, jitter_ms: float, rate_word: str = "clicks"):
        super().__init__()
        self.rate_word = rate_word
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self.mode = Segmented([("interval", "Interval"), ("rate", "Per second")])
        lay.addWidget(FieldRow("Speed as", self.mode))

        self.h = spin(0, 23, 0, " h", 70)
        self.m = spin(0, 59, 0, " m", 72)
        self.s = spin(0, 59, 0, " s", 70)
        self.ms = spin(0, 999, 100, " ms", 90)
        self.interval_row = QWidget()
        self.interval_row.setLayout(hbox(self.h, self.m, self.s, self.ms, spacing=6))
        self.rate = dspin(0.02, 1000, 10, 2, f" {rate_word}/s", 150)
        stack = QWidget()
        stack.setLayout(hbox(self.interval_row, self.rate, spacing=0))
        self.every_row = FieldRow("Every", stack)
        lay.addWidget(self.every_row)

        self.jitter = spin(0, 60_000, int(jitter_ms), " ms", 110)
        lay.addWidget(FieldRow("Random variation", self.jitter,
                               "Adds ± this much to every gap so the timing looks less mechanical."))

        self.set_interval(interval_ms)
        self.mode.changed.connect(self._mode_changed)
        for w in (self.h, self.m, self.s, self.ms, self.jitter):
            w.valueChanged.connect(self._emit)
        self.rate.valueChanged.connect(self._emit)
        self._show_mode()

    def set_interval(self, ms: float) -> None:
        ms = int(round(ms))
        h, rem = divmod(ms, 3_600_000)
        m, rem = divmod(rem, 60_000)
        s, milli = divmod(rem, 1000)
        for w, v in ((self.h, h), (self.m, m), (self.s, s), (self.ms, milli)):
            w.blockSignals(True)
            w.setValue(v)
            w.blockSignals(False)
        self.rate.blockSignals(True)
        self.rate.setValue(interval_to_cps(max(MIN_INTERVAL_MS, ms)))
        self.rate.blockSignals(False)
        self._update_label()

    def set_values(self, interval_ms: float, jitter_ms: float) -> None:
        self.jitter.blockSignals(True)
        self.jitter.setValue(int(jitter_ms))
        self.jitter.blockSignals(False)
        self.set_interval(interval_ms)

    def interval_ms(self) -> float:
        ms = 1000.0 / self.rate.value() if self.mode.value() == "rate" else self._fields_ms()
        return min(MAX_INTERVAL_MS, max(MIN_INTERVAL_MS, ms))

    def jitter_ms(self) -> float:
        return float(self.jitter.value())

    def _mode_changed(self, mode: str) -> None:
        # Carry the current speed across when the user switches units.
        if mode == "rate":
            self.rate.setValue(interval_to_cps(max(MIN_INTERVAL_MS, self._fields_ms())))
        else:
            self.set_interval(1000.0 / self.rate.value())
        self._show_mode()
        self._emit()

    def _show_mode(self) -> None:
        self.interval_row.setVisible(self.mode.value() == "interval")
        self.rate.setVisible(self.mode.value() == "rate")

    def _fields_ms(self) -> float:
        return ((self.h.value() * 60 + self.m.value()) * 60 + self.s.value()) * 1000 + self.ms.value()

    def _update_label(self) -> None:
        ms = self.interval_ms()
        rate = 1000.0 / ms
        text = f"≈ {rate:,.1f} {self.rate_word} per second" if rate >= 0.1 else f"one every {ms / 1000:,.1f} s"
        if ms < 10:
            text += "  ·  very fast: some apps drop input at this speed"
        self.every_row.hint.setText(text)

    def _emit(self, *_) -> None:
        self._update_label()
        self.changed.emit()


class LimitEditor(QWidget):
    changed = Signal()

    def __init__(self, limit: RunLimit, noun: str = "clicks"):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self.mode = Segmented([("forever", "Until stopped"), ("count", f"After N {noun}"),
                               ("duration", "After a time")], limit.mode)
        lay.addWidget(self.mode)
        self.count = spin(1, 1_000_000_000, limit.count, f" {noun}", 170)
        self.seconds = dspin(0.1, 7 * 24 * 3600, limit.seconds, 1, " s", 150)
        self.count_row = FieldRow("Stop after", self.count)
        self.seconds_row = FieldRow("Stop after", self.seconds)
        lay.addWidget(self.count_row)
        lay.addWidget(self.seconds_row)
        self.mode.changed.connect(self._sync)
        self.count.valueChanged.connect(lambda _: self.changed.emit())
        self.seconds.valueChanged.connect(lambda _: self.changed.emit())
        self._sync()

    def _sync(self, *_):
        self.count_row.setVisible(self.mode.value() == "count")
        self.seconds_row.setVisible(self.mode.value() == "duration")
        self.changed.emit()

    def value(self) -> RunLimit:
        return RunLimit(self.mode.value(), self.count.value(), self.seconds.value())

    def set_value(self, limit: RunLimit) -> None:
        for w in (self.mode, self.count, self.seconds):
            w.blockSignals(True)
        self.mode.setValue(limit.mode)
        self.count.setValue(limit.count)
        self.seconds.setValue(limit.seconds)
        for w in (self.mode, self.count, self.seconds):
            w.blockSignals(False)
        self._sync()


class WindowTargetPanel(QFrame):
    """Shows the background target window with pick / choose / clear controls."""

    changed = Signal()
    picked = Signal(object)  # PickResult

    def __init__(self, controller, host: QWidget):
        super().__init__()
        self.controller = controller
        self.host = host
        self.target: WindowTarget | None = None
        self.setObjectName("Inset")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)
        self.dot = StatusDot()
        self.title = QLabel("No window selected")
        self.title.setWordWrap(True)
        # Window titles come from other apps (and web pages): never render them as rich text.
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.detail = label("Pick the window (and spot) that should receive the input.", "faint", wrap=True)
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        lay.addLayout(hbox(self.dot, vbox(self.title, self.detail, spacing=2), spacing=8))
        self.pick_btn = IconButton("target", "Pick on screen", "primary")
        self.choose_btn = button("Choose window ▾")
        self.clear_btn = button("Clear", "ghost")
        lay.addLayout(hbox(self.pick_btn, self.choose_btn, None, self.clear_btn))
        self.pick_btn.clicked.connect(self.pick)
        self.choose_btn.clicked.connect(self.choose)
        self.clear_btn.clicked.connect(lambda: self.set_target(None, emit=True))
        if not controller.backend.supports_background:
            for w in (self.pick_btn, self.choose_btn, self.clear_btn):
                w.setEnabled(False)
            self.detail.setText("Background input is not available on this system.")
        self.alive_timer = QTimer(self)
        self.alive_timer.timeout.connect(self._refresh_alive)
        self.alive_timer.start(1500)

    def set_target(self, target: WindowTarget | None, emit: bool = False) -> None:
        self.target = target
        if target is None:
            self.title.setText("No window selected")
            self.detail.setText("Pick the window (and spot) that should receive the input.")
        else:
            self.title.setText(target.title or target.window_class or "Untitled window")
            bits = [b for b in (target.process, target.window_class) if b]
            self.detail.setText("  ·  ".join(bits) if bits else "")
        self._refresh_alive()
        if emit:
            self.changed.emit()

    def _refresh_alive(self) -> None:
        if self.target is None:
            self.dot.set_state("idle")
            return
        try:
            alive = self.controller.backend.window_alive(self.target)
            minimized = alive and self.controller.backend.is_minimized(self.target)
        except Exception:
            alive = minimized = False
        self.dot.set_state("running" if alive and not minimized else "armed")
        if minimized:
            self.dot.setToolTip("Minimized. Some apps (Discord, browsers, most games) ignore input while "
                                "minimized; leave the window open behind others instead.")
        else:
            self.dot.setToolTip("Window found" if alive else
                                "Window not open right now; it will be found again by its app when you start")

    def pick(self) -> None:
        picker.pick(self.controller.backend, "Click the window and the exact spot to target", True,
                    self._picked, hide=self.host.window())

    def _picked(self, result, error: str) -> None:
        if error:
            self.detail.setText(error)
            return
        if isinstance(result, PickResult):
            self.set_target(result.window, emit=True)
            self.picked.emit(result)

    def choose(self) -> None:
        menu = QMenu(self)
        windows = self.controller.backend.list_windows()
        if not windows:
            menu.addAction("No windows found").setEnabled(False)
        for w in sorted(windows, key=lambda w: w.title.lower())[:60]:
            text = w.title if len(w.title) <= 60 else w.title[:57] + "…"
            action = menu.addAction(f"{text}    —    {w.process}" if w.process else text)
            action.triggered.connect(lambda _=False, w=w: self.set_target(w, emit=True))
        menu.exec(self.choose_btn.mapToGlobal(self.choose_btn.rect().bottomLeft()))


class PointEditDialog(QDialog):
    def __init__(self, parent, x: int, y: int, caption: str):
        super().__init__(parent)
        self.setWindowTitle("Edit point")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.addWidget(label(caption, "faint", wrap=True))
        self.x = spin(-100_000, 100_000, x, "", 110)
        self.y = spin(-100_000, 100_000, y, "", 110)
        lay.addWidget(FieldRow("X", self.x))
        lay.addWidget(FieldRow("Y", self.y))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)


class PointsEditor(QWidget):
    """A list of click points with pick / edit / remove."""

    changed = Signal()

    def __init__(self, controller, host: QWidget, window_mode: bool):
        super().__init__()
        self.controller = controller
        self.host = host
        self.window_mode = window_mode
        self.target_getter = lambda: None
        # Called with a new window when the picked spot belongs to a restarted
        # instance of the target app.
        self.on_retarget = lambda window: None
        self.points: list[TargetPoint] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.list = QListWidget()
        self.list.setMinimumHeight(84)
        self.list.setMaximumHeight(140)
        self.list.itemDoubleClicked.connect(lambda _: self.edit())
        lay.addWidget(self.list)
        self.add_btn = IconButton("target", "Add spot", "primary")
        self.edit_btn = button("Edit")
        self.remove_btn = button("Remove", "ghost")
        self.clear_btn = button("Clear", "ghost")
        lay.addLayout(hbox(self.add_btn, self.edit_btn, None, self.remove_btn, self.clear_btn))
        self.add_btn.clicked.connect(self.add)
        self.edit_btn.clicked.connect(self.edit)
        self.remove_btn.clicked.connect(self.remove)
        self.clear_btn.clicked.connect(self.clear)

    def set_points(self, points: list[TargetPoint]) -> None:
        self.points = [TargetPoint(**vars(p)) for p in points]
        self._render()

    def _render(self) -> None:
        self.list.clear()
        for i, p in enumerate(self.points, 1):
            where = "in window" if self.window_mode else "on screen"
            QListWidgetItem(f"#{i}    {p.x}, {p.y}    {where}", self.list)
        if not self.points:
            item = QListWidgetItem("No spots yet. Use Add spot and click where it should click.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(item)

    def add(self) -> None:
        prompt = "Click the spot inside the target window" if self.window_mode else "Click the spot to add"
        picker.pick(self.controller.backend, prompt, self.window_mode, self._picked, hide=self.host.window())

    def _picked(self, result, error: str) -> None:
        if error or result is None:
            return
        if isinstance(result, PickResult):
            target = self.target_getter()
            if target is not None and result.window.handle != target.handle:
                restarted = (bool(result.window.process)
                             and result.window.process.lower() == target.process.lower()
                             and not self.controller.backend.window_alive(target))
                if not restarted:
                    self.host.window().statusBar().showMessage(
                        "That spot is in a different window. Use Pick on screen to switch windows.", 6000)
                    return
                self.on_retarget(result.window)
            self.points.append(result.point)
        else:
            self.points.append(TargetPoint(*result))
        self._render()
        self.changed.emit()

    def add_point(self, point: TargetPoint) -> None:
        self.points.append(point)
        self._render()
        self.changed.emit()

    def edit(self) -> None:
        row = self.list.currentRow()
        if not 0 <= row < len(self.points):
            return
        p = self.points[row]
        caption = ("Coordinates inside the target window's client area, in physical pixels."
                   if self.window_mode else "Screen coordinates in physical pixels.")
        dlg = PointEditDialog(self, p.x, p.y, caption)
        if dlg.exec():
            dx, dy = dlg.x.value() - p.x, dlg.y.value() - p.y
            p.x, p.y, p.cx, p.cy = p.x + dx, p.y + dy, p.cx + dx, p.cy + dy
            self._render()
            self.changed.emit()

    def remove(self) -> None:
        row = self.list.currentRow()
        if 0 <= row < len(self.points):
            del self.points[row]
            self._render()
            self.changed.emit()

    def clear(self) -> None:
        self.points = []
        self._render()
        self.changed.emit()


def minimized_note(backend, target: WindowTarget) -> str:
    """Explain why input to a minimized target may do nothing, or return ''."""
    try:
        if not backend.is_minimized(target):
            return ""
    except Exception:
        return ""
    if target.window_class.startswith("Chrome_WidgetWin"):
        return (" This window is minimized, and Chromium-based apps (Discord, browsers, Electron apps) ignore "
                "input while minimized. Leave it open behind other windows instead.")
    return (" This window is minimized. If nothing happened, restore it and leave it behind other windows: "
            "some apps ignore input while minimized.")


def stack(*cards: QWidget) -> QVBoxLayout:
    """Cards on top of each other in one grid cell; the last one takes spare height."""
    lay = QVBoxLayout()
    lay.setSpacing(18)
    for i, card in enumerate(cards):
        lay.addWidget(card, 1 if i == len(cards) - 1 else 0)
    return lay


def two_columns(left: list[QWidget], right: list[QWidget]) -> QWidget:
    """Side-by-side columns inside a card, both pinned to the top."""
    box = QWidget()
    row = QHBoxLayout(box)
    row.setContentsMargins(0, 4, 0, 0)
    row.setSpacing(28)
    for items, stretch in ((left, 3), (right, 2)):
        col = QVBoxLayout()
        col.setSpacing(14)
        for w in items:
            col.addWidget(w, 0, Qt.AlignmentFlag.AlignLeft if isinstance(w, QPushButton) else Qt.AlignmentFlag(0))
        col.addStretch(1)
        row.addLayout(col, stretch)
    return box


def section(text: str) -> QLabel:
    return label(text.upper(), "section")


__all__ = ["Page", "RunBar", "IntervalEditor", "LimitEditor", "WindowTargetPanel", "PointsEditor", "Card",
           "FieldRow", "Segmented", "section", "format_elapsed"]
