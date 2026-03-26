"""
Фоновый трей Windows: закрытие главного окна не останавливает приём Portal.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    pystray = None


def _make_icon_image():
    im = Image.new("RGBA", (64, 64), (10, 12, 18, 255))
    dr = ImageDraw.Draw(im)
    dr.ellipse((6, 6, 58, 58), outline=(0, 168, 255, 255), width=4)
    dr.ellipse((18, 18, 46, 46), outline=(255, 107, 53, 255), width=3)
    return im


def start_tray(*, app: Any, on_open: Callable[[], None], on_quit: Callable[[], None]) -> bool:
    if pystray is None:
        return False

    image = _make_icon_image()
    holder: dict = {}

    def open_item(icon, item):
        try:
            app.after(0, on_open)
        except Exception:
            try:
                on_open()
            except Exception:
                pass

    def quit_item(icon, item):
        try:
            icon.stop()
        except Exception:
            pass
        try:
            app.after(0, on_quit)
        except Exception:
            try:
                on_quit()
            except Exception:
                pass

    menu = pystray.Menu(
        pystray.MenuItem("Portal — открыть окно", open_item),
        pystray.MenuItem("Выход", quit_item),
    )
    icon = pystray.Icon("PortalDesktop", image, "Portal", menu)
    holder["icon"] = icon
    app._portal_tray_icon_ref = holder

    def run_icon():
        try:
            icon.run()
        except Exception:
            pass

    threading.Thread(target=run_icon, daemon=True).start()
    return True


def stop_tray(app: Any) -> None:
    h = getattr(app, "_portal_tray_icon_ref", None)
    if not h:
        return
    ic = h.get("icon")
    if ic is None:
        return
    try:
        ic.stop()
    except Exception:
        pass
    h["icon"] = None
