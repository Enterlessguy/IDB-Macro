"""Builds the whole UI on Qt's offscreen platform against a fake backend."""

import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from idb_macro.core.models import STEP_SPECS, Macro, Step  # noqa: E402
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


def test_pages_render(window, app):
    for key in ("clicker", "keys", "macro", "settings"):
        window.navigate(key)
        pump(app, 0.05)
        assert not window.grab().isNull()
    # First launch seeds one example macro.
    assert len(window.c.macros) == 1


def test_clicker_runs_from_ui(window, app, backend):
    page = window.pages["clicker"]
    page.limit.mode.setValue("count")
    page.limit.count.setValue(5)
    page.interval.ms.setValue(1)
    page.bar.run.click()
    pump(app, 0.5)
    assert backend.kinds().count("down") == 5
    assert "Finished" in page.bar.status.text()
    assert window.c.settings.clicker.limit.count == 5


def test_window_mode_visibility(window, app):
    page = window.pages["clicker"]
    page.location.setValue("window")
    pump(app, 0.05)
    assert page.window_panel.isVisible()
    assert not page.screen_points.isVisible()
    page.location.setValue("cursor")
    pump(app, 0.05)
    assert not page.window_panel.isVisible()


def test_choosing_another_window_drops_old_spots(window, app):
    from idb_macro.core.models import TargetPoint, WindowTarget

    page = window.pages["clicker"]
    page.location.setValue("window")
    page.window_panel.set_target(WindowTarget(handle=1, title="A", process="a.exe"), emit=True)
    page.window_points.set_points([TargetPoint(5, 5)])
    page.save()
    page.window_panel.set_target(WindowTarget(handle=2, title="B", process="b.exe"), emit=True)
    assert page.window_points.points == []
    assert window.c.settings.clicker.points == []


def test_add_spot_accepts_the_same_app_after_it_restarted(window, app, backend):
    from idb_macro.core.models import TargetPoint, WindowTarget
    from idb_macro.platform.base import PickResult

    page = window.pages["clicker"]
    page.location.setValue("window")
    page.window_panel.set_target(WindowTarget(handle=1, title="Game", process="game.exe"), emit=True)
    backend.alive = False  # the saved handle belongs to a window that no longer exists
    fresh = WindowTarget(handle=99, title="Game", process="game.exe")
    page.window_points._picked(PickResult(fresh, TargetPoint(7, 8)), "")
    assert page.window_panel.target.handle == 99
    assert [(p.x, p.y) for p in page.window_points.points] == [(7, 8)]


def test_minimized_chromium_target_is_explained(window, app, backend):
    from idb_macro.core.models import TargetPoint, WindowTarget

    page = window.pages["clicker"]
    page.location.setValue("window")
    page.window_panel.set_target(WindowTarget(handle=1, title="Discord", process="Discord.exe",
                                              window_class="Chrome_WidgetWin_1"), emit=True)
    page.window_points.set_points([TargetPoint(5, 5)])
    page.save()
    backend.is_minimized = lambda target: True
    page.test_click()
    assert "minimized" in page.test_result.text()


def test_key_repeater_add_keys(window, app, backend):
    page = window.pages["keys"]
    page._add_key("ctrl+b")
    page._add_key("not a key")
    assert page.keys[-1] == "ctrl+b"
    assert page.key_error.text()
    assert window.c.settings.keys.keys[-1] == "ctrl+b"

    from PySide6.QtWidgets import QPushButton

    chips = [b for b in page.chips.findChildren(QPushButton) if b.isVisibleTo(page.chips)]
    assert [c.text().split("   ")[0] for c in chips] == ["Space", "Ctrl + B"]
    chips[-1].click()  # a chip added after a rebuild must still be clickable
    assert page.keys == ["space"]
    assert window.c.settings.keys.keys == ["space"]


def test_macro_editing_and_playback(window, app, backend):
    page = window.pages["macro"]
    page.new_macro()
    m = page.current
    m.steps = [Step.new("key", combo="a"), Step.new("wait", ms=1), Step.new("text", text="ok")]
    page._render_steps()
    page.steps.setCurrentRow(0)
    page.toggle_steps()
    assert m.steps[0].enabled is False
    page.steps.clearSelection()
    page.steps.setCurrentRow(2)
    page.move_step(-1)
    assert [s.type for s in m.steps] == ["key", "text", "wait"]
    page.play()
    pump(app, 0.4)
    assert ("type", "ok") in backend.calls
    assert ("kdown", "a") not in backend.calls


def test_step_dialog_for_every_type(window, app):
    from idb_macro.core.models import ClickerConfig, KeyRepeaterConfig
    from idb_macro.core.profiles import Profile
    from idb_macro.ui.pages.step_dialog import StepDialog

    macro = Macro()
    empty = StepDialog(window, window.c, macro, Step.new("run_clicker"))
    empty._accept()
    assert empty.result() != QDialog.DialogCode.Accepted  # nothing saved yet to run
    window.c.profiles += [Profile("clicker", "Fast", ClickerConfig()), Profile("keys", "Jump", KeyRepeaterConfig())]
    for step_type in STEP_SPECS:
        step = Step.new(step_type)
        dlg = StepDialog(window, window.c, macro, step)
        dlg._accept()
        assert dlg.result() == QDialog.DialogCode.Accepted, (step_type, dlg.error.text())


def test_hotkey_conflicts(window):
    c = window.c
    assert c.hotkey_conflicts("f6") == "Autoclicker toggle"
    assert c.hotkey_conflicts("f6", ignore="clicker") is None
    assert c.hotkey_conflicts("ctrl+alt+j") is None


def test_splash_paints(app):
    from idb_macro.ui.splash import SplashWindow

    s = SplashWindow(QRect(0, 0, 900, 560))
    img = s.grab()
    assert not img.isNull()
    s.close()
