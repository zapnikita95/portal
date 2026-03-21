"""
Смоук-тест: импорты, модуль буфера, создание окна CTk без долгого mainloop.
Запуск: python test_portal_smoke.py
"""

from __future__ import annotations

import sys


def test_clipboard_rich_import():
    import portal_clipboard_rich as p

    k, d = p.clipboard_snapshot()
    assert k in ("empty", "text", "image", "files")
    assert isinstance(d, dict)


def test_portal_app_window():
    import customtkinter as ctk

    ctk.set_appearance_mode("dark")
    from portal import PortalApp

    app = PortalApp()
    app.update_idletasks()
    app.update()
    assert hasattr(app, "log_text")
    txt = app.log_text.get("1.0", "end")
    assert "Готов" in txt or "Журнал" in txt or len(txt) > 0
    app.destroy()


def main() -> int:
    test_clipboard_rich_import()
    test_portal_app_window()
    print("OK: test_portal_smoke passed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
