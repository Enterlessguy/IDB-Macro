import threading
import time

from idb_macro.core.engine import ClickerRunner, KeyRunner, MacroRunner
from idb_macro.core.models import ClickerConfig, KeyRepeaterConfig, Macro, RunLimit, Step, TargetPoint


def run(runner, timeout=5.0):
    events = []
    done = threading.Event()

    def on_event(kind, msg):
        events.append((kind, msg))
        if kind == "stopped":
            done.set()

    runner.on_event = on_event
    runner.start()
    assert done.wait(timeout), "runner did not finish"
    return events[-1][1]


def test_clicker_count_limit(backend):
    cfg = ClickerConfig(interval_ms=1, limit=RunLimit(mode="count", count=25))
    assert run(ClickerRunner(backend, cfg)) == "Finished"
    assert backend.kinds().count("down") == 25
    assert backend.kinds().count("up") == 25


def test_clicker_double_and_rate(backend):
    cfg = ClickerConfig(interval_ms=20, action="double", limit=RunLimit(mode="duration", seconds=0.5))
    start = time.perf_counter()
    assert run(ClickerRunner(backend, cfg)) == "Finished"
    assert time.perf_counter() - start < 0.8
    clicks = backend.kinds().count("down") // 2
    assert 20 <= clicks <= 27


def test_clicker_points_restore_cursor(backend):
    backend.pos = (5, 5)
    cfg = ClickerConfig(location="points", points=[TargetPoint(100, 100), TargetPoint(200, 200)],
                        interval_ms=1, limit=RunLimit(mode="count", count=4))
    run(ClickerRunner(backend, cfg))
    moves = [c[1:] for c in backend.calls if c[0] == "move"]
    assert moves == [(100, 100), (5, 5), (200, 200), (5, 5)] * 2


def test_clicker_hold_releases_on_stop(backend):
    cfg = ClickerConfig(action="hold", hold_ms=5000, interval_ms=1)
    r = ClickerRunner(backend, cfg)
    threading.Timer(0.1, r.stop).start()
    assert run(r) == "Stopped"
    assert backend.kinds().count("down") == backend.kinds().count("up") == 1


def test_clicker_window_mode(backend, window):
    cfg = ClickerConfig(location="window", window=window, points=[TargetPoint(7, 8, 99, 1, 2)],
                        interval_ms=1, limit=RunLimit(mode="count", count=3))
    run(ClickerRunner(backend, cfg))
    assert [c[:5] for c in backend.calls] == [("bg_mouse", "click", "left", 7, 8)] * 3
    assert "move" not in backend.kinds()


def test_clicker_window_lost(backend, window):
    backend.alive = False
    cfg = ClickerConfig(location="window", window=window, points=[TargetPoint(1, 1)])
    assert "gone" in run(ClickerRunner(backend, cfg))


def test_clicker_requires_points(backend):
    assert "point" in run(ClickerRunner(backend, ClickerConfig(location="points")))


def test_failsafe(backend):
    r = ClickerRunner(backend, ClickerConfig(interval_ms=1), failsafe=lambda: True)
    assert "fail-safe" in run(r)
    assert backend.calls == []


def test_key_cycle_and_combo(backend):
    cfg = KeyRepeaterConfig(keys=["a", "ctrl+b"], interval_ms=1, limit=RunLimit(mode="count", count=4))
    run(KeyRunner(backend, cfg))
    assert backend.calls == [
        ("kdown", "a"), ("kup", "a"),
        ("kdown", "ctrl"), ("kdown", "b"), ("kup", "b"), ("kup", "ctrl"),
    ] * 2


def test_key_tap_is_held_long_enough_for_games(backend):
    # Games sample keys once per frame; a 0 ms press is invisible to them.
    cfg = KeyRepeaterConfig(keys=["space"], interval_ms=200, hold_ms=40, limit=RunLimit(mode="count", count=1))
    run(KeyRunner(backend, cfg))
    assert backend.calls == [("kdown", "space"), ("kup", "space")]
    assert backend.gap(("kdown", "space"), ("kup", "space")) >= 0.035


