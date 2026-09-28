"""Smart-mode presets: ready-made settings for common uses, and tips about the current setup."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from .keys import parse_combo
from .models import ClickerConfig, KeyRepeaterConfig, RunLimit


@dataclass(frozen=True)
class Preset:
    key: str
    name: str
    description: str
    changes: dict = field(default_factory=dict)


CLICKER_PRESETS = [
    Preset("game", "Roblox & games",
           "Clicks every game registers: each click is held for 25 ms, 8 per second, slightly irregular.",
           {"action": "hold", "hold_ms": 25.0, "interval_ms": 125.0, "jitter_ms": 15.0}),
    Preset("idle", "Clicker games",
           "Fast clicking for idle and clicker games, 25 per second.",
           {"action": "single", "interval_ms": 40.0, "jitter_ms": 4.0}),
    Preset("human", "Human-like",
           "Irregular timing and a little wobble in position, like a person clicking.",
           {"action": "single", "interval_ms": 220.0, "jitter_ms": 90.0, "position_jitter_px": 4}),
    Preset("background", "Background farming",
           "Slow, steady clicks into a window you pick, which can stay behind other windows.",
           {"action": "single", "location": "window", "interval_ms": 1000.0, "jitter_ms": 150.0,
            "spoof_focus": True}),
    Preset("trial", "Safe test run",
           "20 slow clicks, then it stops by itself. Good for checking a new setup.",
           {"action": "single", "interval_ms": 500.0, "jitter_ms": 0.0, "limit": RunLimit("count", 20, 60.0)}),
]

KEY_PRESETS = [
    Preset("game", "Roblox & games",
           "Presses games register: each held for 50 ms, 5 per second, slightly irregular.",
           {"action": "tap", "hold_ms": 50.0, "interval_ms": 200.0, "jitter_ms": 30.0}),
    Preset("walk", "Hold to walk",
           "Holds W down until you stop, for auto-running. It's released while you're in another app.",
           {"action": "hold", "keys": ["w"], "interval_ms": 100.0}),
    Preset("afk", "Anti-AFK",
           "Jumps about every 45 seconds at random moments so you aren't kicked for being idle.",
           {"action": "tap", "keys": ["space"], "hold_ms": 80.0, "interval_ms": 45000.0, "jitter_ms": 15000.0}),
    Preset("apps", "Normal apps",
           "Quick presses for regular programs and text fields, 10 per second.",
           {"action": "tap", "hold_ms": 15.0, "interval_ms": 100.0, "jitter_ms": 0.0}),
    Preset("background", "Background app",
           "Sends keys to a window you pick while you keep working elsewhere.",
           {"action": "tap", "target": "window", "hold_ms": 40.0, "interval_ms": 500.0, "spoof_focus": True}),
]


def apply_preset(config: ClickerConfig | KeyRepeaterConfig, preset: Preset):
    """Return a copy of ``config`` with the preset's settings; everything else is kept."""
    result = copy.deepcopy(config)
    for name, value in preset.changes.items():
        setattr(result, name, copy.deepcopy(value))
    return result


def _chromium_minimized(backend, window) -> bool:
    try:
        return (window is not None and window.window_class.startswith("Chrome_WidgetWin")
                and backend.is_minimized(window))
    except Exception:
        return False


def clicker_tips(cfg: ClickerConfig, backend=None) -> list[str]:
    tips = []
    if cfg.interval_ms < 10:
        tips.append("Clicks are under 10 ms apart. Many apps and games drop input that fast.")
    if cfg.action != "hold" and cfg.location != "window":
        tips.append("If a game ignores some clicks, choose Hold with 20–40 ms. Games that check the mouse once "
                    "per frame can miss instant clicks.")
    if cfg.action == "hold" and cfg.hold_ms >= cfg.interval_ms:
        tips.append("Each click is held as long as the gap between clicks, so the button will look held down.")
    if cfg.location == "window" and (cfg.window is None or not cfg.points):
        tips.append("Pick the window and the spot to click before starting.")
    if cfg.location == "window" and backend is not None and _chromium_minimized(backend, cfg.window):
        tips.append("The target is minimized. Discord, browsers and other Chromium apps ignore input while "
                    "minimized; leave the window open behind others.")
    if cfg.limit.mode == "forever" and cfg.interval_ms < 50:
        tips.append("This runs until you stop it. Set a stop condition if you'll walk away. F12 stops "
                    "everything.")
    if cfg.location == "points" and not cfg.restore_cursor:
        tips.append("Your cursor will be left on the last spot. Turn on “Put the cursor back” to keep working "
                    "while it clicks.")
    return tips


def keys_tips(cfg: KeyRepeaterConfig, backend=None) -> list[str]:
    tips = []
    if cfg.action == "tap" and cfg.hold_ms < 30:
        tips.append("Presses shorter than 30 ms can be missed by games, which check keys once per frame.")
    if cfg.action == "tap" and cfg.hold_ms >= cfg.interval_ms:
        tips.append("Each press lasts as long as the gap, so the key will look held down.")
    if cfg.target == "window" and cfg.window is None:
        tips.append("Pick the window that should receive the keys before starting.")
    if cfg.target == "window" and backend is not None and _chromium_minimized(backend, cfg.window):
        tips.append("The target is minimized. Discord, browsers and other Chromium apps ignore input while "
                    "minimized; leave the window open behind others.")
    risky = {("enter",), ("t",), ("/",), ("alt", "f4"), ("win",)}
    pressed = set()
    for text in cfg.keys:
        try:
            pressed.add(parse_combo(text))
        except ValueError:
            continue
    if pressed & {("enter",), ("t",), ("/",)} and cfg.target == "foreground":
        tips.append("Enter, T and / open the chat in many games, so the repeated key may end up typed into chat.")
    if pressed & (risky - {("enter",), ("t",), ("/",)}):
        tips.append("Alt + F4 and Win close windows or open the Start menu. Double-check you want to repeat them.")
    if cfg.action == "hold" and cfg.target == "foreground":
        tips.append("With smart mode on, held keys are released while another app is active.")
    return tips
