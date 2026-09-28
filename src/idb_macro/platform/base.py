"""The interface every input backend implements."""

from __future__ import annotations

import contextlib
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass

from ..core.models import TargetPoint, WindowTarget


class BackendError(RuntimeError):
    """Input could not be delivered; the message is shown to the user."""


class TargetLost(BackendError):
    """The target window no longer exists and could not be found again."""


class TargetDenied(BackendError):
    """The OS refused input to the target (usually a higher-privilege window)."""


class Unsupported(BackendError):
    """This backend cannot do what was asked."""


@dataclass
class PickResult:
    window: WindowTarget
    point: TargetPoint


class Backend(ABC):
    name = "base"
    supports_background = False
    # Shown in the UI when the platform has known caveats (e.g. Wayland).
    notice = ""

    # ---- foreground input -------------------------------------------------

    @abstractmethod
    def cursor_pos(self) -> tuple[int, int]: ...

    @abstractmethod
    def move(self, x: int, y: int) -> None: ...

    @abstractmethod
    def mouse_down(self, button: str) -> None: ...

    @abstractmethod
    def mouse_up(self, button: str) -> None: ...

    @abstractmethod
    def scroll(self, amount: int, horizontal: bool = False) -> None: ...

    @abstractmethod
    def key_down(self, key: str) -> None: ...

    @abstractmethod
    def key_up(self, key: str) -> None: ...

    @abstractmethod
    def type_text(self, text: str) -> None: ...

    def click(self, button: str, count: int = 1) -> None:
        for _ in range(count):
            self.mouse_down(button)
            self.mouse_up(button)

    def combo_down(self, keys: tuple[str, ...]) -> None:
        for k in keys:
            self.key_down(k)

    def combo_up(self, keys: tuple[str, ...]) -> None:
        for k in reversed(keys):
            self.key_up(k)

    def tap_combo(self, keys: tuple[str, ...]) -> None:
        self.combo_down(keys)
        self.combo_up(keys)

    # ---- windows ------------------------------------------------------------

    def pick_at(self, x: int, y: int) -> PickResult:
        raise Unsupported("Picking windows is not supported on this system.")

    def list_windows(self) -> list[WindowTarget]:
        return []

    def window_alive(self, target: WindowTarget) -> bool:
        return False

    def is_minimized(self, target: WindowTarget) -> bool:
        return False

    def foreground_window(self) -> WindowTarget | None:
        """The active top-level window (handle, title, class, pid), if the system can tell."""
        return None

    def window_at(self, x: int, y: int) -> WindowTarget | None:
        """The top-level window under a screen point, if the system can tell."""
        return None

    def reacquire(self, target: WindowTarget) -> WindowTarget | None:
        return None

    def client_to_screen(self, target: WindowTarget, x: int, y: int) -> tuple[int, int]:
        raise Unsupported("Window coordinates are not supported on this system.")

    def screen_to_client(self, target: WindowTarget, x: int, y: int) -> tuple[int, int]:
        raise Unsupported("Window coordinates are not supported on this system.")

    def focus_window(self, title_contains: str) -> bool:
        return False

    def ensure_target(self, target: WindowTarget) -> WindowTarget:
        """Return a live target, refreshing its handle if the window was recreated."""
        if self.window_alive(target):
            return target
        found = self.reacquire(target)
        if found is None:
            raise TargetLost(f"The target window is gone: {target.describe()}")
        target.handle = found.handle
        target.pid = found.pid
        return target

    # ---- background input ---------------------------------------------------

    def bg_mouse(self, target: WindowTarget, point: TargetPoint, button: str,
                 action: str, count: int = 1, spoof_focus: bool = False) -> None:
        """``action`` is ``click``, ``down``, ``up`` or ``move``."""
        raise Unsupported("Background input is not supported on this system.")

    def bg_scroll(self, target: WindowTarget, point: TargetPoint, amount: int, horizontal: bool = False,
                  spoof_focus: bool = False) -> None:
        raise Unsupported("Background input is not supported on this system.")

    def bg_key(self, target: WindowTarget, key: str, down: bool,
               held: tuple[str, ...] = (), spoof_focus: bool = False) -> None:
        raise Unsupported("Background input is not supported on this system.")

    def bg_text(self, target: WindowTarget, text: str, spoof_focus: bool = False) -> None:
        raise Unsupported("Background input is not supported on this system.")

    def bg_tap_combo(self, target: WindowTarget, keys: tuple[str, ...], spoof_focus: bool = False) -> None:
        for i, k in enumerate(keys):
            self.bg_key(target, k, True, keys[:i], spoof_focus)
        for i in range(len(keys) - 1, -1, -1):
            self.bg_key(target, keys[i], False, keys[:i], spoof_focus)

    # ---- misc ---------------------------------------------------------------

    @contextlib.contextmanager
    def session(self) -> Iterator[None]:
        """Wraps a run; backends use it for timer resolution and cleanup."""
        yield

    def close(self) -> None:  # noqa: B027 - optional hook, most backends hold nothing
        return None
