"""
Портал - приложение для передачи файлов и синхронизации буфера обмена
через Tailscale сеть с красивым UI в стиле портала
"""

import sys

# Проверка версии Python (Python 3.13 может иметь проблемы с некоторыми библиотеками)
if sys.version_info >= (3, 13):
    print("⚠️  Python 3.13+ обнаружен. Некоторые библиотеки могут работать нестабильно.")
    print("   Рекомендуется Python 3.11 или 3.12 для стабильности.")
    print("   Если видите ошибки, попробуйте: pyenv install 3.12.7 && pyenv local 3.12.7\n")

import customtkinter as ctk
import socket
import threading
import json
import os
import shutil
import pyperclip
import time
from pathlib import Path
from typing import Optional, List
import subprocess
import platform

import portal_config

# Порт протокола Портала (должен совпадать на всех машинах)
PORTAL_PORT = 12345
# Как часто обновлять статус «пара онлайн?» (мс)
PEER_STATUS_POLL_MS = 20000

# Настройка темы
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def probe_portal_peer(host: str, port: int = PORTAL_PORT, timeout: float = 3.0) -> tuple[bool, str]:
    """
    Проверка, что на host действительно отвечает Портал (ping → pong).
    Возвращает (успех, код): код — ok | refused | timeout | bad_reply | dns | error
    """
    host = (host or "").strip()
    if not host:
        return False, "no_host"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        s.sendall(json.dumps({"type": "ping"}, ensure_ascii=False).encode("utf-8"))
        data = s.recv(4096)
        s.close()
        if not data:
            return False, "bad_reply"
        msg = parse_portal_json_message(data)
        if msg and msg.get("type") == "pong":
            return True, "ok"
        return False, "bad_reply"
    except ConnectionRefusedError:
        return False, "refused"
    except socket.timeout:
        return False, "timeout"
    except socket.gaierror:
        return False, "dns"
    except OSError:
        return False, "error"
    except json.JSONDecodeError:
        return False, "bad_reply"
    except Exception:
        return False, "error"


def parse_portal_json_message(data: bytes) -> Optional[dict]:
    """
    Разбор первого JSON-объекта из буфера (ping/pong и др.).
    Устойчиво к пробелам и лишнему тексту до/после — как при разных recv на Windows/macOS.
    """
    msg, _ = parse_first_json_object_bytes(data)
    return msg


def parse_first_json_object_bytes(buf: bytes) -> tuple[Optional[dict], int]:
    """
    Первый полный JSON-объект в буфере + сколько байт он занял.
    Нужно для ping и для file (после JSON сразу идут бинарные чанки в том же recv).
    """
    if not buf:
        return None, 0
    start = buf.find(b"{")
    if start < 0:
        return None, 0
    depth = 0
    for i in range(start, len(buf)):
        c = buf[i]
        if c == ord("{"):
            depth += 1
        elif c == ord("}"):
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(buf[start : i + 1].decode("utf-8"))
                    return obj, i + 1
                except (json.JSONDecodeError, UnicodeDecodeError):
                    return None, 0
    return None, 0


class PortalApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title("🌀 Портал")
        self.geometry("820x760")
        self.minsize(640, 520)
        
        # Переменные
        self.server_socket: Optional[socket.socket] = None
        self.is_server_running = False
        self.receive_thread: Optional[threading.Thread] = None
        self.clipboard_thread: Optional[threading.Thread] = None
        self.tailscale_ip = self.get_tailscale_ip()
        self.connected_devices = []
        self.sync_clipboard_enabled = False
        self.sync_target_ip = None
        self.is_receiving_clipboard = False
        # IP второго ПК — из файла настроек (один раз указал в главном окне)
        self.remote_peer_ip: Optional[str] = portal_config.load_remote_ip()
        
        # Создание UI
        self.create_ui()
        
        # Drag & Drop в главном окне
        self.setup_main_window_drag_drop()
        
        # Запуск мониторинга буфера обмена
        self.start_clipboard_monitor()
        
    def get_tailscale_ip(self) -> Optional[str]:
        """Получает Tailscale IP адрес устройства"""
        # Метод 1: через tailscale status --json
        try:
            result = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                # Ищем Self в Peer
                self_info = data.get("Self", {})
                tailscale_ips = self_info.get("TailscaleIPs", [])
                for ip in tailscale_ips:
                    if ip.startswith("100."):  # Tailscale IP range
                        return ip
        except:
            pass
        
        # Метод 2: через tailscale ip
        try:
            result = subprocess.run(
                ["tailscale", "ip", "-4"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                ip = result.stdout.strip()
                if ip and ip.startswith("100."):
                    return ip
        except:
            pass
        
        # Метод 3: через сетевые интерфейсы (Windows)
        try:
            import socket
            # Пробуем подключиться к Tailscale DNS
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(1)
            s.connect(("100.100.100.100", 1))
            ip = s.getsockname()[0]
            s.close()
            if ip.startswith("100."):
                return ip
        except:
            pass
        
        # Если Tailscale не найден, возвращаем локальный IP
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(1)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except:
            return None
    
    def create_ui(self):
        """Создание интерфейса"""
        # Всё в одном вертикальном скролле — до журнала можно долистать колёсиком / трекпадом
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        outer = ctk.CTkFrame(self, fg_color="transparent")
        outer.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(0, weight=1)
        main_frame = ctk.CTkScrollableFrame(outer, fg_color="transparent")
        main_frame.grid(row=0, column=0, sticky="nsew")
        outer.grid_rowconfigure(0, weight=1)
        outer.grid_columnconfigure(0, weight=1)
        
        # Заголовок
        title_label = ctk.CTkLabel(
            main_frame,
            text="🌀 ПОРТАЛ",
            font=ctk.CTkFont(size=32, weight="bold")
        )
        title_label.pack(pady=(20, 10))
        
        subtitle = ctk.CTkLabel(
            main_frame,
            text="Передача файлов и синхронизация буфера обмена",
            font=ctk.CTkFont(size=14),
            text_color="gray"
        )
        subtitle.pack(pady=(0, 30))
        
        # Информация о подключении
        info_frame = ctk.CTkFrame(main_frame)
        info_frame.pack(fill="x", padx=20, pady=10)
        
        if self.tailscale_ip:
            if self.tailscale_ip.startswith("100."):
                ip_label = ctk.CTkLabel(
                    info_frame,
                    text=f"📍 Tailscale IP: {self.tailscale_ip}",
                    font=ctk.CTkFont(size=12)
                )
                ip_label.pack(pady=10)
            else:
                ip_label = ctk.CTkLabel(
                    info_frame,
                    text=f"📍 Локальный IP: {self.tailscale_ip} (Tailscale не обнаружен)",
                    font=ctk.CTkFont(size=12),
                    text_color="orange"
                )
                ip_label.pack(pady=10)
        else:
            warning_label = ctk.CTkLabel(
                info_frame,
                text="⚠️ IP адрес не определен",
                font=ctk.CTkFont(size=12),
                text_color="orange"
            )
            warning_label.pack(pady=10)
        
        # IP второго компьютера (сохраняется в %APPDATA%/Portal или ~/Library/...)
        peer_frame = ctk.CTkFrame(main_frame)
        peer_frame.pack(fill="x", padx=20, pady=(0, 10))
        ctk.CTkLabel(
            peer_frame,
            text="🖥 IP второго компьютера (Tailscale / LAN) — указывается один раз:",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", padx=12, pady=(10, 4))
        ctk.CTkLabel(
            peer_frame,
            text="Сохраняется на диск. Отправка файлов/буфера и виджет используют его без повторных вопросов.",
            font=ctk.CTkFont(size=11),
            text_color="gray",
        ).pack(anchor="w", padx=12, pady=(0, 4))
        ctk.CTkLabel(
            peer_frame,
            text=f"💡 Указывай только IP (например 100.65.63.84), порт :{PORTAL_PORT} добавляется автоматически.",
            font=ctk.CTkFont(size=11),
            text_color="gray70",
        ).pack(anchor="w", padx=12, pady=(0, 8))
        row = ctk.CTkFrame(peer_frame, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(0, 12))
        self.peer_ip_entry = ctk.CTkEntry(row, width=280, placeholder_text="например 100.65.63.84")
        self.peer_ip_entry.pack(side="left", padx=(0, 10))
        if self.remote_peer_ip:
            self.peer_ip_entry.insert(0, self.remote_peer_ip)
        self.peer_ip_entry.bind("<KeyRelease>", self._on_peer_ip_edited)
        ctk.CTkButton(
            row,
            text="Сохранить IP",
            width=120,
            command=self.save_peer_ip_from_ui,
            font=ctk.CTkFont(size=13),
        ).pack(side="left")
        self.ip_saved_feedback = ctk.CTkLabel(
            row,
            text="",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#3dd68c",
        )
        self.ip_saved_feedback.pack(side="left", padx=(10, 0))

        # Подсказки по хоткеям (виджет + общий буфер)
        hotkey_frame = ctk.CTkFrame(peer_frame, fg_color="transparent")
        hotkey_frame.pack(fill="x", padx=12, pady=(0, 10))
        if platform.system() == "Darwin":
            hotkey_text = (
                "🔑 Быстрые клавиши (из любого приложения, нужен Accessibility → Терминал):\n"
                "   Показать или скрыть портал — Cmd+Option+P\n"
                "   Отправить буфер на другой ПК — Cmd+Shift+C\n"
                "   Вставить буфер с другого ПК — Cmd+Shift+V"
            )
        else:
            hotkey_text = (
                "🔑 Быстрые клавиши:\n"
                "   Показать или скрыть портал — Ctrl+Alt+P (запас: Win+Shift+P)\n"
                "   Отправить буфер на другой ПК — Ctrl+Alt+C\n"
                "   Вставить буфер с другого ПК — Ctrl+Alt+V"
            )
        ctk.CTkLabel(
            hotkey_frame,
            text=hotkey_text,
            font=ctk.CTkFont(size=12),
            text_color="gray",
            justify="left",
            anchor="w",
        ).pack(anchor="w")

        # Статус связи с парой (ping/pong к Порталу на другом ПК)
        self._peer_poll_job = None
        conn_frame = ctk.CTkFrame(peer_frame, fg_color="transparent")
        conn_frame.pack(fill="x", padx=12, pady=(4, 10))
        ctk.CTkLabel(
            conn_frame,
            text="📡 Статус связи",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", pady=(0, 4))
        self.local_link_status_label = ctk.CTkLabel(
            conn_frame,
            text="⏸ Локальный приём: неизвестно",
            font=ctk.CTkFont(size=12),
            text_color="gray",
            justify="left",
            anchor="w",
        )
        self.local_link_status_label.pack(anchor="w")
        self.peer_link_status_label = ctk.CTkLabel(
            conn_frame,
            text="⚪ Пара: укажи IP и нажми «Сохранить IP»",
            font=ctk.CTkFont(size=12),
            text_color="gray",
            justify="left",
            anchor="w",
        )
        self.peer_link_status_label.pack(anchor="w", pady=(2, 6))
        probe_row = ctk.CTkFrame(conn_frame, fg_color="transparent")
        probe_row.pack(anchor="w", fill="x")
        ctk.CTkButton(
            probe_row,
            text="🔄 Проверить связь",
            width=160,
            command=lambda: self.check_peer_connection_async(silent=False),
            font=ctk.CTkFont(size=12),
        ).pack(side="left")
        ctk.CTkLabel(
            probe_row,
            text=f"авто каждые {PEER_STATUS_POLL_MS // 1000} с, если указан IP",
            font=ctk.CTkFont(size=11),
            text_color="gray",
        ).pack(side="left", padx=(12, 0))

        recv_block = ctk.CTkFrame(peer_frame, fg_color="transparent")
        recv_block.pack(fill="x", padx=12, pady=(0, 10))
        ctk.CTkLabel(
            recv_block,
            text="📁 Куда сохранять входящие файлы на ЭТОМ ПК:",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w", pady=(0, 4))
        recv_row = ctk.CTkFrame(recv_block, fg_color="transparent")
        recv_row.pack(fill="x")
        self.receive_dir_entry = ctk.CTkEntry(recv_row, width=420, font=ctk.CTkFont(size=11))
        self.receive_dir_entry.pack(side="left", padx=(0, 8), fill="x", expand=True)
        try:
            self.receive_dir_entry.insert(0, str(portal_config.load_receive_dir()))
        except Exception:
            self.receive_dir_entry.insert(0, str(Path.home() / "Desktop"))
        ctk.CTkButton(
            recv_row,
            text="Обзор…",
            width=72,
            command=self.choose_receive_dir,
            font=ctk.CTkFont(size=11),
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            recv_row,
            text="Сохранить папку",
            width=120,
            command=self.save_receive_dir_from_ui,
            font=ctk.CTkFont(size=11),
        ).pack(side="left")
        
        # Кнопки управления
        button_frame = ctk.CTkFrame(main_frame)
        button_frame.pack(fill="x", padx=20, pady=20)
        
        self.start_button = ctk.CTkButton(
            button_frame,
            text="🚀 Запустить портал",
            command=self.toggle_server,
            font=ctk.CTkFont(size=14, weight="bold"),
            height=40
        )
        self.start_button.pack(side="left", padx=10, pady=10, fill="x", expand=True)
        
        self.send_button = ctk.CTkButton(
            button_frame,
            text="📤 Отправить файл",
            command=self.send_file_dialog,
            font=ctk.CTkFont(size=14),
            height=40,
            state="disabled"
        )
        self.send_button.pack(side="left", padx=10, pady=10, fill="x", expand=True)
        
        self.clipboard_button = ctk.CTkButton(
            button_frame,
            text="📋 Отправить буфер",
            command=self.send_clipboard_dialog,
            font=ctk.CTkFont(size=14),
            height=40,
            state="disabled"
        )
        self.clipboard_button.pack(side="left", padx=10, pady=10, fill="x", expand=True)
        
        # Статус
        self.status_label = ctk.CTkLabel(
            main_frame,
            text="⏸ Портал остановлен",
            font=ctk.CTkFont(size=12),
            text_color="gray"
        )
        self.status_label.pack(pady=10)
        
        # Лог: внутри общего скролла + своя прокрутка в текстбоксе
        log_frame = ctk.CTkFrame(main_frame)
        log_frame.pack(fill="x", expand=False, padx=12, pady=16)
        
        log_title = ctk.CTkLabel(
            log_frame,
            text="📋 Журнал активности (колёсиком листай всё окно ↓ и сам журнал)",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        log_title.pack(pady=(10, 5))
        
        self.log_text = ctk.CTkTextbox(log_frame, height=300, wrap="word")
        self.log_text.pack(fill="x", expand=False, padx=10, pady=(0, 10))
        self.log_text.insert("1.0", "Готов к работе...\n")
        self.log_text.configure(state="disabled")
        self._log_max_lines = 400

        self._refresh_local_link_status_label()
        self.after(800, lambda: self.check_peer_connection_async(silent=True))
        self._arm_peer_poll()

    def setup_main_window_drag_drop(self):
        """Drag & Drop файлов в главное окно (не только в виджет)."""
        if platform.system() == "Windows":
            try:
                import windnd

                def on_drop(files):
                    paths = []
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
                        self.log(f"📥 Получено {len(paths)} файл(ов) через drag & drop в главное окно")
                        for fp in paths:
                            if os.path.exists(fp):
                                self.log(f"   📄 {Path(fp).name}")
                                if self.remote_peer_ip:
                                    threading.Thread(
                                        target=self.send_file,
                                        args=(fp, self.remote_peer_ip),
                                        daemon=True,
                                    ).start()
                                else:
                                    self.log("⚠️ Сначала укажите IP выше и нажмите «Сохранить IP»")
                                    self.send_file_to_dialog(fp)

                # windnd работает на Tk окне (CTk наследует Tk)
                windnd.hook_dropfiles(self, on_drop)
                self.log("✅ Drag & Drop включён в главном окне (Windows)")
            except Exception as e:
                self.log(f"⚠️ Drag & Drop (Windows): {e}")
        else:
            try:
                from tkinterdnd2 import TkinterDnD, DND_FILES

                # CTk наследует Tk, можно использовать TkinterDnD
                TkinterDnD._require(self)
                self.drop_target_register(DND_FILES)
                self.dnd_bind("<<Drop>>", self._on_main_window_drop)
                self.log("✅ Drag & Drop включён в главном окне (macOS/Linux)")
            except Exception as e:
                self.log(f"⚠️ Drag & Drop (macOS/Linux): {e}")

    def _on_main_window_drop(self, event):
        """Обработка drop в главном окне (tkinterdnd2)."""
        import re

        data = event.data
        files = []
        if data.startswith("{") and data.endswith("}"):
            files = re.findall(r"\{([^}]+)\}", data)
        elif " " in data:
            files = data.split()
        else:
            files = [data]
        if files:
            self.log(f"📥 Получено {len(files)} файл(ов) через drag & drop")
            for fp in files:
                fp = fp.strip()
                if os.path.exists(fp):
                    self.log(f"   📄 {Path(fp).name}")
                    if self.remote_peer_ip:
                        threading.Thread(
                            target=self.send_file,
                            args=(fp, self.remote_peer_ip),
                            daemon=True,
                        ).start()
                    else:
                        self.log("⚠️ Сначала укажите IP выше и нажмите «Сохранить IP»")
                        self.send_file_to_dialog(fp)

    def _on_peer_ip_edited(self, _event=None):
        """Сбросить зелёную галочку, если пользователь снова правит IP."""
        if hasattr(self, "ip_saved_feedback"):
            self.ip_saved_feedback.configure(text="")

    def _peer_ip_entry_set_silent(self, text: str) -> None:
        """Обновить поле IP без срабатывания KeyRelease (иначе сбросится «✅ Сохранено»)."""
        if not hasattr(self, "peer_ip_entry"):
            return
        try:
            self.peer_ip_entry.unbind("<KeyRelease>")
            self.peer_ip_entry.delete(0, "end")
            if text:
                self.peer_ip_entry.insert(0, text)
        finally:
            self.peer_ip_entry.bind("<KeyRelease>", self._on_peer_ip_edited)

    def choose_receive_dir(self) -> None:
        from tkinter import filedialog

        cur = self.receive_dir_entry.get().strip() if hasattr(self, "receive_dir_entry") else ""
        initial = cur if cur and os.path.isdir(cur) else str(portal_config.default_receive_dir())
        d = filedialog.askdirectory(title="Папка для входящих файлов", initialdir=initial)
        if d:
            self.receive_dir_entry.delete(0, "end")
            self.receive_dir_entry.insert(0, d)

    def save_receive_dir_from_ui(self) -> None:
        if not hasattr(self, "receive_dir_entry"):
            return
        raw = self.receive_dir_entry.get().strip()
        if not raw:
            self.log("⚠️ Укажи путь к папке")
            return
        p = Path(raw).expanduser()
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self.log(f"❌ Не удалось создать папку: {e}")
            return
        if portal_config.save_receive_dir(p):
            self.log(f"✅ Папка приёма сохранена: {p.resolve()}")
        else:
            self.log("❌ Не удалось записать настройку в config.json")

    def save_peer_ip_from_ui(self):
        """Сохранить IP второго ПК из поля ввода (в файл + в память)."""
        ip = self.peer_ip_entry.get().strip()
        if not ip:
            self.log("⚠️ Введите IP адрес перед сохранением")
            if hasattr(self, "ip_saved_feedback"):
                self.ip_saved_feedback.configure(text="❌ Введите IP", text_color="#e74c3c")
            return
        
        if hasattr(self, "ip_saved_feedback"):
            self.ip_saved_feedback.configure(text="⏳ …", text_color="gray")
        self.log(f"💾 Сохранение IP: {ip}...")
        
        # Сохраняем напрямую через portal_config для проверки результата
        try:
            success = portal_config.save_remote_ip(ip)
        except Exception as e:
            self.log(f"❌ ИСКЛЮЧЕНИЕ при сохранении: {str(e)}")
            import traceback
            self.log(f"   {traceback.format_exc()}")
            success = False
        
        if success:
            # Обновляем в памяти
            self.remote_peer_ip = ip
            config_file = portal_config.config_path()
            # Двойная проверка - читаем сразу после сохранения
            verify = portal_config.load_remote_ip()
            if verify == ip:
                self.log(f"✅ IP второго ПК сохранён: {ip}")
                self.log(f"💾 Файл: {config_file}")
                if hasattr(self, "ip_saved_feedback"):
                    self.ip_saved_feedback.configure(
                        text="✅ Сохранено",
                        text_color="#3dd68c",
                    )
                # Обновляем поле (чтобы показать что сохранилось)
                try:
                    self._peer_ip_entry_set_silent(ip)
                except Exception as e:
                    self.log(f"⚠️ Не удалось обновить поле ввода: {e}")
                self.check_peer_connection_async(silent=False)
                self._arm_peer_poll()
            else:
                self.log(f"❌ ОШИБКА: IP не сохранился!")
                self.log(f"   Введено: {ip}")
                self.log(f"   Проверка после сохранения: {verify or '(пусто)'}")
                self.log(f"   Файл: {config_file}")
                if hasattr(self, "ip_saved_feedback"):
                    self.ip_saved_feedback.configure(
                        text="❌ Не записалось",
                        text_color="#e74c3c",
                    )
        else:
            # Проверяем что в файле
            saved = portal_config.load_remote_ip()
            config_file = portal_config.config_path()
            self.log(f"❌ ОШИБКА СОХРАНЕНИЯ!")
            self.log(f"   Введено: {ip}")
            self.log(f"   Прочитано из файла: {saved or '(пусто)'}")
            self.log(f"   Файл: {config_file}")
            self.log(f"   Файл существует: {config_file.exists()}")
            if config_file.exists():
                try:
                    content = config_file.read_text(encoding="utf-8")
                    self.log(f"   Содержимое: {content[:200]}")
                except Exception as e:
                    self.log(f"   Не удалось прочитать файл: {e}")
            else:
                self.log(f"   Папка существует: {config_file.parent.exists()}")
                self.log(f"   Папка: {config_file.parent}")
            if hasattr(self, "ip_saved_feedback"):
                self.ip_saved_feedback.configure(
                    text="❌ Ошибка записи",
                    text_color="#e74c3c",
                )

    def _peer_ip_for_probe(self) -> Optional[str]:
        """IP для ручной проверки: сначала поле ввода, иначе сохранённый."""
        if hasattr(self, "peer_ip_entry"):
            t = self.peer_ip_entry.get().strip()
            if t:
                return t
        return self.remote_peer_ip

    def _format_peer_probe_result(self, ip: str, ok: bool, code: str) -> tuple[str, str]:
        """Текст и цвет для строки статуса пары."""
        if not ip:
            return "⚪ Пара: укажи IP и «Сохранить IP»", "gray"
        if ok:
            return (
                f"🟢 Пара ({ip}): Портал на :{PORTAL_PORT} отвечает",
                "#3dd68c",
            )
        if code == "refused":
            return (
                f"🔌 Пара ({ip}): порт {PORTAL_PORT} закрыт — на том ПК «Запустить портал»",
                "#e74c3c",
            )
        if code == "timeout":
            return (
                f"⏱ Пара ({ip}): таймаут — Tailscale, IP или файрвол",
                "#e67e22",
            )
        if code == "dns":
            return f"❓ Пара ({ip}): адрес не найден (DNS)", "#e74c3c"
        if code == "bad_reply":
            return (
                f"⚠ Пара ({ip}): порт открыт, но ответ не Портал",
                "#f39c12",
            )
        if code == "no_host":
            return "⚪ Пара: укажи IP", "gray"
        return f"❌ Пара ({ip}): ошибка ({code})", "#e74c3c"

    def _refresh_local_link_status_label(self) -> None:
        if not hasattr(self, "local_link_status_label"):
            return
        if self.is_server_running:
            ip = self.tailscale_ip or "?"
            self.local_link_status_label.configure(
                text=(
                    f"🟢 Этот ПК принимает: {ip}:{PORTAL_PORT} "
                    "(второй комп шлёт сюда файлы/буфер)"
                ),
                text_color="#3dd68c",
            )
        else:
            self.local_link_status_label.configure(
                text=(
                    f"⏸ Этот ПК не принимает — нажми «Запустить портал» "
                    f"(слушать :{PORTAL_PORT})"
                ),
                text_color="#95a5a6",
            )

    def _cancel_peer_poll(self) -> None:
        if getattr(self, "_peer_poll_job", None) is not None:
            try:
                self.after_cancel(self._peer_poll_job)
            except Exception:
                pass
            self._peer_poll_job = None

    def _arm_peer_poll(self) -> None:
        self._cancel_peer_poll()
        if not self.remote_peer_ip:
            return
        self._peer_poll_job = self.after(PEER_STATUS_POLL_MS, self._peer_poll_tick)

    def _peer_poll_tick(self) -> None:
        self._peer_poll_job = None
        if self.remote_peer_ip:
            self.check_peer_connection_async(silent=True)
        if self.remote_peer_ip:
            self._arm_peer_poll()

    def check_peer_connection_async(self, silent: bool = False) -> None:
        """Фоновый ping → pong к Порталу на другой машине; обновляет подпись под IP."""
        ip = self._peer_ip_for_probe()
        if not ip:
            self.after(
                0,
                lambda: self.peer_link_status_label.configure(
                    text="⚪ Пара: укажи IP и «Сохранить IP»",
                    text_color="gray",
                ),
            )
            return

        def worker():
            ok, code = probe_portal_peer(ip)
            msg_t, msg_c = self._format_peer_probe_result(ip, ok, code)

            def apply():
                if hasattr(self, "peer_link_status_label"):
                    self.peer_link_status_label.configure(text=msg_t, text_color=msg_c)
                if not silent:
                    if ok:
                        self.log(
                            f"📡 Связь с парой: OK — {ip}:{PORTAL_PORT} "
                            f"(это Портал, ответ pong)"
                        )
                    else:
                        self.log(f"📡 Связь с парой: нет — {ip} ({code})")

            try:
                self.after(0, apply)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()
    
    def log(self, message: str):
        """Добавление сообщения в лог с автоскроллом вниз и ограничением строк"""
        self.log_text.configure(state="normal")
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{timestamp}] {message}\n")
        lines = int(self.log_text.index("end-1c").split(".")[0])
        if lines > self._log_max_lines:
            self.log_text.delete("1.0", f"{lines - self._log_max_lines + 1}.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
    
    def toggle_server(self):
        """Запуск/остановка сервера"""
        if not self.is_server_running:
            self.start_server()
        else:
            self.stop_server()
    
    def start_server(self):
        """Запуск сервера для приема файлов"""
        if not self.tailscale_ip:
            self.log("❌ Ошибка: Tailscale IP не найден")
            return
        
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind(("0.0.0.0", PORTAL_PORT))
            self.server_socket.listen(5)
            self.is_server_running = True
            
            self.receive_thread = threading.Thread(target=self.server_loop, daemon=True)
            self.receive_thread.start()
            
            self.start_button.configure(text="⏹ Остановить портал")
            self.send_button.configure(state="normal")
            self.clipboard_button.configure(state="normal")
            self.status_label.configure(
                text=f"✅ Портал активен на {self.tailscale_ip}:{PORTAL_PORT}",
                text_color="green"
            )
            self.log(f"✅ Портал запущен на {self.tailscale_ip}:{PORTAL_PORT}")
            self._refresh_local_link_status_label()
            self._arm_peer_poll()
        except Exception as e:
            self.log(f"❌ Ошибка запуска: {str(e)}")
            self.is_server_running = False
    
    def stop_server(self):
        """Остановка сервера"""
        self.is_server_running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
        
        self.start_button.configure(text="🚀 Запустить портал")
        self.send_button.configure(state="disabled")
        self.clipboard_button.configure(state="disabled")
        self.status_label.configure(
            text="⏸ Портал остановлен",
            text_color="gray"
        )
        self.log("⏸ Портал остановлен")
        self._cancel_peer_poll()
        self._refresh_local_link_status_label()
    
    def server_loop(self):
        """Основной цикл сервера"""
        while self.is_server_running:
            try:
                client_socket, addr = self.server_socket.accept()
                self._log_from_thread(f"🔗 Подключение от {addr[0]}")
                
                # Обработка клиента в отдельном потоке
                client_thread = threading.Thread(
                    target=self.handle_client,
                    args=(client_socket, addr),
                    daemon=True
                )
                client_thread.start()
            except:
                if self.is_server_running:
                    self.log("❌ Ошибка приема подключения")
                break
    
    def _log_from_thread(self, message: str) -> None:
        """Лог из потока accept/handle_client — только через главный поток Tk."""
        try:
            self.after(0, lambda m=message: self.log(m))
        except Exception:
            print(f"[Portal] {message}", flush=True)

    def handle_client(self, client_socket: socket.socket, addr):
        """Обработка клиентского подключения"""
        try:
            data = client_socket.recv(65536)
            message, json_end = parse_first_json_object_bytes(data)
            if not message:
                self._log_from_thread("⚠️ Клиент прислал не-JSON (ожидался ping / метаданные файла)")
                return

            tail = data[json_end:] if json_end <= len(data) else b""

            if message.get("type") == "file":
                self.receive_file(client_socket, message, prefix=tail)
            elif message.get("type") == "clipboard":
                self.receive_clipboard(message)
            elif message.get("type") == "get_clipboard":
                self.send_clipboard_response(client_socket)
            elif message.get("type") == "ping":
                # Как в репо: отвечаем pong сразу (проверка «это Портал» с другого ПК)
                pong = json.dumps(
                    {"type": "pong", "ok": True, "version": 1},
                    ensure_ascii=False,
                )
                client_socket.sendall(pong.encode("utf-8"))
                # Не спамим лог при авто-проверке каждые 20 с (тихий pong)

        except Exception as e:
            self._log_from_thread(f"❌ Ошибка обработки клиента: {str(e)}")
        finally:
            client_socket.close()
    
    def receive_file(
        self,
        client_socket: socket.socket,
        message: dict,
        prefix: bytes = b"",
    ):
        """Прием файла; prefix — байты уже прочитанные после JSON в первом recv."""
        raw_name = message.get("filename", "received_file")
        filename = Path(str(raw_name)).name or "received_file"
        filesize = message.get("filesize", 0)

        self._log_from_thread(f"📥 Прием файла: {filename} ({filesize} байт)")

        receive_dir = portal_config.load_receive_dir()
        try:
            receive_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self._log_from_thread(f"❌ Не удалось создать папку приёма {receive_dir}: {e}")
            raise

        filepath = receive_dir / filename

        with open(filepath, "wb") as f:
            remaining = filesize
            chunk_buf = prefix
            while remaining > 0:
                if chunk_buf:
                    take = min(len(chunk_buf), remaining)
                    f.write(chunk_buf[:take])
                    chunk_buf = chunk_buf[take:]
                    remaining -= take
                    continue
                chunk = client_socket.recv(min(8192, remaining))
                if not chunk:
                    break
                f.write(chunk)
                remaining -= len(chunk)

        self._log_from_thread(f"✅ Файл сохранен: {filepath}")

        client_socket.send(b"OK")
    
    def receive_clipboard(self, message: dict):
        """Прием буфера обмена"""
        clipboard_text = message.get("text", "")
        if clipboard_text:
            self.is_receiving_clipboard = True
            pyperclip.copy(clipboard_text)
            self.last_clipboard = clipboard_text
            self.is_receiving_clipboard = False
            self._log_from_thread(
                f"📋 Буфер обмена обновлен ({len(clipboard_text)} символов)"
            )
    
    def send_clipboard_response(self, client_socket: socket.socket):
        """Отправка текущего локального буфера клиенту (запрос get_clipboard)"""
        try:
            text = pyperclip.paste()
            if text is None:
                text = ""
            resp = json.dumps({"type": "clipboard", "text": text}, ensure_ascii=False)
            client_socket.sendall(resp.encode("utf-8"))
            self._log_from_thread(
                f"📋 Отправлен буфер по запросу ({len(text)} символов)"
            )
        except Exception as e:
            self._log_from_thread(f"❌ Ошибка ответа буфера: {str(e)}")
    
    def set_remote_peer_ip(self, ip: Optional[str]):
        """Сохранить IP второго компьютера (файл + поле в главном окне)."""
        ip_clean = (ip or "").strip() or None
        self.remote_peer_ip = ip_clean
        success = portal_config.save_remote_ip(ip_clean)
        if not success and ip_clean:
            if hasattr(self, "log"):
                self.log(f"⚠️ Не удалось сохранить IP в файл! Проверь права на запись")
            else:
                print(f"[Portal] Не удалось сохранить IP: {ip_clean}")
        # Обновляем поле ввода
        try:
            self._peer_ip_entry_set_silent(self.remote_peer_ip or "")
        except Exception as e:
            print(f"[Portal] Ошибка обновления поля IP: {e}")
    
    def push_shared_clipboard_hotkey(self):
        """Ctrl+Alt+C / Cmd+Shift+C — отправить локальный буфер на удалённый ПК"""
        ip = self.remote_peer_ip
        if not ip:
            self.log("⚠️ Сначала укажите IP в виджете (двойной клик по порталу)")
            return
        threading.Thread(target=self.send_clipboard, args=(ip,), daemon=True).start()
    
    def pull_shared_clipboard_hotkey(self):
        """Ctrl+Alt+V / Cmd+Shift+V — забрать буфер с удалённого ПК"""
        ip = self.remote_peer_ip
        if not ip:
            self.log("⚠️ Сначала укажите IP в виджете (двойной клик по порталу)")
            return
        threading.Thread(target=self._pull_clipboard_worker, args=(ip,), daemon=True).start()
    
    def _pull_clipboard_worker(self, target_ip: str):
        """Запрос буфера с удалённой машины (сервер должен быть запущен)"""
        def _log(msg: str):
            try:
                self.after(0, lambda m=msg: self.log(m))
            except Exception:
                print(msg)

        try:
            _log(f"📥 Запрос буфера с {target_ip}...")
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.settimeout(30)
            client_socket.connect((target_ip, PORTAL_PORT))
            _log(f"✅ Подключение установлено: {target_ip}:{PORTAL_PORT}")
            client_socket.send(json.dumps({"type": "get_clipboard"}).encode("utf-8"))
            buf = b""
            message = None
            while True:
                part = client_socket.recv(65536)
                if not part:
                    break
                buf += part
                try:
                    message = json.loads(buf.decode("utf-8", errors="replace"))
                    break
                except json.JSONDecodeError:
                    if len(buf) > 4 * 1024 * 1024:
                        break
                    continue
            client_socket.close()
            if message is None:
                raise ValueError("Пустой ответ")
            if message.get("type") == "clipboard":
                text = message.get("text", "")
                self.is_receiving_clipboard = True
                pyperclip.copy(text)
                self.last_clipboard = text
                self.is_receiving_clipboard = False
                _log(f"📋 Буфер с удалённого ПК вставлен ({len(text)} символов)")
            else:
                _log("⚠️ Неожиданный ответ при запросе буфера")
        except Exception as e:
            _log(f"❌ Не удалось получить буфер: {str(e)}")
    
    def send_file_dialog(self):
        """Выбор файла; IP берётся из сохранённых настроек (без лишних окон)."""
        from tkinter import filedialog
        self.log("📂 Открыт диалог выбора файла...")
        filepath = filedialog.askopenfilename(
            title="Выберите файл для отправки"
        )
        if not filepath:
            self.log("❌ Файл не выбран (отменено)")
            return
        self.log(f"✅ Файл выбран: {Path(filepath).name} ({Path(filepath).stat().st_size / 1024 / 1024:.2f} MB)")
        if self.remote_peer_ip:
            self.log(f"📤 Отправка на {self.remote_peer_ip}...")
            threading.Thread(
                target=self.send_file,
                args=(filepath, self.remote_peer_ip),
                daemon=True,
            ).start()
        else:
            self.log("⚠️ Сначала укажите IP второго ПК выше и нажмите «Сохранить IP»")
            self.send_file_to_dialog(filepath)
    
    def send_file_to_dialog(self, filepath: str):
        """Только если IP ещё не сохранён — один раз ввести и сохранить."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Отправить файл")
        dialog.geometry("400x200")
        
        label = ctk.CTkLabel(
            dialog,
            text="Введите IP второго ПК (будет сохранён):",
            font=ctk.CTkFont(size=14)
        )
        label.pack(pady=20)
        
        ip_entry = ctk.CTkEntry(dialog, width=200, font=ctk.CTkFont(size=12))
        ip_entry.pack(pady=10)
        ip_entry.insert(0, self.remote_peer_ip or "100.")
        
        def send():
            ip = ip_entry.get().strip()
            if ip:
                self.set_remote_peer_ip(ip)
                dialog.destroy()
                threading.Thread(
                    target=self.send_file,
                    args=(filepath, ip),
                    daemon=True
                ).start()
        
        send_button = ctk.CTkButton(
            dialog,
            text="Отправить",
            command=send,
            font=ctk.CTkFont(size=14)
        )
        send_button.pack(pady=20)
    
    def send_clipboard_dialog(self):
        """Отправка буфера на сохранённый IP без лишних окон."""
        if self.remote_peer_ip:
            threading.Thread(
                target=self.send_clipboard,
                args=(self.remote_peer_ip,),
                daemon=True,
            ).start()
        else:
            self.log("⚠️ Сначала укажите IP второго ПК выше и нажмите «Сохранить IP»")
            dialog = ctk.CTkToplevel(self)
            dialog.title("Отправить буфер обмена")
            dialog.geometry("400x200")
            label = ctk.CTkLabel(
                dialog,
                text="Введите IP второго ПК (будет сохранён):",
                font=ctk.CTkFont(size=14),
            )
            label.pack(pady=20)
            ip_entry = ctk.CTkEntry(dialog, width=200, font=ctk.CTkFont(size=12))
            ip_entry.pack(pady=10)
            ip_entry.insert(0, "100.")

            def send():
                ip = ip_entry.get().strip()
                if ip:
                    self.set_remote_peer_ip(ip)
                    dialog.destroy()
                    threading.Thread(
                        target=self.send_clipboard,
                        args=(ip,),
                        daemon=True,
                    ).start()

            send_button = ctk.CTkButton(
                dialog,
                text="Отправить",
                command=send,
                font=ctk.CTkFont(size=14),
            )
            send_button.pack(pady=20)
    
    def send_file(self, filepath: str, target_ip: str):
        """Отправка файла"""
        try:
            self.log(f"📤 Отправка файла на {target_ip}...")
            
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.settimeout(10)  # Таймаут 10 секунд
            try:
                client_socket.connect((target_ip, PORTAL_PORT))
                self.log(f"✅ Подключение установлено: {target_ip}:{PORTAL_PORT}")
            except socket.timeout:
                self.log(f"❌ Таймаут подключения к {target_ip}")
                self.log("💡 Проверь:")
                self.log("   1. На втором ПК нажат «Запустить портал»")
                self.log("   2. IP адрес правильный")
                self.log("   3. Оба ПК в одной сети (Tailscale или LAN)")
                return
            except ConnectionRefusedError:
                self.log(f"❌ Подключение отклонено: {target_ip}:{PORTAL_PORT}")
                self.log("💡 На втором ПК должен быть нажат «Запустить портал»")
                return
            except OSError as e:
                if "No route to host" in str(e) or "Network is unreachable" in str(e):
                    self.log(f"❌ Нет пути к {target_ip}")
                    self.log("💡 Проверь что оба ПК в одной сети (Tailscale или LAN)")
                else:
                    self.log(f"❌ Ошибка сети: {str(e)}")
                return
            
            filename = os.path.basename(filepath)
            filesize = os.path.getsize(filepath)
            
            # Отправка метаданных
            message = {
                "type": "file",
                "filename": filename,
                "filesize": filesize
            }
            client_socket.send(json.dumps(message).encode('utf-8'))
            time.sleep(0.1)  # Небольшая задержка
            
            # Отправка файла
            with open(filepath, "rb") as f:
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    client_socket.send(chunk)
            
            # Ожидание подтверждения
            response = client_socket.recv(1024)
            client_socket.close()
            
            if response == b"OK":
                self.log(f"✅ Файл успешно отправлен: {filename}")
            else:
                self.log(f"⚠️ Неопределенный ответ от получателя")
                
        except socket.timeout:
            self.log(f"❌ Таймаут при отправке на {target_ip}")
            self.log("💡 Файл слишком большой или медленное соединение")
        except Exception as e:
            err_msg = str(e)
            if "timed out" in err_msg.lower() or "timeout" in err_msg.lower():
                self.log(f"❌ Таймаут: {target_ip} не отвечает")
                self.log("💡 Убедись что на втором ПК запущен портал")
            elif "refused" in err_msg.lower():
                self.log(f"❌ Подключение отклонено: портал на {target_ip} не запущен")
                self.log("💡 На втором ПК нажми «Запустить портал»")
            else:
                self.log(f"❌ Ошибка отправки: {err_msg}")
    
    def send_clipboard(self, target_ip: str):
        """Отправка буфера обмена"""
        try:
            clipboard_text = pyperclip.paste()
            if not clipboard_text:
                self.log("⚠️ Буфер обмена пуст")
                return
            
            self.log(f"📤 Отправка буфера обмена на {target_ip}...")
            
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.settimeout(10)
            try:
                client_socket.connect((target_ip, PORTAL_PORT))
                self.log(f"✅ Подключение установлено: {target_ip}:{PORTAL_PORT}")
            except (socket.timeout, ConnectionRefusedError, OSError) as e:
                if isinstance(e, socket.timeout):
                    self.log(f"❌ Таймаут подключения к {target_ip}")
                elif isinstance(e, ConnectionRefusedError):
                    self.log(f"❌ Подключение отклонено: портал на {target_ip} не запущен")
                    self.log("💡 На втором ПК нажми «Запустить портал»")
                else:
                    self.log(f"❌ Нет пути к {target_ip}")
                    self.log("💡 Проверь что оба ПК в одной сети")
                return
            
            # Отправка метаданных
            message = {
                "type": "clipboard",
                "text": clipboard_text
            }
            client_socket.send(json.dumps(message).encode('utf-8'))
            client_socket.close()
            
            self.log(f"✅ Буфер обмена отправлен ({len(clipboard_text)} символов)")
                
        except Exception as e:
            err_msg = str(e)
            if "timed out" in err_msg.lower() or "timeout" in err_msg.lower():
                self.log(f"❌ Таймаут: {target_ip} не отвечает")
                self.log("💡 Убедись что на втором ПК запущен портал")
            elif "refused" in err_msg.lower():
                self.log(f"❌ Подключение отклонено: портал на {target_ip} не запущен")
                self.log("💡 На втором ПК нажми «Запустить портал»")
            else:
                self.log(f"❌ Ошибка отправки буфера: {err_msg}")
    
    def start_clipboard_monitor(self):
        """Мониторинг буфера на главном потоке (after) — без NSPasteboard warning"""
        try:
            self.last_clipboard = pyperclip.paste()
        except Exception:
            self.last_clipboard = ""
        self._clipboard_tick()

    def _clipboard_tick(self):
        """Один тик проверки буфера — вызывается на главном потоке"""
        try:
            if not self.is_receiving_clipboard:
                current = pyperclip.paste()
                if current != self.last_clipboard:
                    self.last_clipboard = current
                    if self.sync_clipboard_enabled and self.sync_target_ip:
                        threading.Thread(
                            target=self.send_clipboard,
                            args=(self.sync_target_ip,),
                            daemon=True
                        ).start()
        except Exception:
            pass
        self.after(1000, self._clipboard_tick)


if __name__ == "__main__":
    import sys
    
    # По умолчанию ВСЕГДА запускаем виджет (если не указан --no-widget)
    show_widget = "--no-widget" not in sys.argv and "-nw" not in sys.argv
    
    app = PortalApp()

    # Виджет запускается всегда (если не отключен явно)
    if show_widget:
        from portal_widget import PortalWidget, GlobalHotkeyManager, debug_log_path

        app.log(f"📝 Лог хоткеев (файл): {debug_log_path()}")
        try:
            app.update_idletasks()

            widget = PortalWidget(app)
            GlobalHotkeyManager(widget, app).start()
            widget.root.withdraw()
            app.log("✅ Виджет скрыт по умолчанию — Ctrl+Alt+P (Win) / Cmd+Option+P (Mac) чтобы показать")
            app.log("💡 IP второго ПК вводится один раз в поле выше → «Сохранить IP»")
            app.log("⌨️ Смотри строки «⌨️ …» ниже: если жмёшь хоткей — должны появляться сообщения.")
            app.log(
                "📡 Под IP — блок «Статус связи»: зелёный = второй ПК отвечает как Портал; "
                "серый/красный = там не запущен приём или неверный адрес."
            )
        except Exception as e:
            app.log(f"⚠️ Не удалось создать виджет: {str(e)}")
            import traceback

            app.log(traceback.format_exc())

    app.mainloop()
