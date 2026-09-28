"""Autoclicker page."""

from __future__ import annotations

from ...core.models import ClickerConfig
from ...core.presets import CLICKER_PRESETS, apply_preset, clicker_tips
from ...platform.base import BackendError, PickResult
from ..widgets import Card, FieldRow, Message, Segmented, Toggle, button, spin
from .common import (
    IntervalEditor,
    LimitEditor,
    Page,
    PointsEditor,
    RunBar,
    WindowTargetPanel,
    format_elapsed,
    minimized_note,
    stack,
    two_columns,
)
from .profile_bar import ProfileBar, SmartPanel


class ClickerPage(Page):
    tool = "clicker"

    def __init__(self, controller):
        super().__init__("Autoclicker", "Click at the cursor, on a fixed set of spots, or inside a window in "
                                        "the background, even while it is minimized.", "background")
        self.c = controller
        self._loading = False
        cfg: ClickerConfig = controller.settings.clicker

        self.bar = RunBar("clicking", ["Clicks", "Rate", "Elapsed"])
        self.bar.toggled.connect(lambda: self.c.toggle("clicker"))
        self.body.addWidget(self.bar)
        self.profiles = ProfileBar(controller, "clicker", lambda: self.c.settings.clicker, self.apply_config)
        self.body.addWidget(self.profiles)
        self.smart = SmartPanel(CLICKER_PRESETS, self._apply_preset)
        self.body.addWidget(self.smart)
        controller.modes_changed.connect(self._sync_smart)

        grid = self.grid(2)

        click = Card("Click", "Which button and what kind of click.")
        self.button = Segmented([("left", "Left"), ("right", "Right"), ("middle", "Middle"),
                                 ("x1", "Back"), ("x2", "Forward")], cfg.button)
        self.action = Segmented([("single", "Single"), ("double", "Double"), ("triple", "Triple"),
                                 ("hold", "Hold")], cfg.action)
        self.hold = spin(0, 3_600_000, int(cfg.hold_ms), " ms", 120)
        self.hold_row = FieldRow("Hold each click for", self.hold)
        click.add(FieldRow("Button", self.button))
        click.add(FieldRow("Type", self.action))
        click.add(self.hold_row)

        stop = Card("Stop condition")
        self.limit = LimitEditor(cfg.limit, "clicks")
        stop.add(self.limit)
        grid.addLayout(stack(click, stop), 0, 0)

        timing = Card("Timing")
        self.interval = IntervalEditor(cfg.interval_ms, cfg.jitter_ms, "clicks")
        timing.add(self.interval)
        grid.addWidget(timing, 0, 1)

        where = Card("Where to click")
        self.location = Segmented([("cursor", "At the cursor"), ("points", "Fixed spots"),
                                   ("window", "Window (background)")], cfg.location)
        where.add(self.location)
        self.where_hint = Message("faint")
        where.add(self.where_hint)

        self.window_panel = WindowTargetPanel(controller, self)
        self.window_panel.set_target(cfg.window)
        self.screen_points = PointsEditor(controller, self, window_mode=False)
        self.window_points = PointsEditor(controller, self, window_mode=True)
        self.window_points.target_getter = lambda: self.window_panel.target
        if cfg.location == "window":
            self.window_points.set_points(cfg.points)
        else:
            self.screen_points.set_points(cfg.points)

        self.pos_jitter = spin(0, 500, cfg.position_jitter_px, " px", 100)
        self.pos_jitter_row = FieldRow("Random offset", self.pos_jitter, "Clicks land somewhere within this radius.")
        self.restore = Toggle("Put the cursor back after each click", cfg.restore_cursor)
        self.spoof = Toggle("Pretend the window is focused", cfg.spoof_focus)
        self.spoof.setToolTip("Some apps ignore input while they are in the background. This tells them they "
                              "are active without actually switching windows.")
        self.test_btn = button("Send one test click")
        self.test_result = Message("faint")
        self.where_columns = two_columns(
            [self.window_panel, self.screen_points, self.window_points],
            [self.pos_jitter_row, self.restore, self.spoof, self.test_btn, self.test_result],
        )
        where.add(self.where_columns)
        grid.addWidget(where, 1, 0, 1, 2)
        self.body.addStretch(1)

        if not controller.backend.supports_background:
            self.location.setOptionEnabled("window", False, "Background input is not available on this system.")

        self._target_handle = cfg.window.handle if cfg.window else 0
        # Must run before save(): drops spots that belonged to the old window.
        self.window_panel.changed.connect(self._target_changed)
        self.window_points.on_retarget = self._retarget
        for sig in (self.button.changed, self.action.changed, self.location.changed, self.interval.changed,
                    self.limit.changed, self.window_panel.changed, self.screen_points.changed,
                    self.window_points.changed):
            sig.connect(self.save)
        for w in (self.hold, self.pos_jitter):
            w.valueChanged.connect(self.save)
        for t in (self.restore, self.spoof):
            t.toggled.connect(self.save)
        self.window_panel.picked.connect(self._window_picked)
        self.test_btn.clicked.connect(self.test_click)
        self._sync_visibility()
        self._sync_smart()

    def apply_config(self, cfg: ClickerConfig) -> None:
        """Load a whole setup (saved profile or preset) into the page."""
        self._loading = True
        try:
            self.button.setValue(cfg.button)
            self.action.setValue(cfg.action)
            self.hold.setValue(int(cfg.hold_ms))
            self.interval.set_values(cfg.interval_ms, cfg.jitter_ms)
            self.limit.set_value(cfg.limit)
            self.location.setValue(cfg.location)
            self._target_handle = cfg.window.handle if cfg.window else 0
            self.window_panel.set_target(cfg.window)
            self.window_points.set_points(cfg.points if cfg.location == "window" else [])
            self.screen_points.set_points(cfg.points if cfg.location != "window" else [])
            self.pos_jitter.setValue(cfg.position_jitter_px)
            self.restore.setChecked(cfg.restore_cursor)
            self.spoof.setChecked(cfg.spoof_focus)
        finally:
            self._loading = False
        self.save()

    def _apply_preset(self, preset) -> None:
        self.apply_config(apply_preset(self.c.settings.clicker, preset))
        self.smart.applied.setText(f"Applied “{preset.name}”: {preset.description}")

    def _sync_smart(self) -> None:
        self.smart.setVisible(self.c.settings.smart_mode)
        if self.c.settings.smart_mode:
            self.smart.set_tips(clicker_tips(self.c.settings.clicker, self.c.backend))

    def _target_changed(self) -> None:
        target = self.window_panel.target
        handle = target.handle if target else 0
        if handle != self._target_handle:
            self.window_points.set_points([])
            if target is not None:
                self.test_result.setText("Now use Add spot to choose where to click in this window.")
        self._target_handle = handle

    def _retarget(self, window) -> None:
        # Same app, new window (it was restarted): keep the existing spots.
        self._target_handle = window.handle
        self.window_panel.set_target(window, emit=True)

    def _window_picked(self, result: PickResult) -> None:
        self.test_result.setText("")
        self.window_points.set_points([result.point])
        self.save()

    def _sync_visibility(self) -> None:
        loc = self.location.value()
        self.hold_row.setVisible(self.action.value() == "hold")
        self.window_panel.setVisible(loc == "window")
        self.window_points.setVisible(loc == "window")
        self.screen_points.setVisible(loc == "points")
        self.pos_jitter_row.setVisible(loc != "cursor")
        self.restore.setVisible(loc == "points")
        self.spoof.setVisible(loc == "window")
        self.test_btn.setVisible(loc == "window")
        if loc != "window":
            self.test_result.setText("")
        self.where_columns.setVisible(loc != "cursor")
        self.where_hint.setText({
            "cursor": "Clicks wherever the mouse pointer is. Works with every app.",
            "points": "Moves the real cursor to each spot in turn and clicks. Add several spots to cycle "
                      "through them.",
            "window": "Clicks inside the picked window without moving your cursor or changing focus. The "
                      "window can stay minimized or behind others if the app accepts background input. "
                      "Use the test click to check.",
        }[loc])

    def save(self, *_) -> None:
        if self._loading:
            return
        cfg = self.c.settings.clicker
        cfg.button = self.button.value()
        cfg.action = self.action.value()
        cfg.hold_ms = float(self.hold.value())
        cfg.interval_ms = self.interval.interval_ms()
        cfg.jitter_ms = self.interval.jitter_ms()
        cfg.limit = self.limit.value()
        cfg.location = self.location.value()
        cfg.points = list(self.window_points.points if cfg.location == "window" else self.screen_points.points)
        cfg.position_jitter_px = self.pos_jitter.value()
        cfg.restore_cursor = self.restore.isChecked()
        cfg.window = self.window_panel.target
        cfg.spoof_focus = self.spoof.isChecked()
        self._sync_visibility()
        self.c.save_settings()
        self.profiles.refresh_dirty()
        self._sync_smart()

    def test_click(self) -> None:
        cfg = self.c.settings.clicker
        if cfg.window is None or not cfg.points:
            self.test_result.setText("Pick a window and a spot first.")
            return
        try:
            target = self.c.backend.ensure_target(cfg.window)
            self.c.backend.bg_mouse(target, cfg.points[0], cfg.button, "click", 1, cfg.spoof_focus)
            self.test_result.setText("Sent. If nothing happened in the app, try turning on “Pretend the window "
                                     "is focused”. Some apps (many games) ignore background clicks."
                                     + minimized_note(self.c.backend, target))
        except BackendError as exc:
            self.test_result.setText(str(exc))


    def on_state(self, running: bool, message: str) -> None:
        self.bar.set_running(running, message)

    def tick(self) -> None:
        r = self.c.runners.get("clicker")
        if r is None or r.started_at is None:
            return
        elapsed = r.elapsed
        self.bar.set_stat("Clicks", f"{r.count:,}")
        self.bar.set_stat("Rate", f"{r.count / elapsed:,.1f}/s" if elapsed > 0.2 else "—")
        self.bar.set_stat("Elapsed", format_elapsed(elapsed))
        self.bar.set_note(r.status)
