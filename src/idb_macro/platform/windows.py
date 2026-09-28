"""Windows backend.

Foreground input goes through ``SendInput`` (scan codes, so games see real
key presses). Background input is posted as window messages to the exact
control that was picked, so the cursor and focus never move and a minimized
target still receives it if the app processes messages while minimized.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import time
from collections.abc import Iterator
from ctypes import wintypes as wt

from ..core.keys import WIN_EXTENDED, WIN_VK
from ..core.models import TargetPoint, WindowTarget
from ..core.timing import high_resolution_timer
from .base import Backend, BackendError, PickResult, TargetDenied, TargetLost

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
try:
    dwmapi = ctypes.WinDLL("dwmapi")
except OSError:
    dwmapi = None

ULONG_PTR = ctypes.c_size_t
INJECT_TAG = 0x1DB00001

# SendInput
INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP = 0x0020, 0x0040
MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP = 0x0080, 0x0100
MOUSEEVENTF_WHEEL, MOUSEEVENTF_HWHEEL = 0x0800, 0x1000
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP = 0x0001, 0x0002
KEYEVENTF_UNICODE, KEYEVENTF_SCANCODE = 0x0004, 0x0008
WHEEL_DELTA = 120
MAPVK_VK_TO_VSC_EX = 4

# Window messages
WM_NULL = 0x0000
WM_ACTIVATE, WM_SETFOCUS, WM_ACTIVATEAPP, WM_NCACTIVATE = 0x0006, 0x0007, 0x001C, 0x0086
WM_KEYDOWN, WM_KEYUP, WM_CHAR = 0x0100, 0x0101, 0x0102
WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0104, 0x0105
WM_MOUSEMOVE = 0x0200
WM_MOUSEWHEEL, WM_MOUSEHWHEEL = 0x020A, 0x020E
MK_LBUTTON, MK_RBUTTON, MK_MBUTTON, MK_XBUTTON1, MK_XBUTTON2 = 0x1, 0x2, 0x10, 0x20, 0x40

# button -> (down msg, up msg, double-click msg, MK flag, xbutton id)
BUTTON_MESSAGES = {
    "left": (0x0201, 0x0202, 0x0203, MK_LBUTTON, 0),
    "right": (0x0204, 0x0205, 0x0206, MK_RBUTTON, 0),
    "middle": (0x0207, 0x0208, 0x0209, MK_MBUTTON, 0),
    "x1": (0x020B, 0x020C, 0x020D, MK_XBUTTON1, 1),
    "x2": (0x020B, 0x020C, 0x020D, MK_XBUTTON2, 2),
}
BUTTON_INPUT = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, 0),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP, 0),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP, 0),
    "x1": (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, 1),
    "x2": (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, 2),
}

GA_ROOT = 2
CWP_SKIPINVISIBLE, CWP_SKIPTRANSPARENT = 0x1, 0x4
GW_OWNER = 4
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW, WS_EX_APPWINDOW = 0x80, 0x40000
DWMWA_CLOAKED = 14
SW_RESTORE = 9
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
ERROR_ACCESS_DENIED, ERROR_INVALID_WINDOW_HANDLE, ERROR_TIMEOUT = 5, 1400, 1460
SMTO_ABORTIFHUNG = 0x2
SEND_TIMEOUT_MS = 1000
BUTTON_VK = {"left": 0x01, "right": 0x02, "middle": 0x04, "x1": 0x05, "x2": 0x06}
# Generic modifier VKs that GetKeyState callers check alongside the sided ones.
GENERIC_VK = {0xA0: 0x10, 0xA1: 0x10, 0xA2: 0x11, 0xA3: 0x11, 0xA4: 0x12, 0xA5: 0x12}


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("flags", wt.DWORD), ("hwndActive", wt.HWND),
                ("hwndFocus", wt.HWND), ("hwndCapture", wt.HWND), ("hwndMenuOwner", wt.HWND),
                ("hwndMoveSize", wt.HWND), ("hwndCaret", wt.HWND), ("rcCaret", wt.RECT)]


WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def _proto(dll, name, restype, *argtypes):
    fn = getattr(dll, name)
    fn.restype = restype
    fn.argtypes = argtypes
    return fn


SendInput = _proto(user32, "SendInput", wt.UINT, wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
PostMessageW = _proto(user32, "PostMessageW", wt.BOOL, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
WindowFromPoint = _proto(user32, "WindowFromPoint", wt.HWND, wt.POINT)
ChildWindowFromPointEx = _proto(user32, "ChildWindowFromPointEx", wt.HWND, wt.HWND, wt.POINT, wt.UINT)
GetAncestor = _proto(user32, "GetAncestor", wt.HWND, wt.HWND, wt.UINT)
GetWindow = _proto(user32, "GetWindow", wt.HWND, wt.HWND, wt.UINT)
ScreenToClient = _proto(user32, "ScreenToClient", wt.BOOL, wt.HWND, ctypes.POINTER(wt.POINT))
ClientToScreen = _proto(user32, "ClientToScreen", wt.BOOL, wt.HWND, ctypes.POINTER(wt.POINT))
MapWindowPoints = _proto(user32, "MapWindowPoints", ctypes.c_int, wt.HWND, wt.HWND,
                         ctypes.POINTER(wt.POINT), wt.UINT)
IsWindow = _proto(user32, "IsWindow", wt.BOOL, wt.HWND)
IsIconic = _proto(user32, "IsIconic", wt.BOOL, wt.HWND)
IsWindowVisible = _proto(user32, "IsWindowVisible", wt.BOOL, wt.HWND)
GetWindowTextLengthW = _proto(user32, "GetWindowTextLengthW", ctypes.c_int, wt.HWND)
GetWindowTextW = _proto(user32, "GetWindowTextW", ctypes.c_int, wt.HWND, wt.LPWSTR, ctypes.c_int)
GetClassNameW = _proto(user32, "GetClassNameW", ctypes.c_int, wt.HWND, wt.LPWSTR, ctypes.c_int)
GetWindowThreadProcessId = _proto(user32, "GetWindowThreadProcessId", wt.DWORD, wt.HWND,
                                  ctypes.POINTER(wt.DWORD))
GetGUIThreadInfo = _proto(user32, "GetGUIThreadInfo", wt.BOOL, wt.DWORD, ctypes.POINTER(GUITHREADINFO))
EnumWindows = _proto(user32, "EnumWindows", wt.BOOL, WNDENUMPROC, wt.LPARAM)
GetWindowLongPtrW = _proto(user32, "GetWindowLongPtrW", ctypes.c_ssize_t, wt.HWND, ctypes.c_int)
GetForegroundWindow = _proto(user32, "GetForegroundWindow", wt.HWND)
SetForegroundWindow = _proto(user32, "SetForegroundWindow", wt.BOOL, wt.HWND)
BringWindowToTop = _proto(user32, "BringWindowToTop", wt.BOOL, wt.HWND)
ShowWindow = _proto(user32, "ShowWindow", wt.BOOL, wt.HWND, ctypes.c_int)
AttachThreadInput = _proto(user32, "AttachThreadInput", wt.BOOL, wt.DWORD, wt.DWORD, wt.BOOL)
GetCursorPos = _proto(user32, "GetCursorPos", wt.BOOL, ctypes.POINTER(wt.POINT))
SetCursorPos = _proto(user32, "SetCursorPos", wt.BOOL, ctypes.c_int, ctypes.c_int)
MapVirtualKeyW = _proto(user32, "MapVirtualKeyW", wt.UINT, wt.UINT, wt.UINT)
SendMessageTimeoutW = _proto(user32, "SendMessageTimeoutW", ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM,
                             wt.LPARAM, wt.UINT, wt.UINT, ctypes.POINTER(ctypes.c_size_t))
KeyState = ctypes.c_ubyte * 256
GetKeyboardState = _proto(user32, "GetKeyboardState", wt.BOOL, ctypes.POINTER(ctypes.c_ubyte))
SetKeyboardState = _proto(user32, "SetKeyboardState", wt.BOOL, ctypes.POINTER(ctypes.c_ubyte))
GetCurrentThreadId = _proto(kernel32, "GetCurrentThreadId", wt.DWORD)
OpenProcess = _proto(kernel32, "OpenProcess", wt.HANDLE, wt.DWORD, wt.BOOL, wt.DWORD)
CloseHandle = _proto(kernel32, "CloseHandle", wt.BOOL, wt.HANDLE)
QueryFullProcessImageNameW = _proto(kernel32, "QueryFullProcessImageNameW", wt.BOOL, wt.HANDLE,
                                    wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD))


def enable_dpi_awareness() -> None:
    """Work in physical pixels so picked points match what SendInput uses."""
    with contextlib.suppress(AttributeError, OSError):
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    with contextlib.suppress(AttributeError, OSError):
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)


def _h(hwnd) -> int:
    return int(hwnd or 0)


def _make_lparam(x: int, y: int) -> int:
    return ((y & 0xFFFF) << 16) | (x & 0xFFFF)


def window_text(hwnd: int) -> str:
    length = GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(max(1, length + 1))
    GetWindowTextW(hwnd, buf, len(buf))
    return buf.value


def window_class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    GetClassNameW(hwnd, buf, len(buf))
    return buf.value


def window_pid(hwnd: int) -> int:
    pid = wt.DWORD(0)
    GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def process_name(pid: int) -> str:
    handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wt.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
        return ""
    finally:
        CloseHandle(handle)


def _is_cloaked(hwnd: int) -> bool:
    if dwmapi is None:
        return False
    cloaked = wt.DWORD(0)
    res = dwmapi.DwmGetWindowAttribute(wt.HWND(hwnd), DWMWA_CLOAKED, ctypes.byref(cloaked),
                                       ctypes.sizeof(cloaked))
    return res == 0 and cloaked.value != 0


class WindowsBackend(Backend):
    name = "windows"
    supports_background = True

    def __init__(self) -> None:
        enable_dpi_awareness()
        self.own_pid = os.getpid()
        self._real_keys: set[str] = set()

    # ---- foreground ---------------------------------------------------------

    def _send(self, *inputs: INPUT) -> None:
        arr = (INPUT * len(inputs))(*inputs)
        sent = SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
        if sent != len(inputs):
            raise BackendError(
                "Windows blocked the input. The focused window may belong to an app running as "
                "administrator, or the desktop is locked.")

    @staticmethod
    def _mouse_input(flags: int, data: int = 0) -> INPUT:
        return INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(0, 0, data & 0xFFFFFFFF, flags, 0, INJECT_TAG))

    @staticmethod
    def _key_input(key: str, up: bool) -> INPUT:
        vk = WIN_VK[key]
        sc = MapVirtualKeyW(vk, MAPVK_VK_TO_VSC_EX)
        flags = KEYEVENTF_KEYUP if up else 0
        if sc:
            flags |= KEYEVENTF_SCANCODE
            if (sc >> 8) in (0xE0, 0xE1) or key in WIN_EXTENDED:
                flags |= KEYEVENTF_EXTENDEDKEY
        elif key in WIN_EXTENDED:
            flags |= KEYEVENTF_EXTENDEDKEY
        return INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(vk, sc & 0xFF, flags, 0, INJECT_TAG))

    def cursor_pos(self) -> tuple[int, int]:
        pt = wt.POINT()
        GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y

    def move(self, x: int, y: int) -> None:
        SetCursorPos(int(x), int(y))

    def mouse_down(self, button: str) -> None:
        down, _up, xbtn = BUTTON_INPUT[button]
        self._send(self._mouse_input(down, xbtn))

    def mouse_up(self, button: str) -> None:
        _down, up, xbtn = BUTTON_INPUT[button]
        self._send(self._mouse_input(up, xbtn))

    def click(self, button: str, count: int = 1) -> None:
        down, up, xbtn = BUTTON_INPUT[button]
        inputs = []
        for _ in range(count):
            inputs += [self._mouse_input(down, xbtn), self._mouse_input(up, xbtn)]
        self._send(*inputs)

    def scroll(self, amount: int, horizontal: bool = False) -> None:
        flag = MOUSEEVENTF_HWHEEL if horizontal else MOUSEEVENTF_WHEEL
        self._send(self._mouse_input(flag, amount * WHEEL_DELTA))

    def key_down(self, key: str) -> None:
        self._send(self._key_input(key, up=False))

    def key_up(self, key: str) -> None:
        self._send(self._key_input(key, up=True))

    def type_text(self, text: str) -> None:
        inputs: list[INPUT] = []
        for ch in text.replace("\r\n", "\n"):
            if ch in "\n\t":
                key = "enter" if ch == "\n" else "tab"
                inputs += [self._key_input(key, False), self._key_input(key, True)]
                continue
            data = ch.encode("utf-16-le")
            for i in range(0, len(data), 2):
                unit = int.from_bytes(data[i:i + 2], "little")
                for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
                    inputs.append(INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(0, unit, flags, 0, INJECT_TAG)))
        if inputs:
            self._send(*inputs)

    # ---- windows ------------------------------------------------------------

    def _describe(self, root: int, child: int = 0) -> WindowTarget:
        pid = window_pid(root)
        return WindowTarget(handle=root, title=window_text(root), process=process_name(pid),
                            window_class=window_class(root), pid=pid, child=child)

    def pick_at(self, x: int, y: int) -> PickResult:
        hwnd = _h(WindowFromPoint(wt.POINT(x, y)))
        if not hwnd:
            raise BackendError("There is no window at that spot.")
        root = _h(GetAncestor(hwnd, GA_ROOT)) or hwnd
        if window_pid(root) == self.own_pid:
            raise BackendError("That is IDB-Macro itself. Pick another window.")
        root_pt, child_pt = wt.POINT(x, y), wt.POINT(x, y)
        ScreenToClient(root, ctypes.byref(root_pt))
        ScreenToClient(hwnd, ctypes.byref(child_pt))
        target = self._describe(root, hwnd if hwnd != root else 0)
        return PickResult(target, TargetPoint(root_pt.x, root_pt.y, hwnd, child_pt.x, child_pt.y))

    def list_windows(self) -> list[WindowTarget]:
        handles: list[int] = []

        @WNDENUMPROC
        def collect(hwnd, _lparam):
            h = _h(hwnd)
            if not (IsWindowVisible(h) or IsIconic(h)) or GetWindowTextLengthW(h) == 0:
                return True
            if _h(GetWindow(h, GW_OWNER)):
                return True
            ex = GetWindowLongPtrW(h, GWL_EXSTYLE)
            if ex & WS_EX_TOOLWINDOW and not ex & WS_EX_APPWINDOW:
                return True
            if _is_cloaked(h) or window_pid(h) == self.own_pid:
                return True
            handles.append(h)
            return True

        EnumWindows(collect, 0)
        return [self._describe(h) for h in handles]

    def window_alive(self, target: WindowTarget) -> bool:
        if not target.handle or not IsWindow(target.handle):
            return False
        # Handles are recycled; make sure it still belongs to the same process.
        return not target.pid or window_pid(target.handle) == target.pid

    @staticmethod
    def _light(hwnd: int) -> WindowTarget | None:
        # No process-name lookup: this runs before every guarded action.
        if not hwnd:
            return None
        return WindowTarget(handle=hwnd, title=window_text(hwnd), window_class=window_class(hwnd),
                            pid=window_pid(hwnd))

    def foreground_window(self) -> WindowTarget | None:
        return self._light(_h(GetForegroundWindow()))

    def window_at(self, x: int, y: int) -> WindowTarget | None:
        hwnd = _h(WindowFromPoint(wt.POINT(int(x), int(y))))
        return self._light((_h(GetAncestor(hwnd, GA_ROOT)) or hwnd) if hwnd else 0)

    def is_minimized(self, target: WindowTarget) -> bool:
        return bool(target.handle and IsWindow(target.handle) and IsIconic(target.handle))

    def reacquire(self, target: WindowTarget) -> WindowTarget | None:
        # Without a process name any window could match, and input would go
        # to the wrong app. Refuse rather than guess.
        if not target.process:
            return None
        candidates = [w for w in self.list_windows()
                      if w.process.lower() == target.process.lower()
                      and (not target.window_class or w.window_class == target.window_class)]
        if not candidates:
            return None
        exact = [w for w in candidates if w.title == target.title]
        return (exact or candidates)[0]

    def client_to_screen(self, target: WindowTarget, x: int, y: int) -> tuple[int, int]:
        pt = wt.POINT(x, y)
        ClientToScreen(target.handle, ctypes.byref(pt))
        return pt.x, pt.y

    def screen_to_client(self, target: WindowTarget, x: int, y: int) -> tuple[int, int]:
        pt = wt.POINT(x, y)
        ScreenToClient(target.handle, ctypes.byref(pt))
        return pt.x, pt.y

    def focus_window(self, title_contains: str) -> bool:
        needle = title_contains.lower()
        match = next((w for w in self.list_windows() if needle in w.title.lower()), None)
        if match is None:
            return False
        h = match.handle
        if IsIconic(h):
            ShowWindow(h, SW_RESTORE)
        # Windows only lets the foreground thread hand focus over, so briefly
        # share its input state.
        fg = _h(GetForegroundWindow())
        fg_thread = GetWindowThreadProcessId(fg, None) if fg else 0
        me = GetCurrentThreadId()
        attached = bool(fg_thread and fg_thread != me and AttachThreadInput(me, fg_thread, True))
        try:
            BringWindowToTop(h)
            SetForegroundWindow(h)
        finally:
            if attached:
                AttachThreadInput(me, fg_thread, False)
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if _h(GetForegroundWindow()) == h:
                return True
            time.sleep(0.02)
        return _h(GetForegroundWindow()) == h

    # ---- background ---------------------------------------------------------
    #
    # Input goes to the exact control with SendMessageTimeout. Before each
    # message this thread briefly attaches to the target's input queue and
    # marks the relevant buttons and modifiers as held, because many toolkits
    # (Tk, Swing, most game engines) ask GetKeyState whether a button or Ctrl
    # is really down and drop the message otherwise. The user's own keyboard
    # state is never touched: only the target thread's queue is shared.

    def _deliver(self, hwnd: int, msg: int, wparam: int, lparam: int) -> None:
        result = ctypes.c_size_t()
        if SendMessageTimeoutW(hwnd, msg, wparam, wt.LPARAM(lparam).value, SMTO_ABORTIFHUNG,
                               SEND_TIMEOUT_MS, ctypes.byref(result)):
            return
        err = ctypes.get_last_error()
        if err == ERROR_ACCESS_DENIED:
            raise TargetDenied(
                "Windows blocked input to this window because it runs with higher privileges. "
                "Run IDB-Macro as administrator to control it.")
        if err == ERROR_INVALID_WINDOW_HANDLE or not IsWindow(hwnd):
            raise TargetLost("The target window closed.")
        if err in (0, ERROR_TIMEOUT):
            # A busy or hung app; drop this one event rather than stall the run.
            return
        raise BackendError(f"Could not send input to the window (error {err}).")

    @contextlib.contextmanager
    def _held_state(self, root: int, vks: set[int]) -> Iterator[None]:
        tid = GetWindowThreadProcessId(root, None)
        me = GetCurrentThreadId()
        if not tid or tid == me or not AttachThreadInput(me, tid, True):
            yield
            return
        saved = KeyState()
        GetKeyboardState(saved)
        state = KeyState(*saved)
        for vk in (0x01, 0x02, 0x04, 0x05, 0x06, 0x10, 0x11, 0x12, *GENERIC_VK):
            state[vk] &= 0x7F
        for vk in vks:
            state[vk] |= 0x80
            if vk in GENERIC_VK:
                state[GENERIC_VK[vk]] |= 0x80
        SetKeyboardState(state)
        try:
            yield
        finally:
            SetKeyboardState(saved)
            AttachThreadInput(me, tid, False)

    def _root(self, target: WindowTarget) -> int:
        return self.ensure_target(target).handle

    def _resolve(self, root: int, point: TargetPoint) -> tuple[int, int, int]:
        """Find the control under ``point`` and the point in its client space."""
        child = point.child
        if child and IsWindow(child) and _h(GetAncestor(child, GA_ROOT)) == root:
            return child, point.cx, point.cy
        hwnd, pt = root, wt.POINT(point.x, point.y)
        for _ in range(32):
            nxt = _h(ChildWindowFromPointEx(hwnd, pt, CWP_SKIPINVISIBLE | CWP_SKIPTRANSPARENT))
            if not nxt or nxt == hwnd:
                break
            MapWindowPoints(hwnd, nxt, ctypes.byref(pt), 1)
            hwnd = nxt
        return hwnd, pt.x, pt.y

    def _spoof_focus(self, root: int, hwnd: int) -> None:
        # Many toolkits drop input while they think they are in the background.
        self._deliver(root, WM_ACTIVATEAPP, 1, 0)
        self._deliver(root, WM_NCACTIVATE, 1, 0)
        self._deliver(root, WM_ACTIVATE, 1, 0)
        self._deliver(hwnd, WM_SETFOCUS, 0, 0)

    def bg_mouse(self, target: WindowTarget, point: TargetPoint, button: str,
                 action: str, count: int = 1, spoof_focus: bool = False) -> None:
        root = self._root(target)
        hwnd, x, y = self._resolve(root, point)
        if spoof_focus:
            self._spoof_focus(root, hwnd)
        lp = _make_lparam(x, y)
        down, up, dbl, mk, xbtn = BUTTON_MESSAGES[button]
        vk = BUTTON_VK[button]
        w_down, w_up = mk | (xbtn << 16), xbtn << 16

        if action == "move":
            with self._held_state(root, set()):
                self._deliver(hwnd, WM_MOUSEMOVE, 0, lp)
            return
        if action == "up":
            with self._held_state(root, set()):
                self._deliver(hwnd, up, w_up, lp)
            return

        with self._held_state(root, set()):
            self._deliver(hwnd, WM_MOUSEMOVE, 0, lp)
        presses = count if action == "click" else 1
        for i in range(presses):
            with self._held_state(root, {vk}):
                self._deliver(hwnd, dbl if i else down, w_down, lp)
            if action == "click":
                with self._held_state(root, set()):
                    self._deliver(hwnd, up, w_up, lp)

    def bg_scroll(self, target: WindowTarget, point: TargetPoint, amount: int, horizontal: bool = False,
                  spoof_focus: bool = False) -> None:
        root = self._root(target)
        hwnd, x, y = self._resolve(root, point)
        if spoof_focus:
            self._spoof_focus(root, hwnd)
        pt = wt.POINT(x, y)
        ClientToScreen(hwnd, ctypes.byref(pt))  # wheel messages use screen coordinates
        delta = (amount * WHEEL_DELTA) & 0xFFFF
        with self._held_state(root, set()):
            self._deliver(hwnd, WM_MOUSEHWHEEL if horizontal else WM_MOUSEWHEEL, delta << 16,
                          _make_lparam(pt.x, pt.y))

    def _key_window(self, root: int, target: WindowTarget) -> int:
        tid = GetWindowThreadProcessId(root, None)
        info = GUITHREADINFO(cbSize=ctypes.sizeof(GUITHREADINFO))
        if GetGUIThreadInfo(tid, ctypes.byref(info)):
            focus = _h(info.hwndFocus)
            if focus and _h(GetAncestor(focus, GA_ROOT)) == root:
                return focus
        if target.child and IsWindow(target.child) and _h(GetAncestor(target.child, GA_ROOT)) == root:
            return target.child
        return root

    def bg_key(self, target: WindowTarget, key: str, down: bool,
               held: tuple[str, ...] = (), spoof_focus: bool = False) -> None:
        root = self._root(target)
        active = _h(GetForegroundWindow()) == root and not IsIconic(root)
        if (down and active) or (not down and key in self._real_keys):
            # Windows ignores synthetic key state for the active window, but
            # real input reaches it. A minimized window can still be the
            # foreground one and gets no real keys. Keys pressed this way are
            # released this way even if focus moves in between.
            if down:
                self.key_down(key)
                self._real_keys.add(key)
            else:
                self.key_up(key)
                self._real_keys.discard(key)
            return
        hwnd = self._key_window(root, target)
        if spoof_focus and down:
            self._spoof_focus(root, hwnd)
        vk = WIN_VK[key]
        sc = MapVirtualKeyW(vk, MAPVK_VK_TO_VSC_EX)
        extended = (sc >> 8) in (0xE0, 0xE1) or key in WIN_EXTENDED
        alt = key in ("alt", "ralt") or any(k in ("alt", "ralt") for k in held)
        system = alt and not any(k in ("ctrl", "rctrl") for k in held)
        lparam = 1 | ((sc & 0xFF) << 16) | (int(extended) << 24) | (int(alt) << 29)
        vks = {WIN_VK[k] for k in held}
        if down:
            vks.add(vk)
            msg = WM_SYSKEYDOWN if system else WM_KEYDOWN
        else:
            msg = WM_SYSKEYUP if system else WM_KEYUP
            lparam |= (1 << 30) | (1 << 31)
        # Posted like real keyboard input, so the app's own TranslateMessage
        # produces the character (with the held modifiers applied). The held
        # state stays in place until the app has processed the key.
        with self._held_state(root, vks):
            self._post(hwnd, msg, vk, lparam)
            self._wait_processed(hwnd)

    def _post(self, hwnd: int, msg: int, wparam: int, lparam: int) -> None:
        if PostMessageW(hwnd, msg, wparam, wt.LPARAM(lparam).value):
            return
        err = ctypes.get_last_error()
        if err == ERROR_ACCESS_DENIED:
            raise TargetDenied(
                "Windows blocked input to this window because it runs with higher privileges. "
                "Run IDB-Macro as administrator to control it.")
        if err == ERROR_INVALID_WINDOW_HANDLE or not IsWindow(hwnd):
            raise TargetLost("The target window closed.")
        raise BackendError(f"Could not send input to the window (error {err}).")

    def _wait_processed(self, hwnd: int) -> None:
        # A thread handles sent messages before posted ones on each pump, so
        # the second round trip only returns once the posted key was taken
        # off the queue and dispatched.
        self._deliver(hwnd, WM_NULL, 0, 0)
        self._deliver(hwnd, WM_NULL, 0, 0)

    def bg_text(self, target: WindowTarget, text: str, spoof_focus: bool = False) -> None:
        root = self._root(target)
        hwnd = self._key_window(root, target)
        if spoof_focus:
            self._spoof_focus(root, hwnd)
        data = text.replace("\r\n", "\n").replace("\n", "\r").encode("utf-16-le")
        with self._held_state(root, set()):
            for i in range(0, len(data), 2):
                self._deliver(hwnd, WM_CHAR, int.from_bytes(data[i:i + 2], "little"), 1)

    @contextlib.contextmanager
    def session(self) -> Iterator[None]:
        with high_resolution_timer():
            yield
