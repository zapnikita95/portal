"""
Расширенный буфер обмена: текст, PNG-изображение, список файлов (как в Проводнике).
Windows: Pillow + pywin32 (CF_HDROP) + PowerShell.
macOS: osascript → буфер со списком POSIX file (Cmd+V в Finder).
Linux: xclip text/uri-list при наличии xclip.
"""

from __future__ import annotations

import io
import os
import platform
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Literal, Tuple

ClipKind = Literal["empty", "text", "image", "files"]

_MAX_IMAGE_SEND_BYTES = 48 * 1024 * 1024  # 48 МБ сырого PNG


def _darwin_clipboard_file_paths() -> List[str]:
    """
    Файлы, скопированные в Finder / Cmd+C (NSPasteboard).
    Pillow ImageGrab на macOS часто отдаёт **превью-картинку**, а не путь — тогда уходит
    «чужой» PNG вместо реального JPEG/файла; поэтому сначала именно типы файлов.
    """
    if platform.system() != "Darwin":
        return []
    out: List[str] = []
    seen: set[str] = set()

    def _add(p: str) -> None:
        p = (p or "").strip()
        if not p:
            return
        try:
            rp = str(Path(p).resolve())
        except OSError:
            rp = p
        if os.path.isfile(rp) and rp not in seen:
            seen.add(rp)
            out.append(rp)

    try:
        from AppKit import NSPasteboard
        from Foundation import NSURL
        from urllib.parse import unquote, urlparse

        pb = NSPasteboard.generalPasteboard()
        if pb is None:
            return []

        # 1) Finder / Desktop: список путей (главный тип при «копировать файл»)
        for ptype in ("NSFilenamesPboardType",):
            try:
                plist = pb.propertyListForType_(ptype)
            except Exception:
                plist = None
            if plist is None:
                continue
            try:
                seq = list(plist)
            except TypeError:
                seq = [plist]
            for item in seq:
                try:
                    s = str(item)
                    if os.path.isfile(s):
                        _add(s)
                except Exception:
                    continue
            if out:
                return out

        # 2) Элементы pasteboard: public.file-url (и варианты)
        try:
            items = pb.pasteboardItems()
        except Exception:
            items = None
        if items:
            for it in items:
                for uti in (
                    "public.file-url",
                    "NSFilenamesPboardType",
                    "public.url",
                ):
                    try:
                        s = it.stringForType_(uti)
                    except Exception:
                        s = None
                    if not s:
                        continue
                    s = str(s).strip()
                    if s.startswith("file:"):
                        try:
                            path = unquote(urlparse(s).path)
                        except Exception:
                            continue
                        if path and os.path.isfile(path):
                            _add(path)
                    elif os.path.isfile(s):
                        _add(s)
            if out:
                return out

        # 3) NSURL-объекты
        urls = pb.readObjectsForClasses_options_([NSURL], None)
        if urls:
            for u in urls:
                try:
                    if u.isFileURL():
                        p = str(u.path())
                        if p and os.path.isfile(p):
                            _add(p)
                except Exception:
                    continue
            if out:
                return out
    except Exception:
        pass
    # Без PyObjC или нестандартный тип — пробуем AppleScript
    scpt = r"""
    try
      set c to the clipboard
      if c is {} then
        return ""
      else if (class of c) is list then
        set out to ""
        repeat with itm in c
          try
            set out to out & (POSIX path of itm) & linefeed
          end try
        end repeat
        return out
      else
        try
          return (POSIX path of c) & linefeed
        on error
          return ""
        end try
      end if
    on error
      return ""
    end try
    """
    try:
        r = subprocess.run(
            ["osascript", "-e", scpt],
            capture_output=True,
            text=True,
            timeout=12,
        )
        if r.returncode == 0 and (r.stdout or "").strip():
            lines = [ln.strip() for ln in r.stdout.replace("\r", "").split("\n") if ln.strip()]
            paths = [ln for ln in lines if os.path.isfile(ln)]
            if paths:
                return paths
    except Exception:
        pass
    return []


