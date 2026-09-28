"""Foreground-only backend built on pynput, for systems without a native backend."""

from __future__ import annotations

from pynput import keyboard, mouse

from .base import Backend, BackendError

_SPECIAL = {
    "ctrl": "ctrl_l", "rctrl": "ctrl_r", "shift": "shift_l", "rshift": "shift_r",
    "alt": "alt_l", "ralt": "alt_r", "win": "cmd", "enter": "enter", "esc": "esc",
    "space": "space", "tab": "tab", "backspace": "backspace", "delete": "delete",
    "insert": "insert", "home": "home", "end": "end", "pageup": "page_up",
    "pagedown": "page_down", "up": "up", "down": "down", "left": "left", "right": "right",
    "capslock": "caps_lock", "numlock": "num_lock", "scrolllock": "scroll_lock",
    "printscreen": "print_screen", "pause": "pause", "menu": "menu",
    "volumeup": "media_volume_up", "volumedown": "media_volume_down",
    "volumemute": "media_volume_mute", "playpause": "media_play_pause",
    "nexttrack": "media_next", "prevtrack": "media_previous",
}
_NUMPAD_CHARS = {"nummul": "*", "numadd": "+", "numsub": "-", "numdec": ".", "numdiv": "/"}


def _pynput_key(name: str):
    if name.startswith("f") and name[1:].isdigit():
        return getattr(keyboard.Key, name)
    if name in _SPECIAL:
        key = getattr(keyboard.Key, _SPECIAL[name], None)
        if key is None:
            raise BackendError(f"The key {name!r} is not available on this system.")
        return key
    if name.startswith("num") and name[3:].isdigit():
        return keyboard.KeyCode.from_char(name[3:])
    if name in _NUMPAD_CHARS:
        return keyboard.KeyCode.from_char(_NUMPAD_CHARS[name])
    return keyboard.KeyCode.from_char(name)


class FallbackBackend(Backend):
    name = "generic"
    supports_background = False
    notice = ("Background mode is not available on this system. Foreground input may also be "
              "limited (for example on Wayland without XWayland).")

    def __init__(self) -> None:
        self.mouse = mouse.Controller()
        self.keyboard = keyboard.Controller()

    def cursor_pos(self) -> tuple[int, int]:
        x, y = self.mouse.position
        return int(x), int(y)

    def move(self, x: int, y: int) -> None:
        self.mouse.position = (x, y)

    def mouse_down(self, button: str) -> None:
        self.mouse.press(self._button(button))

    def mouse_up(self, button: str) -> None:
        self.mouse.release(self._button(button))

    @staticmethod
    def _button(button: str):
        found = getattr(mouse.Button, button, None)
        if found is None:
            raise BackendError(f"The {button} mouse button is not available on this system.")
        return found

    def scroll(self, amount: int, horizontal: bool = False) -> None:
        self.mouse.scroll(amount if horizontal else 0, 0 if horizontal else amount)

    def key_down(self, key: str) -> None:
        self.keyboard.press(_pynput_key(key))

    def key_up(self, key: str) -> None:
        self.keyboard.release(_pynput_key(key))

    def type_text(self, text: str) -> None:
        self.keyboard.type(text)
