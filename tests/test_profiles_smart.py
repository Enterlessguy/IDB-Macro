import threading
import time

import pytest

from idb_macro.core.engine import ClickerRunner, KeyRunner, MacroRunner
from idb_macro.core.guard import SmartGuard
from idb_macro.core.models import (
    ClickerConfig,
    KeyRepeaterConfig,
    Macro,
    RunLimit,
    Step,
    TargetPoint,
    ValidationError,
    WindowTarget,
)
from idb_macro.core.presets import CLICKER_PRESETS, KEY_PRESETS, apply_preset, clicker_tips, keys_tips
from idb_macro.core.profiles import Profile
from idb_macro.core.storage import Settings, Store, export_macros, import_bundle


def run(runner, timeout=5.0):
    done = threading.Event()
    runner.on_event = lambda kind, msg: kind == "stopped" and done.set()
    runner.start()
    assert done.wait(timeout)
    return runner.finished_reason


# ---- profiles and storage ----------------------------------------------------

def test_profile_round_trip_and_validation(tmp_path):
    store = Store(tmp_path)
    p = Profile("clicker", "Fast", ClickerConfig(interval_ms=20), hotkey="ctrl+f2")
    k = Profile("keys", "Jump", KeyRepeaterConfig(keys=["space"]))
    store.save_profiles([p, k])
    back = store.load_profiles()
    assert [(x.tool, x.name, x.hotkey) for x in back] == [("clicker", "Fast", "ctrl+f2"), ("keys", "Jump", "")]
    assert back[0].config.interval_ms == 20
    with pytest.raises(ValidationError):
        Profile.from_dict({"tool": "nuke", "config": {}})


def test_settings_keep_smart_and_dumb_state(tmp_path):
    store = Store(tmp_path)
    s = Settings(smart_mode=True, dumb_mode=True)
    s.dumb.interval_ms = 50
    s.selected_profiles["clicker"] = "abc123"
    store.save_settings(s)
    back = store.load_settings()
    assert (back.smart_mode, back.dumb_mode, back.dumb.interval_ms) == (True, True, 50)
    assert back.selected_profiles == {"clicker": "abc123"}


def test_macro_export_bundles_the_profiles_it_uses(tmp_path):
    used = Profile("clicker", "Farm", ClickerConfig(location="window", window=WindowTarget(handle=5, process="g.exe"),
                                                    points=[TargetPoint(1, 2, 77, 1, 2)]), hotkey="f2")
    unused = Profile("keys", "Other", KeyRepeaterConfig())
    m = Macro(name="Loop", steps=[Step.new("run_clicker", profile=used.id, ms=2000)])
    path = tmp_path / "share.json"
    export_macros(path, [m], [used, unused])
    macros, profiles = import_bundle(path)
    assert [p.name for p in profiles] == ["Farm"]
    imported = profiles[0]
    assert imported.id != used.id and imported.hotkey == ""
    assert imported.config.window.handle == 0 and imported.config.points[0].child == 0
    assert macros[0].steps[0].get("profile") == imported.id


def test_profile_step_validation_and_summary():
    step = Step.new("run_keys", profile="ab12", until="own")
    assert step.summary({"ab12": "Jump"}) == 'Run key repeater "Jump" until it stops'
    assert "profile missing" in Step.new("run_clicker", profile="ff").summary({})
    with pytest.raises(ValidationError):
        Step.from_dict({"type": "run_clicker", "params": {"profile": "../x"}})


# ---- macros running profiles -----------------------------------------------------

def test_macro_runs_a_clicker_profile_for_a_set_time(backend):
    p = Profile("clicker", "Fast", ClickerConfig(interval_ms=10))
    m = Macro(steps=[Step.new("run_clicker", profile=p.id, ms=300), Step.new("text", text="done")])
    start = time.perf_counter()
    assert run(MacroRunner(backend, m, profiles={p.id: p})) == "Finished"
    assert 0.25 < time.perf_counter() - start < 1.0
    assert 15 <= backend.kinds().count("down") <= 35
    assert backend.calls[-1] == ("type", "done")


def test_macro_profile_step_uses_the_profiles_own_stop_condition(backend):
    p = Profile("keys", "Three", KeyRepeaterConfig(keys=["a"], hold_ms=1, interval_ms=1, limit=RunLimit("count", 3)))
    m = Macro(steps=[Step.new("run_keys", profile=p.id, until="own")])
    run(MacroRunner(backend, m, profiles={p.id: p}))
    assert backend.kinds().count("kdown") == 3


