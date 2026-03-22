"""
Виджет-портал для рабочего стола: прозрачный фон, drag&drop, горячие клавиши.
Анимация только при открытии/закрытии — без бесконечного цикла.
"""

import io
import glob
import tkinter as tk
import math
import threading
import time
import sys
import platform
from pathlib import Path
from PIL import Image, ImageFilter, ImageTk, ImageSequence
import os
import subprocess
from typing import Optional, Any, List

import portal_config
import portal_i18n as i18n
import portal_mac_permissions

try:
    from portal import PortalApp
except ImportError:
    PortalApp = None


def _resolve_mac_hotkey_helper_script() -> Optional[Path]:
    """
    portal_mac_hotkey_helper.py рядом с кодом или в распаковке PyInstaller (_MEIPASS / _internal).
    """
    here = Path(__file__).resolve().parent
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            p = Path(meipass) / "portal_mac_hotkey_helper.py"
            if p.is_file():
                return p
        exe_dir = Path(sys.executable).resolve().parent
        for p in (
            exe_dir / "portal_mac_hotkey_helper.py",
            exe_dir / "_internal" / "portal_mac_hotkey_helper.py",
        ):
            if p.is_file():
                return p
        return None
    p = here / "portal_mac_hotkey_helper.py"
    return p if p.is_file() else None


def _mac_privacy_target_hint() -> str:
    """
    Кому выдавать «Мониторинг ввода» / «Универсальный доступ».
    Собранный .app и `python3 portal.py` — разные записи в списках macOS.
    """
    if getattr(sys, "frozen", False):
        try:
            exe = Path(sys.executable).resolve()
        except Exception:
            exe = None
        tail = (
            f" ({exe})" if exe is not None else ""
        )
        return (
            "Portal.app — тот бинарник, который реально запускаешь из dist/"
            + tail
            + ". После новой сборки PyInstaller иногда нужно **выключить и снова включить** "
            "переключатель для Portal в списках (macOS привязывает права к идентичности приложения)."
        )
    return (
        "тот же **Python** (org.python.python), которым запускаешь `portal.py` из Terminal/Cursor — "
        "им же стартует дочерний hotkey-helper; в «Мониторинг ввода» часто нужны и **Terminal** (или IDE), "
        "и **Python** (как в crash report, если macOS предложит отдельную запись)."
    )


def _portal_hotkey_tk_sequences() -> tuple[List[str], List[str], List[str]]:
    """Последовательности Tk для toggle / push / pull (macOS legacy или нет, Windows/Linux)."""
    is_mac = platform.system() == "Darwin"
    if is_mac:
        legacy = os.environ.get("PORTAL_MAC_HOTKEY_LEGACY", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        if legacy:
            toggle_seqs = [
                "<Command-Option-p>",
                "<Command-Alt-p>",
                "<Meta-Option-p>",
                "<Meta-Alt-p>",
                "<Command-Option-P>",
                "<Meta-Option-P>",
            ]
            push_seqs = [
                "<Command-Shift-C>",
                "<Command-Shift-c>",
                "<Meta-Shift-C>",
                "<Meta-Shift-c>",
            ]
            pull_seqs = [
                "<Command-Shift-V>",
                "<Command-Shift-v>",
                "<Meta-Shift-V>",
                "<Meta-Shift-v>",
                "<Command-Option-v>",
                "<Command-Option-V>",
                "<Meta-Option-v>",
                "<Meta-Option-V>",
            ]
            toggle_seqs += [
                "<Command-Option-з>",
                "<Command-Option-З>",
                "<Meta-Option-з>",
                "<Meta-Option-З>",
            ]
            push_seqs += [
                "<Command-Shift-с>",
                "<Command-Shift-С>",
                "<Meta-Shift-с>",
                "<Meta-Shift-С>",
            ]
            pull_seqs += [
                "<Command-Shift-м>",
                "<Command-Shift-М>",
                "<Meta-Shift-м>",
                "<Meta-Shift-М>",
                "<Command-Option-м>",
                "<Command-Option-М>",
                "<Meta-Option-м>",
                "<Meta-Option-М>",
            ]
        else:
            toggle_seqs = [
                "<Command-Control-p>",
                "<Command-Control-P>",
                "<Control-Command-p>",
                "<Control-Command-P>",
                "<Meta-Control-p>",
                "<Meta-Control-P>",
            ]
            push_seqs = [
                "<Command-Control-c>",
                "<Command-Control-C>",
                "<Control-Command-c>",
                "<Control-Command-C>",
            ]
            pull_seqs = [
                "<Command-Control-v>",
                "<Command-Control-V>",
                "<Control-Command-v>",
                "<Control-Command-V>",
            ]
            toggle_seqs += [
                "<Command-Control-з>",
                "<Command-Control-З>",
                "<Control-Command-з>",
                "<Control-Command-З>",
                "<Meta-Control-з>",
                "<Meta-Control-З>",
            ]
            push_seqs += [
                "<Command-Control-с>",
                "<Command-Control-С>",
                "<Control-Command-с>",
                "<Control-Command-С>",
            ]
            pull_seqs += [
                "<Command-Control-м>",
                "<Command-Control-М>",
                "<Control-Command-м>",
                "<Control-Command-М>",
            ]
    else:
        toggle_seqs = [
            "<Control-Alt-p>",
            "<Control-Alt-P>",
            "<Alt-Control-p>",
            "<Alt-Control-P>",
            "<Control_L-Alt_L-p>",
            "<Control_L-Alt_L-P>",
        ]
        push_seqs = [
            "<Control-Alt-c>",
            "<Control-Alt-C>",
            "<Alt-Control-c>",
        ]
        pull_seqs = [
            "<Control-Alt-v>",
            "<Control-Alt-V>",
            "<Alt-Control-v>",
        ]
        toggle_seqs += [
            "<Control-Alt-з>",
            "<Control-Alt-З>",
            "<Alt-Control-з>",
            "<Alt-Control-З>",
        ]
        push_seqs += [
            "<Control-Alt-с>",
            "<Control-Alt-С>",
            "<Alt-Control-с>",
            "<Alt-Control-С>",
        ]
        pull_seqs += [
            "<Control-Alt-м>",
            "<Control-Alt-М>",
            "<Alt-Control-м>",
            "<Alt-Control-М>",
        ]
    return toggle_seqs, push_seqs, pull_seqs


# Хромакей: Windows — почти чёрный; macOS — магента (#FF00FF), чтобы не съесть тёмные края портала
# Свой цвет: PORTAL_WIDGET_CHROMA=#RRGGBB
CHROMA_KEY_WIN = "#010101"
CHROMA_KEY_MAC = "#FF00FF"


def _hex_to_rgb(h: str) -> tuple:
    h = (h or "").strip().lstrip("#")
    if len(h) != 6:
        return (1, 1, 1)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def widget_chroma_hex() -> str:
    env = os.environ.get("PORTAL_WIDGET_CHROMA", "").strip()
    if env:
        return env if env.startswith("#") else f"#{env}"
    if platform.system() == "Darwin":
        return CHROMA_KEY_MAC
    return CHROMA_KEY_WIN


def grab_clipboard_image():
    """Картинка из буфера как PIL.Image RGBA или None."""
    try:
        from PIL import Image, ImageGrab

        clip = ImageGrab.grabclipboard()
        if isinstance(clip, Image.Image):
            return clip.convert("RGBA")
        if clip and isinstance(clip, list):
            for p in clip:
                ps = str(p).strip()
                if ps and Path(ps).is_file():
                    try:
                        return Image.open(ps).convert("RGBA")
                    except Exception:
                        continue
    except Exception:
        pass
    if platform.system() == "Darwin":
        try:
            from AppKit import NSPasteboard

            pb = NSPasteboard.generalPasteboard()
            for uti in ("public.png", "public.tiff", "public.jpeg", "public.jpg"):
                data = pb.dataForType_(uti)
                if data is None:
                    continue
                try:
                    if hasattr(data, "bytes"):
                        buf = bytes(data.bytes())
                    else:
                        buf = bytes(data)
                except Exception:
                    continue
                if buf:
                    from PIL import Image

                    return Image.open(io.BytesIO(buf)).convert("RGBA")
        except Exception:
            pass
    return None


def grab_clipboard_file_paths() -> List[str]:
    """
    Пути файлов, скопированных в буфер (Finder / Проводник), без открытия как картинка.
    Пустой список, если в буфере только текст или растровая картинка без путей.
    """
    out: List[str] = []
    seen = set()

    def add(p: str) -> None:
        ps = (p or "").strip()
        if not ps:
            return
        try:
            rp = str(Path(ps).resolve())
        except Exception:
            rp = ps
        if rp not in seen and Path(ps).is_file():
            seen.add(rp)
            out.append(ps)

    try:
        from PIL import ImageGrab

        clip = ImageGrab.grabclipboard()
        if isinstance(clip, list):
            for p in clip:
                add(str(p))
            if out:
                return list(out)
    except Exception:
        pass

    if platform.system() == "Darwin":
        try:
            from AppKit import NSPasteboard, NSURL

            pb = NSPasteboard.generalPasteboard()
            urls = pb.readObjectsForClasses_options_([NSURL], None)
            if urls:
                for u in urls:
                    try:
                        p = u.path()
                        if p:
                            add(str(p))
                    except Exception:
                        continue
                if out:
                    return list(out)
        except Exception:
            pass

    if platform.system() == "win32":
        try:
            import win32clipboard

            win32clipboard.OpenClipboard()
            try:
                if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_HDROP):
                    raw = win32clipboard.GetClipboardData(win32clipboard.CF_HDROP)
                    if isinstance(raw, (list, tuple)):
                        for p in raw:
                            add(str(p))
                    elif isinstance(raw, str):
                        for p in raw.split("\0"):
                            add(p)
            finally:
                win32clipboard.CloseClipboard()
            if out:
                return list(out)
        except Exception:
            pass

    return list(out)


# ── Логгинг из фоновых потоков ────────────────────────────────────────────────

def _hotkey_log_path() -> Path:
    base = (
        (os.environ.get("TEMP") or os.environ.get("TMP") or str(Path.home()))
        if sys.platform == "win32"
        else (os.environ.get("TMPDIR") or "/tmp")
    )
    return Path(base) / "portal_hotkey_debug.log"


def debug_log_path() -> Path:
    """Публичный алиас для импорта из portal.py"""
    return _hotkey_log_path()


def _log_to_file(line: str) -> None:
    try:
        p = _hotkey_log_path()
        with p.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def portal_thread_log(main_app: Any, message: str, prefix: str = "⌨️") -> None:
    """
    Лог из любого потока: консоль + файл + журнал GUI.

    ВАЖНО (Python 3.13 + Tk): не вызывать main_app.after(0, ...) из главного потока,
    когда уже внутри колбэка Tk (bind / fileevent) — даёт PyEval_RestoreThread / SIGABRT.
    На главном потоке пишем в журнал напрямую.
    """
    ts = time.strftime("%H:%M:%S")
    full = f"[{ts}] {prefix} {message}"
    print(f"[Portal] {full}", flush=True)
    _log_to_file(f"[Portal] {full}")
    try:
        if main_app is None or not hasattr(main_app, "log"):
            return
        line = f"{prefix} {message}"

        def _do() -> None:
            try:
                main_app.log(line)
            except Exception:
                pass

        if threading.current_thread() is threading.main_thread():
            _do()
        elif hasattr(main_app, "after"):
            main_app.after(0, _do)
        else:
            _do()
    except Exception:
        pass


