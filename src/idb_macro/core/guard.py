"""Smart-mode safety checks that stop foreground input from landing in the wrong place."""

from __future__ import annotations

import os

from ..platform.base import Backend

# Windows shell surfaces a stray click should never hit.
SHELL_CLASSES = frozenset({
    "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Progman", "WorkerW", "NotifyIconOverflowWindow",
    "TopLevelWindowForOverflowXamlIsland", "Windows.UI.Core.CoreWindow", "XamlExplorerHostIslandWindow",
})


def _short(title: str) -> str:
    title = title.strip() or "the window you started in"
    return title if len(title) <= 40 else title[:37] + "…"


class SmartGuard:
    """Decides, before every foreground action, whether it is safe to send.

    ``focus_lock``: input only goes to the window that was active when the run
    started (the first window other than I-DB Macro itself). Switching to
    another app pauses the run instead of clicking or typing into it.
    ``avoid_shell``: clicks over the taskbar, the desktop or I-DB Macro are
    skipped.
    """

    def __init__(self, backend: Backend, focus_lock: bool = True, avoid_shell: bool = True,
                 own_pid: int | None = None):
        self.backend = backend
        self.focus_lock = focus_lock
        self.avoid_shell = avoid_shell
        self.own_pid = os.getpid() if own_pid is None else own_pid
        self.locked = None

    def check(self, pointer: bool, point: tuple[int, int] | None = None) -> str:
        """Empty string if the action may go ahead, otherwise why it is held back."""
        if self.focus_lock:
            active = self.backend.foreground_window()
            if active is not None:
                if active.pid == self.own_pid:
                    return ("Waiting: switch to the window you want to use" if self.locked is None
                            else "Paused while I-DB Macro is the active window")
                if self.locked is None:
                    self.locked = active
                elif active.handle != self.locked.handle:
                    return f"Paused: {_short(self.locked.title)} is not the active window"
        if pointer and self.avoid_shell:
            x, y = point if point is not None else self.backend.cursor_pos()
            under = self.backend.window_at(x, y)
            if under is not None:
                if under.pid == self.own_pid:
                    return "Skipped: the cursor is over I-DB Macro"
                if under.window_class in SHELL_CLASSES:
                    return "Skipped: the cursor is over the taskbar or desktop"
        return ""
