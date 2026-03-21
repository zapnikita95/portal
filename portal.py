"""
Портал - приложение для передачи файлов и синхронизации буфера обмена
через Tailscale сеть с красивым UI в стиле портала
"""

import sys
import os

# Дочерний процесс глобальных хоткеев (macOS 3.13+): только pynput, без Tk/CustomTkinter.
# В сборке PyInstaller тот же бинарник запускается с этой переменной — не нужен отдельный .py.
if __name__ == "__main__" and os.environ.get("PORTAL_HOTKEY_HELPER_SUBPROCESS") == "1":
    from portal_mac_hotkey_helper import main as _portal_hk_main

    _portal_hk_main()
    raise SystemExit(0)

# Проверка версии Python (один раз за процесс)
if sys.version_info >= (3, 13) and not os.environ.get("_PORTAL_PY313_WARN_DONE"):
    os.environ["_PORTAL_PY313_WARN_DONE"] = "1"
    print("⚠️  Python 3.13+ обнаружен. Некоторые библиотеки могут работать нестабильно.")
    print("   Рекомендуется Python 3.11 или 3.12 для стабильности.")
    print("   Если видите ошибки, попробуйте: pyenv install 3.12.7 && pyenv local 3.12.7\n")

import customtkinter as ctk
import tkinter as tk
import socket
import threading
import json
import hmac
import shutil
import pyperclip
import time
import io
import struct
import ctypes
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Any, Callable, Set
import subprocess
import platform
import queue
import webbrowser
from concurrent.futures import ThreadPoolExecutor

import portal_config
import portal_history
import portal_i18n as i18n
import portal_clipboard_rich as portal_clip_rich
from portal_json_framing import parse_first_json_object_bytes
from portal_tk_compat import ensure_tkdnd_tk_misc_patch


def _portal_widget_tk_alive(widget) -> bool:
    """Окно виджета (Toplevel) ещё существует — иначе after() даёт TclError «bad window path»."""
    try:
        r = getattr(widget, "root", None)
        if r is None:
            return False
        return bool(r.winfo_exists())
    except tk.TclError:
        return False


def _portal_message_from_mobile(message: Optional[dict]) -> bool:
    """True, если отправитель пометил себя как мобильный клиент (например Android Share)."""
    if not isinstance(message, dict):
        return False
    v = message.get("portal_source")
    if isinstance(v, str) and v.strip().lower() == "android":
        return True
    return v is True


def _portal_desktop_notify(title: str, body: str) -> None:
    """Короткое системное уведомление на ПК (macOS / Linux). Windows — без лишних зависимостей не подключаем."""
    t = (title or "Portal").strip() or "Portal"
    b = (body or "").strip() or "Портал"
    try:
        if platform.system() == "Darwin":
            # display notification (Notification Center)
            te = b.replace("\\", "\\\\").replace('"', '\\"')
            ti = t.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.run(
                ["osascript", "-e", f'display notification "{te}" with title "{ti}"'],
                check=False,
                timeout=6,
                capture_output=True,
            )
        elif platform.system() == "Linux":
            subprocess.run(
                ["notify-send", "-a", t, t, b],
                check=False,
                timeout=6,
                capture_output=True,
            )
    except Exception:
        pass


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
# Виджет не проигрывает видео напрямую — только после конвертации в GIF
_WIDGET_VIDEO_EXTS = (".mp4", ".webm", ".mov", ".mkv")
# Как часто обновлять статус «пара онлайн?» (мс)
PEER_STATUS_POLL_MS = 20000
# Один файл из буфера удалённого ПК по get_clipboard (не гоняем гигабайты по TCP)
CLIPBOARD_PULL_FILE_MAX_BYTES = 100 * 1024 * 1024


