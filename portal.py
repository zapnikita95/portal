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
from typing import Any, Optional, List
import subprocess
import platform
import queue

import portal_config
import portal_clipboard_rich as portal_clip_rich


def refresh_windows_shell_after_new_file(filepath: Path) -> None:
    """
    Подтолкнуть Explorer / рабочий стол обновить список файлов (новый файл сразу виден).
    Безопасно вызывать с любого потока.
    """
    if platform.system() != "Windows":
        return
    try:
        import ctypes

        fp = filepath.resolve()
        parent = fp if fp.is_dir() else fp.parent
        SHCNE_UPDATEDIR = 0x00001000
        SHCNE_CREATE = 0x00000002
        SHCNF_PATHW = 0x0005
        SHCNF_FLUSH = 0x1000
        buf_dir = ctypes.create_unicode_buffer(str(parent))
        ctypes.windll.shell32.SHChangeNotify(
            SHCNE_UPDATEDIR, SHCNF_PATHW | SHCNF_FLUSH, buf_dir, None
        )
        if fp.is_file():
            buf_file = ctypes.create_unicode_buffer(str(fp))
            ctypes.windll.shell32.SHChangeNotify(
                SHCNE_CREATE, SHCNF_PATHW | SHCNF_FLUSH, buf_file, None
            )
    except Exception:
        pass


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
    Через JSONDecoder.raw_decode — корректно, если в строках JSON есть «}», «{»
    (например имя файла report}.txt); подсчёт скобок по сырым байтам это ломал.
    """
    if not buf:
        return None, 0
    try:
        s = buf.decode("utf-8-sig")
    except UnicodeDecodeError:
        s = buf.decode("utf-8", errors="replace")
    decoder = json.JSONDecoder()
    i = 0
    n = len(s)
    while i < n and s[i].isspace():
        i += 1
    if i >= n:
        return None, 0
    if s[i] != "{":
        j = s.find("{", i)
        if j < 0:
            return None, 0
        i = j
    try:
        obj, end_char = decoder.raw_decode(s, i)
    except json.JSONDecodeError:
        return None, 0
    consumed = s[:end_char].encode("utf-8")
    return obj, len(consumed)


def _portal_sendall(sock: socket.socket, data: bytes) -> None:
    """Всегда sendall по протоколу (на Windows send() может уложить не все байты)."""
    if data:
        sock.sendall(data)


def _recv_ok_prefix(
    sock: socket.socket, timeout: float = 180.0, max_bytes: int = 256
) -> bytes:
    """Ответ получателя после передачи тела — ожидаем префикс OK."""
    sock.settimeout(timeout)
    buf = b""
    while len(buf) < max_bytes:
        chunk = sock.recv(max(1, max_bytes - len(buf)))
        if not chunk:
            break
        buf += chunk
        if buf.startswith(b"OK"):
            return buf
        stripped = buf.lstrip()
        if stripped.startswith(b"OK"):
            return buf
    return buf


def read_first_json_from_stream(
    client_socket: socket.socket,
    max_accumulated: int = 8 * 1024 * 1024,
) -> tuple[Optional[dict], bytes]:
    """
    Читать из TCP, пока не соберётся первый полный JSON-объект.
    Один recv() недостаточен: заголовок может прийти несколькими пакетами —
    тогда разбор падал, сокет закрывался → на отправителе WinError 10054.
    """
    buf = b""
    while len(buf) <= max_accumulated:
        message, json_end = parse_first_json_object_bytes(buf)
        if message is not None:
            tail = buf[json_end:] if json_end <= len(buf) else b""
            return message, tail
        chunk = client_socket.recv(65536)
        if not chunk:
            return None, buf
        buf += chunk
    return None, buf


def _safe_receive_filename(name: str) -> str:
    """Имя файла без путей и недопустимых символов Windows/кроссплатформенно."""
    base = Path(str(name)).name
    if not base or base in (".", ".."):
        return "received_file"
    bad = '<>:"/\\|?*\x00'
    for c in bad:
        base = base.replace(c, "_")
    base = base.strip(" .")
    if not base:
        base = "received_file"
    return base[:240]


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
        self.sync_clipboard_enabled = portal_config.load_auto_clipboard_enabled()
        self.sync_target_ips: List[str] = portal_config.load_remote_ips()
        self.is_receiving_clipboard = False
        # IP компьютеров — из файла настроек
        self.remote_peer_ip: Optional[str] = portal_config.load_remote_ip()
        # pynput / windnd вызываются не с главного потока Tk — только put здесь, разбор через after()
        self._ui_signal_queue: queue.SimpleQueue = queue.SimpleQueue()
        self.portal_widget_ref: Optional[Any] = None
        self._hotkey_mgr: Optional[Any] = None
        # Один «волна» отправки буфера (хоткей / авто / кнопка) — без параллельных push.
        self._clipboard_push_lock = threading.Lock()
        self._clipboard_push_wave_active = False
        self._clipboard_pull_lock = threading.Lock()

        # Создание UI
        self.create_ui()
        
        # Drag & Drop в главном окне
        self.setup_main_window_drag_drop()
        
        # Запуск мониторинга буфера обмена
        self.start_clipboard_monitor()

        # pynput / windnd → только очередь; разбор здесь (главный поток), иначе GIL crash Py3.12 + Tk
        self.after(30, self._drain_ui_signal_queue)

    def _drain_ui_signal_queue(self) -> None:
        try:
            while True:
                item = self._ui_signal_queue.get_nowait()
                if item == "toggle":
                    mgr = self._hotkey_mgr
                    if mgr is not None:
                        mgr._toggle_ui()
                elif item == "push":
                    mgr = self._hotkey_mgr
                    if mgr is not None:
                        mgr._on_push()
                elif item == "pull":
                    mgr = self._hotkey_mgr
                    if mgr is not None:
                        mgr._on_pull()
                elif isinstance(item, tuple) and len(item) == 2:
                    if item[0] == "drop":
                        w = self.portal_widget_ref
                        if w is not None:
                            try:
                                w.send_files(list(item[1]))
                            except Exception as ex:
                                print(f"[Portal] send_files (очередь): {ex}")
                    elif item[0] == "main_drop":
                        try:
                            self._process_main_window_drop(list(item[1]))
                        except Exception as ex:
                            print(f"[Portal] main drop: {ex}")
        except queue.Empty:
            pass
        try:
            self.after(25, self._drain_ui_signal_queue)
        except Exception:
            pass

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
        
        # IP компьютеров в сетке (сохраняется в %APPDATA%/Portal или ~/Library/...)
        peer_frame = ctk.CTkFrame(main_frame)
        peer_frame.pack(fill="x", padx=20, pady=(0, 10))
        ctk.CTkLabel(
            peer_frame,
            text="🖥 IP компьютеров для отправки (Tailscale / LAN) — один или несколько:",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", padx=12, pady=(10, 4))
        ctk.CTkLabel(
            peer_frame,
            text="Файлы и буфер отправляются на ВСЕ указанные IP. Через запятую или с новой строки.",
            font=ctk.CTkFont(size=11),
            text_color="gray",
        ).pack(anchor="w", padx=12, pady=(0, 4))
        ctk.CTkLabel(
            peer_frame,
            text=f"💡 Например: 100.65.63.84, 100.66.1.10 или по одному на строку. Порт :{PORTAL_PORT} добавляется автоматически.",
            font=ctk.CTkFont(size=11),
            text_color="gray70",
        ).pack(anchor="w", padx=12, pady=(0, 4))
        row = ctk.CTkFrame(peer_frame, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(0, 4))
        self.peer_ip_entry = ctk.CTkTextbox(row, width=380, height=70, font=ctk.CTkFont(size=12))
        self.peer_ip_entry.pack(side="left", padx=(0, 10))
        ips_text = ", ".join(portal_config.load_remote_ips()) or ""
        if ips_text:
            self.peer_ip_entry.insert("1.0", ips_text)
        self.peer_ip_entry.bind("<KeyRelease>", self._on_peer_ip_edited)
        btn_row = ctk.CTkFrame(peer_frame, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=(4, 12))
        ctk.CTkButton(
            btn_row,
            text="Сохранить IP",
            width=120,
            command=self.save_peer_ip_from_ui,
            font=ctk.CTkFont(size=13),
        ).pack(side="left")
        self.ip_saved_feedback = ctk.CTkLabel(
            btn_row,
            text="",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#3dd68c",
        )
        self.ip_saved_feedback.pack(side="left", padx=(10, 0))
        self.auto_clipboard_var = ctk.BooleanVar(value=self.sync_clipboard_enabled)
        ctk.CTkCheckBox(
            btn_row,
            text="Авто: при копировании сразу отправлять буфер на все IP",
            variable=self.auto_clipboard_var,
            command=self._on_auto_clipboard_toggled,
            font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=(24, 0))

        # Подсказки по хоткеям (виджет + общий буфер)
        hotkey_frame = ctk.CTkFrame(peer_frame, fg_color="transparent")
        hotkey_frame.pack(fill="x", padx=12, pady=(0, 10))
        if platform.system() == "Darwin":
            hotkey_text = (
                "🔑 Быстрые клавиши (из любого приложения, нужен Accessibility → Терминал):\n"
                "   Показать или скрыть портал — Cmd+Option+P\n"
                "   Отправить буфер (текст / картинка / файлы) — Cmd+Shift+C\n"
                "   Забрать буфер с другого ПК (текст / файлы / картинка) — Cmd+Shift+V или Cmd+Option+V"
            )
        else:
            hotkey_text = (
                "🔑 Быстрые клавиши:\n"
                "   Портал — Ctrl+Alt+P или Win+Shift+P (глобально, pynput). keyboard только PORTAL_HOTKEY_BACKEND=keyboard\n"
                "   Отправить буфер (текст / картинка / файлы) — Ctrl+Alt+C\n"
                "   Забрать буфер с другого ПК (текст / файлы / картинка) — Ctrl+Alt+V"
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

        mode_row = ctk.CTkFrame(recv_block, fg_color="transparent")
        mode_row.pack(fill="x", pady=(8, 0))
        ctk.CTkLabel(
            mode_row,
            text="Файлы из буфера другого ПК:",
            font=ctk.CTkFont(size=11),
        ).pack(side="left", padx=(0, 8))
        self._incoming_files_mode_labels = dict(
            portal_config.INCOMING_CLIPBOARD_FILES_MODE_LABELS_RU
        )
        _mcur = portal_config.load_incoming_clipboard_files_mode()
        if _mcur not in self._incoming_files_mode_labels:
            _mcur = "both"
        self.incoming_files_mode_var = ctk.StringVar(
            value=self._incoming_files_mode_labels[_mcur]
        )
        ctk.CTkOptionMenu(
            mode_row,
            variable=self.incoming_files_mode_var,
            values=list(self._incoming_files_mode_labels.values()),
            command=self._on_incoming_clipboard_files_mode_changed,
            width=340,
            font=ctk.CTkFont(size=11),
        ).pack(side="left", fill="x", expand=True)

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
        
        log_title_row = ctk.CTkFrame(log_frame, fg_color="transparent")
        log_title_row.pack(fill="x", padx=10, pady=(10, 5))
        ctk.CTkLabel(
            log_title_row,
            text="📋 Журнал",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(side="left")
        ctk.CTkButton(
            log_title_row,
            text="Копировать всё",
            width=120,
            command=self.copy_log_to_clipboard,
            font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=(12, 6))
        ctk.CTkButton(
            log_title_row,
            text="Копировать выделение",
            width=150,
            command=self.copy_log_selection_to_clipboard,
            font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            log_title_row,
            text="Открыть папку лога",
            width=140,
            command=self.open_log_folder,
            font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=(0, 0))
        self.log_hint_label = ctk.CTkLabel(
            log_frame,
            text=f"💡 Ctrl+C в журнале — копировать выделение. Дублирование в файл: {portal_config.activity_log_path()}",
            font=ctk.CTkFont(size=11),
            text_color="gray",
            wraplength=720,
            justify="left",
            anchor="w",
        )
        self.log_hint_label.pack(anchor="w", padx=10, pady=(0, 4))

        self.log_text = ctk.CTkTextbox(log_frame, height=300, wrap="word")
        self.log_text.pack(fill="x", expand=False, padx=10, pady=(0, 10))
        self.log_text.insert("1.0", "Готов к работе...\n")
        self._setup_log_text_selectable()
        self._log_max_lines = 400

        self._refresh_local_link_status_label()
        self.after(800, lambda: self.check_peer_connection_async(silent=True))
        self._arm_peer_poll()
        self.after(
            200,
            lambda: self.log(
                "📋 Журнал здесь внизу (не пропал): «Копировать всё», Ctrl+C по выделению, "
                f"файл {portal_config.activity_log_path()}"
            ),
        )

    def _process_main_window_drop(self, paths: List[str]) -> None:
        """
        Обработка путей после drag&drop — только из главного потока Tk.
        windnd кладёт пути в _ui_signal_queue; сюда попадаем из _drain_ui_signal_queue.
        """
        existing = [p for p in paths if p and os.path.exists(p)]
        if paths:
            self.log(f"📥 Получено {len(paths)} файл(ов) через drag & drop в главное окно")
            for fp in existing:
                self.log(f"   📄 {Path(fp).name}")
        ips = self.get_target_ips()
        if ips:
            for fp in existing:
                for ip in ips:
                    threading.Thread(
                        target=self.send_file,
                        args=(fp, ip),
                        daemon=True,
                    ).start()
        else:
            if not existing:
                return
            self.log("⚠️ Сначала укажите IP выше и нажмите «Сохранить IP»")
            self.send_file_to_dialog(existing[0])
            if len(existing) > 1:
                self.log(
                    f"💡 Указан IP — перетащите снова или отправьте остальные {len(existing) - 1} файл(ов) отдельно."
                )

    def setup_main_window_drag_drop(self):
        """Drag & Drop файлов в главное окно (не только в виджет)."""
        if platform.system() == "Windows":
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
                    if not paths:
                        return
                    snapshot = list(paths)
                    try:
                        self._ui_signal_queue.put(("main_drop", snapshot))
                    except Exception:
                        print("[Portal] main window drop: очередь недоступна", flush=True)

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
                    ips = self.get_target_ips()
                    if ips:
                        for ip in ips:
                            threading.Thread(
                                target=self.send_file,
                                args=(fp, ip),
                                daemon=True,
                            ).start()
                    else:
                        self.log("⚠️ Сначала укажите IP выше и нажмите «Сохранить IP»")
                        self.send_file_to_dialog(fp)

    def _on_peer_ip_edited(self, _event=None):
        """Сбросить зелёную галочку, если пользователь снова правит IP."""
        if hasattr(self, "ip_saved_feedback"):
            self.ip_saved_feedback.configure(text="")

    def _on_auto_clipboard_toggled(self) -> None:
        """Переключатель авто-отправки буфера при копировании."""
        self.sync_clipboard_enabled = bool(self.auto_clipboard_var.get())
        self.sync_target_ips = portal_config.load_remote_ips()
        portal_config.save_auto_clipboard_enabled(self.sync_clipboard_enabled)
        if self.sync_clipboard_enabled and self.sync_target_ips:
            self.log("✅ Авто-отправка буфера: при копировании текст уйдёт на все сохранённые IP")
        else:
            self.log("⏸ Авто-отправка буфера выключена")

    def _on_incoming_clipboard_files_mode_changed(self, choice: str) -> None:
        """Режим: куда писать файлы из чужого буфера и класть ли их в системный буфер."""
        rev = {v: k for k, v in self._incoming_files_mode_labels.items()}
        mode = rev.get(str(choice), "both")
        if portal_config.save_incoming_clipboard_files_mode(mode):
            hints = {
                "both": "сохраняем в папку приёма и кладём файлы в буфер (Cmd+V)",
                "disk": "только папка приёма, буфер не трогаем",
                "clipboard": "файлы во временной папке и в буфере — папку приёма не используем",
            }
            self.log(f"💾 Режим входящих файлов из буфера: {hints.get(mode, mode)}")
        else:
            self.log("❌ Не удалось сохранить режим в config.json")

    def _parse_ips_from_entry(self) -> List[str]:
        """Разбор IP из поля (запятая, пробел, перенос строки)."""
        if not hasattr(self, "peer_ip_entry"):
            return []
        raw = self.peer_ip_entry.get("1.0", "end").strip()
        if not raw:
            return []
        parts = []
        for sep in (",", "\n", " ", ";", "\t"):
            raw = raw.replace(sep, " ")
        for s in raw.split():
            s = s.strip()
            if s and s not in parts:
                parts.append(s)
        return parts

    def _peer_ip_entry_set_silent(self, text: str) -> None:
        """Обновить поле IP (Textbox)."""
        if not hasattr(self, "peer_ip_entry"):
            return
        try:
            self.peer_ip_entry.unbind("<KeyRelease>")
            self.peer_ip_entry.delete("1.0", "end")
            if text:
                self.peer_ip_entry.insert("1.0", text)
        finally:
            self.peer_ip_entry.bind("<KeyRelease>", self._on_peer_ip_edited)

    def get_target_ips(self) -> List[str]:
        """IP для отправки (все сохранённые, без дубликатов, порядок сохраняется)."""
        seen = set()
        out: List[str] = []
        for ip in portal_config.load_remote_ips():
            if ip not in seen:
                seen.add(ip)
                out.append(ip)
        return out

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
        """Сохранить IP из поля (один или несколько через запятую/строку)."""
        ips = self._parse_ips_from_entry()
        if not ips:
            self.log("⚠️ Введите хотя бы один IP перед сохранением")
            if hasattr(self, "ip_saved_feedback"):
                self.ip_saved_feedback.configure(text="❌ Введите IP", text_color="#e74c3c")
            return

        if hasattr(self, "ip_saved_feedback"):
            self.ip_saved_feedback.configure(text="⏳ …", text_color="gray")
        self.log(f"💾 Сохранение {len(ips)} IP: {', '.join(ips)}...")

        try:
            success = portal_config.save_remote_ips(ips)
        except Exception as e:
            self.log(f"❌ ИСКЛЮЧЕНИЕ при сохранении: {str(e)}")
            import traceback
            self.log(f"   {traceback.format_exc()}")
            success = False

        if success:
            self.remote_peer_ip = ips[0] if ips else None
            self.sync_target_ips = ips
            verify = portal_config.load_remote_ips()
            if verify == ips:
                self.log(f"✅ Сохранено {len(ips)} IP: {', '.join(ips)}")
                if hasattr(self, "ip_saved_feedback"):
                    self.ip_saved_feedback.configure(text="✅ Сохранено", text_color="#3dd68c")
                self._peer_ip_entry_set_silent(", ".join(ips))
                self.check_peer_connection_async(silent=False)
                self._arm_peer_poll()
                if hasattr(self, "auto_clipboard_var") and self.auto_clipboard_var.get():
                    self.sync_clipboard_enabled = True
                    self.sync_target_ips = ips
            else:
                self.log(f"⚠️ Сохранено, но проверка: ожидалось {ips}, прочитано {verify}")
                if hasattr(self, "ip_saved_feedback"):
                    self.ip_saved_feedback.configure(text="⚠️ Проверь", text_color="orange")
        else:
            self.log("❌ Не удалось сохранить IP")
            if hasattr(self, "ip_saved_feedback"):
                self.ip_saved_feedback.configure(text="❌ Ошибка", text_color="#e74c3c")

    def _peer_ip_for_probe(self) -> Optional[str]:
        """IP для проверки связи (первый из списка)."""
        ips = self.get_target_ips()
        return ips[0] if ips else None

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
        if not self.get_target_ips():
            return
        self._peer_poll_job = self.after(PEER_STATUS_POLL_MS, self._peer_poll_tick)

    def _peer_poll_tick(self) -> None:
        self._peer_poll_job = None
        if self.get_target_ips():
            self.check_peer_connection_async(silent=True)
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
    
    def _setup_log_text_selectable(self) -> None:
        """Журнал не disabled — иначе нельзя выделить и Ctrl+C. Ручной ввод блокируем."""
        tb = self.log_text
        tb.configure(state="normal")

        def on_key(event):
            keysym = (event.keysym or "").lower()
            st = int(event.state or 0)
            mod = (
                (st & 0x4)
                or (st & 0x8)
                or (st & 0x20000)
                or (st & 0x1000000)
            )
            if mod and keysym in ("c", "a", "insert"):
                return
            nav = (
                "left",
                "right",
                "up",
                "down",
                "home",
                "end",
                "prior",
                "next",
            )
            if keysym in nav:
                return
            if keysym.startswith("shift") or keysym in ("caps_lock", "escape"):
                return
            return "break"

        tb.bind("<Key>", on_key, add=True)
        tb.bind("<<Paste>>", lambda e: "break", add=True)

        def focus_log(_e=None):
            try:
                tb.focus_set()
            except Exception:
                pass

        tb.bind("<Button-1>", focus_log, add=True)

    def _append_activity_log_file(self, line: str) -> None:
        try:
            p = portal_config.activity_log_path()
            with open(p, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError:
            pass

    def copy_log_to_clipboard(self) -> None:
        """Весь журнал в буфер обмена."""
        try:
            txt = self.log_text.get("1.0", "end-1c")
            pyperclip.copy(txt)
            self.log(f"📋 Журнал скопирован в буфер ({len(txt)} символов)")
        except Exception as e:
            self.log(f"❌ Не удалось скопировать журнал: {e}")

    def copy_log_selection_to_clipboard(self) -> None:
        """Только выделенный фрагмент."""
        try:
            sel = self.log_text.get("sel.first", "sel.last")
            if sel.strip():
                pyperclip.copy(sel)
                self.log("📋 Выделение скопировано в буфер")
        except Exception:
            self.log("⚠️ Нет выделения: кликни в журнал, выдели мышью текст, затем снова «Копировать выделение» или Ctrl+C")

    def open_log_folder(self) -> None:
        """Папка с portal_activity.log и config.json."""
        folder = portal_config.activity_log_path().parent
        try:
            if platform.system() == "Windows":
                os.startfile(str(folder))
            elif platform.system() == "Darwin":
                subprocess.run(["open", str(folder)], check=False)
            else:
                subprocess.run(["xdg-open", str(folder)], check=False)
            self.log(f"📂 Открыта папка: {folder}")
        except Exception as e:
            self.log(f"❌ Не удалось открыть папку: {e}")

    def log(self, message: str):
        """Добавление сообщения в лог с автоскроллом вниз и ограничением строк"""
        timestamp = time.strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}\n"
        self.log_text.insert("end", line)
        lines = int(self.log_text.index("end-1c").split(".")[0])
        if lines > self._log_max_lines:
            self.log_text.delete("1.0", f"{lines - self._log_max_lines + 1}.0")
        self.log_text.see("end")
        self._append_activity_log_file(line)
    
    def toggle_server(self):
        """Запуск/остановка сервера"""
        if not self.is_server_running:
            self.start_server()
        else:
            self.stop_server()
    
    def start_server(self):
        """Запуск сервера для приема файлов"""
        if not self.tailscale_ip:
            self.log(
                "⚠️ Tailscale IP не определён — сервер всё равно запускается на 0.0.0.0 "
                f"(порт {PORTAL_PORT}). Укажи на других ПК свой LAN / Tailscale IP этого компа."
            )

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
            shown = self.tailscale_ip or "все интерфейсы (0.0.0.0)"
            self.status_label.configure(
                text=f"✅ Портал активен — {shown}:{PORTAL_PORT}",
                text_color="green",
            )
            self.log(f"✅ Портал запущен, приём на 0.0.0.0:{PORTAL_PORT} (для связи: {shown})")
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
            message, tail = read_first_json_from_stream(client_socket)
            if not message:
                self._log_from_thread(
                    "⚠️ Клиент прислал не-JSON или обрыв (ожидался ping / метаданные файла)"
                )
                return

            mtype = message.get("type")
            if mtype == "file":
                self.receive_file(client_socket, message, prefix=tail)
            elif mtype == "clipboard_files":
                self.receive_clipboard_files(client_socket, message, prefix=tail)
            elif mtype == "clipboard_rich":
                self.receive_clipboard_rich(client_socket, message, prefix=tail)
            elif mtype == "clipboard":
                self.receive_clipboard(message)
            elif mtype == "get_clipboard":
                self.send_clipboard_response(client_socket)
            elif mtype == "ping":
                # Как в репо: отвечаем pong сразу (проверка «это Портал» с другого ПК)
                pong = json.dumps(
                    {"type": "pong", "ok": True, "version": 1},
                    ensure_ascii=False,
                )
                client_socket.sendall(pong.encode("utf-8"))
                # Не спамим лог при авто-проверке каждые 20 с (тихий pong)
            else:
                self._log_from_thread(
                    f"⚠️ Неизвестный тип запроса: {mtype!r} — обнови Портал на обоих ПК до одной версии"
                )

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
        filename = _safe_receive_filename(str(raw_name))
        try:
            filesize = int(message.get("filesize", 0))
        except (TypeError, ValueError):
            filesize = 0
        if filesize < 0:
            filesize = 0

        self._log_from_thread(f"📥 Прием файла: {filename} ({filesize} байт)")

        receive_dir = portal_config.load_receive_dir()
        try:
            receive_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self._log_from_thread(f"❌ Не удалось создать папку приёма {receive_dir}: {e}")
            try:
                _portal_sendall(client_socket, b"ERR")
            except Exception:
                pass
            return

        filepath = receive_dir / filename
        recv_chunk = 65536

        try:
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
                    chunk = client_socket.recv(min(recv_chunk, remaining))
                    if not chunk:
                        raise OSError("соединение закрыто до конца файла")
                    f.write(chunk)
                    remaining -= len(chunk)

            self._log_from_thread(f"✅ Файл сохранен: {filepath}")
            refresh_windows_shell_after_new_file(filepath)
            _portal_sendall(client_socket, b"OK")
        except Exception as e:
            self._log_from_thread(f"❌ Ошибка приёма файла «{filename}»: {e}")
            try:
                if filepath.exists():
                    filepath.unlink(missing_ok=True)  # type: ignore[arg-type]
            except Exception:
                pass
            try:
                _portal_sendall(client_socket, b"ERR")
            except Exception:
                pass

    def receive_clipboard_files(
        self,
        client_socket: socket.socket,
        message: dict,
        prefix: bytes = b"",
    ) -> None:
        """Несколько файлов из буфера (Ctrl+Alt+C) — сохранить и положить в буфер получателя."""
        specs = message.get("files") or []
        if not specs:
            self._log_from_thread("⚠️ clipboard_files: пустой список")
            try:
                _portal_sendall(client_socket, b"ERR")
            except Exception:
                pass
            return

        save_dir = portal_config.incoming_clipboard_files_save_dir()
        try:
            save_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self._log_from_thread(f"❌ Папка для приёма файлов из буфера: {e}")
            try:
                _portal_sendall(client_socket, b"ERR")
            except Exception:
                pass
            return

        saved: List[str] = []
        buf = prefix
        try:
            for spec in specs:
                raw_name = spec.get("filename", "file")
                filename = _safe_receive_filename(str(raw_name))
                filesize = int(spec.get("filesize", 0))
                unique = save_dir / f"{int(time.time() * 1000)}_{filename}"
                with open(unique, "wb") as f:
                    remaining = filesize
                    while remaining > 0:
                        if buf:
                            take = min(len(buf), remaining)
                            f.write(buf[:take])
                            buf = buf[take:]
                            remaining -= take
                            continue
                        chunk = client_socket.recv(min(65536, remaining))
                        if not chunk:
                            raise OSError(
                                "соединение закрыто до конца файла (clipboard_files)"
                            )
                        f.write(chunk)
                        remaining -= len(chunk)
                saved.append(str(unique.resolve()))
                refresh_windows_shell_after_new_file(unique)
            _portal_sendall(client_socket, b"OK")
        except Exception as e:
            self._log_from_thread(f"❌ Приём clipboard_files: {e}")
            try:
                _portal_sendall(client_socket, b"ERR")
            except Exception:
                pass
            return

        self._log_from_thread(f"✅ Из буфера сохранено файлов: {len(saved)}")
        try:
            self.after(
                0,
                lambda paths=list(saved): self._apply_incoming_clipboard_files(paths),
            )
        except Exception:
            pass

    def receive_clipboard_rich(
        self,
        client_socket: socket.socket,
        message: dict,
        prefix: bytes = b"",
    ) -> None:
        """Картинка из буфера: JSON + сырые байты PNG."""
        size = int(message.get("size", 0))
        if not portal_clip_rich.image_size_ok(size):
            self._log_from_thread("⚠️ Слишком большой снимок буфера")
            try:
                _portal_sendall(client_socket, b"ERR")
            except Exception:
                pass
            return

        receive_dir = portal_config.load_receive_dir()
        try:
            receive_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self._log_from_thread(f"❌ Папка приёма: {e}")
            try:
                _portal_sendall(client_socket, b"ERR")
            except Exception:
                pass
            return

        out_path = receive_dir / f"portal_clipboard_{int(time.time() * 1000)}.png"
        buf = prefix
        try:
            with open(out_path, "wb") as f:
                remaining = size
                while remaining > 0:
                    if buf:
                        take = min(len(buf), remaining)
                        f.write(buf[:take])
                        buf = buf[take:]
                        remaining -= take
                        continue
                    chunk = client_socket.recv(min(65536, remaining))
                    if not chunk:
                        raise OSError(
                            "соединение закрыто до конца картинки (clipboard_rich)"
                        )
                    f.write(chunk)
                    remaining -= len(chunk)
            _portal_sendall(client_socket, b"OK")
        except Exception as e:
            self._log_from_thread(f"❌ Приём картинки из буфера: {e}")
            try:
                _portal_sendall(client_socket, b"ERR")
            except Exception:
                pass
            return

        refresh_windows_shell_after_new_file(out_path)
        self._log_from_thread(f"✅ Картинка из буфера сохранена: {out_path.name}")
        p = str(out_path.resolve())
        try:
            self.after(0, lambda path=p: self._apply_incoming_clipboard_image(path))
        except Exception:
            pass

    def _apply_incoming_clipboard_files(self, paths: List[str]) -> None:
        self.is_receiving_clipboard = True
        try:
            mode = portal_config.load_incoming_clipboard_files_mode()
            msg = ""
            if mode in ("clipboard", "both"):
                msg = portal_clip_rich.apply_clipboard_payload(
                    "files", file_paths=paths
                )
                try:
                    self.last_clipboard = "\n".join(paths)
                except Exception:
                    pass

            if mode == "disk":
                self.log(
                    f"📁 Из буфера: {len(paths)} файл(ов) в папке приёма — "
                    "в системный буфер не кладём (режим «только папка»)"
                )
            elif mode == "clipboard":
                self.log(f"📋 {msg} — Cmd+V / Ctrl+V")
            else:
                self.log(f"📁 + 📋 {msg} — Cmd+V / Ctrl+V")
        finally:
            self.is_receiving_clipboard = False

    def _apply_incoming_clipboard_image(self, path: str) -> None:
        self.is_receiving_clipboard = True
        try:
            msg = portal_clip_rich.apply_clipboard_payload("image", image_path=path)
            self.log(f"📋 {msg} — Ctrl+V")
        finally:
            self.is_receiving_clipboard = False
    
    def receive_clipboard(self, message: dict):
        """Прием буфера обмена (push с другого ПК) — вставка на главном потоке."""
        clipboard_text = message.get("text", "")
        if clipboard_text:
            def _paste():
                self.is_receiving_clipboard = True
                try:
                    pyperclip.copy(clipboard_text)
                    self.last_clipboard = clipboard_text
                finally:
                    self.is_receiving_clipboard = False
            try:
                self.after(0, _paste)
            except Exception:
                _paste()
            self._log_from_thread(
                f"📋 Буфер обмена обновлен ({len(clipboard_text)} символов) — Ctrl+V для вставки"
            )
    
    def send_clipboard_response(self, client_socket: socket.socket):
        """Ответ на get_clipboard: текст, файлы или картинка — как в локальном буфере."""
        try:
            kind, payload = portal_clip_rich.clipboard_snapshot()
            if kind == "empty":
                resp = json.dumps({"type": "clipboard", "text": ""}, ensure_ascii=False)
                _portal_sendall(client_socket, resp.encode("utf-8"))
                self._log_from_thread("📋 По запросу: буфер пуст")
                return
            if kind == "text":
                t = payload.get("text", "") or ""
                resp = json.dumps({"type": "clipboard", "text": t}, ensure_ascii=False)
                _portal_sendall(client_socket, resp.encode("utf-8"))
                self._log_from_thread(
                    f"📋 Отправлен буфер по запросу (текст, {len(t)} симв.)"
                )
                return
            if kind == "files":
                paths = payload.get("paths") or []
                valid_paths = [p for p in paths if os.path.isfile(p)]
                if not valid_paths:
                    t = ""
                    try:
                        t = pyperclip.paste() or ""
                    except Exception:
                        pass
                    resp = json.dumps({"type": "clipboard", "text": t or ""}, ensure_ascii=False)
                    _portal_sendall(client_socket, resp.encode("utf-8"))
                    self._log_from_thread(
                        "📋 По запросу: в буфере не удалось прочитать файлы → отправлен текст"
                    )
                    return
                specs = [
                    {"filename": os.path.basename(p), "filesize": os.path.getsize(p)}
                    for p in valid_paths
                ]
                header = {"type": "clipboard_files", "files": specs}
                _portal_sendall(
                    client_socket,
                    json.dumps(header, ensure_ascii=False).encode("utf-8"),
                )
                time.sleep(0.05)
                for p in valid_paths:
                    with open(p, "rb") as f:
                        while True:
                            chunk = f.read(65536)
                            if not chunk:
                                break
                            _portal_sendall(client_socket, chunk)
                okp = _recv_ok_prefix(client_socket, timeout=180.0)
                self._log_from_thread(
                    f"📋 По запросу отправлено {len(valid_paths)} файл(ов); ответ: {okp[:32]!r}"
                )
                return
            if kind == "image":
                image_bytes = payload.get("image_bytes") or b""
                if not portal_clip_rich.image_size_ok(len(image_bytes)):
                    resp = json.dumps({"type": "clipboard", "text": ""}, ensure_ascii=False)
                    _portal_sendall(client_socket, resp.encode("utf-8"))
                    self._log_from_thread(
                        "⚠️ По запросу: картинка слишком большая → отправлен пустой текст"
                    )
                    return
                mime = payload.get("mime", "image/png")
                hdr = {
                    "type": "clipboard_rich",
                    "clip_kind": "image",
                    "mime": mime,
                    "size": len(image_bytes),
                }
                _portal_sendall(
                    client_socket,
                    json.dumps(hdr, ensure_ascii=False).encode("utf-8"),
                )
                time.sleep(0.05)
                _portal_sendall(client_socket, image_bytes)
                okp = _recv_ok_prefix(client_socket, timeout=180.0)
                self._log_from_thread(
                    f"📋 По запросу отправлена картинка; ответ: {okp[:32]!r}"
                )
                return
            resp = json.dumps({"type": "clipboard", "text": ""}, ensure_ascii=False)
            _portal_sendall(client_socket, resp.encode("utf-8"))
            self._log_from_thread("📋 По запросу: неизвестный тип снимка → пустой текст")
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
    
    def _try_begin_clipboard_wave(self) -> bool:
        with self._clipboard_push_lock:
            if self._clipboard_push_wave_active:
                return False
            self._clipboard_push_wave_active = True
            return True

    def _end_clipboard_wave(self) -> None:
        with self._clipboard_push_lock:
            self._clipboard_push_wave_active = False

    def push_shared_clipboard_hotkey(self):
        """Ctrl+Alt+C / Cmd+Shift+C — отправить локальный буфер на все сохранённые ПК"""
        ips = self.get_target_ips()
        if not ips:
            self.log("⚠️ Сначала укажите IP выше и нажмите «Сохранить IP»")
            return
        if not self._try_begin_clipboard_wave():
            self.log("⏸ Буфер уже отправляется, дождитесь окончания")
            return

        def _wave():
            try:
                for ip in ips:
                    self.send_clipboard(ip)
            finally:
                self._end_clipboard_wave()

        threading.Thread(target=_wave, daemon=True).start()

    def pull_shared_clipboard_hotkey(self):
        """Ctrl+Alt+V / Cmd+Shift+V / Cmd+Option+V — забрать буфер с первого сохранённого ПК"""
        ips = self.get_target_ips()
        if not ips:
            self.log("⚠️ Сначала укажите IP выше и нажмите «Сохранить IP»")
            return
        if not self._clipboard_pull_lock.acquire(blocking=False):
            self.log("⏸ Уже выполняется запрос буфера с пира, подождите")
            return

        def _worker():
            try:
                self._pull_clipboard_worker(ips[0])
            finally:
                self._clipboard_pull_lock.release()

        threading.Thread(target=_worker, daemon=True).start()

    def _pull_clipboard_worker(self, target_ip: str):
        """Запрос буфера с удалённой машины (сервер должен слушать :PORT)."""
        def _log(msg: str):
            try:
                self.after(0, lambda m=msg: self.log(m))
            except Exception:
                print(msg)

        client_socket: Optional[socket.socket] = None
        try:
            _log(f"📥 Запрос буфера с {target_ip}...")
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.settimeout(15.0)
            client_socket.connect((target_ip, PORTAL_PORT))
            _log(f"✅ Подключение установлено: {target_ip}:{PORTAL_PORT}")
            client_socket.settimeout(None)
            _portal_sendall(
                client_socket,
                json.dumps({"type": "get_clipboard"}).encode("utf-8"),
            )

            message, tail = read_first_json_from_stream(client_socket)
            if not message:
                raise ValueError("Пустой ответ или обрыв заголовка")

            mtype = message.get("type")
            if mtype == "clipboard":
                text = message.get("text", "")

                def _paste_on_main():
                    self.is_receiving_clipboard = True
                    try:
                        pyperclip.copy(text)
                        self.last_clipboard = text
                    finally:
                        self.is_receiving_clipboard = False

                try:
                    self.after(0, _paste_on_main)
                except Exception:
                    _paste_on_main()
                _log(
                    f"📋 Текст с удалённого ПК ({len(text)} символов) — Ctrl+V / Cmd+V"
                )
                return

            if mtype == "clipboard_files":
                self.receive_clipboard_files(client_socket, message, prefix=tail)
                _log("📋 Файлы с удалённого ПК получены — вставь через Ctrl+V / Cmd+V (см. строки выше)")
                return

            if mtype == "clipboard_rich":
                self.receive_clipboard_rich(client_socket, message, prefix=tail)
                _log("📋 Картинка с удалённого ПК получена — см. журнал выше")
                return

            _log(f"⚠️ Неожиданный ответ при запросе буфера: {mtype!r}")
        except ConnectionRefusedError:
            _log(
                "❌ Порт не принимает соединение (Windows: ошибка 10061). "
                "Это не «вопрос разрешения» — на том ПК просто не запущен приём: "
                "открой Портал и нажми «Запустить портал», проверь IP и файрвол."
            )
        except OSError as e:
            winerr = getattr(e, "winerror", None)
            errno_val = getattr(e, "errno", None)
            if winerr == 10061 or errno_val == 10061:
                _log(
                    "❌ Подключение отклонено (10061): на удалённом ПК не слушает Портал "
                    f"или неверный адрес. {e}"
                )
            elif winerr == 10054:
                _log(f"❌ Соединение сброшено (10054): {e}")
            else:
                _log(f"❌ Сеть: {e}")
        except Exception as e:
            _log(f"❌ Не удалось получить буфер: {str(e)}")
        finally:
            if client_socket is not None:
                try:
                    client_socket.close()
                except Exception:
                    pass
    
    def send_file_dialog(self):
        """Выбор файла; отправка на все сохранённые IP."""
        from tkinter import filedialog
        self.log("📂 Открыт диалог выбора файла...")
        filepath = filedialog.askopenfilename(
            title="Выберите файл для отправки"
        )
        if not filepath:
            self.log("❌ Файл не выбран (отменено)")
            return
        self.log(f"✅ Файл выбран: {Path(filepath).name} ({Path(filepath).stat().st_size / 1024 / 1024:.2f} MB)")
        ips = self.get_target_ips()
        if ips:
            self.log(f"📤 Отправка на {len(ips)} ПК: {', '.join(ips)}")
            for ip in ips:
                threading.Thread(
                    target=self.send_file,
                    args=(filepath, ip),
                    daemon=True,
                ).start()
        else:
            self.log("⚠️ Сначала укажите IP выше и нажмите «Сохранить IP»")
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
        """Отправка буфера на все сохранённые IP."""
        ips = self.get_target_ips()
        if ips:
            if not self._try_begin_clipboard_wave():
                self.log("⏸ Буфер уже отправляется, дождитесь окончания")
                return

            def _wave():
                try:
                    for ip in ips:
                        self.send_clipboard(ip)
                finally:
                    self._end_clipboard_wave()

            threading.Thread(target=_wave, daemon=True).start()
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
        client_socket: Optional[socket.socket] = None
        try:
            self.log(f"📤 Отправка файла на {target_ip}...")

            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.settimeout(10.0)
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

            # После connect — длинный таймаут на передачу и ожидание OK
            client_socket.settimeout(None)

            filename = os.path.basename(filepath)
            filesize = os.path.getsize(filepath)

            message = {
                "type": "file",
                "filename": filename,
                "filesize": filesize,
            }
            _portal_sendall(
                client_socket,
                json.dumps(message, ensure_ascii=False).encode("utf-8"),
            )
            time.sleep(0.05)

            with open(filepath, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    _portal_sendall(client_socket, chunk)

            response = _recv_ok_prefix(client_socket, timeout=180.0)
            if response.startswith(b"OK") or response.lstrip().startswith(b"OK"):
                self.log(f"✅ Файл успешно отправлен: {filename}")
            else:
                self.log(f"⚠️ Ответ приёма файла: {response!r}")

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
        finally:
            if client_socket is not None:
                try:
                    client_socket.close()
                except Exception:
                    pass
    
    def _clipboard_connect(self, target_ip: str, timeout: float = 120.0):
        """TCP к пиру: короткий connect, затем без таймаута на передачу (как send_file)."""
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.settimeout(min(15.0, timeout))
        client_socket.connect((target_ip, PORTAL_PORT))
        client_socket.settimeout(None)
        return client_socket

    def _send_clipboard_text_only(self, target_ip: str, clipboard_text: str) -> None:
        client_socket = self._clipboard_connect(target_ip, 30.0)
        try:
            message = {"type": "clipboard", "text": clipboard_text}
            _portal_sendall(
                client_socket,
                json.dumps(message, ensure_ascii=False).encode("utf-8"),
            )
        finally:
            client_socket.close()
        self.log(f"✅ Текст отправлен на {target_ip} ({len(clipboard_text)} симв.)")

    def _send_clipboard_image_payload(self, target_ip: str, image_bytes: bytes, mime: str) -> None:
        if not portal_clip_rich.image_size_ok(len(image_bytes)):
            self.log("⚠️ Картинка в буфере слишком большая для Портала (лимит ~48 МБ)")
            return
        self.log(f"📤 Отправка картинки из буфера на {target_ip} ({len(image_bytes) // 1024} КБ)…")
        client_socket = self._clipboard_connect(target_ip, 180.0)
        try:
            header = {
                "type": "clipboard_rich",
                "clip_kind": "image",
                "mime": mime or "image/png",
                "size": len(image_bytes),
            }
            _portal_sendall(
                client_socket,
                json.dumps(header, ensure_ascii=False).encode("utf-8"),
            )
            time.sleep(0.05)
            _portal_sendall(client_socket, image_bytes)
            resp = _recv_ok_prefix(client_socket, timeout=180.0)
            if not (resp.startswith(b"OK") or resp.lstrip().startswith(b"OK")):
                self.log(f"⚠️ Ответ приёма картинки: {resp!r}")
            else:
                self.log(f"✅ Картинка из буфера доставлена на {target_ip}")
        finally:
            client_socket.close()

    def _send_clipboard_files_bundle(self, target_ip: str, paths: List[str]) -> None:
        valid_paths = [p for p in paths if os.path.isfile(p)]
        specs = [
            {"filename": os.path.basename(p), "filesize": os.path.getsize(p)}
            for p in valid_paths
        ]
        if not specs:
            self.log("⚠️ Нет файлов для отправки из буфера")
            return
        self.log(
            f"📤 Отправка {len(specs)} файл(ов) из буфера на {target_ip}…"
        )
        client_socket = self._clipboard_connect(target_ip, 600.0)
        try:
            header = {"type": "clipboard_files", "files": specs}
            _portal_sendall(
                client_socket,
                json.dumps(header, ensure_ascii=False).encode("utf-8"),
            )
            time.sleep(0.05)
            for p in valid_paths:
                with open(p, "rb") as f:
                    while True:
                        chunk = f.read(65536)
                        if not chunk:
                            break
                        _portal_sendall(client_socket, chunk)
            resp = _recv_ok_prefix(client_socket, timeout=180.0)
            if not (resp.startswith(b"OK") or resp.lstrip().startswith(b"OK")):
                self.log(f"⚠️ Ответ приёма файлов: {resp!r}")
            else:
                self.log(f"✅ Файлы из буфера доставлены на {target_ip}")
        finally:
            client_socket.close()

    def send_clipboard(self, target_ip: str):
        """Отправка буфера: текст / картинка / файлы (Ctrl+Alt+C)."""
        try:
            kind, payload = portal_clip_rich.clipboard_snapshot()
            if kind == "empty":
                self.log("⚠️ Буфер пуст (нет текста, картинки и файлов)")
                return

            self.log(f"📤 Буфер → {target_ip} (тип: {kind})…")

            if kind == "files":
                self._send_clipboard_files_bundle(target_ip, payload["paths"])
                return
            if kind == "image":
                self._send_clipboard_image_payload(
                    target_ip,
                    payload["image_bytes"],
                    payload.get("mime", "image/png"),
                )
                return
            if kind == "text":
                self._send_clipboard_text_only(target_ip, payload["text"])
                return

        except (socket.timeout, ConnectionRefusedError, OSError) as e:
            if isinstance(e, socket.timeout):
                self.log(f"❌ Таймаут подключения к {target_ip}")
            elif isinstance(e, ConnectionRefusedError):
                self.log(f"❌ Портал на {target_ip} не запущен")
                self.log("💡 На том ПК нажми «Запустить портал»")
            else:
                self.log(f"❌ Сеть: {target_ip} — {e}")
        except Exception as e:
            err_msg = str(e)
            if "timed out" in err_msg.lower():
                self.log(f"❌ Таймаут: {target_ip}")
            elif "refused" in err_msg.lower():
                self.log(f"❌ Подключение отклонено: {target_ip}")
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
                    if self.sync_clipboard_enabled:
                        ips = self.get_target_ips()
                        if ips:
                            if not self._try_begin_clipboard_wave():
                                pass
                            else:

                                def _auto_wave():
                                    try:
                                        for ip in ips:
                                            self.send_clipboard(ip)
                                    finally:
                                        self._end_clipboard_wave()

                                threading.Thread(
                                    target=_auto_wave, daemon=True
                                ).start()
        except Exception:
            pass
        self.after(1000, self._clipboard_tick)


if __name__ == "__main__":
    import sys
    import os

    # По умолчанию ВСЕГДА запускаем виджет (если не указан --no-widget)
    show_widget = "--no-widget" not in sys.argv and "-nw" not in sys.argv
    # Сразу показать графический портал (без хоткея) — для проверки и отладки
    show_portal_on_start = (
        "--show-portal" in sys.argv
        or "-sp" in sys.argv
        or os.environ.get("PORTAL_SHOW_ON_START", "").strip().lower() in ("1", "true", "yes")
    )

    app = PortalApp()

    # Виджет запускается всегда (если не отключен явно)
    if show_widget:
        from portal_widget import PortalWidget, GlobalHotkeyManager, debug_log_path

        app.log(f"📝 Лог хоткеев (файл): {debug_log_path()}")
        try:
            app.update_idletasks()

            widget = PortalWidget(app)
            hk = GlobalHotkeyManager(widget, app)
            app.portal_widget_ref = widget
            app._hotkey_mgr = hk
            hk.start()
            widget.root.withdraw()
            if show_portal_on_start:

                def _auto_show_portal():
                    try:
                        widget.show()
                        app.log("🌀 Графический портал открыт (режим --show-portal / PORTAL_SHOW_ON_START=1)")
                    except Exception as ex:
                        app.log(f"❌ Не удалось показать портал: {ex}")

                app.after(200, _auto_show_portal)
                app.log(
                    "✅ Через ~0.2 с откроется виджет-портал (тест/отладка). "
                    "Обычный запуск без флага — Ctrl+Alt+P / Win+Shift+P / Ctrl+Shift+Alt+P."
                )
            else:
                app.log("✅ Виджет скрыт по умолчанию — Ctrl+Alt+P (Win) / Cmd+Option+P (Mac) чтобы показать")
            app.log("💡 IP других ПК — поле выше → «Сохранить IP»")
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
