"""Saved Autoclicker and Key Repeater setups ("profiles")."""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from typing import Any

from .models import (
    FORMAT_ID,
    FORMAT_VERSION,
    MAX_NAME,
    ClickerConfig,
    KeyRepeaterConfig,
    ValidationError,
    _choice,
    _combo,
    _dict,
    _list,
    _str,
)

TOOLS = ("clicker", "keys")
TOOL_NAMES = {"clicker": "Autoclicker", "keys": "Key Repeater"}
MAX_PROFILES = 500
CONFIG_TYPES = {"clicker": ClickerConfig, "keys": KeyRepeaterConfig}


def valid_id(value: Any) -> str:
    """A profile or macro id: lowercase hex, or empty."""
    if not isinstance(value, str) or len(value) > 64 or not all(c in "0123456789abcdef" for c in value):
        raise ValidationError("invalid id")
    return value


@dataclass
class Profile:
    tool: str
    name: str
    config: ClickerConfig | KeyRepeaterConfig
    hotkey: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_dict(self) -> dict:
        return {"id": self.id, "tool": self.tool, "name": self.name, "hotkey": self.hotkey,
                "config": self.config.to_dict()}

    @classmethod
    def from_dict(cls, d: Any) -> Profile:
        d = _dict(d, "profile")
        tool = _choice(d, "tool", "clicker", TOOLS)
        try:
            profile_id = valid_id(d.get("id", "")) or uuid.uuid4().hex
        except ValidationError:
            profile_id = uuid.uuid4().hex
        return cls(
            id=profile_id,
            tool=tool,
            name=_str(d, "name", "Profile", MAX_NAME).strip() or "Profile",
            hotkey=_combo(d.get("hotkey", ""), allow_empty=True),
            config=CONFIG_TYPES[tool].from_dict(d.get("config", {})),
        )

    def copy_config(self) -> ClickerConfig | KeyRepeaterConfig:
        return copy.deepcopy(self.config)


def profiles_to_list(profiles: list[Profile]) -> list[dict]:
    return [p.to_dict() for p in profiles]


def profiles_from_list(items: Any) -> list[Profile]:
    return [Profile.from_dict(p) for p in _list(items, "profiles", MAX_PROFILES)]


def profiles_to_document(profiles: list[Profile]) -> dict:
    return {"format": FORMAT_ID, "version": FORMAT_VERSION, "macros": [], "profiles": profiles_to_list(profiles)}


def strip_for_sharing(profiles: list[Profile]) -> dict[str, str]:
    """Give imported profiles fresh ids and drop machine-specific data.

    Returns a map of old id -> new id so macro steps can be pointed at the copies.
    """
    remap = {}
    for p in profiles:
        new_id = uuid.uuid4().hex
        remap[p.id] = new_id
        p.id = new_id
        p.hotkey = ""
        window = getattr(p.config, "window", None)
        if window is not None:
            window.handle = window.pid = window.child = 0
        for point in getattr(p.config, "points", []):
            point.child = 0
    return remap
