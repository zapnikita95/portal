"""
Портал - приложение для передачи файлов и синхронизации буфера обмена
через Tailscale сеть с красивым UI в стиле портала
"""

import sys
import os

# Проверка версии Python (один раз за процесс)
if sys.version_info >= (3, 13) and not os.environ.get("_PORTAL_PY313_WARN_DONE"):
    os.environ["_PORTAL_PY313_WARN_DONE"] = "1"
    print("⚠️  Python 3.13+ обнаружен. Некоторые библиотеки могут работать нестабильно.")
    print("   Рекомендуется Python 3.11 или 3.12 для стабильности.")
    print("   Если видите ошибки, попробуйте: pyenv install 3.12.7 && pyenv local 3.12.7\n")

import customtkinter as ctk
import socket
import threading
import json
import shutil
import pyperclip
import time
import io
import struct
import ctypes
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Any, Callable
import subprocess
import platform
import queue

import portal_config
import portal_clipboard_rich as portal_clip_rich
from portal_tk_compat import ensure_tkdnd_tk_misc_patch


def refresh_windows_shell_after_new_file(filepath: Path) -> None:
    """Подтолкнуть Explorer обновить список (только Windows)."""
    if platform.system() != "win32":
        return
    try:
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
# Один файл из буфера удалённого ПК по get_clipboard (не гоняем гигабайты по TCP)
CLIPBOARD_PULL_FILE_MAX_BYTES = 100 * 1024 * 1024


def set_system_clipboard_png(png_bytes: bytes) -> bool:
    """Положить PNG в системный буфер (macOS / Windows)."""
    if not png_bytes:
        return False
    try:
        if platform.system() == "Darwin":
            from AppKit import NSPasteboard
            from Foundation import NSData

            pboard = NSPasteboard.generalPasteboard()
            pboard.clearContents()
            data = NSData.dataWithBytes_length_(png_bytes, len(png_bytes))
            return bool(pboard.setData_forType_(data, "public.png"))
        if platform.system() == "win32":
            import win32clipboard
            from PIL import Image

            im = Image.open(io.BytesIO(png_bytes)).convert("RGB")
            out = io.BytesIO()
            im.save(out, "BMP")
            dib = out.getvalue()[14:]
            win32clipboard.OpenClipboard(0)
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32clipboard.CF_DIB, dib)
            finally:
                win32clipboard.CloseClipboard()
            return True
    except Exception:
        pass
    return False


def set_system_clipboard_file_paths(paths: List[str]) -> bool:
    """Один или несколько файлов в буфере как «скопированные файлы»."""
    clean = [str(Path(p).resolve()) for p in paths if p and Path(p).is_file()]
    if not clean:
        return False
    try:
        if platform.system() == "Darwin":
            from AppKit import NSURL, NSPasteboard

            urls = [NSURL.fileURLWithPath_(p) for p in clean]
            pb = NSPasteboard.generalPasteboard()
            pb.clearContents()
            return bool(pb.writeObjects_(urls))
        if platform.system() == "win32":
            import win32clipboard

            # UTF-16-LE, двойной \0 в конце списка
            payload = "\0".join(clean) + "\0\0"
            blob = payload.encode("utf-16-le")
            # DROPFILES: pFiles, pt.x, pt.y, fNC, fWide (UTF-16 имена)
            off = 20
            header = struct.pack("<IiiII", off, 0, 0, 0, 1)
            hdrop = header + blob
            gmem = ctypes.windll.kernel32.GlobalAlloc(0x2000, len(hdrop))  # GMEM_MOVEABLE
            if not gmem:
                return False
            ptr = ctypes.windll.kernel32.GlobalLock(gmem)
            if not ptr:
                ctypes.windll.kernel32.GlobalFree(gmem)
                return False
            try:
                ctypes.memmove(ptr, hdrop, len(hdrop))
            finally:
                ctypes.windll.kernel32.GlobalUnlock(gmem)
            win32clipboard.OpenClipboard(0)
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32clipboard.CF_HDROP, gmem)
            except Exception:
                ctypes.windll.kernel32.GlobalFree(gmem)
                raise
            finally:
                win32clipboard.CloseClipboard()
            return True
    except Exception:
        pass
    return False


def set_system_clipboard_image_from_file(filepath: Path) -> bool:
    """Картинка из файла → буфер (для приёма PNG/JPEG/WebP и т.д.)."""
    fp = Path(filepath)
    if not fp.is_file():
        return False
    suf = fp.suffix.lower()
    try:
        if suf in (".png",) and platform.system() == "Darwin":
            data = fp.read_bytes()
            return set_system_clipboard_png(data)
        from PIL import Image

        im = Image.open(fp).convert("RGBA")
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        return set_system_clipboard_png(buf.getvalue())
    except Exception:
        return False


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

    Важно: нельзя считать «{»/«}» вручную — в имени файла может быть «}» (например doc}.txt),
    тогда ломался разбор, файл не принимался, отправитель получал пустой ответ.
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
    if not isinstance(obj, dict):
        return None, 0
    consumed = s[:end_char].encode("utf-8")
    return obj, len(consumed)


def _portal_sendall(sock: socket.socket, data: bytes) -> None:
    """Полная отправка (на Windows send() может отдать только часть)."""
    if data:
        sock.sendall(data)


def _safe_incoming_filename(name: Any) -> str:
    """Безопасное имя файла при приёме (Windows / кроссплатформа)."""
    s = os.path.basename(str(name or "") or "received_file") or "received_file"
    for c in '<>:"/\\|?*\x00':
        s = s.replace(c, "_")
    s = s.strip(" .")
    if not s or s in (".", ".."):
        s = "received_file"
    stem = Path(s).stem.upper()
    if sys.platform == "win32" and stem in (
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "COM2",
        "COM3",
        "COM4",
        "COM5",
        "COM6",
        "COM7",
        "COM8",
        "COM9",
        "LPT1",
        "LPT2",
        "LPT3",
        "LPT4",
        "LPT5",
        "LPT6",
        "LPT7",
        "LPT8",
        "LPT9",
    ):
        s = f"_{s}"
    return s


def _recv_ok_prefix(
    sock: socket.socket, max_total: int = 64, timeout: Optional[float] = None
) -> bytes:
    """Прочитать ответ получателя до OK или закрытия (короткий ответ)."""
    old: Optional[float] = None
    try:
        if timeout is not None:
            old = sock.gettimeout()
            sock.settimeout(timeout)
        buf = b""
        while len(buf) < max_total:
            chunk = sock.recv(max(8, max_total - len(buf)))
            if not chunk:
                break
            buf += chunk
            if buf.startswith(b"OK"):
                break
        return buf
    finally:
        if timeout is not None and old is not None:
            try:
                sock.settimeout(old)
            except OSError:
                pass


def read_first_json_from_socket(
    sock: socket.socket, max_header_bytes: int = 1_048_576
) -> Tuple[Optional[dict], bytes]:
    """
    Читать из сокета до первого полного JSON-объекта (ping / file / clipboard).
    TCP может разрезать заголовок между пакетами — один recv(65536) тогда ломает приём.
    """
    buf = b""
    while True:
        msg, json_end = parse_first_json_object_bytes(buf)
        if msg is not None:
            return msg, buf[json_end:]
        if len(buf) >= max_header_bytes:
            return None, buf
        chunk = sock.recv(65536)
        if not chunk:
            return (None, buf)
        buf += chunk