def clipboard_snapshot() -> Tuple[ClipKind, Dict[str, Any]]:
    """
    Снимок буфера для отправки (Ctrl+Alt+C).
    """
    # macOS: сначала файлы из NSPasteboard, потом Pillow — иначе grabclipboard()
    # даёт растровое превью выделенного файла, а не сам файл (JPEG оказывается «не тот»).
    if platform.system() == "Darwin":
        dpaths = _darwin_clipboard_file_paths()
        if dpaths:
            return "files", {"paths": dpaths}

    try:
        from PIL import ImageGrab

        data = ImageGrab.grabclipboard()
    except Exception:
        data = None

    if isinstance(data, list):
        paths = [p for p in data if isinstance(p, str) and os.path.isfile(p)]
        if paths:
            return "files", {"paths": paths}

    if data is not None and hasattr(data, "save"):
        try:
            buf = io.BytesIO()
            data.save(buf, format="PNG")
            raw = buf.getvalue()
            if raw:
                return "image", {"image_bytes": raw, "mime": "image/png"}
        except Exception:
            pass

    if platform.system() == "Windows":
        paths = _win32_clipboard_file_paths()
        if paths:
            return "files", {"paths": paths}
        fallback = _paths_from_plaintext_clipboard()
        if fallback:
            return "files", {"paths": fallback}

    import pyperclip

    try:
        t = pyperclip.paste()
    except Exception:
        t = None
    if t is not None and str(t).strip() != "":
        return "text", {"text": str(t)}

    return "empty", {}


def _win32_paths_from_hdrop(hdrop) -> List[str]:
    from ctypes import create_unicode_buffer, windll

    paths: List[str] = []
    try:
        hd = int(hdrop)
    except Exception:
        return []
    n = int(windll.shell32.DragQueryFileW(hd, 0xFFFFFFFF, None, 0))
    for i in range(n):
        buf = create_unicode_buffer(4096)
        windll.shell32.DragQueryFileW(hd, i, buf, 4096)
        p = buf.value
        if p and os.path.isfile(p):
            paths.append(p)
    return paths


def _paths_from_plaintext_clipboard() -> List[str]:
    """
    Если CF_HDROP недоступен, но в буфере текст — по одному пути на строку и все строки
    существуют как файлы, считаем это тем же «копированием файлов» для отправки.
    """
    import pyperclip

    try:
        t = pyperclip.paste()
    except Exception:
        return []
    if t is None or not str(t).strip():
        return []
    lines = [
        ln.strip().strip('"')
        for ln in str(t).replace("\r\n", "\n").split("\n")
        if ln.strip()
    ]
    if not lines:
        return []
    paths: List[str] = []
    for ln in lines:
        if os.path.isfile(ln):
            paths.append(ln)
        else:
            return []
    return paths


def _win32_clipboard_file_paths() -> List[str]:
    try:
        import win32clipboard  # type: ignore
        import win32con  # type: ignore
    except ImportError:
        return []
    try:
        win32clipboard.OpenClipboard()
        try:
            if not win32clipboard.IsClipboardFormatAvailable(win32con.CF_HDROP):
                return []
            hdrop = win32clipboard.GetClipboardData(win32con.CF_HDROP)
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        return []
    return _win32_paths_from_hdrop(hdrop)


