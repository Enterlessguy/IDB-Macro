"""Behaves like a game loop: samples one key's held state once per frame.

Prints how many separate presses it saw, then exits. Windows only.
"""

import ctypes
import sys
import time

vk = int(sys.argv[1])
seconds = float(sys.argv[2])
frame = 1 / 60
user32 = ctypes.windll.user32
user32.GetAsyncKeyState.restype = ctypes.c_short

presses = 0
was_down = False
print("ready", flush=True)
end = time.perf_counter() + seconds
while time.perf_counter() < end:
    down = bool(user32.GetAsyncKeyState(vk) & 0x8000)
    if down and not was_down:
        presses += 1
    was_down = down
    time.sleep(frame)
print("presses", presses, flush=True)
