# Contributing

Thanks for helping out. Bug reports, app compatibility notes ("background mode
works/doesn't work with X") and pull requests are all welcome.

## Setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    Linux: source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m idb_macro
```

On Linux you also need `python3-tk` for the integration tests, and an X11 (or
XWayland) session.

## Checks

```bash
ruff check src tests
pytest
```

`pytest` runs three kinds of tests:

- `tests/test_*` for the pure logic in `core/`, which needs no display.
- `tests/test_gui.py`, which builds the whole UI on Qt's offscreen platform.
- `tests/test_backend_integration.py` (marked `integration`), which opens a
  real window that starts minimized and drives it through the platform
  backend. It needs a desktop session: Windows, or X11/Xvfb on Linux. Skip it
  with `pytest -m "not integration"`.

## Layout

| Path | What lives there |
| --- | --- |
| `src/idb_macro/core/` | Pure logic: keys, timing, models, engine, recorder, storage. No Qt. |
| `src/idb_macro/platform/` | OS input backends behind one interface (`base.py`). |
| `src/idb_macro/ui/` | PySide6 interface. `theme.py` holds the design tokens. |
| `src/idb_macro/hotkeys.py` | Global hotkeys and the input recorder (pynput). |
| `docs/DESIGN.md` | Architecture and the reasoning behind the background input engine. |

## Guidelines

- Keep `core/` free of Qt and OS imports so it stays testable anywhere.
- Anything loaded from disk goes through the validators in `core/models.py`.
- A new step type needs an entry in `STEP_SPECS`, a branch in
  `MacroRunner.run_step`, and a test.
- No network code, telemetry or elevation.
