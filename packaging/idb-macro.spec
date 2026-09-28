# PyInstaller spec for a one-folder build.
#
#   pyinstaller packaging/idb-macro.spec
#
# One-folder (not one-file) keeps the LGPL Qt and pynput libraries as
# separate files users can replace, and avoids unpacking to a temp directory
# on every start.

import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
ASSETS = ROOT / "src" / "idb_macro" / "assets"

a = Analysis(
    [str(ROOT / "packaging" / "launch.py")],
    pathex=[str(ROOT / "src")],
    datas=[(str(ASSETS), "idb_macro/assets"), (str(ROOT / "LICENSE"), "."),
           (str(ROOT / "THIRD_PARTY_NOTICES.md"), ".")],
    hiddenimports=["pynput.keyboard._win32", "pynput.mouse._win32"] if sys.platform == "win32"
    else ["pynput.keyboard._xorg", "pynput.mouse._xorg", "Xlib.ext.xtest"],
    excludes=["tkinter", "unittest", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="IDB-Macro",
    console=False,
    icon=str(ROOT / "packaging" / "idb-macro.ico") if sys.platform == "win32" else None,
    version=str(ROOT / "packaging" / "version_info.txt") if sys.platform == "win32" else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="IDB-Macro")
