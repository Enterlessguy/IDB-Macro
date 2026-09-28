# Changelog

## Unreleased

- Renamed the app from "I-DB Macro" to "IDB-Macro" to match the repository.
  Settings, saved setups and exported macro files are unaffected.

## 1.2.0

- Updates page: shows the latest GitHub release and its notes. The Windows
  app can download, verify (SHA-256) and install updates, and restart into
  the new version. It can check automatically at startup.
- 💡 explainers with animated examples for background clicking, key timing
  and hotkeys, macros, and smart mode, each with simple and technical text.

## 1.1.0

- Saved setups for the Autoclicker and Key Repeater: save, save as, rename,
  delete, import and export, with an unsaved-changes marker and an optional
  hotkey for each setup.
- New macro steps that run a saved setup, for a set time or until its own
  stop condition. Stopping the macro stops the setup too, and exported macros
  bundle the setups they use.
- Smart mode: presets for common uses, live tips about the current settings,
  and safety checks. Input stays in the window you started in (with held
  keys released while you're elsewhere), and clicks never hit the taskbar,
  the desktop or the app itself.
- Dumb mode: the whole app as one plain autoclicker, with its own settings.
- Fixed: key taps lasted about 0 ms, so games that read keys once per frame
  (Roblox, for example) missed most of them. Taps now last 40 ms by default
  (adjustable), and recorded macros keep the real press length.
- Fixed: switching the background target window kept the old window's click
  spots; "Add spot" rejected picks after the target app restarted; picking
  sent a stray mouse release to the app underneath.
- The app now explains that Chromium-based apps (Discord, browsers) ignore
  input while minimized.

## 1.0.0

First release.

- Autoclicker: clicks at the cursor, on a cycle of fixed spots, or in a
  background window. Supports left, right, middle, back and forward buttons;
  single, double, triple and hold clicks; interval or clicks-per-second
  timing; random timing and position variation; and stopping after a number
  of clicks or a length of time.
- Key Repeater: taps, press-and-holds or holds keys and combinations, either
  cycling through several or pressing them together, in the active app or a
  background window.
- Macros: record or build steps (click, mouse down/up, move, scroll, keys,
  key down/up, text, wait with random extra, focus window, launch program).
  Each macro has repeat, speed and a hotkey, and can target the foreground or
  a background window. Includes a library with import and export.
- Background engine for Windows: input goes to the exact control, works on
  minimized windows, and presents button and modifier state so toolkits that
  check `GetKeyState` accept it.
- X11 backend for Linux (XTEST for foreground input, `XSendEvent` for
  background input).
- System-wide hotkeys, a panic key, a fail-safe corner, a tray icon, and the
  Intelligence Database startup animation.
