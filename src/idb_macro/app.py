"""Entry point: startup animation, then the main window."""

from __future__ import annotations

import argparse
import logging
import sys

from PySide6.QtCore import QLockFile, QRect, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox

from . import __version__
from .core.storage import Store
from .platform import create_backend


def _set_windows_app_id() -> None:
    """Group the taskbar button under our own icon instead of python.exe's."""
    if sys.platform != "win32":
        return
    import ctypes

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("IntelligenceDatabase.IDBMacro")
    except (AttributeError, OSError):
        pass


def _initial_geometry() -> QRect:
    screen = QGuiApplication.primaryScreen().availableGeometry()
    w = min(1200, int(screen.width() * 0.9))
    h = min(800, int(screen.height() * 0.9))
    return QRect(screen.x() + (screen.width() - w) // 2, screen.y() + (screen.height() - h) // 2, w, h)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="idb-macro", description="I-DB Macro")
    parser.add_argument("--no-splash", action="store_true", help="skip the startup animation")
    parser.add_argument("--version", action="version", version=f"I-DB Macro {__version__}")
    parser.add_argument("--debug", action="store_true", help="verbose logging to the console")
    args, qt_args = parser.parse_known_args(argv if argv is not None else sys.argv[1:])

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    _set_windows_app_id()
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName("I-DB Macro")
    app.setOrganizationName("Intelligence Database")
    app.setStyle("Fusion")

    from .ui import theme

    app.setWindowIcon(theme.app_icon())
    app.setFont(theme.ui_font(13))
    app.setStyleSheet(theme.stylesheet())

    store = Store()
    store.dir.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(store.dir / "instance.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, "I-DB Macro", "I-DB Macro is already running. Look for its icon in the "
                                                    "system tray.")
        return 0

    from .ui.controller import Controller
    from .ui.main_window import MainWindow
    from .ui.splash import SplashWindow

    controller = Controller(create_backend(), store)
    geometry = _initial_geometry()
    holder: dict[str, object] = {}

    def build() -> MainWindow:
        window = MainWindow(controller)
        window.setGeometry(geometry)
        window.show()
        controller.start()
        holder["window"] = window
        return window

    if controller.settings.show_splash and not args.no_splash:
        splash = SplashWindow(geometry)
        holder["splash"] = splash

        def reveal() -> None:
            build()
            splash.raise_()
            splash.reveal_after(900)

        splash.fully_visible.connect(reveal)
        splash.start()
    else:
        build()

    code = app.exec()
    lock.unlock()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
