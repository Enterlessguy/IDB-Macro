# I-DB Macro design

## Goal

One desktop tool that replaces the usual pile of half-working autoclickers and
macro recorders. Three tools share one input engine:

| Tool | What it does |
| --- | --- |
| Autoclicker | Clicks at the cursor, at fixed points (one or a cycle of several), or inside a picked window in the background. |
| Key Repeater | The autoclicker idea for keyboards: presses a key or combo repeatedly, holds it, or cycles through several keys. |
| Macros | Recorded or hand-built step sequences (clicks, keys, text, scroll, waits, launching apps, focusing windows) with a library, per-macro hotkeys, repeat and speed control. |

Every tool can run in **foreground** mode (real OS input) or **background**
mode (input delivered to one picked window; the cursor and focus stay where
they are, and the target may stay minimized when the app allows it).

## Lessons from the previous attempt

The earlier `autoclicker.py` failed in background mode for concrete reasons:

1. A minimized window has an empty client rect, and the old resolver returned
   `None` whenever width or height was zero, so minimized targets never got a
   click.
2. Positions were saved as a fraction of the picked child's client area. When
   the window was minimized or relaid out, the fraction mapped to the wrong
   pixel.
3. It used `SendMessageTimeout`, which blocks on busy targets and throttles
   the click thread.
4. The Chromium UI Automation path only worked while the browser was in the
   foreground, the opposite of the goal.
5. Keyboard input could not be sent to a background window at all.

The new engine saves the exact child window handle and its client coordinates
at pick time. It uses `PostMessage`, which never blocks, and it re-resolves the
child from the root only when the saved handle has died. Keys go to the focused
control of the target's GUI thread. When that control is unknown, as it is for
a minimized window, they go to the picked control.

## Honest limits

No operating system has a universal way to make every background app accept
synthetic input. Background mode works with apps that read ordinary window
messages (Win32, WinForms, WPF, most Qt and GTK apps, Notepad, many launchers
and idle games). It usually does **not** work with apps that read raw input or
DirectInput (most 3D games), with anti-cheat-protected games, or with elevated
windows when I-DB Macro is not elevated. The UI has a **Test** button so users
can check a target before relying on it, and an optional "spoof focus" switch
that helps some engines that drop input while they are unfocused.

On Linux, background mode uses `XSendEvent`. Some toolkits ignore synthetic
events. Wayland does not allow global input injection or window lookup, so on
Wayland only XWayland windows are supported.

## Architecture

```
idb_macro/
  core/        pure logic, no Qt, fully unit-tested
    keys.py      key/combo parsing and normalisation
    timing.py    intervals, jitter, drift-free precise scheduler
    models.py    dataclasses + validated JSON (de)serialisation
    engine.py    ClickerRunner, KeyRunner, MacroRunner (thread + stop event)
    recorder.py  raw input events -> macro steps
    storage.py   config dir, atomic JSON writes, macro library
  platform/    OS input backends behind one interface
    base.py      Backend ABC, WindowTarget
    windows.py   SendInput (foreground) + PostMessage (background)
    x11.py       XTest (foreground) + XSendEvent (background)
    fallback.py  pynput-only, foreground only (Wayland/unknown)
  ui/          PySide6 interface
    theme.py     Intelligence Database design tokens + QSS
    splash.py    startup animation ported from the Control Center
    widgets.py   toggle, segmented control, stat tile, hotkey field...
    picker.py    full-screen point / window picker overlay
    pages/       autoclicker, keys, macros, settings
    main_window.py
  hotkeys.py   global hotkeys via pynput (ignores injected events)
  app.py       entry point
```

Runners take a `Backend` by injection, which lets the tests drive them with a
fake backend that records calls.

## Timing

Runners schedule against absolute deadlines (`perf_counter`), so jitter and
work time do not accumulate drift. They wait with `Event.wait` until about
2 ms before the deadline and busy-wait the rest. On Windows the process calls
`timeBeginPeriod(1)` while a runner is active. The minimum interval is 1 ms.

## Safety

- A global panic hotkey (default `F12`) stops everything.
- An optional fail-safe stops everything when the cursor is slammed into the
  top-left screen corner (foreground runs).
- Recording and hotkeys ignore injected input, so a running macro cannot
  trigger itself.
- Imported macro files are schema-validated with size limits. Every import
  shows a plain-text summary of what the macros do (including programs and
  their arguments) and needs confirmation; imported hotkeys and window handles
  are dropped.
- `launch` runs a program with an argument list, never through a shell.
- No network code, telemetry, or elevation.

## Startup animation

This is a direct port of `IntroSplashForm`. It uses the navy vertical gradient,
a 52 px ambient grid with a vignette, a radial blue glow behind the cube, the
cube image, the "Intelligence Database" wordmark in Segoe UI Bold `#1E67CE`,
and "Welcome, <user>" in the Control Center script font with a soft blue
stroke glow and an accent rule. It fades in over 720 ms (ease-out cubic),
holds while the main window builds (at least 900 ms), then fades out over
680 ms (ease-in quadratic). It can be disabled in Settings.

## Testing

- Unit tests for everything in `core/`.
- Backend integration test on Windows. A helper Qt window starts minimized in
  a subprocess, the Windows backend posts clicks and keys to it, and the test
  asserts that they arrived. The same test runs on Linux CI under Xvfb.
- GUI smoke test using the Qt offscreen platform. It builds every page and
  opens and closes dialogs.
- CI runs on Windows and Ubuntu with Python 3.10 and 3.12.

## Plan

1. Scaffold the repo: pyproject, licence, git init, venv.
2. Build `core/` with its tests (keys, timing, models, engine, recorder,
   storage).
3. Build the platform backends and the minimized-window integration test.
4. Add global hotkeys.
5. Build the UI: theme, splash, widgets, picker, then the four pages and the
   main window with a tray icon.
6. Run the GUI smoke test and review screenshots.
7. Write the docs: README, SECURITY, CONTRIBUTING, CHANGELOG, third-party
   notices.
8. Add CI and a PyInstaller build.
9. Run the audits: security, secrets, AI-comment cleanup, open-source
   readiness, Linux.
