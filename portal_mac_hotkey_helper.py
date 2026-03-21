#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Отдельный процесс для глобальных хоткеев на macOS (pynput).
Не импортирует Tk — иначе с CGEventTap часто Trace/BPT trap в одном процессе с Python 3.13.

Печатает в stdout по одной букве на строку:
  t — переключить виджет
  c — отправить буфер
  v — забрать буфер

По умолчанию: только Cmd+Ctrl+P / C / V (меньше конфликтов с Terminal и др.).
LEGACY=1: Cmd+Option+P и Cmd+Shift+C/V (без Cmd+Ctrl).
"""
from __future__ import annotations

import os
import sys
import time


def main() -> None:
    try:
        from pynput import keyboard
    except ImportError:
        print("e import pynput", flush=True)
        return

    legacy = os.environ.get("PORTAL_MAC_HOTKEY_LEGACY", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if legacy:
        combo = {
            "<cmd>+<alt>+p": lambda: print("t", flush=True),
            "<cmd>+<shift>+c": lambda: print("c", flush=True),
            "<cmd>+<shift>+v": lambda: print("v", flush=True),
        }
    else:
        combo = {
            "<cmd>+<ctrl>+p": lambda: print("t", flush=True),
            "<cmd>+<ctrl>+c": lambda: print("c", flush=True),
            "<cmd>+<ctrl>+v": lambda: print("v", flush=True),
        }
    # suppress=False: suppress=True на macOS ломает ввод клавиатуры в целом (CGEventTap).
    # macOS иногда снимает event tap — pynput выходит из join(); без цикла процесс умирал
    # и глобальные хоткеи «через раз». Пересоздаём слушатель с бэкоффом.
    delay = 1.25
    cycle = 0
    while True:
        cycle += 1
        try:
            if cycle > 1:
                print(f"i hotkey_listener_restart n={cycle} after {delay:.1f}s", flush=True)
            with keyboard.GlobalHotKeys(combo, suppress=False) as h:
                h.join()
        except KeyboardInterrupt:
            raise SystemExit(0) from None
        except Exception as e:
            print(f"e {e!r}", flush=True, file=sys.stderr)
        time.sleep(delay)
        delay = min(delay * 1.35, 30.0)


if __name__ == "__main__":
    main()
