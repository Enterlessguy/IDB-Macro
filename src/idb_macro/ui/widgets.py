"""Reusable widgets in the Intelligence Database style."""

from __future__ import annotations

import sys

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeyEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..core.keys import MODIFIERS, KeyComboError, display_combo, format_combo, normalize_key
from . import theme


def label(text: str = "", role: str | None = None, wrap: bool = False) -> QLabel:
    w = QLabel(text)
    if role:
        w.setProperty("role", role)
    w.setWordWrap(wrap)
    return w


class Message(QLabel):
    """A wrapped label that takes no space while it is empty."""

    def __init__(self, role: str = "faint"):
        super().__init__("")
        self.setProperty("role", role)
        self.setWordWrap(True)
        # Messages can quote window titles and file contents.
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.hide()

    def setText(self, text: str) -> None:  # noqa: N802 - Qt naming
        super().setText(text)
        self.setVisible(bool(text))


def button(text: str, variant: str | None = None, tip: str | None = None) -> QPushButton:
    b = QPushButton(text)
    if variant:
        b.setProperty("variant", variant)
    if tip:
        b.setToolTip(tip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def restyle(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def hbox(*items, spacing: int = 8, margins=(0, 0, 0, 0), stretch_last: bool = False) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for item in items:
        if item is None:
            lay.addStretch(1)
        elif isinstance(item, int):
            lay.addSpacing(item)
        elif isinstance(item, QWidget):
            lay.addWidget(item)
        else:
            lay.addLayout(item)
    if stretch_last:
        lay.addStretch(1)
    return lay


def vbox(*items, spacing: int = 8, margins=(0, 0, 0, 0)) -> QVBoxLayout:
    lay = QVBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for item in items:
        if item is None:
            lay.addStretch(1)
        elif isinstance(item, int):
            lay.addSpacing(item)
        elif isinstance(item, QWidget):
            lay.addWidget(item)
        else:
            lay.addLayout(item)
    return lay


class Card(QFrame):
    """Rounded panel. Content stays at the top when the card is stretched to its row."""

    def __init__(self, title: str = "", subtitle: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(22, 18, 22, 20)
        self.body.setSpacing(14)
        if title or subtitle:
            head = QVBoxLayout()
            head.setSpacing(3)
            if title:
                t = QLabel(title)
                t.setObjectName("CardTitle")
                head.addWidget(t)
            if subtitle:
                head.addWidget(label(subtitle, "faint", wrap=True))
            self.body.addLayout(head)
        self.body.addStretch(1)

    def add(self, item) -> None:
        at = self.body.count() - 1
        if isinstance(item, QWidget):
            self.body.insertWidget(at, item)
        else:
            self.body.insertLayout(at, item)


CAPTION_WIDTH = 150


class FieldRow(QWidget):
    """Caption in a fixed column, control left-aligned beside it, optional hint below the control.

    Using the same caption width everywhere lines controls up across rows and cards.
    """

    def __init__(self, caption: str, control, hint: str = "", caption_width: int = CAPTION_WIDTH):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)
        self.caption = label(caption, "muted")
        self.caption.setFixedWidth(caption_width)
        self.caption.setWordWrap(True)
        right = QVBoxLayout()
        right.setSpacing(5)
        if isinstance(control, QWidget):
            right.addWidget(control, 0, Qt.AlignmentFlag.AlignLeft)
            height = max(34, control.sizeHint().height())
        else:
            right.addLayout(control)
            height = 36
        self.caption.setMinimumHeight(height)
        self.caption.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.hint = Message("faint")
        self.hint.setText(hint)
        right.addWidget(self.hint)
        lay.addWidget(self.caption, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(right, 1)


class KeyChips(QWidget):
    """Removable key-combo chips that wrap onto new lines."""

    removed = Signal(int)

    def __init__(self, empty_text: str = "No keys yet"):
        super().__init__()
        self.empty_text = empty_text
        self.flow = FlowLayout(self, spacing=8)
        self.set_items([])

    def set_items(self, labels: list[str]) -> None:
        while self.flow.count():
            item = self.flow.takeAt(0)
            old = item.widget()
            if old is not None:
                # Detach now: a widget waiting for deleteLater still covers
                # (and swallows clicks on) the new chips.
                old.hide()
                old.setParent(None)
                old.deleteLater()
        if not labels:
            self.flow.addWidget(label(self.empty_text, "faint"))
        for i, text in enumerate(labels):
            chip = QPushButton(f"{text}   ✕")
            chip.setProperty("chip", True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setToolTip("Remove")
            chip.clicked.connect(lambda _=False, i=i: self.removed.emit(i))
            self.flow.addWidget(chip)
        self.updateGeometry()


class FlowLayout(QLayout):
    """Lays widgets out left to right, wrapping to a new line when full."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 8):
        super().__init__(parent)
        self._items: list = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _arrange(self, rect: QRect, apply: bool) -> int:
        x, y, line = rect.x(), rect.y(), 0
        gap = self.spacing()
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > rect.right() + 1 and line > 0:
                x, y, line = rect.x(), y + line + gap, 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + gap
            line = max(line, hint.height())
        return y + line - rect.y()


class Segmented(QFrame):
    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]], value: str | None = None):
        super().__init__()
        self.setObjectName("Segmented")
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        for key, text in options:
            b = QPushButton(text)
            b.setProperty("seg", True)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            self.group.addButton(b)
            self.buttons[key] = b
            lay.addWidget(b)
            b.toggled.connect(lambda on, k=key: on and self.changed.emit(k))
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.setValue(value or options[0][0])

    def value(self) -> str:
        for key, b in self.buttons.items():
            if b.isChecked():
                return key
        return next(iter(self.buttons))

    def setValue(self, key: str) -> None:  # noqa: N802 - Qt naming
        if key in self.buttons:
            self.buttons[key].setChecked(True)

    def setOptionEnabled(self, key: str, enabled: bool, tip: str = "") -> None:  # noqa: N802
        if key in self.buttons:
            self.buttons[key].setEnabled(enabled)
            self.buttons[key].setToolTip(tip)


class Toggle(QCheckBox):
    """A pill switch."""

    def __init__(self, text: str = "", checked: bool = False):
        super().__init__(text)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:  # noqa: N802
        base = super().sizeHint()
        text_w = self.fontMetrics().horizontalAdvance(self.text()) + 12 if self.text() else 0
        return QSize(44 + text_w, max(24, base.height()))

    def hitButton(self, pos) -> bool:  # noqa: N802
        return self.rect().contains(pos)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = 22
        track = QRectF(1, (self.height() - h) / 2, 40, h)
        on = self.isChecked()
        enabled = self.isEnabled()
        p.setPen(QPen(QColor(theme.PRIMARY_HOVER if on else theme.BORDER_STRONG), 1))
        p.setBrush(QColor(theme.PRIMARY_STRONG if on else theme.INPUT))
        if not enabled:
            p.setOpacity(0.45)
        p.drawRoundedRect(track, h / 2, h / 2)
        knob = 16
        x = track.right() - knob - 3 if on else track.left() + 3
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.INK if on else theme.MUTED))
        p.drawEllipse(QRectF(x, track.top() + 3, knob, knob))
        if self.text():
            p.setPen(QColor(theme.INK if enabled else theme.FAINT))
            p.setFont(self.font())
            p.drawText(QRectF(track.right() + 10, 0, self.width() - track.right() - 10, self.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())


class StatTile(QFrame):
    def __init__(self, caption: str, value: str = "0"):
        super().__init__()
        self.setObjectName("Inset")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)
        lay.addWidget(label(caption.upper(), "section"))
        self.value = QLabel(value)
        self.value.setFont(theme.ui_font(22, QFont.Weight.DemiBold))
        lay.addWidget(self.value)

    def set(self, text: str) -> None:
        self.value.setText(text)

    def set_active(self, active: bool) -> None:
        self.value.setStyleSheet(f"color: {theme.PRIMARY_HOVER};" if active else "")


class StatusDot(QWidget):
    def __init__(self, size: int = 9):
        super().__init__()
        self.setFixedSize(size + 6, size + 6)
        self.state = "idle"

    def set_state(self, state: str) -> None:
        self.state = state
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = {"idle": theme.FAINT, "running": theme.SUCCESS, "error": theme.DANGER, "armed": theme.WARNING}
        c = QColor(colors.get(self.state, theme.FAINT))
        r = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        if self.state == "running":
            glow = QColor(c)
            glow.setAlpha(70)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.drawEllipse(QRectF(self.rect()))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawEllipse(r)


def spin(lo: int, hi: int, value: int, suffix: str = "", width: int = 96) -> QSpinBox:
    s = QSpinBox()
    s.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
    s.setRange(lo, hi)
    s.setValue(value)
    if suffix:
        s.setSuffix(suffix)
    s.setFixedWidth(width)
    s.setAlignment(Qt.AlignmentFlag.AlignRight)
    return s


def dspin(lo: float, hi: float, value: float, decimals: int = 2, suffix: str = "", width: int = 110) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setValue(value)
    if suffix:
        s.setSuffix(suffix)
    s.setFixedWidth(width)
    s.setAlignment(Qt.AlignmentFlag.AlignRight)
    return s


# ------------------------------------------------------------------ hotkeys

_QT_KEYS = {
    Qt.Key.Key_Return: "enter", Qt.Key.Key_Enter: "enter", Qt.Key.Key_Escape: "esc",
    Qt.Key.Key_Space: "space", Qt.Key.Key_Tab: "tab", Qt.Key.Key_Backtab: "tab",
    Qt.Key.Key_Backspace: "backspace", Qt.Key.Key_Delete: "delete", Qt.Key.Key_Insert: "insert",
    Qt.Key.Key_Home: "home", Qt.Key.Key_End: "end", Qt.Key.Key_PageUp: "pageup",
    Qt.Key.Key_PageDown: "pagedown", Qt.Key.Key_Up: "up", Qt.Key.Key_Down: "down",
    Qt.Key.Key_Left: "left", Qt.Key.Key_Right: "right", Qt.Key.Key_CapsLock: "capslock",
    Qt.Key.Key_NumLock: "numlock", Qt.Key.Key_ScrollLock: "scrolllock", Qt.Key.Key_Print: "printscreen",
    Qt.Key.Key_Pause: "pause", Qt.Key.Key_Menu: "menu", Qt.Key.Key_Control: "ctrl",
    Qt.Key.Key_Shift: "shift", Qt.Key.Key_Alt: "alt", Qt.Key.Key_Meta: "win", Qt.Key.Key_Super_L: "win",
    Qt.Key.Key_Super_R: "win", Qt.Key.Key_VolumeUp: "volumeup", Qt.Key.Key_VolumeDown: "volumedown",
    Qt.Key.Key_VolumeMute: "volumemute", Qt.Key.Key_MediaTogglePlayPause: "playpause",
    Qt.Key.Key_MediaPlay: "playpause", Qt.Key.Key_MediaNext: "nexttrack", Qt.Key.Key_MediaPrevious: "prevtrack",
    Qt.Key.Key_MediaStop: "stopmedia",
}
if sys.platform == "darwin":
    _QT_KEYS[Qt.Key.Key_Control] = "win"
    _QT_KEYS[Qt.Key.Key_Meta] = "ctrl"


def qt_event_key(event: QKeyEvent) -> str | None:
    """Canonical key name for a Qt key event (layout independent where possible)."""
    native = event.nativeVirtualKey()
    if native:
        from ..input_names import _VK_NAMES, _x_keysym_names

        table = _VK_NAMES if sys.platform == "win32" else _x_keysym_names()
        if native in table:
            return table[native]
    key = event.key()
    if key in _QT_KEYS:
        return _QT_KEYS[key]
    if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F24:
        return f"f{key - Qt.Key.Key_F1 + 1}"
    keypad = bool(event.modifiers() & Qt.KeyboardModifier.KeypadModifier)
    if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        return f"num{key - Qt.Key.Key_0}" if keypad else chr(key)
    if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
        return chr(key).lower()
    text = event.text()
    if text:
        from ..core.keys import char_to_combo

        combo = char_to_combo(text)
        if combo:
            return combo[-1]
    return None


class HotkeyEdit(QPushButton):
    """Click, then press a key combination. Esc cancels, Backspace clears."""

    changed = Signal(str)

    def __init__(self, combo: str = "", allow_empty: bool = True, placeholder: str = "Not set"):
        super().__init__()
        self.combo = combo
        self.allow_empty = allow_empty
        self.placeholder = placeholder
        self.capturing = False
        self._held: list[str] = []
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(150)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.clicked.connect(self._begin)
        self._render()

    def value(self) -> str:
        return self.combo

    def setValue(self, combo: str) -> None:  # noqa: N802
        self.combo = combo
        self._render()

    def _render(self) -> None:
        if self.capturing:
            held = " + ".join(display_combo((k,)) for k in self._held)
            self.setText(f"{held} + …" if held else "Press keys…")
        else:
            self.setText(display_combo(self.combo) if self.combo else self.placeholder)
        self.setChecked(self.capturing)

    def _begin(self) -> None:
        self.capturing = True
        self._held = []
        self.grabKeyboard()
        self._render()

    def _end(self, combo: str | None) -> None:
        self.releaseKeyboard()
        self.capturing = False
        if combo is not None and combo != self.combo:
            self.combo = combo
            self.changed.emit(combo)
        self._render()

    def focusOutEvent(self, event) -> None:  # noqa: N802
        if self.capturing:
            self._end(None)
        super().focusOutEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if not self.capturing:
            super().keyPressEvent(event)
            return
        name = qt_event_key(event)
        if name == "esc" and not self._held:
            self._end(None)
            return
        if name == "backspace" and not self._held and self.allow_empty:
            self._end("")
            return
        if name is None or event.isAutoRepeat():
            return
        if name in MODIFIERS:
            if name not in self._held:
                self._held.append(name)
            self._render()
            return
        try:
            normalize_key(name)
        except KeyComboError:
            return
        mods = [m for m in MODIFIERS if m in self._held]
        self._end(format_combo((*mods, name)))

    def keyReleaseEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if not self.capturing:
            super().keyReleaseEvent(event)
            return
        name = qt_event_key(event)
        if name in MODIFIERS and name in self._held and not event.isAutoRepeat():
            # Releasing a lone modifier binds the modifier itself.
            mods = [m for m in MODIFIERS if m in self._held]
            self._end(format_combo(tuple(mods)))


# ------------------------------------------------------------------- icons

def draw_icon(p: QPainter, name: str, rect: QRectF, color: QColor) -> None:
    """Small line icons, drawn so the app needs no icon files."""
    p.save()
    pen = QPen(color, 1.7)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    s = min(rect.width(), rect.height())
    p.translate(rect.center().x() - s / 2, rect.center().y() - s / 2)
    p.scale(s / 20, s / 20)
    if name == "click":
        path = QPainterPath(QPointF(6, 4))
        for x, y in ((6, 16), (9, 13), (11.5, 18), (13.5, 17), (11, 12.2), (15, 12.2)):
            path.lineTo(x, y)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(3, 2.5), QPointF(4.2, 3.7))
        p.drawLine(QPointF(9.5, 1.5), QPointF(9.5, 2.8))
        p.drawLine(QPointF(1.5, 8), QPointF(2.8, 8))
    elif name == "keys":
        p.drawRoundedRect(QRectF(2, 5, 16, 11), 2.5, 2.5)
        for x in (5, 8, 11, 14):
            p.drawPoint(QPointF(x + 0.5, 8.5))
        p.drawLine(QPointF(6.5, 12.5), QPointF(13.5, 12.5))
    elif name == "macro":
        p.drawRoundedRect(QRectF(2.5, 3, 15, 14), 3, 3)
        p.drawLine(QPointF(6, 7.5), QPointF(14, 7.5))
        p.drawLine(QPointF(6, 10.5), QPointF(12, 10.5))
        p.drawLine(QPointF(6, 13.5), QPointF(10, 13.5))
    elif name == "settings":
        p.drawEllipse(QPointF(10, 10), 2.6, 2.6)
        p.drawEllipse(QPointF(10, 10), 6.5, 6.5)
        for i in range(8):
            p.save()
            p.translate(10, 10)
            p.rotate(i * 45)
            p.drawLine(QPointF(0, -6.5), QPointF(0, -8.6))
            p.restore()
    elif name == "bulb":
        p.drawEllipse(QPointF(10, 8), 5.5, 5.5)
        p.drawLine(QPointF(7.8, 13), QPointF(7.8, 15.5))
        p.drawLine(QPointF(12.2, 13), QPointF(12.2, 15.5))
        p.drawLine(QPointF(7.8, 15.5), QPointF(12.2, 15.5))
        p.drawLine(QPointF(8.6, 17.8), QPointF(11.4, 17.8))
    elif name == "update":
        p.drawArc(QRectF(3.5, 3.5, 13, 13), 60 * 16, 280 * 16)
        p.drawLine(QPointF(13.5, 2.5), QPointF(13.8, 6.4))
        p.drawLine(QPointF(13.8, 6.4), QPointF(9.9, 6.6))
    elif name == "stop":
        p.setBrush(color)
        p.drawRoundedRect(QRectF(5, 5, 10, 10), 2, 2)
    elif name == "play":
        p.setBrush(color)
        path = QPainterPath(QPointF(6, 4))
        path.lineTo(16, 10)
        path.lineTo(6, 16)
        path.closeSubpath()
        p.drawPath(path)
    elif name == "record":
        p.setBrush(color)
        p.drawEllipse(QPointF(10, 10), 5, 5)
    elif name == "target":
        p.drawEllipse(QPointF(10, 10), 6.5, 6.5)
        p.drawEllipse(QPointF(10, 10), 2, 2)
        for a, b in (((10, 1), (10, 4.5)), ((10, 15.5), (10, 19)), ((1, 10), (4.5, 10)), ((15.5, 10), (19, 10))):
            p.drawLine(QPointF(*a), QPointF(*b))
    p.restore()


class IconButton(QPushButton):
    def __init__(self, icon: str, text: str = "", variant: str | None = None, tip: str | None = None):
        super().__init__(("      " + text) if text else "")
        self.icon_name = icon
        if variant:
            self.setProperty("variant", variant)
        if tip:
            self.setToolTip(tip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if not text:
            self.setFixedSize(36, 34)

    def set_icon(self, name: str) -> None:
        self.icon_name = name
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QColor(theme.INK if self.isEnabled() else theme.FAINT)
        if self.text():
            fm = self.fontMetrics()
            text_w = fm.horizontalAdvance(self.text().strip())
            x = (self.width() - text_w - 22) / 2
            rect = QRectF(max(8, x), (self.height() - 16) / 2, 16, 16)
        else:
            rect = QRectF((self.width() - 16) / 2, (self.height() - 16) / 2, 16, 16)
        draw_icon(p, self.icon_name, rect, c)


class NavButton(QAbstractButton):
    def __init__(self, icon: str, text: str, hint: str = ""):
        super().__init__()
        self.icon_name = icon
        self.setText(text)
        self.hint = hint
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(44)
        self.running = False
        self._hover = False

    def set_running(self, running: bool) -> None:
        self.running = running
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(200, 44)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(8, 2, -8, -2)
        active = self.isChecked()
        if active or self._hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.PRIMARY_SOFT if active else theme.SURFACE_STRONG))
            p.drawRoundedRect(r, 9, 9)
        if active:
            p.setBrush(QColor(theme.PRIMARY))
            p.drawRoundedRect(QRectF(r.left(), r.top() + 10, 3, r.height() - 20), 1.5, 1.5)
        ink = QColor(theme.INK if active else theme.MUTED)
        draw_icon(p, self.icon_name, QRectF(r.left() + 14, r.center().y() - 9, 18, 18),
                  QColor(theme.PRIMARY_HOVER) if active else ink)
        p.setPen(ink)
        p.setFont(theme.ui_font(13, QFont.Weight.DemiBold))
        p.drawText(QRectF(r.left() + 44, r.top(), r.width() - 90, r.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())
        if self.running:
            p.setPen(Qt.PenStyle.NoPen)
            glow = QColor(theme.SUCCESS)
            glow.setAlpha(70)
            p.setBrush(glow)
            p.drawEllipse(QPointF(r.right() - 16, r.center().y()), 7, 7)
            p.setBrush(QColor(theme.SUCCESS))
            p.drawEllipse(QPointF(r.right() - 16, r.center().y()), 4, 4)
        elif self.hint:
            p.setPen(QColor(theme.FAINT))
            p.setFont(theme.ui_font(11, QFont.Weight.DemiBold))
            p.drawText(QRectF(r.right() - 48, r.top(), 40, r.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, self.hint)
