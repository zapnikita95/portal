"""
Виджет-портал для рабочего стола: прозрачный фон, drag&drop, горячие клавиши.
Анимация только при открытии/закрытии — без бесконечного цикла.
"""

import tkinter as tk
import math
import threading
import time
import sys
import platform
from pathlib import Path
from PIL import Image, ImageTk, ImageSequence
import os
import tempfile
from typing import Optional, Any, List

import portal_config

try:
    from portal import PortalApp
except ImportError:
    PortalApp = None

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
    """Лог из любого потока: консоль + файл + журнал GUI (thread-safe через after)."""
    ts = time.strftime("%H:%M:%S")
    full = f"[{ts}] {prefix} {message}"
    print(f"[Portal] {full}", flush=True)
    _log_to_file(f"[Portal] {full}")
    try:
        if main_app is not None and hasattr(main_app, "after") and hasattr(main_app, "log"):
            def _do():
                try:
                    main_app.log(f"{prefix} {message}")
                except Exception:
                    pass
            main_app.after(0, _do)
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
                from tkinterdnd2 import TkinterDnD
                if os.environ.get("PORTAL_NO_MAC_DND", "").strip() in ("1", "true", "yes"):
                    print("[Portal] tkinterdnd2 отключён (PORTAL_NO_MAC_DND)")
                    self._dnd_tkinterdnd2 = False
                else:
                    TkinterDnD._require(main_app)
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

        self.root.title("🌀 Портал")

        self.size = 220

        # Состояние анимации
        self.anim_state = self.ANIM_HIDDEN
        self.anim_frame_idx = 0
        self._anim_after_id = None
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

        self.setup_window()

        self.canvas = tk.Canvas(
            self.root,
            width=self.size,
            height=self.size,
            bg=self._chroma_hex,
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

    # ───────────────────────────── ОКНО ─────────────────────────────

    def setup_window(self):
        """Позиция, поверх остальных окон, без рамки"""
        try:
            self.root.configure(highlightthickness=0, bd=0, bg=self._chroma_hex)
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
        try:
            self.root.overrideredirect(True)
        except tk.TclError:
            pass

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = sw - self.size - 24
        y = sh - self.size - 96
        self.root.geometry(f"{self.size}x{self.size}+{x}+{y}")

        self.drag_start_x = 0
        self.drag_start_y = 0

    def setup_transparency(self):
        """
        Windows: хромакей + -transparentcolor.
        macOS: магента (или PORTAL_WIDGET_CHROMA) + transparentcolor + -transparent.
        Отключить «дырявое» окно виджета: PORTAL_WIDGET_NO_MAC_TRANSPARENT=1
        Старый флаг PORTAL_MAC_TRANSPARENT=1 всё ещё включает -transparent (дубль не страшен).
        """
        self.root.configure(bg=self._chroma_hex)
        self.canvas.configure(bg=self._chroma_hex)
        if platform.system() == "Windows":
            try:
                self.root.attributes("-transparentcolor", self._chroma_hex)
            except tk.TclError:
                pass
            return

        if platform.system() == "Darwin":
            try:
                self.root.attributes("-transparentcolor", self._chroma_hex)
            except tk.TclError:
                try:
                    self.root.wm_attributes("-transparentcolor", self._chroma_hex)
                except tk.TclError:
                    pass
            no_transparent = os.environ.get(
                "PORTAL_WIDGET_NO_MAC_TRANSPARENT", ""
            ).strip() in ("1", "true", "yes")
            want_transparent = (
                os.environ.get("PORTAL_MAC_TRANSPARENT", "").strip()
                in ("1", "true", "yes")
            ) or not no_transparent
            if want_transparent:
                try:
                    self.root.wm_attributes("-transparent", True)
                except tk.TclError:
                    pass
            return

        # Linux: сплошной фон хромакея (уже задан выше)

    # ───────────────────────────── ЗАГРУЗКА GIF ─────────────────────

    def load_portal_gif(self):
        """Загрузить кадры GIF, вырезать круг, сделать фон прозрачным."""
        assets_dir = os.path.join(os.path.dirname(__file__), "assets")
        search_paths = [
            os.path.join(assets_dir, "portal_main.gif"),
            os.path.join(assets_dir, "portal_animated_opening.gif"),
            os.path.join(assets_dir, "portal_opening.gif"),
            os.path.join(assets_dir, "portal_animated.gif"),
            os.path.join(assets_dir, "portal_static.gif"),
        ]

        gif_path = None
        for p in search_paths:
            if os.path.exists(p):
                gif_path = p
                break

        if not gif_path:
            print("[Portal] GIF не найден — используется рисованный портал")
            return

        try:
            gif = Image.open(gif_path)
            raw_frames: List[Image.Image] = []
            durations: List[int] = []

            for frame in ImageSequence.Iterator(gif):
                img = frame.convert("RGBA")
                ms = int(frame.info.get("duration", 80) or 80)
                if ms <= 0:
                    ms = 80
                durations.append(ms)

                w, h = img.size
                sq = min(w, h)
                left = (w - sq) // 2
                top = (h - sq) // 2
                img = img.crop((left, top, left + sq, top + sq))
                img = img.resize((self.size, self.size), Image.Resampling.LANCZOS)

                # Без круговой маски+blur (зернистость); хромакей как фон для -transparentcolor
                r, g, b = self._chroma_rgb
                bg = Image.new("RGBA", (self.size, self.size), (r, g, b, 255))
                composed = Image.alpha_composite(bg, img)
                raw_frames.append(composed)

            self.gif_frames_raw = raw_frames
            self._gif_frame_durations = durations
            master = self.root
            self.gif_frames = [
                ImageTk.PhotoImage(f.convert("RGB"), master=master) for f in raw_frames
            ]
            print(f"[Portal] Загружено {len(self.gif_frames)} кадров из {gif_path}")

        except Exception as e:
            print(f"[Portal] Ошибка загрузки GIF: {e}")

    # ───────────────────────────── АНИМАЦИЯ ─────────────────────────

    def _cancel_anim(self):
        if self._anim_after_id is not None:
            for target in (getattr(self, "main_app", None), self.root):
                if target is not None and hasattr(target, "after_cancel"):
                    try:
                        target.after_cancel(self._anim_after_id)
                        break
                    except Exception:
                        continue
            self._anim_after_id = None

    def _schedule_anim_ms(self, delay_ms: int, callback) -> None:
        """Таймер анимации через главное окно — у скрытого Toplevel root.after часто не срабатывает."""
        delay_ms = max(1, int(delay_ms))
        try:
            if self.main_app is not None and hasattr(self.main_app, "after"):
                self._anim_after_id = self.main_app.after(delay_ms, callback)
                return
        except Exception:
            pass
        self._anim_after_id = self.root.after(delay_ms, callback)

    def _gif_delay_for_idx(self, idx: int) -> int:
        if self._gif_frame_durations and 0 <= idx < len(self._gif_frame_durations):
            return max(16, self._gif_frame_durations[idx])
        return max(16, self._anim_speed_ms)

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
            # Fallback: рисованный портал со scale-эффектом
            total = 20
            scale = min(1.0, idx / max(1, total))
            r = (self.size // 2 - 18) * scale
            if r > 1:
                self._draw_portal(cx, cy, r)

    def _animate_step(self):
        """Один шаг анимации — планируется через main_app.after (надёжно при withdraw Toplevel)."""
        if self.anim_state == self.ANIM_HIDDEN:
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
        """Показать виджет с анимацией разворачивания."""
        self._cancel_anim()
        self.root.deiconify()
        self.root.lift()
        self.root.update_idletasks()  # Убедиться что окно видимо перед анимацией
        self.anim_state = self.ANIM_OPENING
        self.anim_frame_idx = 0
        self._animate_step()

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

        self.canvas.bind("<Double-Button-1>", self.on_double_click_portal)
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
                    self.root.after(0, lambda p=list(paths): self.send_files(p))

            windnd.hook_dropfiles(self.root, on_drop)
            self._windnd_ok = True
        except Exception as e:
            print(f"[Portal] windnd не сработал ({e}), пробуем tkinterdnd2…")
            try:
                from tkinterdnd2 import TkinterDnD, DND_FILES
                TkinterDnD._require(self.root)
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
                self.root.after(0, lambda f=list(files): self.send_files(f))
        except Exception as ex:
            print(f"[Portal] Ошибка Drop: {ex}")

    # ───────────────────────────── КОНТЕКСТНОЕ МЕНЮ ─────────────────

    def show_context_menu(self, event):
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="IP удалённого ПК", command=self.show_ip_dialog)
        menu.add_command(label="Выбрать файл (Ctrl+клик)", command=self.on_portal_click)
        menu.add_command(label="Картинка из буфера (двойной клик)", command=self.on_double_click_portal)
        menu.add_command(label="Скрыть", command=self.hide)
        menu.add_separator()
        menu.add_command(label="Выход", command=self.destroy)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ───────────────────────────── IP / НАСТРОЙКИ ───────────────────

    def show_settings(self, event=None):
        self.show_ip_dialog()

    def show_ip_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("IP получателя")
        dialog.geometry("320x160")
        dialog.attributes("-topmost", True)

        tk.Label(dialog, text="IP второго компьютера:").pack(pady=10)
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

        tk.Button(dialog, text="Сохранить", command=save_ip).pack(pady=10)

    def show_ip_dialog_sync(self, callback):
        dialog = tk.Toplevel(self.root)
        dialog.title("IP получателя")
        dialog.geometry("320x160")
        dialog.attributes("-topmost", True)
        dialog.grab_set()

        tk.Label(dialog, text="IP второго компьютера (Tailscale / LAN):").pack(pady=10)
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
        files = filedialog.askopenfilenames(title="Выберите файлы для отправки")
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
                    self.main_app.after(0, lambda m=str(e): self.main_app.log(f"⚠️ Буфер: {m}"))
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
                        self.main_app.after(0, lambda m=str(e): self.main_app.log(f"⚠️ Картинка: {m}"))
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
        ip = self._resolve_peer_ip()
        if not ip:
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
        if self.main_app and hasattr(self.main_app, "log"):
            try:
                self.main_app.after(0, lambda: self.main_app.log("📤 Картинка из буфера → отправка"))
            except Exception:
                pass
        threading.Thread(target=self._send_file_then_unlink, args=(path, ip), daemon=True).start()

    def _send_file_then_unlink(self, path: str, ip: str) -> None:
        try:
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

    def send_files(self, files: List[str]):
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
        else:
            self.target_ip = ip

        for fp in files:
            if self.main_app and hasattr(self.main_app, "send_file"):
                if hasattr(self.main_app, "log"):
                    self.main_app.log(f"📤 Виджет: {Path(fp).name}")
                threading.Thread(
                    target=self.main_app.send_file,
                    args=(fp, ip),
                    daemon=True,
                ).start()


# ─────────────────────────── ГОРЯЧИЕ КЛАВИШИ ────────────────────────────────

class GlobalHotkeyManager:
    """
    macOS: NSEvent global monitor → очередь → poll на главном потоке (без GIL crash);
           плюс Tk bind_all когда окно Портала в фокусе (Apple не шлёт global в своё приложение).
    Windows: pynput GlobalHotKeys.
    """

    # macOS virtual keycodes (US layout, layout-independent)
    _KEY_P = 35
    _KEY_C = 8
    _KEY_V = 9

    _NSCmd   = 1 << 20   # NSCommandKeyMask
    _NSAlt   = 1 << 19   # NSAlternateKeyMask (Option)
    _NSShift = 1 << 17   # NSShiftKeyMask
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

    def _log(self, msg: str, prefix: str = "⌨️") -> None:
        portal_thread_log(self.main_app, msg, prefix)

    def start(self):
        self._log(f"Запуск хоткеев на {platform.system()}")
        _log_to_file(f"[Portal] debug-файл: {_hotkey_log_path()}")

        # 1. Tk bind_all — работает сразу, без Accessibility, когда Portal в фокусе
        self._bind_tk_all()

        if platform.system() == "Darwin":
            try:
                import fcntl

                self._hk_r, self._hk_w = os.pipe()
                fcntl.fcntl(self._hk_r, fcntl.F_SETFL, os.O_NONBLOCK)
            except Exception as e:
                self._log(f"⚠️ pipe хоткеев не создан: {e}")
                self._hk_r = self._hk_w = None
            self._schedule_hotkey_poll()
            t = threading.Thread(
                target=self._run_mac_global, daemon=True, name="portal-hotkeys-global"
            )
            t.start()
            # Local monitor: когда в фокусе сам Портал (global такие события не получает)
            try:
                self.main_app.after(350, self._setup_nslocal_monitor)
            except Exception as e:
                self._log(f"after(local monitor): {e}")
            self._log(
                "✅ Хоткеи: Cmd+Option+P / Cmd+Shift+C/V — из других приложений (Accessibility→Терминал или Python) "
                "и из окна Портала"
            )
        else:
            t = threading.Thread(target=self._run_win, daemon=True, name="portal-hotkeys-win")
            t.start()

    # ── 1. Tk bind_all ─────────────────────────────────────────────────────────

    def _bind_tk_all(self):
        """
        bind_all на корневом окне ловит клавиши со всего приложения.
        На macOS Option-клавиша в Tk = Alt, Command = Command или Meta.
        Биндим несколько вариантов написания.
        """
        def _toggle(e=None):
            if platform.system() == "Darwin":
                self._log("🔑 Tk bind: Cmd+Option+P → переключить виджет", "🔑")
            else:
                self._log("🔑 Tk bind: Ctrl+Alt+P → переключить виджет", "🔑")
            self._toggle_ui()
            return "break"

        def _push(e=None):
            if platform.system() == "Darwin":
                self._log("🔑 Tk bind: Cmd+Shift+C → отправить буфер", "🔑")
            else:
                self._log("🔑 Tk bind: Ctrl+Alt+C → отправить буфер", "🔑")
            self._on_push()
            return "break"

        def _pull(e=None):
            if platform.system() == "Darwin":
                self._log("🔑 Tk bind: Cmd+Shift+V → получить буфер", "🔑")
            else:
                self._log("🔑 Tk bind: Ctrl+Alt+V → получить буфер", "🔑")
            self._on_pull()
            return "break"

        is_mac = platform.system() == "Darwin"
        # CTk + Toplevel виджета — биндим на все корни, иначе часть событий теряется
        roots: List[Any] = []
        try:
            roots.append(self.main_app)
        except Exception:
            pass
        try:
            tl = self.main_app.winfo_toplevel()
            if tl not in roots:
                roots.append(tl)
        except Exception:
            pass
        try:
            if self.widget.root not in roots:
                roots.append(self.widget.root)
        except Exception:
            pass

        try:
            if is_mac:
                toggle_seqs = [
                    "<Command-Option-p>", "<Command-Alt-p>",
                    "<Meta-Option-p>", "<Meta-Alt-p>",
                    "<Command-Option-P>", "<Meta-Option-P>",
                ]
                push_seqs = [
                    "<Command-Shift-C>", "<Command-Shift-c>",
                    "<Meta-Shift-C>", "<Meta-Shift-c>",
                ]
                pull_seqs = [
                    "<Command-Shift-V>", "<Command-Shift-v>",
                    "<Meta-Shift-V>", "<Meta-Shift-v>",
                ]
            else:
                toggle_seqs = ["<Control-Alt-p>"]
                push_seqs   = ["<Control-Alt-c>"]
                pull_seqs   = ["<Control-Alt-v>"]

            # bind_all — один раз на весь процесс (иначе дубли)
            primary = roots[0] if roots else self.main_app
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

            self._log("Tk bind_all + bind на виджет (фокус на Портале)")
        except Exception as e:
            self._log(f"bind_all ошибка: {e}")

    def _schedule_hotkey_poll(self) -> None:
        try:
            self.main_app.after(25, self._poll_hotkey_queue)
        except Exception:
            pass

    def _poll_hotkey_queue(self) -> None:
        """Главный поток Tk: читаем pipe от глобального NSEvent (только os.write в колбэке)."""
        if not self._running:
            return
        if self._hk_r is not None:
            try:
                while True:
                    chunk = os.read(self._hk_r, 64)
                    if not chunk:
                        break
                    for c in chunk:
                        if c == ord("t"):
                            self._log("🔑 Глобальный хоткей: Cmd+Option+P → виджет", "🔑")
                            self._toggle_ui()
                        elif c == ord("c"):
                            self._log("🔑 Глобальный хоткей: Cmd+Shift+C → буфер", "🔑")
                            self._on_push()
                        elif c == ord("v"):
                            self._log("🔑 Глобальный хоткей: Cmd+Shift+V → буфер", "🔑")
                            self._on_pull()
            except BlockingIOError:
                pass
            except OSError:
                pass
        self._schedule_hotkey_poll()

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
            self._log("🔑 Local: Cmd+Option+P", "🔑")
            self._toggle_ui()
        elif cmd == "c":
            self._log("🔑 Local: Cmd+Shift+C", "🔑")
            self._on_push()
        elif cmd == "v":
            self._log("🔑 Local: Cmd+Shift+V", "🔑")
            self._on_pull()

    def _nsevent_match_command(self, event) -> Optional[str]:
        """Возвращает 't'|'c'|'v' или None. Модификаторы — по битам, не строгое равенство."""
        try:
            CMD, ALT, SHIFT = self._NSCmd, self._NSAlt, self._NSShift
            try:
                from AppKit import NSDeviceIndependentModifierFlagsMask

                mask = int(NSDeviceIndependentModifierFlagsMask)
            except Exception:
                mask = self._NSMask
            f = int(event.modifierFlags()) & mask
            keycode = int(event.keyCode())
            # Cmd+Option+P (без требования «ровно два» бита — CapsLock и др. не ломают)
            if keycode == self._KEY_P and (f & CMD) and (f & ALT) and not (f & SHIFT):
                return "t"
            if keycode == self._KEY_C and (f & CMD) and (f & SHIFT) and not (f & ALT):
                return "c"
            if keycode == self._KEY_V and (f & CMD) and (f & SHIFT) and not (f & ALT):
                return "v"
        except Exception:
            pass
        return None

    # ── 2. NSEvent global monitor (фоновый поток) ─────────────────────────────

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

    # ── Windows ────────────────────────────────────────────────────────────────

    def _run_win(self):
        try:
            from pynput import keyboard
        except ImportError:
            self._log("pynput не установлен — хоткеи отключены")
            return

        combo = {
            "<ctrl>+<alt>+p": self.toggle_widget,
            "<ctrl>+<alt>+c": self.push_clipboard,
            "<ctrl>+<alt>+v": self.pull_clipboard,
        }
        try:
            with keyboard.GlobalHotKeys(combo) as h:
                self._log("✅ pynput GlobalHotKeys активен: Ctrl+Alt+P | C | V")
                h.join()
        except Exception as e:
            self._log(f"pynput GlobalHotKeys: {e}")

    # ── Общие обработчики ──────────────────────────────────────────────────────

    def _toggle_ui(self):
        """Всегда на главном потоке Tk."""
        now = time.monotonic()
        if now - self._last_toggle_debounce < 0.2:
            return
        self._last_toggle_debounce = now
        state = self.widget.anim_state
        if state in (self.widget.ANIM_OPEN, self.widget.ANIM_OPENING):
            self.widget.hide()
        else:
            self.widget.show()

    def toggle_widget(self):
        try:
            self.main_app.after(0, self._toggle_ui)
        except Exception:
            pass

    def _on_toggle(self):
        self.toggle_widget()

    def _on_push(self):
        if self.main_app and hasattr(self.main_app, "push_shared_clipboard_hotkey"):
            try:
                self.main_app.after(0, self.main_app.push_shared_clipboard_hotkey)
            except Exception:
                pass

    def _on_pull(self):
        if self.main_app and hasattr(self.main_app, "pull_shared_clipboard_hotkey"):
            try:
                self.main_app.after(0, self.main_app.pull_shared_clipboard_hotkey)
            except Exception:
                pass

    def push_clipboard(self):
        self._on_push()

    def pull_clipboard(self):
        self._on_pull()


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
