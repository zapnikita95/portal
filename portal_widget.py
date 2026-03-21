"""
Виджет-портал для рабочего стола: прозрачный фон, drag&drop, горячие клавиши.
"""

import tkinter as tk
import math
import threading
import time
import sys
import platform

# Проверка версии Python для совместимости
if sys.version_info >= (3, 13):
    print("[Portal] Python 3.13+ - некоторые функции могут быть ограничены")
from pathlib import Path
from PIL import Image, ImageTk, ImageSequence
import os
from typing import Optional, Any, List

import portal_config

try:
    from portal import PortalApp
except ImportError:
    PortalApp = None

# Цвет «хромакей» для прозрачного фона (Windows: -transparentcolor)
CHROMA_KEY = "#010101"


def _debug_log_file(line: str) -> None:
    """Всегда пишем в файл — даже если консоль не видна (двойной клик по .bat)."""
    try:
        if platform.system() == "win32":
            base = os.environ.get("TEMP") or os.environ.get("TMP") or str(Path.home())
        else:
            base = os.environ.get("TMPDIR") or "/tmp"
        Path(base).mkdir(parents=True, exist_ok=True)
        p = Path(base) / "portal_hotkey_debug.log"
        with p.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def portal_thread_log(main_app: Any, message: str, prefix: str = "⌨️") -> None:
    """Лог из фонового потока: консоль + файл + журнал GUI (через after)."""
    ts = time.strftime("%H:%M:%S")
    full = f"[{ts}] {prefix} {message}"
    print(f"[Portal] {full}", flush=True)
    _debug_log_file(f"[Portal] {full}")
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

    def __init__(self, main_app: Any):
        self.main_app = main_app
        self._dnd_tkinterdnd2 = False
        self._windnd_ok = False

        # macOS/Linux: TkinterDnD._require на Toplevel даёт Tcl-ошибки; патчим главное CTk-окно
        # ВАЖНО: на Python 3.13+ может быть segfault - пробуем безопасно
        if platform.system() != "Windows" and main_app is not None:
            try:
                from tkinterdnd2 import TkinterDnD
                # На Python 3.13+ _require может падать - пробуем с защитой
                if sys.version_info >= (3, 13):
                    # Пропускаем _require на 3.13+ - может вызвать segfault
                    print("[Portal] Python 3.13+: пропускаем tkinterdnd2._require (может вызвать segfault)")
                    self._dnd_tkinterdnd2 = False
                else:
                    TkinterDnD._require(main_app)
                    self._dnd_tkinterdnd2 = True
            except Exception as e:
                self._dnd_tkinterdnd2 = False
                print(f"[Portal] tkinterdnd2 (главное окно): {e}")

        # ВАЖНО: Toplevel с master=главное окно (CustomTkinter = Tk)
        if main_app is not None and hasattr(main_app, "winfo_toplevel"):
            self.root = tk.Toplevel(master=main_app)
        else:
            self.root = tk.Tk()

        self.root.title("🌀 Портал")

        self.size = 220
        self.angle = 0.0
        self.animation_running = True
        self.is_opening = False
        self.is_closing = False
        self.opening_scale = 0.0
        self._after_id: Optional[Any] = None  # id для after_cancel
        self._after_master: Optional[Any] = None  # тот же Tk/CTk, что вызвал after (нужен для cancel)

        self.gif_frames: List[ImageTk.PhotoImage] = []
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

        # Анимация «раскрытия» только по хоткею (show), не в фоне каждые N мс

    def _widget_log(self, message: str) -> None:
        portal_thread_log(self.main_app, message, "🌀")

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
        """Убрать «чёрную подложку»: прозрачный фон по платформе"""
        if platform.system() == "Darwin":
            try:
                self.root.configure(bg="systemTransparent")
                self.canvas.configure(bg="systemTransparent")
                # На части сборок Tcl True ломается — используем 1
                self.root.attributes("-transparent", 1)
            except tk.TclError:
                try:
                    self.root.configure(bg=CHROMA_KEY)
                    self.canvas.configure(bg=CHROMA_KEY)
                    self.root.attributes("-alpha", 0.92)
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

    def setup_mouse_bindings(self):
        """Перетаскивание окна: Alt+ЛКМ. Файлы: Ctrl+ЛКМ. Настройки: двойной клик."""

        def bind_drag(w):
            w.bind("<Alt-Button-1>", self.start_drag)
            w.bind("<Alt-B1-Motion>", self.on_drag)

        bind_drag(self.root)
        bind_drag(self.canvas)

        self.canvas.bind("<Double-Button-1>", lambda e: self.show_settings())
        self.canvas.bind("<Control-Button-1>", lambda e: self.on_portal_click())
        self.root.bind("<Button-3>", self.show_context_menu)
        self.canvas.bind("<Button-3>", self.show_context_menu)

    def _setup_windnd_drop(self):
        """Windows: перетаскивание файлов из Проводника (в т.ч. .mp4)."""
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
                    # Логируем в главное окно если доступно
                    if self.main_app and hasattr(self.main_app, "log"):
                        self.main_app.log(f"📥 Получено файлов через drag & drop: {len(paths)}")
                    self.root.after(0, lambda p=list(paths): self.send_files(p))

            # Ждём пока окно полностью создано
            self.root.update_idletasks()
            windnd.hook_dropfiles(self.root, on_drop)
            self._windnd_ok = True
            if self.main_app and hasattr(self.main_app, "log"):
                self.main_app.log("✅ Drag & Drop включён (windnd)")
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
                # Часто приходит: {C:\path\file.txt} или {C:\a} {C:\b}
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

    def on_portal_click(self):
        from tkinter import filedialog

        files = filedialog.askopenfilenames(title="Выберите файлы для отправки")
        if files:
            self.send_files(list(files))

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

    def show_settings(self, event=None):
        self.show_ip_dialog()

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

    def start_drag(self, event):
        self.drag_start_x = event.x
        self.drag_start_y = event.y

    def on_drag(self, event):
        x = self.root.winfo_x() + event.x - self.drag_start_x
        y = self.root.winfo_y() + event.y - self.drag_start_y
        self.root.geometry(f"+{x}+{y}")

    def load_portal_gif(self):
        assets_dir = os.path.join(os.path.dirname(__file__), "assets")
        # Сначала твой GIF с MP4 (import_portal_from_mp4.py → portal_animated.gif)
        for name in (
            "portal_animated.gif",
            "portal_static.gif",
            "portal_animated_opening.gif",
            "portal_opening.gif",
        ):
            gif_path = os.path.join(assets_dir, name)
            if not os.path.exists(gif_path):
                continue
            try:
                gif = Image.open(gif_path)
                self.gif_frames = []
                for frame in ImageSequence.Iterator(gif):
                    rgba = frame.convert("RGBA")
                    rgba = rgba.resize((self.size, self.size), Image.Resampling.LANCZOS)
                    # Подложка под хромакей: почти чёрный → CHROMA_KEY
                    bg = Image.new("RGBA", rgba.size, CHROMA_KEY)
                    bg.paste(rgba, (0, 0), rgba)
                    self.gif_frames.append(ImageTk.PhotoImage(bg.convert("RGBA")))
                if self.gif_frames:
                    return
            except Exception as e:
                print(f"[Portal] GIF {gif_path}: {e}")

    def _schedule_after(self, ms: int, callback) -> None:
        """Тикает анимацию через главное окно CTk — у Toplevel.after иногда не срабатывает."""
        master = self.root
        if self.main_app is not None and hasattr(self.main_app, "after"):
            master = self.main_app
        self._after_master = master
        try:
            self._after_id = master.after(ms, callback)
        except Exception as e:
            self._widget_log(f"ОШИБКА after({ms}): {e} — анимация может не идти")

    def _cancel_scheduled_animation(self) -> None:
        if self._after_id is not None:
            master = self._after_master if self._after_master is not None else self.root
            try:
                master.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
            self._after_master = None

    def start_opening_animation(self) -> None:
        """Раскрытие при показе виджета (хоткей)."""
        self._widget_log(
            f"Анимация ОТКРЫТИЯ старт (масштаб={self.opening_scale:.2f})"
        )
        self._cancel_scheduled_animation()
        self.is_opening = True
        self.is_closing = False
        # Если закрывали на полпути — продолжаем открытие с текущего масштаба
        self.opening_scale = min(1.0, max(0.0, self.opening_scale))
        self._animate_step()

    def start_closing_animation(self) -> None:
        """Схлопывание перед скрытием."""
        self._widget_log(
            f"Анимация ЗАКРЫТИЯ старт (масштаб={self.opening_scale:.2f})"
        )
        self._cancel_scheduled_animation()
        self.is_opening = False
        self.is_closing = True
        self.opening_scale = min(1.0, max(0.0, self.opening_scale))
        self._animate_step()

    def _animate_step(self) -> None:
        """Один кадр открытия/закрытия; без постоянного цикла в фоне."""
        if not self.animation_running:
            return

        self.canvas.delete("all")
        cx, cy = self.size // 2, self.size // 2
        max_r = self.size // 2 - 18

        if self.is_opening:
            self.opening_scale = min(1.0, self.opening_scale + 0.11)
            # Минимальный радиус, иначе первые кадры почти не видны (особенно с прозрачностью)
            r = max(6.0, max_r * self.opening_scale)
            self.draw_portal(cx, cy, min(r, max_r), angle=0.0)
            if self.opening_scale >= 1.0:
                self.is_opening = False
                self.opening_scale = 1.0
                self._widget_log("Анимация открытия завершена → статичный кадр")
                self.draw_portal_static()
                self._after_id = None
                self._after_master = None
                return
            self._schedule_after(42, self._animate_step)
            return

        if self.is_closing:
            self.opening_scale = max(0.0, self.opening_scale - 0.13)
            r = max(0.0, max_r * self.opening_scale)
            if r > 4:
                self.draw_portal(cx, cy, min(r, max_r), angle=0.0)
            if self.opening_scale <= 0.0:
                self.is_closing = False
                self.opening_scale = 0.0
                self._after_id = None
                self._after_master = None
                self._widget_log("Анимация закрытия завершена → виджет скрыт")
                try:
                    self.root.withdraw()
                except Exception:
                    pass
                return
            self._schedule_after(42, self._animate_step)
            return

    def draw_portal_static(self) -> None:
        """Статичный портал после раскрытия (без циклической анимации)."""
        if not self.animation_running:
            return
        self.canvas.delete("all")
        cx, cy = self.size // 2, self.size // 2
        if self.gif_frames:
            # Средний кадр — часто красивее, чем первый (чёрный кадр в начале видео)
            idx = max(0, len(self.gif_frames) // 2)
            img = self.gif_frames[idx]
            self.canvas.create_image(cx, cy, image=img, anchor=tk.CENTER)
        else:
            r_full = self.size // 2 - 18
            self.draw_portal(cx, cy, r_full, angle=0.0)
        self.opening_scale = 1.0

    def draw_portal(self, cx, cy, radius, angle: Optional[float] = None):
        self.canvas.create_oval(
            cx - radius,
            cy - radius,
            cx + radius,
            cy + radius,
            outline="#00A8FF",
            width=3,
            fill="#02060a",
        )
        base_angle = self.angle if angle is None else angle
        inner = radius * 0.72
        pts = []
        for i in range(16):
            a = base_angle + (i * 2 * math.pi / 16)
            pts.extend([cx + inner * math.cos(a), cy + inner * math.sin(a)])
        if len(pts) >= 6:
            self.canvas.create_polygon(pts, outline="#FF6B35", fill="#1a0a05", width=2)

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

        # Логируем начало отправки
        if self.main_app and hasattr(self.main_app, "log"):
            self.main_app.log(f"📤 Виджет: отправка {len(files)} файл(ов) на {ip}")
            for fp in files:
                self.main_app.log(f"   - {Path(fp).name}")
        
        for fp in files:
            if not os.path.exists(fp):
                if self.main_app and hasattr(self.main_app, "log"):
                    self.main_app.log(f"❌ Файл не найден: {Path(fp).name}")
                continue
                
            if self.main_app and hasattr(self.main_app, "send_file"):
                # Отправка в отдельном потоке с обработкой ошибок
                def send_with_error_handling(filepath, target_ip):
                    try:
                        self.main_app.send_file(filepath, target_ip)
                    except Exception as e:
                        if hasattr(self.main_app, "log"):
                            err = str(e)
                            if "refused" in err.lower() or "connection refused" in err.lower():
                                self.main_app.log(f"❌ Не удалось отправить {Path(filepath).name}")
                                self.main_app.log("💡 На втором ПК должен быть нажат «Запустить портал»")
                                self.main_app.log(f"💡 IP получателя: {target_ip}")
                            elif "timeout" in err.lower() or "timed out" in err.lower():
                                self.main_app.log(f"❌ Таймаут при отправке {Path(filepath).name}")
                                self.main_app.log("💡 Проверь что второй ПК включён и в сети")
                            elif "no route" in err.lower() or "unreachable" in err.lower():
                                self.main_app.log(f"❌ Нет пути к {target_ip}")
                                self.main_app.log("💡 Проверь что оба ПК в одной сети (Tailscale или LAN)")
                            else:
                                self.main_app.log(f"❌ Ошибка отправки {Path(filepath).name}: {err}")
                threading.Thread(
                    target=send_with_error_handling,
                    args=(fp, ip),
                    daemon=True,
                ).start()
            else:
                print(f"[Portal] Не удалось отправить {Path(fp).name}: главное приложение недоступно")

    def hide(self) -> None:
        if self.is_closing:
            self._widget_log("hide(): уже идёт закрытие — пропуск")
            return
        try:
            if not self.root.winfo_viewable():
                self._widget_log("hide(): окно уже не видно — пропуск")
                return
        except Exception as e:
            self._widget_log(f"hide(): ошибка winfo_viewable: {e}")
            return
        self._widget_log("hide(): начинаю схлопывание")
        self.start_closing_animation()

    def show(self) -> None:
        self._widget_log("show(): окно deiconify + lift, запуск открытия")
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.update_idletasks()
            if self.main_app is not None and hasattr(self.main_app, "update_idletasks"):
                self.main_app.update_idletasks()
        except Exception:
            pass
        # Всегда запускаем раскрытие при показе (масштаб уже 0 после закрытия или <1 при прерывании)
        self.start_opening_animation()

    def destroy(self):
        self.animation_running = False
        self._cancel_scheduled_animation()
        try:
            self.root.destroy()
        except Exception:
            pass

    def is_visible(self) -> bool:
        try:
            return bool(self.root.winfo_viewable())
        except Exception:
            return False


class GlobalHotkeyManager:
    """Глобальные хоткеи через pynput (Windows/macOS)."""

    def __init__(self, widget: PortalWidget, main_app: Any):
        self.widget = widget
        self.main_app = main_app
        self._thread: Optional[threading.Thread] = None

    def _safe_log(self, message: str) -> None:
        portal_thread_log(self.main_app, message, "⌨️")

    def start(self):
        self._safe_log("Старт фонового потока регистрации хоткеев…")
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        self._safe_log("Поток хоткеев: _run() начат")
        try:
            from pynput import keyboard
        except ImportError as e:
            self._safe_log(f"pynput не установлен ({e}) — ставь: pip install pynput")
            self._fallback_keyboard_lib()
            return

        is_mac = platform.system() == "Darwin"
        combo = {}

        if is_mac:
            combo["<cmd>+<alt>+p"] = self.toggle_widget
            combo["<cmd>+<shift>+c"] = self.push_clipboard
            combo["<cmd>+<shift>+v"] = self.pull_clipboard
            self._safe_log(
                "macOS: зарегистрированы Cmd+Option+P, Cmd+Shift+C/V "
                "(нужны «Мониторинг ввода» / Accessibility для Терминала или Python)"
            )
        else:
            combo["<ctrl>+<alt>+p"] = self.toggle_widget
            combo["<ctrl>+<alt>+c"] = self.push_clipboard
            combo["<ctrl>+<alt>+v"] = self.pull_clipboard
            self._safe_log(
                "Windows: зарегистрированы Ctrl+Alt+P, Ctrl+Alt+C/V "
                "(если не срабатывает — другая программа могла перехватить сочетание)"
            )

        self._safe_log(f"Ключи pynput: {', '.join(combo.keys())}")

        try:
            with keyboard.GlobalHotKeys(combo) as h:
                _started_msg = (
                    "pynput GlobalHotKeys запущен — жми сочетание. Полный лог: %TEMP%\\portal_hotkey_debug.log"
                    if platform.system() == "win32"
                    else "pynput GlobalHotKeys запущен — жми сочетание. Лог: /tmp/portal_hotkey_debug.log"
                )
                self._safe_log(_started_msg)
                h.join()
        except Exception as e:
            import traceback

            self._safe_log(f"pynput GlobalHotKeys упал: {e!r}")
            self._safe_log(traceback.format_exc())
            self._fallback_keyboard_lib()

    def _fallback_keyboard_lib(self) -> None:
        """Резерв на Windows, если pynput не взлетел."""
        if platform.system() != "Darwin":
            try:
                import keyboard as kb  # type: ignore
            except ImportError as e:
                self._safe_log(
                    f"Библиотека keyboard недоступна ({e}). Хоткеи не работают."
                )
                return
            self._safe_log("Пробую резерв: пакет keyboard (Ctrl+Alt+P/C/V)…")
            try:
                kb.add_hotkey("ctrl+alt+p", self.toggle_widget, suppress=False)
                kb.add_hotkey("ctrl+alt+c", self.push_clipboard, suppress=False)
                kb.add_hotkey("ctrl+alt+v", self.pull_clipboard, suppress=False)
                self._safe_log(
                    "keyboard: хоткеи повешены. Если снова тишина — запускай из консоли и смотри лог."
                )
                kb.wait()
            except Exception as e:
                import traceback

                self._safe_log(f"keyboard тоже упал: {e!r}")
                self._safe_log(traceback.format_exc())
            return
        self._safe_log(
            "На Mac резерва keyboard нет — почини pynput или права Accessibility."
        )

    def toggle_widget(self):
        self._safe_log("НАЖАТО сочетание портала (Ctrl+Alt+P / Cmd+Option+P) → планирую переключение в GUI")
        try:
            if self.main_app is not None and hasattr(self.main_app, "after"):
                self.main_app.after(0, self._toggle_ui)
            else:
                self.widget.root.after(0, self._toggle_ui)
        except Exception as e:
            self._safe_log(f"Ошибка main_app.after(0, toggle): {e!r}")

    def _toggle_ui(self):
        vis = False
        try:
            vis = self.widget.is_visible()
        except Exception as e:
            portal_thread_log(self.main_app, f"is_visible() ошибка: {e}", "⌨️")
        closing = getattr(self.widget, "is_closing", False)
        portal_thread_log(
            self.main_app,
            f"_toggle_ui: видим={vis}, закрывается={closing}",
            "⌨️",
        )
        # Во время схлопывания повторный хоткей — снова раскрыть, а не игнорировать
        if closing:
            self.widget.show()
            return
        if vis:
            self.widget.hide()
        else:
            self.widget.show()

    def push_clipboard(self):
        self._safe_log("Нажато: отправка буфера (Ctrl+Alt+C / Cmd+Shift+C)")
        if self.main_app and hasattr(self.main_app, "push_shared_clipboard_hotkey"):
            try:
                self.main_app.after(0, self.main_app.push_shared_clipboard_hotkey)
            except Exception as e:
                self._safe_log(f"after(clipboard push): {e!r}")
                self.main_app.push_shared_clipboard_hotkey()

    def pull_clipboard(self):
        self._safe_log("Нажато: получение буфера (Ctrl+Alt+V / Cmd+Shift+V)")
        if self.main_app and hasattr(self.main_app, "pull_shared_clipboard_hotkey"):
            try:
                self.main_app.after(0, self.main_app.pull_shared_clipboard_hotkey)
            except Exception as e:
                self._safe_log(f"after(clipboard pull): {e!r}")
                self.main_app.pull_shared_clipboard_hotkey()


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
