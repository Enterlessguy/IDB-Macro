"""Light-bulb explainers: a live animation of an example, with a simple or a technical explanation."""

from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QDialog, QVBoxLayout, QWidget

from . import theme
from .widgets import IconButton, Segmented, button, hbox, label

C = theme.color
TEXT = {
    "background": (
        "Clicking a window in the background",
        "You keep working in one window while I-DB Macro clicks a game or app behind it. Your mouse "
        "doesn't move and nothing pops up. The window can even be minimized, as long as the app "
        "accepts it (Discord and browsers don't while minimized). Use the test click to check.",
        "Each click is sent as window messages (WM_MOUSEMOVE, WM_LBUTTONDOWN/UP) straight to the "
        "picked child control with SendMessageTimeout. The point is stored in that control's client "
        "coordinates, so it survives moves and minimizing. While each message is delivered, the "
        "worker thread attaches to the target's input queue (AttachThreadInput) and marks the "
        "button as held, because many toolkits check GetKeyState. The real cursor and focus are "
        "never touched. On Linux the equivalent is XSendEvent.",
    ),
    "keys": (
        "Why key presses need a length",
        "Games look at the keyboard about 60 times a second. A press that's too short can happen "
        "between two looks and gets missed, which is why a jump sometimes didn't happen. I-DB Macro "
        "holds each press for a short time (40 ms by default), so the game always sees it. Hotkeys "
        "like F6 work from any app.",
        "Games commonly poll key state once per frame (GetAsyncKeyState / raw input snapshots, "
        "≈16.7 ms at 60 FPS). A down/up pair sent back to back via SendInput has ~0 ms duration and "
        "only registers if a poll lands inside it. The Key Repeater holds the key for the press "
        "length (≥ one frame) between the scan-code key-down and key-up. Global hotkeys use a "
        "low-level keyboard hook that ignores injected events (LLKHF_INJECTED), so the repeater can "
        "never trigger itself.",
    ),
    "macro": (
        "How a macro plays",
        "A macro is a list of steps played from top to bottom: switch to a window, click, wait, press "
        "keys, or run a saved Autoclicker or Key Repeater setup for a while. Then it repeats as "
        "many times as you like. F12 stops everything at any moment.",
        "MacroRunner executes steps sequentially on a worker thread against an absolute-deadline "
        "scheduler (no drift). Waits are divided by the speed factor. A 'Run saved setup' step "
        "starts a nested ClickerRunner / KeyRunner on the same thread, sharing the macro's stop "
        "event, so stopping is immediate. Any key or button a step leaves held is released at the "
        "end of each loop and when the run ends. Recording converts low-level hook events into "
        "steps, keeping real waits and press lengths.",
    ),
    "smart": (
        "Smart mode's safety checks",
        "Smart mode remembers the window you started in. If you switch to another app, clicks and "
        "key presses pause, so nothing lands in your chat or browser, and held keys are let go. "
        "Switch back and it carries on. It also never clicks the taskbar or desktop.",
        "Before each foreground action, SmartGuard compares GetForegroundWindow() with the window "
        "locked at the first action (skipping I-DB Macro's own process). On a mismatch the action "
        "is skipped and the run reports why; Hold-down mode releases its keys and presses them "
        "again on return. For pointer actions, WindowFromPoint → GetAncestor(GA_ROOT) is checked "
        "against shell window classes (Shell_TrayWnd, Progman, WorkerW, …) and I-DB Macro's own "
        "process ID.",
    ),
}


