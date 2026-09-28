"""Startup animation, ported from the Schedule I Control Center intro.

Phases: fade in (720 ms, ease-out cubic), hold while the main window is
built (at least 900 ms), fade out (680 ms, ease-in quadratic).
"""

from __future__ import annotations

import getpass

from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from . import theme

FADE_IN_MS = 720
FADE_OUT_MS = 680
MIN_HOLD_MS = 900


def _user_name() -> str:
    try:
        name = getpass.getuser().strip()
    except Exception:
        name = ""
    return name or "User"


class SplashWindow(QWidget):
    fully_visible = Signal()
    finished = Signal()

    def __init__(self, geometry, parent=None):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setGeometry(geometry)
        self.setWindowOpacity(0.0)
        self.greeting = f"Welcome, {_user_name()}"
        self.cube = QPixmap(str(theme.ASSETS / "cube.png"))
        self.welcome_family = theme.welcome_family()
        self._anim: QPropertyAnimation | None = None


    def start(self) -> None:
        self.show()
        self.raise_()
        self._animate(0.0, 1.0, FADE_IN_MS, QEasingCurve.Type.OutCubic, self.fully_visible.emit)

    def reveal_after(self, hold_ms: int) -> None:
        QTimer.singleShot(max(MIN_HOLD_MS, hold_ms), self._fade_out)

    def _fade_out(self) -> None:
        self.raise_()
        self._animate(self.windowOpacity(), 0.0, FADE_OUT_MS, QEasingCurve.Type.InQuad, self._done)

    def _done(self) -> None:
        self.finished.emit()
        self.close()

    def _animate(self, start: float, end: float, ms: int, curve, on_done) -> None:
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.setDuration(ms)
        anim.setEasingCurve(curve)
        anim.finished.connect(on_done)
        self._anim = anim
        anim.start()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Space, Qt.Key.Key_Return):
            self._fade_out()


    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
                         | QPainter.RenderHint.TextAntialiasing)
        rect = QRectF(self.rect())

        bg = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        bg.setColorAt(0, QColor(5, 13, 34))
        bg.setColorAt(1, QColor(2, 5, 16))
        p.fillRect(rect, bg)
        self._grid(p, rect)

        scale = max(0.72, min(1.18, min(rect.width() / 1450, rect.height() / 850)))
        cx = rect.center().x()
        cube_size = 190 * scale
        cube_cy = rect.top() + rect.height() * 0.39

        self._glow(p, cx, cube_cy + cube_size * 0.12, 420 * scale, 250 * scale)
        cube_rect = QRectF(cx - cube_size / 2, cube_cy - cube_size / 2, cube_size, cube_size)
        if not self.cube.isNull():
            p.drawPixmap(cube_rect, self.cube, QRectF(self.cube.rect()))

        title_top = cube_rect.bottom() + 26 * scale
        self._brand(p, "Intelligence Database", cx, title_top, 30 * scale)
        welcome_top = title_top + 72 * scale
        self._welcome(p, self.greeting, cx, welcome_top, 31 * scale)

        rule_y = welcome_top + 54 * scale
        p.setPen(QPen(QColor(40, 144, 255, 90), max(1.0, 1.4 * scale)))
        p.drawLine(QPointF(cx - 118 * scale, rule_y), QPointF(cx + 118 * scale, rule_y))

        product = ui_caps_font(11 * scale)
        p.setFont(product)
        p.setPen(QColor(theme.FAINT))
        p.drawText(QRectF(rect.left(), rule_y + 14 * scale, rect.width(), 24 * scale),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, "IDB-MACRO")
        p.end()

    @staticmethod
    def _grid(p: QPainter, rect: QRectF) -> None:
        p.setPen(QPen(QColor(86, 161, 255, 9), 1))
        x = rect.left()
        while x < rect.right():
            p.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            x += 52
        y = rect.top()
        while y < rect.bottom():
            p.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            y += 52
        # Vignette: darker at the top and bottom, clear through the middle.
        v = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        v.setColorAt(0.0, QColor(3, 7, 20, int(205 * 0.85)))
        v.setColorAt(0.48, QColor(2, 5, 16, int(205 * 0.08)))
        v.setColorAt(1.0, QColor(2, 5, 16, 205))
        p.fillRect(rect, v)

    @staticmethod
    def _glow(p: QPainter, cx: float, cy: float, w: float, h: float) -> None:
        p.save()
        p.translate(cx, cy)
        p.scale(1.0, h / w)
        g = QRadialGradient(QPointF(0, 0), w / 2)
        g.setColorAt(0, QColor(32, 134, 255, 105))
        g.setColorAt(1, QColor(4, 10, 28, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(QPointF(0, 0), w / 2, w / 2)
        p.restore()

    @staticmethod
    def _brand(p: QPainter, text: str, cx: float, top: float, px: float) -> None:
        font = theme.ui_font(max(1, round(px)), QFont.Weight.Bold)
        metrics = QFontMetricsF(font)
        width = metrics.horizontalAdvance(text)
        height = metrics.height()
        haze = QRectF(cx - width / 2 - 42, top - 18, width + 84, height + 36)
        p.save()
        p.translate(haze.center())
        p.scale(1.0, haze.height() / haze.width())
        g = QRadialGradient(QPointF(0, 0), haze.width() / 2)
        g.setColorAt(0, QColor(30, 103, 206, 25))
        g.setColorAt(1, QColor(30, 103, 206, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(QPointF(0, 0), haze.width() / 2, haze.width() / 2)
        p.restore()
        p.setFont(font)
        p.setPen(QColor(30, 103, 206))
        p.drawText(QRectF(cx - width / 2, top, width + 2, height), Qt.AlignmentFlag.AlignLeft, text)

    def _welcome(self, p: QPainter, text: str, cx: float, top: float, px: float) -> None:
        font = QFont(self.welcome_family)
        font.setPixelSize(max(1, round(px)))
        path = QPainterPath()
        path.addText(0, 0, font, text)
        bounds = path.boundingRect()
        path.translate(cx - bounds.left() - bounds.width() / 2, top - bounds.top())
        pen = QPen(QColor(69, 146, 255, 32), max(3.0, px * 0.18))
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.strokePath(path, pen)
        p.fillPath(path, QColor(218, 229, 249))


def ui_caps_font(px: float) -> QFont:
    f = theme.ui_font(max(1, round(px)), QFont.Weight.DemiBold)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, max(1.0, px * 0.35))
    return f
