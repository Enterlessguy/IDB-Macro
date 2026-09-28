"""Settings and macro library on disk: atomic writes, corrupt-file recovery."""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .models import (
    PROFILE_STEPS,
    STEP_LABELS,
    ClickerConfig,
    KeyRepeaterConfig,
    Macro,
    ValidationError,
    _bool,
    _combo,
    _dict,
    macros_from_document,
    macros_to_document,
)
from .profiles import (
    TOOLS,
    Profile,
    profiles_from_list,
    profiles_to_document,
    profiles_to_list,
    strip_for_sharing,
    valid_id,
)

log = logging.getLogger(__name__)

APP_DIR_NAME = "IDB-Macro"
MAX_FILE_BYTES = 20 * 1024 * 1024


def config_dir() -> Path:
    override = os.environ.get("IDB_MACRO_CONFIG_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_DIR_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "idb-macro"


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path: Path) -> Any:
    """Read a JSON file with a size cap. Raises ValidationError on bad content."""
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ValidationError(f"{path.name} is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB")
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValidationError(f"{path.name} is not valid JSON: {exc}") from None
    except RecursionError:
        raise ValidationError(f"{path.name} is nested too deeply to be a macro file") from None


def _quarantine(path: Path) -> None:
    """Keep a copy of an unreadable file instead of silently overwriting it."""
    target = path.with_name(f"{path.name}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}")
    try:
        os.replace(path, target)
        log.warning("moved unreadable %s to %s", path.name, target.name)
    except OSError:
        log.warning("could not move unreadable %s aside", path.name)


DEFAULT_HOTKEYS = {
    "clicker": "f6",
    "keys": "f7",
    "macro": "f8",
    "record": "f9",
    "panic": "f12",
}


@dataclass
class Settings:
    hotkeys: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_HOTKEYS))
    show_splash: bool = True
    always_on_top: bool = False
    close_to_tray: bool = True
    failsafe_corner: bool = True
    minimize_while_recording: bool = True
    smart_mode: bool = False
    smart_focus_lock: bool = True
    smart_avoid_shell: bool = True
    dumb_mode: bool = False
    check_updates: bool = True
    clicker: ClickerConfig = field(default_factory=ClickerConfig)
    keys: KeyRepeaterConfig = field(default_factory=KeyRepeaterConfig)
    dumb: ClickerConfig = field(default_factory=ClickerConfig)
    selected_macro: str = ""
    # tool -> id of the profile currently loaded on that page
    selected_profiles: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["clicker"] = self.clicker.to_dict()
        d["keys"] = self.keys.to_dict()
        d["dumb"] = self.dumb.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: Any) -> Settings:
        d = _dict(d, "settings")
        s = cls()
        raw_hotkeys = d.get("hotkeys", {})
        if isinstance(raw_hotkeys, dict):
            for name in DEFAULT_HOTKEYS:
                if name in raw_hotkeys:
                    try:
                        s.hotkeys[name] = _combo(raw_hotkeys[name], allow_empty=True)
                    except ValidationError:
                        pass
        for name in ("show_splash", "always_on_top", "close_to_tray", "failsafe_corner",
                     "minimize_while_recording", "smart_mode", "smart_focus_lock", "smart_avoid_shell",
                     "dumb_mode", "check_updates"):
            try:
                setattr(s, name, _bool(d, name, getattr(s, name)))
            except ValidationError:
                pass
        # A bad tool config should not wipe the rest of the settings.
        try:
            s.clicker = ClickerConfig.from_dict(d.get("clicker", {}))
        except ValidationError as exc:
            log.warning("ignoring saved autoclicker settings: %s", exc)
        try:
            s.keys = KeyRepeaterConfig.from_dict(d.get("keys", {}))
        except ValidationError as exc:
            log.warning("ignoring saved key repeater settings: %s", exc)
        try:
            s.dumb = ClickerConfig.from_dict(d.get("dumb", {}))
        except ValidationError as exc:
            log.warning("ignoring saved dumb mode settings: %s", exc)
        selected = d.get("selected_macro", "")
        s.selected_macro = selected if isinstance(selected, str) and len(selected) <= 64 else ""
        chosen = d.get("selected_profiles", {})
        if isinstance(chosen, dict):
            for tool in TOOLS:
                try:
                    chosen_id = valid_id(chosen.get(tool, ""))
                except ValidationError:
                    continue
                if chosen_id:
                    s.selected_profiles[tool] = chosen_id
        return s


