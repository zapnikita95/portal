# -*- coding: utf-8 -*-
"""
macOS: запрос прав при старте Portal.

- Универсальный доступ: AXIsProcessTrustedWithOptions(..., prompt=True) — система сама
  показывает диалог «Открыть настройки?», если приложению ещё не доверяют.
- Мониторинг ввода: публичного API «попросить разрешение» нет; показываем окно с кнопкой,
  которая открывает нужную панель «Конфиденциальность и безопасность».

Отключить авто-подсказки: PORTAL_SKIP_MAC_PERMISSION_PROMPT=1
"""
from __future__ import annotations

import os
import subprocess
import sys
from typing import Any, Optional


def skip_mac_permission_ui() -> bool:
    return os.environ.get("PORTAL_SKIP_MAC_PERMISSION_PROMPT", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def request_accessibility_trust_prompt() -> Optional[bool]:
    """
    Если Portal ещё не в списке «Универсальный доступ», macOS покажет стандартный запрос.
    Возвращает True если уже доверен, False если нет, None если API недоступен.
    """
    if sys.platform != "darwin" or skip_mac_permission_ui():
        return None
    try:
        from ApplicationServices import AXIsProcessTrustedWithOptions
        from Foundation import NSDictionary

        opts = NSDictionary.dictionaryWithDictionary_({"AXTrustedCheckOptionPrompt": True})
        return bool(AXIsProcessTrustedWithOptions(opts))
    except Exception:
        pass
    try:
        from Quartz import AXIsProcessTrustedWithOptions
        from Foundation import NSDictionary

        opts = NSDictionary.dictionaryWithDictionary_({"AXTrustedCheckOptionPrompt": True})
        return bool(AXIsProcessTrustedWithOptions(opts))
    except Exception:
        return None


def open_input_monitoring_settings() -> None:
    """Открыть раздел «Мониторинг ввода» (Listen Event)."""
    if sys.platform != "darwin":
        return
    urls = (
        "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
        "x-apple.systempreferences:com.apple.Settings.extension?privacy&path=Privacy/InputMonitoring",
    )
    for u in urls:
        try:
            subprocess.run(["open", u], check=False, timeout=15)
            return
        except Exception:
            continue


def open_accessibility_settings() -> None:
    if sys.platform != "darwin":
        return
    urls = (
        "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
        "x-apple.systempreferences:com.apple.Settings.extension?privacy&path=Privacy/Accessibility",
    )
    for u in urls:
        try:
            subprocess.run(["open", u], check=False, timeout=15)
            return
        except Exception:
            continue


def _tk_parent(main_app: Any):
    try:
        import tkinter as tk

        if isinstance(main_app, (tk.Tk, tk.Toplevel)):
            return main_app
        return main_app.winfo_toplevel()
    except Exception:
        return None


def show_input_monitoring_dialog(main_app: Any) -> None:
    """Окно с предложением открыть «Мониторинг ввода» (после неудачного NSEvent global)."""
    if sys.platform != "darwin" or skip_mac_permission_ui():
        return
    try:
        from tkinter import messagebox
    except Exception:
        return
    parent = _tk_parent(main_app)
    try:
        r = messagebox.askyesno(
            "Portal — мониторинг ввода",
            "Без разрешения «Мониторинг ввода» глобальные сочетания Cmd+Ctrl+P/C/V "
            "не работают в других приложениях.\n\n"
            "Если переключатель уже включён, а хоткеев нет — выключите и снова включите "
            "(или удалите строку и добавьте приложение заново после запуска Portal).\n\n"
            "Добавьте Portal (или тот Python/Terminal, из которого запускаете) в список "
            "и включите переключатель.\n\n"
            "Открыть раздел настроек сейчас?",
            parent=parent,
        )
        if r:
            open_input_monitoring_settings()
    except Exception:
        pass


def show_accessibility_followup_dialog(main_app: Any, trusted: Optional[bool]) -> None:
    """Если Accessibility всё ещё не выдан — напомнить и дать кнопку в настройки."""
    if sys.platform != "darwin" or skip_mac_permission_ui():
        return
    if trusted is not False:
        return
    try:
        from tkinter import messagebox
    except Exception:
        return
    parent = _tk_parent(main_app)
    try:
        r = messagebox.askyesno(
            "Portal — универсальный доступ",
            "Для части функций (буфер, перетаскивание) macOS может требовать "
            "«Универсальный доступ» для Portal.\n\n"
            "Открыть раздел настроек?",
            parent=parent,
        )
        if r:
            open_accessibility_settings()
    except Exception:
        pass


def schedule_mac_permission_flow(main_app: Any) -> None:
    """
    Вызывать с главного потока Tk: app.after(500, lambda: schedule_mac_permission_flow(app))
    """
    if sys.platform != "darwin" or skip_mac_permission_ui():
        return
    try:
        trusted = request_accessibility_trust_prompt()
    except Exception:
        trusted = None
    try:
        if main_app is not None and hasattr(main_app, "log"):
            if trusted is True:
                main_app.log("🔐 Универсальный доступ для Portal уже включён.")
            elif trusted is False:
                main_app.log(
                    "🔐 Если появилось системное окно — разрешите универсальный доступ для Portal "
                    "(или включи вручную в настройках)."
                )
            else:
                main_app.log(
                    "🔐 Диалог Accessibility недоступен (нет ApplicationServices в сборке). "
                    "При необходимости открой настройки вручную."
                )
    except Exception:
        pass
