"""Main window: sidebar navigation, tool pages, tray icon."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QFont, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QStackedWidget,
    QStatusBar,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from ..core.keys import display_combo
from . import theme
from .controller import Controller
from .dumb import DumbView
from .pages.clicker import ClickerPage
from .pages.keys import KeysPage
from .pages.macros import MacrosPage
from .pages.settings import SettingsPage
from .pages.updates import UpdatesPage
from .widgets import IconButton, NavButton, Toggle, label

NAV = [("clicker", "click", "Autoclicker"), ("keys", "keys", "Key Repeater"), ("macro", "macro", "Macros")]


class MainWindow(QMainWindow):
    def __init__(self, controller: Controller):
        super().__init__()
        self.c = controller
        self.setWindowTitle("I-DB Macro")
        self.setWindowIcon(theme.app_icon())
        self.setMinimumSize(980, 640)
        self._tray_hint_shown = False
        self._quitting = False

        root = QWidget()
        root.setObjectName("Content")
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        self.pages = {
            "clicker": ClickerPage(controller),
            "keys": KeysPage(controller),
            "macro": MacrosPage(controller),
            "settings": SettingsPage(controller, self.set_always_on_top),
            "updates": UpdatesPage(controller),
        }
        for page in self.pages.values():
            self.stack.addWidget(page)
        lay.addWidget(self.stack, 1)
        # Full app and dumb mode are two views of the same window.
        self.views = QStackedWidget()
        self.views.addWidget(root)
        self.dumb = DumbView(controller, lambda: self.set_dumb(False))
        self.views.addWidget(self.dumb)
        self.setCentralWidget(self.views)
        self._full_geometry = None

        status = QStatusBar()
        status.setSizeGripEnabled(False)
        status.setStyleSheet(f"QStatusBar {{ background: {theme.SIDEBAR}; color: {theme.MUTED};"
                             f" border-top: 1px solid {theme.BORDER}; }}")
        self.setStatusBar(status)
        # Only take up space while there is something to say.
        status.messageChanged.connect(lambda text: status.setVisible(bool(text)))
        status.hide()

        self._build_tray()
        controller.state_changed.connect(self._on_state)
        controller.hotkeys_updated.connect(self._refresh_hotkey_hints)
        self._refresh_hotkey_hints()
        self.navigate("clicker")

        self.ticker = QTimer(self)
        self.ticker.timeout.connect(self._tick)
        self.ticker.start(100)
        if controller.settings.always_on_top:
            self.set_always_on_top(True)
        if controller.backend.notice:
            status.showMessage(controller.backend.notice, 15000)
        if controller.bad_hotkeys:
            status.showMessage("Some saved hotkeys were invalid and have been ignored.", 10000)
        controller.modes_changed.connect(self._sync_modes)
        self.pages["updates"].update_available.connect(self._update_available)
        if controller.settings.check_updates:
            QTimer.singleShot(4000, self.pages["updates"].check)
        if controller.settings.dumb_mode:
            # After the caller has placed the window, so the full size is remembered.
            QTimer.singleShot(0, lambda: self.set_dumb(True))


    def _build_sidebar(self) -> QWidget:
        side = QWidget()
        side.setObjectName("Sidebar")
        side.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        side.setFixedWidth(236)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(10, 20, 10, 16)
        lay.setSpacing(4)

        brand = QHBoxLayout()
        brand.setContentsMargins(10, 0, 0, 0)
        brand.setSpacing(10)
        cube = QLabel()
        cube.setPixmap(QPixmap(str(theme.ASSETS / "cube.png")).scaled(
            38, 38, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        names = QVBoxLayout()
        names.setSpacing(0)
        title = QLabel("I-DB Macro")
        title.setFont(theme.ui_font(17, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {theme.INK};")
        sub = QLabel("Intelligence Database")
        sub.setFont(theme.ui_font(11, QFont.Weight.DemiBold))
        sub.setStyleSheet(f"color: {theme.PRIMARY};")
        names.addWidget(title)
        names.addWidget(sub)
        brand.addWidget(cube)
        brand.addLayout(names, 1)
        lay.addLayout(brand)
        lay.addSpacing(26)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav: dict[str, NavButton] = {}
        lay.addWidget(self._section("Tools"))
        for key, icon, text in NAV:
            self._add_nav(lay, key, icon, text)
        lay.addSpacing(14)
        lay.addWidget(self._section("App"))
        self._add_nav(lay, "settings", "settings", "Settings")
        self._add_nav(lay, "updates", "update", "Updates")
        lay.addSpacing(14)
        lay.addWidget(self._section("Modes"))
        self.smart_toggle = Toggle("Smart mode", self.c.settings.smart_mode)
        self.smart_toggle.setToolTip("Ready-made setups for common uses, safety checks that keep clicks and keys "
                                     "in the window you started in, and tips about your settings.")
        self.smart_toggle.toggled.connect(self.c.set_smart_mode)
        smart_row = QHBoxLayout()
        smart_row.setContentsMargins(20, 6, 8, 6)
        smart_row.addWidget(self.smart_toggle)
        lay.addLayout(smart_row)
        self.dumb_btn = NavButton("click", "Dumb mode")
        self.dumb_btn.setCheckable(False)
        self.dumb_btn.setToolTip("Turn the app into one plain autoclicker. You can switch back any time.")
        self.dumb_btn.clicked.connect(lambda: self.set_dumb(True))
        lay.addWidget(self.dumb_btn)
        lay.addStretch(1)

        self.stop_all = IconButton("stop", "Stop everything", "danger")
        self.stop_all.setMinimumHeight(40)
        self.stop_all.clicked.connect(self.c.stop_all)
        self.stop_hint = label("", "faint")
        self.stop_hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self.stop_all)
        lay.addWidget(self.stop_hint)
        return side

    @staticmethod
    def _section(text: str) -> QLabel:
        w = label(text.upper(), "section")
        w.setContentsMargins(14, 0, 0, 6)
        return w

    def _add_nav(self, lay, key: str, icon: str, text: str) -> None:
        b = NavButton(icon, text)
        b.clicked.connect(lambda: self.navigate(key))
        self.nav_group.addButton(b)
        self.nav[key] = b
        lay.addWidget(b)

    def navigate(self, key: str) -> None:
        self.stack.setCurrentWidget(self.pages[key])
        self.nav[key].setChecked(True)

    def _build_tray(self) -> None:
        self.tray: QSystemTrayIcon | None = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        tray = QSystemTrayIcon(theme.app_icon(), self)
        tray.setToolTip("I-DB Macro")
        menu = QMenu()
        menu.addAction("Show I-DB Macro").triggered.connect(self.show_from_tray)
        menu.addSeparator()
        self.tray_actions: dict[str, QAction] = {}
        for key, _icon, text in NAV:
            action = menu.addAction(f"Start {text}")
            action.triggered.connect(lambda _=False, k=key: self.c.toggle(k))
            self.tray_actions[key] = action
        menu.addAction("Stop everything").triggered.connect(self.c.stop_all)
        menu.addSeparator()
        menu.addAction("Quit").triggered.connect(self.quit)
        tray.setContextMenu(menu)
        tray.activated.connect(lambda reason: reason == QSystemTrayIcon.ActivationReason.Trigger
                               and self.show_from_tray())
        tray.show()
        self._tray_menu = menu
        self.tray = tray


    def set_dumb(self, on: bool) -> None:
        in_dumb = self.views.currentWidget() is self.dumb
        if on != self.c.settings.dumb_mode:
            self.c.set_dumb_mode(on)
        if on and not in_dumb:
            self._full_geometry = self.geometry()
            self.views.setCurrentWidget(self.dumb)
            self.setMinimumSize(360, 480)
            self.resize(430, 560)
        elif not on and in_dumb:
            self.views.setCurrentIndex(0)
            self.setMinimumSize(980, 640)
            if self._full_geometry is not None:
                self.setGeometry(self._full_geometry)

    def _update_available(self, version: str) -> None:
        self.nav["updates"].hint = "NEW"
        self.nav["updates"].update()
        self.statusBar().showMessage(f"I-DB Macro {version} is available. Open Updates to install it.", 15000)

    def _sync_modes(self) -> None:
        self.smart_toggle.blockSignals(True)
        self.smart_toggle.setChecked(self.c.settings.smart_mode)
        self.smart_toggle.blockSignals(False)
        self.smart_toggle.update()

    def _on_state(self, tool: str, running: bool, message: str) -> None:
        page = self.pages[tool]
        page.on_state(running, message)
        if tool == "clicker":
            self.dumb.on_state(running, message)
        self.nav[tool].set_running(running)
        if self.tray is not None:
            text = dict((k, t) for k, _i, t in NAV)[tool]
            self.tray_actions[tool].setText(f"{'Stop' if running else 'Start'} {text}")
            active = [t for k, _i, t in NAV if self.c.is_running(k) or (k == tool and running)]
            self.tray.setToolTip("I-DB Macro" + (f" — running: {', '.join(active)}" if active else ""))
        if not running and message not in ("", "Stopped", "Finished"):
            self.statusBar().showMessage(message, 10000)

    def _refresh_hotkey_hints(self) -> None:
        hk = self.c.settings.hotkeys
        self.pages["clicker"].bar.set_hotkey(hk.get("clicker", ""))
        self.pages["keys"].bar.set_hotkey(hk.get("keys", ""))
        self.pages["macro"].bar.set_hotkey(hk.get("macro", ""))
        self.nav["clicker"].hint = display_combo(hk["clicker"]) if hk.get("clicker") else ""
        self.nav["keys"].hint = display_combo(hk["keys"]) if hk.get("keys") else ""
        self.nav["macro"].hint = display_combo(hk["macro"]) if hk.get("macro") else ""
        for b in self.nav.values():
            b.update()
        panic = hk.get("panic", "")
        self.stop_hint.setText(f"or press {display_combo(panic)} anywhere" if panic else "")

    def _tick(self) -> None:
        for key in ("clicker", "keys", "macro"):
            if self.c.is_running(key):
                self.pages[key].tick()
        if self.views.currentWidget() is self.dumb:
            self.dumb.tick()


    def set_always_on_top(self, on: bool) -> None:
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
        if visible:
            self.show()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        theme.apply_dark_title_bar(self)

    def show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._quitting and self.c.settings.close_to_tray and self.tray is not None:
            event.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self.tray.showMessage("I-DB Macro is still running",
                                      "Hotkeys keep working. Use the tray icon to open it or quit.",
                                      QSystemTrayIcon.MessageIcon.Information, 4000)
                self._tray_hint_shown = True
            return
        self._shutdown()
        event.accept()

    def quit(self) -> None:
        self._quitting = True
        self.close()

    def _shutdown(self) -> None:
        pages = self.pages["macro"]
        if pages.recorder is not None:
            pages.stop_record()
        self.c.shutdown()
        if self.tray is not None:
            self.tray.hide()
        from PySide6.QtWidgets import QApplication

        QApplication.quit()