def apply_clipboard_payload(
    kind: str,
    text: str = "",
    image_path: str | None = None,
    file_paths: List[str] | None = None,
) -> str:
    """
    Поместить данные в системный буфер. Вызывать с главного потока UI.
    """
    file_paths = file_paths or []
    if kind == "text":
        import pyperclip

        pyperclip.copy(text or "")
        return f"текст ({len(text or '')} симв.)"

    if kind == "image" and image_path and os.path.isfile(image_path):
        if platform.system() == "Windows":
            ok, err = _win_set_clipboard_image_png(image_path)
            if ok:
                return "картинка → буфер (Ctrl+V в Paint, Word, Telegram…)"
            return f"картинка на диске; буфер: {err}"
        return f"картинка: {image_path}"

    if kind == "files" and file_paths:
        existing = [p for p in file_paths if os.path.isfile(p)]
        if not existing:
            return "файлы не найдены"
        if platform.system() == "Windows":
            ok, err = _win_set_clipboard_files(existing)
            if ok:
                return f"файлы в буфере ({len(existing)} шт.) — Ctrl+V в Проводнике"
            try:
                import pyperclip

                pyperclip.copy("\n".join(existing))
                return (
                    f"пути в буфер текстом ({len(existing)} шт.) — "
                    "вставь в адресную строку Проводника или открой путь"
                )
            except Exception as e2:
                return (
                    f"файлы на диске; CF_HDROP не выставлен ({err}); "
                    f"текст в буфер: {e2}"
                )
        if platform.system() == "Darwin":
            ok, err = _darwin_set_clipboard_files(existing)
            if ok:
                return (
                    f"файлы в буфере ({len(existing)} шт.) — в Finder: открой папку, клик в окно, "
                    "Cmd+V (вставка). Cmd+Shift+V у Портала = «забрать с другого ПК», не вставка."
                )
            import pyperclip

            try:
                pyperclip.copy("\n".join(existing))
                return (
                    f"пути в буфер текстом ({len(existing)} шт., osascript: {err})"
                )
            except Exception as e2:
                return f"не удалось буфер: {err}; pyperclip: {e2}"
        if platform.system() == "Linux":
            ok, err = _linux_set_clipboard_files_uri_list(existing)
            if ok:
                return f"файлы в буфере ({len(existing)} шт.) — вставка в файловом менеджере"
        import pyperclip

        pyperclip.copy("\n".join(existing))
        return f"пути в буфере текстом ({len(existing)} шт.)"

    return "пусто"


def _win_set_clipboard_image_png(path: str) -> Tuple[bool, str]:
    path = str(Path(path).resolve())
    esc = path.replace("'", "''")
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
        f"$p = '{esc}'; "
        "$img = [System.Drawing.Image]::FromFile($p); "
        "[System.Windows.Forms.Clipboard]::SetImage($img); "
        "$img.Dispose()"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode == 0:
            return True, ""
        return False, (r.stderr or r.stdout or "PowerShell")[:200]
    except Exception as e:
        return False, str(e)[:200]


def _darwin_set_clipboard_files(paths: List[str]) -> Tuple[bool, str]:
    """macOS: положить в буфер ссылки на файлы (Finder / Cmd+V)."""
    resolved = [str(Path(p).resolve()) for p in paths if os.path.isfile(p)]
    if not resolved:
        return False, "нет файлов"
    # argv — пути без экранирования в AppleScript
    script = """
on run argv
    set fileList to {}
    repeat with i from 1 to (count argv)
        set p to item i of argv
        set end of fileList to POSIX file p
    end repeat
    set the clipboard to fileList
end run
"""
    try:
        r = subprocess.run(
            ["osascript", "-e", script, *resolved],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode == 0:
            return True, ""
        return False, (r.stderr or r.stdout or "osascript")[:300]
    except Exception as e:
        return False, str(e)[:300]


def _linux_set_clipboard_files_uri_list(paths: List[str]) -> Tuple[bool, str]:
    """Linux: text/uri-list через xclip (если есть)."""
    resolved = [Path(p).resolve() for p in paths if os.path.isfile(p)]
    if not resolved:
        return False, "нет файлов"
    payload = "".join(p.as_uri() + "\n" for p in resolved)
    try:
        r = subprocess.run(
            ["xclip", "-selection", "clipboard", "-t", "text/uri-list"],
            input=payload,
            text=True,
            capture_output=True,
            timeout=15,
        )
        if r.returncode == 0:
            return True, ""
        return False, (r.stderr or "xclip")[:200]
    except FileNotFoundError:
        return False, "xclip не найден"
    except Exception as e:
        return False, str(e)[:200]


def _win_set_clipboard_files(paths: List[str]) -> Tuple[bool, str]:
    parts = []
    for p in paths:
        fp = str(Path(p).resolve()).replace("'", "''")
        parts.append(f"'{fp}'")
    ps = f"Set-Clipboard -LiteralPath @({','.join(parts)})"
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode == 0:
            return True, ""
        return False, (r.stderr or r.stdout or "err")[:200]
    except Exception as e:
        return False, str(e)[:200]


def image_size_ok(n: int) -> bool:
    return 0 < n <= _MAX_IMAGE_SEND_BYTES
