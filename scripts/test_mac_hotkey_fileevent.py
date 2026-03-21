#!/usr/bin/env python3
"""
Проверка: на macOS Tk fileevent по pipe срабатывает даже при withdraw() (аналог свёрнутого окна).
Если тест падает — глобальные хоткеи через after() могут не доходить при свёрнутом Portal.
"""
from __future__ import annotations

import os
import sys
import time


def main() -> int:
    if sys.platform != "darwin":
        print("skip: not darwin", file=sys.stderr)
        return 0

    import fcntl
    import tkinter as tk

    r = tk.Tk()
    r.withdraw()
    pr, pw = os.pipe()
    try:
        fcntl.fcntl(pr, fcntl.F_SETFL, os.O_NONBLOCK)
    except OSError:
        os.close(pr)
        os.close(pw)
        print("FAIL: fcntl", file=sys.stderr)
        return 1

    fired: list[bool] = []

    def on_read(_fd, _mask):
        try:
            while True:
                chunk = os.read(pr, 64)
                if not chunk:
                    break
                fired.append(True)
        except BlockingIOError:
            pass

    try:
        r.tk.createfilehandler(pr, tk.READABLE, on_read)
    except Exception as e:
        os.close(pr)
        os.close(pw)
        print(f"FAIL: createfilehandler {e}", file=sys.stderr)
        return 1

    os.write(pw, b"t")

    t0 = time.monotonic()
    while time.monotonic() - t0 < 2.0:
        r.update_idletasks()
        r.update()
        if fired:
            break

    try:
        r.tk.deletefilehandler(pr)
    except Exception:
        pass
    os.close(pr)
    os.close(pw)
    try:
        r.destroy()
    except Exception:
        pass

    if not fired:
        print("FAIL: fileevent did not fire within 2s (withdrawn root)", file=sys.stderr)
        return 1
    print("OK: macOS Tk fileevent + pipe (withdrawn window)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