def _portal_allow_legacy_no_auth() -> bool:
    """Принимать соединения без поля secret (небезопасно; только для перехода со старых клиентов)."""
    return os.environ.get("PORTAL_ALLOW_LEGACY_NO_AUTH", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def merge_outgoing_shared_secret(message: Dict[str, Any]) -> Dict[str, Any]:
    """Добавить secret в первый JSON запроса, если пароль задан в config.json."""
    secret = portal_config.load_shared_secret()
    if not secret:
        return message
    out = dict(message)
    out["secret"] = secret
    return out


def incoming_peer_secret_ok(message: Optional[dict]) -> bool:
    """Проверка пароля сети на приёме (константное время)."""
    expected = portal_config.load_shared_secret()
    if not expected:
        return True
    if _portal_allow_legacy_no_auth():
        return True
    if not isinstance(message, dict):
        return False
    got = message.get("secret")
    if got is None:
        return False
    try:
        a = str(got).encode("utf-8")
        b = expected.encode("utf-8")
    except Exception:
        return False
    if len(a) > 512 or len(b) > 512:
        return False
    return hmac.compare_digest(a, b)


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


def send_sync_shared_secret_to_peer(
    host: str,
    new_shared_secret: str,
    port: int = PORTAL_PORT,
    timeout: float = 12.0,
) -> tuple[bool, str]:
    """
    Отправить новый пароль сети на другой ПК с Порталом.
    Аутентификация — текущий пароль из config (merge_outgoing_shared_secret); вызывать до локального save нового пароля.
    Возвращает (успех, пояснение для лога).
    """
    host = (host or "").strip()
    if not host:
        return False, "пустой IP"
    new_shared_secret = (new_shared_secret or "").strip()
    if not new_shared_secret:
        return False, "пустой пароль"
    if len(new_shared_secret) > 512:
        return False, "пароль слишком длинный"
    msg = merge_outgoing_shared_secret(
        {
            "type": "sync_shared_secret",
            "new_shared_secret": new_shared_secret,
        }
    )
    payload = json.dumps(msg, ensure_ascii=False).encode("utf-8")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(timeout)
        s.connect((host, port))
        s.sendall(payload)
        data = s.recv(16384)
    except ConnectionRefusedError:
        return False, "порт закрыт (запусти Портал на том ПК)"
    except socket.timeout:
        return False, "таймаут"
    except OSError as e:
        return False, str(e)[:120]
    finally:
        try:
            s.close()
        except OSError:
            pass
    if not data:
        return False, "нет ответа"
    resp = parse_portal_json_message(data)
    if isinstance(resp, dict) and resp.get("type") == "sync_shared_secret_ok":
        return True, "ok"
    if isinstance(resp, dict) and resp.get("type") == "portal_auth_failed":
        return False, "неверный текущий пароль на принимающей стороне"
    if isinstance(resp, dict) and resp.get("type") == "sync_shared_secret_reject":
        return False, str(resp.get("reason") or "отклонено")
    return False, "неожиданный ответ"


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
        ping = merge_outgoing_shared_secret({"type": "ping"})
        s.sendall(json.dumps(ping, ensure_ascii=False).encode("utf-8"))
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


def scan_lan_subnet_for_portal_hosts(
    my_ip: str,
    *,
    port: int = PORTAL_PORT,
    timeout: float = 0.2,
    max_workers: int = 56,
) -> List[str]:
    """
    Фаза A LAN: скан подсети /24 вокруг my_ip, TCP + ping Portal (как probe_portal_peer).
    """
    my_ip = (my_ip or "").strip()
    if not my_ip:
        return []
    parts = my_ip.rsplit(".", 1)
    if len(parts) != 2:
        return []
    prefix = parts[0]
    hosts = [f"{prefix}.{i}" for i in range(1, 255) if f"{prefix}.{i}" != my_ip]
    found: List[str] = []
    lock = threading.Lock()

    def check(host: str) -> None:
        ok, _code = probe_portal_peer(host, port=port, timeout=timeout)
        if ok:
            with lock:
                found.append(host)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        list(ex.map(check, hosts))
    found.sort(key=lambda ip: tuple(int(x) for x in ip.split(".")))
    return found


def parse_portal_json_message(data: bytes) -> Optional[dict]:
    """
    Разбор первого JSON-объекта из буфера (ping/pong и др.).
    Устойчиво к пробелам и лишнему тексту до/после — как при разных recv на Windows/macOS.
    """
    msg, _ = parse_first_json_object_bytes(data)
    return msg


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


def wire_ctk_entry_paste(entry: Any) -> None:
    """
    Явная вставка из буфера для CTkEntry.
    - Русская раскладка: Tk часто НЕ шлёт <Control-v>, а даёт keysym «м» при той же физ. клавише — ловим <Control-KeyPress> + keycode 86.
    - Буфер: сначала Tk clipboard (как в обычных полях), затем pyperclip.
    """
    import tkinter as tk

    if entry is None:
        return

    inner = getattr(entry, "_entry", None)

    def _clipboard_read() -> str:
        for w in (
            entry,
            inner,
            getattr(entry, "master", None),
        ):
            if w is None:
                continue
            try:
                top = w.winfo_toplevel()
            except Exception:
                top = None
            for widget in (w, top):
                if widget is None:
                    continue
                try:
                    t = widget.clipboard_get()
                    if t is not None and str(t) != "":
                        return str(t)
                except tk.TclError:
                    pass
                except Exception:
                    pass
        try:
            t = pyperclip.paste()
            return "" if t is None else str(t)
        except Exception:
            return ""

    def _paste(event=None):
        raw = _clipboard_read()
        s = str(raw).replace("\r\n", "\n")
        line = s.split("\n", 1)[0]
        if "\r" in line:
            line = line.split("\r", 1)[0]
        try:
            w = inner if inner is not None else entry
            if hasattr(w, "selection_present") and w.selection_present():
                entry.delete("sel.first", "sel.last")
        except Exception:
            try:
                entry.delete("sel.first", "sel.last")
            except Exception:
                pass
        try:
            entry.insert("insert", line)
        except Exception:
            try:
                entry.insert("end", line)
            except Exception:
                pass
        return "break"

    def _control_keypress_paste(event):
        """Ctrl+физическая V (RU/EN): keycode 86 на Windows; плюс keysym v / м."""
        if not (event.state & 0x0004):
            return
        ks = (event.keysym or "")
        kc = int(getattr(event, "keycode", 0) or 0)
        # keysym: EN «v» / RU «м» на той же клавише; keycode 86 — физ. V на Windows
        if ks.lower() == "v" or ks in ("м", "М"):
            return _paste(event)
        if platform.system() == "win32" and kc == 86:
            return _paste(event)
        return None

    # Только один виджет: CTkEntry.bind() уже проксирует на _entry — не дублировать.
    bind_targets = [inner] if inner is not None else [entry]
    for w in bind_targets:
        try:
            w.bind("<Control-KeyPress>", _control_keypress_paste, add=True)
        except Exception:
            pass

    for seq in (
        "<<Paste>>",
        "<Control-v>",
        "<Control-V>",
        "<Shift-Insert>",
    ):
        for w in bind_targets:
            try:
                w.bind(seq, _paste, add=True)
            except Exception:
                pass
    if platform.system() == "Darwin":
        for seq in ("<Command-v>", "<Command-V>", "<Meta-v>", "<Meta-V>"):
            for w in bind_targets:
                try:
                    w.bind(seq, _paste, add=True)
                except Exception:
                    pass


def wire_ctk_textbox_paste(tb: Any) -> None:
    """Многострочная вставка для CTkTextbox (список IP и т.п.): RU-раскладка + Tk clipboard + pyperclip."""
    import tkinter as tk

    if tb is None:
        return

    inner = getattr(tb, "_textbox", None)

    def _clipboard_read() -> str:
        for w in (tb, inner, getattr(tb, "master", None)):
            if w is None:
                continue
            try:
                top = w.winfo_toplevel()
            except Exception:
                top = None
            for widget in (w, top):
                if widget is None:
                    continue
                try:
                    t = widget.clipboard_get()
                    if t is not None and str(t) != "":
                        return str(t)
                except tk.TclError:
                    pass
                except Exception:
                    pass
        try:
            t = pyperclip.paste()
            return "" if t is None else str(t)
        except Exception:
            return ""

    def _paste(event=None):
        raw = _clipboard_read()
        s = str(raw).replace("\r\n", "\n").replace("\r", "\n")
        try:
            w = inner if inner is not None else tb
            if hasattr(w, "tag_ranges") and w.tag_ranges(tk.SEL):
                tb.delete("sel.first", "sel.last")
        except Exception:
            try:
                tb.delete("sel.first", "sel.last")
            except Exception:
                pass
        try:
            tb.insert("insert", s)
        except Exception:
            try:
                tb.insert("end", s)
            except Exception:
                pass
        return "break"

    def _control_keypress_paste(event):
        if not (event.state & 0x0004):
            return
        ks = (event.keysym or "")
        kc = int(getattr(event, "keycode", 0) or 0)
        if ks.lower() == "v" or ks in ("м", "М"):
            return _paste(event)
        if platform.system() == "win32" and kc == 86:
            return _paste(event)
        return None

    bind_targets = [inner] if inner is not None else [tb]
    for w in bind_targets:
        try:
            w.bind("<Control-KeyPress>", _control_keypress_paste, add=True)
        except Exception:
            pass

    for seq in (
        "<<Paste>>",
        "<Control-v>",
        "<Control-V>",
        "<Shift-Insert>",
    ):
        for w in bind_targets:
            try:
                w.bind(seq, _paste, add=True)
            except Exception:
                pass
    if platform.system() == "Darwin":
        for seq in ("<Command-v>", "<Command-V>", "<Meta-v>", "<Meta-V>"):
            for w in bind_targets:
                try:
                    w.bind(seq, _paste, add=True)
                except Exception:
                    pass


class PortalApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title(i18n.tr("app.title"))
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
        self._widget_pulse_generation: int = 0
        self._widget_preset_rule_rows: List[Dict[str, Any]] = []
        self._settings_win: Optional[ctk.CTkToplevel] = None
        self._log_win: Optional[ctk.CTkToplevel] = None
        self._apk_win: Optional[ctk.CTkToplevel] = None
        self._help_win: Optional[ctk.CTkToplevel] = None
        self._history_win: Optional[ctk.CTkToplevel] = None
        self._history_scroll: Optional[Any] = None
        self._history_filter_entry: Optional[Any] = None
        self._lan_win: Optional[ctk.CTkToplevel] = None

        # Стандартное медиа из assets → сразу в config, чтобы поле «Медиа» не было пустым
        try:
            portal_config.ensure_widget_media_path_persisted()
        except Exception:
            pass
        
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
        """Создание интерфейса: верхняя панель + главный скролл; настройки/APK/лог/справка — отдельные окна."""
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        ctk.CTkLabel(
            toolbar,
            text=i18n.tr("app.title"),
            font=ctk.CTkFont(size=20, weight="bold"),
        ).pack(side="left", padx=(0, 14))
        ctk.CTkButton(
            toolbar,
            text=i18n.tr("toolbar.settings"),
            width=118,
            command=self._open_settings_window,
            font=ctk.CTkFont(size=13),
        ).pack(side="left", padx=3)
        ctk.CTkButton(
            toolbar,
            text=i18n.tr("toolbar.apk"),
            width=82,
            command=self._open_apk_window,
            font=ctk.CTkFont(size=13),
        ).pack(side="left", padx=3)
        ctk.CTkButton(
            toolbar,
            text=i18n.tr("toolbar.log"),
            width=100,
            command=self._open_log_window,
            font=ctk.CTkFont(size=13),
        ).pack(side="left", padx=3)
        ctk.CTkButton(
            toolbar,
            text=i18n.tr("toolbar.history"),
            width=100,
            command=self._open_history_window,
            font=ctk.CTkFont(size=13),
        ).pack(side="left", padx=3)
        ctk.CTkButton(
            toolbar,
            text=i18n.tr("toolbar.help"),
            width=40,
            command=self._open_help_window,
            font=ctk.CTkFont(size=14),
        ).pack(side="left", padx=3)

        outer = ctk.CTkFrame(self, fg_color="transparent")
        outer.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 8))
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(0, weight=1)
        main_frame = ctk.CTkScrollableFrame(outer, fg_color="transparent")
        main_frame.grid(row=0, column=0, sticky="nsew")

        ctk.CTkLabel(
            main_frame,
            text=i18n.tr("main.subtitle"),
            font=ctk.CTkFont(size=13),
            text_color="gray",
        ).pack(pady=(10, 14))
        
        # Информация о подключении
        info_frame = ctk.CTkFrame(main_frame)
        info_frame.pack(fill="x", padx=20, pady=10)
        
        if self.tailscale_ip:
            if self.tailscale_ip.startswith("100."):
                ip_label = ctk.CTkLabel(
                    info_frame,
                    text=i18n.tr("main.ip_tailscale", ip=self.tailscale_ip),
                    font=ctk.CTkFont(size=12)
                )
                ip_label.pack(pady=10)
            else:
                ip_label = ctk.CTkLabel(
                    info_frame,
                    text=i18n.tr("main.ip_local", ip=self.tailscale_ip),
                    font=ctk.CTkFont(size=12),
                    text_color="orange"
                )
                ip_label.pack(pady=10)
        else:
            warning_label = ctk.CTkLabel(
                info_frame,
                text=i18n.tr("main.ip_unknown"),
                font=ctk.CTkFont(size=12),
                text_color="orange"
            )
            warning_label.pack(pady=10)
        
        peer_frame = ctk.CTkFrame(main_frame)
        peer_frame.pack(fill="x", padx=20, pady=(0, 10))

        self._peer_targets_heading = ctk.CTkLabel(
            peer_frame,
            text="",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self._refresh_peer_targets_heading()
        self._main_secret_frame = ctk.CTkFrame(peer_frame)
        ctk.CTkLabel(
            self._main_secret_frame,
            text=i18n.tr("main.network_password"),
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", padx=4, pady=(0, 4))
        _msr = ctk.CTkFrame(self._main_secret_frame, fg_color="transparent")
        _msr.pack(fill="x")
        self.main_secret_entry = ctk.CTkEntry(
            _msr, width=240, placeholder_text=i18n.tr("main.secret_placeholder")
        )
        self.main_secret_entry.pack(side="left", padx=(0, 8))
        wire_ctk_entry_paste(self.main_secret_entry)
        ctk.CTkButton(
            _msr,
            text=i18n.tr("main.save_password"),
            width=130,
            command=self._save_main_secret_banner,
            font=ctk.CTkFont(size=12),
        ).pack(side="left")
        ctk.CTkLabel(
            self._main_secret_frame,
            text=i18n.tr("main.secret_hint"),
            font=ctk.CTkFont(size=10),
            text_color="gray",
        ).pack(anchor="w", padx=4, pady=(4, 0))

        self._peer_targets_heading.pack(anchor="w", padx=12, pady=(8, 4))
        self.peer_select_frame = ctk.CTkFrame(peer_frame, fg_color="transparent", height=42)
        self.peer_select_frame.pack(fill="x", padx=12, pady=(0, 4))
        try:
            self.peer_select_frame.pack_propagate(False)
        except Exception:
            pass
        self.rebuild_peer_checkboxes()
        ctk.CTkButton(
            peer_frame,
            text=i18n.tr("main.save_recipients"),
            width=210,
            command=self.save_peer_selection_from_ui,
            font=ctk.CTkFont(size=12),
        ).pack(anchor="w", padx=12, pady=(8, 4))
        self.ip_saved_feedback = ctk.CTkLabel(
            peer_frame,
            text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#3dd68c",
        )
        self.ip_saved_feedback.pack(anchor="w", padx=12, pady=(0, 4))
        self._refresh_main_secret_banner_visibility()

        # Статус связи с парой (ping/pong к Порталу на другом ПК)
        self._peer_poll_job = None
        conn_frame = ctk.CTkFrame(peer_frame, fg_color="transparent")
        conn_frame.pack(fill="x", padx=12, pady=(4, 10))
        ctk.CTkLabel(
            conn_frame,
            text=i18n.tr("main.conn_title"),
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", pady=(0, 4))
        self.local_link_status_label = ctk.CTkLabel(
            conn_frame,
            text=i18n.tr("main.local_recv_unknown"),
            font=ctk.CTkFont(size=12),
            text_color="gray",
            justify="left",
            anchor="w",
        )
        self.local_link_status_label.pack(anchor="w")
        self.peer_link_status_label = ctk.CTkLabel(
            conn_frame,
            text=i18n.tr("main.peers_idle"),
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
            text=i18n.tr("main.probe_btn"),
            width=160,
            command=lambda: self.check_peer_connection_async(silent=False),
            font=ctk.CTkFont(size=12),
        ).pack(side="left")
        ctk.CTkButton(
            probe_row,
            text=i18n.tr("main.lan_find_btn"),
            width=150,
            command=self._open_lan_scan_window,
            font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=(10, 0))
        ctk.CTkLabel(
            probe_row,
            text=i18n.tr("main.probe_auto", sec=PEER_STATUS_POLL_MS // 1000),
            font=ctk.CTkFont(size=11),
            text_color="gray",
        ).pack(side="left", padx=(12, 0))
        
        # Кнопки управления
        button_frame = ctk.CTkFrame(main_frame)
        button_frame.pack(fill="x", padx=20, pady=20)
        
        self.start_button = ctk.CTkButton(
            button_frame,
            text=i18n.tr("btn.start"),
            command=self.toggle_server,
            font=ctk.CTkFont(size=14, weight="bold"),
            height=40
        )
        self.start_button.pack(side="left", padx=10, pady=10, fill="x", expand=True)
        
        self.send_button = ctk.CTkButton(
            button_frame,
            text=i18n.tr("btn.send_file"),
            command=self.send_file_dialog,
            font=ctk.CTkFont(size=14),
            height=40,
            state="disabled"
        )
        self.send_button.pack(side="left", padx=10, pady=10, fill="x", expand=True)
        
        self.clipboard_button = ctk.CTkButton(
            button_frame,
            text=i18n.tr("btn.send_clipboard"),
            command=self.send_clipboard_dialog,
            font=ctk.CTkFont(size=14),
            height=40,
            state="disabled"
        )
        self.clipboard_button.pack(side="left", padx=10, pady=10, fill="x", expand=True)
        
        # Статус
        self.status_label = ctk.CTkLabel(
            main_frame,
            text=i18n.tr("status.stopped"),
            font=ctk.CTkFont(size=12),
            text_color="gray"
        )
        self.status_label.pack(pady=10)
        
        self._setup_floating_log_window()


        self._refresh_local_link_status_label()
        self.after(800, lambda: self.check_peer_connection_async(silent=True))
        self._arm_peer_poll()
        self.after(
            200,
            lambda: self.log(
                i18n.tr(
                    "log.journal_hint",
                    path=str(portal_config.activity_log_path()),
                )
            ),
        )
        self.after(500, self._auto_start_portal_if_enabled)

    def _refresh_peer_targets_heading(self) -> None:
        if not hasattr(self, "_peer_targets_heading"):
            return
        if platform.system() == "Darwin":
            _hk = (
                "Cmd+Shift+C"
                if os.environ.get("PORTAL_MAC_HOTKEY_LEGACY", "").strip().lower()
                in ("1", "true", "yes")
                else "Cmd+Ctrl+C"
            )
        else:
            _hk = "Ctrl+Alt+C"
        self._peer_targets_heading.configure(text=i18n.tr("main.peer_heading", hk=_hk))

    def _save_ui_language_from_settings(self) -> None:
        from tkinter import messagebox

        label = self._ui_lang_menu.get()
        lang = self._lang_display_to_code.get(label, "ru")
        if portal_config.save_ui_language(lang):
            messagebox.showinfo(
                i18n.tr("lang.saved_title"),
                i18n.tr("lang.restart_hint"),
            )

    def _refresh_main_secret_banner_visibility(self) -> None:
        if not hasattr(self, "_main_secret_frame") or not hasattr(
            self, "_peer_targets_heading"
        ):
            return
        if portal_config.load_shared_secret():
            try:
                self._main_secret_frame.pack_forget()
            except Exception:
                pass
        else:
            try:
                self._main_secret_frame.pack(
                    fill="x",
                    padx=12,
                    pady=(4, 10),
                    before=self._peer_targets_heading,
                )
            except Exception:
                try:
                    self._main_secret_frame.pack(fill="x", padx=12, pady=(4, 10))
                except Exception:
                    pass

    def _save_main_secret_banner(self) -> None:
        if not hasattr(self, "main_secret_entry"):
            return
        raw = self.main_secret_entry.get().strip()
        if not raw:
            self.log("⚠️ Введи пароль или оставь пустым и задай в Настройках")
            return
        if portal_config.save_shared_secret(raw):
            self.log("✅ Пароль сохранён")
            try:
                self.main_secret_entry.delete(0, "end")
            except Exception:
                pass
            self._refresh_main_secret_banner_visibility()
            self._sync_settings_secret_entry_from_config()

    def _sync_settings_secret_entry_from_config(self) -> None:
        if not hasattr(self, "shared_secret_entry"):
            return
        try:
            self.shared_secret_entry.delete(0, "end")
            s = portal_config.load_shared_secret()
            if s:
                self.shared_secret_entry.insert(0, s)
        except Exception:
            pass

    def _on_settings_closed(self) -> None:
        try:
            self.rebuild_peer_checkboxes()
            self._sync_settings_secret_entry_from_config()
            self._refresh_main_secret_banner_visibility()
        except Exception:
            pass

    def _open_settings_window(self) -> None:
        if self._settings_win is not None:
            try:
                if self._settings_win.winfo_exists():
                    self._settings_win.deiconify()
                    self._settings_win.lift()
                    self._settings_win.focus_force()
                    self._refresh_settings_preset_rules_ui()
                    return
            except Exception:
                self._settings_win = None
        win = ctk.CTkToplevel(self)
        win.title(i18n.tr("settings.title"))
        win.geometry("760x640")
        win.minsize(640, 520)
        try:
            win.transient(self)
        except Exception:
            pass
        self._settings_win = win
        self._build_settings_window_content(win)
        win.protocol("WM_DELETE_WINDOW", lambda: self._hide_settings_window())

    def _hide_settings_window(self) -> None:
        if self._settings_win is not None:
            try:
                self._on_settings_closed()
                self._settings_win.withdraw()
            except Exception:
                pass

    def _build_settings_window_content(self, win: ctk.CTkToplevel) -> None:
        try:
            if win.winfo_children():
                return
        except Exception:
            pass
        tab = ctk.CTkTabview(win)
        tab.pack(fill="both", expand=True, padx=10, pady=10)

        t_gen = tab.add(i18n.tr("settings.tab_general"))
        ctk.CTkLabel(
            t_gen,
            text=i18n.tr("settings.ui_language"),
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", padx=8, pady=(8, 4))
        lang_row = ctk.CTkFrame(t_gen, fg_color="transparent")
        lang_row.pack(fill="x", padx=8, pady=(0, 4))
        self._lang_display_to_code = {"Русский": "ru", "English": "en"}
        _cur_lang = portal_config.load_ui_language()
        self._ui_lang_menu = ctk.CTkOptionMenu(
            lang_row,
            values=["Русский", "English"],
            width=200,
            font=ctk.CTkFont(size=13),
        )
        self._ui_lang_menu.set("English" if _cur_lang == "en" else "Русский")
        self._ui_lang_menu.pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            lang_row,
            text=i18n.tr("settings.save_language"),
            width=170,
            command=self._save_ui_language_from_settings,
            font=ctk.CTkFont(size=12),
        ).pack(side="left")
        ctk.CTkLabel(
            t_gen,
            text=i18n.tr("settings.lang_note"),
            font=ctk.CTkFont(size=11),
            text_color="gray",
            wraplength=680,
            justify="left",
        ).pack(anchor="w", padx=8, pady=(0, 12))

        t_recv = tab.add(i18n.tr("settings.tab_recv"))
        t_widget = tab.add(i18n.tr("settings.tab_widget"))
        t_peers = tab.add(i18n.tr("settings.tab_peers"))
        t_secret = tab.add(i18n.tr("settings.tab_secret"))

        ctk.CTkLabel(
            t_recv,
            text=i18n.tr("recv.incoming_folder"),
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", padx=8, pady=(8, 4))
        ctk.CTkLabel(
            t_recv,
            text=i18n.tr("recv.incoming_hint"),
            font=ctk.CTkFont(size=11),
            text_color="gray",
        ).pack(anchor="w", padx=8, pady=(0, 6))
        recv_row = ctk.CTkFrame(t_recv, fg_color="transparent")
        recv_row.pack(fill="x", padx=8, pady=(0, 8))
        self.receive_dir_entry = ctk.CTkEntry(
            recv_row, width=400, placeholder_text="~/Desktop"
        )
        self.receive_dir_entry.pack(side="left", padx=(0, 8))
        try:
            self.receive_dir_entry.insert(0, str(portal_config.receive_dir_path()))
        except Exception:
            pass
        wire_ctk_entry_paste(self.receive_dir_entry)
        ctk.CTkButton(
            recv_row,
            text=i18n.tr("recv.browse"),
            width=88,
            command=self.choose_receive_dir,
            font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            recv_row,
            text=i18n.tr("recv.save_folder"),
            width=130,
            command=self.save_receive_dir_from_ui,
            font=ctk.CTkFont(size=12),
        ).pack(side="left")
        self.receive_dir_feedback = ctk.CTkLabel(
            recv_row, text="", font=ctk.CTkFont(size=12), text_color="gray"
        )
        self.receive_dir_feedback.pack(side="left", padx=(8, 0))

        ctk.CTkLabel(
            t_recv,
            text=i18n.tr("recv.per_ip_title"),
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", padx=8, pady=(12, 4))
        ctk.CTkLabel(
            t_recv,
            text=i18n.tr("recv.per_ip_hint"),
            font=ctk.CTkFont(size=11),
            text_color="gray",
            wraplength=680,
            justify="left",
        ).pack(anchor="w", padx=8, pady=(0, 4))
        peer_recv_wrap = ctk.CTkFrame(t_recv, fg_color="transparent")
        peer_recv_wrap.pack(fill="both", expand=False, padx=8, pady=(0, 8))
        self._peer_recv_dirs_scroll = ctk.CTkScrollableFrame(
            peer_recv_wrap, height=220, fg_color="transparent"
        )
        self._peer_recv_dirs_scroll.pack(fill="both", expand=True)
        self._peer_recv_dir_rows = []
        pr_btn_row = ctk.CTkFrame(peer_recv_wrap, fg_color="transparent")
        pr_btn_row.pack(fill="x", pady=(10, 0))
        ctk.CTkButton(
            pr_btn_row,
            text=i18n.tr("recv.save_ip_list"),
            width=180,
            command=self.save_peer_receive_dirs_from_ui,
            font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=(0, 8))
        self.peer_receive_dirs_feedback = ctk.CTkLabel(
            pr_btn_row, text="", font=ctk.CTkFont(size=11), text_color="gray"
        )
        self.peer_receive_dirs_feedback.pack(side="left")
        self._rebuild_peer_receive_dir_rows()

        ctk.CTkLabel(
            t_recv,
            text=i18n.tr("recv.mode_title"),
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", padx=8, pady=(16, 4))
        self._receive_files_mode_labels = {
            "both": i18n.tr("recv_mode.both"),
            "disk_only": i18n.tr("recv_mode.disk_only"),
            "clipboard_only": i18n.tr("recv_mode.clipboard_only"),
        }
        rm_row = ctk.CTkFrame(t_recv, fg_color="transparent")
        rm_row.pack(fill="x", padx=8, pady=(0, 10))
        self.receive_mode_menu = ctk.CTkOptionMenu(
            rm_row,
            values=list(self._receive_files_mode_labels.values()),
            command=self._on_receive_files_mode_menu,
            width=440,
            font=ctk.CTkFont(size=12),
        )
        self.receive_mode_menu.pack(side="left", padx=(0, 8))
        cur_m = portal_config.receive_files_mode()
        self.receive_mode_menu.set(
            self._receive_files_mode_labels.get(
                cur_m, self._receive_files_mode_labels["both"]
            )
        )

        ctk.CTkLabel(
            t_widget,
            text=i18n.tr("widget.media_title"),
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", padx=8, pady=(8, 4))
        wm_row1 = ctk.CTkFrame(t_widget, fg_color="transparent")
        wm_row1.pack(fill="x", padx=8, pady=(0, 4))
        self.widget_media_entry = ctk.CTkEntry(
            wm_row1,
            width=360,
            placeholder_text=i18n.tr("widget.media_placeholder"),
            font=ctk.CTkFont(size=12),
        )
        self.widget_media_entry.pack(side="left", padx=(0, 8))
        try:
            _wmp = portal_config.effective_widget_media_path()
            if _wmp:
                self.widget_media_entry.insert(0, _wmp)
        except Exception:
            pass
        wire_ctk_entry_paste(self.widget_media_entry)
        ctk.CTkButton(
            wm_row1,
            text=i18n.tr("recv.browse"),
            width=88,
            command=self.choose_widget_media_file,
            font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            wm_row1,
            text=i18n.tr("widget.video_gif"),
            width=100,
            command=self.choose_widget_video_convert_to_gif,
            font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            wm_row1,
            text=i18n.tr("widget.reset"),
            width=72,
            command=self.clear_widget_media_from_ui,
            font=ctk.CTkFont(size=12),
        ).pack(side="left")
        wm_row2 = ctk.CTkFrame(t_widget, fg_color="transparent")
        wm_row2.pack(fill="x", padx=8, pady=(0, 6))
        self._widget_media_mode_labels_ru = i18n.widget_media_mode_labels()
        self._widget_media_mode_rev = {
            v: k for k, v in self._widget_media_mode_labels_ru.items()
        }
        self.widget_media_mode_menu = ctk.CTkOptionMenu(
            wm_row2,
            values=list(self._widget_media_mode_labels_ru.values()),
            command=lambda _c: None,
            width=460,
            font=ctk.CTkFont(size=12),
        )
        self.widget_media_mode_menu.pack(side="left", padx=(0, 8))
        _wmm = portal_config.load_widget_media_mode()
        self.widget_media_mode_menu.set(
            self._widget_media_mode_labels_ru.get(
                _wmm, self._widget_media_mode_labels_ru["auto"]
            )
        )
        ctk.CTkButton(
            wm_row2,
            text=i18n.tr("widget.save_look"),
            width=168,
            command=self.save_widget_media_from_ui,
            font=ctk.CTkFont(size=12),
        ).pack(side="left")
        wm_geo = ctk.CTkFrame(t_widget, fg_color="transparent")
        wm_geo.pack(fill="x", padx=8, pady=(10, 4))
        ctk.CTkLabel(
            wm_geo, text=i18n.tr("widget.size_px"), font=ctk.CTkFont(size=12)
        ).pack(side="left", padx=(0, 6))
        self.widget_size_entry = ctk.CTkEntry(
            wm_geo, width=56, font=ctk.CTkFont(size=12)
        )
        self.widget_size_entry.pack(side="left", padx=(0, 10))
        self.widget_size_entry.insert(0, str(portal_config.load_widget_size()))
        wire_ctk_entry_paste(self.widget_size_entry)
        ctk.CTkLabel(wm_geo, text=i18n.tr("widget.corner"), font=ctk.CTkFont(size=12)).pack(
            side="left", padx=(0, 6)
        )
        self._widget_corner_labels_ru = i18n.widget_corner_labels()
        self._widget_corner_rev = {
            v: k for k, v in self._widget_corner_labels_ru.items()
        }
        self.widget_corner_menu = ctk.CTkOptionMenu(
            wm_geo,
            values=list(self._widget_corner_labels_ru.values()),
            command=lambda _c: None,
            width=168,
            font=ctk.CTkFont(size=12),
        )
        self.widget_corner_menu.pack(side="left", padx=(0, 10))
        _wc = portal_config.load_widget_corner()
        self.widget_corner_menu.set(
            self._widget_corner_labels_ru.get(_wc, self._widget_corner_labels_ru["br"])
        )
        ctk.CTkLabel(
            wm_geo, text=i18n.tr("widget.margin_x"), font=ctk.CTkFont(size=12)
        ).pack(side="left", padx=(0, 4))
        self.widget_margin_x_entry = ctk.CTkEntry(
            wm_geo, width=44, font=ctk.CTkFont(size=12)
        )
        self.widget_margin_x_entry.pack(side="left", padx=(0, 8))
        self.widget_margin_x_entry.insert(0, str(portal_config.load_widget_margin_x()))
        wire_ctk_entry_paste(self.widget_margin_x_entry)
        ctk.CTkLabel(wm_geo, text=i18n.tr("widget.margin_y"), font=ctk.CTkFont(size=12)).pack(
            side="left", padx=(0, 4)
        )
        self.widget_margin_y_entry = ctk.CTkEntry(
            wm_geo, width=44, font=ctk.CTkFont(size=12)
        )
        self.widget_margin_y_entry.pack(side="left", padx=(0, 8))
        self.widget_margin_y_entry.insert(0, str(portal_config.load_widget_margin_y()))
        wire_ctk_entry_paste(self.widget_margin_y_entry)
        ctk.CTkButton(
            wm_geo,
            text=i18n.tr("widget.save_geo"),
            width=178,
            command=self.save_widget_geometry_from_ui,
            font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=(4, 0))
        ctk.CTkLabel(
            t_widget,
            text=i18n.tr("widget.hint_geo"),
            font=ctk.CTkFont(size=11),
            text_color="gray",
            wraplength=680,
            justify="left",
        ).pack(anchor="w", padx=8, pady=(8, 8))

        ctk.CTkLabel(
            t_widget,
            text=i18n.tr("widget.pulse_title"),
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", padx=8, pady=(16, 4))
        ctk.CTkLabel(
            t_widget,
            text=i18n.tr("widget.pulse_hint"),
            font=ctk.CTkFont(size=11),
            text_color="gray",
            wraplength=680,
            justify="left",
        ).pack(anchor="w", padx=8, pady=(0, 6))
        prev_row = ctk.CTkFrame(t_widget, fg_color="transparent")
        prev_row.pack(fill="x", padx=8, pady=(0, 8))
        self._widget_preset_preview_combo = ctk.CTkComboBox(
            prev_row,
            width=420,
            values=["…"],
            font=ctk.CTkFont(size=12),
            state="readonly",
        )
        self._widget_preset_preview_combo.pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            prev_row,
            text=i18n.tr("widget.preview_btn"),
            width=200,
            command=self.preview_widget_preset_from_settings_ui,
            font=ctk.CTkFont(size=12),
        ).pack(side="left")
        self._refresh_widget_preset_preview_menu_from_catalog()

        ctk.CTkLabel(
            t_widget,
            text=i18n.tr("widget.rules_hint"),
            font=ctk.CTkFont(size=11),
            text_color="gray",
            wraplength=680,
            justify="left",
        ).pack(anchor="w", padx=8, pady=(0, 4))
        ctk.CTkLabel(
            t_widget,
            text=i18n.tr("widget.rules_rows_intro"),
            font=ctk.CTkFont(size=11),
            text_color="gray",
            wraplength=680,
            justify="left",
        ).pack(anchor="w", padx=8, pady=(0, 6))
        wpr_row = ctk.CTkFrame(t_widget, fg_color="transparent")
        wpr_row.pack(fill="x", padx=8, pady=(0, 8))
        ctk.CTkButton(
            wpr_row,
            text=i18n.tr("widget.add_rule"),
            width=280,
            command=self._widget_preset_add_rule_row,
            font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            wpr_row,
            text=i18n.tr("widget.save_rules"),
            width=200,
            command=self.save_widget_preset_rules_from_ui,
            font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=(0, 8))
        self.widget_preset_rules_feedback = ctk.CTkLabel(
            wpr_row, text="", font=ctk.CTkFont(size=12), text_color="gray"
        )
        self.widget_preset_rules_feedback.pack(side="left")
        hdr = ctk.CTkFrame(t_widget, fg_color="transparent")
        hdr.pack(fill="x", padx=8, pady=(0, 2))
        ctk.CTkLabel(
            hdr,
            text=i18n.tr("widget.rules_col_peer"),
            width=160,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="gray",
            anchor="w",
        ).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(
            hdr,
            text=i18n.tr("widget.rules_col_event"),
            width=200,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="gray",
            anchor="w",
        ).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(
            hdr,
            text=i18n.tr("widget.rules_col_preset"),
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="gray",
            anchor="w",
        ).pack(side="left", padx=(0, 6), fill="x", expand=True)
        ctk.CTkLabel(hdr, text=i18n.tr("widget.rules_col_del"), width=40).pack(
            side="left", padx=(4, 0)
        )
        self._widget_preset_rules_scroll = ctk.CTkScrollableFrame(
            t_widget, height=220, fg_color="transparent"
        )
        self._widget_preset_rules_scroll.pack(fill="x", padx=8, pady=(0, 6))
        self._rebuild_widget_preset_rule_rows()

        ctk.CTkLabel(
            t_peers,
            text=i18n.tr("peers.list_title"),
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", padx=8, pady=(8, 4))
        ip_edit_row = ctk.CTkFrame(t_peers, fg_color="transparent")
        ip_edit_row.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.peer_ips_text = ctk.CTkTextbox(
            ip_edit_row, width=440, height=180, font=ctk.CTkFont(size=13)
        )
        self.peer_ips_text.pack(side="left", padx=(0, 10), anchor="nw", fill="both", expand=True)
        self._fill_peer_ips_textbox()
        self.peer_ips_text.bind("<KeyRelease>", self._on_peer_ips_edited)
        wire_ctk_textbox_paste(self.peer_ips_text)
        btn_col = ctk.CTkFrame(ip_edit_row, fg_color="transparent")
        btn_col.pack(side="left", fill="y")
        ctk.CTkButton(
            btn_col,
            text=i18n.tr("peers.save_list"),
            width=130,
            command=self.save_peer_ips_from_ui,
            font=ctk.CTkFont(size=12),
        ).pack(pady=(0, 6))

        ctk.CTkLabel(
            t_secret,
            text=i18n.tr("secret.title"),
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", padx=8, pady=(8, 4))
        secret_row = ctk.CTkFrame(t_secret, fg_color="transparent")
        secret_row.pack(fill="x", padx=8, pady=(0, 8))
        self.shared_secret_entry = ctk.CTkEntry(
            secret_row,
            width=260,
            placeholder_text=i18n.tr("secret.placeholder"),
        )
        self.shared_secret_entry.pack(side="left", padx=(0, 8))
        try:
            _sec0 = portal_config.load_shared_secret()
            if _sec0:
                self.shared_secret_entry.insert(0, _sec0)
        except Exception:
            pass
        wire_ctk_entry_paste(self.shared_secret_entry)
        ctk.CTkButton(
            secret_row,
            text=i18n.tr("secret.fill"),
            width=100,
            command=self._generate_shared_secret_ui,
            font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            secret_row,
            text=i18n.tr("secret.save"),
            width=96,
            command=self._save_shared_secret_ui,
            font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            secret_row,
            text=i18n.tr("secret.copy"),
            width=96,
            command=self._copy_shared_secret_ui,
            font=ctk.CTkFont(size=12),
        ).pack(side="left")
        sync_btns = ctk.CTkFrame(t_secret, fg_color="transparent")
        sync_btns.pack(fill="x", padx=8, pady=(0, 6))
        ctk.CTkButton(
            sync_btns,
            text=i18n.tr("secret.gen_push"),
            height=36,
            command=self._generate_and_sync_shared_secret_ui,
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(fill="x", pady=(0, 6))
        ctk.CTkButton(
            sync_btns,
            text=i18n.tr("secret.push_field"),
            height=32,
            command=self._push_shared_secret_from_field_ui,
            font=ctk.CTkFont(size=12),
        ).pack(fill="x")
        ctk.CTkLabel(
            t_secret,
            text=i18n.tr("secret.long_hint"),
            font=ctk.CTkFont(size=11),
            text_color="gray",
            wraplength=680,
            justify="left",
        ).pack(anchor="w", padx=8, pady=(4, 8))
        ctk.CTkLabel(
            t_secret,
            text=i18n.tr("secret.banner_hint2"),
            font=ctk.CTkFont(size=11),
            text_color="gray",
            wraplength=680,
            justify="left",
        ).pack(anchor="w", padx=8, pady=(0, 8))

    def _open_apk_window(self) -> None:
        if self._apk_win is not None:
            try:
                if self._apk_win.winfo_exists():
                    self._apk_win.deiconify()
                    self._apk_win.lift()
                    return
            except Exception:
                self._apk_win = None
        w = ctk.CTkToplevel(self)
        w.title(i18n.tr("apk.title"))
        w.geometry("520x360")
        try:
            w.transient(self)
        except Exception:
            pass
        self._apk_win = w
        ctk.CTkLabel(
            w,
            text=i18n.tr("apk.heading"),
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(anchor="w", padx=14, pady=(14, 4))
        ctk.CTkLabel(
            w,
            text=i18n.tr("apk.blurb"),
            font=ctk.CTkFont(size=11),
            text_color="gray",
            wraplength=480,
            justify="left",
        ).pack(anchor="w", padx=14, pady=(0, 12))
        ctk.CTkButton(
            w,
            text=i18n.tr("apk.download"),
            height=44,
            command=self.download_portal_apk_from_github,
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(fill="x", padx=14, pady=(0, 10))
        row2 = ctk.CTkFrame(w, fg_color="transparent")
        row2.pack(fill="x", padx=14, pady=4)
        ctk.CTkButton(
            row2,
            text=i18n.tr("apk.open_release"),
            width=200,
            command=self.open_apk_release_page,
            font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            row2,
            text=i18n.tr("apk.build_gh"),
            width=160,
            command=self.trigger_android_apk_workflow,
            font=ctk.CTkFont(size=12),
        ).pack(side="left")
        ctk.CTkLabel(
            w,
            text=i18n.tr("apk.repo_hint"),
            font=ctk.CTkFont(size=11),
            text_color="gray",
        ).pack(anchor="w", padx=14, pady=(14, 4))
        row = ctk.CTkFrame(w, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=0)
        self.github_repo_entry = ctk.CTkEntry(
            row, width=220, placeholder_text="owner/repo"
        )
        self.github_repo_entry.pack(side="left", padx=(0, 8))
        try:
            self.github_repo_entry.insert(0, portal_config.load_github_repo())
        except Exception:
            self.github_repo_entry.insert(0, portal_config.DEFAULT_GITHUB_REPO)
        wire_ctk_entry_paste(self.github_repo_entry)
        ctk.CTkButton(
            row,
            text=i18n.tr("apk.save"),
            width=100,
            command=self.save_github_repo_from_ui,
            font=ctk.CTkFont(size=12),
        ).pack(side="left")
        ctk.CTkLabel(
            w,
            text=i18n.tr("apk.token_hint"),
            font=ctk.CTkFont(size=10),
            text_color="gray",
            wraplength=480,
            justify="left",
        ).pack(anchor="w", padx=14, pady=(12, 14))

    def _open_log_window(self) -> None:
        if self._log_win is not None:
            try:
                if self._log_win.winfo_exists():
                    self._log_win.deiconify()
                    self._log_win.lift()
                    return
            except Exception:
                self._log_win = None
        self._setup_floating_log_window()
        if self._log_win is not None:
            self._log_win.deiconify()
            self._log_win.lift()

    def _open_help_window(self) -> None:
        if self._help_win is not None:
            try:
                if self._help_win.winfo_exists():
                    self._help_win.deiconify()
                    self._help_win.lift()
                    return
            except Exception:
                self._help_win = None
        h = ctk.CTkToplevel(self)
        h.title(i18n.tr("help.title"))
        h.geometry("620x480")
        try:
            h.transient(self)
        except Exception:
            pass
        self._help_win = h
        txt = ctk.CTkTextbox(h, wrap="word", font=ctk.CTkFont(size=13))
        txt.pack(fill="both", expand=True, padx=10, pady=10)
        txt.insert("1.0", self._hotkey_help_text())
        txt.configure(state="disabled")

    def _hotkey_help_text(self) -> str:
        is_mac = platform.system() == "Darwin"
        mac_legacy = os.environ.get("PORTAL_MAC_HOTKEY_LEGACY", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        return i18n.hotkey_help_text(is_mac, mac_legacy, sys.version_info >= (3, 13))

    def _open_history_window(self) -> None:
        if self._history_win is not None:
            try:
                if self._history_win.winfo_exists():
                    self._history_win.deiconify()
                    self._history_win.lift()
                    self._history_refresh_list()
                    return
            except Exception:
                self._history_win = None
        w = ctk.CTkToplevel(self)
        w.title(i18n.tr("history.title"))
        w.geometry("660x540")
        try:
            w.transient(self)
        except Exception:
            pass
        self._history_win = w
        top = ctk.CTkFrame(w, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=8)
        ctk.CTkLabel(top, text=i18n.tr("history.filter")).pack(side="left")
        self._history_filter_entry = ctk.CTkEntry(top, width=240)
        self._history_filter_entry.pack(side="left", padx=8)
        self._history_filter_entry.bind("<KeyRelease>", lambda _e: self._history_refresh_list())
        ctk.CTkButton(
            top,
            text=i18n.tr("history.refresh"),
            width=100,
            command=self._history_refresh_list,
        ).pack(side="left")
        self._history_scroll = ctk.CTkScrollableFrame(w)
        self._history_scroll.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self._history_refresh_list()

    def _history_refresh_list(self) -> None:
        sc = self._history_scroll
        if sc is None:
            return
        for ch in sc.winfo_children():
            ch.destroy()
        q = ""
        try:
            if self._history_filter_entry is not None:
                q = self._history_filter_entry.get()
        except Exception:
            pass
        try:
            portal_history.init_db()
            rows = portal_history.list_events(limit=150, search=q)
        except Exception as ex:
            ctk.CTkLabel(sc, text=str(ex)).pack(anchor="w", pady=6)
            return
        if not rows:
            ctk.CTkLabel(sc, text=i18n.tr("history.empty")).pack(anchor="w", pady=6)
            return
        for ev in rows:
            self._history_add_row(ev)

    def _history_add_row(self, ev: Dict[str, Any]) -> None:
        sc = self._history_scroll
        if sc is None:
            return
        fr = ctk.CTkFrame(sc)
        fr.pack(fill="x", pady=4)
        ts = float(ev.get("ts") or 0)
        tss = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
        d = ev.get("direction") or "?"
        k = ev.get("kind") or "?"
        who = ev.get("peer_label") or ev.get("peer_ip") or ""
        nm = ev.get("name") or ""
        line = f"{tss}  {d}/{k}  {who}"
        if nm:
            line += f"  {nm}"
        ctk.CTkLabel(
            fr,
            text=line[:220],
            anchor="w",
            justify="left",
            wraplength=560,
        ).pack(fill="x", padx=6, pady=2)
        btn_row = ctk.CTkFrame(fr, fg_color="transparent")
        btn_row.pack(fill="x", padx=4, pady=2)
        eid = int(ev["id"])
        ctk.CTkButton(
            btn_row,
            text=i18n.tr("history.resend"),
            width=110,
            command=lambda i=eid: self._history_resend(i),
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            btn_row,
            text=i18n.tr("history.copy"),
            width=110,
            command=lambda i=eid: self._history_copy(i),
        ).pack(side="left", padx=4)

    def _history_resend(self, event_id: int) -> None:
        ev = portal_history.get_event(event_id)
        if not ev:
            return
        if ev.get("kind") != "file":
            self.log(i18n.tr("history.resend_file_only"))
            return
        path = (ev.get("stored_path") or "").strip()
        if not path or not os.path.isfile(path):
            self.log(i18n.tr("history.missing_file"))
            return
        ips = portal_history.parse_route_ips(ev.get("route_json") or "")
        if not ips:
            p = (ev.get("peer_ip") or "").strip()
            ips = [p] if p else []
        if not ips:
            self.log(i18n.tr("history.no_targets"))
            return

        def work():
            for ip in ips:
                try:
                    self.send_file(path, ip)
                except Exception as ex:
                    msg = str(ex)
                    self.after(
                        0,
                        lambda m=msg: self.log(f"{i18n.tr('history.resend')}: {m}"),
                    )

        threading.Thread(target=work, daemon=True).start()
        self.log(i18n.tr("history.resend_started"))

    def _history_copy(self, event_id: int) -> None:
        ev = portal_history.get_event(event_id)
        if not ev:
            return
        path = (ev.get("stored_path") or "").strip()
        snip = (ev.get("snippet") or "").strip()
        if path:
            try:
                pyperclip.copy(path)
                self.log(i18n.tr("history.copied_path"))
            except Exception as e:
                self.log(str(e))
        elif snip:
            try:
                pyperclip.copy(snip)
                self.log(i18n.tr("history.copied_text"))
            except Exception as e:
                self.log(str(e))
        else:
            self.log(i18n.tr("history.nothing_to_copy"))

    def _open_lan_scan_window(self) -> None:
        base = (self.tailscale_ip or "").strip()
        if not base:
            self.log(i18n.tr("lan.no_local_ip"))
            return
        if self._lan_win is not None:
            try:
                if self._lan_win.winfo_exists():
                    self._lan_win.deiconify()
                    self._lan_win.lift()
                    return
            except Exception:
                self._lan_win = None
        w = ctk.CTkToplevel(self)
        w.title(i18n.tr("lan.title"))
        w.geometry("500x460")
        try:
            w.transient(self)
        except Exception:
            pass
        self._lan_win = w
        st = ctk.CTkLabel(w, text=i18n.tr("lan.scanning"))
        st.pack(pady=8)
        scroll = ctk.CTkScrollableFrame(w)
        scroll.pack(fill="both", expand=True, padx=10, pady=4)
        check_vars: Dict[str, tk.BooleanVar] = {}

        def finish(found: List[str]) -> None:
            st.configure(text=i18n.tr("lan.done", n=len(found)))
            for ch in scroll.winfo_children():
                ch.destroy()
            if not found:
                ctk.CTkLabel(scroll, text=i18n.tr("lan.none")).pack(anchor="w", pady=6)
                return
            for ip in found:
                row = ctk.CTkFrame(scroll, fg_color="transparent")
                row.pack(fill="x", pady=2)
                v = tk.BooleanVar(value=True)
                check_vars[ip] = v
                ctk.CTkCheckBox(row, text=ip, variable=v).pack(side="left")

        def work() -> None:
            found = scan_lan_subnet_for_portal_hosts(base)
            self.after(0, lambda: finish(found))

        threading.Thread(target=work, daemon=True).start()

        def add_selected() -> None:
            sel = [ip for ip, v in check_vars.items() if v.get()]
            if not sel:
                self.log(i18n.tr("lan.nothing_selected"))
                return
            have = list(portal_config.load_peer_ips())
            seen = set(have)
            added = [ip for ip in sel if ip not in seen]
            if not added:
                self.log(i18n.tr("lan.already_in_list"))
                return
            merged = have + added
            portal_config.save_peer_ips(merged)
            self.rebuild_peer_checkboxes()
            self.log(i18n.tr("lan.added", ips=", ".join(added)))

        btn_row = ctk.CTkFrame(w, fg_color="transparent")
        btn_row.pack(fill="x", pady=8)
        ctk.CTkButton(
            btn_row,
            text=i18n.tr("lan.add_btn"),
            command=add_selected,
        ).pack(side="left", padx=8)
        ctk.CTkButton(btn_row, text=i18n.tr("lan.close_btn"), command=w.destroy).pack(
            side="left", padx=8
        )

    def _setup_floating_log_window(self) -> None:
        if self._log_win is not None:
            try:
                if self._log_win.winfo_exists():
                    return
            except Exception:
                pass
        self._log_win = ctk.CTkToplevel(self)
        self._log_win.title(i18n.tr("logwin.title"))
        self._log_win.geometry("720x420")
        try:
            self._log_win.transient(self)
        except Exception:
            pass
        log_frame = ctk.CTkFrame(self._log_win)
        log_frame.pack(fill="both", expand=True, padx=8, pady=8)
        log_title_row = ctk.CTkFrame(log_frame, fg_color="transparent")
        log_title_row.pack(fill="x", padx=8, pady=(6, 4))
        ctk.CTkLabel(
            log_title_row,
            text=i18n.tr("logwin.heading"),
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(side="left")
        ctk.CTkButton(
            log_title_row,
            text=i18n.tr("logwin.copy_all"),
            width=120,
            command=self.copy_log_to_clipboard,
            font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=(12, 6))
        ctk.CTkButton(
            log_title_row,
            text=i18n.tr("logwin.copy_sel"),
            width=150,
            command=self.copy_log_selection_to_clipboard,
            font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            log_title_row,
            text=i18n.tr("logwin.open_folder"),
            width=110,
            command=self.open_log_folder,
            font=ctk.CTkFont(size=12),
        ).pack(side="left")
        self.log_hint_label = ctk.CTkLabel(
            log_frame,
            text=i18n.tr(
                "logwin.hint", path=str(portal_config.activity_log_path())
            ),
            font=ctk.CTkFont(size=11),
            text_color="gray",
            wraplength=680,
            justify="left",
            anchor="w",
        )
        self.log_hint_label.pack(fill="x", padx=8, pady=(0, 4))
        self.log_text = ctk.CTkTextbox(log_frame, height=280, wrap="word")
        self.log_text.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        # Восстанавливаем историю из файла — лог не обнуляется при закрытии окна
        self._log_max_lines = 800
        self._restore_log_from_file()
        self._setup_log_text_selectable()
        self.log_text.bind("<Command-c>", self._log_copy_selection_hotkey)
        self.log_text.bind("<Control-c>", self._log_copy_selection_hotkey)
        self._log_win.withdraw()

    def _auto_start_portal_if_enabled(self) -> None:
        if os.environ.get("PORTAL_NO_AUTO_START", "").strip().lower() in (
            "1",
            "true",
            "yes",
        ):
            self.log("ℹ️ Автозапуск приёма отключён (PORTAL_NO_AUTO_START)")
            return
        if self.is_server_running:
            return
        try:
            self.start_server()
            self.log("🚀 Портал запущен автоматически (приём файлов и буфера)")
        except Exception as e:
            self.log(f"⚠️ Автозапуск: {e}")

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
        al = portal_config.load_peer_aliases()
        lines_out: List[str] = []
        for ip in ips:
            nm = al.get(ip, "").strip()
            lines_out.append(f"{ip}  {nm}".rstrip() if nm else ip)
        self.peer_ips_text.delete("1.0", "end")
        self.peer_ips_text.insert("1.0", "\n".join(lines_out) if lines_out else "")

    def save_peer_ips_from_ui(self) -> None:
        raw = self.peer_ips_text.get("1.0", "end") if hasattr(self, "peer_ips_text") else ""
        lines = [ln.strip() for ln in raw.replace("\r", "").split("\n")]
        ips: List[str] = []
        aliases: Dict[str, str] = {}
        bad_lines: List[str] = []
        seen_ip = set()
        for line in lines:
            if not line or line.lstrip().startswith("#"):
                continue
            p = portal_config.parse_peer_line(line)
            if not p:
                bad_lines.append(line)
                continue
            ip, name = p
            if ip in seen_ip:
                if name:
                    aliases[ip] = name
                continue
            seen_ip.add(ip)
            ips.append(ip)
            if name:
                aliases[ip] = name
        if hasattr(self, "ip_saved_feedback"):
            self.ip_saved_feedback.configure(text="⏳ …", text_color="gray")
        ok = portal_config.save_peer_ips(ips)
        if ok:
            portal_config.save_peer_aliases(aliases)
        self.remote_peer_ip = portal_config.load_remote_ip()
        if ok:
            if bad_lines:
                self.log(
                    f"⚠️ Строки без корректного IPv4 пропущены: {bad_lines[:5]}"
                    + (" …" if len(bad_lines) > 5 else "")
                )
            shown = [portal_config.peer_display_label(ip) for ip in ips]
            self.log(f"💾 Список пиров сохранён ({len(ips)}): {', '.join(shown) or '(пусто)'}")
            if hasattr(self, "ip_saved_feedback"):
                self.ip_saved_feedback.configure(text="✅ Список сохранён", text_color="#3dd68c")
            self.rebuild_peer_checkboxes()
            self.check_peer_connection_async(silent=False)
            self._arm_peer_poll()
            try:
                self._rebuild_peer_receive_dir_rows()
            except Exception:
                pass
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
                text=i18n.tr("peer.add_ip_hint"),
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
                text=portal_config.peer_display_label(ip),
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
        labels = [portal_config.peer_display_label(ip) for ip in chosen]
        self.log(f"💾 Отправка на выбранные ПК: {', '.join(labels)}")
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

    def _rebuild_peer_receive_dir_rows(self) -> None:
        """По одному блоку на каждый сохранённый IP (вкладка «Пиры»)."""
        sc = getattr(self, "_peer_recv_dirs_scroll", None)
        if sc is None:
            return
        try:
            for w in sc.winfo_children():
                w.destroy()
        except Exception:
            pass
        self._peer_recv_dir_rows = []
        ips = portal_config.load_peer_ips()
        dirs_map = portal_config.load_peer_receive_dirs()
        if not ips:
            ctk.CTkLabel(
                sc,
                text=i18n.tr("recv.per_ip_empty"),
                font=ctk.CTkFont(size=11),
                text_color="gray",
                wraplength=640,
                justify="left",
            ).pack(anchor="w", pady=(4, 8))
            return
        ph = i18n.tr("recv.per_ip_path_placeholder")
        for ip in ips:
            fr = ctk.CTkFrame(sc, fg_color="transparent")
            fr.pack(fill="x", pady=(0, 10))
            ctk.CTkLabel(
                fr,
                text=portal_config.peer_display_label(ip),
                width=200,
                anchor="w",
                font=ctk.CTkFont(size=12, weight="bold"),
            ).pack(side="left", padx=(0, 10))
            ent = ctk.CTkEntry(fr, placeholder_text=ph, font=ctk.CTkFont(size=12))
            ent.pack(side="left", padx=(0, 8), fill="x", expand=True)
            prev = (dirs_map.get(ip) or "").strip()
            if prev:
                ent.insert(0, prev)
            wire_ctk_entry_paste(ent)
            ctk.CTkButton(
                fr,
                text=i18n.tr("recv.browse"),
                width=88,
                command=lambda e=ent: self._choose_dir_for_peer_entry(e),
                font=ctk.CTkFont(size=12),
            ).pack(side="left")
            self._peer_recv_dir_rows.append({"ip": ip, "entry": ent, "frame": fr})

    def _choose_dir_for_peer_entry(self, entry) -> None:
        from tkinter import filedialog

        if entry is None:
            return
        cur = entry.get().strip()
        base = str(portal_config.receive_dir_path())
        exp = os.path.expanduser(cur)
        initial = cur if cur and os.path.isdir(exp) else base
        d = filedialog.askdirectory(
            title=i18n.tr("recv.per_ip_filedialog"),
            initialdir=initial,
        )
        if d:
            entry.delete(0, "end")
            entry.insert(0, d)

    def save_peer_receive_dirs_from_ui(self) -> None:
        """Сохранить маппинг IP → папка из блоков по списку пиров."""
        rows = getattr(self, "_peer_recv_dir_rows", None)
        mapping: Dict[str, str] = {}
        if rows:
            for row in rows:
                ip = str(row.get("ip", "")).strip()
                ent = row.get("entry")
                if not ip or ent is None:
                    continue
                p = (ent.get() or "").strip()
                if p:
                    mapping[ip] = p
        ok = portal_config.save_peer_receive_dirs(mapping)
        if ok:
            self.log(
                f"✅ Папки по IP: {len(mapping)} записей"
                if mapping
                else "✅ Список папок по IP очищен (общая папка для всех)"
            )
            if hasattr(self, "peer_receive_dirs_feedback"):
                self.peer_receive_dirs_feedback.configure(
                    text="✅ OK", text_color="#3dd68c"
                )
        else:
            self.log("❌ Не удалось сохранить папки по IP")
            if hasattr(self, "peer_receive_dirs_feedback"):
                self.peer_receive_dirs_feedback.configure(
                    text="❌ Ошибка", text_color="#e74c3c"
                )

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

    def _generate_shared_secret_ui(self) -> None:
        s = portal_config.generate_shared_secret(12)
        if hasattr(self, "shared_secret_entry"):
            self.shared_secret_entry.delete(0, "end")
            self.shared_secret_entry.insert(0, s)
        self.log(
            "🔑 Подставлен новый пароль — «Сохранить» только на этом ПК, "
            "или «Сгенерировать и разослать по сети» / «Разослать из поля» для остальных."
        )

    def _collect_peer_ips_for_secret_sync(self) -> List[str]:
        skip: set[str] = {"127.0.0.1", "::1"}
        try:
            ts = (self.tailscale_ip or "").strip()
            if ts:
                skip.add(ts)
        except Exception:
            pass
        out: List[str] = []
        seen: set[str] = set()
        for line in portal_config.load_peer_ips():
            pr = portal_config.parse_peer_line(line)
            ip = pr[0] if pr else ""
            if not ip or ip in skip or ip in seen:
                continue
            seen.add(ip)
            out.append(ip)
        return out

    def _generate_and_sync_shared_secret_ui(self) -> None:
        if os.environ.get("PORTAL_NO_REMOTE_SECRET_SYNC", "").strip().lower() in (
            "1",
            "true",
            "yes",
        ):
            self.log("ℹ️ Рассылка пароля отключена (PORTAL_NO_REMOTE_SECRET_SYNC=1)")
            return
        new_sec = portal_config.generate_shared_secret(12)
        self._sync_new_secret_to_peers_then_local(new_sec, intro_log="🔑 Новый пароль сгенерирован, шлю пирам…")

    def _push_shared_secret_from_field_ui(self) -> None:
        if os.environ.get("PORTAL_NO_REMOTE_SECRET_SYNC", "").strip().lower() in (
            "1",
            "true",
            "yes",
        ):
            self.log("ℹ️ Рассылка пароля отключена (PORTAL_NO_REMOTE_SECRET_SYNC=1)")
            return
        if not hasattr(self, "shared_secret_entry"):
            return
        new_sec = self.shared_secret_entry.get().strip()
        if not new_sec:
            self.log("⚠️ Введи пароль в поле или нажми «Подставить»")
            return
        self._sync_new_secret_to_peers_then_local(
            new_sec, intro_log="🔑 Рассылаю пароль из поля по пирам…"
        )

    def _sync_new_secret_to_peers_then_local(
        self, new_sec: str, *, intro_log: str
    ) -> None:
        new_sec = (new_sec or "").strip()
        if not new_sec or len(new_sec) > 512:
            self.log("⚠️ Некорректный пароль для рассылки")
            return
        peers = self._collect_peer_ips_for_secret_sync()
        self.log(intro_log)

        def work() -> None:
            results: List[tuple[str, bool, str]] = []
            for ip in peers:
                ok, detail = send_sync_shared_secret_to_peer(ip, new_sec)
                results.append((ip, ok, detail))
            save_ok = portal_config.save_shared_secret(new_sec)

            def done() -> None:
                if hasattr(self, "shared_secret_entry"):
                    try:
                        self.shared_secret_entry.delete(0, "end")
                        self.shared_secret_entry.insert(0, new_sec)
                    except Exception:
                        pass
                self._refresh_main_secret_banner_visibility()
                for ip, ok, detail in results:
                    if ok:
                        self.log(f"✅ Пароль принят на {ip}")
                    else:
                        self.log(f"⚠️ {ip}: не доставлен ({detail})")
                if not peers:
                    self.log("ℹ️ В списке пиров нет других IP — пароль сохранён только здесь.")
                if save_ok:
                    self.log("✅ Пароль сети сохранён на этом компьютере")
                else:
                    self.log("❌ Не удалось записать пароль в config.json на этом ПК")

            try:
                self.after(0, done)
            except Exception:
                done()

        threading.Thread(target=work, daemon=True).start()

    def _save_shared_secret_ui(self) -> None:
        if not hasattr(self, "shared_secret_entry"):
            return
        raw = self.shared_secret_entry.get().strip()
        if portal_config.save_shared_secret(raw if raw else None):
            if raw:
                self.log("✅ Пароль сети сохранён — на всех своих компьютерах должен быть тот же пароль.")
            else:
                self.log("✅ Пароль сети снят: приём как в старых версиях (без проверки).")
        else:
            self.log("⚠️ Не удалось сохранить пароль сети (права на config.json?)")

    def _copy_shared_secret_ui(self) -> None:
        if not hasattr(self, "shared_secret_entry"):
            return
        raw = self.shared_secret_entry.get().strip()
        if not raw:
            self.log("⚠️ Поле пароля пустое — нечего копировать")
            return
        try:
            pyperclip.copy(raw)
            self.log("📋 Пароль сети скопирован в буфер")
        except Exception as e:
            self.log(f"⚠️ Не удалось скопировать: {e}")

    def choose_widget_media_file(self) -> None:
        from tkinter import filedialog
        from tkinter import messagebox

        if not hasattr(self, "widget_media_entry"):
            return
        p = filedialog.askopenfilename(
            title="Картинка, GIF или видео для портала",
            filetypes=[
                ("Изображения и GIF", "*.gif *.png *.jpg *.jpeg *.webp"),
                ("Видео (будет конвертация)", "*.mp4 *.webm *.mov *.mkv"),
                ("Все файлы", "*.*"),
            ],
        )
        if not p:
            return
        low = p.lower()
        if low.endswith(_WIDGET_VIDEO_EXTS):
            if messagebox.askyesno(
                "Видео → GIF",
                "Виджет использует GIF/картинки.\n\n"
                "Сконвертировать выбранное видео в assets/portal_animated.gif\n"
                "(скрипт import_portal_from_mp4.py, может занять несколько минут)?",
            ):
                self._start_widget_video_convert(p)
            return
        self.widget_media_entry.delete(0, "end")
        self.widget_media_entry.insert(0, p)

    def choose_widget_video_convert_to_gif(self) -> None:
        from tkinter import filedialog

        if not hasattr(self, "widget_media_entry"):
            return
        p = filedialog.askopenfilename(
            title="Видео для конвертации в GIF виджета",
            filetypes=[
                ("Видео", "*.mp4 *.webm *.mov *.mkv"),
                ("Все файлы", "*.*"),
            ],
        )
        if p:
            self._start_widget_video_convert(p)

    def _start_widget_video_convert(self, video_path: str) -> None:
        """import_portal_from_mp4.py в фоне → путь к portal_animated.gif в конфиг."""
        root = Path(__file__).resolve().parent
        script = root / "import_portal_from_mp4.py"
        if not script.is_file():
            self.log(f"❌ Не найден {script.name} — положи скрипт рядом с portal.py")
            return
        vp = Path(video_path)
        if not vp.is_file():
            self.log("⚠️ Файл видео не найден")
            return
        self.log(f"⏳ Конвертация видео → GIF… ({vp.name})")

        def work() -> None:
            try:
                r = subprocess.run(
                    [sys.executable, str(script), str(vp)],
                    cwd=str(root),
                    capture_output=True,
                    text=True,
                    timeout=900,
                )
                out = (r.stdout or "") + (r.stderr or "")
            except Exception as ex:
                r = None
                out = str(ex)

            def done() -> None:
                if r is not None and r.returncode == 0:
                    gif = root / "assets" / "portal_animated.gif"
                    if gif.is_file():
                        gp = str(gif.resolve())
                        self.widget_media_entry.delete(0, "end")
                        self.widget_media_entry.insert(0, gp)
                        self.save_widget_media_from_ui()
                    else:
                        self.log("⚠️ Конвертация завершилась, но portal_animated.gif не найден")
                else:
                    tail = (out or "")[-1200:] if out else ""
                    self.log(
                        f"❌ Конвертация видео не удалась"
                        f"{f' (код {r.returncode})' if r is not None else ''}: {tail}"
                    )

            try:
                self.after(0, done)
            except Exception:
                done()

        threading.Thread(target=work, daemon=True).start()

    def _apk_repo_from_ui(self) -> str:
        if hasattr(self, "github_repo_entry"):
            raw = self.github_repo_entry.get().strip()
            if raw and raw.count("/") == 1:
                return raw
        return portal_config.load_github_repo()

    def save_github_repo_from_ui(self) -> None:
        if not hasattr(self, "github_repo_entry"):
            return
        raw = self.github_repo_entry.get().strip()
        if portal_config.save_github_repo(raw):
            self.log(f"✅ GitHub repo сохранён: {raw}")
        else:
            self.log("⚠️ Некорректный repo — нужен формат owner/repo (один слэш)")

    def open_apk_release_page(self) -> None:
        try:
            import portal_github

            repo = self._apk_repo_from_ui()
            url = portal_github.apk_release_page_url(repo)
            webbrowser.open(url)
            self.log(f"🌐 Релиз с APK: {url}")
        except Exception as e:
            self.log(f"❌ Не удалось открыть релиз: {e}")

    def download_portal_apk_from_github(self) -> None:
        import portal_github

        repo = self._apk_repo_from_ui()
        if not repo or repo.count("/") != 1:
            self.log("⚠️ Укажи репозиторий как owner/repo и сохрани")
            return
        home = Path.home()
        down = home / "Downloads"
        if not down.is_dir():
            down = home / "Загрузки"
        if not down.is_dir():
            down = home
        dest = down / "Portal-Android.apk"
        token = os.environ.get("PORTAL_GITHUB_TOKEN", "").strip()

        def work() -> None:
            ok, msg = portal_github.download_apk_to_file(
                repo, dest, token=token or None
            )

            def done() -> None:
                if ok:
                    self.log(f"✅ APK сохранён: {msg}")
                    if platform.system() == "Darwin":
                        try:
                            subprocess.run(
                                ["open", "-R", str(dest)],
                                check=False,
                                capture_output=True,
                            )
                        except Exception:
                            pass
                else:
                    self.log(f"❌ Скачивание APK: {msg}")

            try:
                self.after(0, done)
            except Exception:
                done()

        self.log("⬇ Качаю APK с GitHub Release…")
        threading.Thread(target=work, daemon=True).start()

    def trigger_android_apk_workflow(self) -> None:
        import portal_github

        token = os.environ.get("PORTAL_GITHUB_TOKEN", "").strip()
        repo = self._apk_repo_from_ui()
        if not repo or repo.count("/") != 1:
            self.log("⚠️ Укажи репозиторий как owner/repo")
            return
        if not token:
            self.log(
                "ℹ️ Нет PORTAL_GITHUB_TOKEN — открываю страницу workflow. "
                "Нажми Run workflow. Токен (repo+workflow) нужен только для запуска из приложения."
            )
            try:
                webbrowser.open(portal_github.actions_workflow_page_url(repo))
            except Exception:
                pass
            return
        branch = os.environ.get("PORTAL_GITHUB_BRANCH", "main").strip() or "main"

        def work() -> None:
            ok, msg = portal_github.dispatch_android_apk_workflow(
                repo, token, ref=branch
            )

            def done() -> None:
                if ok:
                    self.log(f"🤖 {msg}")
                else:
                    self.log(f"❌ Запуск сборки: {msg}")

            try:
                self.after(0, done)
            except Exception:
                done()

        self.log("🤖 Запрос на запуск сборки APK на GitHub…")
        threading.Thread(target=work, daemon=True).start()

    def save_widget_media_from_ui(self) -> None:
        if not hasattr(self, "widget_media_entry"):
            return
        raw = self.widget_media_entry.get().strip()
        if raw and not os.path.isfile(raw):
            self.log("⚠️ Файл не найден — проверь путь")
            return
        if raw:
            low = raw.lower()
            if low.endswith(_WIDGET_VIDEO_EXTS):
                self.log(
                    "⚠️ Виджет не использует MP4/WebM напрямую. Нажми «Видео → GIF» "
                    "или выбери видео в «Обзор…» и согласись на конвертацию."
                )
                return
            if not portal_config.save_widget_media_path(raw):
                self.log("⚠️ Не удалось сохранить путь к медиа")
                return
        else:
            fb = portal_config.default_widget_media_fallback_path()
            if fb:
                if not portal_config.save_widget_media_path(fb):
                    self.log("⚠️ Не удалось сохранить стандартное медиа")
                    return
                self.log("✅ Пустое поле — сохранено стандартное медиа из assets")
            else:
                portal_config.save_widget_media_path(None)
                self.log("⚠️ В assets нет portal_main.gif — укажи файл вручную")
        label = self.widget_media_mode_menu.get()
        mode_key = getattr(self, "_widget_media_mode_rev", {}).get(label, "auto")
        if not portal_config.save_widget_media_mode(mode_key):
            self.log("⚠️ Не удалось сохранить режим отображения")
            return
        self.log("✅ Внешний вид портала сохранён")
        self.apply_widget_media_reload()

    def clear_widget_media_from_ui(self) -> None:
        fb = portal_config.default_widget_media_fallback_path()
        if fb:
            portal_config.save_widget_media_path(fb)
            if hasattr(self, "widget_media_entry"):
                self.widget_media_entry.delete(0, "end")
                self.widget_media_entry.insert(0, fb)
            self.log("✅ Сброшено на стандартное медиа (portal_main.gif в assets)")
        else:
            portal_config.save_widget_media_path(None)
            if hasattr(self, "widget_media_entry"):
                self.widget_media_entry.delete(0, "end")
            self.log("⚠️ Нет стандартного файла в assets — поле очищено")
        self.apply_widget_media_reload()

    def apply_widget_media_reload(self) -> None:
        w = getattr(self, "portal_widget_ref", None)
        if w is not None and hasattr(w, "reload_portal_media"):
            try:
                self.after(0, w.reload_portal_media)
            except Exception as ex:
                self.log(f"⚠️ Перезагрузка виджета: {ex}")
        else:
            self.log(
                "💡 Виджет ещё не создан — открой его хоткеем после запуска; "
                "медиа подхватится при следующей загрузке."
            )

    def save_widget_geometry_from_ui(self) -> None:
        if not hasattr(self, "widget_size_entry"):
            return
        try:
            sz = int(self.widget_size_entry.get().strip())
        except ValueError:
            self.log("⚠️ Размер виджета — целое число (пиксели, 80…600)")
            return
        label = self.widget_corner_menu.get()
        ck = getattr(self, "_widget_corner_rev", {}).get(label, "br")
        try:
            mx = int(self.widget_margin_x_entry.get().strip())
            my = int(self.widget_margin_y_entry.get().strip())
        except ValueError:
            self.log("⚠️ Отступы X и Y — целые числа (пиксели от края экрана)")
            return
        if portal_config.save_widget_geometry_settings(
            size=sz, corner_key=ck, margin_x=mx, margin_y=my
        ):
            self.log("✅ Размер и положение виджета сохранены")
            self._apply_widget_geometry_live()
        else:
            self.log("⚠️ Не удалось записать настройки геометрии")

    def _widget_preset_labels_and_ids(self) -> Tuple[List[str], List[str]]:
        cat = portal_config.load_widget_presets_catalog()
        labels: List[str] = []
        ids: List[str] = []
        for p in cat:
            pid = str(p.get("id", "")).strip()
            if not pid:
                continue
            nm = str(p.get("name") or pid).strip()
            labels.append(f"{nm} ({pid})")
            ids.append(pid)
        if not labels:
            labels = ["Основное медиа виджета (main)"]
            ids = ["main"]
        return labels, ids

    def _refresh_widget_preset_preview_menu_from_catalog(self) -> None:
        m = getattr(self, "_widget_preset_preview_combo", None)
        if m is None:
            return
        labels, _ids = self._widget_preset_labels_and_ids()
        try:
            cur = m.get()
        except Exception:
            cur = ""
        m.configure(values=labels)
        if labels:
            m.set(cur if cur in labels else labels[0])

    def _refresh_settings_preset_rules_ui(self) -> None:
        try:
            self._rebuild_widget_preset_rule_rows()
            self._refresh_widget_preset_preview_menu_from_catalog()
        except Exception as ex:
            try:
                self.log(f"⚠️ Обновление таблицы пресетов: {ex}")
            except Exception:
                pass

    def _remove_widget_preset_rule_row(self, row: Dict[str, Any]) -> None:
        try:
            if row in self._widget_preset_rule_rows:
                self._widget_preset_rule_rows.remove(row)
            row["frame"].destroy()
        except Exception:
            pass

    def _add_widget_preset_rule_row(
        self, peer: str, event_key: str, preset_id: str
    ) -> None:
        sc = getattr(self, "_widget_preset_rules_scroll", None)
        if sc is None:
            return
        labels, ids = self._widget_preset_labels_and_ids()
        fr = ctk.CTkFrame(sc, fg_color="transparent")
        fr.pack(fill="x", pady=3)
        peer_s = (peer or "").strip() or "*"
        ip_vals = ["*"] + [p for p in portal_config.load_peer_ips() if str(p).strip()]
        if peer_s not in ip_vals:
            ip_vals.insert(1, peer_s)
        ip_e = ctk.CTkComboBox(
            fr,
            width=160,
            values=ip_vals,
            font=ctk.CTkFont(size=12),
            state="normal",
        )
        ip_e.set(peer_s if peer_s in ip_vals else ip_vals[0])
        ip_e.pack(side="left", padx=(0, 6))
        ev_map = i18n.widget_preset_event_labels()
        ev_labels = list(ev_map.values())
        ev_m = ctk.CTkOptionMenu(
            fr,
            values=ev_labels,
            width=200,
            font=ctk.CTkFont(size=12),
        )
        if event_key in ev_map:
            ev_m.set(ev_map[event_key])
        else:
            ev_m.set(ev_labels[0])
        ev_m.pack(side="left", padx=(0, 6))
        pr_m = ctk.CTkOptionMenu(
            fr,
            values=labels,
            width=340,
            font=ctk.CTkFont(size=12),
        )
        if preset_id in ids:
            pr_m.set(labels[ids.index(preset_id)])
        else:
            pr_m.set(labels[0])
        pr_m.pack(side="left", padx=(0, 6), fill="x", expand=True)
        row_ui: Dict[str, Any] = {
            "frame": fr,
            "ip": ip_e,
            "event_menu": ev_m,
            "preset_menu": pr_m,
            "preset_ids": list(ids),
        }
        self._widget_preset_rule_rows.append(row_ui)

        def _rm() -> None:
            self._remove_widget_preset_rule_row(row_ui)

        ctk.CTkButton(
            fr,
            text="✕",
            width=36,
            command=_rm,
            font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=(4, 0))

    def _rebuild_widget_preset_rule_rows(self) -> None:
        sc = getattr(self, "_widget_preset_rules_scroll", None)
        if sc is None:
            return
        for w in sc.winfo_children():
            w.destroy()
        self._widget_preset_rule_rows.clear()
        for r in portal_config.load_widget_preset_rules():
            self._add_widget_preset_rule_row(
                str(r.get("peer", "*") or "*"),
                str(r.get("event", "receive")),
                str(r.get("preset", "main")),
            )

    def _widget_preset_add_rule_row(self) -> None:
        self._add_widget_preset_rule_row("*", "receive", "main")

    def _collect_widget_preset_rules_from_table(self) -> List[Dict[str, str]]:
        rules: List[Dict[str, str]] = []
        rev_ev = {v: k for k, v in i18n.widget_preset_event_labels().items()}
        for row in self._widget_preset_rule_rows:
            ip = (row["ip"].get() or "").strip() or "*"
            ev_ru = row["event_menu"].get()
            ev = rev_ev.get(ev_ru, "receive")
            pr_vals = list(row["preset_menu"].cget("values"))
            cur = row["preset_menu"].get()
            ids_row: List[str] = row["preset_ids"]
            try:
                ix = pr_vals.index(cur)
                pid = ids_row[ix]
            except (ValueError, IndexError):
                pid = "main"
            rules.append({"peer": ip, "event": ev, "preset": pid})
        return rules

    def save_widget_preset_rules_from_ui(self) -> None:
        """Сохранить правила пресетов из таблицы во вкладке «Виджет»."""
        if getattr(self, "_widget_preset_rules_scroll", None) is None:
            return
        fb = getattr(self, "widget_preset_rules_feedback", None)
        try:
            rules = self._collect_widget_preset_rules_from_table()
            if portal_config.save_widget_preset_rules(rules):
                if fb is not None:
                    fb.configure(text="✅ Сохранено")
                self.log("✅ Правила пресетов виджета сохранены (импульс по IP/событию)")
            else:
                if fb is not None:
                    fb.configure(text="⚠️ Не записалось")
                self.log("⚠️ Не удалось сохранить правила пресетов (config.json)")
        except Exception as e:
            if fb is not None:
                fb.configure(text="❌ Ошибка")
            self.log(f"❌ Пресеты виджета: {e}")

    def preview_widget_preset_from_settings_ui(self) -> None:
        m = getattr(self, "_widget_preset_preview_combo", None)
        if m is None:
            return
        labels, ids = self._widget_preset_labels_and_ids()
        try:
            cur = m.get()
            ix = labels.index(cur)
            pid = ids[ix]
        except (ValueError, IndexError):
            pid = "main"
        self.preview_preset_in_corner(pid)

    def preview_preset_in_corner(self, preset_id: str) -> None:
        """Кратко показать пресет в углу, как при импульсе виджета."""
        w = getattr(self, "portal_widget_ref", None)
        if w is None or not hasattr(w, "show"):
            self.log(
                "💡 Виджет ещё не создан: перезапусти Portal или нажми хоткей показа портала, "
                "затем снова «Показать превью»."
            )
            return
        pid = (preset_id or "main").strip() or "main"
        media_path = portal_config.resolve_widget_preset_file_path(pid)
        if not media_path:
            self.log(
                f"⚠️ Нет файла для пресета «{pid}». "
                "Проверь путь в «Медиа» (по умолчанию assets/portal_main.gif) и файлы в assets/presets/."
            )
            return
        seconds = 4.0

        def run() -> None:
            try:
                if not _portal_widget_tk_alive(w):
                    return
                self._widget_pulse_generation += 1
                gen = self._widget_pulse_generation
                was_visible = False
                try:
                    was_visible = bool(w.is_visible())
                except Exception:
                    pass
                if hasattr(w, "set_transient_portal_media"):
                    w.set_transient_portal_media(media_path)
                if not was_visible:
                    w.show()

                def hide_later() -> None:
                    if self._widget_pulse_generation != gen:
                        return
                    if not _portal_widget_tk_alive(w):
                        return
                    try:
                        if hasattr(w, "clear_transient_portal_media"):
                            w.clear_transient_portal_media()
                        if not was_visible:
                            try:
                                if w.is_visible():
                                    w.hide()
                            except Exception:
                                pass
                    except tk.TclError:
                        pass
                    except Exception:
                        pass

                self.after(int(seconds * 1000), hide_later)
            except tk.TclError as ex:
                self.log(f"⚠️ Превью пресета: {ex}")
            except Exception as ex:
                self.log(f"⚠️ Превью пресета: {ex}")

        try:
            self.after(0, run)
        except Exception:
            run()

    def _apply_widget_geometry_live(self) -> None:
        w = getattr(self, "portal_widget_ref", None)
        if w is not None and hasattr(w, "apply_widget_geometry"):
            try:
                self.after(0, w.apply_widget_geometry)
            except Exception as e:
                self.log(f"⚠️ Применение геометрии виджета: {e}")
        else:
            self.log(
                "💡 Виджет ещё не создан — геометрия из config подхватится при следующем старте"
            )

    def _pulse_portal_widget(
        self,
        seconds: Optional[float] = None,
        *,
        pulse_event: str = "receive",
        peer_ip: Optional[str] = None,
    ) -> None:
        """
        Кратко показать виджет (если был скрыт) и/или подменить GIF по пресетам (IP + событие).
        pulse_event: receive | receive_file | send
        Отключить: PORTAL_WIDGET_PULSE_ON_RECEIVE=0
        """
        if os.environ.get("PORTAL_WIDGET_PULSE_ON_RECEIVE", "1").strip().lower() in (
            "0",
            "false",
            "no",
            "off",
        ):
            return
        w = getattr(self, "portal_widget_ref", None)
        if w is None or not hasattr(w, "show") or not hasattr(w, "hide"):
            return
        if seconds is None:
            try:
                seconds = float(os.environ.get("PORTAL_WIDGET_PULSE_SECONDS", "3").strip() or "3")
            except ValueError:
                seconds = 3.0
        seconds = max(0.5, min(float(seconds), 30.0))

        ev = (pulse_event or "receive").strip()
        if ev not in ("receive", "receive_file", "send"):
            ev = "receive"

        def run() -> None:
            try:
                if not _portal_widget_tk_alive(w):
                    return
                self._widget_pulse_generation += 1
                gen = self._widget_pulse_generation
                was_visible = False
                try:
                    was_visible = bool(w.is_visible())
                except Exception:
                    pass
                media_path = portal_config.resolve_widget_pulse_media_path(ev, peer_ip)
                if media_path and hasattr(w, "set_transient_portal_media"):
                    w.set_transient_portal_media(media_path)
                elif hasattr(w, "clear_transient_portal_media"):
                    w.clear_transient_portal_media()
                if not was_visible:
                    w.show()

                def hide_later() -> None:
                    if self._widget_pulse_generation != gen:
                        return
                    if not _portal_widget_tk_alive(w):
                        return
                    try:
                        if hasattr(w, "clear_transient_portal_media"):
                            w.clear_transient_portal_media()
                        if not was_visible:
                            try:
                                if w.is_visible():
                                    w.hide()
                            except Exception:
                                pass
                    except tk.TclError:
                        pass
                    except Exception:
                        pass

                self.after(int(seconds * 1000), hide_later)
            except tk.TclError as ex:
                try:
                    self.log(f"⚠️ Импульс виджета: {ex}")
                except Exception:
                    pass
            except Exception as ex:
                try:
                    self.log(f"⚠️ Импульс виджета: {ex}")
                except Exception:
                    pass

        try:
            self.after(0, run)
        except Exception:
            run()

    def _parse_peer_ips_draft(self) -> List[str]:
        if not hasattr(self, "peer_ips_text"):
            return list(portal_config.load_peer_ips())
        raw = self.peer_ips_text.get("1.0", "end")
        lines = [ln.strip() for ln in raw.replace("\r", "").split("\n")]
        out: List[str] = []
        for line in lines:
            if not line or line.lstrip().startswith("#"):
                continue
            p = portal_config.parse_peer_line(line)
            if p:
                out.append(p[0])
        return out

    def _peer_ips_for_probe(self) -> List[str]:
        draft = self._parse_peer_ips_draft()
        return draft if draft else list(portal_config.load_peer_ips())

    def _peer_targets_for_probe(self) -> List[str]:
        """IP только с отмеченными получателями (как при отправке файла)."""
        seen: Set[str] = set()
        out: List[str] = []
        for ip in portal_config.load_peer_send_targets():
            ip = (ip or "").strip()
            if not ip or ip in seen:
                continue
            seen.add(ip)
            out.append(ip)
        return out

    def _format_peer_probe_result(self, ip: str, ok: bool, code: str) -> tuple[str, str]:
        """Текст и цвет для строки статуса пары."""
        if not ip:
            return i18n.tr("peer.need_ip"), "gray"
        lbl = portal_config.peer_display_label(ip)
        if ok:
            return (
                i18n.tr("peer.ok", lbl=lbl, port=PORTAL_PORT),
                "#3dd68c",
            )
        if code == "refused":
            return (
                i18n.tr("peer.refused", lbl=lbl, port=PORTAL_PORT),
                "#e74c3c",
            )
        if code == "timeout":
            return (
                i18n.tr("peer.timeout", lbl=lbl),
                "#e67e22",
            )
        if code == "dns":
            return i18n.tr("peer.dns", lbl=lbl), "#e74c3c"
        if code == "bad_reply":
            return (
                i18n.tr("peer.bad_reply", lbl=lbl),
                "#f39c12",
            )
        if code == "no_host":
            return i18n.tr("peer.no_host"), "gray"
        return i18n.tr("peer.error", lbl=lbl, code=code), "#e74c3c"

    def _refresh_local_link_status_label(self) -> None:
        if not hasattr(self, "local_link_status_label"):
            return
        if self.is_server_running:
            ip = self.tailscale_ip or "?"
            self.local_link_status_label.configure(
                text=i18n.tr("local.recv_on", ip=ip, port=PORTAL_PORT),
                text_color="#3dd68c",
            )
        else:
            self.local_link_status_label.configure(
                text=i18n.tr("local.recv_off", port=PORTAL_PORT),
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
        if not self._peer_targets_for_probe():
            return
        self._peer_poll_job = self.after(PEER_STATUS_POLL_MS, self._peer_poll_tick)

    def _peer_poll_tick(self) -> None:
        self._peer_poll_job = None
        if self._peer_targets_for_probe():
            self.check_peer_connection_async(silent=True)
        if self._peer_targets_for_probe():
            self._arm_peer_poll()

    def check_peer_connection_async(self, silent: bool = False) -> None:
        """Фоновый ping → pong только к отмеченным получателям."""
        ips = self._peer_targets_for_probe()
        if not ips:
            def _idle_status():
                if not hasattr(self, "peer_link_status_label"):
                    return
                if not portal_config.load_peer_ips():
                    msg = i18n.tr("peer.probe_empty")
                else:
                    msg = i18n.tr("peer.probe_no_selection")
                self.peer_link_status_label.configure(text=msg, text_color="gray")

            self.after(0, _idle_status)
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
                        msg_t = i18n.tr(
                            "peer.all_ok", n=len(results), port=PORTAL_PORT
                        )
                        msg_c = "#3dd68c"
                    elif oks:
                        msg_t = i18n.tr(
                            "peer.partial",
                            ok=oks,
                            total=len(results),
                            bad=", ".join(bad[:5]),
                        )
                        msg_c = "#e67e22"
                    else:
                        msg_t = i18n.tr(
                            "peer.none_ok", n=len(results), first=bad[0]
                        )
                        msg_c = "#e74c3c"
                self.peer_link_status_label.configure(text=msg_t, text_color=msg_c)
                if not silent:
                    for ip, ok, code in results:
                        if ok:
                            self.log(i18n.tr("log.probe_ok", ip=ip))
                        else:
                            self.log(i18n.tr("log.probe_fail", ip=ip, code=code))

            try:
                self.after(0, apply)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()
    
    def _restore_log_from_file(self) -> None:
        """При открытии/повторном открытии журнала — загрузить последние строки из файла."""
        try:
            log_file = portal_config.activity_log_path()
            if log_file.is_file():
                raw = log_file.read_text(encoding="utf-8", errors="replace")
                lines = raw.splitlines()
                tail = lines[-self._log_max_lines:] if len(lines) > self._log_max_lines else lines
                content = "\n".join(tail) + "\n"
                self.log_text.configure(state="normal")
                self.log_text.delete("1.0", "end")
                self.log_text.insert("1.0", content)
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
                return
        except Exception:
            pass
        self.log_text.configure(state="normal")
        self.log_text.insert("1.0", i18n.tr("log.ready") + "\n")
        self.log_text.configure(state="disabled")

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
            
            self.start_button.configure(text=i18n.tr("btn.stop"))
            self.send_button.configure(state="normal")
            self.clipboard_button.configure(state="normal")
            shown = self.tailscale_ip or i18n.tr("status.all_interfaces")
            self.status_label.configure(
                text=i18n.tr(
                    "status.active", shown=shown, port=PORTAL_PORT
                ),
                text_color="green",
            )
            self.log(f"✅ Портал запущен, приём на 0.0.0.0:{PORTAL_PORT} (для связи: {shown})")
            if portal_config.load_shared_secret():
                self.log(
                    "🔒 Пароль сети включён — другие ПК должны иметь тот же пароль в настройках "
                    "(или на этом ПК PORTAL_ALLOW_LEGACY_NO_AUTH=1 для старых клиентов)."
                )
            if _portal_allow_legacy_no_auth():
                self.log(
                    "⚠️ PORTAL_ALLOW_LEGACY_NO_AUTH=1 — принимаются подключения и без пароля (риск в LAN)."
                )
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
        
        self.start_button.configure(text=i18n.tr("btn.start"))
        self.send_button.configure(state="disabled")
        self.clipboard_button.configure(state="disabled")
        self.status_label.configure(
            text=i18n.tr("status.stopped"),
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

            if not incoming_peer_secret_ok(message):
                self._log_from_thread(
                    f"⚠️ {addr[0]}: отклонено — неверный или отсутствующий пароль сети "
                    "(укажи тот же пароль в настройках на отправителе; "
                    "PORTAL_ALLOW_LEGACY_NO_AUTH=1 на приёме — только для старых клиентов)"
                )
                try:
                    _portal_sendall(
                        client_socket,
                        json.dumps(
                            {"type": "portal_auth_failed", "reason": "secret"},
                            ensure_ascii=False,
                        ).encode("utf-8"),
                    )
                except Exception:
                    pass
                return

            req = message.get("type")
            if req == "sync_shared_secret":
                raw_new = message.get("new_shared_secret")
                if not isinstance(raw_new, str):
                    try:
                        _portal_sendall(
                            client_socket,
                            json.dumps(
                                {
                                    "type": "sync_shared_secret_reject",
                                    "reason": "bad_type",
                                },
                                ensure_ascii=False,
                            ).encode("utf-8"),
                        )
                    except Exception:
                        pass
                    return
                new_s = raw_new.strip()
                if not new_s or len(new_s) > 512:
                    try:
                        _portal_sendall(
                            client_socket,
                            json.dumps(
                                {
                                    "type": "sync_shared_secret_reject",
                                    "reason": "bad_length",
                                },
                                ensure_ascii=False,
                            ).encode("utf-8"),
                        )
                    except Exception:
                        pass
                    return
                if not portal_config.save_shared_secret(new_s):
                    try:
                        _portal_sendall(
                            client_socket,
                            json.dumps(
                                {
                                    "type": "sync_shared_secret_reject",
                                    "reason": "save_failed",
                                },
                                ensure_ascii=False,
                            ).encode("utf-8"),
                        )
                    except Exception:
                        pass
                    return
                try:
                    _portal_sendall(
                        client_socket,
                        json.dumps(
                            {"type": "sync_shared_secret_ok"},
                            ensure_ascii=False,
                        ).encode("utf-8"),
                    )
                except Exception:
                    pass

                def _refresh_secret_ui() -> None:
                    try:
                        self._sync_settings_secret_entry_from_config()
                        self._refresh_main_secret_banner_visibility()
                        self.log(
                            f"🔑 Пароль сети обновлён с {addr[0]} — смотри поле в ⚙ Настройки."
                        )
                    except Exception:
                        pass

                try:
                    self.after(0, _refresh_secret_ui)
                except Exception:
                    _refresh_secret_ui()
                return

            if req != "ping":
                self._log_from_thread(f"🔗 {addr[0]} · {req}")
            
            peer_host = addr[0]
            if message.get("type") == "file":
                self.receive_file(
                    client_socket, message, prefix=tail, peer_ip=peer_host
                )
            elif message.get("type") == "clipboard_files":
                self.receive_clipboard_files(
                    client_socket, message, prefix=tail, peer_ip=peer_host
                )
            elif message.get("type") == "clipboard_rich":
                self.receive_clipboard_rich(
                    client_socket, message, prefix=tail, peer_ip=peer_host
                )
            elif message.get("type") == "clipboard":
                self.receive_clipboard(message, peer_ip=peer_host)
                try:
                    _portal_sendall(
                        client_socket,
                        json.dumps(
                            {"type": "clipboard_ok"},
                            ensure_ascii=False,
                        ).encode("utf-8"),
                    )
                except Exception:
                    pass
            elif message.get("type") == "clipboard_file":
                self._receive_clipboard_file_payload(
                    client_socket, message, prefix=tail, peer_ip=peer_host
                )
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
        peer_ip: Optional[str] = None,
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
            receive_dir = portal_config.incoming_clipboard_files_save_dir(peer_ip)
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

            def _apply(ip: Optional[str] = peer_ip):
                try:
                    self._apply_incoming_clipboard_files([p])
                    self._pulse_portal_widget(
                        pulse_event="receive_file", peer_ip=ip
                    )
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
        peer_ip: Optional[str] = None,
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

            receive_dir = portal_config.resolve_receive_dir_for_peer(peer_ip)
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

            if remaining > 0:
                self._log_from_thread(
                    f"❌ Файл {filename}: получено {filesize - remaining}/{filesize} байт (обрыв или сбой заголовка JSON/размера)"
                )
                try:
                    _portal_sendall(client_socket, b"ERR")
                except Exception:
                    pass
                try:
                    filepath.unlink(missing_ok=True)  # type: ignore[arg-type]
                except Exception:
                    pass
                return

            try:
                if filepath.is_file() and filepath.stat().st_size != filesize:
                    self._log_from_thread(
                        f"❌ Файл {filename}: размер на диске не совпадает с заголовком"
                    )
                    try:
                        _portal_sendall(client_socket, b"ERR")
                    except Exception:
                        pass
                    try:
                        filepath.unlink(missing_ok=True)  # type: ignore[arg-type]
                    except Exception:
                        pass
                    return
            except OSError:
                self._log_from_thread(f"❌ Файл {filename}: не удалось проверить размер на диске")
                try:
                    _portal_sendall(client_socket, b"ERR")
                except Exception:
                    pass
                try:
                    filepath.unlink(missing_ok=True)  # type: ignore[arg-type]
                except Exception:
                    pass
                return

            self._log_from_thread(
                f"✅ Файл сохранен: {filepath}"
                + (f" (папка для {peer_ip})" if peer_ip else "")
            )

            _portal_sendall(client_socket, b"OK")

            try:
                portal_history.append_event(
                    direction="receive",
                    kind="file",
                    peer_ip=peer_ip or "",
                    peer_label=portal_config.peer_display_label(peer_ip or ""),
                    name=filename,
                    stored_path=str(filepath.resolve()),
                    route_json=json.dumps([]),
                    filesize=filesize,
                )
            except Exception:
                pass

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
                        self._apply_receive_mode_after_saved_file(
                            p,
                            reveal_mac_allowed=reveal_ok,
                            from_mobile=_portal_message_from_mobile(msg_local),
                        )
                except Exception as ex:
                    self.log(f"❌ После приёма (Finder/буфер): {ex}")
                else:
                    self._pulse_portal_widget(
                        pulse_event="receive_file",
                        peer_ip=peer_ip,
                    )
                    if _portal_message_from_mobile(msg_local):
                        self.log("📱 Получено с телефона — файл сохранён")
                        _portal_desktop_notify(
                            "Portal",
                            f"Файл с телефона: {fp_saved.name}",
                        )

            try:
                self.after(0, _finish_receive)
            except Exception:
                _finish_receive()
        except Exception as e:
            self._log_from_thread(f"❌ Ошибка приёма файла: {e}")

    def _apply_receive_mode_after_saved_file(
        self, p: Path, *, reveal_mac_allowed: bool, from_mobile: bool = False
    ) -> None:
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
        # С телефона — только файл на диске, без подмены системного буфера обмена.
        copy_clip = (not from_mobile) and mode in ("both", "clipboard_only")
        if copy_clip:
            self._apply_portal_clipboard_files([p])
            self.log(f"📋 В буфере для вставки: {p.name}")

    def receive_clipboard_files(
        self,
        client_socket: socket.socket,
        message: dict,
        prefix: bytes = b"",
        peer_ip: Optional[str] = None,
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

        save_dir = portal_config.incoming_clipboard_files_save_dir(peer_ip)
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
            def _done(paths: List[str] = list(saved), ip: Optional[str] = peer_ip) -> None:
                self._apply_incoming_clipboard_files(paths)
                self._pulse_portal_widget(pulse_event="receive_file", peer_ip=ip)

            self.after(0, _done)
        except Exception:
            pass

    def receive_clipboard_rich(
        self,
        client_socket: socket.socket,
        message: dict,
        prefix: bytes = b"",
        peer_ip: Optional[str] = None,
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

        receive_dir = portal_config.resolve_receive_dir_for_peer(peer_ip)
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

        def _done_img(path: str = p, ip: Optional[str] = peer_ip) -> None:
            self._apply_incoming_clipboard_image(path)
            self._pulse_portal_widget(pulse_event="receive", peer_ip=ip)

        try:
            self.after(0, _done_img)
        except Exception:
            _done_img()

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
    
    def receive_clipboard(
        self, message: dict, peer_ip: Optional[str] = None
    ):
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

            def _paste_and_pulse() -> None:
                _paste()
                self._pulse_portal_widget(
                    pulse_event="receive", peer_ip=peer_ip
                )

            try:
                self.after(0, _paste_and_pulse)
            except Exception:
                _paste_and_pulse()
            self._log_from_thread(
                f"📋 Буфер обмена обновлен ({len(clipboard_text)} символов) — Ctrl+V для вставки"
            )
            if _portal_message_from_mobile(message):
                self._log_from_thread("📱 Получено с телефона — текст в буфере")
                _portal_desktop_notify("Portal", "Текст с телефона — в буфере обмена")
            try:
                portal_history.append_event(
                    direction="receive",
                    kind="text",
                    peer_ip=peer_ip or "",
                    peer_label=portal_config.peer_display_label(peer_ip or ""),
                    name="clipboard",
                    snippet=str(clipboard_text)[:500],
                    stored_path="",
                    route_json=json.dumps([]),
                )
            except Exception:
                pass

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
        attach_secret: bool = True,
    ) -> bool:
        """Записать снимок в сокет (ответ get_clipboard или входящий push clipboard_*). Возвращает успех."""
        def _sec(d: Dict[str, Any]) -> Dict[str, Any]:
            return merge_outgoing_shared_secret(d) if attach_secret else d

        if kind == "text":
            t = payload.get("text", "") or ""
            resp = json.dumps(_sec({"type": "clipboard", "text": t}), ensure_ascii=False)
            client_socket.sendall(resp.encode("utf-8") + b"\n")
            log(f"📋 {context_label} → текст ({len(t)} симв.)")
            return True

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
                    _sec({"type": "clipboard", "text": t or ""}),
                    ensure_ascii=False,
                )
                client_socket.sendall(resp.encode("utf-8") + b"\n")
                log(f"📋 {context_label} → файлы не прочитались, отдан текст/пусто")
                return True
            if len(valid_paths) == 1:
                one = Path(valid_paths[0])
                try:
                    sz = int(one.stat().st_size)
                except OSError:
                    sz = 0
                if 0 < sz <= CLIPBOARD_PULL_FILE_MAX_BYTES:
                    hdr = json.dumps(
                        _sec(
                            {
                                "type": "clipboard_file",
                                "filename": one.name,
                                "filesize": sz,
                            }
                        ),
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
                        return bool(okp.startswith(b"OK"))
                    log(
                        f"📋 {context_label} → один файл «{one.name}» ({sz} байт)"
                    )
                    return True
            specs = [
                {"filename": os.path.basename(p), "filesize": os.path.getsize(p)}
                for p in valid_paths
            ]
            header = _sec({"type": "clipboard_files", "files": specs})
            _portal_sendall(
                client_socket,
                json.dumps(header, ensure_ascii=False).encode("utf-8") + b"\n",
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
            return bool(okp.startswith(b"OK"))

        if kind == "image":
            image_bytes = payload.get("image_bytes") or b""
            if not portal_clip_rich.image_size_ok(len(image_bytes)):
                resp = json.dumps(
                    _sec({"type": "clipboard", "text": ""}), ensure_ascii=False
                )
                client_socket.sendall(resp.encode("utf-8") + b"\n")
                log(f"📋 {context_label} → картинка слишком большая")
                return False
            mime = payload.get("mime", "image/png")
            hdr = _sec(
                {
                    "type": "clipboard_rich",
                    "clip_kind": "image",
                    "mime": mime,
                    "size": len(image_bytes),
                }
            )
            _portal_sendall(
                client_socket,
                json.dumps(hdr, ensure_ascii=False).encode("utf-8") + b"\n",
            )
            time.sleep(0.05)
            _portal_sendall(client_socket, image_bytes)
            okp = _recv_ok_prefix(client_socket, timeout=180.0)
            log(
                f"📋 {context_label} → картинка clipboard_rich; ответ: {okp[:24]!r}"
            )
            return bool(okp.startswith(b"OK"))

        resp = json.dumps(_sec({"type": "clipboard", "text": ""}), ensure_ascii=False)
        client_socket.sendall(resp.encode("utf-8") + b"\n")
        log(f"📋 {context_label} → неизвестный снимок буфера")
        return True
    
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
                attach_secret=False,
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
            self._rebuild_peer_receive_dir_rows()
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
        # Снимок буфера только на главном потоке Tk: на Windows pywin32/OpenClipboard
        # и pyperclip из фонового потока часто дают пустой буфер или сбой.
        try:
            self.after(0, self._broadcast_clipboard_push_on_main_thread)
        except Exception:
            self._broadcast_clipboard_push_on_main_thread()
    
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
                json.dumps(
                    merge_outgoing_shared_secret({"type": "get_clipboard"}),
                    ensure_ascii=False,
                ).encode("utf-8")
                + b"\n",
            )
            message, rest = read_one_json_object_from_socket(client_socket)
            if message.get("type") == "portal_auth_failed":
                _log(
                    "❌ Удалённый ПК отклонил запрос: неверный пароль сети. "
                    "Задай тот же пароль в настройках здесь и на машине-приёмнике."
                )
                return
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
                try:
                    self.after(
                        0,
                        lambda ip=target_ip: self._pulse_portal_widget(
                            pulse_event="receive", peer_ip=ip
                        ),
                    )
                except Exception:
                    pass
            elif message.get("type") == "clipboard_files":
                self.receive_clipboard_files(
                    client_socket, message, prefix=rest, peer_ip=target_ip
                )
                _log("📋 Файлы с удалённого ПК получены (см. строки выше)")
            elif message.get("type") == "clipboard_rich":
                self.receive_clipboard_rich(
                    client_socket, message, prefix=rest, peer_ip=target_ip
                )
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
                receive_dir = portal_config.incoming_clipboard_files_save_dir(target_ip)
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

                def _finish_pull_file(ip: str = target_ip):
                    try:
                        self._apply_incoming_clipboard_files([str(filepath.resolve())])
                        self._pulse_portal_widget(
                            pulse_event="receive_file", peer_ip=ip
                        )
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

                def _apply_png_pull(ip: str = target_ip):
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
                        self._pulse_portal_widget(pulse_event="receive", peer_ip=ip)
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
        wire_ctk_entry_paste(ip_entry)
        
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
            try:
                self.after(0, self._broadcast_clipboard_push_on_main_thread)
            except Exception:
                self._broadcast_clipboard_push_on_main_thread()
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
            wire_ctk_entry_paste(ip_entry)

            def send():
                ip = ip_entry.get().strip()
                if ip:
                    self.set_remote_peer_ip(ip)
                    portal_config.save_peer_send_targets([ip])
                    self.rebuild_peer_checkboxes()
                    dialog.destroy()
                    try:
                        self.after(0, self._broadcast_clipboard_push_on_main_thread)
                    except Exception:
                        self._broadcast_clipboard_push_on_main_thread()

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

            message = merge_outgoing_shared_secret(message)
            # Без лимита времени на передачу больших файлов; отдельный таймаут на ответ OK
            client_socket.settimeout(None)
            _portal_sendall(
                client_socket,
                json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n",
            )
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
                try:
                    portal_history.append_event(
                        direction="send",
                        kind="file",
                        peer_ip=target_ip,
                        peer_label=portal_config.peer_display_label(target_ip),
                        name=filename,
                        stored_path=str(Path(filepath).resolve()),
                        route_json=json.dumps([target_ip]),
                        filesize=filesize,
                    )
                except Exception:
                    pass
                try:
                    self.after(
                        0,
                        lambda ip_=target_ip: self._pulse_portal_widget(
                            pulse_event="send", peer_ip=ip_
                        ),
                    )
                except Exception:
                    pass
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
    
    def _broadcast_clipboard_push_on_main_thread(self) -> None:
        """
        Только главный поток Tk: чтение буфера + постановка TCP-потоков.
        Иначе на Windows фоновый поток часто видит «пустой» буфер (OpenClipboard/pyperclip).
        """
        if not self.get_target_ips():
            self.log(
                "⚠️ Сохрани список IP и отметь получателей (галочки) или укажи IP в виджете"
            )
            return

        with self._clipboard_push_lock:
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
                    sent_ok = self._emit_resolved_clipboard_payload(
                        sock,
                        kind,
                        payload,
                        log=self.log,
                        context_label=f"push → {ip}",
                    )
                    if sent_ok:
                        try:
                            self.after(
                                0,
                                lambda ip_=ip: self._pulse_portal_widget(
                                    pulse_event="send", peer_ip=ip_
                                ),
                            )
                        except Exception:
                            pass
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

            message = merge_outgoing_shared_secret(
                {"type": "clipboard", "text": clipboard_text}
            )
            _portal_sendall(
                client_socket,
                json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n",
            )
            client_socket.close()
            
            self.log(f"✅ Текст отправлен ({len(clipboard_text)} символов)")
            try:
                portal_history.append_event(
                    direction="send",
                    kind="text",
                    peer_ip=target_ip,
                    peer_label=portal_config.peer_display_label(target_ip),
                    name="clipboard",
                    snippet=str(clipboard_text)[:500],
                    stored_path="",
                    route_json=json.dumps([target_ip]),
                )
            except Exception:
                pass
            try:
                self.after(
                    0,
                    lambda ip_=target_ip: self._pulse_portal_widget(
                        pulse_event="send", peer_ip=ip_
                    ),
                )
            except Exception:
                pass
                
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
                if current is None:
                    current = ""
                if current != self.last_clipboard:
                    self.last_clipboard = current
                    if self.sync_clipboard_enabled and str(current).strip():
                        ips = self.get_target_ips()
                        if ips:
                            if not self._try_begin_clipboard_wave():
                                pass
                            else:
                                # Текст уже прочитан на главном потоке — не вызывать pyperclip из фона (Windows).
                                captured = current

                                def _auto_wave():
                                    try:
                                        for ip in ips:
                                            self.send_clipboard_text(ip, captured)
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
            if platform.system() == "Darwin":
                try:
                    from portal_mac_permissions import schedule_mac_permission_flow

                    app.after(500, lambda: schedule_mac_permission_flow(app))
                except Exception:
                    pass
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