class Store:
    def __init__(self, directory: Path | None = None):
        self.dir = directory or config_dir()
        self.settings_path = self.dir / "settings.json"
        self.macros_path = self.dir / "macros.json"
        self.profiles_path = self.dir / "profiles.json"

    def load_settings(self) -> Settings:
        if not self.settings_path.exists():
            return Settings()
        try:
            return Settings.from_dict(read_json(self.settings_path))
        except (ValidationError, OSError) as exc:
            log.warning("settings unreadable: %s", exc)
            _quarantine(self.settings_path)
            return Settings()

    def save_settings(self, settings: Settings) -> None:
        atomic_write_json(self.settings_path, settings.to_dict())

    def load_macros(self) -> list[Macro]:
        if not self.macros_path.exists():
            return []
        try:
            return macros_from_document(read_json(self.macros_path))
        except (ValidationError, OSError) as exc:
            log.warning("macro library unreadable: %s", exc)
            _quarantine(self.macros_path)
            return []

    def save_macros(self, macros: list[Macro]) -> None:
        atomic_write_json(self.macros_path, macros_to_document(macros))

    def load_profiles(self) -> list[Profile]:
        if not self.profiles_path.exists():
            return []
        try:
            return profiles_from_list(_dict(read_json(self.profiles_path), "file").get("profiles", []))
        except (ValidationError, OSError) as exc:
            log.warning("profile library unreadable: %s", exc)
            _quarantine(self.profiles_path)
            return []

    def save_profiles(self, profiles: list[Profile]) -> None:
        atomic_write_json(self.profiles_path, profiles_to_document(profiles))


def export_macros(path: Path, macros: list[Macro], profiles: list[Profile] | None = None) -> None:
    """Write macros, bundling any profiles their steps run so the file works anywhere."""
    used = {s.get("profile") for m in macros for s in m.steps if s.type in PROFILE_STEPS}
    doc = macros_to_document(macros)
    doc["profiles"] = profiles_to_list([p for p in profiles or [] if p.id in used])
    atomic_write_json(path, doc)


def export_profiles(path: Path, profiles: list[Profile]) -> None:
    atomic_write_json(path, profiles_to_document(profiles))


def import_macros(path: Path) -> list[Macro]:
    return import_bundle(path)[0]


def import_bundle(path: Path) -> tuple[list[Macro], list[Profile]]:
    """Read a shared file: its macros and the profiles they use, safe to add to the library."""
    doc = read_json(path)
    macros = prepare_import(macros_from_document(doc))
    profiles = profiles_from_list(_dict(doc, "file").get("profiles", []))
    remap = strip_for_sharing(profiles)
    for m in macros:
        for step in m.steps:
            if step.type in PROFILE_STEPS:
                step.params["profile"] = remap.get(step.get("profile"), step.get("profile"))
    return macros, profiles


def prepare_import(macros: list[Macro]) -> list[Macro]:
    """Strip everything from shared macros that could act without the user asking.

    Hotkeys are cleared so a file cannot bind itself to a common key, and
    window handles are dropped because they only mean something on the
    machine that made the file (the window is found again by its process).
    """
    for m in macros:
        m.id = uuid.uuid4().hex
        m.hotkey = ""
        if m.window is not None:
            m.window.handle = m.window.pid = m.window.child = 0
        for step in m.steps:
            if "child" in step.params:
                step.params["child"] = 0
    return macros


def describe_import(macros: list[Macro], profiles: list[Profile] | None = None) -> str:
    """Plain-text summary of what imported macros would do, for the consent dialog."""
    lines = [f"{len(macros)} macro(s):"]
    for m in macros[:20]:
        counts = Counter(s.type for s in m.steps)
        parts = ", ".join(f"{n} × {STEP_LABELS[t].lower()}" for t, n in counts.most_common())
        target = f" → background window of {m.window.process or m.window.title}" if m.window else ""
        lines.append(f"• {m.name}{target}: {parts or 'no steps'}")
    if len(macros) > 20:
        lines.append(f"• … and {len(macros) - 20} more")
    if profiles:
        lines.append("")
        lines.append("Saved setups it brings along:")
        for p in profiles[:15]:
            lines.append(f"• {p.name} ({'autoclicker' if p.tool == 'clicker' else 'key repeater'})")
    launches = [s for m in macros for s in m.launch_steps()]
    if launches:
        lines.append("")
        lines.append("Programs it can start:")
        for s in launches[:15]:
            args = " ".join(s.get("args"))
            lines.append(f"• {s.get('path')}{(' ' + args) if args else ''}")
        if len(launches) > 15:
            lines.append(f"• … and {len(launches) - 15} more")
    return "\n".join(line.replace("\r", " ").replace("\n", " ") for line in lines)
