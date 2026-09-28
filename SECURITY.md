# Security

## Reporting a problem

Please report vulnerabilities privately through GitHub's
[security advisory form](https://github.com/Enterlessguy/IDB-Macro/security/advisories/new)
rather than in a public issue. Include the version, your operating system and
the steps to reproduce. You should get a reply within a week.

## What IDB-Macro does and does not do

- **Network use is limited to updates.** The app only contacts GitHub, to
  check this repository's releases (at startup if enabled, and on the Updates
  page) and to download an update when you click install. There's no
  telemetry and no accounts, and nothing about you is sent.
- **Updates are verified.** Downloads must use HTTPS from GitHub hosts,
  including every redirect. The file's SHA-256 must match the checksum
  published with the release, otherwise it's deleted. Zip entries that would
  escape the update folder are refused, and the update is copied over the app
  folder without deleting anything else in it.
- **No elevation.** It never asks for administrator or root rights. Windows
  will not let it send input to apps running as administrator unless you start
  it that way yourself.
- **Local data only.** Settings and macros are JSON files in your user
  profile: `%APPDATA%\IDB-Macro` on Windows and `~/.config/idb-macro` on
  Linux. They never leave your machine.
- **Input is filtered.** Hotkeys and the recorder ignore input produced by
  software (the OS "injected" flag), so a running macro cannot trigger itself
  or end up in a recording.

## Macro files are code

A macro can press any key, type anything and click anywhere, so it can do
anything you could do at the keyboard, including opening a terminal. **Treat a
macro file from someone else like a script from them.** Imports are handled
like this:

- Every import shows a confirmation. It summarises what each macro does and
  lists every program it can start, with its arguments, before anything is
  added. That text is shown as plain text, so the file can't disguise it.
- Hotkeys in imported files are always removed, so a shared macro can't bind
  itself to a key you press every day. Window handles and control hints are
  removed too.
- Imported files are strictly validated. Unknown fields are dropped, numbers
  are range-checked, and sizes are capped: 20 MB per file, 500 macros,
  10,000 steps each, 10,000 characters of text per step, and limited nesting.
- "Launch program" runs the program directly with an argument list, never
  through a shell. Arguments are refused for `.bat` and `.cmd` files, because
  `cmd.exe` would re-parse them.

## Recording

The recorder saves what you type into the macro, in plain text in
`macros.json`. Don't type passwords while recording.

## Window titles

Titles of other windows (for example browser tabs) are always shown as plain
text, so a web page can't style or spoof the target shown in IDB-Macro.

## Emergency stop

The panic hotkey (default **F12**) stops every running tool and releases any
key or mouse button a tool was holding. With the fail-safe enabled (the
default), moving the cursor into the top-left corner of the main screen stops
foreground runs too.