def _ease(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def _window(p: QPainter, r: QRectF, title: str, accent: QColor, active: bool = True) -> None:
    shadow = QColor(0, 0, 0, 110)
    p.setPen(Qt.PenStyle.NoPen)
    for i, a in enumerate((60, 35, 18)):
        shadow.setAlpha(a)
        p.setBrush(shadow)
        p.drawRoundedRect(r.adjusted(-i * 2, i * 3, i * 2, i * 4 + 4), 12, 12)
    p.setPen(QPen(accent if active else C(theme.BORDER_STRONG), 1.6 if active else 1))
    p.setBrush(C(theme.SURFACE_STRONG if active else theme.SURFACE))
    p.drawRoundedRect(r, 11, 11)
    bar = QRectF(r.left() + 1, r.top() + 1, r.width() - 2, 30)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(C(theme.INPUT))
    p.drawRoundedRect(bar, 10, 10)
    p.drawRect(QRectF(bar.left(), bar.bottom() - 8, bar.width(), 8))
    for i, col in enumerate(("#FF6577", "#F5B942", "#49D18B")):
        p.setBrush(C(col, 230 if active else 110))
        p.drawEllipse(QPointF(r.left() + 16 + i * 14, r.top() + 16), 4, 4)
    p.setPen(C(theme.INK if active else theme.MUTED))
    p.setFont(theme.ui_font(12, QFont.Weight.DemiBold))
    p.drawText(QRectF(r.left() + 62, r.top() + 1, r.width() - 74, 30), Qt.AlignmentFlag.AlignVCenter, title)


def _backdrop(p: QPainter, r: QRectF, focus: QPointF) -> None:
    glow = QRadialGradient(focus, r.width() * 0.55)
    glow.setColorAt(0, QColor(32, 134, 255, 40))
    glow.setColorAt(1, QColor(4, 10, 28, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(glow)
    p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 14, 14)
    p.setPen(QPen(QColor(86, 161, 255, 12), 1))
    x = r.left() + 26
    while x < r.right():
        p.drawLine(QPointF(x, r.top() + 2), QPointF(x, r.bottom() - 2))
        x += 26


_cube: QPixmap | None = None


def _logo(p: QPainter, c: QPointF, size: float) -> None:
    global _cube
    if _cube is None:
        _cube = QPixmap(str(theme.ASSETS / "cube.png"))
    p.drawPixmap(QRectF(c.x() - size / 2, c.y() - size / 2, size, size), _cube, QRectF(_cube.rect()))


def _cursor(p: QPainter, x: float, y: float) -> None:
    pts = [QPointF(x, y), QPointF(x, y + 18), QPointF(x + 5, y + 14), QPointF(x + 9, y + 21),
           QPointF(x + 12, y + 19), QPointF(x + 8, y + 12), QPointF(x + 14, y + 12)]
    p.setPen(QPen(C(theme.BG_DEEP), 1.2))
    p.setBrush(C(theme.INK))
    p.drawPolygon(pts)


def _ripple(p: QPainter, c: QPointF, phase: float, color: QColor) -> None:
    if 0 <= phase <= 1:
        col = QColor(color)
        col.setAlphaF(1 - phase)
        p.setPen(QPen(col, 2.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(c, 6 + 26 * phase, 6 + 26 * phase)


def _badge(p: QPainter, c: QPointF, text: str, color: QColor) -> None:
    p.setFont(theme.ui_font(12, QFont.Weight.DemiBold))
    w = p.fontMetrics().horizontalAdvance(text) + 22
    r = QRectF(c.x() - w / 2, c.y() - 14, w, 28)
    fill = QColor(color)
    fill.setAlpha(45)
    p.setPen(QPen(color, 1.2))
    p.setBrush(fill)
    p.drawRoundedRect(r, 14, 14)
    p.setPen(C(theme.INK))
    p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)


class Stage(QWidget):
    """Paints one looping scene; ``t`` is seconds since the dialog opened."""

    def __init__(self, scene: str):
        super().__init__()
        self.scene = scene
        self.start = time.monotonic()
        self.setMinimumSize(640, 300)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self.timer.start(16)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        p.setPen(QPen(C(theme.BORDER), 1))
        p.setBrush(C(theme.BG_DEEP))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 14, 14)
        getattr(self, f"_{self.scene}")(p, r, time.monotonic() - self.start)
        p.end()

    # ---- scenes -------------------------------------------------------------

    def _background(self, p: QPainter, r: QRectF, t: float) -> None:
        game = QRectF(r.left() + r.width() * 0.44, r.top() + 30, r.width() * 0.50, r.height() * 0.66)
        work = QRectF(r.left() + 26, r.top() + 70, r.width() * 0.47, r.height() * 0.66)
        _backdrop(p, r, game.center())
        _window(p, game, "Game  ·  in the background", C(theme.SUCCESS), active=False)
        spot = QPointF(game.right() - game.width() * 0.24, game.top() + game.height() * 0.45)
        pulse = 0.5 + 0.5 * math.sin(t * 3)
        p.setPen(QPen(C(theme.SUCCESS, int(90 + 80 * pulse)), 1.6, Qt.PenStyle.DashLine))
        p.setBrush(C(theme.SUCCESS, 18))
        p.drawEllipse(spot, 17, 17)
        p.setPen(QPen(C(theme.SUCCESS, 200), 1.4))
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            p.drawLine(QPointF(spot.x() + dx * 8, spot.y() + dy * 8), QPointF(spot.x() + dx * 13, spot.y() + dy * 13))

        src = QPointF(r.right() - 44, r.bottom() - 40)
        path = QPainterPath(src)
        ctrl = QPointF((src.x() + spot.x()) / 2 + 40, min(src.y(), spot.y()) + 10)
        path.quadTo(ctrl, spot)
        p.setPen(QPen(C(theme.PRIMARY, 70), 1.5, Qt.PenStyle.DotLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        period = 1.2
        n, phase = int(t / period), (t % period) / period
        if phase < 0.4:
            k = _ease(phase / 0.4)
            for trail in range(4):
                kk = max(0.0, k - trail * 0.05)
                dot = path.pointAtPercent(kk)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(C(theme.PRIMARY_HOVER, 255 - trail * 60))
                p.drawEllipse(dot, 5 - trail, 5 - trail)
        else:
            _ripple(p, spot, (phase - 0.4) / 0.45, C(theme.SUCCESS))
            _ripple(p, spot, (phase - 0.5) / 0.45, C(theme.SUCCESS))
        clicks = f"{n} click{'s' if n != 1 else ''} received"
        _badge(p, QPointF(game.center().x() + 30, game.bottom() - 28), clicks, C(theme.SUCCESS))

        _window(p, work, "Your work  ·  active", C(theme.PRIMARY))
        full = "Hi! Writing this email while I-DB Macro clicks the game for me."
        shown = full[: int(t * 12) % (len(full) + 18)]
        p.setPen(C(theme.MUTED))
        p.setFont(theme.ui_font(13))
        p.drawText(QRectF(work.left() + 16, work.top() + 44, work.width() - 32, 80),
                   Qt.TextFlag.TextWordWrap, shown + ("|" if int(t * 2.5) % 2 else " "))
        _cursor(p, work.left() + work.width() * 0.62, work.bottom() - 54)
        _badge(p, QPointF(work.center().x(), work.bottom() - 22), "your mouse stays here", C(theme.PRIMARY))
        _logo(p, src, 44)
        p.setPen(C(theme.FAINT))
        p.setFont(theme.ui_font(11, QFont.Weight.DemiBold))
        p.drawText(QRectF(src.x() - 60, src.y() + 20, 120, 16), Qt.AlignmentFlag.AlignHCenter, "I-DB Macro")

    def _keys(self, p: QPainter, r: QRectF, t: float) -> None:
        _backdrop(p, r, QPointF(r.center().x(), r.top() + 60))
        left, right = r.left() + 150, r.right() - 28
        width = right - left
        frame_px, speed = 42.0, 70.0          # one game frame; scroll speed in px/s
        offset = (t * speed) % frame_px
        ticks = [left + i * frame_px - offset for i in range(int(width / frame_px) + 3)]
        ticks = [x for x in ticks if left <= x <= right]
        p.setFont(theme.ui_font(12, QFont.Weight.DemiBold))
        p.setPen(C(theme.MUTED))
        p.drawText(QRectF(left, r.top() + 18, width, 20), Qt.AlignmentFlag.AlignLeft,
                   "▲ each line = the game checking the keyboard (once per frame, ≈16 ms)")
        lane_h, first = 58, r.top() + 58
        lanes = [("Instant tap", "0 ms", 0.0, C(theme.DANGER)),
                 ("I-DB Macro", "40 ms", frame_px * 1.25, C(theme.SUCCESS))]
        spacing = 150.0
        p.save()
        p.setClipRect(QRectF(left, first - 10, width, 2 * lane_h + 60))
        for row, (name, length, bar_w, color) in enumerate(lanes):
            y = first + row * (lane_h + 34)
            p.setPen(C(theme.INK))
            p.setFont(theme.ui_font(13, QFont.Weight.DemiBold))
            p.drawText(QRectF(r.left() + 22, y + 6, 120, 22), Qt.AlignmentFlag.AlignLeft, name)
            p.setPen(C(theme.FAINT))
            p.setFont(theme.ui_font(11))
            p.drawText(QRectF(r.left() + 22, y + 28, 120, 18), Qt.AlignmentFlag.AlignLeft, f"press length {length}")
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C(theme.SURFACE))
            p.drawRoundedRect(QRectF(left, y, width, lane_h), 9, 9)
            shift = (t * speed) % spacing
            x = right - shift + spacing
            while x > left - bar_w - 4:
                if x < right:
                    bar = QRectF(x, y + 12, max(3.0, bar_w), lane_h - 24)
                    seen = any(bar.left() <= tx <= bar.right() for tx in ticks)
                    p.setBrush(color)
                    p.drawRoundedRect(bar, 3, 3)
                    if bar.center().x() < right - 50 and bar.center().x() > left + 40:
                        ok = bar_w > 0 and seen
                        mark = "seen ✓" if ok else ("missed ✗" if bar_w == 0 else "")
                        if mark:
                            _badge(p, QPointF(bar.center().x(), y + lane_h + 14), mark,
                                   C(theme.SUCCESS if ok else theme.DANGER))
                x -= spacing
        for tx in ticks:  # frame checks drawn on top, so crossings are visible
            p.setPen(QPen(C(theme.PRIMARY_HOVER, 150), 1.6))
            p.drawLine(QPointF(tx, first - 6), QPointF(tx, first + 2 * lane_h + 40))
        p.restore()
        cap = QRectF(r.left() + 24, r.bottom() - 66, 96, 48)
        down = (t * speed) % spacing < 25
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(C("#000000", 90))
        p.drawRoundedRect(cap.translated(0, 5), 10, 10)
        p.setPen(QPen(C(theme.PRIMARY if down else theme.BORDER_STRONG), 1.5))
        p.setBrush(C(theme.PRIMARY_SOFT if down else theme.SURFACE_STRONG))
        p.drawRoundedRect(cap.translated(0, 4 if down else 0), 10, 10)
        p.setPen(C(theme.INK))
        p.setFont(theme.ui_font(13, QFont.Weight.DemiBold))
        p.drawText(cap.translated(0, 4 if down else 0), Qt.AlignmentFlag.AlignCenter, "Space")
        p.setPen(C(theme.MUTED))
        p.setFont(theme.ui_font(12))
        p.drawText(QRectF(cap.right() + 18, cap.top(), r.right() - cap.right() - 40, cap.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap,
                   "A press only counts if a check line crosses it while the key is down.")

    def _macro(self, p: QPainter, r: QRectF, t: float) -> None:
        _backdrop(p, r, QPointF(r.center().x(), r.bottom() - 60))
        steps = [("Focus game", "window"), ("Click", "click"), ("Wait 0.5 s", "wait"), ("Press E", "key"),
                 ("Run saved\nautoclicker", "setup")]
        dur = [1.0, 1.0, 1.4, 1.0, 2.4]
        total = sum(dur)
        loop, lt = int(t / total), t % total
        idx, local, acc = 0, 0.0, 0.0
        for i, d in enumerate(dur):
            if lt < acc + d:
                idx, local = i, (lt - acc) / d
                break
            acc += d
        gap = 22
        w = (r.width() - 56 - gap * (len(steps) - 1)) / len(steps)
        y = r.top() + 30
        for i, (name, _kind) in enumerate(steps):
            box = QRectF(r.left() + 28 + i * (w + gap), y, w, 62)
            if i < len(steps) - 1:
                x1, x2 = box.right() + 3, box.right() + gap - 3
                done_link = i < idx
                p.setPen(QPen(C(theme.PRIMARY if done_link else theme.BORDER_STRONG), 2))
                p.drawLine(QPointF(x1, box.center().y()), QPointF(x2, box.center().y()))
                p.drawLine(QPointF(x2 - 5, box.center().y() - 4), QPointF(x2, box.center().y()))
                p.drawLine(QPointF(x2 - 5, box.center().y() + 4), QPointF(x2, box.center().y()))
            active, done = i == idx, i < idx
            if active:
                glow = C(theme.PRIMARY, 45)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(glow)
                p.drawRoundedRect(box.adjusted(-5, -5, 5, 5), 14, 14)
            p.setPen(QPen(C(theme.PRIMARY_HOVER if active else (theme.PRIMARY if done else theme.BORDER_STRONG)),
                          2 if active else 1))
            p.setBrush(C(theme.PRIMARY_SOFT if active else theme.SURFACE_STRONG))
            p.drawRoundedRect(box, 11, 11)
            if active:  # progress fill along the bottom edge
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(C(theme.PRIMARY_HOVER))
                p.drawRoundedRect(QRectF(box.left() + 8, box.bottom() - 6, (box.width() - 16) * local, 3), 1.5, 1.5)
            p.setPen(C(theme.INK if active or done else theme.MUTED))
            p.setFont(theme.ui_font(12, QFont.Weight.DemiBold))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, (("✓ " if done else "") + f"{i + 1}. {name}"))
        stage = QRectF(r.left() + 28, y + 90, r.width() - 56, r.bottom() - y - 108)
        p.setPen(QPen(C(theme.BORDER), 1))
        p.setBrush(C(theme.SURFACE, 220))
        p.drawRoundedRect(stage, 14, 14)
        _badge(p, QPointF(stage.right() - 56, stage.top() + 24), f"loop {loop + 1} of ∞", C(theme.PRIMARY))
        c = QPointF(stage.center().x(), stage.center().y() + 6)
        kind = steps[idx][1]
        if kind == "window":
            k = _ease(local * 1.6)
            win = QRectF(c.x() - 150 * k, c.y() - 58 * k, 300 * k, 116 * k)
            if k > 0.2:
                _window(p, win, "Game", C(theme.PRIMARY))
        elif kind == "click":
            _ripple(p, c, local, C(theme.SUCCESS))
            _ripple(p, c, local - 0.15, C(theme.SUCCESS))
            _cursor(p, c.x() - 2, c.y() - 2)
        elif kind == "wait":
            p.setPen(QPen(C(theme.BORDER_STRONG), 5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, 34, 34)
            p.setPen(QPen(C(theme.PRIMARY_HOVER), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(QRectF(c.x() - 34, c.y() - 34, 68, 68), 90 * 16, int(-360 * 16 * local))
            p.setPen(C(theme.INK))
            p.setFont(theme.ui_font(14, QFont.Weight.DemiBold))
            p.drawText(QRectF(c.x() - 34, c.y() - 34, 68, 68), Qt.AlignmentFlag.AlignCenter,
                       f"{0.5 * (1 - local):.1f}s")
        elif kind == "key":
            down = 0.15 < local < 0.55
            cap = QRectF(c.x() - 36, c.y() - 30 + (5 if down else 0), 72, 60)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C("#000000", 90))
            p.drawRoundedRect(QRectF(c.x() - 36, c.y() - 24, 72, 60), 12, 12)
            p.setPen(QPen(C(theme.PRIMARY_HOVER if down else theme.BORDER_STRONG), 1.6))
            p.setBrush(C(theme.PRIMARY_SOFT if down else theme.SURFACE_STRONG))
            p.drawRoundedRect(cap, 12, 12)
            p.setPen(C(theme.INK))
            p.setFont(theme.ui_font(20, QFont.Weight.Bold))
            p.drawText(cap, Qt.AlignmentFlag.AlignCenter, "E")
        else:
            spots = [QPointF(c.x() - 110 + k * 55, c.y() - 8 + (18 if k % 2 else -8)) for k in range(5)]
            for k, spot in enumerate(spots):
                _ripple(p, spot, (local * 4 - k * 0.2) % 1, C(theme.SUCCESS))
            n = int(local * 24)
            _badge(p, QPointF(c.x(), stage.bottom() - 26), f"{n} click{'' if n == 1 else 's'} · stops with the macro",
                   C(theme.SUCCESS))

    def _smart(self, p: QPainter, r: QRectF, t: float) -> None:
        on_game = (t % 6) < 3.6
        game = QRectF(r.left() + 26, r.top() + 34, r.width() * 0.45, r.height() * 0.72)
        chat = QRectF(r.right() - 26 - r.width() * 0.45, r.top() + 34, r.width() * 0.45, r.height() * 0.72)
        _backdrop(p, r, game.center() if on_game else chat.center())
        _window(p, game, "Game  ·  locked in", C(theme.SUCCESS), active=on_game)
        _window(p, chat, "Discord", C(theme.PRIMARY), active=not on_game)
        # Padlock on the game's title bar.
        lock = QPointF(game.right() - 24, game.top() + 16)
        p.setPen(QPen(C(theme.SUCCESS), 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(lock.x() - 4, lock.y() - 9, 8, 9), 0, 180 * 16)
        p.setBrush(C(theme.SUCCESS))
        p.drawRoundedRect(QRectF(lock.x() - 6, lock.y() - 3, 12, 9), 2, 2)
        spot = QPointF(game.center().x() - 20, game.center().y() - 6)
        cap = QRectF(game.left() + 20, game.bottom() - 64, 44, 40)
        if on_game:
            _ripple(p, spot, (t % 0.8) / 0.8, C(theme.SUCCESS))
            _ripple(p, spot, (t % 0.8) / 0.8 - 0.2, C(theme.SUCCESS))
            _cursor(p, spot.x() + 8, spot.y() + 8)
            _badge(p, QPointF(game.center().x() + 30, game.bottom() - 44), "clicking · holding W", C(theme.SUCCESS))
        else:
            _badge(p, spot, "Paused", C(theme.WARNING))
            _badge(p, QPointF(game.center().x() + 30, game.bottom() - 44), "W let go", C(theme.WARNING))
            _cursor(p, chat.center().x() + 40, chat.center().y() + 30)
            full = "you: brb, getting food"
            shown = full[: int(((t % 6) - 3.6) * 12)]
            p.setPen(C(theme.MUTED))
            p.setFont(theme.ui_font(13))
            p.drawText(QRectF(chat.left() + 16, chat.top() + 46, chat.width() - 32, 40),
                       Qt.AlignmentFlag.AlignLeft, shown + ("|" if int(t * 2.5) % 2 else " "))
        held = on_game
        p.setPen(QPen(C(theme.SUCCESS if held else theme.BORDER_STRONG), 1.4))
        p.setBrush(C(theme.PRIMARY_SOFT if held else theme.SURFACE_STRONG))
        p.drawRoundedRect(cap.translated(0, 3 if held else 0), 8, 8)
        p.setPen(C(theme.INK))
        p.setFont(theme.ui_font(14, QFont.Weight.Bold))
        p.drawText(cap.translated(0, 3 if held else 0), Qt.AlignmentFlag.AlignCenter, "W")
        active = chat if not on_game else game
        _badge(p, QPointF(active.center().x(), r.bottom() - 22), "▲ active window", C(theme.PRIMARY))

class ExplainerDialog(QDialog):
    def __init__(self, parent, scene: str):
        super().__init__(parent)
        title, simple, technical = TEXT[scene]
        self.setWindowTitle(title)
        self.setMinimumSize(720, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(14)
        self.level = Segmented([("simple", "Simple"), ("technical", "Technical")])
        lay.addLayout(hbox(label(title, "title"), None, self.level))
        self.stage = Stage(scene)
        lay.addWidget(self.stage, 1)
        self.text = label(simple, None, wrap=True)
        self.text.setTextFormat(Qt.TextFormat.PlainText)
        self.text.setMinimumHeight(96)
        self.text.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(self.text)
        close = button("Got it", "primary")
        close.clicked.connect(self.accept)
        lay.addLayout(hbox(None, close))
        self.level.changed.connect(lambda k: self.text.setText(simple if k == "simple" else technical))


def bulb(parent: QWidget, scene: str, tip: str = "How does this work?") -> IconButton:
    """A small light-bulb button that opens the explainer for ``scene``."""
    b = IconButton("bulb", "", "ghost", tip)
    b.clicked.connect(lambda: ExplainerDialog(parent.window(), scene).exec())
    return b


