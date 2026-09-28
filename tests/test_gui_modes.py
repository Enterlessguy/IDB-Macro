"""Profiles, dumb mode and smart mode, driven through the real UI."""

import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QInputDialog  # noqa: E402

from idb_macro.core.models import Macro, Step  # noqa: E402
from idb_macro.core.storage import Store  # noqa: E402


@pytest.fixture(scope="module")
def app():
    from idb_macro.ui import theme

    a = QApplication.instance() or QApplication([])
    a.setStyleSheet(theme.stylesheet())
    return a


@pytest.fixture
def window(app, backend, tmp_path):
    from idb_macro.ui.controller import Controller
    from idb_macro.ui.main_window import MainWindow

    controller = Controller(backend, Store(tmp_path))
    w = MainWindow(controller)
    w.resize(1200, 800)
    w.show()
    app.processEvents()
    yield w
    controller.stop_all()
    w._quitting = True
    controller.settings.close_to_tray = False
    w.hide()


def pump(app, seconds=0.2):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def save_as(page, monkeypatch, name):
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: (name, True)))
    page.profiles.save_as()


def test_save_load_and_dirty_profiles(window, app, monkeypatch):
    page = window.pages["clicker"]
    page.interval.ms.setValue(250)
    save_as(page, monkeypatch, "Slow")
    assert [p.name for p in window.c.profiles] == ["Slow"]
    assert page.profiles.combo.currentText() == "Slow"
    assert not page.profiles.dirty.isVisibleTo(page)

    page.interval.ms.setValue(40)
    assert page.profiles.dirty.isVisibleTo(page)
    save_as(page, monkeypatch, "Fast")

    page.profiles.select(window.c.profiles[0].id)
    assert window.c.settings.clicker.interval_ms == 250
    assert page.interval.ms.value() == 250
    assert not page.profiles.dirty.isVisibleTo(page)
    # Profiles survive a restart.
    assert [p.name for p in window.c.store.load_profiles()] == ["Slow", "Fast"]


def test_profile_hotkey_runs_that_setup(window, app, monkeypatch, backend):
    page = window.pages["keys"]
    page._add_key("x")
    save_as(page, monkeypatch, "Spam X")
    page.profiles.hotkey.changed.emit("ctrl+f10")
    profile = window.c.profiles[0]
    assert profile.hotkey == "ctrl+f10"
    assert window.c.hotkey_conflicts("ctrl+f10") == 'saved setup "Spam X"'
    window.c._on_hotkey(f"profile:{profile.id}")
    pump(app, 0.3)
    assert ("kdown", "x") in backend.calls
    window.c._on_hotkey(f"profile:{profile.id}")  # the same hotkey stops it
    pump(app, 0.2)
    assert not window.c.is_running("keys")


def test_macro_step_runs_a_saved_setup(window, app, monkeypatch, backend):
    clicker = window.pages["clicker"]
    clicker.interval.ms.setValue(10)
    save_as(clicker, monkeypatch, "Burst")
    profile = window.c.profiles[0]
    page = window.pages["macro"]
    page.new_macro()
    page.current.steps = [Step.new("run_clicker", profile=profile.id, ms=200), Step.new("text", text="after")]
    page._render_steps()
    assert "Burst" in page.steps.item(0).text()
    page.play()
    pump(app, 0.8)
    assert backend.kinds().count("down") >= 5
    assert backend.calls[-1] == ("type", "after")


def test_dumb_mode_is_a_separate_plain_clicker(window, app, backend):
    window.pages["clicker"].location.setValue("points")  # full setup that would fail without spots
    window.set_dumb(True)
    assert window.views.currentWidget() is window.dumb
    assert window.c.settings.dumb_mode
    window.dumb.cps.setValue(50)
    window.dumb.run.click()
    pump(app, 0.3)
    assert window.c.is_running("clicker")
    window.dumb.run.click()
    pump(app, 0.2)
    assert backend.kinds().count("down") >= 5
    assert window.c.settings.clicker.location == "points"  # the full setup was left alone
    window.set_dumb(False)
    assert window.views.currentIndex() == 0
    assert not window.c.settings.dumb_mode


def test_smart_mode_presets_tips_and_guard(window, app):
    page = window.pages["clicker"]
    assert not page.smart.isVisibleTo(page)
    window.smart_toggle.setChecked(True)
    pump(app, 0.05)
    assert window.c.settings.smart_mode
    assert page.smart.isVisibleTo(page)
    assert window.pages["settings"].smart_on.isChecked()

    from idb_macro.core.presets import CLICKER_PRESETS

    page._apply_preset(next(p for p in CLICKER_PRESETS if p.key == "game"))
    assert (window.c.settings.clicker.action, page.action.value(), page.hold.value()) == ("hold", "hold", 25)
    assert "Roblox" in page.smart.applied.text()

    page.interval.ms.setValue(5)
    page.interval.s.setValue(0)
    assert any("10 ms" in t.text() for t in page.smart._tips)
    assert window.c.make_guard() is not None
    window.c.settings.smart_mode = False
    assert window.c.make_guard() is None


def test_import_brings_macros_and_their_setups(window, app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    from idb_macro.core.models import ClickerConfig
    from idb_macro.core.profiles import Profile
    from idb_macro.core.storage import export_macros

    p = Profile("clicker", "Shared", ClickerConfig())
    path = tmp_path / "bundle.json"
    export_macros(path, [Macro(name="Uses it", steps=[Step.new("run_clicker", profile=p.id)])], [p])
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(path), "")))
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Yes)
    window.pages["macro"].import_file()
    shared = next(x for x in window.c.profiles if x.name == "Shared")
    imported = next(m for m in window.c.macros if m.name == "Uses it")
    assert imported.steps[0].get("profile") == shared.id


def test_explainers_paint_every_scene(window, app):
    from idb_macro.ui.explainer import TEXT, ExplainerDialog

    for scene, (_title, simple, technical) in TEXT.items():
        d = ExplainerDialog(window, scene)
        for at in (0.2, 1.7, 3.9, 5.5):
            d.stage.start -= at
            assert not d.stage.grab().isNull()
        d.level.setValue("technical")
        assert d.text.text() == technical
        d.level.setValue("simple")
        assert d.text.text() == simple
        d.close()


def test_updates_page_reports_new_version(window, app):
    from idb_macro.core.updates import Release

    page = window.pages["updates"]
    page._checked(Release("99.0.0", "v99", "Big update", "https://github.com/x"), "")
    assert "99.0.0 is available" in page.status.text()
    assert window.nav["updates"].hint == "NEW"
    page._checked(Release("0.0.1", "old", "", "https://github.com/x"), "")
    assert "up to date" in page.status.text()
    page._checked(None, "offline")
    assert "offline" in page.status.text()
