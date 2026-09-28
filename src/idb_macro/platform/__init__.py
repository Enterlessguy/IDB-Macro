"""Pick the best input backend for the running system."""

from __future__ import annotations

import logging
import os
import sys

from .base import Backend

log = logging.getLogger(__name__)


def create_backend() -> Backend:
    if sys.platform == "win32":
        from .windows import WindowsBackend

        return WindowsBackend()
    if sys.platform.startswith("linux") and os.environ.get("DISPLAY"):
        try:
            from .x11 import X11Backend

            return X11Backend()
        except Exception as exc:
            log.warning("X11 backend unavailable, using the generic one: %s", exc)
    from .fallback import FallbackBackend

    return FallbackBackend()
