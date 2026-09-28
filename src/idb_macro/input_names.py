"""Translate pynput key and button objects into the app's canonical names."""

from __future__ import annotations

import sys

from pynput import keyboard, mouse

from .core.keys import KNOWN_KEYS, WIN_VK, X_KEYSYM, char_to_combo

_SPECIAL = {
    "ctrl": "ctrl", "ctrl_l": "ctrl", "ctrl_r": "ctrl",
    "shift": "shift", "shift_l": "shift", "shift_r": "shift",
    "alt": "alt", "alt_l": "alt", "alt_r": "alt", "alt_gr": "alt",
    "cmd": "win", "cmd_l": "win", "cmd_r": "win",
    "enter": "enter", "esc": "esc", "space": "space", "tab": "tab",
    "backspace": "backspace", "delete": "delete", "insert": "insert",
    "home": "home", "end": "end", "page_up": "pageup", "page_down": "pagedown",
    "up": "up", "down": "down", "left": "left", "right": "right",
    "caps_lock": "capslock", "num_lock": "numlock", "scroll_lock": "scrolllock",
    "print_screen": "printscreen", "pause": "pause", "menu": "menu",
    "media_volume_up": "volumeup", "media_volume_down": "volumedown",
    "media_volume_mute": "volumemute", "media_play_pause": "playpause",
    "media_next": "nexttrack", "media_previous": "prevtrack",
}

# Windows VK -> name, preferring generic modifier names.
_VK_NAMES = {vk: name for name, vk in WIN_VK.items() if name not in ("rctrl", "rshift", "ralt")}
_VK_NAMES.update({0x10: "shift", 0x11: "ctrl", 0x12: "alt", 0xA1: "shift", 0xA3: "ctrl", 0xA5: "alt", 0x5C: "win"})

_keysym_names: dict[int, str] | None = None


def _x_keysym_names() -> dict[int, str]:
    global _keysym_names
    if _keysym_names is None:
        _keysym_names = {}
        try:
            from Xlib import XK

            XK.load_keysym_group("xf86")
            for name, sym_name in X_KEYSYM.items():
                sym = XK.string_to_keysym(sym_name)
                if sym and name not in ("rctrl", "rshift", "ralt"):
                    _keysym_names.setdefault(sym, name)
        except ImportError:
            pass
    return _keysym_names


def key_name(key) -> str | None:
    """Canonical name for a pynput key, or None if it has no equivalent."""
    if key is None:
        return None
    if isinstance(key, keyboard.Key):
        name = key.name
        if name.startswith("f") and name[1:].isdigit():
            return name if name in KNOWN_KEYS else None
        return _SPECIAL.get(name)
    vk = getattr(key, "vk", None)
    if sys.platform == "win32" and vk is not None:
        return _VK_NAMES.get(vk)
    if vk is not None and vk in _x_keysym_names():
        return _x_keysym_names()[vk]
    ch = getattr(key, "char", None)
    if ch:
        if ch.lower() in KNOWN_KEYS and len(ch) == 1:
            return ch.lower()
        combo = char_to_combo(ch)
        if combo:
            return combo[-1]
    return None


def button_name(button) -> str | None:
    name = getattr(button, "name", "")
    if name in ("left", "right", "middle", "x1", "x2"):
        return name
    if name == "button8":
        return "x1"
    if name == "button9":
        return "x2"
    return None


__all__ = ["key_name", "button_name", "keyboard", "mouse"]
