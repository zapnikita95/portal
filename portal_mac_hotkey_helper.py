#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Отдельный процесс для глобальных хоткеев на macOS (без Tk — нет GIL-краша Python 3.13).

Порядок попыток:
  1) Quartz CGEventTap (listen-only) + CFRunLoopRun — самый стабильный цикл событий
  2) NSEvent global monitor + NSApplication.run()
  3) pynput GlobalHotKeys (запасной вариант)

Stdout: одна буква на строку (t / c / v).
Stderr: "e ..." ошибки, "i ..." инфо.

По умолчанию: Cmd+Ctrl+P/C/V.  LEGACY=1: Cmd+Option+P, Cmd+Shift+C/V.
"""
from __future__ import annotations

import os
import sys
import time
from typing import Optional

_KEY_P = 35
_KEY_C = 8
_KEY_V = 9
_NSCmd = 1 << 20
_NSAlt = 1 << 19
_NSShift = 1 << 17
_NSCtrl = 1 << 18
_NSKeyDownMask = 1 << 10


def _is_legacy() -> bool:
    return os.environ.get("PORTAL_MAC_HOTKEY_LEGACY", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _pipe_write_fd() -> Optional[int]:
    """Родитель передаёт fd записи в pipe (pass_fds) — без stdout/буферов и отдельного потока."""
    raw = os.environ.get("PORTAL_HOTKEY_PIPE_FD", "").strip()
    if raw.isdigit():
        return int(raw)
    return None


_PIPE_HOTKEY_W: Optional[int] = _pipe_write_fd()


def _emit(c: str) -> None:
    fd = _PIPE_HOTKEY_W
    if fd is not None:
        try:
            os.write(fd, c.encode("ascii"))
            return
        except Exception:
            pass
    try:
        sys.stdout.write(c + "\n")
        sys.stdout.flush()
    except Exception:
        pass


def _match_hotkey(flags: int, keycode: int) -> str | None:
    """Вернуть 't'|'c'|'v' или None. flags — CG или NSEvent-подобная маска."""
    # Только «чистые» модификаторы: Fn/Caps/secondary не ломают Cmd+Ctrl
    f = int(flags) & (_NSCmd | _NSAlt | _NSShift | _NSCtrl)
    kc = int(keycode)
    if _is_legacy():
        if kc == _KEY_P and (f & _NSCmd) and (f & _NSAlt) and not (f & _NSShift):
            return "t"
        if kc == _KEY_C and (f & _NSCmd) and (f & _NSShift) and not (f & _NSAlt):
            return "c"
        if kc == _KEY_V and (f & _NSCmd) and (f & _NSShift) and not (f & _NSAlt):
            return "v"
        if kc == _KEY_V and (f & _NSCmd) and (f & _NSAlt) and not (f & _NSShift):
            return "v"
        return None
    if kc == _KEY_P and (f & _NSCmd) and (f & _NSCtrl) and not (f & _NSAlt) and not (f & _NSShift):
        return "t"
    if kc == _KEY_C and (f & _NSCmd) and (f & _NSCtrl) and not (f & _NSAlt) and not (f & _NSShift):
        return "c"
    if kc == _KEY_V and (f & _NSCmd) and (f & _NSCtrl) and not (f & _NSAlt) and not (f & _NSShift):
        return "v"
    return None


def _check_nsevent(event) -> None:
    try:
        try:
            from AppKit import NSDeviceIndependentModifierFlagsMask

            mask = int(NSDeviceIndependentModifierFlagsMask)
        except Exception:
            mask = 0xFFFF0000
        f = int(event.modifierFlags()) & mask
        kc = int(event.keyCode())
        try:
            if event.isARepeat():
                return
        except Exception:
            pass
        cmd = _match_hotkey(f, kc)
        if cmd:
            _emit(cmd)
    except Exception:
        pass


def _real_exe() -> str:
    try:
        return os.path.realpath(sys.executable)
    except Exception:
        return sys.executable


def main_cg_event_tap() -> bool:
    """
    CGEventTap (listen-only) + CFRunLoop — надёжнее, чем ручной NSRunLoop.runUntilDate.
    """
    try:
        import Quartz
    except ImportError:
        print(
            "e Quartz не найден — pip install pyobjc-framework-Quartz",
            file=sys.stderr,
            flush=True,
        )
        return False

    mask = Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
    tap_ref: list = [None]

    disabled_types = []
    for name in ("kCGEventTapDisabledByTimeout", "kCGEventTapDisabledByUserInput"):
        v = getattr(Quartz, name, None)
        if v is not None:
            disabled_types.append(v)

    def callback(proxy, typ, event, refcon):  # noqa: ARG001
        try:
            if tap_ref[0] is not None and typ in disabled_types:
                Quartz.CGEventTapEnable(tap_ref[0], True)
                return event
        except Exception:
            pass

        if typ != Quartz.kCGEventKeyDown:
            return event

        try:
            if Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventAutorepeat):
                return event
        except Exception:
            pass

        try:
            flags = int(Quartz.CGEventGetFlags(event))
            kc = int(
                Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
            )
        except Exception:
            return event

        # CGEventFlags совпадают по битам с NSEvent для Cmd/Ctrl/Alt/Shift
        cmd = _match_hotkey(flags, kc)
        if cmd:
            _emit(cmd)
        return event

    tap = Quartz.CGEventTapCreate(
        Quartz.kCGSessionEventTap,
        Quartz.kCGHeadInsertEventTap,
        Quartz.kCGEventTapOptionListenOnly,
        mask,
        callback,
        None,
    )
    if not tap and os.environ.get("PORTAL_MAC_HOTKEY_TRY_HID_TAP", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        tap = Quartz.CGEventTapCreate(
            Quartz.kCGHIDEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,
            mask,
            callback,
            None,
        )
    if not tap:
        print(
            "e CGEventTap не создан — это НЕ значит автоматически «ты не дал Мониторинг ввода». "
            "На macOS tap иногда не создаётся при уже включённых переключателях: сменилась подпись/путь "
            "после новой сборки .app, в списке TCC другой python3, «залипшая» запись. "
            "Что сделать: выключи и снова включи переключатель у **этого** приложения "
            "(или удали строку и добавь заново после запуска Portal). "
            "Дальше helper поднимает **NSEvent** — глобальные хоткеи часто работают и без CGEventTap.\n"
            f"  Бинарник этого процесса (сверь с «Мониторинг ввода»): {_real_exe()}",
            file=sys.stderr,
            flush=True,
        )
        return False

    tap_ref[0] = tap
    run_loop_source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
    Quartz.CFRunLoopAddSource(
        Quartz.CFRunLoopGetCurrent(),
        run_loop_source,
        Quartz.kCFRunLoopCommonModes,
    )
    Quartz.CGEventTapEnable(tap, True)

    print("i cgevent_tap_ok", flush=True)

    try:
        Quartz.CFRunLoopRun()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            Quartz.CGEventTapEnable(tap, False)
            Quartz.CFRunLoopRemoveSource(
                Quartz.CFRunLoopGetCurrent(),
                run_loop_source,
                Quartz.kCFRunLoopCommonModes,
            )
        except Exception:
            pass
    return True


def main_nsevent() -> bool:
    """NSEvent global monitor + полноценный NSApp.run() (не runUntilDate в цикле)."""
    try:
        from AppKit import NSEvent, NSApplication
    except ImportError:
        print("e AppKit недоступен — попробуем pynput", file=sys.stderr, flush=True)
        return False

    app = NSApplication.sharedApplication()
    try:
        app.setActivationPolicy_(1)  # Accessory
    except Exception:
        pass
    try:
        app.finishLaunching()
    except Exception:
        pass

    monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
        _NSKeyDownMask, _check_nsevent
    )
    if not monitor:
        print(
            "e NSEvent global monitor не создан (права «Мониторинг ввода» / «Универсальный доступ»).\n"
            "  → Добавь Portal.app в списки и перезапусти Portal.",
            file=sys.stderr,
            flush=True,
        )
        return False

    print("i nsevent_monitor_ok", flush=True)
    print(
        "i Проверка глобальных хоткеев: переключись в другое приложение (Safari, Terminal), "
        "нажми Cmd+Ctrl+P — в журнале Portal должна появиться строка «Глобальный хоткей». "
        "Если только «Tk bind» при фокусе на Portal — монитор не получает события; проверь «Мониторинг ввода» для Python.",
        flush=True,
    )

    try:
        app.run()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            NSEvent.removeMonitor_(monitor)
        except Exception:
            pass
    return True


def main_pynput() -> None:
    try:
        from pynput import keyboard
    except ImportError:
        print("e pynput не установлен", file=sys.stderr, flush=True)
        return

    if _is_legacy():
        combo = {
            "<cmd>+<alt>+p": lambda: _emit("t"),
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
    # В portal_hotkey_debug.log попадёт через stdout → out_reader родителя
    print(f"i hotkey-helper exe {_real_exe()}", flush=True)
    # Сначала NSEvent: при конфликте с другими CGEventTap (др. приложения) часто стабильнее для Chrome и т.д.
    if os.environ.get("PORTAL_MAC_HOTKEY_CG_FIRST", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        if main_cg_event_tap():
            return
        if main_nsevent():
            return
    else:
        if main_nsevent():
            return
        if main_cg_event_tap():
            return
    # Python 3.13: pynput на Darwin ловит TypeError: ThreadHandle is not callable — не используем.
    if sys.version_info >= (3, 13) and sys.platform == "darwin":
        print(
            "e hotkey-helper: CGEventTap и NSEvent недоступны; на Python 3.13+ pynput на macOS отключён "
            "(баг pynput). Проверь «Мониторинг ввода» для Portal.app и перезапусти приложение.",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(1)
    print("i fallback pynput", flush=True)
    main_pynput()


if __name__ == "__main__":
    main()
