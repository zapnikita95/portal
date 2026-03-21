#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Отдельный процесс для глобальных хоткеев на macOS (pynput).
Не импортирует Tk — иначе с CGEventTap часто Trace/BPT trap в одном процессе с Python 3.13.

Печатает в stdout по одной букве на строку:
  t — переключить виджет
  c — отправить буфер
  v — забрать буфер

По умолчанию: Cmd+Ctrl и дубли Cmd+Option+P, Cmd+Shift+C/V, Cmd+Option+V (как в Tk bind_all).
LEGACY=1: только Cmd+Option+P и Cmd+Shift+C/V (без Cmd+Ctrl).
"""
from __future__ import annotations

import os
import sys


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
        # Все «обычные» и «старые» сочетания сразу — иначе при отсутствии LEGACY глобально
        # работал только Cmd+Ctrl, а в интерфейсе часто пишут Cmd+Shift / Cmd+Option+P.
        combo = {
            "<cmd>+<ctrl>+p": lambda: print("t", flush=True),
            "<cmd>+<alt>+p": lambda: print("t", flush=True),
            "<cmd>+<ctrl>+c": lambda: print("c", flush=True),
            "<cmd>+<shift>+c": lambda: print("c", flush=True),
            "<cmd>+<ctrl>+v": lambda: print("v", flush=True),
            "<cmd>+<shift>+v": lambda: print("v", flush=True),
            "<cmd>+<alt>+v": lambda: print("v", flush=True),
        }
    # suppress=False: suppress=True на macOS ломает ввод клавиатуры в целом (CGEventTap).
    try:
        with keyboard.GlobalHotKeys(combo, suppress=False) as h:
            h.join()
    except Exception as e:
        print(f"e {e!r}", flush=True, file=sys.stderr)


if __name__ == "__main__":
    main()
