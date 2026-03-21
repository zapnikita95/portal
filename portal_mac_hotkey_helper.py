#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Отдельный процесс для глобальных хоткеев на macOS.
Без Tk — поэтому NSEvent/CGEventTap не вызывает GIL-краша с Python 3.13.

Stdout: одна буква на строку (t / c / v).
Stderr: строки "e <текст>" при ошибках, "i <текст>" — инфо.

По умолчанию: Cmd+Ctrl+P/C/V.  LEGACY=1: Cmd+Option+P, Cmd+Shift+C/V.
"""
from __future__ import annotations

import os
import sys
import time

_KEY_P = 35
_KEY_C = 8
_KEY_V = 9
_NSCmd   = 1 << 20
_NSAlt   = 1 << 19
_NSShift = 1 << 17
_NSCtrl  = 1 << 18
_NSKeyDownMask = 1 << 10


def _is_legacy() -> bool:
    return os.environ.get("PORTAL_MAC_HOTKEY_LEGACY", "").strip().lower() in (
        "1", "true", "yes"
    )


def _emit(c: str) -> None:
    try:
        sys.stdout.write(c + "\n")
        sys.stdout.flush()
    except Exception:
        pass


def _check_event(event) -> None:
    """Вызывается из NSEvent callback; только os-уровень — без очереди Tk."""
    try:
        try:
            from AppKit import NSDeviceIndependentModifierFlagsMask
            mask = int(NSDeviceIndependentModifierFlagsMask)
        except Exception:
            mask = 0xFFFF0000
        f  = int(event.modifierFlags()) & mask
        kc = int(event.keyCode())
        if _is_legacy():
            if kc == _KEY_P and (f & _NSCmd) and (f & _NSAlt) and not (f & _NSShift):
                _emit("t")
            elif kc == _KEY_C and (f & _NSCmd) and (f & _NSShift) and not (f & _NSAlt):
                _emit("c")
            elif kc == _KEY_V and (f & _NSCmd) and (f & _NSShift) and not (f & _NSAlt):
                _emit("v")
            elif kc == _KEY_V and (f & _NSCmd) and (f & _NSAlt) and not (f & _NSShift):
                _emit("v")
        else:
            if kc == _KEY_P and (f & _NSCmd) and (f & _NSCtrl) and not (f & _NSAlt) and not (f & _NSShift):
                _emit("t")
            elif kc == _KEY_C and (f & _NSCmd) and (f & _NSCtrl) and not (f & _NSAlt) and not (f & _NSShift):
                _emit("c")
            elif kc == _KEY_V and (f & _NSCmd) and (f & _NSCtrl) and not (f & _NSAlt) and not (f & _NSShift):
                _emit("v")
    except Exception:
        pass


def main_nsevent() -> bool:
    """
    NSEvent global monitor в этом процессе (без Tk → нет GIL-краша).
    Возвращает True если монитор запущен и отработал до конца.
    """
    try:
        from AppKit import NSEvent, NSApplication
        from Foundation import NSRunLoop, NSDate
    except ImportError:
        print("e AppKit/Foundation недоступны — попробуем pynput", file=sys.stderr, flush=True)
        return False

    # Инициализируем NSApp без Dock-иконки (helper-процесс)
    app = NSApplication.sharedApplication()
    try:
        app.setActivationPolicy_(1)  # NSApplicationActivationPolicyAccessory
    except Exception:
        pass

    monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
        _NSKeyDownMask, _check_event
    )
    if not monitor:
        print(
            "e NSEvent global monitor не создан.\n"
            "  → Системные настройки → Конфиденциальность → Мониторинг ввода\n"
            "    и Универсальный доступ → добавь Portal (или Python, если из терминала).\n"
            "  → После добавления прав ПЕРЕЗАПУСТИ Portal.",
            file=sys.stderr,
            flush=True,
        )
        return False

    print("i nsevent_monitor_ok", flush=True)

    run_loop = NSRunLoop.currentRunLoop()
    try:
        while True:
            run_loop.runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.5))
    except KeyboardInterrupt:
        pass
    finally:
        try:
            NSEvent.removeMonitor_(monitor)
        except Exception:
            pass
    return True


def main_pynput() -> None:
    """Запасной вариант: pynput GlobalHotKeys с циклом перезапуска."""
    try:
        from pynput import keyboard
    except ImportError:
        print("e pynput не установлен", file=sys.stderr, flush=True)
        return

    legacy = _is_legacy()
    if legacy:
        combo = {
            "<cmd>+<alt>+p":   lambda: _emit("t"),
            "<cmd>+<shift>+c": lambda: _emit("c"),
            "<cmd>+<shift>+v": lambda: _emit("v"),
        }
    else:
        combo = {
            "<cmd>+<ctrl>+p": lambda: _emit("t"),
            "<cmd>+<ctrl>+c": lambda: _emit("c"),
            "<cmd>+<ctrl>+v": lambda: _emit("v"),
        }

    delay = 1.5
    cycle = 0
    while True:
        cycle += 1
        try:
            if cycle > 1:
                print(f"i pynput_restart #{cycle} (backoff {delay:.1f}s)", flush=True)
            with keyboard.GlobalHotKeys(combo, suppress=False) as h:
                print("i pynput_ok", flush=True)
                h.join()
        except KeyboardInterrupt:
            raise SystemExit(0) from None
        except Exception as e:
            print(f"e pynput: {e!r}", file=sys.stderr, flush=True)
        time.sleep(delay)
        delay = min(delay * 1.35, 30.0)


def main() -> None:
    # NSEvent в subprocess — без Tk-краша, надёжнее на Python 3.13
    if main_nsevent():
        return
    # Fallback: pynput (нужны те же права, но другой механизм)
    print("i fallback pynput", flush=True)
    main_pynput()


if __name__ == "__main__":
    main()
