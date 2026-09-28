"""Dumb mode: the whole app as one plain autoclicker."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from ..core.keys import display_combo
from ..core.models import ClickerConfig, RunLimit
from . import theme
from .widgets import IconButton, Segmented, StatusDot, button, dspin, hbox, label, restyle


class DumbView(QWidget):
    """Clicks per second, a mouse button and one big Start button. Nothing else."""

    def __init__(self, controller, on_exit: Callable[[], None]):
        super().__init__()
        self.c = controller
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 20)
        outer.setSpacing(16)

        cube = QLabel()
        cube.setPixmap(QPixmap(str(theme.ASSETS / "cube.png")).scaled(
            34, 34, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        title = QLabel("IDB-Macro")
        title.setFont(theme.ui_font(17, QFont.Weight.Bold))
        pill = label("DUMB MODE", "section")
        outer.addLayout(hbox(cube, title, None, pill, spacing=10))

        card = QFrame()
        card.setObjectName("Card")
        body = QVBoxLayout(card)
        body.setContentsMargins(24, 22, 24, 22)
        body.setSpacing(14)
        cfg = controller.settings.dumb
        body.addWidget(label("Clicks per second", "muted"))
        self.cps = dspin(0.1, 200, round(1000.0 / cfg.interval_ms, 2), 1, "", 300)
        self.cps.setStyleSheet("font-size: 30px; font-weight: 600;")
        self.cps.setMinimumHeight(64)
        self.cps.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.addWidget(self.cps, 0, Qt.AlignmentFlag.AlignHCenter)
        self.button = Segmented([("left", "Left click"), ("right", "Right click"), ("middle", "Middle")],
                                cfg.button if cfg.button in ("left", "right", "middle") else "left")
        body.addWidget(self.button, 0, Qt.AlignmentFlag.AlignHCenter)
        self.run = IconButton("play", "Start clicking", "run")
        self.run.setMinimumHeight(64)
        body.addWidget(self.run)
        self.dot = StatusDot()
        self.status = label("Idle", "muted")
        body.addLayout(hbox(None, self.dot, self.status, None, spacing=6))
        outer.addWidget(card, 1)

        self.hint = label("", "faint")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        outer.addWidget(self.hint)
        back = button("Back to the full app", "ghost")
        back.clicked.connect(on_exit)
        outer.addWidget(back, 0, Qt.AlignmentFlag.AlignHCenter)

        self.cps.valueChanged.connect(self.save)
        self.button.changed.connect(self.save)
        self.run.clicked.connect(lambda: self.c.toggle("clicker"))
        controller.hotkeys_updated.connect(self.refresh_hint)
        self.refresh_hint()

    def save(self, *_) -> None:
        # Always the plain case: click at the cursor until stopped.
        self.c.settings.dumb = ClickerConfig(button=self.button.value(), interval_ms=1000.0 / self.cps.value(),
                                             location="cursor", limit=RunLimit())
        self.c.save_settings()

    def refresh_hint(self) -> None:
        start, panic = self.c.settings.hotkeys.get("clicker", ""), self.c.settings.hotkeys.get("panic", "")
        parts = []
        if start:
            parts.append(f"{display_combo(start)} starts and stops, even in other apps")
        if panic:
            parts.append(f"{display_combo(panic)} stops everything")
        self.hint.setText("  ·  ".join(parts))

    def on_state(self, running: bool, message: str) -> None:
        self.run.setText(("      Stop" if running else "      Start") + " clicking")
        self.run.set_icon("stop" if running else "play")
        self.run.setProperty("running", "true" if running else "false")
        restyle(self.run)
        self.dot.set_state("running" if running else ("idle" if message in ("", "Stopped", "Finished")
                                                       else "error"))
        self.status.setText("Clicking" if running else (message or "Idle"))

    def tick(self) -> None:
        r = self.c.runners.get("clicker")
        if r is not None and r.is_alive():
            self.status.setText(f"Clicking  ·  {r.count:,} clicks")
