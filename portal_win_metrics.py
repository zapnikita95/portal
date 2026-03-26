"""
Геометрия рабочей области экрана (учёт панели задач на Windows) для позиции виджета.
"""

from __future__ import annotations

import sys
from typing import Any, Optional, Tuple

WorkArea = Tuple[int, int, int, int]  # x, y, width, height


def primary_work_area_tk(root: Any) -> WorkArea:
    """
    Рабочая область в пикселях Tk (логические пиксели).
    Windows: SystemParametersInfo SPI_GETWORKAREA; иначе весь экран от Tk.
    """
    try:
        sw = int(root.winfo_screenwidth())
        sh = int(root.winfo_screenheight())
    except Exception:
        sw, sh = 1920, 1080
    ox, oy = 0, 0
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            SPI_GETWORKAREA = 48
            rect = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(
                SPI_GETWORKAREA, 0, ctypes.byref(rect), 0
            ):
                ox = int(rect.left)
                oy = int(rect.top)
                sw = max(1, int(rect.right - rect.left))
                sh = max(1, int(rect.bottom - rect.top))
        except Exception:
            pass
    return ox, oy, sw, sh
