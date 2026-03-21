#!/usr/bin/env python3
"""
Генерация иконок для PyInstaller и Android из assets/branding/portal_icon.png
  - portal.ico (Windows)
  - portal.icns (только macOS, через sips + iconutil)

Запуск из корня репозитория: python3 scripts/generate_branding_icons.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "assets" / "branding" / "portal_icon.png"
_OUT_DIR = _ROOT / "assets" / "branding"


def _png_to_ico(png_path: Path, ico_path: Path) -> bool:
    try:
        from PIL import Image
    except ImportError:
        print("Нужен Pillow: pip install pillow", file=sys.stderr)
        return False
    im = Image.open(png_path).convert("RGBA")
    try:
        im.save(
            ico_path,
            format="ICO",
            sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )
    except TypeError:
        # Старый Pillow: несколько кадров вручную
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
        print("Пропуск .icns (только macOS; на Windows/Linux собери .app на Mac или положи готовый portal.icns)")
        return False
    sips = shutil.which("sips")
    iconutil = shutil.which("iconutil")
    if not sips or not iconutil:
        print("Нет sips/iconutil", file=sys.stderr)
        return False
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        iconset = tdp / "icon.iconset"
        iconset.mkdir()
        # Типичный набор для iconutil
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
    if not _SRC.is_file():
        print(f"Нет исходника: {_SRC}", file=sys.stderr)
        return 1
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    ico = _OUT_DIR / "portal.ico"
    icns = _OUT_DIR / "portal.icns"
    if not _png_to_ico(_SRC, ico):
        return 1
    _png_to_icns_mac(_SRC, icns)
    # Копия для Android (launcher + экран настроек)
    and_assets = _ROOT / "portal-android" / "assets"
    and_assets.mkdir(parents=True, exist_ok=True)
    dst = and_assets / "icon.png"
    shutil.copyfile(_SRC, dst)
    print("OK:", dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
