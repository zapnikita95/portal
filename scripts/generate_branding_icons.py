#!/usr/bin/env python3
"""
Генерация иконок для PyInstaller и Android из assets/portal_main.gif
(первый кадр, хромакей #FF00FF как у виджета Portal → прозрачный фон).

Выход:
  - assets/branding/portal_icon.png (квадрат 1024, RGBA)
  - portal.ico (Windows)
  - portal.icns (macOS, sips + iconutil)
  - portal-android/assets/icon.png (копия PNG для лаунчера)
  - portal-android/assets/portal_main.gif (копия для анимации в приложении)

Запуск из корня репозитория: python3 scripts/generate_branding_icons.py
"""
from __future__ import annotations

import math
import shutil
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_GIF_SRC = _ROOT / "assets" / "portal_main.gif"
_FALLBACK_SRC = _ROOT / "assets" / "branding" / "portal_icon.png"
_OUT_DIR = _ROOT / "assets" / "branding"
_ICON_PX = 1024
_CHROMA = (255, 0, 255)


def _prepare_portal_frame_rgba(frame, out_size: int = _ICON_PX):
    """Упрощённая копия логики portal_widget._prepare_portal_frame_rgba для CLI (без tk)."""
    try:
        from PIL import Image, ImageFilter
    except ImportError:
        print("Need Pillow: pip install pillow", file=sys.stderr)
        raise

    img = frame.convert("RGBA")
    w, h = img.size
    sq = min(w, h)
    left = (w - sq) // 2
    top = (h - sq) // 2
    img = img.crop((left, top, left + sq, top + sq))
    img = img.resize((out_size, out_size), Image.Resampling.LANCZOS)

    cr, cg, cb = _CHROMA
    chroma_r2 = 105 * 105
    size = out_size
    cx = (size - 1) * 0.5
    cy = (size - 1) * 0.5
    rx = max(size * 0.44, 1.0)
    ry = max(size * 0.50, 1.0)

    px = img.load()
    for y in range(size):
        for x in range(size):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            d2 = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
            if d2 <= chroma_r2:
                px[x, y] = (0, 0, 0, 0)
                continue
            if r >= 130 and b >= 130 and g <= 135 and (r + b) >= (g * 2.4 + 80):
                px[x, y] = (0, 0, 0, 0)
                continue
            dx = (x - cx) / rx
            dy = (y - cy) / ry
            ell = math.hypot(dx, dy)
            luma = (r + g + b) / 3.0
            mn, mx = min(r, g, b), max(r, g, b)
            grayish = (mx - mn) < 34
            if ell > 0.44 and grayish and luma < 54:
                px[x, y] = (0, 0, 0, 0)
                continue
            if ell > 0.52 and luma < 40:
                px[x, y] = (0, 0, 0, 0)
                continue

    rch, gch, bch, ach = img.split()
    ach = ach.filter(ImageFilter.GaussianBlur(0.45))
    return Image.merge("RGBA", (rch, gch, bch, ach))


def _render_icon_png_from_gif() -> Path | None:
    from PIL import Image

    if not _GIF_SRC.is_file():
        return None
    im = Image.open(_GIF_SRC)
    try:
        im.seek(0)
    except EOFError:
        return None
    rgba = _prepare_portal_frame_rgba(im, _ICON_PX)
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = _OUT_DIR / "portal_icon.png"
    rgba.save(out, format="PNG")
    print("OK:", out, "(from portal_main.gif frame 0)")
    return out


def _png_to_ico(png_path: Path, ico_path: Path) -> bool:
    try:
        from PIL import Image
    except ImportError:
        print("Need Pillow: pip install pillow", file=sys.stderr)
        return False
    im = Image.open(png_path).convert("RGBA")
    try:
        im.save(
            ico_path,
            format="ICO",
            sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )
    except TypeError:
        sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
        frames = [im.resize(s, Image.Resampling.LANCZOS) for s in sizes]
        frames[0].save(
            ico_path,
            format="ICO",
            append_images=frames[1:],
        )
    print("OK:", ico_path)
    return True


def _png_to_icns_mac(png_path: Path, icns_path: Path) -> bool:
    if sys.platform != "darwin":
        print(
            "Skip .icns (macOS only; build .app on Mac or add portal.icns)",
            file=sys.stderr,
        )
        return False
    sips = shutil.which("sips")
    iconutil = shutil.which("iconutil")
    if not sips or not iconutil:
        print("Missing sips/iconutil", file=sys.stderr)
        return False
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        iconset = tdp / "icon.iconset"
        iconset.mkdir()
        spec = [
            ("icon_16x16.png", 16),
            ("icon_16x16@2x.png", 32),
            ("icon_32x32.png", 32),
            ("icon_32x32@2x.png", 64),
            ("icon_128x128.png", 128),
            ("icon_128x128@2x.png", 256),
            ("icon_256x256.png", 256),
            ("icon_256x256@2x.png", 512),
            ("icon_512x512.png", 512),
            ("icon_512x512@2x.png", 1024),
        ]
        for name, dim in spec:
            out = iconset / name
            r = subprocess.run(
                [
                    sips,
                    "-s",
                    "format",
                    "png",
                    "-z",
                    str(dim),
                    str(dim),
                    str(png_path),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
            )
            if r.returncode != 0:
                print(r.stderr or r.stdout, file=sys.stderr)
                return False
        r2 = subprocess.run(
            [iconutil, "-c", "icns", str(iconset), "-o", str(icns_path)],
            capture_output=True,
            text=True,
        )
        if r2.returncode != 0:
            print(r2.stderr or r2.stdout, file=sys.stderr)
            return False
    print("OK:", icns_path)
    return True


def main() -> int:
    png_src: Path | None = _render_icon_png_from_gif()
    if png_src is None:
        if _FALLBACK_SRC.is_file():
            print(
                f"Missing {_GIF_SRC.name}, using fallback {_FALLBACK_SRC}",
                file=sys.stderr,
            )
            png_src = _FALLBACK_SRC
        else:
            print(f"Missing both {_GIF_SRC} and {_FALLBACK_SRC}", file=sys.stderr)
            return 1

    ico = _OUT_DIR / "portal.ico"
    icns = _OUT_DIR / "portal.icns"
    if not _png_to_ico(png_src, ico):
        return 1
    _png_to_icns_mac(png_src, icns)

    and_assets = _ROOT / "portal-android" / "assets"
    and_assets.mkdir(parents=True, exist_ok=True)
    dst = and_assets / "icon.png"
    shutil.copyfile(png_src, dst)
    print("OK:", dst)
    gif_app = and_assets / "portal_main.gif"
    if _GIF_SRC.is_file():
        shutil.copyfile(_GIF_SRC, gif_app)
        print("OK:", gif_app, "(Android assets copy)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
