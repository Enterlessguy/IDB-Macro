"""Canonical key names, combo parsing, and the per-platform key tables."""

from __future__ import annotations

MODIFIERS = ("ctrl", "shift", "alt", "win")

_LETTERS = {chr(c): 0x41 + i for i, c in enumerate(range(ord("a"), ord("z") + 1))}
_DIGITS = {str(d): 0x30 + d for d in range(10)}
_FKEYS = {f"f{n}": 0x6F + n for n in range(1, 25)}
_NUMPAD = {f"num{d}": 0x60 + d for d in range(10)}

# Windows virtual-key codes. Left-hand modifiers are used so that games which
# distinguish sides see the common physical key.
WIN_VK: dict[str, int] = {
    **_LETTERS,
    **_DIGITS,
    **_FKEYS,
    **_NUMPAD,
    "ctrl": 0xA2, "shift": 0xA0, "alt": 0xA4, "win": 0x5B,
    "rctrl": 0xA3, "rshift": 0xA1, "ralt": 0xA5,
    "enter": 0x0D, "esc": 0x1B, "space": 0x20, "tab": 0x09,
    "backspace": 0x08, "delete": 0x2E, "insert": 0x2D,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "capslock": 0x14, "numlock": 0x90, "scrolllock": 0x91,
    "printscreen": 0x2C, "pause": 0x13, "menu": 0x5D,
    "nummul": 0x6A, "numadd": 0x6B, "numsub": 0x6D, "numdec": 0x6E, "numdiv": 0x6F,
    "`": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, "\\": 0xDC,
    ";": 0xBA, "'": 0xDE, ",": 0xBC, ".": 0xBE, "/": 0xBF,
    "volumeup": 0xAF, "volumedown": 0xAE, "volumemute": 0xAD,
    "playpause": 0xB3, "nexttrack": 0xB0, "prevtrack": 0xB1, "stopmedia": 0xB2,
}

# Windows keys whose scan code needs KEYEVENTF_EXTENDEDKEY / lParam bit 24.
WIN_EXTENDED = frozenset({
    "rctrl", "ralt", "win", "insert", "delete", "home", "end", "pageup",
    "pagedown", "up", "down", "left", "right", "numlock", "printscreen",
    "numdiv", "menu",
})

# X11 keysym names.
X_KEYSYM: dict[str, str] = {
    **{k: k for k in _LETTERS},
    **{k: k for k in _DIGITS},
    **{k: k.upper() for k in _FKEYS},
    **{f"num{d}": f"KP_{d}" for d in range(10)},
    "ctrl": "Control_L", "shift": "Shift_L", "alt": "Alt_L", "win": "Super_L",
    "rctrl": "Control_R", "rshift": "Shift_R", "ralt": "Alt_R",
    "enter": "Return", "esc": "Escape", "space": "space", "tab": "Tab",
    "backspace": "BackSpace", "delete": "Delete", "insert": "Insert",
    "home": "Home", "end": "End", "pageup": "Prior", "pagedown": "Next",
    "up": "Up", "down": "Down", "left": "Left", "right": "Right",
    "capslock": "Caps_Lock", "numlock": "Num_Lock", "scrolllock": "Scroll_Lock",
    "printscreen": "Print", "pause": "Pause", "menu": "Menu",
    "nummul": "KP_Multiply", "numadd": "KP_Add", "numsub": "KP_Subtract",
    "numdec": "KP_Decimal", "numdiv": "KP_Divide",
    "`": "grave", "-": "minus", "=": "equal", "[": "bracketleft",
    "]": "bracketright", "\\": "backslash", ";": "semicolon",
    "'": "apostrophe", ",": "comma", ".": "period", "/": "slash",
    "volumeup": "XF86_AudioRaiseVolume", "volumedown": "XF86_AudioLowerVolume",
    "volumemute": "XF86_AudioMute", "playpause": "XF86_AudioPlay",
    "nexttrack": "XF86_AudioNext", "prevtrack": "XF86_AudioPrev",
    "stopmedia": "XF86_AudioStop",
}

KNOWN_KEYS = frozenset(WIN_VK)

