#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проверка глобальных хоткеев macOS БЕЗ ручного круга «а попробуй ещё раз».

Что делает скрипт (автоматически):
  1) Поднимает тот же portal_mac_hotkey_helper.py, что и Portal, с pipe (как в приложении).
  2) Ждёт до --timeout секунд строку i cgevent_tap_ok или i nsevent_monitor_ok в stdout helper'а.
  3) Печатает ИТОГ: монитор глобальных клавиш создан или нет (права TCC / Quartz).

Что НИКТО из автоматики не может сделать:
  Эмулировать настоящее Cmd+Ctrl+P в чужом приложении без специальных прав/драйверов.
  Поэтому после зелёного ИТОГА — один осмысленный ручной шаг (см. в конце вывода).

Запуск из корня репозитория portal/:
  python3 scripts/verify_mac_hotkey_helper.py
  python3 scripts/verify_mac_hotkey_helper.py --timeout 6

Проверка именно собранного .app (те же права TCC, что в жизни):
  python3 scripts/verify_mac_hotkey_helper.py --bundle dist/Portal.app
"""

from __future__ import annotations

import argparse
import fcntl
import os
import subprocess
import sys
import threading
import time
from pathlib import Path


def _nonblock(fd: int) -> None:
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)


def _portal_exe_from_bundle(path: Path) -> Path:
    p = path.resolve()
    if p.suffix == ".app" or p.name.endswith(".app"):
        exe = p / "Contents" / "MacOS" / "Portal"
        if exe.is_file():
            return exe
    if p.is_file() and os.access(p, os.X_OK):
        return p
    raise FileNotFoundError(f"не найден исполняемый Portal: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка macOS hotkey-helper (глобальный монитор)")
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Секунд ждать подтверждения монитора (по умолчанию 5)",
    )
    parser.add_argument(
        "--bundle",
        type=str,
        default="",
        help="Путь к dist/Portal.app (или к бинарнику …/MacOS/Portal) — тест как в проде",
    )
    args = parser.parse_args()

    if sys.platform != "darwin":
        print("SKIP: только macOS (Darwin).")
        return 0

    root = Path(__file__).resolve().parent.parent
    use_frozen = bool((args.bundle or "").strip())
    if use_frozen:
        try:
            portal_exe = _portal_exe_from_bundle(Path(args.bundle.strip()))
        except FileNotFoundError as e:
            print(f"FAIL: {e}")
            return 2
        cmd: list[str] = [str(portal_exe)]
    else:
        helper = root / "portal_mac_hotkey_helper.py"
        if not helper.is_file():
            print(f"FAIL: нет файла {helper}")
            return 2
        cmd = [sys.executable, str(helper)]
        portal_exe = Path(sys.executable)

    hr, hw = os.pipe()
    try:
        _nonblock(hr)
    except OSError:
        pass

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PORTAL_HOTKEY_PIPE_FD"] = str(int(hw))
    if use_frozen:
        env["PORTAL_HOTKEY_HELPER_SUBPROCESS"] = "1"

    collected: list[str] = []
    lock = threading.Lock()

    def pump(stream, label: str) -> None:
        try:
            for line in stream:
                s = (line or "").rstrip()
                with lock:
                    collected.append(f"{label}:{s}")
        except Exception:
            pass

    cwd = str(portal_exe.parent) if use_frozen else str(root)
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
            text=True,
            cwd=cwd,
            env=env,
            close_fds=True,
            pass_fds=(int(hw),),
        )
    except Exception as e:
        os.close(hr)
        os.close(hw)
        print(f"FAIL: не удалось запустить helper: {e}")
        return 3

    # Родителю конец записи не нужен — закрываем, у child остаётся свой dup из pass_fds
    try:
        os.close(hw)
    except OSError:
        pass
    hw = -1

    threading.Thread(
        target=pump, args=(proc.stdout, "out"), daemon=True
    ).start()
    threading.Thread(
        target=pump, args=(proc.stderr, "err"), daemon=True
    ).start()

    deadline = time.monotonic() + float(args.timeout)
    ok_cg = False
    ok_ns = False
    err_lines: list[str] = []

    while time.monotonic() < deadline:
        with lock:
            for raw in collected:
                if "i cgevent_tap_ok" in raw:
                    ok_cg = True
                if "i nsevent_monitor_ok" in raw:
                    ok_ns = True
                if raw.startswith("err:e ") or "Traceback" in raw:
                    err_lines.append(raw)
        if ok_cg or ok_ns:
            break
        time.sleep(0.05)

    try:
        proc.kill()
    except Exception:
        pass
    try:
        proc.wait(timeout=2.0)
    except Exception:
        pass
    try:
        os.close(hr)
    except OSError:
        pass

    print("--- Собранные строки helper (out/err) ---")
    with lock:
        for line in collected:
            print(line)
    print("---")

    if ok_cg:
        print("ИТОГ: OK — CGEventTap поднят (глобальный слушатель клавиш работает на уровне ОС).")
        mode = "CGEventTap"
    elif ok_ns:
        print(
            "ИТОГ: OK — NSEvent global monitor поднят (глобальный слушатель клавиш работает на уровне ОС)."
        )
        print(
            "      (Сообщение «CGEventTap не создан» в stderr часто бывает даже при включённых правах — тогда используется NSEvent.)"
        )
        mode = "NSEvent"
    else:
        print("ИТОГ: FAIL — за отведённое время монитор не подтвердился.")
        print("       Чаще всего: нет «Мониторинг ввода» (и иногда «Универсальный доступ») для:")
        print(f"       {'бинарника ' + str(portal_exe) if use_frozen else 'интерпретатора ' + sys.executable}")
        print("       Для .app: python3 scripts/verify_mac_hotkey_helper.py --bundle dist/Portal.app")
        if err_lines:
            print("       Последние ошибки:")
            for e in err_lines[-8:]:
                print("        ", e)
        return 1

    # Проверка pipe: helper мог бы слать t/c/v — без реальной клавиши не проверяем.
    print()
    print("Ручной шаг (один раз, после OK выше):")
    print(f"  1) Запусти Portal (тот же способ, что обычно: .app или python3).")
    print(f"  2) Переключись в ЛЮБОЕ другое приложение (не окно Portal).")
    print(f"  3) Нажми Cmd+Ctrl+P (если LEGACY=1 — Cmd+Option+P).")
    print(f"  4) В журнале Portal должна появиться строка про глобальный хоткей / виджет.")
    print()
    print(f"Этот скрипт подтвердил только слой ОС: {mode}. Клавишу я нажать за тебя не могу.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
