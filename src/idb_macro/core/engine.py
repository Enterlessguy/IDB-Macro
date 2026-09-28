"""Runners that turn configs into input, one thread per active tool."""

from __future__ import annotations

import logging
import os
import random
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable

from ..platform.base import Backend, BackendError
from .keys import parse_combo
from .models import (
    PROFILE_STEPS,
    STEP_SPECS,
    ClickerConfig,
    KeyRepeaterConfig,
    Macro,
    RunLimit,
    Step,
    TargetPoint,
    WindowTarget,
)
from .profiles import TOOL_NAMES, Profile
from .timing import Scheduler, jitter_point, jittered_ms

log = logging.getLogger(__name__)

EventCallback = Callable[[str, str], None]

CLICK_COUNTS = {"single": 1, "double": 2, "triple": 3, "hold": 1}


class Runner(threading.Thread):
    """Base runner: owns the stop flag, limits, fail-safe and held-input cleanup.

    ``on_event(kind, message)`` is called from the runner thread with
    ``kind`` = ``"started"`` or ``"stopped"``.
    """

    tool = "runner"

    def __init__(self, backend: Backend, on_event: EventCallback | None = None,
                 failsafe: Callable[[], bool] | None = None, rng: random.Random | None = None,
                 guard=None):
        super().__init__(daemon=True, name=f"idb-{self.tool}")
        self.backend = backend
        # Optional SmartGuard; see allowed().
        self.guard = guard
        # Why the run is currently holding back, shown in the UI ("" when active).
        self.status = ""
        self.on_event = on_event or (lambda kind, msg: None)
        self.failsafe = failsafe or (lambda: False)
        self.rng = rng or random.Random()
        self.stop_event = threading.Event()
        self.sched = Scheduler(self.stop_event)
        self.count = 0
        self.started_at: float | None = None
        self.finished_reason = ""
        self._held_keys: list[tuple[WindowTarget | None, str]] = []
        self._held_buttons: list[tuple[WindowTarget | None, str, TargetPoint | None]] = []

    # ---- lifecycle ----------------------------------------------------------

    def stop(self) -> None:
        self.stop_event.set()

    @property
    def elapsed(self) -> float:
        return 0.0 if self.started_at is None else time.perf_counter() - self.started_at

    def run(self) -> None:
        self.started_at = time.perf_counter()
        self.on_event("started", "")
        reason = "Stopped"
        try:
            with self.backend.session():
                try:
                    reason = self.work()
                finally:
                    self.release_all()
        except BackendError as exc:
            reason = str(exc)
        except Exception as exc:  # keep the UI alive and tell the user
            log.exception("%s runner crashed", self.tool)
            reason = f"Unexpected error: {exc}"
        self.finished_reason = reason
        self.on_event("stopped", reason)

    def work(self) -> str:
        raise NotImplementedError

    # ---- helpers ------------------------------------------------------------

    def limit_reached(self, limit: RunLimit) -> bool:
        if limit.mode == "count":
            return self.count >= limit.count
        if limit.mode == "duration":
            return self.elapsed >= limit.seconds
        return False

    def wait_interval(self, limit: RunLimit, base_ms: float, jitter_ms: float) -> bool:
        """Sleep until the next tick; False if stopped."""
        self.sched.advance(jittered_ms(base_ms, jitter_ms, self.rng))
        deadline = self.sched.next_deadline
        if limit.mode == "duration" and self.started_at is not None:
            deadline = min(deadline, self.started_at + limit.seconds)
        return self.sched.wait_until(deadline)

    def allowed(self, pointer: bool, point: tuple[int, int] | None = None) -> bool:
        """Ask the smart guard whether a foreground action may go ahead now."""
        if self.guard is None:
            return True
        self.status = self.guard.check(pointer, point)
        return not self.status

    def check_failsafe(self, foreground: bool) -> None:
        if foreground and self.failsafe():
            raise BackendError("Stopped by the fail-safe (cursor moved to the top-left corner).")

    def hold_key(self, target: WindowTarget | None, key: str, spoof: bool = False) -> None:
        held = tuple(k for t, k in self._held_keys if t is target)
        if target is None:
            self.backend.key_down(key)
        else:
            self.backend.bg_key(target, key, True, held, spoof)
        self._held_keys.append((target, key))

    def release_key(self, target: WindowTarget | None, key: str, spoof: bool = False) -> None:
        if (target, key) in self._held_keys:
            self._held_keys.remove((target, key))
        held = tuple(k for t, k in self._held_keys if t is target)
        if target is None:
            self.backend.key_up(key)
        else:
            self.backend.bg_key(target, key, False, held, spoof)

    def hold_button(self, target: WindowTarget | None, button: str, point: TargetPoint | None,
                    spoof: bool = False) -> None:
        if target is None:
            self.backend.mouse_down(button)
        else:
            self.backend.bg_mouse(target, point or TargetPoint(), button, "down", 1, spoof)
        self._held_buttons.append((target, button, point))

    def release_button(self, target: WindowTarget | None, button: str, point: TargetPoint | None,
                       spoof: bool = False) -> None:
        for entry in list(self._held_buttons):
            if entry[0] is target and entry[1] == button:
                self._held_buttons.remove(entry)
                point = point or entry[2]
                break
        if target is None:
            self.backend.mouse_up(button)
        else:
            self.backend.bg_mouse(target, point or TargetPoint(), button, "up", 1, spoof)

    def release_all(self) -> None:
        """Never leave a key or button stuck down, whatever ended the run."""
        for target, key in reversed(self._held_keys):
            try:
                if target is None:
                    self.backend.key_up(key)
                else:
                    self.backend.bg_key(target, key, False)
            except Exception:
                log.debug("release of %s failed", key, exc_info=True)
        self._held_keys.clear()
        for target, button, point in reversed(self._held_buttons):
            try:
                if target is None:
                    self.backend.mouse_up(button)
                else:
                    self.backend.bg_mouse(target, point or TargetPoint(), button, "up")
            except Exception:
                log.debug("release of %s failed", button, exc_info=True)
        self._held_buttons.clear()


