"""Full-screen crosshair overlay for picking a point (and the window under it)."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..platform.base import Backend, BackendError, PickResult
from . import theme


class _Shade(QWidget):
    def __init__(self, session: PickSession, screen):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.session = session
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setScreen(screen)
        self.setGeometry(screen.geometry())

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(3, 6, 18, 90))
        local = self.mapFromGlobal(QCursor.pos())
        if not self.rect().contains(local):
            self._bubble(p, QPointF(self.width() / 2, self.height() / 2), centered=True)
            return
        pos = QPointF(local)
        p.setPen(QPen(theme.color(theme.PRIMARY, 150), 1))
        p.drawLine(QPointF(0, pos.y()), QPointF(self.width(), pos.y()))
        p.drawLine(QPointF(pos.x(), 0), QPointF(pos.x(), self.height()))
        p.setPen(QPen(theme.color(theme.PRIMARY_HOVER), 2))
        p.drawEllipse(pos, 14, 14)
        p.setBrush(theme.color(theme.PRIMARY_HOVER))
        p.drawEllipse(pos, 2.5, 2.5)
        self._bubble(p, pos)

    def _bubble(self, p: QPainter, pos: QPointF, centered: bool = False) -> None:
        x, y = self.session.backend_pos()
        lines = [self.session.prompt, f"{x}, {y}   ·   Esc to cancel"]
        p.setFont(theme.ui_font(13, QFont.Weight.DemiBold))
        fm = p.fontMetrics()
        w = max(fm.horizontalAdvance(line) for line in lines) + 28
        h = 58
        if centered:
            box = QRectF(pos.x() - w / 2, pos.y() - h / 2, w, h)
        else:
            box = QRectF(pos.x() + 22, pos.y() + 22, w, h)
            if box.right() > self.width() - 8:
                box.moveRight(pos.x() - 22)
            if box.bottom() > self.height() - 8:
                box.moveBottom(pos.y() - 22)
        p.setPen(QPen(theme.color(theme.BORDER_STRONG), 1))
        p.setBrush(theme.color(theme.SURFACE_STRONG, 240))
        p.drawRoundedRect(box, 10, 10)
        p.setPen(theme.color(theme.INK))
        p.drawText(box.adjusted(14, 8, -14, -30), Qt.AlignmentFlag.AlignLeft, lines[0])
        p.setFont(theme.ui_font(12))
        p.setPen(theme.color(theme.MUTED))
        p.drawText(box.adjusted(14, 30, -14, -8), Qt.AlignmentFlag.AlignLeft, lines[1])

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self.session.repaint_all()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            self.session.cancel()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        # Finish on release: finishing on press would let the release fall
        # through to the app underneath as a stray click.
        if event.button() == Qt.MouseButton.LeftButton:
            self.session.finish()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.session.cancel()


class PickSession:
    """One pick: shows the overlay, then reports a point or a window pick."""

    def __init__(self, backend: Backend, prompt: str, want_window: bool,
                 on_done: Callable[[PickResult | tuple[int, int] | None, str], None],
                 hide: QWidget | None = None):
        self.backend = backend
        self.prompt = prompt
        self.want_window = want_window
        self.on_done = on_done
        self.hide = hide
        self.shades: list[_Shade] = []
        self.timer = QTimer()
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.repaint_all)
        self.done = False

    def backend_pos(self) -> tuple[int, int]:
        try:
            return self.backend.cursor_pos()
        except Exception:
            pos = QCursor.pos()
            return pos.x(), pos.y()

    def start(self) -> None:
        if self.hide is not None:
            self.hide.hide()
        for screen in QGuiApplication.screens():
            shade = _Shade(self, screen)
            self.shades.append(shade)
            shade.show()
        if self.shades:
            self.shades[0].activateWindow()
            self.shades[0].grabKeyboard()
        self.timer.start()

    def repaint_all(self) -> None:
        for s in self.shades:
            s.update()

    def _close(self) -> None:
        self.timer.stop()
        for s in self.shades:
            s.releaseKeyboard()
            s.close()
        self.shades = []

    def finish(self) -> None:
        if self.done:
            return
        self.done = True
        x, y = self.backend_pos()
        self._close()
        # Let the overlay disappear before asking which window is underneath.
        QTimer.singleShot(150, lambda: self._report(x, y))

    def _report(self, x: int, y: int) -> None:
        result: PickResult | tuple[int, int] | None = (x, y)
        error = ""
        if self.want_window:
            try:
                result = self.backend.pick_at(x, y)
            except BackendError as exc:
                result, error = None, str(exc)
        self._restore()
        self.on_done(result, error)

    def cancel(self) -> None:
        if self.done:
            return
        self.done = True
        self._close()
        self._restore()
        self.on_done(None, "")

    def _restore(self) -> None:
        if self.hide is not None:
            self.hide.show()
            self.hide.raise_()
            self.hide.activateWindow()


_active: list[PickSession] = []


def pick(backend: Backend, prompt: str, want_window: bool,
         on_done: Callable[[PickResult | tuple[int, int] | None, str], None], hide: QWidget | None = None) -> None:
    def done(result, error):
        _active.clear()
        on_done(result, error)

    session = PickSession(backend, prompt, want_window, done, hide)
    _active.append(session)
    session.start()
