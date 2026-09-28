import json

import pytest

from idb_macro.core.models import (
    ClickerConfig,
    KeyRepeaterConfig,
    Macro,
    Step,
    TargetPoint,
    ValidationError,
    WindowTarget,
    macros_from_document,
    macros_to_document,
)
from idb_macro.core.storage import Settings, Store, import_macros


def sample_macro():
    return Macro(
        name="Demo",
        repeat=3,
        speed=2.0,
        hotkey="ctrl+f1",
        steps=[
            Step.new("click", button="right", count=2, x=10, y=20),
            Step.new("wait", ms=250, random_ms=50),
            Step.new("key", combo="Ctrl+C"),
            Step.new("text", text="hello\nworld"),
            Step.new("launch", path="notepad.exe", args=["a.txt"]),
        ],
    )


def test_macro_round_trip():
    m = sample_macro()
    doc = json.loads(json.dumps(macros_to_document([m])))
    (back,) = macros_from_document(doc)
    assert back.to_dict() == m.to_dict()
    assert back.steps[2].get("combo") == "ctrl+c"
    assert [s.type for s in back.launch_steps()] == ["launch"]


def test_step_defaults_and_summary():
    s = Step.new("scroll")
    assert s.get("amount") == -1
    assert "Scroll down" in s.summary()
    assert Step.new("key", combo="ctrl+shift+s").summary() == "Press Ctrl + Shift + S"
    assert Step.new("wait", ms=100, random_ms=20).summary() == "Wait 100 ms (+0–20 ms)"


@pytest.mark.parametrize("bad", [
    {"type": "nope"},
    {"type": "click", "params": {"button": "sideways"}},
    {"type": "click", "params": {"count": 9}},
    {"type": "wait", "params": {"ms": -1}},
    {"type": "wait", "params": {"ms": float("inf")}},
    {"type": "wait", "params": {"ms": True}},
    {"type": "key", "params": {"combo": "ctrl+q+w"}},
    {"type": "text", "params": {"text": "x" * 10_001}},
    {"type": "text", "params": {"text": "a\x00b"}},
    {"type": "launch", "params": {"args": "not a list"}},
    {"type": "launch", "params": {"args": [1, 2]}},
    "not a dict",
])
def test_step_validation_rejects(bad):
    with pytest.raises(ValidationError):
        Step.from_dict(bad)


def test_unknown_fields_are_dropped():
    s = Step.from_dict({"type": "wait", "params": {"ms": 5, "evil": "x"}, "extra": 1})
    assert "evil" not in s.params


def test_document_checks():
    with pytest.raises(ValidationError):
        macros_from_document({"format": "other", "version": 1, "macros": []})
    with pytest.raises(ValidationError):
        macros_from_document({"format": "idb-macro", "version": 99, "macros": []})
    with pytest.raises(ValidationError):
        macros_from_document({"format": "idb-macro", "version": 1, "macros": [{}] * 501})


def test_macro_id_is_sanitised():
    m = Macro.from_dict({"id": "../../etc", "name": "x"})
    assert all(c in "0123456789abcdef" for c in m.id)


def test_clicker_config_round_trip():
    c = ClickerConfig(location="window", points=[TargetPoint(1, 2, 3, 4, 5)],
                      window=WindowTarget(handle=9, title="t", process="p.exe"))
    assert ClickerConfig.from_dict(c.to_dict()) == c
    with pytest.raises(ValidationError):
        ClickerConfig.from_dict({"interval_ms": 0})


def test_key_config_normalises():
    k = KeyRepeaterConfig.from_dict({"keys": ["Space", "Ctrl+A"]})
    assert k.keys == ["space", "ctrl+a"]


def test_store_round_trip(tmp_path):
    store = Store(tmp_path)
    s = Settings()
    s.hotkeys["clicker"] = "f2"
    s.clicker.interval_ms = 33
    store.save_settings(s)
    store.save_macros([sample_macro()])
    s2 = store.load_settings()
    assert s2.hotkeys["clicker"] == "f2"
    assert s2.clicker.interval_ms == 33
    assert store.load_macros()[0].name == "Demo"


def test_store_quarantines_corrupt_files(tmp_path):
    store = Store(tmp_path)
    store.settings_path.write_text("{not json", encoding="utf-8")
    store.macros_path.write_text('{"format": "idb-macro", "version": 1, "macros": [{"steps": 5}]}',
                                 encoding="utf-8")
    assert store.load_settings() == Settings()
    assert store.load_macros() == []
    leftovers = sorted(p.name.split(".corrupt")[0] for p in tmp_path.iterdir())
    assert leftovers == ["macros.json", "settings.json"]


def test_bad_tool_config_keeps_other_settings(tmp_path):
    store = Store(tmp_path)
    store.settings_path.write_text(json.dumps({"show_splash": False, "clicker": {"interval_ms": -5},
                                               "hotkeys": {"panic": "bogus+key+x"}}), encoding="utf-8")
    s = store.load_settings()
    assert s.show_splash is False
    assert s.clicker == ClickerConfig()
    assert s.hotkeys["panic"] == "f12"


def test_import_strips_hotkeys_and_handles(tmp_path):
    from idb_macro.core.storage import export_macros

    m = sample_macro()
    m.hotkey = "enter"
    m.target = "window"
    m.window = WindowTarget(handle=1234, title="t", process="p.exe", pid=99, child=55)
    m.steps[0].params["child"] = 777
    path = tmp_path / "shared.json"
    export_macros(path, [m])
    (back,) = import_macros(path)
    assert back.hotkey == ""
    assert back.id != m.id
    assert (back.window.handle, back.window.pid, back.window.child) == (0, 0, 0)
    assert back.window.process == "p.exe"
    assert back.steps[0].params["child"] == 0


def test_import_summary_lists_programs_with_arguments():
    from idb_macro.core.storage import describe_import

    m = sample_macro()
    m.steps.append(Step.new("launch", path="evil.exe", args=["--wipe", "all\nfake line"]))
    text = describe_import([m])
    assert "evil.exe --wipe all fake line" in text
    assert "notepad.exe a.txt" in text
    assert "1 × press keys" in text


def test_deeply_nested_json_is_rejected(tmp_path):
    p = tmp_path / "deep.json"
    p.write_text("[" * 100_000 + "]" * 100_000, encoding="utf-8")
    with pytest.raises(ValidationError):
        import_macros(p)


def test_import_size_cap(tmp_path, monkeypatch):
    import idb_macro.core.storage as storage

    monkeypatch.setattr(storage, "MAX_FILE_BYTES", 10)
    p = tmp_path / "big.json"
    p.write_text(" " * 100, encoding="utf-8")
    with pytest.raises(ValidationError):
        import_macros(p)
