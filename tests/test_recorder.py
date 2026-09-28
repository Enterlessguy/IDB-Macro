from idb_macro.core.recorder import RawEvent, RecordOptions, events_to_steps


def ev(t, kind, **kw):
    return RawEvent(t=t, kind=kind, **kw)


def summary(steps):
    return [(s.type, {k: v for k, v in s.params.items() if k in ("button", "count", "combo", "ms", "text", "amount")})
            for s in steps]


def test_click_and_wait():
    steps = events_to_steps([
        ev(0.0, "mouse_down", x=10, y=10, button="left"),
        ev(0.05, "mouse_up", x=10, y=10, button="left"),
        ev(1.05, "mouse_down", x=50, y=50, button="right"),
        ev(1.10, "mouse_up", x=51, y=50, button="right"),
    ])
    assert summary(steps) == [
        ("click", {"button": "left", "count": 1}),
        ("wait", {"ms": 1000}),
        ("click", {"button": "right", "count": 1}),
    ]
    assert steps[0].get("x") == 10


def test_double_click_merge():
    steps = events_to_steps([
        ev(0.0, "mouse_down", x=5, y=5, button="left"),
        ev(0.03, "mouse_up", x=5, y=5, button="left"),
        ev(0.10, "mouse_down", x=5, y=5, button="left"),
        ev(0.13, "mouse_up", x=5, y=5, button="left"),
    ])
    assert summary(steps) == [("click", {"button": "left", "count": 2})]


def test_drag_becomes_down_up():
    steps = events_to_steps([
        ev(0.0, "mouse_down", x=0, y=0, button="left"),
        ev(0.5, "mouse_up", x=300, y=0, button="left"),
    ])
    assert [s.type for s in steps] == ["mouse_down", "wait", "mouse_up"]


def test_combo_is_collapsed():
    steps = events_to_steps([
        ev(0.0, "key_down", key="ctrl"),
        ev(0.05, "key_down", key="s"),
        ev(0.08, "key_up", key="s"),
        ev(0.12, "key_up", key="ctrl"),
    ])
    assert summary(steps) == [("key", {"combo": "ctrl+s"})]


def test_recorded_taps_keep_their_press_length():
    steps = events_to_steps([
        ev(0.0, "key_down", key="ctrl"),
        ev(0.05, "key_down", key="s"),
        ev(0.13, "key_up", key="s"),
        ev(0.2, "key_up", key="ctrl"),
        ev(1.0, "key_down", key="space"),
        ev(1.004, "key_up", key="space"),
    ])
    taps = [s for s in steps if s.type == "key"]
    assert [(s.get("combo"), s.get("hold_ms")) for s in taps] == [("ctrl+s", 80), ("space", 10)]


def test_long_hold_kept():
    steps = events_to_steps([
        ev(0.0, "key_down", key="w"),
        ev(0.1, "key_down", key="w"),  # auto-repeat is ignored
        ev(2.0, "key_up", key="w"),
    ])
    assert summary(steps) == [("key_down", {"combo": "w"}), ("wait", {"ms": 2000}), ("key_up", {"combo": "w"})]


def test_modifier_tap():
    steps = events_to_steps([ev(0.0, "key_down", key="shift"), ev(0.1, "key_up", key="shift")])
    assert summary(steps) == [("key", {"combo": "shift"})]


def test_scroll_merge():
    steps = events_to_steps([
        ev(0.0, "scroll", x=1, y=1, amount=-1),
        ev(0.05, "scroll", x=1, y=1, amount=-1),
        ev(0.10, "scroll", x=1, y=1, amount=-1),
    ])
    assert summary(steps) == [("scroll", {"amount": -3})]


def test_drop_stop_hotkey_and_merge_text():
    opts = RecordOptions(drop_keys=("f9",), merge_text=True)
    events = []
    t = 0.0
    for ch in "hi":
        events += [ev(t, "key_down", key=ch), ev(t + 0.02, "key_up", key=ch)]
        t += 0.1
    events += [ev(t, "key_down", key="f9"), ev(t + 0.02, "key_up", key="f9")]
    steps = events_to_steps(events, opts)
    assert summary(steps) == [("text", {"text": "hi"})]


def test_transform_for_background_targets():
    opts = RecordOptions(transform=lambda x, y: (x - 100, y - 100, 42, 1, 2))
    steps = events_to_steps([
        ev(0, "mouse_down", x=150, y=160, button="left"),
        ev(0.01, "mouse_up", x=150, y=160, button="left"),
    ], opts)
    p = steps[0].params
    assert (p["x"], p["y"], p["child"], p["cx"], p["cy"]) == (50, 60, 42, 1, 2)


def test_moves_are_sampled():
    opts = RecordOptions(record_moves=True, move_sample_ms=40)
    events = [ev(i * 0.01, "move", x=i, y=i) for i in range(10)]
    steps = events_to_steps(events, opts)
    assert [s.type for s in steps if s.type == "move"] == ["move"] * 3
