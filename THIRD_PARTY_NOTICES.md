# Third-party notices

I-DB Macro's own source is MIT licensed (see [LICENSE](LICENSE)). It depends
on the following libraries, which keep their own licences. The source
repository contains none of their code.

| Component | Licence | Used for |
| --- | --- | --- |
| [Qt for Python (PySide6)](https://doc.qt.io/qtforpython-6/) | LGPL-3.0 (or commercial) | User interface |
| [pynput](https://github.com/moses-palmer/pynput) | LGPL-3.0 | Global hotkeys, recording, generic input fallback |
| [python-xlib](https://github.com/python-xlib/python-xlib) (Linux only) | LGPL-2.1 | X11 input backend |

PySide6 and pynput are used unmodified and loaded as ordinary Python
packages. Anyone who redistributes a bundled build (for example one made with
PyInstaller) must follow the LGPL: include the licence texts, and let users
replace those libraries with their own versions. The one-folder PyInstaller
build in `packaging/` keeps them as separate, replaceable files for this
reason.

## Brand assets

`src/idb_macro/assets/cube.png` (the Intelligence Database cube) and
`src/idb_macro/assets/welcome.ttf` (the "Control Center Script" face used for
the startup greeting) are original Intelligence Database artwork. They are
released with this project under the same MIT licence.