# --------------------------------------------------------------------- clicker

class ClickerRunner(Runner):
    tool = "clicker"

    def __init__(self, backend: Backend, config: ClickerConfig, **kw):
        super().__init__(backend, **kw)
        self.cfg = config

    def work(self) -> str:
        cfg = self.cfg
        target = None
        if cfg.location == "window":
            if cfg.window is None:
                raise BackendError("Pick a target window first.")
            if not cfg.points:
                raise BackendError("Pick the spot to click inside the target window.")
            target = self.backend.ensure_target(cfg.window)
        elif cfg.location == "points" and not cfg.points:
            raise BackendError("Add at least one click point.")

        foreground = target is None
        index = 0
        self.sched.reset()
        while True:
            if self.limit_reached(cfg.limit):
                return "Finished"
            self.check_failsafe(foreground)
            if not foreground or self.allowed(True, self.aim_point(index)):
                self.click_once(target, index)
                self.count += 1
                index += 1
            if not self.wait_interval(cfg.limit, cfg.interval_ms, cfg.jitter_ms):
                return "Stopped" if self.stop_event.is_set() else "Finished"

    def aim_point(self, index: int) -> tuple[int, int] | None:
        if self.cfg.location != "points":
            return None
        p = self.cfg.points[index % len(self.cfg.points)]
        return p.x, p.y

    def click_once(self, target: WindowTarget | None, index: int) -> None:
        cfg = self.cfg
        count = CLICK_COUNTS[cfg.action]
        hold = cfg.action == "hold"

        if cfg.location == "cursor":
            if hold:
                self.hold_button(None, cfg.button, None)
                self.sched.sleep(cfg.hold_ms)
                self.release_button(None, cfg.button, None)
            else:
                self.backend.click(cfg.button, count)
            return

        base = cfg.points[index % len(cfg.points)]
        x, y = jitter_point(base.x, base.y, cfg.position_jitter_px, self.rng)
        dx, dy = x - base.x, y - base.y

        if target is not None:
            point = TargetPoint(x, y, base.child, base.cx + dx, base.cy + dy)
            if hold:
                self.hold_button(target, cfg.button, point, cfg.spoof_focus)
                self.sched.sleep(cfg.hold_ms)
                self.release_button(target, cfg.button, point, cfg.spoof_focus)
            else:
                self.backend.bg_mouse(target, point, cfg.button, "click", count, cfg.spoof_focus)
            return

        original = self.backend.cursor_pos() if cfg.restore_cursor else None
        self.backend.move(x, y)
        if hold:
            self.hold_button(None, cfg.button, None)
            self.sched.sleep(cfg.hold_ms)
            self.release_button(None, cfg.button, None)
        else:
            self.backend.click(cfg.button, count)
        if original is not None:
            self.backend.move(*original)


# ---------------------------------------------------------------- key repeater

