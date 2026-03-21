"""
Импорт MP4/WebP/GIF в assets/ для виджета-портала.

Пример (Windows, «тот самый» портал из tumblr):
  python import_portal_from_mp4.py "C:\\Users\\1\\Downloads\\tumblr_mm55e88N8H1rnir1do1_500.gif.mp4"

Нужно одно из: ffmpeg в PATH, либо: pip install imageio imageio-ffmpeg
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _assets_dir() -> Path:
    return Path(__file__).resolve().parent / "assets"


def _try_ffmpeg(input_path: Path, out_gif: Path, size: int, fps: float) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    # Палитра + gif: фон паддинга = почти чёрный под хромакей
    vf = (
        f"fps={fps},scale={size}:{size}:force_original_aspect_ratio=decrease,"
        f"pad={size}:{size}:(ow-iw)/2:(oh-ih)/2:color=#010101,"
        f"split[s0][s1];[s0]palettegen=max_colors=128[p];[s1][p]paletteuse"
    )
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(input_path),
        "-lavfi",
        vf,
        str(out_gif),
    ]
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        return r.returncode == 0 and out_gif.exists() and out_gif.stat().st_size > 0
    except Exception:
        return False


def _try_imageio(input_path: Path, out_gif: Path, size: int, fps: float) -> bool:
    """Читает видео через imageio + встроенный ffmpeg (imageio-ffmpeg), без системного ffmpeg."""
    try:
        import imageio.v2 as imageio
    except ImportError:
        return False
    from PIL import Image

    try:
        reader = imageio.get_reader(str(input_path), "ffmpeg")
    except Exception as e:
        print(f"imageio ffmpeg: не открылось видео: {e}")
        return False

    meta = {}
    try:
        meta = reader.get_meta_data() or {}
    except Exception:
        pass
    src_fps = float(meta.get("fps") or fps)
    step = max(1, int(round(src_fps / max(0.5, fps))))

    frames_pil: list[Image.Image] = []
    try:
        import numpy as np  # noqa: PLC0415

        for i, frame in enumerate(reader):
            if i % step != 0:
                continue
            im = Image.fromarray(frame).convert("RGBA")

            # Делаем чёрный/тёмный фон прозрачным
            data = np.array(im)
            r = data[:, :, 0].astype(int)
            g = data[:, :, 1].astype(int)
            b = data[:, :, 2].astype(int)
            mask = (r + g + b) < 35
            data[mask, 3] = 0
            im = Image.fromarray(data, "RGBA")

            im.thumbnail((size, size), Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", (size, size), (1, 1, 1, 255))
            x = (size - im.width) // 2
            y = (size - im.height) // 2
            canvas.paste(im, (x, y), im)
            frames_pil.append(canvas)
            if len(frames_pil) > 120:
                break
    except Exception as e:
        print(f"imageio чтение кадров: {e}")
        return False
    finally:
        try:
            reader.close()
        except Exception:
            pass

    if not frames_pil:
        return False

    duration_ms = max(30, int(1000 / max(1.0, fps)))
    try:
        frames_pil[0].save(
            out_gif,
            save_all=True,
            append_images=frames_pil[1:],
            duration=duration_ms,
            loop=0,
            disposal=2,
        )
        return out_gif.exists() and out_gif.stat().st_size > 0
    except Exception as e:
        print(f"Сохранение GIF: {e}")
        return False


def _static_from_gif(gif_path: Path, out_static: Path) -> None:
    from PIL import Image, ImageSequence

    im = Image.open(gif_path)
    frames = [f.convert("RGBA") for f in ImageSequence.Iterator(im)]
    if not frames:
        return
    mid = frames[len(frames) // 2]
    mid.save(out_static, "GIF", save_all=False)


def main() -> int:
    p = argparse.ArgumentParser(description="MP4 → assets/portal_animated.gif")
    p.add_argument("input", type=Path, help="Путь к .mp4 / .webm / .gif")
    p.add_argument("--size", type=int, default=220, help="Сторона квадрата (как у виджета)")
    p.add_argument("--fps", type=float, default=12.0, help="FPS для GIF")
    args = p.parse_args()

    src = args.input.expanduser().resolve()
    if not src.is_file():
        print(f"❌ Файл не найден: {src}")
        return 1

    assets = _assets_dir()
    assets.mkdir(parents=True, exist_ok=True)
    out_main = assets / "portal_animated.gif"
    out_static = assets / "portal_static.gif"

    print(f"📥 {src}")
    print(f"📤 {out_main}")

    ok = _try_ffmpeg(src, out_main, args.size, args.fps)
    if not ok:
        print("… ffmpeg в PATH не найден, пробую imageio + imageio-ffmpeg…")
        ok = _try_imageio(src, out_main, args.size, args.fps)

    if not ok:
        print(
            "❌ Не удалось конвертировать.\n"
            "   Установи ffmpeg (https://ffmpeg.org) в PATH\n"
            "   или: pip install imageio imageio-ffmpeg"
        )
        return 1

    try:
        _static_from_gif(out_main, out_static)
        print(f"✅ Статичный кадр: {out_static}")
    except Exception as e:
        print(f"⚠️ portal_static.gif: {e}")

    print("✅ Готово. Перезапусти Портал — виджет подхватит portal_animated.gif")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