class PortalWidget:
    """Виджет-портал на рабочем столе"""

    # Состояния анимации
    ANIM_HIDDEN  = "hidden"
    ANIM_OPENING = "opening"
    ANIM_OPEN    = "open"
    ANIM_CLOSING = "closing"

    def __init__(self, main_app: Any):
        self.main_app = main_app
        self._chroma_hex = widget_chroma_hex()
        self._chroma_rgb = _hex_to_rgb(self._chroma_hex)
        self._dnd_tkinterdnd2 = False
        self._windnd_ok = False

        # macOS/Linux: TkinterDnD._require на главное CTk-окно — drag&drop на canvas виджета
        # Отключить: PORTAL_NO_MAC_DND=1 (если краш на Python 3.13+)
        if platform.system() != "Windows" and main_app is not None:
            try:
                from portal_tk_compat import ensure_tkdnd_tk_misc_patch

                from tkinterdnd2 import TkinterDnD
                if os.environ.get("PORTAL_NO_MAC_DND", "").strip() in ("1", "true", "yes"):
                    print("[Portal] tkinterdnd2 отключён (PORTAL_NO_MAC_DND)")
                    self._dnd_tkinterdnd2 = False
                else:
                    TkinterDnD._require(main_app)
                    ensure_tkdnd_tk_misc_patch()
                    self._dnd_tkinterdnd2 = True
                    if sys.version_info >= (3, 13):
                        print(
                            "[Portal] tkinterdnd2 включён (Python 3.13). "
                            "При падении запускай с PORTAL_NO_MAC_DND=1"
                        )
            except Exception as e:
                self._dnd_tkinterdnd2 = False
                print(f"[Portal] tkinterdnd2 (главное окно): {e}")

        if main_app is not None and hasattr(main_app, "winfo_toplevel"):
            self.root = tk.Toplevel(master=main_app)
        else:
            self.root = tk.Tk()

        # Уникальный заголовок — по нему ищем NSWindow для настоящей прозрачности (macOS)
        self.root.title(i18n.tr("widget.desktop_title"))

        self.size = portal_config.load_widget_size()
        # Подложка режима «окошко» (macOS): цвет из настроек (config.json widget_mac_panel_bg)
        self._frame_panel_rgb = portal_config.load_widget_mac_panel_bg_rgb()
        self._mac_framed_window: bool = self._widget_framed_mode()
        self._mac_using_rgba_window: bool = False  # True = реальная альфа, без хромакей-менты в PhotoImage
        self._mac_nswindow_fixed: bool = False  # лог успеха Cocoa один раз
        self._mac_nswindow_fail_logged: bool = False  # предупреждение «окно не найдено» один раз
        self._mac_pyobjc_import_logged: bool = False  # «нет AppKit» один раз за сессию

        # Состояние анимации
        self.anim_state = self.ANIM_HIDDEN
        self.anim_frame_idx = 0
        self._anim_after_id = None
        self._anim_master: Optional[tk.Misc] = None  # тот же виджет, что вызывал after (для after_cancel)
        self._anim_speed_ms = 42  # ~24fps

        # GIF-кадры (открытие/статика)
        self.gif_frames: List[ImageTk.PhotoImage] = []
        self.gif_frames_raw: List[Image.Image] = []  # PIL-объекты для обратного воспроизведения
        self._gif_frame_durations: List[int] = []
        self._last_photo: Optional[ImageTk.PhotoImage] = None  # держим ссылку, чтобы GC не удалил

        # Fallback-рисованный портал
        self.angle = 0.0

        self.target_ip: Optional[str] = None
        if main_app and getattr(main_app, "remote_peer_ip", None):
            self.target_ip = main_app.remote_peer_ip
        if not self.target_ip:
            self.target_ip = portal_config.load_remote_ip()

        # Антидребезг: двойной клик в Tk может вызвать обработчик дважды (canvas + toplevel в bindtags)
        self._last_double_clipboard_send_mono: float = 0.0
        # Режим «статичная картинка»: масштаб при открытии/закрытии
        self._portal_media_static_visual: bool = False
        self._static_rgba_full: Optional[Image.Image] = None
        self._static_open_photo: Optional[ImageTk.PhotoImage] = None
        self._static_anim_steps: int = 18
        # Временная подмена GIF/WebP на импульс (пресеты по IP / событию)
        self._transient_media_path: Optional[str] = None

        self.setup_window()

        _panel_hex = portal_config.load_widget_mac_panel_bg_hex()
        _cbg = (
            _panel_hex
            if platform.system() == "Darwin" and getattr(self, "_mac_framed_window", False)
            else self._chroma_hex
        )
        self.canvas = tk.Canvas(
            self.root,
            width=self.size,
            height=self.size,
            bg=_cbg,
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack()

        # GIF после canvas: PhotoImage(master=...) обязателен на macOS, иначе картинка не рисуется
        self.load_portal_gif()

        self.setup_transparency()
        self.root.update_idletasks()

        if platform.system() == "Windows":
            self._setup_windnd_drop()
        else:
            self.setup_drag_drop_tkdnd()

        self.setup_mouse_bindings()

        # Анимация запустится при первом show() — не при init, т.к. виджет скрыт по умолчанию

    def _mac_real_transparency_enabled(self) -> bool:
        """macOS: настоящая прозрачность (альфа + NSWindow), без -transparentcolor."""
        if platform.system() != "Darwin":
            return False
        return os.environ.get("PORTAL_MAC_CHROMA_ONLY", "").strip() not in (
            "1",
            "true",
            "yes",
        )

    def _widget_framed_mode(self) -> bool:
        """
        macOS: обычное окно с заголовком и тёмным фоном — картинка на подложке, не магента на весь стол.
        PORTAL_WIDGET_FRAMED=0 — прежний режим (полная прозрачность / хромакей на окне).
        """
        if platform.system() != "Darwin":
            return False
        v = os.environ.get("PORTAL_WIDGET_FRAMED", "").strip().lower()
        if v in ("0", "false", "no", "off"):
            return False
        if v in ("1", "true", "yes", "on"):
            return True
        return True

    # ───────────────────────────── ОКНО ─────────────────────────────

    def setup_window(self):
        """Позиция, поверх остальных окон, без рамки"""
        framed = platform.system() == "Darwin" and getattr(self, "_mac_framed_window", False)
        bg_use = (
            portal_config.load_widget_mac_panel_bg_hex() if framed else self._chroma_hex
        )
        try:
            ht = 1 if framed else 0
            hb = "#555555" if framed else self._chroma_hex
            self.root.configure(highlightthickness=ht, highlightbackground=hb, bd=0, bg=bg_use)
        except tk.TclError:
            pass
        try:
            self.root.attributes("-topmost", True)
        except tk.TclError:
            pass
        try:
            self.root.attributes("-alpha", 1.0)
        except tk.TclError:
            pass
        # macOS: overrideredirect до хромакея ломает -transparentcolor у части сборок Tk/Aqua —
        # включаем рамку без декора после setup_transparency()
        if platform.system() != "Darwin":
            try:
                self.root.overrideredirect(True)
            except tk.TclError:
                pass

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x, y = portal_config.widget_window_xy(
            sw,
            sh,
            self.size,
            portal_config.load_widget_corner(),
            portal_config.load_widget_margin_x(),
            portal_config.load_widget_margin_y(),
        )
        self.root.geometry(f"{self.size}x{self.size}+{x}+{y}")

        self.drag_start_x = 0
        self.drag_start_y = 0

    def apply_widget_geometry(self) -> None:
        """Размер и угол из config.json (после «Сохранить размер и угол» в главном окне)."""
        try:
            new_size = portal_config.load_widget_size()
            corner = portal_config.load_widget_corner()
            mx = portal_config.load_widget_margin_x()
            my = portal_config.load_widget_margin_y()
            sw = int(self.root.winfo_screenwidth())
            sh = int(self.root.winfo_screenheight())
            x, y = portal_config.widget_window_xy(sw, sh, new_size, corner, mx, my)
            size_changed = new_size != self.size
            self.size = new_size
            try:
                self.canvas.configure(width=self.size, height=self.size)
            except tk.TclError:
                pass
            self.root.geometry(f"{self.size}x{self.size}+{x}+{y}")
            if size_changed:
                try:
                    self.load_portal_gif()
                except Exception as e:
                    print(f"[Portal] apply_widget_geometry / load_portal_gif: {e}")
            self.root.update_idletasks()
        except Exception as e:
            print(f"[Portal] apply_widget_geometry: {e}")

    def setup_transparency(self):
        """
        Windows: хромакей + -transparentcolor.
        macOS по умолчанию: RGBA + systemTransparent + NSWindow opaque=NO (настоящая альфа пикселей).
        PORTAL_MAC_CHROMA_ONLY=1 — только #FF00FF + -transparentcolor (если альфа не работает).
        """
        if platform.system() == "Windows":
            self.root.configure(bg=self._chroma_hex)
            self.canvas.configure(bg=self._chroma_hex)
            try:
                self.root.attributes("-transparentcolor", self._chroma_hex)
            except tk.TclError:
                pass
            return

        if platform.system() == "Darwin":
            if getattr(self, "_mac_framed_window", False):
                # Окошко: без -transparentcolor и без ORR — GIF на тёмной подложке (см. _photo_from_rgba_chroma)
                self.root.configure(bg="#2a2d35")
                self.canvas.configure(bg="#2a2d35")
                try:
                    self.root.attributes("-transparentcolor", "")
                except tk.TclError:
                    pass
                try:
                    self.root.wm_attributes("-transparent", False)
                except tk.TclError:
                    pass
                return
            # Режим A: не заливаем магентой — иначе Cocoa рисует непрозражный фон под альфой
            if self._mac_real_transparency_enabled() and self._mac_using_rgba_window:
                self._mac_refresh_real_transparency()
                try:
                    self.root.overrideredirect(True)
                except tk.TclError:
                    pass
                self._mac_refresh_real_transparency()
                try:
                    for ms in (30, 80, 200, 450, 900):
                        self.root.after(ms, self._mac_nswindow_make_opaque_false)
                except Exception:
                    pass
                return
            self.root.configure(bg=self._chroma_hex)
            self.canvas.configure(bg=self._chroma_hex)
            # Режим B: хромакей #FF00FF + -transparentcolor (если RGBA не взошёл — PORTAL_MAC_CHROMA_ONLY=1)
            self._mac_apply_chroma_transparency()
            try:
                self.root.overrideredirect(True)
            except tk.TclError:
                pass
            self._mac_apply_chroma_transparency()
            if os.environ.get("PORTAL_MAC_TRANSPARENT", "").strip() in (
                "1",
                "true",
                "yes",
            ):
                try:
                    self.root.wm_attributes("-transparent", True)
                except tk.TclError:
                    pass
            return

        self.root.configure(bg=self._chroma_hex)
        self.canvas.configure(bg=self._chroma_hex)

    def _mac_apply_chroma_transparency(self) -> None:
        """Сброс + повторная установка хромакея (Aqua часто «забывает» цвет до/после ORR)."""
        if platform.system() != "Darwin":
            return
        h = self._chroma_hex
        try:
            self.root.attributes("-transparentcolor", "")
        except tk.TclError:
            pass
        try:
            self.root.update_idletasks()
        except tk.TclError:
            pass
        try:
            self.root.attributes("-transparentcolor", h)
        except tk.TclError:
            try:
                self.root.wm_attributes("-transparentcolor", h)
            except tk.TclError:
                pass

    def _mac_refresh_real_transparency(self) -> None:
        """Tk: прозрачный фон окна + слой с альфой (кадры GIF — RGBA PhotoImage)."""
        if not self._mac_real_transparency_enabled():
            return
        for w in (self.root, self.canvas):
            try:
                w.configure(bg="systemTransparent")
            except tk.TclError:
                try:
                    w.configure(bg=self._chroma_hex)
                except tk.TclError:
                    pass
        try:
            self.root.wm_attributes("-transparent", True)
        except tk.TclError:
            pass

    def _mac_tk_rect_in_cocoa_space(self) -> Optional[tuple]:
        """
        Прямоугольник окна Tk в координатах Cocoa (origin — нижний левый угол экрана).
        Нужен для поиска NSWindow: заголовок/видимость на macOS ненадёжны (Toplevel, withdraw).
        """
        if platform.system() != "Darwin":
            return None
        try:
            self.root.update_idletasks()
            rx = float(self.root.winfo_rootx())
            ry = float(self.root.winfo_rooty())
            w = float(self.root.winfo_width())
            h = float(self.root.winfo_height())
            sh = float(self.root.winfo_screenheight())
            if w < 8 or h < 8:
                return None
            # Tk: Y сверху вниз. Cocoa: Y снизу вверх.
            cocoa_x = rx
            cocoa_y = sh - ry - h
            return (cocoa_x, cocoa_y, w, h)
        except tk.TclError:
            return None

    def _mac_nswindow_make_opaque_false(self) -> None:
        """Cocoa: без opaque=NO Tk рисует магенту/серый фон поверх «прозрачного» окна."""
        if not self._mac_real_transparency_enabled() or not self._mac_using_rgba_window:
            return
        try:
            from AppKit import NSApplication, NSColor
        except ImportError:
            if not self._mac_pyobjc_import_logged:
                self._mac_pyobjc_import_logged = True
                print(
                    "[Portal] Нет PyObjC AppKit — pip install pyobjc-framework-Cocoa "
                    "(или PORTAL_MAC_CHROMA_ONLY=1 для режима #FF00FF)"
                )
            return
        self.root.update_idletasks()
        expected = self._mac_tk_rect_in_cocoa_space()
        target = None
        best_score = float("inf")
        try:
            app = NSApplication.sharedApplication()
            wins = list(app.windows())
        except Exception as e:
            print(f"[Portal] NSApplication.sharedApplication: {e}")
            return

        def score_window(win) -> Optional[tuple]:
            """
            Меньше = лучше. (score, win) или None если окно явно не наш виджет.
            Не требуем isVisible: при withdraw() окно есть, но скрыто — прозрачность всё равно задаём.
            """
            try:
                f = win.frame()
                x0, y0 = float(f.origin.x), float(f.origin.y)
                w0, h0 = float(f.size.width), float(f.size.height)
                if w0 < 8 or h0 < 8:
                    return None
                title = str(win.title() or "")
                tl = title.lower()
                is_widget_title = "виджет" in tl or "widget" in tl

                if expected is not None:
                    ex, ey, ew, eh = expected
                    dist = (
                        abs(x0 - ex)
                        + abs(y0 - ey)
                        + abs(w0 - ew)
                        + abs(h0 - eh)
                    )
                    # Жёсткий порог: другое окно того же размера в другом углу не цепляем
                    if dist > 48:
                        return None
                    score = dist
                    if is_widget_title:
                        score -= 18.0
                    if "портал" in tl or "portal" in tl:
                        score -= 8.0
                    if win.isVisible():
                        score -= 5.0
                    return (score, win)

                # Фолбэк без геометрии (старый эвристический режим)
                sz = float(self.size)
                size_ok = abs(w0 - sz) <= 36 and abs(h0 - sz) <= 36
                size_loose = abs(w0 - sz) <= 72 and abs(h0 - sz) <= 72
                if is_widget_title and size_ok:
                    return (-300.0, win)
                if is_widget_title and size_loose:
                    return (-200.0, win)
                if is_widget_title:
                    return (-150.0, win)
                if size_ok and ("портал" in tl or "portal" in tl):
                    return (-120.0, win)
                if size_ok:
                    return (-50.0, win)
                return None
            except Exception:
                return None

        for win in wins:
            got = score_window(win)
            if got is None:
                continue
            sc, wn = got
            if sc < best_score:
                best_score = sc
                target = wn

        if target is None:
            if not self._mac_nswindow_fixed and not self._mac_nswindow_fail_logged:
                self._mac_nswindow_fail_logged = True
                hint = ""
                if expected:
                    ex, ey, ew, eh = expected
                    hint = f" ожидалось Cocoa ({int(ex)},{int(ey)}) {int(ew)}×{int(eh)}."
                print(
                    f"[Portal] ⚠️ NSWindow виджета не найден по геометрии.{hint} "
                    "pip install pyobjc-framework-Cocoa или PORTAL_MAC_CHROMA_ONLY=1"
                )
            return
        try:
            target.setOpaque_(False)
            target.setBackgroundColor_(NSColor.clearColor())
            cv = target.contentView()
            if cv is not None:
                # True часто даёт пустое окно: Tk рисует в NSView без слоя.
                # PORTAL_MAC_CV_WANTSLAYER=1 — включить слой вручную.
                use_layer = os.environ.get("PORTAL_MAC_CV_WANTSLAYER", "").strip() in (
                    "1",
                    "true",
                    "yes",
                )
                cv.setWantsLayer_(use_layer)
            if not self._mac_nswindow_fixed:
                self._mac_nswindow_fixed = True
                fr = target.frame()
                vis = "видимо" if target.isVisible() else "скрыто (withdraw)"
                print(
                    f"[Portal] ✅ Прозрачность Cocoa: «{target.title()}» "
                    f"{int(fr.size.width)}×{int(fr.size.height)} @ "
                    f"({int(fr.origin.x)},{int(fr.origin.y)}), {vis}"
                )
            try:
                if target.isVisible():
                    target.orderFrontRegardless()
            except Exception:
                pass
        except Exception as e:
            print(f"[Portal] NSWindow setOpaque/clearColor: {e}")

    # ───────────────────────────── ЗАГРУЗКА GIF ─────────────────────

    def _find_portal_asset(self) -> Optional[str]:
        """Пользовательский путь из config или GIF/PNG в assets/ (portal*.gif / portal*.png)."""
        t = getattr(self, "_transient_media_path", None)
        if t and os.path.isfile(t):
            return t
        custom = portal_config.effective_widget_media_path()
        if custom and os.path.isfile(custom):
            return custom
        assets_dir = os.path.join(os.path.dirname(__file__), "assets")
        os.makedirs(assets_dir, exist_ok=True)
        priority = [
            "portal_main.gif",
            "portal_main.png",
            "portal_opening.gif",
            "portal_animated_opening.gif",
            "portal_animated.gif",
            "portal_static.gif",
        ]
        for name in priority:
            p = os.path.join(assets_dir, name)
            if os.path.isfile(p):
                return p
        for pattern in ("portal*.gif", "portal*.png", "Portal*.gif", "Portal*.png"):
            found = sorted(glob.glob(os.path.join(assets_dir, pattern)))
            if found:
                return found[0]
        return None

    def _prepare_portal_frame_rgba(self, frame: Image.Image) -> Image.Image:
        """
        Квадрат → resize; убрать магенту (#FF00FF) и тёмную «подложку» вокруг портала;
        лёгкое размытие альфы по краю (без замены альфы жёстким кругом).
        """
        img = frame.convert("RGBA")
        w, h = img.size
        sq = min(w, h)
        left = (w - sq) // 2
        top = (h - sq) // 2
        img = img.crop((left, top, left + sq, top + sq))
        img = img.resize((self.size, self.size), Image.Resampling.LANCZOS)

        cr, cg, cb = self._chroma_rgb
        # Радиус в RGB²: дизер/сглаживание к магенте (не только чистый #FF00FF)
        chroma_r2 = 105 * 105
        size = self.size
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
                # «Розово-фиолетовая» кайма (R+B высокие, G подавлен) — остатки антиалиаса к фону GIF
                if r >= 130 and b >= 130 and g <= 135 and (r + b) >= (g * 2.4 + 80):
                    px[x, y] = (0, 0, 0, 0)
                    continue
                dx = (x - cx) / rx
                dy = (y - cy) / ry
                ell = math.hypot(dx, dy)
                luma = (r + g + b) / 3.0
                mn, mx = min(r, g, b), max(r, g, b)
                grayish = (mx - mn) < 34
                # Тёмная матовка вокруг огня (чёрный круг в ассете), не трогаем само пламя
                if ell > 0.44 and grayish and luma < 54:
                    px[x, y] = (0, 0, 0, 0)
                    continue
                if ell > 0.52 and luma < 40:
                    px[x, y] = (0, 0, 0, 0)
                    continue

        rch, gch, bch, ach = img.split()
        ach = ach.filter(ImageFilter.GaussianBlur(0.45))
        img = Image.merge("RGBA", (rch, gch, bch, ach))
        return img

    @staticmethod
    def _snap_near_chroma_rgb(
        rgb_im: Image.Image, cr: int, cg: int, cb: int, tol: int = 108
    ) -> Image.Image:
        """
        После композита полупрозрачные края дают RGB ≠ #FF00FF — Tk не вырезает их.
        Подтягиваем близкие к ключу пиксели к точному цвету хромакея.
        """
        im = rgb_im.copy()
        px = im.load()
        w, h = im.size
        t2 = tol * tol
        for yy in range(h):
            for xx in range(w):
                r0, g0, b0 = px[xx, yy]
                if (r0 - cr) ** 2 + (g0 - cg) ** 2 + (b0 - cb) ** 2 <= t2:
                    px[xx, yy] = (cr, cg, cb)
        return im

    @staticmethod
    def _purge_magenta_screen_rgb(
        rgb_im: Image.Image, cr: int, cg: int, cb: int
    ) -> Image.Image:
        """
        Остатки «экранной» магенты/фуксии (высокие R и B, G заметно ниже) → точный ключ.
        Огонь/центр портала не трогаем (там B или R низкие).
        """
        im = rgb_im.copy()
        px = im.load()
        w, h = im.size
        for yy in range(h):
            for xx in range(w):
                r0, g0, b0 = px[xx, yy]
                mnrb = min(r0, b0)
                if (
                    mnrb >= 108
                    and g0 < mnrb * 0.52 + 58
                    and (r0 + b0) >= 278
                ):
                    px[xx, yy] = (cr, cg, cb)
        return im

    def _photo_from_rgba_chroma(self, rgba: Image.Image) -> ImageTk.PhotoImage:
        """Win / macOS хромакей: фон под GIF + -transparentcolor. macOS «окошко»: фон панели без прозрачности окна."""
        if platform.system() == "Darwin" and getattr(self, "_mac_framed_window", False):
            pr, pg, pb = self._frame_panel_rgb
            bg = Image.new("RGBA", rgba.size, (pr, pg, pb, 255))
            composed = Image.alpha_composite(bg, rgba).convert("RGB")
            composed = self._snap_near_chroma_rgb(composed, pr, pg, pb, tol=72)
            return ImageTk.PhotoImage(composed, master=self.canvas)
        r, g, b = self._chroma_rgb
        bg = Image.new("RGBA", rgba.size, (r, g, b, 255))
        composed = Image.alpha_composite(bg, rgba).convert("RGB")
        composed = self._snap_near_chroma_rgb(composed, r, g, b)
        composed = self._purge_magenta_screen_rgb(composed, r, g, b)
        return ImageTk.PhotoImage(composed, master=self.canvas)

    def _fit_rgba_to_widget_canvas(self, rgba: Image.Image) -> Image.Image:
        """Вписать кадр в квадрат окна с сохранением пропорций (letterbox)."""
        rgba = rgba.convert("RGBA")
        s = max(8, int(self.size))
        iw, ih = rgba.size
        if iw < 1 or ih < 1:
            return Image.new("RGBA", (s, s), (0, 0, 0, 0))
        sc = min(s / float(iw), s / float(ih))
        nw = max(1, int(round(iw * sc)))
        nh = max(1, int(round(ih * sc)))
        resized = rgba.resize((nw, nh), Image.Resampling.LANCZOS)
        if platform.system() == "Darwin" and getattr(self, "_mac_framed_window", False):
            bg = (*self._frame_panel_rgb, 255)
        else:
            bg = (*self._chroma_rgb, 255)
        out = Image.new("RGBA", (s, s), bg)
        x = (s - nw) // 2
        y = (s - nh) // 2
        out.paste(resized, (x, y), resized)
        return out

    def apply_mac_panel_background(self) -> None:
        """После смены цвета подложки в config — обновить Tk и пересобрать PhotoImage."""
        if platform.system() != "Darwin" or not getattr(self, "_mac_framed_window", False):
            return
        self._frame_panel_rgb = portal_config.load_widget_mac_panel_bg_rgb()
        hx = portal_config.load_widget_mac_panel_bg_hex()
        try:
            self.canvas.configure(bg=hx)
            self.root.configure(bg=hx)
        except tk.TclError:
            pass
        self.reload_portal_media()

    def load_portal_gif(self):
        """Загрузить GIF/PNG/WebP: путь из config (widget_media_path) или assets/, режим — widget_media_mode."""
        asset_path = self._find_portal_asset()
        if not asset_path:
            print(
                "[Portal] Нет portal*.gif / portal*.png в папке assets/ — рисованный портал. "
                "Положи, например, assets/portal_main.gif или portal_main.png"
            )
            return

        try:
            src = Image.open(asset_path)
            raw_frames: List[Image.Image] = []
            durations: List[int] = []

            if asset_path.lower().endswith(".png") or getattr(src, "n_frames", 1) == 1:
                try:
                    src.seek(0)
                except EOFError:
                    pass
                raw_frames.append(self._prepare_portal_frame_rgba(src))
            else:
                for frame in ImageSequence.Iterator(src):
                    raw_frames.append(self._prepare_portal_frame_rgba(frame))

            if not raw_frames:
                print("[Portal] Файл без кадров — рисованный портал")
                return

            raw_frames = [self._fit_rgba_to_widget_canvas(f) for f in raw_frames]

            wmode = portal_config.load_widget_media_mode()
            if wmode == "static":
                use_static_visual = True
            elif wmode == "animated":
                use_static_visual = False
            else:
                low = asset_path.lower()
                if low.endswith(".gif"):
                    use_static_visual = False
                elif len(raw_frames) > 1:
                    use_static_visual = False
                else:
                    use_static_visual = True

            if use_static_visual and len(raw_frames) > 1:
                raw_frames = [raw_frames[0]]

            self._portal_media_static_visual = bool(use_static_visual and raw_frames)
            self._static_rgba_full = (
                raw_frames[0].copy() if self._portal_media_static_visual else None
            )
            self._static_open_photo = None

            self.gif_frames_raw = [f.copy() for f in raw_frames]
            self.gif_frames = []
            self._mac_using_rgba_window = False

            use_rgba_mac = self._mac_real_transparency_enabled() and not getattr(
                self, "_mac_framed_window", False
            )
            if use_rgba_mac:
                rgba_ok = True
                for f in raw_frames:
                    try:
                        self.gif_frames.append(
                            ImageTk.PhotoImage(f.convert("RGBA"), master=self.canvas)
                        )
                    except Exception as ex:
                        print(
                            f"[Portal] macOS RGBA PhotoImage не удался ({ex}) — режим хромакея"
                        )
                        rgba_ok = False
                        self.gif_frames = []
                        break
                if rgba_ok and len(self.gif_frames) == len(raw_frames):
                    self._mac_using_rgba_window = True

            if not self.gif_frames:
                for f in raw_frames:
                    self.gif_frames.append(self._photo_from_rgba_chroma(f))
                if platform.system() == "Darwin" and getattr(self, "_mac_framed_window", False):
                    mode_note = f"macOS: окно с рамкой, фон {portal_config.load_widget_mac_panel_bg_hex()}"
                else:
                    mode_note = f"хромакей {self._chroma_hex}"
            else:
                mode_note = (
                    "macOS: альфа + прозрачное окно (pip: pyobjc — для NSWindow)"
                    if self._mac_using_rgba_window
                    else "хромакей"
                )

            if getattr(self, "_portal_media_static_visual", False):
                self.gif_frames = []
                self.gif_frames_raw = []
                self._gif_frame_durations = []
                try:
                    f0 = self._static_rgba_full
                    if f0 is not None:
                        if self._mac_using_rgba_window:
                            self._static_open_photo = ImageTk.PhotoImage(
                                f0.convert("RGBA"), master=self.canvas
                            )
                        else:
                            self._static_open_photo = self._photo_from_rgba_chroma(f0)
                        self._last_photo = self._static_open_photo
                except Exception as ex:
                    print(f"[Portal] статика: полный кадр: {ex}")
                    self._static_open_photo = None
                mode_note = f"{mode_note} | статика (масштаб при открытии/закрытии)"

            _nframes = len(self.gif_frames) or (1 if self._static_open_photo else 0)
            print(
                f"[Portal] Загружено {_nframes} кадр(ов) из {asset_path} ({mode_note})"
            )
            if platform.system() == "Darwin":
                try:
                    if self._mac_using_rgba_window:
                        self._mac_refresh_real_transparency()
                        for ms in (50, 150, 400):
                            self.root.after(ms, self._mac_nswindow_make_opaque_false)
                    elif not getattr(self, "_mac_framed_window", False):
                        self.root.after(60, self._mac_apply_chroma_transparency)
                        self.root.after(400, self._mac_apply_chroma_transparency)
                except Exception:
                    pass

        except Exception as e:
            print(f"[Portal] Ошибка загрузки ассета портала: {e}")
            import traceback

            traceback.print_exc()

    def set_transient_portal_media(self, path: Optional[str]) -> None:
        """Временно показать другой ассет (пресет); None — сбросить на обычный config/assets."""
        self._transient_media_path = path if path and os.path.isfile(path) else None
        self._cancel_anim()
        self.gif_frames = []
        self.gif_frames_raw = []
        self._gif_frame_durations = []
        self._portal_media_static_visual = False
        self._static_rgba_full = None
        self._static_open_photo = None
        self._mac_using_rgba_window = False
        self.anim_state = self.ANIM_HIDDEN
        self.anim_frame_idx = 0
        self.load_portal_gif()

    def clear_transient_portal_media(self) -> None:
        """Убрать подмену и перечитать обычное медиа."""
        self.set_transient_portal_media(None)

    def reload_portal_media(self) -> None:
        """Перечитать путь/режим из config и заново загрузить медиа (только главный поток Tk)."""
        self._transient_media_path = None
        self._cancel_anim()
        self.gif_frames = []
        self.gif_frames_raw = []
        self._gif_frame_durations = []
        self._portal_media_static_visual = False
        self._static_rgba_full = None
        self._static_open_photo = None
        self._mac_using_rgba_window = False
        self.anim_state = self.ANIM_HIDDEN
        self.anim_frame_idx = 0
        self.load_portal_gif()

    # ───────────────────────────── АНИМАЦИЯ ─────────────────────────

    def _cancel_anim(self):
        if self._anim_after_id is not None:
            target = getattr(self, "_anim_master", None)
            if target is not None and hasattr(target, "after_cancel"):
                try:
                    target.after_cancel(self._anim_after_id)
                except Exception:
                    for t in (getattr(self, "main_app", None), self.root):
                        if t is None:
                            continue
                        try:
                            t.after_cancel(self._anim_after_id)
                            break
                        except Exception:
                            continue
            else:
                for t in (getattr(self, "main_app", None), self.root):
                    if t is None:
                        continue
                    try:
                        t.after_cancel(self._anim_after_id)
                        break
                    except Exception:
                        continue
            self._anim_after_id = None
            self._anim_master = None

    def _schedule_anim_ms(self, delay_ms: int, callback) -> None:
        """
        Таймер анимации на Toplevel (self.root): кадры рисуются на этом окне —
        через main_app.after (CTk) на части систем колбэк срабатывал, а перерисовка портала не шла.
        """
        delay_ms = max(1, int(delay_ms))
        self._anim_master = self.root
        try:
            self._anim_after_id = self.root.after(delay_ms, callback)
            return
        except Exception:
            self._anim_master = None
        try:
            if self.main_app is not None and hasattr(self.main_app, "after"):
                self._anim_master = self.main_app
                self._anim_after_id = self.main_app.after(delay_ms, callback)
                return
        except Exception:
            pass
        self._anim_master = self.root
        self._anim_after_id = self.root.after(delay_ms, callback)

    def _gif_delay_for_idx(self, idx: int) -> int:
        if self._gif_frame_durations and 0 <= idx < len(self._gif_frame_durations):
            return max(16, self._gif_frame_durations[idx])
        return max(16, self._anim_speed_ms)

    def _show_static_scaled(self, t: float) -> None:
        """Статичная картинка: масштаб t ∈ [0, 1] от центра."""
        base = self._static_rgba_full
        if base is None:
            return
        t = max(0.0, min(1.0, float(t)))
        self.canvas.delete("all")
        cx, cy = self.size // 2, self.size // 2
        if t >= 0.998 and getattr(self, "_static_open_photo", None):
            photo = self._static_open_photo
            self._last_photo = photo
            self.canvas.create_image(cx, cy, image=photo, anchor=tk.CENTER)
            return
        scale = 0.06 + 0.94 * (t ** 0.82)
        side = max(2, int(self.size * scale))
        small = base.resize((side, side), Image.Resampling.LANCZOS)
        if self._mac_using_rgba_window and not getattr(
            self, "_mac_framed_window", False
        ):
            photo = ImageTk.PhotoImage(small.convert("RGBA"), master=self.canvas)
        else:
            photo = self._photo_from_rgba_chroma(small)
        self._last_photo = photo
        self.canvas.create_image(cx, cy, image=photo, anchor=tk.CENTER)

    def _show_frame(self, idx: int):
        """Отрисовать один кадр на canvas."""
        self.canvas.delete("all")
        cx, cy = self.size // 2, self.size // 2

        if self.gif_frames:
            idx = max(0, min(idx, len(self.gif_frames) - 1))
            photo = self.gif_frames[idx]
            self._last_photo = photo
            self.canvas.create_image(cx, cy, image=photo, anchor=tk.CENTER)
        else:
            # Fallback: рисованный портал со scale-эффектом (idx=0 → видимый радиус, не ноль)
            total = 20
            scale = min(1.0, (idx + 1) / max(1, total))
            r = max(4.0, (self.size // 2 - 18) * scale)
            if r > 1:
                self._draw_portal(cx, cy, r)

    def _animate_step(self):
        """Один шаг анимации — планируется через self.root.after (перерисовка canvas Toplevel)."""
        if self.anim_state == self.ANIM_HIDDEN:
            return

        steps = max(8, int(getattr(self, "_static_anim_steps", 18)))

        if self.anim_state == self.ANIM_OPENING and getattr(
            self, "_portal_media_static_visual", False
        ):
            tt = self.anim_frame_idx / max(1, steps - 1)
            self._show_static_scaled(tt)
            if self.anim_frame_idx < steps - 1:
                self.anim_frame_idx += 1
                self._schedule_anim_ms(self._anim_speed_ms, self._animate_step)
            else:
                self.anim_state = self.ANIM_OPEN
                self._show_static_scaled(1.0)
            return

        if self.anim_state == self.ANIM_OPEN and getattr(
            self, "_portal_media_static_visual", False
        ):
            self._show_static_scaled(1.0)
            return

        if self.anim_state == self.ANIM_CLOSING and getattr(
            self, "_portal_media_static_visual", False
        ):
            tt = self.anim_frame_idx / max(1, steps - 1)
            self._show_static_scaled(tt)
            if self.anim_frame_idx > 0:
                self.anim_frame_idx -= 1
                self._schedule_anim_ms(self._anim_speed_ms, self._animate_step)
            else:
                self.anim_state = self.ANIM_HIDDEN
                try:
                    self.root.withdraw()
                except tk.TclError:
                    pass
            return

        total = len(self.gif_frames) if self.gif_frames else 20

        # Пока открыт — цикл GIF
        if self.anim_state == self.ANIM_OPEN and self.gif_frames:
            self.anim_frame_idx = (self.anim_frame_idx + 1) % len(self.gif_frames)
            self._show_frame(self.anim_frame_idx)
            self._schedule_anim_ms(self._gif_delay_for_idx(self.anim_frame_idx), self._animate_step)
            return

        self._show_frame(self.anim_frame_idx)

        if self.anim_state == self.ANIM_OPENING:
            if self.gif_frames:
                if self.anim_frame_idx < total - 1:
                    d = self._gif_delay_for_idx(self.anim_frame_idx)
                    self.anim_frame_idx += 1
                    self._schedule_anim_ms(d, self._animate_step)
                else:
                    self.anim_state = self.ANIM_OPEN
                    self._schedule_anim_ms(self._gif_delay_for_idx(self.anim_frame_idx), self._animate_step)
            else:
                if self.anim_frame_idx < total - 1:
                    self.anim_frame_idx += 1
                    self._schedule_anim_ms(self._anim_speed_ms, self._animate_step)
                else:
                    self.anim_state = self.ANIM_OPEN

        elif self.anim_state == self.ANIM_CLOSING:
            if self.gif_frames:
                if self.anim_frame_idx > 0:
                    d = self._gif_delay_for_idx(self.anim_frame_idx)
                    self.anim_frame_idx -= 1
                    self._schedule_anim_ms(d, self._animate_step)
                else:
                    self.anim_state = self.ANIM_HIDDEN
                    self.root.withdraw()
            else:
                if self.anim_frame_idx > 0:
                    self.anim_frame_idx -= 1
                    self._schedule_anim_ms(self._anim_speed_ms, self._animate_step)
                else:
                    self.anim_state = self.ANIM_HIDDEN
                    self.root.withdraw()

    def start_opening_animation(self):
        """Запустить анимацию разворачивания (вызывается при init)."""
        self._cancel_anim()
        self.anim_state = self.ANIM_OPENING
        self.anim_frame_idx = 0
        self._animate_step()

    def _draw_portal(self, cx, cy, radius):
        """Fallback-рисованный портал (если нет GIF)."""
        self.canvas.create_oval(
            cx - radius, cy - radius, cx + radius, cy + radius,
            outline="#00A8FF", width=3, fill="#02060a",
        )
        inner = radius * 0.72
        pts = []
        for i in range(16):
            a = self.angle + (i * 2 * math.pi / 16)
            pts.extend([cx + inner * math.cos(a), cy + inner * math.sin(a)])
        if len(pts) >= 6:
            self.canvas.create_polygon(pts, outline="#FF6B35", fill="#1a0a05", width=2)

    # ───────────────────────────── ПОКАЗАТЬ / СКРЫТЬ ────────────────

    def hide(self):
        """Закрыть виджет с анимацией сворачивания."""
        self._cancel_anim()
        steps = max(8, int(getattr(self, "_static_anim_steps", 18)))
        if getattr(self, "_portal_media_static_visual", False) and (
            self._static_rgba_full is not None or self._static_open_photo is not None
        ):
            if self.anim_state == self.ANIM_OPEN:
                self.anim_frame_idx = steps - 1
            elif self.anim_state == self.ANIM_OPENING:
                self.anim_frame_idx = min(self.anim_frame_idx, steps - 1)
            self.anim_state = self.ANIM_CLOSING
            self._animate_step()
            return
        if self.gif_frames:
            # Если портал уже открыт — начинаем с последнего кадра
            if self.anim_state == self.ANIM_OPEN:
                self.anim_frame_idx = len(self.gif_frames) - 1
            # Иначе — с текущего кадра (мог быть в середине открытия)
            self.anim_state = self.ANIM_CLOSING
            self._animate_step()
        else:
            self.anim_state = self.ANIM_HIDDEN
            self.root.withdraw()

    def show(self):
        """Показать виджет с анимацией разворачивания (главное окно не поднимаем)."""
        self._cancel_anim()
        self.root.deiconify()
        self.root.update_idletasks()
        # macOS: main_app.lower() БЕЗ аргумента опускает ВСЁ окно приложения —
        # виджет оказывается под рабочим столом и «невидим». Поднимаем виджет НАД CTk.
        try:
            if self.main_app is not None:
                try:
                    self.root.lift(self.main_app)
                except tk.TclError:
                    self.root.lift()
            else:
                self.root.lift()
        except Exception:
            try:
                self.root.lift()
            except tk.TclError:
                pass
        self.root.update_idletasks()
        if platform.system() == "Darwin":
            if self._mac_using_rgba_window:
                self._mac_refresh_real_transparency()
                # Сразу и с задержкой: после deiconify другой NSWindow / геометрия
                self.root.after(0, self._mac_nswindow_make_opaque_false)
                for ms in (20, 100, 250, 600):
                    self.root.after(ms, self._mac_nswindow_make_opaque_false)
            else:
                self._mac_apply_chroma_transparency()
        try:
            self.root.attributes("-topmost", True)
        except tk.TclError:
            pass
        try:
            self.root.focus_force()
        except Exception:
            pass
        self.anim_state = self.ANIM_OPENING
        self.anim_frame_idx = 0
        self.root.update_idletasks()
        try:
            self.root.update()
        except Exception:
            pass
        # Первый кадр после отрисовки окна (синхронный шаг часто попадает до первого paint)
        self.root.after(1, self._animate_step)

    def is_visible(self) -> bool:
        try:
            return bool(self.root.winfo_viewable())
        except Exception:
            return False

    def destroy(self):
        self._cancel_anim()
        try:
            self.root.destroy()
        except Exception:
            pass

    # ───────────────────────────── МЫШЬ / БИНДИНГИ ──────────────────

    def setup_mouse_bindings(self):
        def bind_drag(w):
            w.bind("<Alt-Button-1>", self.start_drag)
            w.bind("<Alt-B1-Motion>", self.on_drag)

        bind_drag(self.root)
        bind_drag(self.canvas)

        # Только canvas: привязка на root дублирует событие (toplevel входит в bindtags canvas → два файла)
        self.canvas.bind("<Double-Button-1>", self.on_double_click_clipboard_image)
        self.canvas.bind("<Triple-Button-1>", lambda e: self.show_settings())
        self.canvas.bind("<Control-Button-1>", lambda e: self.on_portal_click())
        self.root.bind("<Button-3>", self.show_context_menu)
        self.canvas.bind("<Button-3>", self.show_context_menu)

    def start_drag(self, event):
        self.drag_start_x = event.x
        self.drag_start_y = event.y

    def on_drag(self, event):
        x = self.root.winfo_x() + event.x - self.drag_start_x
        y = self.root.winfo_y() + event.y - self.drag_start_y
        self.root.geometry(f"+{x}+{y}")

    # ───────────────────────────── DRAG & DROP ───────────────────────

    def _setup_windnd_drop(self):
        """Windows: перетаскивание файлов из Проводника."""
        try:
            import windnd

            def on_drop(files):
                paths: List[str] = []
                enc = sys.getfilesystemencoding() or "utf-8"
                for b in files:
                    if isinstance(b, str):
                        paths.append(b)
                        continue
                    try:
                        paths.append(b.decode("utf-8"))
                    except Exception:
                        try:
                            paths.append(b.decode(enc))
                        except Exception:
                            paths.append(b.decode("mbcs", errors="replace"))
                if paths:
                    plist = list(paths)
                    q = getattr(self.main_app, "_ui_signal_queue", None)
                    if q is not None:
                        try:
                            q.put(("drop", plist))
                            return
                        except Exception:
                            pass
                    try:

                        def _do_send():
                            try:
                                self.send_files(plist)
                            except Exception as ex:
                                print(f"[Portal] send_files после drop: {ex}")

                        if self.main_app and hasattr(self.main_app, "after"):
                            self.main_app.after(0, _do_send)
                        else:
                            self.root.after(0, _do_send)
                    except Exception:
                        pass

            windnd.hook_dropfiles(self.root, on_drop)
            self._windnd_ok = True
        except Exception as e:
            print(f"[Portal] windnd не сработал ({e}), пробуем tkinterdnd2…")
            try:
                from portal_tk_compat import ensure_tkdnd_tk_misc_patch

                from tkinterdnd2 import TkinterDnD, DND_FILES
                TkinterDnD._require(self.root)
                ensure_tkdnd_tk_misc_patch()
                self._dnd_tkinterdnd2 = True
                self.canvas.drop_target_register(DND_FILES)
                self.canvas.dnd_bind("<<Drop>>", self._on_tkdnd_drop)
            except Exception as e2:
                print(f"[Portal] И drag&drop недоступен: {e2}")

    def setup_drag_drop_tkdnd(self):
        """macOS / Linux: tkinterdnd2 на canvas."""
        if not self._dnd_tkinterdnd2:
            return
        try:
            from tkinterdnd2 import DND_FILES
            self.canvas.drop_target_register(DND_FILES)
            self.canvas.dnd_bind("<<Drop>>", self._on_tkdnd_drop)
        except Exception as e:
            print(f"[Portal] Не удалось включить drop: {e}")

    def _on_tkdnd_drop(self, event):
        try:
            import re
            raw = event.data.strip()
            files: List[str] = []
            if platform.system() == "Windows":
                if "{" in raw:
                    files = [p for p in re.findall(r"\{([^}]*)\}", raw) if p]
                else:
                    files = list(self.root.tk.splitlist(raw))
            else:
                files = list(self.root.tk.splitlist(raw))
            if files:
                fl = list(files)
                q = getattr(self.main_app, "_ui_signal_queue", None)
                if q is not None and platform.system() == "Windows":
                    try:
                        q.put(("drop", fl))
                    except Exception:
                        pass
                    return

                def _do():
                    try:
                        self.send_files(fl)
                    except Exception as ex:
                        print(f"[Portal] Ошибка send_files после Drop: {ex}")

                if self.main_app and hasattr(self.main_app, "after"):
                    self.main_app.after(0, _do)
                else:
                    self.root.after(0, _do)
        except Exception as ex:
            print(f"[Portal] Ошибка Drop: {ex}")

    # ───────────────────────────── КОНТЕКСТНОЕ МЕНЮ ─────────────────

    def show_context_menu(self, event):
        menu = tk.Menu(self.root, tearoff=0)
        clip_lbls = i18n.incoming_clipboard_files_mode_labels()
        menu.add_command(
            label=i18n.tr("widget.menu_remote_ip"),
            command=self.show_ip_dialog,
        )
        menu.add_command(
            label=i18n.tr("widget.menu_pick_file"), command=self.on_portal_click
        )
        cur = portal_config.load_incoming_clipboard_files_mode()
        clip_var = tk.StringVar(value=cur)
        clip_menu = tk.Menu(menu, tearoff=0)

        def _set_mode(mode_key: str) -> None:
            if portal_config.save_incoming_clipboard_files_mode(mode_key):
                clip_var.set(mode_key)
                if self.main_app and hasattr(self.main_app, "log"):
                    self.main_app.log(
                        i18n.tr(
                            "log.clipboard_recv_mode",
                            label=clip_lbls.get(mode_key, mode_key),
                        )
                    )
            else:
                clip_var.set(portal_config.load_incoming_clipboard_files_mode())

        for key in ("both", "disk", "clipboard"):
            clip_menu.add_radiobutton(
                label=clip_lbls.get(key, key),
                variable=clip_var,
                value=key,
                command=lambda k=key: _set_mode(k),
            )
        menu.add_cascade(
            label=i18n.tr("widget.menu_clip_recv"),
            menu=clip_menu,
        )
        menu.add_command(label=i18n.tr("widget.menu_hide"), command=self.hide)
        menu.add_separator()
        menu.add_command(label=i18n.tr("widget.menu_exit"), command=self.destroy)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ───────────────────────────── IP / НАСТРОЙКИ ───────────────────

    def show_settings(self, event=None):
        self.show_ip_dialog()

    def on_double_click_clipboard_image(self, event=None):
        """Двойной клик: картинка из буфера → временный файл → отправка на второй ПК."""
        self.root.after(10, self._double_click_clipboard_worker)
        return "break"

    def _double_click_clipboard_worker(self):
        now = time.monotonic()
        if now - self._last_double_clipboard_send_mono < 0.45:
            return
        self._last_double_clipboard_send_mono = now

        im = grab_clipboard_image()
        if im is None:
            if self.main_app and hasattr(self.main_app, "log"):
                self.main_app.log(i18n.tr("widget.no_clipboard_image"))
            return

        def send_with_ip(addr: str):
            ip = (addr or "").strip()
            if not ip:
                return
            self.target_ip = ip
            if self.main_app and hasattr(self.main_app, "set_remote_peer_ip"):
                self.main_app.set_remote_peer_ip(ip)
            else:
                portal_config.save_remote_ip(ip)
            self._save_clipboard_image_and_send(im, ip)

        ip = self._resolve_peer_ip()
        if not ip:
            self.show_ip_dialog_sync(send_with_ip)
            return
        self._save_clipboard_image_and_send(im, ip)

    def _save_clipboard_image_and_send(self, im, ip: str):
        import tempfile

        tmp = Path(tempfile.gettempdir()) / f"portal_clip_{int(time.time() * 1000)}.png"
        try:
            im.save(tmp, "PNG")
            if self.main_app and hasattr(self.main_app, "log"):
                self.main_app.log(
                    i18n.tr(
                        "log.clipboard_image_send",
                        path=tmp.name,
                        ip=ip,
                    )
                )
            self.send_files([str(tmp)], portal_clipboard=True)
        except Exception as e:
            if self.main_app and hasattr(self.main_app, "log"):
                self.main_app.log(
                    i18n.tr("log.clipboard_image_fail", err=e)
                )
            print(f"[Portal] clipboard image: {e}")

    def show_ip_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title(i18n.tr("widget.ip_dialog_title"))
        dialog.geometry("320x160")
        dialog.attributes("-topmost", True)

        tk.Label(dialog, text=i18n.tr("widget.ip_label_simple")).pack(pady=10)
        ip_entry = tk.Entry(dialog, width=28)
        ip_entry.pack(pady=5)
        pref = self.target_ip or portal_config.load_remote_ip() or "100."
        ip_entry.insert(0, pref)

        def save_ip():
            ip = ip_entry.get().strip()
            if ip:
                self.target_ip = ip
                if self.main_app and hasattr(self.main_app, "set_remote_peer_ip"):
                    self.main_app.set_remote_peer_ip(ip)
                else:
                    portal_config.save_remote_ip(ip)
            dialog.destroy()

        tk.Button(dialog, text=i18n.tr("secret.save"), command=save_ip).pack(
            pady=10
        )

    def show_ip_dialog_sync(self, callback):
        dialog = tk.Toplevel(self.root)
        dialog.title(i18n.tr("widget.ip_dialog_title"))
        dialog.geometry("320x160")
        dialog.attributes("-topmost", True)
        dialog.grab_set()

        tk.Label(dialog, text=i18n.tr("widget.ip_label_full")).pack(pady=10)
        ip_entry = tk.Entry(dialog, width=28)
        ip_entry.pack(pady=5)
        pref = self.target_ip or portal_config.load_remote_ip() or "100."
        ip_entry.insert(0, pref)
        ip_entry.focus()

        def save_ip():
            ip = ip_entry.get().strip()
            if ip:
                callback(ip)
            dialog.destroy()

        ip_entry.bind("<Return>", lambda e: save_ip())
        tk.Button(dialog, text="OK", command=save_ip).pack(pady=10)

    # ───────────────────────────── ФАЙЛЫ ────────────────────────────

    def on_portal_click(self):
        from tkinter import filedialog
        files = filedialog.askopenfilenames(
            title=i18n.tr("widget.file_pick_title")
        )
        if files:
            self.send_files(list(files))

    def on_double_click_portal(self, event=None):
        """Двойной клик: если в буфере картинка — отправить; иначе выбор файла."""
        try:
            from PIL import ImageGrab
        except ImportError:
            self.on_portal_click()
            return
        try:
            data = ImageGrab.grabclipboard()
        except Exception as e:
            if self.main_app and hasattr(self.main_app, "log"):
                try:
                    self.main_app.after(
                        0,
                        lambda m=str(e): self.main_app.log(
                            i18n.tr("log.widget_clipboard_err", m=m)
                        ),
                    )
                except Exception:
                    pass
            self.on_portal_click()
            return
        if data is None:
            self.on_portal_click()
            return
        if isinstance(data, Image.Image):
            try:
                fd, path = tempfile.mkstemp(prefix="portal_clip_", suffix=".png")
                os.close(fd)
                data.save(path, "PNG")
            except Exception as e:
                if self.main_app and hasattr(self.main_app, "log"):
                    try:
                        self.main_app.after(
                            0,
                            lambda m=str(e): self.main_app.log(
                                i18n.tr("log.widget_image_err", m=m)
                            ),
                        )
                    except Exception:
                        pass
                self.on_portal_click()
                return
            self._send_clipboard_image_path(path)
            return
        if isinstance(data, list):
            paths = [p for p in data if isinstance(p, str) and os.path.isfile(p)]
            if paths:
                self.send_files(paths)
                return
        self.on_portal_click()

    def _send_clipboard_image_path(self, path: str) -> None:
        ips = self._resolve_peer_ips()
        if not ips:
            result: List[str] = []

            def cb(addr: str):
                result.append(addr)

            self.show_ip_dialog_sync(cb)
            if not result:
                try:
                    os.unlink(path)
                except Exception:
                    pass
                return
            ip = result[0].strip()
            self.target_ip = ip
            if self.main_app and hasattr(self.main_app, "set_remote_peer_ip"):
                self.main_app.set_remote_peer_ip(ip)
            else:
                portal_config.save_remote_ip(ip)
            ips = [ip]
        if self.main_app and hasattr(self.main_app, "log"):
            try:
                self.main_app.after(
                    0,
                    lambda: self.main_app.log(
                        i18n.tr("log.widget_send_clip_image")
                    ),
                )
            except Exception:
                pass
        threading.Thread(target=self._send_file_to_ips_then_unlink, args=(path, ips), daemon=True).start()

    def _send_file_to_ips_then_unlink(self, path: str, ips: List[str]) -> None:
        try:
            for ip in ips:
                if self.main_app and hasattr(self.main_app, "send_file"):
                    self.main_app.send_file(path, ip)
        finally:
            try:
                os.unlink(path)
            except Exception:
                pass

    def _resolve_peer_ip(self) -> Optional[str]:
        ip = self.target_ip
        if not ip and self.main_app:
            ip = getattr(self.main_app, "remote_peer_ip", None)
        if not ip:
            ip = portal_config.load_remote_ip()
        return ip

    def send_files(self, files: List[str], portal_clipboard: bool = False):
        targets: List[str] = []
        if self.main_app and hasattr(self.main_app, "get_target_ips"):
            try:
                targets = list(self.main_app.get_target_ips() or [])
            except Exception:
                targets = []

        if not targets:
            ip = self._resolve_peer_ip()
            if not ip:
                result: List[str] = []

                def cb(addr: str):
                    result.append(addr)

                self.show_ip_dialog_sync(cb)
                if not result:
                    return
                ip = result[0].strip()
                self.target_ip = ip
                if self.main_app and hasattr(self.main_app, "set_remote_peer_ip"):
                    self.main_app.set_remote_peer_ip(ip)
                else:
                    portal_config.save_remote_ip(ip)
                targets = [ip]
            else:
                self.target_ip = ip
                targets = [ip]

        for fp in files:
            if self.main_app and hasattr(self.main_app, "send_file"):
                if hasattr(self.main_app, "log"):
                    self.main_app.log(
                        i18n.tr(
                            "log.widget_send_files",
                            name=Path(fp).name,
                            n=len(targets),
                        )
                    )
                kw = {"portal_clipboard": True} if portal_clipboard else {}
                for ip in targets:
                    threading.Thread(
                        target=self.main_app.send_file,
                        args=(fp, ip),
                        kwargs=kw,
                        daemon=True,
                    ).start()


# ─────────────────────────── ГОРЯЧИЕ КЛАВИШИ ────────────────────────────────

class GlobalHotkeyManager:
    """
    macOS: NSEvent global monitor → очередь → poll на главном потоке (без GIL crash);
           плюс Tk bind_all когда окно Портала в фокусе (Apple не шлёт global в своё приложение).
    Windows: pynput — только put в main_app._ui_signal_queue; разбор в PortalApp._drain_ui_signal_queue (главный поток).
    """

    # macOS virtual keycodes (US layout, layout-independent)
    _KEY_P = 35
    _KEY_C = 8
    _KEY_V = 9

    _NSCmd   = 1 << 20   # NSCommandKeyMask
    _NSAlt   = 1 << 19   # NSAlternateKeyMask (Option)
    _NSShift = 1 << 17   # NSShiftKeyMask
    _NSControl = 1 << 18  # NSControlKeyMask (Cmd+Ctrl+P/C/V — без конфликта с Терминалом)
    _NSMask  = 0xFFFF0000
    _NSKeyDownMask = 1 << 10

    def __init__(self, widget: PortalWidget, main_app: Any):
        self.widget   = widget
        self.main_app = main_app
        self._running = True
        self._global_monitor = None   # держим ссылку — иначе GC удалит
        self._local_monitor  = None
        self._handle_ref     = None   # держим ссылку на callback-блок
        # macOS: pipe — из NSEvent callback только os.write (без queue/GIL сюрпризов)
        self._hk_r: Optional[int] = None
        self._hk_w: Optional[int] = None
        self._last_toggle_debounce = 0.0
        self._last_push_debounce = 0.0
        self._last_pull_debounce = 0.0
        self._hotkey_helper_proc: Optional[Any] = None
        self._hotkey_pipe_got_byte = False
        # Любой из CGEventTap / NSEvent / pynput подтвердил старт (для healthcheck)
        self._helper_global_listener_ok = False
        # macOS: чтение pipe через Tk fileevent — иначе after(25) замирает при свёрнутом окне
        self._mac_pipe_fileevent_installed = False
        # Одноразовое окно «открыть Мониторинг ввода» (healthcheck / helper stderr)
        self._mac_input_dialog_shown = False

    def _enqueue_toggle(self) -> None:
        q = getattr(self.main_app, "_ui_signal_queue", None)
        if q is not None:
            try:
                q.put("toggle")
                return
            except Exception:
                pass
        try:
            self.main_app.after(0, self._toggle_ui)
        except Exception:
            pass

    def _enqueue_push(self) -> None:
        q = getattr(self.main_app, "_ui_signal_queue", None)
        if q is not None:
            try:
                q.put("push")
                return
            except Exception:
                pass
        self._on_push()

    def _enqueue_pull(self) -> None:
        q = getattr(self.main_app, "_ui_signal_queue", None)
        if q is not None:
            try:
                q.put("pull")
                return
            except Exception:
                pass
        self._on_pull()

    def _log(self, msg: str, prefix: str = "⌨️") -> None:
        portal_thread_log(self.main_app, msg, prefix)

    def start(self):
        self._log(f"Запуск хоткеев на {platform.system()}")
        _log_to_file(f"[Portal] debug-файл: {_hotkey_log_path()}")

        # 1. Tk bind_all — работает сразу, без Accessibility, когда Portal в фокусе
        self._bind_tk_all()

        if platform.system() == "Darwin":
            # Python 3.13 + PyObjC NSEvent в фоне даёт PyEval_RestoreThread / Abort — только bind_all
            use_objc = sys.version_info < (3, 13) or os.environ.get(
                "PORTAL_MAC_FORCE_GLOBAL_HOTKEYS", ""
            ).strip() in ("1", "true", "yes")
            if use_objc:
                try:
                    import fcntl

                    self._hk_r, self._hk_w = os.pipe()
                    fcntl.fcntl(self._hk_r, fcntl.F_SETFL, os.O_NONBLOCK)
                except Exception as e:
                    self._log(f"⚠️ pipe хоткеев не создан: {e}")
                    self._hk_r = self._hk_w = None
                self._schedule_hotkey_poll()
                threading.Thread(
                    target=self._run_mac_global, daemon=True, name="portal-hotkeys-global"
                ).start()
                try:
                    self.main_app.after(350, self._setup_nslocal_monitor)
                except Exception as e:
                    self._log(f"after(local monitor): {e}")
                self._log(
                    "✅ Глобальные хоткеи: по умолчанию Cmd+Ctrl+P/C/V; "
                    "PORTAL_MAC_HOTKEY_LEGACY=1 — Cmd+Option+P, Cmd+Shift+C/V (NSEvent + Accessibility)"
                )
            else:
                # Python 3.13+: нельзя крутить NSRunLoop.runUntilDate из Tk after() — реентрантность
                # Tcl ↔ AppKit даёт PyEval_RestoreThread / SIGABRT (см. crash: runUntilDate внутри draw).
                # Нельзя NSEvent global в фоне — тот же GIL-крэш. Остаётся hotkey-helper subprocess + pipe.
                self._hk_r = self._hk_w = None
                try:
                    import fcntl

                    self._hk_r, self._hk_w = os.pipe()
                    fcntl.fcntl(self._hk_r, fcntl.F_SETFL, os.O_NONBLOCK)
                except Exception as e:
                    self._log(f"⚠️ pipe хоткеев: {e}")
                    self._hk_r = self._hk_w = None
                self._schedule_hotkey_poll()

                if os.environ.get("PORTAL_MAC_NO_HOTKEY_HELPER", "").strip() in (
                    "1",
                    "true",
                    "yes",
                ):
                    self._log(
                        "PORTAL_MAC_NO_HOTKEY_HELPER=1 — глобальных хоткеев нет, только Tk при фокусе на Portal."
                    )
                else:
                    threading.Thread(
                        target=self._run_mac_hotkey_helper_subprocess,
                        daemon=True,
                        name="portal-mac-hotkey-helper",
                    ).start()
                    try:
                        self.main_app.after(3500, self._hotkey_helper_healthcheck)
                    except Exception:
                        pass

                # Local NSEvent: Apple не шлёт global monitor в своё приложение — без этого только Tk (ломается на РУ).
                if os.environ.get("PORTAL_MAC_NSLOCAL_MONITOR", "1").strip().lower() not in (
                    "0",
                    "false",
                    "no",
                    "off",
                ):
                    try:
                        self.main_app.after(350, self._setup_nslocal_monitor)
                    except Exception as e:
                        self._log(f"after(local monitor 3.13+): {e}")

                self._log(
                    "⌛ macOS 3.13+: глобальные хоткеи — процесс hotkey-helper → pipe (без NSRunLoop в Tk). "
                    "Права «Мониторинг ввода»: "
                    + _mac_privacy_target_hint()
                )
        else:
            t = threading.Thread(target=self._run_win, daemon=True, name="portal-hotkeys-win")
            t.start()

        # Журнал: внутри CTkTextbox события обрабатывает класс Text раньше bind_all → хоткеи «молчат».
        try:
            lt = getattr(self.main_app, "log_text", None)
            if lt is not None:
                self.bind_inner_text_hotkeys(lt)
        except Exception:
            pass

    def bind_inner_text_hotkeys(self, ctk_text_widget: Any) -> None:
        """
        CustomTkinter CTkTextbox: цепочка bindtags у внутреннего tk.Text обрабатывает клавиши до тега «all»,
        поэтому bind_all не срабатывает при фокусе в журнале (и в других многострочных полях).
        Дублируем сочетания на _textbox с add=True и return "break".
        """
        inner = getattr(ctk_text_widget, "_textbox", None)
        if inner is None or not hasattr(inner, "bind"):
            return

        def _toggle(_e=None):
            self._log("Tk bind (текстовое поле) → переключить виджет", "🔑")
            self._toggle_ui()
            return "break"

        def _push(_e=None):
            self._log("Tk bind (текстовое поле) → отправить буфер", "🔑")
            self._on_push()
            return "break"

        def _pull(_e=None):
            self._log("Tk bind (текстовое поле) → забрать буфер с удалённого ПК", "🔑")
            self._on_pull()
            return "break"

        toggle_seqs, push_seqs, pull_seqs = _portal_hotkey_tk_sequences()
        for seq in toggle_seqs:
            try:
                inner.bind(seq, _toggle, add=True)
            except Exception:
                pass
        for seq in push_seqs:
            try:
                inner.bind(seq, _push, add=True)
            except Exception:
                pass
        for seq in pull_seqs:
            try:
                inner.bind(seq, _pull, add=True)
            except Exception:
                pass

    def _mac_keypress_cmd_ctrl_hotkey(self, event) -> Optional[str]:
        """
        Раскладка РУ: последовательности <Command-Control-p> часто не срабатывают в Tk.
        Ловим те же физические keycode, что и portal_mac_hotkey_helper (35=P, 8=C, 9=V),
        при зажатых Cmd+Ctrl. Для латинской раскладки не дублируем — там уже bind_all.
        """
        if not self._running or platform.system() != "Darwin":
            return None
        if os.environ.get("PORTAL_MAC_HOTKEY_LEGACY", "").strip().lower() in (
            "1",
            "true",
            "yes",
        ):
            return None
        try:
            kc = int(getattr(event, "keycode", 0) or 0)
        except (TypeError, ValueError):
            return None
        if kc not in (35, 8, 9):
            return None
        ks = getattr(event, "keysym", "") or ""
        if len(ks) == 1 and ks.isascii() and ks.lower() in "pcv":
            return None
        st = int(getattr(event, "state", 0) or 0)
        # Tk/macOS: Control=0x4; Command часто 0x8, на части сборок — другие биты
        ctrl = bool(st & 0x0004)
        cmd = bool(st & 0x0008) or bool(st & 0x0100) or bool(st & 0x20000)
        if not (ctrl and cmd):
            return None
        if kc == 35:
            self._log("Tk физ. клавиша (напр. РУ) → переключить виджет", "🔑")
            self._toggle_ui()
            return "break"
        if kc == 8:
            self._log("Tk физ. клавиша → отправить буфер", "🔑")
            self._on_push()
            return "break"
        if kc == 9:
            self._log("Tk физ. клавиша → забрать буфер", "🔑")
            self._on_pull()
            return "break"
        return None

    # ── 1. Tk bind_all ─────────────────────────────────────────────────────────

    def _bind_tk_all(self):
        """
        bind_all на корневом окне ловит клавиши со всего приложения.
        На macOS Option-клавиша в Tk = Alt, Command = Command или Meta.
        Биндим несколько вариантов написания.
        """
        def _toggle(e=None):
            self._log("Tk bind → переключить виджет", "🔑")
            self._toggle_ui()
            return "break"

        def _push(e=None):
            self._log("Tk bind → отправить буфер", "🔑")
            self._on_push()
            return "break"

        def _pull(e=None):
            self._log("Tk bind → забрать буфер с удалённого ПК", "🔑")
            self._on_pull()
            return "break"

        is_mac = platform.system() == "Darwin"
        # CTk + Toplevel виджета — биндим на все корни, иначе часть событий теряется.
        # Сначала реальный Tk root (toplevel), затем main_app — так bind_all чаще ловит клавиши в CTk.
        roots: List[Any] = []
        try:
            tl = self.main_app.winfo_toplevel()
            if tl is not None:
                roots.append(tl)
        except Exception:
            pass
        try:
            if self.main_app not in roots:
                roots.append(self.main_app)
        except Exception:
            pass
        try:
            if self.widget.root not in roots:
                roots.append(self.widget.root)
        except Exception:
            pass

        try:
            toggle_seqs, push_seqs, pull_seqs = _portal_hotkey_tk_sequences()

            # bind_all — на корневом Tk (и дублируем на main_app, если это другой объект — CTk/обёртки)
            primaries = []
            for w in (roots[0] if roots else None, self.main_app):
                if w is not None and w not in primaries:
                    primaries.append(w)
            if not primaries:
                primaries = [self.main_app]
            for primary in primaries:
                for seq in toggle_seqs:
                    try:
                        primary.bind_all(seq, _toggle)
                    except Exception:
                        pass
                for seq in push_seqs:
                    try:
                        primary.bind_all(seq, _push)
                    except Exception:
                        pass
                for seq in pull_seqs:
                    try:
                        primary.bind_all(seq, _pull)
                    except Exception:
                        pass
            # Дополнительно на Toplevel виджета (иногда CTk перехватывает фокус)
            for win in roots[1:]:
                for seq in toggle_seqs:
                    try:
                        win.bind(seq, _toggle)
                    except Exception:
                        pass
                for seq in push_seqs:
                    try:
                        win.bind(seq, _push)
                    except Exception:
                        pass
                for seq in pull_seqs:
                    try:
                        win.bind(seq, _pull)
                    except Exception:
                        pass

            if is_mac:
                try:
                    self.main_app.bind_all(
                        "<KeyPress>",
                        self._mac_keypress_cmd_ctrl_hotkey,
                        add="+",
                    )
                except Exception:
                    pass
                self._log(
                    "Tk bind_all (macOS: по умолчанию Cmd+Ctrl+P/C/V; legacy: PORTAL_MAC_HOTKEY_LEGACY=1)"
                )
            else:
                self._log("Tk bind_all + bind на виджет (фокус на Портале)")
        except Exception as e:
            self._log(f"bind_all ошибка: {e}")

    def _schedule_hotkey_poll(self) -> None:
        """
        Глобальные хоткеи macOS пишут байты в pipe (NSEvent или hotkey-helper).
        Раньше опрашивали pipe через main_app.after(25) — на macOS при свёрнутом окне
        Tk/App Nap часто не вызывает after, и хоткеи «умирают». Решение: Tk fileevent
        (createfilehandler) на читающем конце pipe — срабатывает из главного цикла Tcl.
        """
        if platform.system() != "Darwin" or self._hk_r is None:
            try:
                self.main_app.after(25, self._poll_hotkey_queue)
            except Exception:
                pass
            return
        try:
            self.main_app.tk.createfilehandler(
                self._hk_r,
                tk.READABLE,
                self._mac_hotkey_pipe_readable,
            )
            self._mac_pipe_fileevent_installed = True
            self._log(
                "✅ macOS: глобальные хоткеи через Tk fileevent (свёрнутое окно / другой фокус)"
            )
        except Exception as e:
            self._log(f"⚠️ fileevent для хоткеев недоступен, опрос 25 мс: {e}")
            try:
                self.main_app.after(25, self._poll_hotkey_queue)
            except Exception:
                pass
        # Дублирующий опрос pipe: на части сборок Tcl fileevent по pipe не срабатывает
        if platform.system() == "Darwin" and self._hk_r is not None:
            try:
                self.main_app.after(30, self._poll_hotkey_queue)
            except Exception:
                pass

    def _mac_hotkey_pipe_readable(self, *_args) -> None:
        """Колбэк Tcl fileevent — всегда главный поток Tk."""
        self._drain_hotkey_pipe()

    def _drain_hotkey_pipe(self) -> None:
        """Считать все доступные байты из pipe глобальных хоткеев и выполнить действия."""
        if not self._running or self._hk_r is None:
            return
        try:
            while True:
                chunk = os.read(self._hk_r, 64)
                if not chunk:
                    break
                for c in chunk:
                    if c in (ord("t"), ord("c"), ord("v")):
                        self._hotkey_pipe_got_byte = True
                    if c == ord("t"):
                        self._log("🔑 Глобальный хоткей → виджет", "🔑")
                        self._toggle_ui()
                    elif c == ord("c"):
                        self._log("🔑 Глобальный хоткей → отправить буфер", "🔑")
                        self._on_push()
                    elif c == ord("v"):
                        self._log("🔑 Глобальный хоткей → забрать буфер", "🔑")
                        self._on_pull()
        except BlockingIOError:
            pass
        except OSError:
            pass

    def _poll_hotkey_queue(self) -> None:
        """Резерв: опрос pipe через after() (Windows нет pipe; macOS — если fileevent не встал)."""
        if not self._running:
            return
        self._drain_hotkey_pipe()
        try:
            self.main_app.after(25, self._poll_hotkey_queue)
        except Exception:
            pass

    def _hotkey_helper_healthcheck(self) -> None:
        """Через ~3 с: диагностика без ложных срабатываний."""
        if platform.system() != "Darwin" or sys.version_info < (3, 13):
            return
        if os.environ.get("PORTAL_MAC_NO_HOTKEY_HELPER", "").strip() in ("1", "true", "yes"):
            return
        # Всё хорошо: монитор активен или уже пришёл хоткей
        if self._hotkey_pipe_got_byte or self._helper_global_listener_ok:
            return
        proc = self._hotkey_helper_proc
        if proc is not None and proc.poll() is not None:
            rc = proc.returncode
            self._log(
                f"⚠️ hotkey-helper завершился (код {rc}) — супервизор перезапустит процесс. "
                "Если цикл повторяется: Конфиденциальность → «Мониторинг ввода» + при необходимости "
                "«Универсальный доступ» → "
                + _mac_privacy_target_hint()
                + " Полный выход из Portal (Cmd+Q) и запуск снова."
            )
            self._maybe_prompt_input_monitoring_dialog()
            return
        # Процесс жив — монитор ещё не отрапортовал (нормально при медленной инициализации NSApp)
        self._log(
            "⏳ Глобальный helper жив, но ещё не подтвердил монитор — подожди 1–2 с или нажми Cmd+Ctrl+P "
            "**вне** окна Portal. Строка «✅ Глобальные хоткеи: NSEvent/CGEventTap» значит снаружи окна уже ок. "
            "Внутри окна — Tk bind_all (local NSEvent: PORTAL_MAC_NSLOCAL_MONITOR=1, нестабильно на 3.13). Права TCC: "
            + _mac_privacy_target_hint()
        )
        self._maybe_prompt_input_monitoring_dialog()

    def _setup_nslocal_monitor(self) -> None:
        """События внутри приложения Портал (global их не видит)."""
        try:
            from AppKit import NSEvent
        except ImportError:
            return

        mgr = self

        def local_cb(event):
            cmd = mgr._nsevent_match_command(event)
            if cmd:
                try:
                    mgr.main_app.after(0, lambda c=cmd: mgr._dispatch_local_hotkey(c))
                except Exception:
                    pass
                # Иначе то же нажатие дойдёт до Tk bind_all → двойной toggle/push/pull
                return None
            return event

        try:
            self._local_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
                self._NSKeyDownMask, local_cb
            )
            if self._local_monitor:
                self._log("✅ NSEvent local monitor (фокус на Портале)")
        except Exception as e:
            self._log(f"NSEvent local: {e}")

    def _dispatch_local_hotkey(self, cmd: str) -> None:
        if cmd == "t":
            self._log("Local → виджет", "🔑")
            self._toggle_ui()
        elif cmd == "c":
            self._log("Local → отправить буфер", "🔑")
            self._on_push()
        elif cmd == "v":
            self._log("Local → забрать буфер", "🔑")
            self._on_pull()

    def _nsevent_match_command(self, event) -> Optional[str]:
        """Возвращает 't'|'c'|'v' или None. Модификаторы — по битам, не строгое равенство."""
        try:
            CMD, ALT, SHIFT, CTRL = (
                self._NSCmd,
                self._NSAlt,
                self._NSShift,
                self._NSControl,
            )
            try:
                from AppKit import NSDeviceIndependentModifierFlagsMask

                mask = int(NSDeviceIndependentModifierFlagsMask)
            except Exception:
                mask = self._NSMask
            raw_f = int(event.modifierFlags()) & mask
            # Только Cmd/Opt/Shift/Ctrl — иначе Fn/Caps ломают сравнение
            f = raw_f & (CMD | ALT | SHIFT | CTRL)
            keycode = int(event.keyCode())
            legacy = os.environ.get("PORTAL_MAC_HOTKEY_LEGACY", "").strip().lower() in (
                "1",
                "true",
                "yes",
            )
            if legacy:
                if keycode == self._KEY_P and (f & CMD) and (f & ALT) and not (f & SHIFT):
                    return "t"
                if keycode == self._KEY_C and (f & CMD) and (f & SHIFT) and not (f & ALT):
                    return "c"
                if keycode == self._KEY_V and (f & CMD) and (f & SHIFT) and not (f & ALT):
                    return "v"
                # Дубль «забрать буфер» (в части приложений Cmd+Opt+V занят — тогда Cmd+Shift+V)
                if keycode == self._KEY_V and (f & CMD) and (f & ALT) and not (f & SHIFT):
                    return "v"
            else:
                if keycode == self._KEY_P and (f & CMD) and (f & CTRL) and not (f & ALT) and not (f & SHIFT):
                    return "t"
                if keycode == self._KEY_C and (f & CMD) and (f & CTRL) and not (f & ALT) and not (f & SHIFT):
                    return "c"
                if keycode == self._KEY_V and (f & CMD) and (f & CTRL) and not (f & ALT) and not (f & SHIFT):
                    return "v"
        except Exception:
            pass
        return None

    def _maybe_prompt_input_monitoring_dialog(self) -> None:
        """Один раз за сессию — кнопка открыть «Мониторинг ввода»."""
        if self._mac_input_dialog_shown:
            return
        if portal_mac_permissions.skip_mac_permission_ui():
            return
        self._mac_input_dialog_shown = True
        try:
            self.main_app.after(
                400,
                lambda app=self.main_app: portal_mac_permissions.show_input_monitoring_dialog(app),
            )
        except Exception:
            pass

    # ── 2. NSEvent global monitor — фоновый поток (Python < 3.13) ───────────

    def _run_mac_global(self):
        """Фоновый поток с NSRunLoop. Ловит события когда ДРУГОЕ приложение в фокусе."""
        try:
            from AppKit import NSEvent
            from Foundation import NSRunLoop, NSDate
        except ImportError:
            self._log("⚠️ pyobjc/AppKit не найден — глобальные хоткеи отключены")
            return

        # Только os.write в pipe — никакого Tk / after / логов в этом потоке
        handle = self._make_nshandle_global()

        try:
            self._global_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                self._NSKeyDownMask, handle
            )
        except Exception as e:
            self._log(f"NSEvent global monitor ошибка создания: {e}")
            return

        if self._global_monitor:
            self._log("✅ NSEvent global monitor активен (другое приложение в фокусе)")
            self._log("  Accessibility → Терминал уже включён — всё должно работать")
        else:
            self._log("⚠️ Global monitor не создан — проверь Accessibility для Терминала")

        # NSRunLoop держит монитор живым
        try:
            run_loop = NSRunLoop.currentRunLoop()
            while self._running:
                run_loop.runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.2))
        except Exception as e:
            self._log(f"NSRunLoop завершён: {e}")

    def _make_nshandle_global(self):
        """Callback глобального монитора: только os.write (1 байт) в pipe."""
        mgr = self

        def handle(event):
            try:
                w = mgr._hk_w
                if w is None:
                    return
                cmd = mgr._nsevent_match_command(event)
                if cmd == "t":
                    os.write(w, b"t")
                elif cmd == "c":
                    os.write(w, b"c")
                elif cmd == "v":
                    os.write(w, b"v")
            except (OSError, BlockingIOError, TypeError, ValueError):
                pass
            except Exception:
                pass

        return handle

    # ── pynput (Windows + macOS 3.13+) ─────────────────────────────────────────

    def _run_pynput_hotkeys(self, combo: dict, label: str) -> None:
        try:
            from pynput import keyboard as pynkeyboard
        except ImportError:
            self._log("pynput не установлен — pip install pynput; хоткеи отключены")
            return
        try:
            with pynkeyboard.GlobalHotKeys(combo, suppress=False) as h:
                self._log(f"✅ pynput GlobalHotKeys: {label}")
                h.join()
        except Exception as e:
            self._log(
                f"pynput GlobalHotKeys ({label}): {type(e).__name__}: {e!r}"
            )

    def _run_mac_hotkey_helper_subprocess(self) -> None:
        """Запуск hotkey-helper: stdout → pipe → fileevent; супервизор перезапускает процесс при вылете."""
        hw = self._hk_w
        if hw is None:
            return
        hp = _resolve_mac_hotkey_helper_script()
        frozen = getattr(sys, "frozen", False)
        if hp is None and not frozen:
            self._log(
                "⚠️ Нет portal_mac_hotkey_helper.py — глобальные хоткеи macOS отключены "
                "(ожидался файл рядом с приложением или в .app/_internal)."
            )
            try:
                os.close(hw)
            except OSError:
                pass
            return

        env = os.environ.copy()
        env["PORTAL_HOTKEY_HELPER_SUBPROCESS"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        # Прямая запись в pipe (обходит буферизацию stdout и гонки out_reader → надёжнее на Mac)
        env["PORTAL_HOTKEY_PIPE_FD"] = str(int(hw))
        # Frozen: тот же бинарник + env → portal.py сразу уходит в helper (см. portal.py).
        if frozen:
            cmd: List[str] = [sys.executable]
            cwd = str(Path(sys.executable).resolve().parent)
        else:
            cmd = [sys.executable, str(hp)]
            cwd = str(hp.parent)

        mgr = self

        def supervisor() -> None:
            attempt = 0
            backoff = 2.0
            while mgr._running:
                attempt += 1
                try:
                    proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        stdin=subprocess.DEVNULL,
                        bufsize=1,
                        text=True,
                        cwd=cwd,
                        close_fds=True,
                        pass_fds=(int(hw),),
                        env=env,
                    )
                except Exception as e:
                    mgr._log(f"⚠️ Запуск hotkey-helper: {e}")
                    time.sleep(min(backoff, 30.0))
                    backoff = min(backoff * 1.35, 30.0)
                    continue

                mgr._hotkey_helper_proc = proc
                if attempt > 1:
                    mgr._log(f"♻️ hotkey-helper: перезапуск процесса #{attempt}")

                def err_reader(p: Any = proc) -> None:
                    try:
                        if p.stderr:
                            for line in p.stderr:
                                s = line.rstrip()
                                _log_to_file(f"[hotkey-helper] {s}")
                                if not s:
                                    continue
                                low = s.lower()
                                if (
                                    s.startswith("e ")
                                    or "traceback" in low
                                    or "error" in low
                                    or "exception" in low
                                ):
                                    portal_thread_log(
                                        mgr.main_app,
                                        f"hotkey-helper: {s}",
                                        "⌨️",
                                    )
                    except Exception:
                        pass

                def out_reader(p: Any = proc) -> None:
                    try:
                        if not p.stdout:
                            return
                        for line in p.stdout:
                            c = (line or "").strip()
                            cl = c.lower()
                            if len(c) == 1 and cl in "tcv":
                                try:
                                    os.write(hw, cl.encode("ascii"))
                                except (OSError, BlockingIOError, TypeError, ValueError):
                                    pass
                            elif cl.startswith("i "):
                                # Инфо от helper: cgevent_tap_ok, nsevent_monitor_ok, pynput_ok
                                _log_to_file(f"[hotkey-helper] {c}")
                                if "cgevent_tap_ok" in cl:
                                    mgr._helper_global_listener_ok = True
                                    portal_thread_log(
                                        mgr.main_app,
                                        "✅ Глобальные хоткеи: CGEventTap (Cmd+Ctrl+P/C/V из любого приложения)",
                                        "⌨️",
                                    )
                                elif "nsevent_monitor_ok" in cl:
                                    mgr._helper_global_listener_ok = True
                                    portal_thread_log(
                                        mgr.main_app,
                                        "✅ Глобальные хоткеи: NSEvent (Cmd+Ctrl+P/C/V из любого приложения)",
                                        "⌨️",
                                    )
                                elif "pynput_ok" in cl:
                                    mgr._helper_global_listener_ok = True
                                    portal_thread_log(
                                        mgr.main_app,
                                        "✅ Глобальные хоткеи: pynput (Cmd+Ctrl+P/C/V)",
                                        "⌨️",
                                    )
                    except Exception:
                        pass

                threading.Thread(
                    target=err_reader, daemon=True, name="hotkey-helper-stderr"
                ).start()
                threading.Thread(
                    target=out_reader, daemon=True, name="hotkey-helper-stdout"
                ).start()

                rc = proc.wait()
                if not mgr._running:
                    break
                mgr._log(
                    f"⚠️ hotkey-helper процесс завершился (код {rc}), следующий запуск через {backoff:.1f} с…"
                )
                time.sleep(backoff)
                backoff = min(backoff * 1.2, 25.0)

        threading.Thread(
            target=supervisor, daemon=True, name="portal-mac-hotkey-supervisor"
        ).start()

    def _run_win(self) -> None:
        # EN + русская раскладка (те же физические клавиши) + запасной toggle
        combo = {
            "<ctrl>+<alt>+p": self.toggle_widget,
            "<ctrl>+<alt>+c": self.push_clipboard,
            "<ctrl>+<alt>+v": self.pull_clipboard,
            "<ctrl>+<alt>+з": self.toggle_widget,
            "<ctrl>+<alt>+З": self.toggle_widget,
            "<ctrl>+<alt>+с": self.push_clipboard,
            "<ctrl>+<alt>+С": self.push_clipboard,
            "<ctrl>+<alt>+м": self.pull_clipboard,
            "<ctrl>+<alt>+М": self.pull_clipboard,
            # В pynput клавиша Win = Key.cmd (не существует тега <win>)
            "<cmd>+<shift>+p": self.toggle_widget,
        }
        self._run_pynput_hotkeys(
            combo,
            "Win Ctrl+Alt+P/З C/С V/М, Win+Shift+P",
        )

    # ── Общие обработчики ──────────────────────────────────────────────────────

    def _toggle_ui(self):
        """Всегда на главном потоке Tk."""
        now = time.monotonic()
        if now - self._last_toggle_debounce < 0.35:
            return
        self._last_toggle_debounce = now
        state = self.widget.anim_state
        if state in (self.widget.ANIM_OPEN, self.widget.ANIM_OPENING):
            self.widget.hide()
        else:
            self.widget.show()

    def toggle_widget(self):
        """Из чужого потока — только в очередь → PortalApp._drain_ui_signal_queue."""
        self._log("Глобальный хоткей → виджет", "🔑")
        self._enqueue_toggle()

    def _on_toggle(self):
        self.toggle_widget()

    def _on_push(self):
        now = time.monotonic()
        if now - self._last_push_debounce < 0.45:
            return
        self._last_push_debounce = now
        if self.main_app and hasattr(self.main_app, "push_shared_clipboard_hotkey"):
            try:
                self.main_app.push_shared_clipboard_hotkey()
            except Exception:
                pass

    def _on_pull(self):
        now = time.monotonic()
        if now - self._last_pull_debounce < 0.45:
            return
        self._last_pull_debounce = now
        if self.main_app and hasattr(self.main_app, "pull_shared_clipboard_hotkey"):
            try:
                self.main_app.pull_shared_clipboard_hotkey()
            except Exception:
                pass

    def push_clipboard(self):
        self._log("Глобальный хоткей → отправить буфер", "🔑")
        self._enqueue_push()

    def pull_clipboard(self):
        self._log("Глобальный хоткей → забрать буфер", "🔑")
        self._enqueue_pull()


if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()

    class FakeApp:
        def send_file(self, fp, ip):
            print(fp, ip)

        def after(self, _ms, fn=None, *args):
            if callable(fn):
                fn()

    fa = FakeApp()
    w = PortalWidget(fa)
    GlobalHotkeyManager(w, fa).start()
    root.mainloop()