class KeyRunner(Runner):
    tool = "keys"

    def __init__(self, backend: Backend, config: KeyRepeaterConfig, **kw):
        super().__init__(backend, **kw)
        self.cfg = config

    def work(self) -> str:
        cfg = self.cfg
        combos = [parse_combo(k) for k in cfg.keys]
        if not combos:
            raise BackendError("Add at least one key to repeat.")
        target = None
        if cfg.target == "window":
            if cfg.window is None:
                raise BackendError("Pick a target window first.")
            target = self.backend.ensure_target(cfg.window)
        foreground = target is None

        if cfg.action == "hold":
            return self.hold_until_stopped(target, combos)

        index = 0
        self.sched.reset()
        while True:
            if self.limit_reached(cfg.limit):
                return "Finished"
            self.check_failsafe(foreground)
            if not foreground or self.allowed(False):
                group = combos if cfg.sequence == "together" else [combos[index % len(combos)]]
                keys = list(dict.fromkeys(k for combo in group for k in combo))
                for k in keys:
                    self.hold_key(target, k, cfg.spoof_focus)
                self.sched.sleep(cfg.hold_ms)
                for k in reversed(keys):
                    self.release_key(target, k, cfg.spoof_focus)
                self.count += 1
                index += 1
            if not self.wait_interval(cfg.limit, cfg.interval_ms, cfg.jitter_ms):
                return "Stopped" if self.stop_event.is_set() else "Finished"

    def hold_until_stopped(self, target: WindowTarget | None, combos: list[tuple[str, ...]]) -> str:
        cfg = self.cfg
        keys = list(dict.fromkeys(k for combo in combos for k in combo))
        holding = False
        self.sched.reset()
        while True:
            if cfg.limit.mode == "duration" and self.limit_reached(cfg.limit):
                return "Finished"
            self.check_failsafe(target is None)
            ok = target is not None or self.allowed(False)
            if ok and not holding:
                for k in keys:
                    self.hold_key(target, k, cfg.spoof_focus)
                holding = True
                self.count = max(self.count, 1)
            elif not ok and holding:
                # Let go while another app is active so the key cannot leak into it.
                for k in reversed(keys):
                    self.release_key(target, k, cfg.spoof_focus)
                holding = False
            if not self.wait_interval(cfg.limit, cfg.interval_ms, 0):
                return "Stopped" if self.stop_event.is_set() else "Finished"
            if target is not None and holding:
                # Windows apps expect auto-repeat key-downs while a key is held.
                held: tuple[str, ...] = ()
                for k in keys:
                    self.backend.bg_key(target, k, True, held, cfg.spoof_focus)
                    held += (k,)
                self.count += 1
            if cfg.limit.mode == "count" and self.count >= cfg.limit.count:
                return "Finished"


# ----------------------------------------------------------------------- macro

