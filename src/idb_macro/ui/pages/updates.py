"""Updates page: live release info from GitHub, one-click update for the Windows build."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QProgressBar, QTextBrowser

from ... import __version__
from ...core import updates
from ..widgets import Card, Message, Toggle, button, hbox, label
from .common import Page


def frozen_app_dir() -> Path | None:
    """Folder of the installed Windows build, or None when running from source."""
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        return Path(sys.executable).resolve().parent
    return None


def install_and_restart(app_dir: Path, new_app: Path) -> None:
    """Copy the new files over the app once it has exited, then start it again."""
    def q(p: Path) -> str:
        return str(p).replace("%", "%%")

    pid = os.getpid()
    script = new_app.parent / "apply-update.cmd"
    # /E copies and overwrites but never deletes, so nothing else in the folder is touched.
    script.write_text(
        "@echo off\r\n"
        ":wait\r\n"
        f'tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul && (timeout /t 1 /nobreak >nul & goto wait)\r\n'
        f'robocopy "{q(new_app)}" "{q(app_dir)}" /E /R:5 /W:1 /NFL /NDL /NJH /NJS >nul\r\n'
        f'start "" "{q(app_dir / "IDB-Macro.exe")}"\r\n',
        encoding="utf-8")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    # Full path, so a cmd.exe planted elsewhere on PATH can never be picked up.
    cmd = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "cmd.exe")
    subprocess.Popen([cmd, "/c", str(script)], creationflags=flags, close_fds=True)


class _Worker(QObject):
    checked = Signal(object, str)      # Release | None, error
    progress = Signal(int, int)
    downloaded = Signal(object, str)   # app folder Path | None, error


class UpdatesPage(Page):
    update_available = Signal(str)

    def __init__(self, controller):
        super().__init__("Updates", f"New versions are published at github.com/{updates.REPO}. "
                                    "Checking only contacts GitHub; nothing about you is sent.")
        self.c = controller
        self.release: updates.Release | None = None
        self.w = _Worker()
        self.w.checked.connect(self._checked)
        self.w.progress.connect(self._progress)
        self.w.downloaded.connect(self._downloaded)

        card = Card("I-DB Macro")
        self.current = label(f"You have version {__version__}.", "muted")
        self.status = Message("muted")
        self.check_btn = button("Check for updates", "primary")
        self.install_btn = button("Download and install")
        self.page_btn = button("Open release page", "ghost")
        self.install_btn.hide()
        self.page_btn.hide()
        card.add(self.current)
        card.add(hbox(self.check_btn, self.install_btn, self.page_btn, None))
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.hide()
        card.add(self.bar)
        card.add(self.status)
        self.auto = Toggle("Check for updates when I-DB Macro starts", controller.settings.check_updates)
        self.auto.toggled.connect(self._set_auto)
        card.add(self.auto)
        self.body.addWidget(card)

        notes = Card("What's new")
        self.notes = QTextBrowser()
        # Notes are display-only: links in them are never followed.
        self.notes.setOpenExternalLinks(False)
        self.notes.setOpenLinks(False)
        self.notes.setMinimumHeight(260)
        self.notes.setPlaceholderText("Check for updates to see the latest release notes.")
        notes.add(self.notes)
        self.body.addWidget(notes)
        self.body.addStretch(1)

        self.check_btn.clicked.connect(self.check)
        self.install_btn.clicked.connect(self.install)
        self.page_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(
            self.release.page_url if self.release else updates.RELEASES_PAGE)))

    def _set_auto(self, on: bool) -> None:
        self.c.settings.check_updates = on
        self.c.save_settings()

    def check(self) -> None:
        self.check_btn.setEnabled(False)
        self.status.setText("Checking GitHub…")

        def work():
            try:
                self.w.checked.emit(updates.fetch_latest(), "")
            except updates.UpdateError as exc:
                self.w.checked.emit(None, str(exc))

        threading.Thread(target=work, daemon=True).start()

    def _checked(self, rel, error: str) -> None:
        self.check_btn.setEnabled(True)
        if rel is None:
            self.status.setText(f"Couldn't check for updates: {error}")
            return
        self.release = rel
        self.notes.setMarkdown(f"## {rel.name}\n\n{rel.notes}")
        self.page_btn.show()
        if updates.is_newer(rel.version, __version__):
            can_install = frozen_app_dir() is not None and bool(rel.asset_url)
            self.install_btn.setVisible(can_install)
            self.status.setText(f"Version {rel.version} is available." + (
                "" if can_install else " Download it from the release page."))
            self.update_available.emit(rel.version)
        else:
            self.install_btn.hide()
            self.status.setText(f"You're up to date ({__version__} is the latest).")

    def install(self) -> None:
        rel, app_dir = self.release, frozen_app_dir()
        if rel is None or app_dir is None:
            return
        self.install_btn.setEnabled(False)
        self.check_btn.setEnabled(False)
        self.bar.show()
        self.status.setText("Downloading…")
        staging = Path(tempfile.mkdtemp(prefix="idb-macro-update-"))

        def work():
            try:
                zip_path = updates.download(rel, staging, lambda d, t: self.w.progress.emit(d, t))
                self.w.downloaded.emit(updates.safe_extract(zip_path, staging / "app"), "")
            except updates.UpdateError as exc:
                self.w.downloaded.emit(None, str(exc))

        threading.Thread(target=work, daemon=True).start()

    def _progress(self, done: int, total: int) -> None:
        self.bar.setRange(0, max(total, 1))
        self.bar.setValue(min(done, max(total, 1)))

    def _downloaded(self, new_app, error: str) -> None:
        self.bar.hide()
        self.check_btn.setEnabled(True)
        if new_app is None:
            self.install_btn.setEnabled(True)
            self.status.setText(f"Update failed: {error}")
            return
        self.status.setText("Verified. Restarting to finish the update…")
        install_and_restart(frozen_app_dir(), new_app)
        win = self.window()
        win._quitting = True
        win.close()
        QApplication.quit()

