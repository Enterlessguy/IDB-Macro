"""Linux X11 backend.

Foreground input uses the XTEST extension (real input, like a physical
device). Background input uses ``XSendEvent`` straight to the picked window.
Most GTK and Qt apps accept those events; some programs (xterm by default,
many games) ignore synthetic events on purpose.
"""

from __future__ import annotations

import contextlib
import os
import threading
import time
from collections.abc import Iterator

from Xlib import XK, X, error
from Xlib import display as xdisplay
from Xlib.ext import xtest
from Xlib.protocol import event as xevent

from ..core.keys import X_KEYSYM
from ..core.models import TargetPoint, WindowTarget
from .base import Backend, BackendError, PickResult, TargetLost

XK.load_keysym_group("xf86")  # media keys

BUTTON_CODES = {"left": 1, "middle": 2, "right": 3, "x1": 8, "x2": 9}
MODIFIER_MASKS = {"shift": X.ShiftMask, "rshift": X.ShiftMask, "ctrl": X.ControlMask,
                  "rctrl": X.ControlMask, "alt": X.Mod1Mask, "ralt": X.Mod1Mask, "win": X.Mod4Mask}
BUTTON_MASKS = {1: X.Button1Mask, 2: X.Button2Mask, 3: X.Button3Mask}


def char_keysym(ch: str) -> int:
    if ch == "\n":
        return XK.XK_Return
    if ch == "\t":
        return XK.XK_Tab
    code = ord(ch)
    return code if code <= 0xFF else 0x01000000 | code