class MacroRunner(Runner):
    tool = "macro"

    def __init__(self, backend: Backend, macro: Macro, profiles: dict[str, Profile] | None = None,
                 guard_factory: Callable[[], object] | None = None, **kw):
        super().__init__(backend, **kw)
        self.macro = macro
        self.profiles = profiles or {}
        self.guard_factory = guard_factory
        self.current_step = -1
        self.nested: Runner | None = None

    def work(self) -> str:
        macro = self.macro
        if not any(s.enabled for s in macro.steps):
            raise BackendError("This macro has no enabled steps.")
        target = None
        if macro.target == "window":
            if macro.window is None:
                raise BackendError("Pick a target window for this macro first.")
            target = self.backend.ensure_target(macro.window)

        loops = 0
        while macro.repeat == 0 or loops < macro.repeat:
            for index, step in enumerate(macro.steps):
                if self.stop_event.is_set():
                    return "Stopped"
                if not step.enabled:
                    continue
                self.current_step = index
                self.check_failsafe(target is None)
                self.run_step(step, target)
            loops += 1
            self.count = loops
            # Release anything a step left held before the next loop starts.
            self.release_all()
        return "Stopped" if self.stop_event.is_set() else "Finished"

    def scaled(self, ms: float) -> float:
        return ms / self.macro.speed

    def point_of(self, step: Step) -> TargetPoint:
        g = step.get
        return TargetPoint(g("x"), g("y"), g("child"), g("cx"), g("cy"))

    def run_step(self, step: Step, target: WindowTarget | None) -> None:
        g, t, b = step.get, step.type, self.backend
        spoof = self.macro.spoof_focus
        at_point = "at" in STEP_SPECS[t] and g("at") == "point"

        if t == "click":
            if target is not None:
                b.bg_mouse(target, self.point_of(step), g("button"), "click", g("count"), spoof)
            else:
                if at_point:
                    b.move(g("x"), g("y"))
                b.click(g("button"), g("count"))
        elif t == "mouse_down":
            if target is None and at_point:
                b.move(g("x"), g("y"))
            self.hold_button(target, g("button"), self.point_of(step) if target else None, spoof)
        elif t == "mouse_up":
            if target is None and at_point:
                b.move(g("x"), g("y"))
            self.release_button(target, g("button"), self.point_of(step) if target else None, spoof)
        elif t == "move":
            if target is not None:
                b.bg_mouse(target, self.point_of(step), "left", "move", 1, spoof)
            else:
                self.glide(g("x"), g("y"), self.scaled(g("duration_ms")))
        elif t == "scroll":
            if target is not None:
                b.bg_scroll(target, self.point_of(step), g("amount"), g("horizontal"), spoof)
            else:
                if at_point:
                    b.move(g("x"), g("y"))
                b.scroll(g("amount"), g("horizontal"))
        elif t == "key":
            combo = parse_combo(g("combo"))
            for k in combo:
                self.hold_key(target, k, spoof)
            self.sched.sleep(g("hold_ms"))
            for k in reversed(combo):
                self.release_key(target, k, spoof)
        elif t == "key_down":
            for k in parse_combo(g("combo")):
                self.hold_key(target, k, spoof)
        elif t == "key_up":
            for k in reversed(parse_combo(g("combo"))):
                self.release_key(target, k, spoof)
        elif t == "text":
            self.type_text(g("text"), self.scaled(g("char_delay_ms")), target, spoof)
        elif t == "wait":
            extra = self.rng.randint(0, g("random_ms")) if g("random_ms") else 0
            self.sched.sleep(self.scaled(g("ms") + extra))
        elif t == "launch":
            launch_program(g("path"), g("args"))
        elif t == "focus":
            if not b.focus_window(g("title")):
                raise BackendError(f'No window with "{g("title")}" in its title was found.')
        elif t in PROFILE_STEPS:
            self.run_profile(step)
        else:
            raise BackendError(f"Unknown step type: {t}")

    def run_profile(self, step: Step) -> None:
        """Run a saved Autoclicker / Key Repeater setup inside this macro, on this thread."""
        tool = PROFILE_STEPS[step.type]
        profile = self.profiles.get(step.get("profile"))
        if profile is None or profile.tool != tool:
            raise BackendError(f"Step {self.current_step + 1} runs a saved {TOOL_NAMES[tool]} setup that no "
                               "longer exists. Pick another one in the step.")
        cfg = profile.copy_config()
        if step.get("until") == "time":
            cfg.limit = RunLimit("duration", cfg.limit.count, max(0.1, self.scaled(step.get("ms")) / 1000))
        runner_type = ClickerRunner if tool == "clicker" else KeyRunner
        nested = runner_type(self.backend, cfg, failsafe=self.failsafe, rng=self.rng,
                             guard=self.guard_factory() if self.guard_factory else None)
        # Share the stop flag so stopping the macro stops the nested run at once.
        nested.stop_event = self.stop_event
        nested.sched = Scheduler(self.stop_event)
        nested.started_at = time.perf_counter()
        self.nested = nested
        try:
            nested.work()
        finally:
            nested.release_all()
            self.nested = None

    def type_text(self, text: str, char_delay_ms: float, target: WindowTarget | None, spoof: bool = False) -> None:
        if char_delay_ms <= 0:
            if target is not None:
                self.backend.bg_text(target, text, spoof)
            else:
                self.backend.type_text(text)
            return
        for ch in text:
            if self.stop_event.is_set():
                return
            if target is not None:
                self.backend.bg_text(target, ch, spoof)
            else:
                self.backend.type_text(ch)
            self.sched.sleep(char_delay_ms)

    def glide(self, x: int, y: int, duration_ms: float) -> None:
        if duration_ms <= 0:
            self.backend.move(x, y)
            return
        sx, sy = self.backend.cursor_pos()
        steps = max(2, int(duration_ms / 10))
        for i in range(1, steps + 1):
            if self.stop_event.is_set():
                return
            p = i / steps
            ease = p * p * (3 - 2 * p)
            self.backend.move(round(sx + (x - sx) * ease), round(sy + (y - sy) * ease))
            self.sched.sleep(duration_ms / steps)


def launch_program(path: str, args: list[str]) -> None:
    """Start a program without a shell. Documents open with their default app."""
    if not path:
        raise BackendError("The launch step has no program set.")
    path = os.path.expandvars(os.path.expanduser(path))
    if args and path.lower().endswith((".bat", ".cmd")):
        # cmd.exe re-parses batch arguments, so they cannot be passed safely.
        raise BackendError("Arguments cannot be passed to .bat or .cmd files.")
    try:
        if sys.platform == "win32" and not path.lower().endswith((".exe", ".com", ".bat", ".cmd")) \
                and os.path.exists(path):
            os.startfile(path)  # noqa: S606 - opens a document with its associated app
            return
        exe = path if os.path.exists(path) else shutil.which(path)
        if exe is None:
            raise BackendError(f"Program not found: {path}")
        if sys.platform != "win32" and not os.access(exe, os.X_OK):
            opener = shutil.which("xdg-open") or shutil.which("open")
            if opener is None:
                raise BackendError(f"Cannot open {path}: no xdg-open available.")
            subprocess.Popen([opener, exe], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            return
        kwargs = {"start_new_session": True} if sys.platform != "win32" else {}
        subprocess.Popen([exe, *args], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True, **kwargs)
    except OSError as exc:
        raise BackendError(f"Could not launch {path}: {exc}") from None
