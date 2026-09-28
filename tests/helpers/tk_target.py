"""A small window that logs the input it receives, used by the backend tests."""

import ctypes
import sys
import tkinter as tk

if sys.platform == "win32":
    # Match the backend's physical-pixel coordinates exactly.
    ctypes.windll.shcore.SetProcessDpiAwareness(2)


def log(*parts):
    print(*parts, flush=True)


root = tk.Tk()
root.title("IDB Macro test target")
root.geometry("420x300+120+120")
canvas = tk.Canvas(root, width=400, height=200, bg="white")
canvas.pack()
text = tk.StringVar()
entry = tk.Entry(root, textvariable=text)
entry.pack(fill="x")
text.trace_add("write", lambda *_: log("text", repr(text.get())))

canvas.bind("<ButtonPress>", lambda e: log("press", e.num, e.x, e.y))
canvas.bind("<ButtonRelease>", lambda e: log("release", e.num, e.x, e.y))
canvas.bind("<Double-Button-1>", lambda e: log("double", e.x, e.y))
canvas.bind("<MouseWheel>", lambda e: log("wheel", e.delta))
for seq in ("<Button-4>", "<Button-5>"):
    canvas.bind(seq, lambda e: log("wheel", 120 if e.num == 4 else -120))
entry.bind("<KeyPress>", lambda e: log("key", e.keysym, e.state & 0x4 != 0))

entry.focus_set()
root.update()
frame = root.wm_frame()
log("ready", int(frame, 16) if frame.startswith("0x") else root.winfo_id(), canvas.winfo_id(), entry.winfo_id())
if "--minimized" in sys.argv:
    root.iconify()
    root.update()
    log("minimized", root.state())
root.after(int(sys.argv[-1]) if sys.argv[-1].isdigit() else 20000, root.destroy)
root.mainloop()