ALIASES = {
    "control": "ctrl", "lctrl": "ctrl", "ctl": "ctrl",
    "lshift": "shift", "lalt": "alt", "option": "alt", "altgr": "ralt",
    "cmd": "win", "super": "win", "meta": "win", "windows": "win", "lwin": "win",
    "return": "enter", "escape": "esc", "spacebar": "space",
    "del": "delete", "ins": "insert", "pgup": "pageup", "pgdn": "pagedown",
    "pagedn": "pagedown", "bksp": "backspace", "caps": "capslock",
    "prtsc": "printscreen", "print": "printscreen",
    "plus": "=", "minus": "-", "equals": "=", "comma": ",", "period": ".",
    "slash": "/", "backslash": "\\", "semicolon": ";", "quote": "'",
    "grave": "`", "backtick": "`", "tilde": "`",
    "arrowup": "up", "arrowdown": "down", "arrowleft": "left", "arrowright": "right",
}

_DISPLAY = {
    "ctrl": "Ctrl", "shift": "Shift", "alt": "Alt", "win": "Win",
    "rctrl": "Right Ctrl", "rshift": "Right Shift", "ralt": "Right Alt",
    "esc": "Esc", "pageup": "PgUp", "pagedown": "PgDn", "printscreen": "PrtSc",
    "capslock": "Caps Lock", "numlock": "Num Lock", "scrolllock": "Scroll Lock",
    "backspace": "Backspace", "space": "Space",
}

MODIFIER_ORDER = {name: i for i, name in enumerate(MODIFIERS)}


class KeyComboError(ValueError):
    """Raised for an unknown key name or a malformed combo."""


def normalize_key(name: str) -> str:
    """Return the canonical name for one key, or raise ``KeyComboError``."""
    if not isinstance(name, str):
        raise KeyComboError("key name must be text")
    raw = name.strip()
    if raw == "+":
        return "="
    key = raw.lower().replace(" ", "")
    key = ALIASES.get(key, key)
    if key not in KNOWN_KEYS:
        raise KeyComboError(f"unknown key: {name!r}")
    return key


def is_modifier(key: str) -> bool:
    return key in MODIFIERS or key in ("rctrl", "rshift", "ralt")


def parse_combo(text: str) -> tuple[str, ...]:
    """Parse ``"ctrl+shift+s"`` into ``("ctrl", "shift", "s")``.

    Modifiers come first in a fixed order, followed by at most one other key.
    A combo made only of modifiers (for example ``"shift"``) is allowed.
    """
    if not isinstance(text, str) or not text.strip():
        raise KeyComboError("empty key combo")
    raw = text.strip().split("+")
    parts: list[str] = []
    i = 0
    while i < len(raw):
        if raw[i].strip():
            parts.append(raw[i])
            i += 1
        elif i + 1 < len(raw) and not raw[i + 1].strip():
            # Two empty pieces in a row come from a literal "+" key ("ctrl++").
            parts.append("+")
            i += 2
        else:
            raise KeyComboError(f"malformed key combo: {text!r}")
    keys = [normalize_key(p) for p in parts]
    if len(set(keys)) != len(keys):
        raise KeyComboError(f"key repeated in combo: {text!r}")
    mods = sorted((k for k in keys if k in MODIFIERS), key=MODIFIER_ORDER.get)
    others = [k for k in keys if k not in MODIFIERS]
    if len(others) > 1:
        raise KeyComboError(f"a combo can hold only one non-modifier key: {text!r}")
    return tuple(mods + others)


def format_combo(keys: tuple[str, ...] | list[str]) -> str:
    return "+".join(keys)


def display_combo(keys: tuple[str, ...] | list[str] | str) -> str:
    """Human-friendly label such as ``Ctrl + Shift + S``."""
    if isinstance(keys, str):
        keys = parse_combo(keys)
    return " + ".join(_DISPLAY.get(k, k.upper() if len(k) <= 3 else k.title()) for k in keys)


def char_to_combo(ch: str) -> tuple[str, ...] | None:
    """Map a character typed on a US layout to the combo that produces it."""
    shifted = {
        "~": "`", "!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6",
        "&": "7", "*": "8", "(": "9", ")": "0", "_": "-", "+": "=", "{": "[",
        "}": "]", "|": "\\", ":": ";", '"': "'", "<": ",", ">": ".", "?": "/",
    }
    if ch == " ":
        return ("space",)
    if ch in ("\n", "\r"):
        return ("enter",)
    if ch == "\t":
        return ("tab",)
    if ch.isascii() and ch.isalpha():
        return ("shift", ch.lower()) if ch.isupper() else (ch,)
    if ch in shifted:
        return ("shift", shifted[ch])
    if ch in KNOWN_KEYS and len(ch) == 1:
        return (ch,)
    return None
