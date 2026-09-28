"""Configuration and macro data, with strict validation of anything loaded from disk.

Macro files are shareable, so every loader here treats its input as untrusted:
unknown fields are dropped, numbers are range-checked and sizes are capped.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from .keys import KeyComboError, format_combo, parse_combo
from .timing import MAX_INTERVAL_MS, MIN_INTERVAL_MS

FORMAT_ID = "idb-macro"
FORMAT_VERSION = 1

BUTTONS = ("left", "right", "middle", "x1", "x2")
MAX_STEPS = 10_000
MAX_MACROS = 500
MAX_TEXT = 10_000
MAX_NAME = 100
MAX_POINTS = 100
MAX_KEYS = 32
MAX_ARGS = 64
MAX_PATH = 1024
MAX_COORD = 1_000_000
MAX_WAIT_MS = 24 * 60 * 60 * 1000


class ValidationError(ValueError):
    pass


# --------------------------------------------------------------------- helpers

def _num(d: dict, key: str, default: float, lo: float, hi: float, integer: bool = False) -> float | int:
    value = d.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{key} must be a number")
    if not math.isfinite(value):
        raise ValidationError(f"{key} must be finite")
    if value < lo or value > hi:
        raise ValidationError(f"{key} must be between {lo} and {hi}")
    return int(value) if integer else float(value)


def _int(d: dict, key: str, default: int, lo: int, hi: int) -> int:
    return int(_num(d, key, default, lo, hi, integer=True))


def _bool(d: dict, key: str, default: bool) -> bool:
    value = d.get(key, default)
    if not isinstance(value, bool):
        raise ValidationError(f"{key} must be true or false")
    return value


def _str(d: dict, key: str, default: str, max_len: int) -> str:
    value = d.get(key, default)
    if not isinstance(value, str):
        raise ValidationError(f"{key} must be text")
    if len(value) > max_len:
        raise ValidationError(f"{key} is longer than {max_len} characters")
    if "\x00" in value:
        raise ValidationError(f"{key} contains a NUL character")
    return value


def _choice(d: dict, key: str, default: str, choices: tuple[str, ...]) -> str:
    value = d.get(key, default)
    if value not in choices:
        raise ValidationError(f"{key} must be one of {', '.join(choices)}")
    return value


def _combo(value: Any, allow_empty: bool = False) -> str:
    if allow_empty and value in ("", None):
        return ""
    if not isinstance(value, str):
        raise ValidationError("key combo must be text")
    try:
        return format_combo(parse_combo(value))
    except KeyComboError as exc:
        raise ValidationError(str(exc)) from None


def _dict(value: Any, what: str) -> dict:
    if not isinstance(value, dict):
        raise ValidationError(f"{what} must be an object")
    return value


def _list(value: Any, what: str, max_len: int) -> list:
    if not isinstance(value, list):
        raise ValidationError(f"{what} must be a list")
    if len(value) > max_len:
        raise ValidationError(f"{what} has more than {max_len} entries")
    return value


# ---------------------------------------------------------------- shared parts

@dataclass
class TargetPoint:
    """A click position.

    ``x``/``y`` are screen coordinates in foreground mode and client
    coordinates of the target window in background mode.  ``child``/``cx``/
    ``cy`` remember the exact control that was under the point when it was
    picked, which keeps background clicks accurate while the window is
    minimized.
    """

    x: int = 0
    y: int = 0
    child: int = 0
    cx: int = 0
    cy: int = 0

    @classmethod
    def from_dict(cls, d: Any) -> TargetPoint:
        d = _dict(d, "point")
        return cls(
            x=_int(d, "x", 0, -MAX_COORD, MAX_COORD),
            y=_int(d, "y", 0, -MAX_COORD, MAX_COORD),
            child=_int(d, "child", 0, 0, 2**64 - 1),
            cx=_int(d, "cx", 0, -MAX_COORD, MAX_COORD),
            cy=_int(d, "cy", 0, -MAX_COORD, MAX_COORD),
        )


@dataclass
class WindowTarget:
    """A window picked for background input.

    ``handle`` is only valid while that window exists.  ``process``,
    ``window_class`` and ``title`` let the backend find the window again after
    the app restarts.
    """

    handle: int = 0
    title: str = ""
    process: str = ""
    window_class: str = ""
    pid: int = 0
    # Control that gets keyboard input when the window's own focus is unknown.
    child: int = 0

    def describe(self) -> str:
        name = self.title or self.window_class or "window"
        return f"{name} ({self.process})" if self.process else name

    @classmethod
    def from_dict(cls, d: Any) -> WindowTarget | None:
        if d is None:
            return None
        d = _dict(d, "window")
        return cls(
            handle=_int(d, "handle", 0, 0, 2**64 - 1),
            title=_str(d, "title", "", 512),
            process=_str(d, "process", "", 260),
            window_class=_str(d, "window_class", "", 256),
            pid=_int(d, "pid", 0, 0, 2**32 - 1),
            child=_int(d, "child", 0, 0, 2**64 - 1),
        )


LIMIT_MODES = ("forever", "count", "duration")


@dataclass
class RunLimit:
    mode: str = "forever"
    count: int = 100
    seconds: float = 60.0

    @classmethod
    def from_dict(cls, d: Any) -> RunLimit:
        d = _dict(d if d is not None else {}, "limit")
        return cls(
            mode=_choice(d, "mode", "forever", LIMIT_MODES),
            count=_int(d, "count", 100, 1, 10**9),
            seconds=_num(d, "seconds", 60.0, 0.1, 7 * 24 * 3600),
        )


# ----------------------------------------------------------------- autoclicker

CLICK_ACTIONS = ("single", "double", "triple", "hold")
LOCATIONS = ("cursor", "points", "window")


@dataclass
class ClickerConfig:
    button: str = "left"
    action: str = "single"
    hold_ms: float = 50.0
    interval_ms: float = 100.0
    jitter_ms: float = 0.0
    limit: RunLimit = field(default_factory=RunLimit)
    location: str = "cursor"
    points: list[TargetPoint] = field(default_factory=list)
    position_jitter_px: int = 0
    restore_cursor: bool = True
    window: WindowTarget | None = None
    spoof_focus: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Any) -> ClickerConfig:
        d = _dict(d, "clicker")
        return cls(
            button=_choice(d, "button", "left", BUTTONS),
            action=_choice(d, "action", "single", CLICK_ACTIONS),
            hold_ms=_num(d, "hold_ms", 50.0, 0, MAX_WAIT_MS),
            interval_ms=_num(d, "interval_ms", 100.0, MIN_INTERVAL_MS, MAX_INTERVAL_MS),
            jitter_ms=_num(d, "jitter_ms", 0.0, 0, MAX_INTERVAL_MS),
            limit=RunLimit.from_dict(d.get("limit")),
            location=_choice(d, "location", "cursor", LOCATIONS),
            points=[TargetPoint.from_dict(p) for p in _list(d.get("points", []), "points", MAX_POINTS)],
            position_jitter_px=_int(d, "position_jitter_px", 0, 0, 500),
            restore_cursor=_bool(d, "restore_cursor", True),
            window=WindowTarget.from_dict(d.get("window")),
            spoof_focus=_bool(d, "spoof_focus", False),
        )


# ---------------------------------------------------------------- key repeater

KEY_ACTIONS = ("tap", "hold")
KEY_SEQUENCES = ("cycle", "together")
KEY_TARGETS = ("foreground", "window")


@dataclass
class KeyRepeaterConfig:
    keys: list[str] = field(default_factory=lambda: ["space"])
    sequence: str = "cycle"
    action: str = "tap"
    # How long each tap holds the key. Games read keys once per frame, so a
    # press shorter than a frame is often never seen.
    hold_ms: float = 40.0
    interval_ms: float = 100.0
    jitter_ms: float = 0.0
    limit: RunLimit = field(default_factory=RunLimit)
    target: str = "foreground"
    window: WindowTarget | None = None
    spoof_focus: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Any) -> KeyRepeaterConfig:
        d = _dict(d, "key repeater")
        keys = [_combo(k) for k in _list(d.get("keys", ["space"]), "keys", MAX_KEYS)]
        if d.get("action") == "hold_tap":  # older name for a tap with a set press length
            d = {**d, "action": "tap"}
        return cls(
            keys=keys,
            sequence=_choice(d, "sequence", "cycle", KEY_SEQUENCES),
            action=_choice(d, "action", "tap", KEY_ACTIONS),
            hold_ms=_num(d, "hold_ms", 40.0, 0, MAX_WAIT_MS),
            interval_ms=_num(d, "interval_ms", 100.0, MIN_INTERVAL_MS, MAX_INTERVAL_MS),
            jitter_ms=_num(d, "jitter_ms", 0.0, 0, MAX_INTERVAL_MS),
            limit=RunLimit.from_dict(d.get("limit")),
            target=_choice(d, "target", "foreground", KEY_TARGETS),
            window=WindowTarget.from_dict(d.get("window")),
            spoof_focus=_bool(d, "spoof_focus", True),
        )


# ---------------------------------------------------------------------- macros

POSITION_MODES = ("cursor", "point")

# Field specs per step type: name -> (kind, default, extra)
#   kind "int"/"float": extra = (lo, hi)
#   kind "choice":      extra = tuple of choices
#   kind "str":         extra = max length
#   kind "combo":       key combo text
#   kind "bool":        extra unused
#   kind "args":        list of strings
_POS = {
    "at": ("choice", "point", POSITION_MODES),
    "x": ("int", 0, (-MAX_COORD, MAX_COORD)),
    "y": ("int", 0, (-MAX_COORD, MAX_COORD)),
    "child": ("int", 0, (0, 2**64 - 1)),
    "cx": ("int", 0, (-MAX_COORD, MAX_COORD)),
    "cy": ("int", 0, (-MAX_COORD, MAX_COORD)),
}

STEP_SPECS: dict[str, dict[str, tuple]] = {
    "click": {"button": ("choice", "left", BUTTONS), "count": ("int", 1, (1, 3)), **_POS},
    "mouse_down": {"button": ("choice", "left", BUTTONS), **_POS},
    "mouse_up": {"button": ("choice", "left", BUTTONS), **_POS},
    "move": {"x": _POS["x"], "y": _POS["y"], "duration_ms": ("int", 0, (0, 60_000))},
    "scroll": {"amount": ("int", -1, (-1000, 1000)), "horizontal": ("bool", False, None), **_POS},
    "key": {"combo": ("combo", "space", None), "hold_ms": ("int", 40, (0, 60_000))},
    "key_down": {"combo": ("combo", "shift", None)},
    "key_up": {"combo": ("combo", "shift", None)},
    "text": {"text": ("str", "", MAX_TEXT), "char_delay_ms": ("int", 0, (0, 10_000))},
    "wait": {"ms": ("int", 500, (0, MAX_WAIT_MS)), "random_ms": ("int", 0, (0, MAX_WAIT_MS))},
    "launch": {"path": ("str", "", MAX_PATH), "args": ("args", [], None)},
    "focus": {"title": ("str", "", 512)},
    # Run a saved Autoclicker / Key Repeater profile, for a set time or until
    # the profile's own stop condition.
    "run_clicker": {"profile": ("id", "", None), "until": ("choice", "time", ("time", "own")),
                    "ms": ("int", 5000, (0, MAX_WAIT_MS))},
    "run_keys": {"profile": ("id", "", None), "until": ("choice", "time", ("time", "own")),
                 "ms": ("int", 5000, (0, MAX_WAIT_MS))},
}

# Which tool's profiles a profile step runs.
PROFILE_STEPS = {"run_clicker": "clicker", "run_keys": "keys"}

STEP_LABELS = {
    "click": "Click",
    "mouse_down": "Mouse down",
    "mouse_up": "Mouse up",
    "move": "Move mouse",
    "scroll": "Scroll",
    "key": "Press keys",
    "key_down": "Key down",
    "key_up": "Key up",
    "text": "Type text",
    "wait": "Wait",
    "launch": "Launch program",
    "focus": "Focus window",
    "run_clicker": "Run autoclicker profile",
    "run_keys": "Run key repeater profile",
}

# Step types that only make sense with real (foreground) input.
FOREGROUND_ONLY_STEPS = frozenset({"move", "focus"})


def _validate_field(name: str, spec: tuple, value: Any) -> Any:
    kind, default, extra = spec
    holder = {name: value}
    if kind == "int":
        return _int(holder, name, default, *extra)
    if kind == "float":
        return _num(holder, name, default, *extra)
    if kind == "choice":
        return _choice(holder, name, default, extra)
    if kind == "str":
        return _str(holder, name, default, extra)
    if kind == "bool":
        return _bool(holder, name, default)
    if kind == "combo":
        return _combo(value)
    if kind == "args":
        items = _list(value, name, MAX_ARGS)
        return [_str({"arg": a}, "arg", "", MAX_PATH) for a in items]
    if kind == "id":
        if not isinstance(value, str) or len(value) > 64 or not all(c in "0123456789abcdef" for c in value):
            raise ValidationError(f"{name} is not a valid id")
        return value
    raise AssertionError(kind)


@dataclass
class Step:
    type: str
    params: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    note: str = ""

    @classmethod
    def new(cls, step_type: str, **params: Any) -> Step:
        if step_type not in STEP_SPECS:
            raise ValidationError(f"unknown step type: {step_type!r}")
        spec = STEP_SPECS[step_type]
        full = {k: (list(v[1]) if isinstance(v[1], list) else v[1]) for k, v in spec.items()}
        full.update(params)
        return cls.from_dict({"type": step_type, "params": full})

    def get(self, key: str) -> Any:
        if key in self.params:
            return self.params[key]
        default = STEP_SPECS[self.type][key][1]
        return list(default) if isinstance(default, list) else default

    def to_dict(self) -> dict:
        return {"type": self.type, "params": dict(self.params), "enabled": self.enabled, "note": self.note}

    @classmethod
    def from_dict(cls, d: Any) -> Step:
        d = _dict(d, "step")
        step_type = d.get("type")
        if step_type not in STEP_SPECS:
            raise ValidationError(f"unknown step type: {step_type!r}")
        spec = STEP_SPECS[step_type]
        raw = _dict(d.get("params", {}), "params")
        params = {}
        for name, field_spec in spec.items():
            value = raw.get(name, field_spec[1])
            params[name] = _validate_field(name, field_spec, value)
        return cls(
            type=step_type,
            params=params,
            enabled=_bool(d, "enabled", True),
            note=_str(d, "note", "", 200),
        )

    def summary(self, profile_names: dict[str, str] | None = None) -> str:
        """One-line description for the step list."""
        t, g = self.type, self.get

        def where() -> str:
            return "at cursor" if g("at") == "cursor" else f"at ({g('x')}, {g('y')})"

        if t == "click":
            times = {1: "", 2: " double", 3: " triple"}[g("count")]
            return f"{g('button').title()}{times} click {where()}"
        if t in ("mouse_down", "mouse_up"):
            return f"{g('button').title()} button {'down' if t == 'mouse_down' else 'up'} {where()}"
        if t == "move":
            glide = f" over {g('duration_ms')} ms" if g("duration_ms") else ""
            return f"Move to ({g('x')}, {g('y')}){glide}"
        if t == "scroll":
            positive = g("amount") > 0
            if g("horizontal"):
                direction = "right" if positive else "left"
            else:
                direction = "up" if positive else "down"
            return f"Scroll {direction} {abs(g('amount'))} {where()}"
        if t in ("key", "key_down", "key_up"):
            from .keys import display_combo

            verb = {"key": "Press", "key_down": "Hold", "key_up": "Release"}[t]
            return f"{verb} {display_combo(g('combo'))}"
        if t == "text":
            text = g("text").replace("\n", "⏎")
            return f'Type "{text[:40]}{"…" if len(text) > 40 else ""}"'
        if t == "wait":
            extra = f" (+0–{g('random_ms')} ms)" if g("random_ms") else ""
            return f"Wait {g('ms')} ms{extra}"
        if t == "launch":
            return f"Launch {g('path') or '(no program)'}"
        if t == "focus":
            return f'Focus window "{g("title")}"'
        if t in PROFILE_STEPS:
            tool = "autoclicker" if t == "run_clicker" else "key repeater"
            name = (profile_names or {}).get(g("profile"))
            what = f'{tool} "{name}"' if name else f"{tool} (profile missing)"
            how = f"for {g('ms') / 1000:g} s" if g("until") == "time" else "until it stops"
            return f"Run {what} {how}"
        return t


@dataclass
class Macro:
    name: str = "New macro"
    steps: list[Step] = field(default_factory=list)
    repeat: int = 1
    speed: float = 1.0
    hotkey: str = ""
    target: str = "foreground"
    window: WindowTarget | None = None
    spoof_focus: bool = True
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "repeat": self.repeat,
            "speed": self.speed,
            "hotkey": self.hotkey,
            "target": self.target,
            "window": asdict(self.window) if self.window else None,
            "spoof_focus": self.spoof_focus,
            "steps": [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, d: Any) -> Macro:
        d = _dict(d, "macro")
        macro_id = _str(d, "id", "", 64) or uuid.uuid4().hex
        if not all(c in "0123456789abcdef" for c in macro_id):
            macro_id = uuid.uuid4().hex
        return cls(
            id=macro_id,
            name=_str(d, "name", "Macro", MAX_NAME).strip() or "Macro",
            repeat=_int(d, "repeat", 1, 0, 10**9),
            speed=_num(d, "speed", 1.0, 0.1, 20.0),
            hotkey=_combo(d.get("hotkey", ""), allow_empty=True),
            target=_choice(d, "target", "foreground", KEY_TARGETS),
            window=WindowTarget.from_dict(d.get("window")),
            spoof_focus=_bool(d, "spoof_focus", True),
            steps=[Step.from_dict(s) for s in _list(d.get("steps", []), "steps", MAX_STEPS)],
        )

    def launch_steps(self) -> list[Step]:
        return [s for s in self.steps if s.type == "launch"]


def macros_to_document(macros: list[Macro]) -> dict:
    return {"format": FORMAT_ID, "version": FORMAT_VERSION, "macros": [m.to_dict() for m in macros]}


def macros_from_document(doc: Any) -> list[Macro]:
    doc = _dict(doc, "file")
    if doc.get("format") != FORMAT_ID:
        raise ValidationError("this is not an I-DB Macro file")
    version = doc.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version > FORMAT_VERSION:
        raise ValidationError("this file was made by a newer version of I-DB Macro")
    return [Macro.from_dict(m) for m in _list(doc.get("macros", []), "macros", MAX_MACROS)]
