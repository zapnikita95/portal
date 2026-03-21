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
from PIL import Image, ImageTk, ImageSequence, ImageDraw, ImageFilter
import os
from typing import Optional, Any, List

import portal_config

try:
    from portal import PortalApp
except ImportError:
    PortalApp = None

# Хромакей для Windows (fallback)
CHROMA_KEY = "#010101"


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
        self._dnd_tkinterdnd2 = False
        self._windnd_ok = False

        # macOS/Linux: TkinterDnD._require на Toplevel даёт Tcl-ошибки; патчим главное CTk-окно
        # Python 3.13+: _require может вызывать segfault — пропускаем
        if platform.system() != "Windows" and main_app is not None:
            try:
                from tkinterdnd2 import TkinterDnD
                if sys.version_info >= (3, 13):
                    print("[Portal] Python 3.13+: пропускаем tkinterdnd2._require (возможен segfault)")
                    self._dnd_tkinterdnd2 = False
                else:
                    TkinterDnD._require(main_app)
                    self._dnd_tkinterdnd2 = True
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
        self._last_photo: Optional[ImageTk.PhotoImage] = None  # держим ссылку, чтобы GC не удалил

        # Fallback-рисованный портал
        self.angle = 0.0

        self.target_ip: Optional[str] = None
        if main_app and getattr(main_app, "remote_peer_ip", None):
            self.target_ip = main_app.remote_peer_ip
        if not self.target_ip:
            self.target_ip = portal_config.load_remote_ip()

        self.load_portal_gif()
        self.setup_window()

        self.canvas = tk.Canvas(
            self.root,
            width=self.size,
            height=self.size,
            bg=CHROMA_KEY,
            highlightthickness=0,
        )
        self.canvas.pack()

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
        """Прозрачный фон по платформе"""
        if platform.system() == "Darwin":
            # wm_attributes("-transparent", True) на части macOS (в т.ч. новых) даёт SIGTRAP в Tk/AppKit.
            # По умолчанию — только systemTransparent + круглая альфа в GIF; окно без «дырявого» флага.
            try:
                self.root.configure(bg="systemTransparent")
                self.canvas.configure(bg="systemTransparent")
            except tk.TclError:
                pass
            if os.environ.get("PORTAL_MAC_TRANSPARENT", "").strip() in ("1", "true", "yes"):
                try:
                    self.root.wm_attributes("-transparent", True)
                except tk.TclError:
                    pass
            return

        self.root.configure(bg=CHROMA_KEY)
        self.canvas.configure(bg=CHROMA_KEY)
        if platform.system() == "Windows":
            try:
                self.root.attributes("-transparentcolor", CHROMA_KEY)
            except tk.TclError:
                pass

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

            for frame in ImageSequence.Iterator(gif):
                img = frame.convert("RGBA")

                # Кроп до центрального квадрата
                w, h = img.size
                sq = min(w, h)
                left = (w - sq) // 2
                top  = (h - sq) // 2
                img = img.crop((left, top, left + sq, top + sq))

                # Ресайз до размера виджета
                img = img.resize((self.size, self.size), Image.Resampling.LANCZOS)

                # Антиалиасный круглый вырез — за пределами круга прозрачно
                mask = Image.new("L", (self.size, self.size), 0)
                draw = ImageDraw.Draw(mask)
                margin = 4
                draw.ellipse(
                    [margin, margin, self.size - margin - 1, self.size - margin - 1],
                    fill=255,
                )
                mask = mask.filter(ImageFilter.GaussianBlur(3))
                img.putalpha(mask)

                raw_frames.append(img)

            self.gif_frames_raw = raw_frames
            self.gif_frames = [ImageTk.PhotoImage(f) for f in raw_frames]
            print(f"[Portal] Загружено {len(self.gif_frames)} кадров из {gif_path}")

        except Exception as e:
            print(f"[Portal] Ошибка загрузки GIF: {e}")

    # ───────────────────────────── АНИМАЦИЯ ─────────────────────────

    def _cancel_anim(self):
        if self._anim_after_id is not None:
            try:
                self.root.after_cancel(self._anim_after_id)
            except Exception:
                pass
            self._anim_after_id = None

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
        """Один шаг анимации — вызывается через after()."""
        if self.anim_state == self.ANIM_HIDDEN:
            return

        total = len(self.gif_frames) if self.gif_frames else 20

        self._show_frame(self.anim_frame_idx)

        if self.anim_state == self.ANIM_OPENING:
            if self.anim_frame_idx < total - 1:
                self.anim_frame_idx += 1
                self._anim_after_id = self.root.after(self._anim_speed_ms, self._animate_step)
            else:
                # Анимация открытия завершена — стоим на последнем кадре
                self.anim_state = self.ANIM_OPEN

        elif self.anim_state == self.ANIM_CLOSING:
            if self.anim_frame_idx > 0:
                self.anim_frame_idx -= 1
                self._anim_after_id = self.root.after(self._anim_speed_ms, self._animate_step)
            else:
                # Анимация закрытия завершена — скрыть окно
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

        self.canvas.bind("<Double-Button-1>", lambda e: self.show_settings())
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
    macOS: AppKit NSEvent (global = когда другое приложение в фокусе,
                           local  = когда Portal в фокусе) + Tk bind_all.
    Windows: pynput GlobalHotKeys.
    Логи пишутся в консоль, GUI и файл /tmp/portal_hotkey_debug.log.
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

    def _log(self, msg: str, prefix: str = "⌨️") -> None:
        portal_thread_log(self.main_app, msg, prefix)

    def start(self):
        self._log(f"Запуск хоткеев на {platform.system()}")
        _log_to_file(f"[Portal] debug-файл: {_hotkey_log_path()}")

        # 1. Tk bind_all — работает сразу, без Accessibility, когда Portal в фокусе
        self._bind_tk_all()

        if platform.system() == "Darwin":
            # 2. NSEvent local monitor — scheduleим на главном потоке Tk
            try:
                self.main_app.after(300, self._setup_nslocal_monitor)
            except Exception as e:
                self._log(f"after(local monitor): {e}")
            # 3. NSEvent global monitor — фоновый поток с NSRunLoop
            t = threading.Thread(target=self._run_mac_global, daemon=True, name="portal-hotkeys-global")
            t.start()
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
            self._log("🔑 Tk bind: Cmd+Option+P → переключить виджет", "🔑")
            self._toggle_ui()
            return "break"

        def _push(e=None):
            self._log("🔑 Tk bind: Cmd+Shift+C → отправить буфер", "🔑")
            self._on_push()
            return "break"

        def _pull(e=None):
            self._log("🔑 Tk bind: Cmd+Shift+V → получить буфер", "🔑")
            self._on_pull()
            return "break"

        is_mac = platform.system() == "Darwin"
        root = self.main_app  # главное окно ловит bind_all

        try:
            if is_mac:
                toggle_seqs = [
                    "<Command-Option-p>", "<Command-Alt-p>",
                    "<Meta-Option-p>",    "<Meta-Alt-p>",
                ]
                push_seqs = ["<Command-Shift-C>", "<Command-Shift-c>", "<Meta-Shift-C>"]
                pull_seqs = ["<Command-Shift-V>", "<Command-Shift-v>", "<Meta-Shift-V>"]
            else:
                toggle_seqs = ["<Control-Alt-p>"]
                push_seqs   = ["<Control-Alt-c>"]
                pull_seqs   = ["<Control-Alt-v>"]

            for seq in toggle_seqs:
                try:
                    root.bind_all(seq, _toggle)
                except Exception:
                    pass
            for seq in push_seqs:
                try:
                    root.bind_all(seq, _push)
                except Exception:
                    pass
            for seq in pull_seqs:
                try:
                    root.bind_all(seq, _pull)
                except Exception:
                    pass

            self._log("Tk bind_all зарегистрирован (работает когда Portal в фокусе)")
        except Exception as e:
            self._log(f"bind_all ошибка: {e}")

    # ── 2. NSEvent local monitor (главный поток) ───────────────────────────────

    def _setup_nslocal_monitor(self):
        """Вызывается НА ГЛАВНОМ ПОТОКЕ через after(). Ловит события внутри нашего приложения."""
        try:
            from AppKit import NSEvent
        except ImportError:
            return

        handle = self._make_nshandle(source="local")
        self._handle_ref = handle  # держим от GC

        try:
            # Local monitor возвращает обработанное (или None чтобы сглотнуть) событие
            def local_cb(event):
                handle(event)
                return event  # не блокируем событие

            self._local_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
                self._NSKeyDownMask, local_cb
            )
            if self._local_monitor:
                self._log("✅ NSEvent local monitor активен (Portal в фокусе)")
            else:
                self._log("⚠️ NSEvent local monitor не создан")
        except Exception as e:
            self._log(f"NSEvent local monitor ошибка: {e}")

    # ── 3. NSEvent global monitor (фоновый поток) ─────────────────────────────

    def _run_mac_global(self):
        """Фоновый поток с NSRunLoop. Ловит события когда ДРУГОЕ приложение в фокусе."""
        try:
            from AppKit import NSEvent
            from Foundation import NSRunLoop, NSDate
        except ImportError:
            self._log("⚠️ pyobjc/AppKit не найден — глобальные хоткеи отключены")
            return

        handle = self._make_nshandle(source="global")

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

    def _make_nshandle(self, source: str):
        """Создаёт callback для NSEvent монитора."""
        CMD, ALT, SHIFT, MASK = self._NSCmd, self._NSAlt, self._NSShift, self._NSMask
        KEY_P, KEY_C, KEY_V   = self._KEY_P, self._KEY_C, self._KEY_V

        mgr = self

        def handle(event):
            try:
                flags   = int(event.modifierFlags()) & MASK
                keycode = int(event.keyCode())

                if flags == (CMD | ALT) and keycode == KEY_P:
                    mgr._log(f"🔑 NSEvent[{source}] Cmd+Option+P → виджет", "🔑")
                    mgr.widget.root.after(0, mgr._toggle_ui)

                elif flags == (CMD | SHIFT) and keycode == KEY_C:
                    mgr._log(f"🔑 NSEvent[{source}] Cmd+Shift+C → буфер отправить", "🔑")
                    mgr._on_push()

                elif flags == (CMD | SHIFT) and keycode == KEY_V:
                    mgr._log(f"🔑 NSEvent[{source}] Cmd+Shift+V → буфер получить", "🔑")
                    mgr._on_pull()

            except Exception as e:
                print(f"[Portal] NSEvent handle ошибка: {e}", flush=True)

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
