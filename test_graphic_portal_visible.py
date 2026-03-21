"""
Графический смоук-тест: виджет-портал после show() реально отображается (winfo_viewable).

Запуск (нужен рабочий дисплей / сессия с GUI):
  python test_graphic_portal_visible.py

Если падает в CI без монитора — это ожидаемо; локально на ПК должно быть OK.
"""

from __future__ import annotations

import sys


def test_graphic_portal_visible() -> None:
    import customtkinter as ctk

    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    from portal import PortalApp
    from portal_widget import PortalWidget

    app = PortalApp()
    app.update_idletasks()

    widget = PortalWidget(app)
    widget.root.withdraw()
    app.update()

    widget.show()

    visible = False
    for _ in range(300):
        app.update()
        try:
            if widget.is_visible():
                visible = True
                break
        except Exception:
            pass

    try:
        assert visible, (
            "Графический портал не стал видимым после show(). "
            "Запусти вручную: python portal.py --show-portal"
        )
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
    test_graphic_portal_visible()
    print("OK: graphic portal visible after show()", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
