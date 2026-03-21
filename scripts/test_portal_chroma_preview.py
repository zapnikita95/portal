#!/usr/bin/env python3
"""
Проверка без Tk: один кадр GIF → RGB после snap/purge.

Запуск из папки portal:
  python3 scripts/test_portal_chroma_preview.py

Файл сохраняется В ПАПКУ ПРОЕКТА: portal/chroma_preview_test.png

Сейчас виджет по умолчанию использует НАСТОЯЩУЮ прозрачность (альфа), без хромакея на экране.

Этот скрипт проверяет только «запасной» путь: RGB для -transparentcolor.
В Preview фон на PNG будет фиолетовым — это норма для файла; живой виджет
при альфе показывает рабочий стол через прозрачные пиксели.
"""
from __future__ import annotations

import os
import sys

# корень проекта
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PIL import Image, ImageSequence  # noqa: E402


def main() -> None:
    from portal_widget import PortalWidget

    class _Stub:
        size = 220
        _chroma_rgb = (255, 0, 255)

    assets = os.path.join(ROOT, "assets", "portal_main.gif")
    if not os.path.isfile(assets):
        print("Нет", assets)
        return
    stub = _Stub()
    prep = PortalWidget._prepare_portal_frame_rgba.__get__(stub, PortalWidget)
    gif = Image.open(assets)
    gif.seek(0)
    rgba = prep(gif)
    r, g, b = 255, 0, 255
    bg = Image.new("RGBA", rgba.size, (r, g, b, 255))
    composed = Image.alpha_composite(bg, rgba).convert("RGB")
    composed = PortalWidget._snap_near_chroma_rgb(composed, r, g, b)
    composed = PortalWidget._purge_magenta_screen_rgb(composed, r, g, b)
    out = os.path.join(ROOT, "chroma_preview_test.png")
    composed.save(out)
    px = composed.load()
    for name, xy in [("corner", (2, 2)), ("mid-edge", (10, 109)), ("center", (110, 110))]:
        print(name, xy, "=", px[xy[0], xy[1]])
    print()
    print("Файл:", os.path.abspath(out))
    print("Углы (255,0,255) — проверка запасного хромакея; сам виджет — см. лог при старте «альфа + прозрачное окно».")


if __name__ == "__main__":
    main()