def test_legacy_press_and_hold_action_becomes_tap():
    cfg = KeyRepeaterConfig.from_dict({"keys": ["a"], "action": "hold_tap", "hold_ms": 80})
    assert (cfg.action, cfg.hold_ms) == ("tap", 80)
    assert KeyRepeaterConfig().hold_ms == 40


def test_macro_key_step_holds(backend):
    m = Macro(steps=[Step.new("key", combo="space", hold_ms=40)])
    run(MacroRunner(backend, m))
    assert backend.gap(("kdown", "space"), ("kup", "space")) >= 0.035
    assert Step.new("key", combo="a").get("hold_ms") == 40


def test_key_together(backend):
    cfg = KeyRepeaterConfig(keys=["a", "b"], sequence="together", interval_ms=1,
                            limit=RunLimit(mode="count", count=1))
    run(KeyRunner(backend, cfg))
    assert backend.calls == [("kdown", "a"), ("kdown", "b"), ("kup", "b"), ("kup", "a")]


def test_key_hold_until_stop(backend):
    r = KeyRunner(backend, KeyRepeaterConfig(keys=["shift+w"], action="hold", interval_ms=10))
    threading.Timer(0.1, r.stop).start()
    run(r)
    assert backend.calls == [("kdown", "shift"), ("kdown", "w"), ("kup", "w"), ("kup", "shift")]


def test_key_background_hold_repeats(backend, window):
    cfg = KeyRepeaterConfig(keys=["w"], action="hold", target="window", window=window, interval_ms=10,
                            limit=RunLimit(mode="count", count=4))
    run(KeyRunner(backend, cfg))
    assert backend.kinds().count("bg_kdown") == 4
    assert backend.kinds()[-1] == "bg_kup"


def test_macro_steps_and_repeat(backend):
    m = Macro(repeat=2, steps=[
        Step.new("click", x=1, y=2),
        Step.new("key", combo="ctrl+v"),
        Step.new("wait", ms=1),
        Step.new("text", text="hi"),
        Step.new("scroll", amount=3, at="cursor"),
        Step.from_dict({"type": "click", "enabled": False}),
    ])
    assert run(MacroRunner(backend, m)) == "Finished"
    one = [("move", 1, 2), ("down", "left"), ("up", "left"),
           ("kdown", "ctrl"), ("kdown", "v"), ("kup", "v"), ("kup", "ctrl"),
           ("type", "hi"), ("scroll", 3, False)]
    assert backend.calls == one * 2


def test_macro_releases_held_keys(backend):
    m = Macro(repeat=0, steps=[Step.new("key_down", combo="shift"), Step.new("wait", ms=5000)])
    r = MacroRunner(backend, m)
    threading.Timer(0.1, r.stop).start()
    assert run(r) == "Stopped"
    assert backend.calls == [("kdown", "shift"), ("kup", "shift")]


def test_macro_speed_scales_waits(backend):
    m = Macro(speed=10.0, steps=[Step.new("wait", ms=1000)])
    start = time.perf_counter()
    run(MacroRunner(backend, m))
    assert time.perf_counter() - start < 0.4


def test_macro_focus_failure_stops(backend):
    m = Macro(steps=[Step.new("focus", title="missing"), Step.new("text", text="x")])
    assert "missing" in run(MacroRunner(backend, m))
    assert "type" not in backend.kinds()


def test_macro_background(backend, window):
    m = Macro(target="window", window=window, steps=[
        Step.new("click", x=3, y=4), Step.new("key", combo="ctrl+s"), Step.new("text", text="ab"),
    ])
    run(MacroRunner(backend, m))
    assert backend.calls == [
        ("bg_mouse", "click", "left", 3, 4, 1),
        ("bg_kdown", "ctrl", ()), ("bg_kdown", "s", ("ctrl",)),
        ("bg_kup", "s", ("ctrl",)), ("bg_kup", "ctrl", ()),
        ("bg_text", "ab"),
    ]


def test_launch_rejects_batch_arguments(backend):
    m = Macro(steps=[Step.new("launch", path="evil.bat", args=["&calc"])])
    assert ".bat" in run(MacroRunner(backend, m))


def test_empty_macro(backend):
    assert "no enabled steps" in run(MacroRunner(backend, Macro()))