def read_one_json_object_from_socket(
    sock: socket.socket, max_buf: int = 4_194_304
) -> Tuple[dict, bytes]:
    """
    Первый полный JSON в TCP-потоке + «хвост» после него.
    Для get_clipboard: сервер раньше слал текст без \\n — клиент ждал \\n и падал.
    """
    buf = b""
    while True:
        msg, end = parse_first_json_object_bytes(buf)
        if msg is not None:
            if not isinstance(msg, dict):
                raise ValueError("Ответ не JSON-объект")
            return msg, buf[end:]
        if len(buf) >= max_buf:
            raise ValueError("Слишком длинный ответ сервера")
        chunk = sock.recv(65536)
        if not chunk:
            raise ValueError("Пустой или неполный ответ")
        buf += chunk


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
        # Первый IP из списка (совместимость с виджетом / старым кодом)
        self.remote_peer_ip: Optional[str] = portal_config.load_remote_ip()
        self._clip_batch_lock = threading.Lock()
        self._clip_batches: Dict[str, Dict[str, Any]] = {}
        self._peer_checkbox_vars: Dict[str, Any] = {}
        # Один push буфера за раз (двойной хоткей / два источника событий)
        self._clipboard_push_lock = threading.Lock()
        self._clipboard_pull_lock = threading.Lock()
        # После записи файлов в буфер pyperclip часто пустой — не дергать sync по ложному «изменению»
        self._clipboard_ignore_until = 0.0
        # pynput / windnd — только put в очередь; разбор на главном потоке Tk
        self._ui_signal_queue: queue.SimpleQueue = queue.SimpleQueue()
        self.portal_widget_ref: Optional[Any] = None
        self._hotkey_mgr: Optional[Any] = None
        
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
            text="🖥 IP других компьютеров (Tailscale / LAN) — список, несколько строк:",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", padx=12, pady=(10, 4))
        ctk.CTkLabel(
            peer_frame,
            text="Сохраняется на диск. Ниже отметь галочками, кому слать сразу (файлы, буфер, виджет).",
            font=ctk.CTkFont(size=11),
            text_color="gray",
        ).pack(anchor="w", padx=12, pady=(0, 4))
        ctk.CTkLabel(
            peer_frame,
            text=f"💡 Только IP в строке (например 100.65.63.84), порт :{PORTAL_PORT} добавляется сам.",
            font=ctk.CTkFont(size=11),
            text_color="gray70",
        ).pack(anchor="w", padx=12, pady=(0, 8))

        ctk.CTkLabel(
            peer_frame,
            text="📁 Папка для входящих файлов (по умолчанию — Рабочий стол):",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w", padx=12, pady=(4, 2))
        ctk.CTkLabel(
            peer_frame,
            text="К этой папке относятся и файлы из буфера с другого ПК (отправка/забрать буфер), "
            "кроме режима «только в буфер» — там сохранение во временную папку.",
            font=ctk.CTkFont(size=10),
            text_color="gray",
        ).pack(anchor="w", padx=12, pady=(0, 2))
        recv_row = ctk.CTkFrame(peer_frame, fg_color="transparent")
        recv_row.pack(fill="x", padx=12, pady=(0, 8))
        self.receive_dir_entry = ctk.CTkEntry(recv_row, width=360, placeholder_text="~/Desktop")
        self.receive_dir_entry.pack(side="left", padx=(0, 8))
        try:
            self.receive_dir_entry.insert(0, str(portal_config.receive_dir_path()))
        except Exception:
            pass
        ctk.CTkButton(
            recv_row,
            text="Обзор…",
            width=88,
            command=self.choose_receive_dir,
            font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            recv_row,
            text="Сохранить папку",
            width=130,
            command=self.save_receive_dir_from_ui,
            font=ctk.CTkFont(size=12),
        ).pack(side="left")
        self.receive_dir_feedback = ctk.CTkLabel(
            recv_row, text="", font=ctk.CTkFont(size=12), text_color="gray"
        )
        self.receive_dir_feedback.pack(side="left", padx=(8, 0))

        ctk.CTkLabel(
            peer_frame,
            text="Входящие файлы (не «как из буфера» у отправителя — там всегда диск+буфер):",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w", padx=12, pady=(4, 2))
        self._receive_files_mode_labels = {
            "both": "На диск и в буфер (Cmd+V)",
            "disk_only": "Только в папку приёма",
            "clipboard_only": "В буфер (+ файл в папке; без «Показать в Finder»)",
        }
        rm_row = ctk.CTkFrame(peer_frame, fg_color="transparent")
        rm_row.pack(fill="x", padx=12, pady=(0, 6))
        self.receive_mode_menu = ctk.CTkOptionMenu(
            rm_row,
            values=list(self._receive_files_mode_labels.values()),
            command=self._on_receive_files_mode_menu,
            width=420,
            font=ctk.CTkFont(size=12),
        )
        self.receive_mode_menu.pack(side="left", padx=(0, 8))
        cur_m = portal_config.receive_files_mode()
        self.receive_mode_menu.set(self._receive_files_mode_labels.get(cur_m, self._receive_files_mode_labels["both"]))

        ip_edit_row = ctk.CTkFrame(peer_frame, fg_color="transparent")
        ip_edit_row.pack(fill="x", padx=12, pady=(0, 6))
        self.peer_ips_text = ctk.CTkTextbox(ip_edit_row, width=420, height=88, font=ctk.CTkFont(size=13))
        self.peer_ips_text.pack(side="left", padx=(0, 10), anchor="nw")
        self._fill_peer_ips_textbox()
        self.peer_ips_text.bind("<KeyRelease>", self._on_peer_ips_edited)
        btn_col = ctk.CTkFrame(ip_edit_row, fg_color="transparent")
        btn_col.pack(side="left", fill="y")
        ctk.CTkButton(
            btn_col,
            text="Сохранить\nсписок IP",
            width=130,
            command=self.save_peer_ips_from_ui,
            font=ctk.CTkFont(size=12),
        ).pack(pady=(0, 6))
        ctk.CTkButton(
            btn_col,
            text="Сохранить\nвыбор",
            width=130,
            command=self.save_peer_selection_from_ui,
            font=ctk.CTkFont(size=12),
        ).pack()
        self.ip_saved_feedback = ctk.CTkLabel(
            peer_frame,
            text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#3dd68c",
        )
        self.ip_saved_feedback.pack(anchor="w", padx=12, pady=(0, 4))

        if platform.system() == "Darwin":
            _hk = (
                "Cmd+Shift+C"
                if os.environ.get("PORTAL_MAC_HOTKEY_LEGACY", "").strip().lower() in ("1", "true", "yes")
                else "Cmd+Ctrl+C"
            )
        else:
            _hk = "Ctrl+Alt+C"
        ctk.CTkLabel(
            peer_frame,
            text=f"Кому отправлять ({_hk}, файлы, виджет):",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w", padx=12, pady=(4, 2))
        # Одна компактная строка с чекбоксами (без высокого ScrollableFrame)
        self.peer_select_frame = ctk.CTkFrame(peer_frame, fg_color="transparent", height=42)
        self.peer_select_frame.pack(fill="x", padx=12, pady=(0, 4))
        try:
            self.peer_select_frame.pack_propagate(False)
        except Exception:
            pass
        self.rebuild_peer_checkboxes()

        # Подсказки по хоткеям (виджет + общий буфер)
        hotkey_frame = ctk.CTkFrame(peer_frame, fg_color="transparent")
        hotkey_frame.pack(fill="x", padx=12, pady=(0, 10))
        if platform.system() == "Darwin":
            _leg = os.environ.get("PORTAL_MAC_HOTKEY_LEGACY", "").strip().lower() in ("1", "true", "yes")
            if _leg:
                hotkey_text = (
                    "🔑 macOS (режим PORTAL_MAC_HOTKEY_LEGACY=1 — может конфликтовать с Терминалом):\n"
                    "   Портал — Cmd+Option+P\n"
                    "   Отправить буфер — Cmd+Shift+C\n"
                    "   Забрать буфер — Cmd+Shift+V (дубль: Cmd+Option+V, если не занято приложением)\n"
                    "   Русская раскладка — Cmd+Option+з, Cmd+Shift+с / м (дубль: Cmd+Option+м)"
                )
            else:
                hotkey_text = (
                    "🔑 macOS по умолчанию (Cmd+Ctrl — реже лезет в Терминал):\n"
                    "   Показать/скрыть портал — Cmd+Ctrl+P\n"
                    "   Отправить буфер на другие ПК — Cmd+Ctrl+C\n"
                    "   Забрать буфер с первого отмеченного IP — Cmd+Ctrl+V\n"
                    "   Русская раскладка (те же физические клавиши) — Cmd+Ctrl+з / с / м"
                )
            hotkey_text += (
                "\n📌 Забрать буфер = **первый отмеченный IP**. На том ПК в логе будет get_clipboard — это ответ твоему запросу."
                "\n💡 Старые сочетания: экспорт PORTAL_MAC_HOTKEY_LEGACY=1 перед запуском."
            )
            if sys.version_info >= (3, 13):
                hotkey_text += (
                    "\n✅ Python 3.13+: глобальные хоткеи — отдельный процесс pynput (не падает вместе с окном). "
                    "Права: Input Monitoring + Универсальный доступ для Терминала/Python. "
                    "Отключить helper: PORTAL_MAC_NO_HOTKEY_HELPER=1 (только при фокусе на Портале)."
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
            text="⚪ Пары: сохрани список IP и проверь связь",
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
            text=f"авто каждые {PEER_STATUS_POLL_MS // 1000} с, если есть IP",
            font=ctk.CTkFont(size=11),
            text_color="gray",
        ).pack(side="left", padx=(12, 0))
        
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
        self.log_hint_label.pack(fill="x", padx=10, pady=(0, 4))

        log_btn_row = ctk.CTkFrame(log_frame, fg_color="transparent")
        log_btn_row.pack(fill="x", padx=10, pady=(0, 4))
        ctk.CTkButton(
            log_btn_row,
            text="📋 Копировать весь журнал",
            width=200,
            command=self.copy_whole_activity_log,
            font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=(0, 10))
        _lp = portal_config.activity_log_path()
        ctk.CTkLabel(
            log_btn_row,
            text=f"Также пишется в: {_lp}",
            font=ctk.CTkFont(size=11),
            text_color="gray",
            anchor="w",
        ).pack(side="left", fill="x", expand=True)

        self.log_text = ctk.CTkTextbox(log_frame, height=300, wrap="word")
        self.log_text.pack(fill="x", expand=False, padx=10, pady=(0, 10))
        self.log_text.insert("1.0", "Готов к работе...\n")
        self._setup_log_text_selectable()
        self._log_max_lines = 400
        # Cmd/Ctrl+C: копировать выделение или весь журнал (в disabled-текстбоксе своё копирование часто ломается)
        self.log_text.bind("<Command-c>", self._log_copy_selection_hotkey)
        self.log_text.bind("<Control-c>", self._log_copy_selection_hotkey)

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
        ensure_tkdnd_tk_misc_patch()
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
                    if paths:
                        self.log(f"📥 Получено {len(paths)} файл(ов) через drag & drop в главное окно")
                        for fp in paths:
                            if os.path.exists(fp):
                                self.log(f"   📄 {Path(fp).name}")
                                if self.get_target_ips():
                                    for ip in self.get_target_ips():
                                        threading.Thread(
                                            target=self.send_file,
                                            args=(fp, ip),
                                            daemon=True,
                                        ).start()
                                else:
                                    self.log("⚠️ Сначала сохрани список IP и отметь получателей")
                                    self.send_file_to_dialog(fp)

                # windnd работает на Tk окне (CTk наследует Tk)
                windnd.hook_dropfiles(self, on_drop)
                self.log("✅ Drag & Drop включён в главном окне (Windows)")
            except Exception as e:
                self.log(f"⚠️ Drag & Drop (Windows): {e}")
        else:
            try:
                from tkinterdnd2 import TkinterDnD, DND_FILES

                # _require вешает методы на BaseWidget → копируем на Misc (Python 3.13 + CTk).
                TkinterDnD._require(self)
                ensure_tkdnd_tk_misc_patch()
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
                    if self.get_target_ips():
                        for ip in self.get_target_ips():
                            threading.Thread(
                                target=self.send_file,
                                args=(fp, ip),
                                daemon=True,
                            ).start()
                    else:
                        self.log("⚠️ Сначала сохрани список IP и отметь получателей")
                        self.send_file_to_dialog(fp)

    def get_target_ips(self) -> List[str]:
        """IP получателей для одновременной отправки (галочки), без дубликатов."""
        raw = portal_config.load_peer_send_targets()
        seen = set()
        out: List[str] = []
        for x in raw:
            s = str(x).strip()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
        return out

    def _on_peer_ips_edited(self, _event=None):
        if hasattr(self, "ip_saved_feedback"):
            self.ip_saved_feedback.configure(text="")

    def _fill_peer_ips_textbox(self) -> None:
        if not hasattr(self, "peer_ips_text"):
            return
        ips = portal_config.load_peer_ips()
        self.peer_ips_text.delete("1.0", "end")
        self.peer_ips_text.insert("1.0", "\n".join(ips) if ips else "")

    def save_peer_ips_from_ui(self) -> None:
        raw = self.peer_ips_text.get("1.0", "end") if hasattr(self, "peer_ips_text") else ""
        lines = [ln.strip() for ln in raw.replace("\r", "").split("\n")]
        ips = [x for x in lines if x]
        if hasattr(self, "ip_saved_feedback"):
            self.ip_saved_feedback.configure(text="⏳ …", text_color="gray")
        ok = portal_config.save_peer_ips(ips)
        self.remote_peer_ip = portal_config.load_remote_ip()
        if ok:
            self.log(f"💾 Список IP сохранён ({len(ips)}): {', '.join(ips) or '(пусто)'}")
            if hasattr(self, "ip_saved_feedback"):
                self.ip_saved_feedback.configure(text="✅ Список сохранён", text_color="#3dd68c")
            self.rebuild_peer_checkboxes()
            self.check_peer_connection_async(silent=False)
            self._arm_peer_poll()
        else:
            self.log("❌ Не удалось сохранить список IP")
            if hasattr(self, "ip_saved_feedback"):
                self.ip_saved_feedback.configure(text="❌ Ошибка записи", text_color="#e74c3c")

    def rebuild_peer_checkboxes(self) -> None:
        if not hasattr(self, "peer_select_frame"):
            return
        for w in self.peer_select_frame.winfo_children():
            w.destroy()
        self._peer_checkbox_vars.clear()
        ips = portal_config.load_peer_ips()
        targets_set = set(portal_config.load_peer_send_targets())
        if not ips:
            ctk.CTkLabel(
                self.peer_select_frame,
                text="Добавь IP выше → «Сохранить список IP»",
                font=ctk.CTkFont(size=11),
                text_color="gray",
            ).pack(side="left", padx=4, pady=4)
            return
        row = ctk.CTkFrame(self.peer_select_frame, fg_color="transparent")
        row.pack(fill="x", pady=2)
        for ip in ips:
            var = ctk.BooleanVar(value=ip in targets_set)
            self._peer_checkbox_vars[ip] = var
            ctk.CTkCheckBox(
                row,
                text=ip,
                variable=var,
                font=ctk.CTkFont(size=11),
            ).pack(side="left", padx=(0, 16), pady=0)

    def save_peer_selection_from_ui(self) -> None:
        ips = portal_config.load_peer_ips()
        chosen = [ip for ip in ips if self._peer_checkbox_vars.get(ip) and self._peer_checkbox_vars[ip].get()]
        if not chosen:
            self.log("⚠️ Отметь хотя бы один IP или сохрани список IP")
            if hasattr(self, "ip_saved_feedback"):
                self.ip_saved_feedback.configure(text="❌ Нет галочек", text_color="#e74c3c")
            return
        portal_config.save_peer_send_targets(chosen)
        self.log(f"💾 Отправка на выбранные ПК: {', '.join(chosen)}")
        if hasattr(self, "ip_saved_feedback"):
            self.ip_saved_feedback.configure(text="✅ Выбор сохранён", text_color="#3dd68c")
        self.check_peer_connection_async(silent=False)

    def _on_receive_files_mode_menu(self, choice: str) -> None:
        rev = {v: k for k, v in getattr(self, "_receive_files_mode_labels", {}).items()}
        key = rev.get(choice, "both")
        if portal_config.save_receive_files_mode(key):
            self.log(f"💾 Входящие файлы: {choice}")
        else:
            self.log("⚠️ Не удалось сохранить режим приёма")

    def choose_receive_dir(self) -> None:
        """Диалог выбора папки приёма (кнопка «Обзор…»)."""
        from tkinter import filedialog

        if not hasattr(self, "receive_dir_entry"):
            return
        cur = self.receive_dir_entry.get().strip()
        initial = cur if cur and os.path.isdir(cur) else str(portal_config.receive_dir_path())
        d = filedialog.askdirectory(title="Папка для входящих файлов", initialdir=initial)
        if d:
            self.receive_dir_entry.delete(0, "end")
            self.receive_dir_entry.insert(0, d)

    def save_receive_dir_from_ui(self):
        """Сохранить папку для входящих файлов (пусто = только рабочий стол по умолчанию)."""
        raw = self.receive_dir_entry.get().strip() if hasattr(self, "receive_dir_entry") else ""
        ok = portal_config.save_receive_dir(raw)
        if ok:
            p = portal_config.receive_dir_path()
            self.log(f"✅ Папка для входящих: {p}")
            if hasattr(self, "receive_dir_feedback"):
                self.receive_dir_feedback.configure(text="✅ OK", text_color="#3dd68c")
            try:
                self.receive_dir_entry.delete(0, "end")
                self.receive_dir_entry.insert(0, str(p))
            except Exception:
                pass
        else:
            self.log("❌ Не удалось сохранить папку (проверь путь и права)")
            if hasattr(self, "receive_dir_feedback"):
                self.receive_dir_feedback.configure(text="❌ Ошибка", text_color="#e74c3c")

    def _parse_peer_ips_draft(self) -> List[str]:
        if not hasattr(self, "peer_ips_text"):
            return list(portal_config.load_peer_ips())
        raw = self.peer_ips_text.get("1.0", "end")
        lines = [ln.strip() for ln in raw.replace("\r", "").split("\n")]
        return [x for x in lines if x]

    def _peer_ips_for_probe(self) -> List[str]:
        draft = self._parse_peer_ips_draft()
        return draft if draft else list(portal_config.load_peer_ips())

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
        if not portal_config.load_peer_ips():
            return
        self._peer_poll_job = self.after(PEER_STATUS_POLL_MS, self._peer_poll_tick)

    def _peer_poll_tick(self) -> None:
        self._peer_poll_job = None
        if portal_config.load_peer_ips():
            self.check_peer_connection_async(silent=True)
        if portal_config.load_peer_ips():
            self._arm_peer_poll()

    def check_peer_connection_async(self, silent: bool = False) -> None:
        """Фоновый ping → pong ко всем IP из списка (черновик в текстбоксе или сохранённый)."""
        ips = self._peer_ips_for_probe()
        if not ips:
            self.after(
                0,
                lambda: self.peer_link_status_label.configure(
                    text="⚪ Пары: добавь IP в список",
                    text_color="gray",
                ),
            )
            return

        def worker():
            results: List[Tuple[str, bool, str]] = []
            for ip in ips:
                ok, code = probe_portal_peer(ip)
                results.append((ip, ok, code))

            def apply():
                if not hasattr(self, "peer_link_status_label"):
                    return
                if len(results) == 1:
                    ip, ok, code = results[0]
                    msg_t, msg_c = self._format_peer_probe_result(ip, ok, code)
                else:
                    oks = sum(1 for _, o, _ in results if o)
                    bad = [ip for ip, o, _ in results if not o]
                    if oks == len(results):
                        msg_t = f"🟢 Все {len(results)} ПК отвечают на :{PORTAL_PORT}"
                        msg_c = "#3dd68c"
                    elif oks:
                        msg_t = f"⚠️ Онлайн {oks}/{len(results)} — нет: {', '.join(bad[:5])}"
                        msg_c = "#e67e22"
                    else:
                        msg_t = f"🔌 Ни один из {len(results)} ПК не отвечает ({bad[0]}…)"
                        msg_c = "#e74c3c"
                self.peer_link_status_label.configure(text=msg_t, text_color=msg_c)
                if not silent:
                    for ip, ok, code in results:
                        if ok:
                            self.log(f"📡 {ip}: OK (Портал)")
                        else:
                            self.log(f"📡 {ip}: нет связи ({code})")

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
        """Лог в UI; безопасен с любого потока (Tk на macOS только из главного)."""
        try:
            if threading.current_thread() is threading.main_thread():
                self._log_sync(message)
            else:
                try:
                    self.after(0, lambda m=message: self._log_sync(m))
                except Exception:
                    print(f"[Portal] {message}", flush=True)
        except Exception:
            try:
                print(f"[Portal] {message}", flush=True)
            except Exception:
                pass

    def _log_sync(self, message: str) -> None:
        """Писать в журнал только с главного потока Tk."""
        self.log_text.configure(state="normal")
        timestamp = time.strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}\n"
        self.log_text.insert("end", line)
        lines = int(self.log_text.index("end-1c").split(".")[0])
        if lines > self._log_max_lines:
            self.log_text.delete("1.0", f"{lines - self._log_max_lines + 1}.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        try:
            with portal_config.activity_log_path().open("a", encoding="utf-8") as af:
                af.write(line)
        except Exception:
            pass

    def copy_whole_activity_log(self):
        """Кнопка: весь текст журнала в буфер обмена."""
        try:
            self.log_text.configure(state="normal")
            t = self.log_text.get("1.0", "end-1c")
            self.log_text.configure(state="disabled")
            if t.strip():
                pyperclip.copy(t)
                self.log("📋 Весь журнал скопирован в буфер обмена")
        except Exception as e:
            self.log(f"⚠️ Копирование журнала: {e}")

    def _log_copy_selection_hotkey(self, event=None):
        """Cmd/Ctrl+C в журнале: выделение или весь текст (CTk часто не копирует из disabled)."""
        try:
            self.log_text.configure(state="normal")
            if self.log_text.tag_ranges("sel"):
                t = self.log_text.get("sel.first", "sel.last")
            else:
                t = self.log_text.get("1.0", "end-1c")
            self.log_text.configure(state="disabled")
            if t:
                pyperclip.copy(t)
        except Exception:
            try:
                self.log_text.configure(state="disabled")
            except Exception:
                pass
        return "break"
    
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
                # Не логируем каждое соединение: авто-ping со второго ПК каждые ~20 с
                # путает с «вот-вот пришлют файл». Тип запроса пишем в handle_client.
                
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
            message, tail = read_first_json_from_socket(client_socket)
            if not message:
                self._log_from_thread(
                    "⚠️ Клиент прислал не-JSON или обрыв заголовка (ping / метаданные файла)"
                )
                return

            req = message.get("type")
            if req != "ping":
                self._log_from_thread(f"🔗 {addr[0]} · {req}")
            
            if message.get("type") == "file":
                self.receive_file(client_socket, message, prefix=tail)
            elif message.get("type") == "clipboard_files":
                self.receive_clipboard_files(client_socket, message, prefix=tail)
            elif message.get("type") == "clipboard_rich":
                self.receive_clipboard_rich(client_socket, message, prefix=tail)
            elif message.get("type") == "clipboard":
                self.receive_clipboard(message)
            elif message.get("type") == "clipboard_file":
                self._receive_clipboard_file_payload(client_socket, message, prefix=tail)
            elif req == "get_clipboard":
                self.send_clipboard_response(client_socket)
            elif req == "ping":
                # Как в репо: отвечаем pong сразу (проверка «это Портал» с другого ПК)
                pong = json.dumps(
                    {"type": "pong", "ok": True, "version": 1},
                    ensure_ascii=False,
                )
                client_socket.sendall(pong.encode("utf-8"))
                # Не спамим лог при авто-проверке каждые 20 с (тихий pong)
            else:
                self._log_from_thread(
                    f"⚠️ Неизвестный тип запроса: {req!r} — обнови Портал на обоих ПК до одной версии"
                )
            
        except Exception as e:
            self._log_from_thread(f"❌ Ошибка обработки клиента: {str(e)}")
        finally:
            client_socket.close()
    
    def _receive_clipboard_file_payload(
        self,
        client_socket: socket.socket,
        message: dict,
        prefix: bytes = b"",
    ) -> None:
        """Один файл в стиле clipboard_file (JSON + сырые байты), как в ответе get_clipboard."""
        try:
            raw_name = message.get("filename", "remote_clipboard_file")
            fname = _safe_incoming_filename(raw_name)
            try:
                need = int(message.get("filesize", 0) or 0)
            except (TypeError, ValueError):
                need = 0
            if need <= 0 or need > CLIPBOARD_PULL_FILE_MAX_BYTES:
                self._log_from_thread(f"⚠️ clipboard_file: некорректный размер {need}")
                _portal_sendall(client_socket, b"ERR")
                return
            receive_dir = portal_config.incoming_clipboard_files_save_dir()
            receive_dir.mkdir(parents=True, exist_ok=True)
            filepath = receive_dir / f"{int(time.time() * 1000)}_{fname}"
            data = bytearray(prefix.lstrip(b"\n\r"))
            while len(data) < need:
                part = client_socket.recv(min(65536, need - len(data)))
                if not part:
                    break
                data.extend(part)
            if len(data) < need:
                self._log_from_thread("❌ clipboard_file: обрезаны данные")
                _portal_sendall(client_socket, b"ERR")
                return
            filepath.write_bytes(bytes(data))
            refresh_windows_shell_after_new_file(filepath)
            _portal_sendall(client_socket, b"OK")
            p = str(filepath.resolve())

            def _apply():
                try:
                    self._apply_incoming_clipboard_files([p])
                except Exception as ex:
                    self._log_from_thread(f"❌ После приёма clipboard_file: {ex}")

            try:
                self.after(0, _apply)
            except Exception:
                _apply()
            self._log_from_thread(f"✅ clipboard_file: {filepath.name}")
        except Exception as e:
            self._log_from_thread(f"❌ clipboard_file: {e}")
            try:
                _portal_sendall(client_socket, b"ERR")
            except Exception:
                pass

    def receive_file(
        self,
        client_socket: socket.socket,
        message: dict,
        prefix: bytes = b"",
    ):
        """Прием файла; prefix — байты уже прочитанные после JSON в первом recv."""
        filepath: Optional[Path] = None
        try:
            raw_name = message.get("filename", "received_file")
            filename = _safe_incoming_filename(raw_name)
            try:
                filesize = int(message.get("filesize", 0) or 0)
            except (TypeError, ValueError):
                filesize = 0
            if filesize < 0:
                filesize = 0

            self._log_from_thread(f"📥 Прием файла: {filename} ({filesize} байт)")

            receive_dir = portal_config.receive_dir_path()
            receive_dir.mkdir(parents=True, exist_ok=True)

            filepath = receive_dir / filename
            if filepath.exists():
                stem, suf = filepath.stem, filepath.suffix
                filepath = receive_dir / f"{stem}_{int(time.time())}{suf}"

            remaining = filesize
            chunk_buf = prefix
            with open(filepath, "wb") as f:
                while remaining > 0:
                    if chunk_buf:
                        take = min(len(chunk_buf), remaining)
                        f.write(chunk_buf[:take])
                        chunk_buf = chunk_buf[take:]
                        remaining -= take
                        continue
                    chunk = client_socket.recv(min(65536, remaining))
                    if not chunk:
                        break
                    f.write(chunk)
                    remaining -= len(chunk)

            self._log_from_thread(f"✅ Файл сохранен: {filepath}")

            _portal_sendall(client_socket, b"OK")

            # Finder / NSPasteboard только из главного потока Tk — иначе на macOS возможен обрыв сокета (10054).
            fp_saved = filepath
            msg_local = dict(message)

            def _finish_receive():
                try:
                    p = Path(fp_saved)
                    reveal_ok = os.environ.get("PORTAL_REVEAL_RECEIVED", "1").strip().lower() not in (
                        "0",
                        "false",
                        "no",
                        "off",
                    )
                    if msg_local.get("portal_clipboard"):
                        if platform.system() == "Darwin" and reveal_ok:
                            try:
                                subprocess.run(
                                    ["open", "-R", str(p)],
                                    check=False,
                                    timeout=8,
                                    capture_output=True,
                                )
                            except Exception:
                                pass
                        bd = msg_local.get("clip_batch")
                        if isinstance(bd, dict) and bd.get("id") is not None:
                            try:
                                bid = str(bd["id"])
                                i = int(bd.get("i", 0))
                                n = int(bd.get("n", 1))
                                self._clip_batch_add(bid, i, n, p)
                            except (TypeError, ValueError):
                                self._apply_portal_clipboard_files([p])
                        else:
                            self._apply_portal_clipboard_files([p])
                    else:
                        self._apply_receive_mode_after_saved_file(p, reveal_mac_allowed=reveal_ok)
                except Exception as ex:
                    self.log(f"❌ После приёма (Finder/буфер): {ex}")

            try:
                self.after(0, _finish_receive)
            except Exception:
                _finish_receive()
        except Exception as e:
            self._log_from_thread(f"❌ Ошибка приёма файла: {e}")

    def _apply_receive_mode_after_saved_file(self, p: Path, *, reveal_mac_allowed: bool) -> None:
        """Обычный приём файла: режим both / disk_only / clipboard_only (не portal_clipboard)."""
        mode = portal_config.receive_files_mode()
        if not p.is_file():
            return
        if (
            reveal_mac_allowed
            and platform.system() == "Darwin"
            and mode in ("both", "disk_only")
        ):
            try:
                subprocess.run(
                    ["open", "-R", str(p)],
                    check=False,
                    timeout=8,
                    capture_output=True,
                )
            except Exception:
                pass
        if mode in ("both", "clipboard_only"):
            self._apply_portal_clipboard_files([p])
            self.log(f"📋 В буфере для вставки: {p.name}")

    def receive_clipboard_files(
        self,
        client_socket: socket.socket,
        message: dict,
        prefix: bytes = b"",
    ) -> None:
        """Несколько файлов из буфера (push Ctrl+Alt+C) — сохранить и по режиму в буфер ОС."""
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
                filename = _safe_incoming_filename(str(raw_name))
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
        """Картинка из буфера: JSON + сырые байты PNG (протокол Win/Mac)."""
        try:
            size = int(message.get("size", 0))
        except (TypeError, ValueError):
            size = 0
        if not portal_clip_rich.image_size_ok(size):
            self._log_from_thread("⚠️ Слишком большой снимок буфера (clipboard_rich)")
            try:
                _portal_sendall(client_socket, b"ERR")
            except Exception:
                pass
            return

        receive_dir = portal_config.receive_dir_path()
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
                # macOS: сначала NSPasteboard (NSURL) в процессе приложения — надёжнее для Finder, чем osascript
                if platform.system() == "Darwin" and set_system_clipboard_file_paths(paths):
                    msg = (
                        f"файлы в буфере ({len(paths)} шт.) — в Finder: открой нужную папку, "
                        "кликни в список файлов, Cmd+V. "
                        "(Cmd+Ctrl+V у Портала = «забрать буфер с пира», не вставка; legacy: Cmd+Shift+V.)"
                    )
                else:
                    msg = portal_clip_rich.apply_clipboard_payload(
                        "files", file_paths=paths
                    )
                try:
                    self.last_clipboard = "\n".join(paths)
                except Exception:
                    pass
                try:
                    self._clipboard_ignore_until = time.monotonic() + 5.0
                except Exception:
                    pass

            if mode == "disk":
                self.log(
                    f"📁 Из буфера: {len(paths)} файл(ов) в папке — "
                    "в системный буфер не кладём (режим «только папка»)"
                )
            elif mode == "clipboard":
                self.log(f"📋 {msg}")
            else:
                self.log(f"📁 + 📋 {msg}")
        finally:
            self.is_receiving_clipboard = False

    def _apply_incoming_clipboard_image(self, path: str) -> None:
        self.is_receiving_clipboard = True
        try:
            p = Path(path)
            if p.is_file():
                if platform.system() == "Darwin":
                    if set_system_clipboard_image_from_file(p):
                        self.log(
                            f"📋 Картинка в буфере (macOS): {p.name} — Cmd+V"
                        )
                        return
                    try:
                        raw = p.read_bytes()
                        if set_system_clipboard_png(raw):
                            self.log(f"📋 Картинка в буфере (PNG): {p.name}")
                            return
                    except Exception:
                        pass
                msg = portal_clip_rich.apply_clipboard_payload(
                    "image", image_path=str(p)
                )
                self.log(f"📋 {msg} — Ctrl+V / Cmd+V")
        finally:
            self.is_receiving_clipboard = False

    def _clip_batch_add(self, batch_id: str, index: int, total: int, path: Path) -> None:
        with self._clip_batch_lock:
            entry = self._clip_batches.setdefault(
                batch_id, {"total": total, "paths": {}}
            )
            entry["paths"][index] = path
            if len(entry["paths"]) >= entry["total"]:
                ordered = [entry["paths"][j] for j in sorted(entry["paths"])]
                del self._clip_batches[batch_id]
                paths_copy = list(ordered)
            else:
                paths_copy = None
        if paths_copy is not None:
            self._apply_portal_clipboard_files(paths_copy)

    def _apply_portal_clipboard_files(self, paths: List[Path]) -> None:
        """Безопасно с любого потока: выполнение на главном цикле Tk (pasteboard / win32)."""
        snap: List[Path] = []
        for p in paths:
            try:
                snap.append(Path(p))
            except Exception:
                continue

        def _do():
            try:
                self._apply_portal_clipboard_files_impl(snap)
            except Exception as e:
                self.log(f"❌ Буфер (файлы): {e}")

        try:
            self.after(0, _do)
        except Exception:
            _do()

    def _apply_portal_clipboard_files_impl(self, paths: List[Path]) -> None:
        paths = [p for p in paths if p.is_file()]
        if not paths:
            return
        paths_str = [str(p.resolve()) for p in paths]
        if len(paths) == 1:
            suf = paths[0].suffix.lower()
            if suf in (
                ".png",
                ".jpg",
                ".jpeg",
                ".gif",
                ".webp",
                ".bmp",
                ".tif",
                ".tiff",
            ):
                if set_system_clipboard_image_from_file(paths[0]):
                    self._log_from_thread(
                        f"📋 Буфер: картинка «{paths[0].name}» ({paths[0].stat().st_size} байт)"
                    )
                    return
        if set_system_clipboard_file_paths(paths_str):
            self._log_from_thread(
                f"📋 Буфер: {len(paths_str)} файл(ов) — можно вставить (Ctrl+V / Cmd+V)"
            )
        else:
            self._log_from_thread(
                "📋 Не удалось положить файлы в буфер ОС (CF_HDROP) — открой папку приёма"
            )
            try:
                pyperclip.copy("\n".join(paths_str))
                self._log_from_thread(
                    "📋 В буфер как текст скопированы полные пути к файлам (вставь в адресную строку Проводника)"
                )
            except Exception:
                pass
    
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
    
    def _clipboard_snapshot_resolved_for_send(self) -> Tuple[str, dict]:
        """Снимок буфера для отправки (push и ответ get_clipboard): snapshot + фолбэки."""
        from portal_widget import grab_clipboard_file_paths, grab_clipboard_image

        kind, payload = portal_clip_rich.clipboard_snapshot()
        if kind == "empty":
            text = pyperclip.paste()
            if text is not None and str(text).strip():
                kind, payload = "text", {"text": str(text)}
            else:
                im = grab_clipboard_image()
                if im is not None:
                    buf = io.BytesIO()
                    im.save(buf, format="PNG")
                    raw = buf.getvalue()
                    if raw:
                        kind, payload = "image", {
                            "image_bytes": raw,
                            "mime": "image/png",
                        }
                if kind == "empty":
                    paths_fb = grab_clipboard_file_paths()
                    if paths_fb:
                        kind, payload = "files", {"paths": list(paths_fb)}
        return kind, payload

    def _emit_resolved_clipboard_payload(
        self,
        client_socket: socket.socket,
        kind: str,
        payload: dict,
        *,
        log: Callable[[str], None],
        context_label: str,
    ) -> None:
        """Записать снимок в сокет (ответ get_clipboard или входящий push clipboard_*)."""
        if kind == "text":
            t = payload.get("text", "") or ""
            resp = json.dumps({"type": "clipboard", "text": t}, ensure_ascii=False)
            client_socket.sendall(resp.encode("utf-8") + b"\n")
            log(f"📋 {context_label} → текст ({len(t)} симв.)")
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
                resp = json.dumps(
                    {"type": "clipboard", "text": t or ""}, ensure_ascii=False
                )
                client_socket.sendall(resp.encode("utf-8") + b"\n")
                log(f"📋 {context_label} → файлы не прочитались, отдан текст/пусто")
                return
            if len(valid_paths) == 1:
                one = Path(valid_paths[0])
                try:
                    sz = int(one.stat().st_size)
                except OSError:
                    sz = 0
                if 0 < sz <= CLIPBOARD_PULL_FILE_MAX_BYTES:
                    hdr = json.dumps(
                        {
                            "type": "clipboard_file",
                            "filename": one.name,
                            "filesize": sz,
                        },
                        ensure_ascii=False,
                    )
                    client_socket.sendall(hdr.encode("utf-8") + b"\n")
                    with open(one, "rb") as src_f:
                        while True:
                            chunk = src_f.read(65536)
                            if not chunk:
                                break
                            _portal_sendall(client_socket, chunk)
                    # Ответ get_clipboard: клиент pull не шлёт OK. Push на сервер — приёмник шлёт OK.
                    if str(context_label).startswith("push"):
                        okp = _recv_ok_prefix(client_socket, timeout=180.0)
                        log(
                            f"📋 {context_label} → один файл «{one.name}» ({sz} байт); ответ: {okp[:32]!r}"
                        )
                    else:
                        log(
                            f"📋 {context_label} → один файл «{one.name}» ({sz} байт)"
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
            log(
                f"📋 {context_label} → {len(valid_paths)} файл(ов); ответ: {okp[:24]!r}"
            )
            return

        if kind == "image":
            image_bytes = payload.get("image_bytes") or b""
            if not portal_clip_rich.image_size_ok(len(image_bytes)):
                resp = json.dumps({"type": "clipboard", "text": ""}, ensure_ascii=False)
                client_socket.sendall(resp.encode("utf-8") + b"\n")
                log(f"📋 {context_label} → картинка слишком большая")
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
            log(
                f"📋 {context_label} → картинка clipboard_rich; ответ: {okp[:24]!r}"
            )
            return

        resp = json.dumps({"type": "clipboard", "text": ""}, ensure_ascii=False)
        client_socket.sendall(resp.encode("utf-8") + b"\n")
        log(f"📋 {context_label} → неизвестный снимок буфера")
    
    def send_clipboard_response(self, client_socket: socket.socket):
        """
        Ответ на get_clipboard: portal_clipboard_rich (как на Windows) + фолбэк для macOS.
        Типы: clipboard (текст), clipboard_files (поток), clipboard_rich (PNG), clipboard_image (старый клиент).
        """
        try:
            kind, payload = self._clipboard_snapshot_resolved_for_send()

            if kind == "empty":
                resp = json.dumps({"type": "clipboard", "text": ""}, ensure_ascii=False)
                client_socket.sendall(resp.encode("utf-8") + b"\n")
                self._log_from_thread("📋 get_clipboard → буфер пуст")
                return

            self._emit_resolved_clipboard_payload(
                client_socket,
                kind,
                payload,
                log=self._log_from_thread,
                context_label="get_clipboard",
            )
        except Exception as e:
            self._log_from_thread(f"❌ Ошибка ответа буфера: {str(e)}")
    
    def set_remote_peer_ip(self, ip: Optional[str]):
        """Добавить/обновить IP в списке пиров (файл + текстбокс в главном окне)."""
        ip_clean = (ip or "").strip() or None
        success = portal_config.save_remote_ip(ip_clean)
        self.remote_peer_ip = portal_config.load_remote_ip()
        if not success and ip_clean:
            if hasattr(self, "log"):
                self.log("⚠️ Не удалось сохранить IP в файл! Проверь права на запись")
            else:
                print(f"[Portal] Не удалось сохранить IP: {ip_clean}")
        try:
            self._fill_peer_ips_textbox()
            self.rebuild_peer_checkboxes()
        except Exception as e:
            print(f"[Portal] Ошибка обновления списка IP: {e}")
    
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
        """Ctrl+Alt+C / Cmd+Ctrl+C (legacy: Cmd+Shift+C) — отправить локальный буфер на выбранные ПК"""
        if not self.get_target_ips():
            self.log("⚠️ Сохрани список IP и отметь получателей (галочки) или укажи IP в виджете")
            return
        threading.Thread(target=self._broadcast_clipboard_push_worker, daemon=True).start()
    
    def pull_shared_clipboard_hotkey(self):
        """Ctrl+Alt+V / Cmd+Ctrl+V — забрать буфер с первого выбранного ПК"""
        targets = self.get_target_ips()
        if not targets:
            self.log("⚠️ Сохрани список IP и отметь, с какого ПК забирать (первый в списке)")
            return
        if not self._clipboard_pull_lock.acquire(blocking=False):
            self.log("⏸ Уже выполняется запрос буфера с пира — подождите")
            return
        src = targets[0]
        self.log(
            f"📥 Забираю буфер с {src} (на том ПК в логе будет get_clipboard — это ответ на запрос)"
        )

        def _worker():
            try:
                self._pull_clipboard_worker(src)
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
            _log(f"🔌 Соединение с {target_ip} для get_clipboard…")
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.settimeout(30)
            try:
                client_socket.connect((target_ip, PORTAL_PORT))
            except ConnectionRefusedError:
                _log(
                    "❌ Порт не принимает соединение (Windows часто: 10061). "
                    "На удалённом ПК не запущен приём — открой Портал и «Запустить портал», проверь IP и файрвол."
                )
                return
            except OSError as e:
                winerr = getattr(e, "winerror", None)
                errno_val = getattr(e, "errno", None)
                if winerr == 10061 or errno_val == 10061:
                    _log(
                        "❌ Подключение отклонено (10061): на том IP не слушает Портал "
                        "или неверный адрес. Запусти приём на удалённой машине."
                    )
                    return
                raise
            client_socket.settimeout(600)
            _log(f"✅ Подключение установлено: {target_ip}:{PORTAL_PORT}")
            _portal_sendall(
                client_socket,
                json.dumps({"type": "get_clipboard"}).encode("utf-8"),
            )
            message, rest = read_one_json_object_from_socket(client_socket)
            if message.get("type") == "clipboard":
                text = message.get("text", "")
                lines = [ln.strip() for ln in (text or "").split("\n") if ln.strip()]
                resolved: List[str] = []
                for ln in lines:
                    try:
                        pp = Path(ln)
                        if pp.is_file():
                            resolved.append(str(pp.resolve()))
                    except Exception:
                        pass
                self.is_receiving_clipboard = True
                try:
                    if lines and len(resolved) == len(lines):
                        if set_system_clipboard_file_paths(resolved):
                            _log(f"📋 С буфера удалённого ПК: {len(resolved)} файл(ов) (пути есть локально)")
                        else:
                            pyperclip.copy(text)
                            _log(f"📋 Текст с удалённого ПК ({len(text)} символов)")
                    else:
                        pyperclip.copy(text)
                        _log(f"📋 Текст с удалённого ПК ({len(text)} символов)")
                finally:
                    self.is_receiving_clipboard = False
                self.last_clipboard = text
            elif message.get("type") == "clipboard_files":
                self.receive_clipboard_files(client_socket, message, prefix=rest)
                _log("📋 Файлы с удалённого ПК получены (см. строки выше)")
            elif message.get("type") == "clipboard_rich":
                self.receive_clipboard_rich(client_socket, message, prefix=rest)
                _log("📋 Данные clipboard_rich с удалённого ПК получены")
            elif message.get("type") == "clipboard_file":
                raw_name = message.get("filename", "remote_clipboard_file")
                fname = _safe_incoming_filename(raw_name)
                try:
                    need = int(message.get("filesize", 0) or 0)
                except (TypeError, ValueError):
                    need = 0
                if need <= 0 or need > CLIPBOARD_PULL_FILE_MAX_BYTES:
                    raise ValueError(f"Некорректный размер файла в ответе: {need}")
                receive_dir = portal_config.incoming_clipboard_files_save_dir()
                receive_dir.mkdir(parents=True, exist_ok=True)
                filepath = receive_dir / f"{int(time.time() * 1000)}_{fname}"
                data = bytearray(rest.lstrip(b"\n\r"))
                while len(data) < need:
                    part = client_socket.recv(min(65536, need - len(data)))
                    if not part:
                        break
                    data.extend(part)
                if len(data) < need:
                    raise ValueError("Обрезаны данные файла из буфера")
                filepath.write_bytes(bytes(data))
                refresh_windows_shell_after_new_file(filepath)
                _log(f"✅ Файл из буфера удалённого ПК сохранён: {filepath.name}")

                def _finish_pull_file():
                    try:
                        self._apply_incoming_clipboard_files([str(filepath.resolve())])
                    except Exception as ex:
                        self.log(f"❌ После приёма файла из буфера: {ex}")

                try:
                    self.after(0, _finish_pull_file)
                except Exception:
                    _finish_pull_file()
            elif message.get("type") == "clipboard_image":
                need = int(message.get("size", 0))
                # После JSON сервер шлёт \n и сразу PNG (старые версии)
                data = bytearray(rest.lstrip(b"\n\r"))
                while len(data) < need:
                    part = client_socket.recv(min(65536, need - len(data)))
                    if not part:
                        break
                    data.extend(part)
                if len(data) < need:
                    raise ValueError("Обрезаны данные картинки")

                def _apply_png_pull():
                    self.is_receiving_clipboard = True
                    try:
                        raw = bytes(data)
                        ok = set_system_clipboard_png(raw)
                        if ok:
                            _log(
                                f"📋 Картинка с удалённого ПК ({len(raw)} байт) — "
                                "Cmd+V / Ctrl+V"
                            )
                        else:
                            _log("⚠️ Картинка получена, но не удалось записать в буфер ОС")
                    finally:
                        self.is_receiving_clipboard = False

                try:
                    self.after(0, _apply_png_pull)
                except Exception:
                    _apply_png_pull()
            else:
                _log(f"⚠️ Неожиданный ответ при запросе буфера: {message.get('type')!r}")
        except Exception as e:
            err = str(e)
            if "10061" in err:
                _log(
                    "❌ Сеть 10061: на удалённом IP не слушает порт Портала — "
                    "запусти «Запустить портал» там и проверь Tailscale/IP."
                )
            else:
                _log(f"❌ Не удалось получить буфер: {err}")
        finally:
            if client_socket is not None:
                try:
                    client_socket.close()
                except OSError:
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
        targets = self.get_target_ips()
        if targets:
            self.log(f"📤 Отправка на {len(targets)} ПК: {', '.join(targets)}")
            for ip in targets:
                threading.Thread(
                    target=self.send_file,
                    args=(filepath, ip),
                    daemon=True,
                ).start()
        else:
            self.log("⚠️ Сначала сохрани список IP и отметь получателей")
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
        """Отправка буфера (текст / картинка / файлы) на все отмеченные ПК."""
        if self.get_target_ips():
            threading.Thread(
                target=self._broadcast_clipboard_push_worker,
                daemon=True,
            ).start()
        else:
            self.log("⚠️ Сначала сохрани список IP и отметь получателей")
            dialog = ctk.CTkToplevel(self)
            dialog.title("Отправить буфер обмена")
            dialog.geometry("400x200")
            label = ctk.CTkLabel(
                dialog,
                text="Введите IP ПК (добавится в список):",
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
                    portal_config.save_peer_send_targets([ip])
                    self.rebuild_peer_checkboxes()
                    dialog.destroy()
                    threading.Thread(
                        target=self._broadcast_clipboard_push_worker,
                        daemon=True,
                    ).start()

            send_button = ctk.CTkButton(
                dialog,
                text="Отправить",
                command=send,
                font=ctk.CTkFont(size=14),
            )
            send_button.pack(pady=20)
    
    def send_file(
        self,
        filepath: str,
        target_ip: str,
        portal_clipboard: bool = False,
        clip_batch: Optional[Tuple[str, int, int]] = None,
    ):
        """Отправка файла; portal_clipboard — на приёме положить в буфер ОС."""
        try:
            self.log(f"📤 Отправка файла на {target_ip}...")
            
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.settimeout(15)
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
                winerr = getattr(e, "winerror", None)
                errno_val = getattr(e, "errno", None)
                if winerr == 10061 or errno_val == 10061 or "10061" in str(e):
                    self.log(
                        f"❌ {target_ip}: 10061 — порт не принимает соединение. "
                        "На удалённом ПК «Запустить портал», проверь IP / Tailscale / файрвол."
                    )
                    return
                if "No route to host" in str(e) or "Network is unreachable" in str(e):
                    self.log(f"❌ Нет пути к {target_ip}")
                    self.log("💡 Проверь что оба ПК в одной сети (Tailscale или LAN)")
                else:
                    self.log(f"❌ Ошибка сети: {str(e)}")
                return
            
            filename = os.path.basename(filepath)
            filesize = os.path.getsize(filepath)
            
            message: Dict[str, Any] = {
                "type": "file",
                "filename": filename,
                "filesize": filesize,
            }
            if portal_clipboard:
                message["portal_clipboard"] = True
            if clip_batch is not None:
                bid, i, n = clip_batch
                message["clip_batch"] = {"id": bid, "i": i, "n": n}

            # Без лимита времени на передачу больших файлов; отдельный таймаут на ответ OK
            client_socket.settimeout(None)
            _portal_sendall(client_socket, json.dumps(message, ensure_ascii=False).encode("utf-8"))
            time.sleep(0.05)

            with open(filepath, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    _portal_sendall(client_socket, chunk)
            
            client_socket.settimeout(180)
            response = _recv_ok_prefix(client_socket)
            try:
                client_socket.close()
            except OSError:
                pass
            
            if response.startswith(b"OK"):
                self.log(f"✅ Файл успешно отправлен: {filename}")
            else:
                self.log(
                    f"⚠️ Ответ приёма файлов: {response!r} — смотри лог на ПК-получателе (ошибка приёма / JSON)"
                )
                
        except socket.timeout:
            self.log(f"❌ Таймаут при отправке на {target_ip}")
            self.log("💡 Файл слишком большой или медленное соединение")
        except (ConnectionResetError, BrokenPipeError) as e:
            self.log(f"❌ Сеть: {target_ip} — соединение разорвано ({e})")
            self.log(
                "💡 Часто ПК-получатель закрыл сокет (ошибка приёма / краш). На Mac обнови Портал и смотри "
                f"{portal_config.activity_log_path().name} на том ПК."
            )
        except OSError as e:
            err_msg = str(e)
            if getattr(e, "winerror", None) == 10054 or "10054" in err_msg:
                self.log(f"❌ Сеть: {target_ip} — удалённый хост разорвал соединение (WinError 10054)")
                self.log(
                    "💡 Обычно сбой на стороне приёма (буфер/Finder из фонового потока). Обнови Портал на получателе."
                )
            elif "timed out" in err_msg.lower() or "timeout" in err_msg.lower():
                self.log(f"❌ Таймаут: {target_ip} не отвечает")
            else:
                self.log(f"❌ Ошибка отправки: {err_msg}")
        except Exception as e:
            err_msg = str(e)
            if "timed out" in err_msg.lower() or "timeout" in err_msg.lower():
                self.log(f"❌ Таймаут: {target_ip} не отвечает")
                self.log("💡 Убедись что на втором ПК запущен портал")
            elif "refused" in err_msg.lower():
                self.log(f"❌ Подключение отклонено: портал на {target_ip} не запущен")
                self.log("💡 На втором ПК нажми «Запустить портал»")
            elif "10054" in err_msg or "forcibly closed" in err_msg.lower():
                self.log(f"❌ Сеть: {target_ip} — соединение сброшено")
                self.log("💡 Проверь журнал Портала на ПК-получателе и обнови приложение там.")
            else:
                self.log(f"❌ Ошибка отправки: {err_msg}")
        finally:
            if client_socket is not None:
                try:
                    client_socket.close()
                except Exception:
                    pass
    
    def _broadcast_clipboard_push_worker(self) -> None:
        """Фон: файлы из буфера → send_file; картинка без путей → PNG; иначе текст."""
        with self._clipboard_push_lock:
            self._broadcast_clipboard_push_worker_impl()

    def _broadcast_clipboard_push_worker_impl(self) -> None:
        """Тот же протокол, что и ответ get_clipboard: clipboard / clipboard_file(s) / clipboard_rich."""
        targets = self.get_target_ips()
        if not targets:
            self.log("⚠️ Нет получателей — отметь IP галочками")
            return

        kind, payload = self._clipboard_snapshot_resolved_for_send()
        if kind == "empty":
            self.log(
                "⚠️ Буфер пуст (нет текста, картинки и скопированных файлов)"
            )
            return

        def _push_to_ip(ip: str) -> None:
            sock: Optional[socket.socket] = None
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(30)
                try:
                    sock.connect((ip, PORTAL_PORT))
                except ConnectionRefusedError:
                    self.log(
                        f"❌ {ip}: порт не принимает (часто Windows 10061) — "
                        "на том ПК «Запустить портал», проверь IP и файрвол."
                    )
                    return
                except OSError as e:
                    winerr = getattr(e, "winerror", None)
                    errno_val = getattr(e, "errno", None)
                    if winerr == 10061 or errno_val == 10061:
                        self.log(
                            f"❌ {ip}: 10061 — на этом адресе не слушает Портал."
                        )
                        return
                    raise
                sock.settimeout(600)
                self._emit_resolved_clipboard_payload(
                    sock,
                    kind,
                    payload,
                    log=self.log,
                    context_label=f"push → {ip}",
                )
            except Exception as e:
                err = str(e)
                if "10061" in err:
                    self.log(
                        f"❌ {ip}: 10061 — приём не запущен или неверный IP (Tailscale/VPN)."
                    )
                else:
                    self.log(f"❌ {ip}: отправка буфера — {err}")
            finally:
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass

        for ip in targets:
            threading.Thread(target=_push_to_ip, args=(ip,), daemon=True).start()

        if kind == "text":
            summary = f"📤 Буфер (текст) → {len(targets)} ПК"
        elif kind == "files":
            n = len([p for p in (payload.get("paths") or []) if os.path.isfile(p)])
            summary = (
                f"📤 Буфер: {n} файл(ов) (clipboard_files) → {len(targets)} ПК"
            )
        elif kind == "image":
            summary = (
                f"📤 Буфер: картинка (clipboard_rich) → {len(targets)} ПК"
            )
        else:
            summary = f"📤 Буфер → {len(targets)} ПК"
        self.log(summary)
    
    def send_clipboard(self, target_ip: str):
        """Синхронизация / совместимость: отправить текущий текст буфера."""
        text = pyperclip.paste() or ""
        if not text:
            return
        self.send_clipboard_text(target_ip, text)

    def send_clipboard_text(self, target_ip: str, clipboard_text: str):
        """Отправка текста в буфер на удалённый ПК (JSON type clipboard)."""
        try:
            if not clipboard_text:
                self.log("⚠️ Буфер обмена пуст")
                return
            
            self.log(f"📤 Отправка текста на {target_ip}...")
            
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

            message = {"type": "clipboard", "text": clipboard_text}
            _portal_sendall(
                client_socket,
                json.dumps(message, ensure_ascii=False).encode("utf-8"),
            )
            client_socket.close()
            
            self.log(f"✅ Текст отправлен ({len(clipboard_text)} символов)")
                
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
                if time.monotonic() < getattr(
                    self, "_clipboard_ignore_until", 0.0
                ):
                    self.after(1000, self._clipboard_tick)
                    return
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
            app.log(
                "✅ Виджет скрыт по умолчанию — Ctrl+Alt+P (Win) / Cmd+Ctrl+P (Mac; LEGACY: Cmd+Option+P) чтобы показать"
            )
            app.log("💡 Список IP и галочки «кому слать» — в главном окне Портала")
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
