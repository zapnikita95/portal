"""
Проверка цепочки как у глобального хоткея: main_app.after(0, _toggle_ui) → портал виден.

Реальные клавиши здесь не эмулируем (нужны права/хуки), но если этот тест падает —
сломан сам показ виджета, а не только pynput.
"""

from __future__ import annotations

import sys
import time


def test_toggle_pipeline_matches_hotkey_callback() -> None:
    import customtkinter as ctk

    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    from portal import PortalApp
    from portal_widget import PortalWidget, GlobalHotkeyManager

    app = PortalApp()
    app.update_idletasks()
    widget = PortalWidget(app)
    widget.root.withdraw()
    app.update()

    mgr = GlobalHotkeyManager(widget, app)
    app.portal_widget_ref = widget
    app._hotkey_mgr = mgr
    # Как в pynput: только очередь → съедает PortalApp._drain_ui_signal_queue
    mgr.toggle_widget()
    time.sleep(0.15)
    for _ in range(200):
        app.update()
        if widget.is_visible():
            break

    try:
        assert widget.is_visible(), "очередь→_toggle_ui не показал портал"
    finally:
        try:
            widget.destroy()
        except Exception:
            pass
        try:
            app.destroy()
        except Exception:
            pass


def main() -> int:
    test_toggle_pipeline_matches_hotkey_callback()
    print("OK: hotkey pipeline (after→toggle→show)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