class X11Backend(Backend):
    name = "x11"
    supports_background = True

    def __init__(self) -> None:
        try:
            self.d = xdisplay.Display()
        except Exception as exc:
            raise BackendError(f"Cannot connect to the X server: {exc}") from None
        if not self.d.has_extension("XTEST"):
            raise BackendError("The X server has no XTEST extension, so input cannot be simulated.")
        self.root = self.d.screen().root
        self.lock = threading.RLock()
        self.own_pid = os.getpid()
        self._errors: list[error.XError] = []
        self.d.set_error_handler(self._errors.append)
        if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
            self.notice = ("Wayland session: only apps running under XWayland can be controlled, "
                           "and foreground input may be limited.")
        self._atoms = {name: self.d.intern_atom(name) for name in (
            "_NET_WM_NAME", "UTF8_STRING", "_NET_WM_PID", "_NET_CLIENT_LIST",
            "_NET_ACTIVE_WINDOW", "WM_STATE")}

    # ---- helpers ------------------------------------------------------------

    def _win(self, xid: int):
        return self.d.create_resource_object("window", xid)

    def _sync_checked(self) -> None:
        self._errors.clear()
        self.d.sync()
        if any(isinstance(e, error.BadWindow) for e in self._errors):
            raise TargetLost("The target window closed.")

    def _keycode(self, key: str) -> int:
        sym = XK.string_to_keysym(X_KEYSYM[key])
        code = self.d.keysym_to_keycode(sym)
        if not code:
            raise BackendError(f"This keyboard layout has no key for {key!r}.")
        return code

    def _state_for(self, held: tuple[str, ...]) -> int:
        state = 0
        for k in held:
            state |= MODIFIER_MASKS.get(k, 0)
        return state

    # ---- foreground ---------------------------------------------------------

    def cursor_pos(self) -> tuple[int, int]:
        with self.lock:
            p = self.root.query_pointer()
            return p.root_x, p.root_y

    def move(self, x: int, y: int) -> None:
        with self.lock:
            xtest.fake_input(self.d, X.MotionNotify, x=int(x), y=int(y))
            self.d.sync()

    def _button(self, code: int, down: bool) -> None:
        with self.lock:
            xtest.fake_input(self.d, X.ButtonPress if down else X.ButtonRelease, code)
            self.d.sync()

    def mouse_down(self, button: str) -> None:
        self._button(BUTTON_CODES[button], True)

    def mouse_up(self, button: str) -> None:
        self._button(BUTTON_CODES[button], False)

    def scroll(self, amount: int, horizontal: bool = False) -> None:
        if horizontal:
            code = 7 if amount > 0 else 6
        else:
            code = 4 if amount > 0 else 5
        for _ in range(abs(amount)):
            self._button(code, True)
            self._button(code, False)

    def key_down(self, key: str) -> None:
        with self.lock:
            xtest.fake_input(self.d, X.KeyPress, self._keycode(key))
            self.d.sync()

    def key_up(self, key: str) -> None:
        with self.lock:
            xtest.fake_input(self.d, X.KeyRelease, self._keycode(key))
            self.d.sync()

    def _code_for_char(self, ch: str) -> tuple[int, bool, bool]:
        """Return (keycode, needs_shift, remapped) for a character."""
        sym = char_keysym(ch)
        for code, index in self.d.keysym_to_keycodes(sym):
            if index in (0, 1):
                return code, index == 1, False
        # No key produces this character: borrow an unused keycode.
        first = self.d.display.info.min_keycode
        count = self.d.display.info.max_keycode - first + 1
        mapping = self.d.get_keyboard_mapping(first, count)
        for offset, syms in enumerate(mapping):
            if not any(syms):
                code = first + offset
                self.d.change_keyboard_mapping(code, [(sym, sym)])
                self.d.sync()
                time.sleep(0.01)
                return code, False, True
        raise BackendError(f"Cannot type {ch!r}: no free key to map it to.")

    def type_text(self, text: str) -> None:
        shift = self._keycode("shift")
        with self.lock:
            for ch in text:
                code, needs_shift, remapped = self._code_for_char(ch)
                if needs_shift:
                    xtest.fake_input(self.d, X.KeyPress, shift)
                xtest.fake_input(self.d, X.KeyPress, code)
                xtest.fake_input(self.d, X.KeyRelease, code)
                if needs_shift:
                    xtest.fake_input(self.d, X.KeyRelease, shift)
                self.d.sync()
                if remapped:
                    time.sleep(0.01)
                    self.d.change_keyboard_mapping(code, [(X.NoSymbol, X.NoSymbol)])
                    self.d.sync()

    # ---- windows ------------------------------------------------------------

    def _prop(self, win, name: str):
        with contextlib.suppress(error.XError):
            prop = win.get_full_property(self._atoms[name], X.AnyPropertyType)
            return prop.value if prop else None
        return None

    def _title(self, win) -> str:
        value = self._prop(win, "_NET_WM_NAME")
        if value is None:
            with contextlib.suppress(error.XError):
                value = win.get_wm_name()
        if isinstance(value, bytes):
            return value.decode("utf-8", "replace")
        return value or ""

    def _pid(self, win) -> int:
        value = self._prop(win, "_NET_WM_PID")
        return int(value[0]) if value is not None and len(value) else 0

    @staticmethod
    def _process_name(pid: int) -> str:
        try:
            with open(f"/proc/{pid}/comm", encoding="utf-8") as fh:
                return fh.read().strip()
        except OSError:
            return ""

    def _describe(self, xid: int, child: int = 0) -> WindowTarget:
        win = self._win(xid)
        pid = self._pid(win)
        cls = ""
        with contextlib.suppress(error.XError):
            wm_class = win.get_wm_class()
            cls = wm_class[1] if wm_class else ""
        return WindowTarget(handle=xid, title=self._title(win), process=self._process_name(pid) if pid else "",
                            window_class=cls, pid=pid, child=child)

    def _chain_at(self, x: int, y: int) -> list[int]:
        """Windows under a screen point, from top-level frame to deepest child."""
        chain = []
        win = self.root
        for _ in range(64):
            reply = win.translate_coords(self.root, x, y)
            child = reply.child
            if not child:
                break
            xid = child.id if hasattr(child, "id") else int(child)
            chain.append(xid)
            win = self._win(xid)
        return chain

    def pick_at(self, x: int, y: int) -> PickResult:
        with self.lock:
            chain = self._chain_at(x, y)
            if not chain:
                raise BackendError("There is no window at that spot.")
            client = next((w for w in chain if self._prop(self._win(w), "WM_STATE") is not None), chain[0])
            deepest = chain[-1]
            target = self._describe(client, deepest)
            if target.pid == self.own_pid:
                raise BackendError("That is I-DB Macro itself. Pick another window.")
            cx, cy = self._to_window(client, x, y)
            dx, dy = self._to_window(deepest, x, y)
            return PickResult(target, TargetPoint(cx, cy, deepest, dx, dy))

    def foreground_window(self) -> WindowTarget | None:
        with self.lock:
            active = self._prop(self.root, "_NET_ACTIVE_WINDOW")
            if active is None or not len(active) or not active[0]:
                return None
            win = self._win(int(active[0]))
            return WindowTarget(handle=int(active[0]), title=self._title(win), pid=self._pid(win))

    def window_at(self, x: int, y: int) -> WindowTarget | None:
        with self.lock:
            chain = self._chain_at(x, y)
            if not chain:
                return None
            client = next((w for w in chain if self._prop(self._win(w), "WM_STATE") is not None), chain[0])
            win = self._win(client)
            return WindowTarget(handle=client, title=self._title(win), pid=self._pid(win))

    def _to_window(self, xid: int, x: int, y: int) -> tuple[int, int]:
        reply = self._win(xid).translate_coords(self.root, x, y)
        return reply.x, reply.y

    def list_windows(self) -> list[WindowTarget]:
        with self.lock:
            ids = self._prop(self.root, "_NET_CLIENT_LIST")
            out = []
            for xid in ids if ids is not None else []:
                with contextlib.suppress(error.XError):
                    target = self._describe(int(xid))
                    if target.pid != self.own_pid and target.title:
                        out.append(target)
            return out

    def window_alive(self, target: WindowTarget) -> bool:
        if not target.handle:
            return False
        with self.lock:
            try:
                self._win(target.handle).get_geometry()
            except error.XError:
                return False
            return not target.pid or self._pid(self._win(target.handle)) in (0, target.pid)

    def reacquire(self, target: WindowTarget) -> WindowTarget | None:
        if not target.process:
            return None
        candidates = [w for w in self.list_windows()
                      if w.process == target.process
                      and (not target.window_class or w.window_class == target.window_class)]
        exact = [w for w in candidates if w.title == target.title]
        return (exact or candidates or [None])[0]

    def client_to_screen(self, target: WindowTarget, x: int, y: int) -> tuple[int, int]:
        with self.lock:
            reply = self.root.translate_coords(self._win(target.handle), x, y)
            return reply.x, reply.y

    def screen_to_client(self, target: WindowTarget, x: int, y: int) -> tuple[int, int]:
        with self.lock:
            return self._to_window(target.handle, x, y)

    def focus_window(self, title_contains: str) -> bool:
        needle = title_contains.lower()
        match = next((w for w in self.list_windows() if needle in w.title.lower()), None)
        if match is None:
            return False
        with self.lock:
            win = self._win(match.handle)
            win.map()
            ev = xevent.ClientMessage(window=win, client_type=self._atoms["_NET_ACTIVE_WINDOW"],
                                      data=(32, [2, X.CurrentTime, 0, 0, 0]))
            self.root.send_event(ev, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
            self.d.sync()
        time.sleep(0.15)
        return True

    # ---- background ---------------------------------------------------------

    def _resolve(self, target: WindowTarget, point: TargetPoint) -> tuple[int, int, int]:
        root_id = self.ensure_target(target).handle
        if point.child:
            with contextlib.suppress(error.XError):
                self._win(point.child).get_geometry()
                return point.child, point.cx, point.cy
        sx, sy = self.client_to_screen(target, point.x, point.y)
        win_id, x, y = root_id, point.x, point.y
        for _ in range(64):
            reply = self._win(win_id).translate_coords(self.root, sx, sy)
            if not reply.child:
                break
            win_id = reply.child.id if hasattr(reply.child, "id") else int(reply.child)
            x, y = self._to_window(win_id, sx, sy)
        return win_id, x, y

    def _send(self, xid: int, ev, mask: int) -> None:
        self._win(xid).send_event(ev, event_mask=mask, propagate=True)

    def bg_mouse(self, target: WindowTarget, point: TargetPoint, button: str,
                 action: str, count: int = 1, spoof_focus: bool = False) -> None:
        self._bg_button(target, point, BUTTON_CODES[button], action, count, spoof_focus)

    def bg_scroll(self, target: WindowTarget, point: TargetPoint, amount: int, horizontal: bool = False,
                  spoof_focus: bool = False) -> None:
        # X11 reports wheel steps as clicks of buttons 4-7.
        code = (7 if amount > 0 else 6) if horizontal else (4 if amount > 0 else 5)
        self._bg_button(target, point, code, "click", abs(amount), spoof_focus)

    def _bg_button(self, target: WindowTarget, point: TargetPoint, code: int,
                   action: str, count: int, spoof_focus: bool) -> None:
        with self.lock:
            xid, x, y = self._resolve(target, point)
            screen = self.root.translate_coords(self._win(xid), x, y)
            common = dict(time=X.CurrentTime, root=self.root, window=self._win(xid), same_screen=1,
                          child=X.NONE, root_x=screen.x, root_y=screen.y, event_x=x, event_y=y)
            if spoof_focus:
                self._spoof_focus(target.handle)
            self._send(xid, xevent.MotionNotify(state=0, detail=0, **common), X.PointerMotionMask)
            presses = 0 if action == "move" else count if action == "click" else 1
            for _ in range(presses):
                if action in ("click", "down"):
                    self._send(xid, xevent.ButtonPress(state=0, detail=code, **common), X.ButtonPressMask)
                if action in ("click", "up"):
                    self._send(xid, xevent.ButtonRelease(state=BUTTON_MASKS.get(code, 0), detail=code, **common),
                               X.ButtonReleaseMask)
            self._sync_checked()

    def _spoof_focus(self, xid: int) -> None:
        ev = xevent.FocusIn(window=self._win(xid), detail=X.NotifyNonlinear, mode=X.NotifyNormal)
        self._send(xid, ev, X.FocusChangeMask)

    def _key_window(self, target: WindowTarget) -> int:
        return self.ensure_target(target).handle

    def bg_key(self, target: WindowTarget, key: str, down: bool,
               held: tuple[str, ...] = (), spoof_focus: bool = False) -> None:
        with self.lock:
            xid = self._key_window(target)
            if spoof_focus and down:
                self._spoof_focus(xid)
            self._send_key(xid, self._keycode(key), down, self._state_for(held))
            self._sync_checked()

    def _send_key(self, xid: int, code: int, down: bool, state: int) -> None:
        cls = xevent.KeyPress if down else xevent.KeyRelease
        ev = cls(time=X.CurrentTime, root=self.root, window=self._win(xid), same_screen=1, child=X.NONE,
                 root_x=0, root_y=0, event_x=0, event_y=0, state=state, detail=code)
        self._send(xid, ev, X.KeyPressMask if down else X.KeyReleaseMask)

    def bg_text(self, target: WindowTarget, text: str, spoof_focus: bool = False) -> None:
        with self.lock:
            xid = self._key_window(target)
            if spoof_focus:
                self._spoof_focus(xid)
            for ch in text:
                code, needs_shift, remapped = self._code_for_char(ch)
                state = X.ShiftMask if needs_shift else 0
                self._send_key(xid, code, True, state)
                self._send_key(xid, code, False, state)
                self._sync_checked()
                if remapped:
                    time.sleep(0.01)
                    self.d.change_keyboard_mapping(code, [(X.NoSymbol, X.NoSymbol)])
                    self.d.sync()

    @contextlib.contextmanager
    def session(self) -> Iterator[None]:
        yield

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.d.close()
