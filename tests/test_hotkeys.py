from pynput import keyboard

from idb_macro.hotkeys import HotkeyManager
from idb_macro.input_names import button_name, key_name


def test_key_names():
    assert key_name(keyboard.Key.f6) == "f6"
    assert key_name(keyboard.Key.ctrl_r) == "ctrl"
    assert key_name(keyboard.Key.page_down) == "pagedown"
    assert key_name(keyboard.KeyCode.from_char("A")) == "a"
    assert key_name(None) is None


def test_button_names():
    from pynput import mouse

    assert button_name(mouse.Button.left) == "left"


def make():
    fired = []
    hk = HotkeyManager(fired.append)
    hk.set_bindings({"clicker": "f6", "panic": "ctrl+shift+x", "none": ""})
    return hk, fired


def tap(hk, *keys, injected=False):
    for k in keys:
        hk._on_press(k, injected)
    for k in reversed(keys):
        hk._on_release(k, injected)


def test_simple_hotkey():
    hk, fired = make()
    tap(hk, keyboard.Key.f6)
    assert fired == ["clicker"]


def test_combo_needs_exact_modifiers():
    hk, fired = make()
    tap(hk, keyboard.Key.ctrl_l, keyboard.KeyCode.from_char("x"))
    assert fired == []
    tap(hk, keyboard.Key.ctrl_l, keyboard.Key.shift, keyboard.KeyCode.from_char("x"))
    assert fired == ["panic"]
    tap(hk, keyboard.Key.ctrl_l, keyboard.Key.f6)
    assert fired == ["panic"]


def test_injected_and_autorepeat_ignored():
    hk, fired = make()
    tap(hk, keyboard.Key.f6, injected=True)
    hk._on_press(keyboard.Key.f6, False)
    hk._on_press(keyboard.Key.f6, False)
    assert fired == ["clicker"]


def test_stale_key_does_not_block():
    hk, fired = make()
    hk._on_press(keyboard.KeyCode.from_char("q"), False)  # release never arrives
    tap(hk, keyboard.Key.f6)
    assert fired == ["clicker"]


def test_invalid_binding_reported():
    hk, _ = make()
    assert hk.set_bindings({"a": "ctrl+nonsense"}) == ["a"]