def test_stopping_the_macro_stops_the_nested_profile(backend):
    p = Profile("clicker", "Endless", ClickerConfig(interval_ms=5))
    m = Macro(steps=[Step.new("run_clicker", profile=p.id, until="own")])
    r = MacroRunner(backend, m, profiles={p.id: p})
    threading.Timer(0.2, r.stop).start()
    start = time.perf_counter()
    assert run(r) == "Stopped"
    assert time.perf_counter() - start < 0.6


def test_missing_profile_is_explained(backend):
    m = Macro(steps=[Step.new("run_clicker", profile="dead")])
    assert "no longer exists" in run(MacroRunner(backend, m, profiles={}))


# ---- smart guard ----------------------------------------------------------------

class GuardBackend:
    """Just enough backend for SmartGuard."""

    def __init__(self):
        self.active = WindowTarget(handle=10, title="Game", pid=100)
        self.under = WindowTarget(handle=10, window_class="GameWindow", pid=100)
        self.pos = (5, 5)

    def foreground_window(self):
        return self.active

    def window_at(self, x, y):
        return self.under

    def cursor_pos(self):
        return self.pos


def test_guard_waits_for_a_real_window_then_locks_to_it():
    b = GuardBackend()
    g = SmartGuard(b, own_pid=1)
    b.active = WindowTarget(handle=1, pid=1)  # I-DB Macro itself is active after pressing Start
    assert g.check(False).startswith("Waiting")
    b.active = WindowTarget(handle=10, title="Game", pid=100)
    assert g.check(False) == ""
    b.active = WindowTarget(handle=20, title="Discord", pid=200)
    assert "Game" in g.check(False)
    b.active = WindowTarget(handle=10, title="Game", pid=100)
    assert g.check(False) == ""


def test_guard_never_clicks_the_taskbar_or_itself():
    b = GuardBackend()
    g = SmartGuard(b, focus_lock=False, own_pid=1)
    assert g.check(True) == ""
    b.under = WindowTarget(handle=3, window_class="Shell_TrayWnd", pid=50)
    assert "taskbar" in g.check(True)
    b.under = WindowTarget(handle=4, window_class="Qt", pid=1)
    assert "I-DB Macro" in g.check(True)
    assert g.check(False) == ""  # key presses don't care what is under the cursor


class Gate:
    def __init__(self):
        self.open = True

    def check(self, pointer, point=None):
        return "" if self.open else "Paused: test"


def test_clicker_skips_clicks_while_guarded(backend):
    gate = Gate()
    gate.open = False
    r = ClickerRunner(backend, ClickerConfig(interval_ms=5, limit=RunLimit("duration", 1, 0.2)), guard=gate)
    run(r)
    assert backend.kinds().count("down") == 0
    assert r.status == "Paused: test"


def test_held_key_is_released_while_another_app_is_active(backend):
    gate = Gate()
    r = KeyRunner(backend, KeyRepeaterConfig(keys=["w"], action="hold", interval_ms=10), guard=gate)
    r.start()
    time.sleep(0.1)
    gate.open = False
    time.sleep(0.1)
    assert backend.calls[-1] == ("kup", "w")
    gate.open = True
    time.sleep(0.1)
    r.stop()
    r.join(2)
    assert backend.calls == [("kdown", "w"), ("kup", "w"), ("kdown", "w"), ("kup", "w")]


# ---- presets and tips ---------------------------------------------------------------

def test_presets_only_change_what_they_name():
    base = ClickerConfig(button="right", points=[TargetPoint(1, 1)])
    game = next(p for p in CLICKER_PRESETS if p.key == "game")
    out = apply_preset(base, game)
    assert (out.action, out.hold_ms, out.button, len(out.points)) == ("hold", 25.0, "right", 1)
    assert base.action == "single"  # the original is untouched
    for preset in CLICKER_PRESETS:
        ClickerConfig.from_dict(apply_preset(ClickerConfig(), preset).to_dict())
    for preset in KEY_PRESETS:
        KeyRepeaterConfig.from_dict(apply_preset(KeyRepeaterConfig(), preset).to_dict())


def test_tips_react_to_settings():
    assert any("under 10 ms" in t for t in clicker_tips(ClickerConfig(interval_ms=5)))
    assert any("Pick the window" in t for t in clicker_tips(ClickerConfig(location="window")))
    assert any("30 ms" in t for t in keys_tips(KeyRepeaterConfig(hold_ms=10)))
    assert any("chat" in t for t in keys_tips(KeyRepeaterConfig(keys=["enter"])))
    assert not any("30 ms" in t for t in keys_tips(KeyRepeaterConfig(hold_ms=50)))
