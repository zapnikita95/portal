"""
Виджет-портал для рабочего стола: прозрачный фон, drag&drop, горячие клавиши.
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
from typing import Optional, Any, List

import portal_config

try:
    from portal import PortalApp
except ImportError:
    PortalApp = None

# Цвет «хромакей» для прозрачного фона (Windows: -transparentcolor)
CHROMA_KEY = "#010101"


class PortalWidget:
    """Виджет-портал на рабочем столе"""

    def __init__(self, main_app: Any):
        self.main_app = main_app
        # ВАЖНО для macOS/CustomTkinter: Toplevel должен иметь master=главное окно
        if main_app is not None and hasattr(main_app, "winfo_toplevel"):
            self.root = tk.Toplevel(master=main_app)
        else:
            self.root = tk.Tk()

        self.root.title("🌀 Портал")

        self.size = 220
        self.angle = 0.0
        self.animation_running = True
        self.is_opening = False
        self.opening_scale = 0.0

        self.gif_frames: List[ImageTk.PhotoImage] = []
        self.current_frame = 0
        self.target_ip: Optional[str] = None
        self._dnd_tkinterdnd2 = False
        self._windnd_ok = False

        if main_app and getattr(main_app, "remote_peer_ip", None):
            self.target_ip = main_app.remote_peer_ip
        if not self.target_ip:
            self.target_ip = portal_config.load_remote_ip()

        self.load_portal_gif()
        self.setup_window()

        # Windows: windnd цепляется к HWND надёжнее, чем tkinterdnd2 на Toplevel
        if platform.system() != "Windows":
            try:
                from tkinterdnd2 import TkinterDnD

                TkinterDnD._require(self.root)
                self._dnd_tkinterdnd2 = True
            except Exception as e:
                self._dnd_tkinterdnd2 = False
                print(f"[Portal] tkinterdnd2: {e} — pip install tkinterdnd2")

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

        self.start_opening_animation()

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

        self.root.overrideredirect(True)

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
                self.root.attributes("-transparent", True)
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
        for name in (
            "portal_animated_opening.gif",
            "portal_opening.gif",
            "portal_animated.gif",
            "portal_static.gif",
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

    def start_opening_animation(self):
        self.is_opening = True
        self.opening_scale = 0.0
        self.animate()

    def animate(self):
        if not self.animation_running:
            return

        self.canvas.delete("all")
        cx, cy = self.size // 2, self.size // 2

        if self.is_opening:
            self.opening_scale = min(1.0, self.opening_scale + 0.08)
            r = (self.size // 2 - 18) * self.opening_scale
            if r > 1:
                self.draw_portal(cx, cy, r)
            if self.opening_scale >= 1.0:
                self.is_opening = False
        else:
            if self.gif_frames:
                img = self.gif_frames[self.current_frame % len(self.gif_frames)]
                self.canvas.create_image(cx, cy, image=img, anchor=tk.CENTER)
                self.current_frame += 1
            else:
                self.draw_portal(cx, cy, self.size // 2 - 18)
                self.angle += 0.12
                if self.angle >= 2 * math.pi:
                    self.angle = 0.0

        self.root.after(45, self.animate)

    def draw_portal(self, cx, cy, radius):
        self.canvas.create_oval(
            cx - radius,
            cy - radius,
            cx + radius,
            cy + radius,
            outline="#00A8FF",
            width=3,
            fill="#02060a",
        )
        inner = radius * 0.72
        pts = []
        for i in range(16):
            a = self.angle + (i * 2 * math.pi / 16)
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

        for fp in files:
            if self.main_app and hasattr(self.main_app, "send_file"):
                if hasattr(self.main_app, "log"):
                    self.main_app.log(f"📤 Виджет: {Path(fp).name}")
                threading.Thread(
                    target=self.main_app.send_file,
                    args=(fp, ip),
                    daemon=True,
                ).start()

    def hide(self):
        self.root.withdraw()

    def show(self):
        self.root.deiconify()
        self.root.lift()

    def destroy(self):
        self.animation_running = False
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

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        try:
            from pynput import keyboard
        except ImportError:
            print("[Portal] pynput не установлен — хоткеи отключены")
            return

        is_mac = platform.system() == "Darwin"
        combo = {}

        if is_mac:
            combo["<cmd>+<alt>+p"] = self.toggle_widget
            combo["<cmd>+<shift>+c"] = self.push_clipboard
            combo["<cmd>+<shift>+v"] = self.pull_clipboard
        else:
            combo["<ctrl>+<alt>+p"] = self.toggle_widget
            combo["<ctrl>+<alt>+c"] = self.push_clipboard
            combo["<ctrl>+<alt>+v"] = self.pull_clipboard

        try:
            with keyboard.GlobalHotKeys(combo) as h:
                h.join()
        except Exception as e:
            print(f"[Portal] GlobalHotKeys: {e}")

    def toggle_widget(self):
        try:
            self.widget.root.after(0, self._toggle_ui)
        except Exception:
            pass

    def _toggle_ui(self):
        if self.widget.is_visible():
            self.widget.hide()
        else:
            self.widget.show()

    def push_clipboard(self):
        if self.main_app and hasattr(self.main_app, "push_shared_clipboard_hotkey"):
            try:
                self.main_app.after(0, self.main_app.push_shared_clipboard_hotkey)
            except Exception:
                self.main_app.push_shared_clipboard_hotkey()

    def pull_clipboard(self):
        if self.main_app and hasattr(self.main_app, "pull_shared_clipboard_hotkey"):
            try:
                self.main_app.after(0, self.main_app.pull_shared_clipboard_hotkey)
            except Exception:
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
