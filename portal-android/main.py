"""
Portal для Android (Kivy): настройки, отправка через Share Sheet, приём файлов с ПК.
"""
from __future__ import annotations

import json
import os
import re
import socket
import threading
import time
from pathlib import Path
from typing import Optional

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.image import AsyncImage
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.utils import platform as kivy_platform

try:
    from portal_protocol import ping_peer, send_file_to_peer, send_text_clipboard
except ImportError:
    ping_peer = None  # type: ignore
    send_file_to_peer = None  # type: ignore
    send_text_clipboard = None  # type: ignore

try:
    from android_share import (
        SharePayload,
        bind_new_intent,
        finish_activity,
        is_android_runtime,
        is_share_intent,
        read_share_intent,
        toast,
    )
except ImportError:
    SharePayload = None  # type: ignore

    def is_android_runtime() -> bool:
        return False

    def is_share_intent(*_a, **_k):
        return False

    def read_share_intent(*_a, **_k):
        return None

    def toast(_m, long=False):
        print(f"[toast] {_m}")

    def finish_activity():
        pass

    def bind_new_intent(_cb):
        pass


PORTAL_SOURCE_ANDROID = "android"
PORTAL_PORT = 12345
CONFIG_NAME = "portal_android_config.json"

try:
    from android_folder_picker import (
        android_cache_dir,
        close_java,
        copy_path_to_java_stream,
        create_document_output_stream,
    )
except ImportError:
    def android_cache_dir() -> str:
        return ""

    def close_java(_o) -> None:
        pass

    def copy_path_to_java_stream(_path: str, _out) -> bool:
        return False

    def create_document_output_stream(_tree: str, _name: str):
        return None, None


# Тема
C_BG     = (0.05, 0.06, 0.10, 1)
C_PANEL  = (0.10, 0.12, 0.19, 1)
C_CARD   = (0.13, 0.15, 0.23, 1)
C_INPUT  = (0.16, 0.18, 0.27, 1)
C_ACCENT = (0.95, 0.45, 0.12, 1)
C_BLUE   = (0.22, 0.48, 0.96, 1)
C_TEXT   = (0.93, 0.94, 0.97, 1)
C_MUTED  = (0.54, 0.57, 0.68, 1)
C_OK     = (0.25, 0.82, 0.55, 1)
C_ERR    = (0.90, 0.32, 0.30, 1)

_GIF_FRAME_DELAY  = 0.06
_GIF_FROZEN_DELAY = 86400.0
_LOG_MAX          = 60


# ── утилиты ─────────────────────────────────────────────────────────────────

def config_path() -> Path:
    try:
        from android.storage import app_storage_path  # type: ignore
        p = Path(app_storage_path()) / CONFIG_NAME
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    except Exception:
        pass
    return Path.home() / ".portal_android" / CONFIG_NAME


def load_cfg() -> dict:
    p = config_path()
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"peers": [], "secret": "", "receive_dir": "", "receive_saf_tree_uri": ""}


def save_cfg(data: dict) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def normalize_peers(raw) -> list:
    out = []
    for p in raw or []:
        if not isinstance(p, dict):
            continue
        ip = str(p.get("ip", "")).strip()
        if not ip:
            continue
        name = str(p.get("name", "") or ip).strip()
        send = p.get("send", True)
        if not isinstance(send, bool):
            send = str(send).strip().lower() in ("1", "true", "yes", "on")
        out.append({"ip": ip, "name": name, "send": send})
    return out


def peers_marked_for_send(peers: list) -> list:
    return [p for p in peers if p.get("send", True)]


def _safe_filename(name: str) -> str:
    n = (name or "").strip() or "shared"
    n = os.path.basename(n.replace("\\", "/"))
    n = re.sub(r"[^\w.\-]+", "_", n, flags=re.UNICODE)
    if not n or n.startswith("."):
        n = "shared_" + n
    return n[:180] if len(n) > 180 else n


def _default_receive_dir() -> str:
    if kivy_platform == "android":
        try:
            from jnius import autoclass  # type: ignore
            Env = autoclass("android.os.Environment")
            dl = Env.getExternalStoragePublicDirectory(Env.DIRECTORY_DOWNLOADS)
            return str(dl.getAbsolutePath())
        except Exception:
            pass
        return "/sdcard/Download"
    return str(Path.home() / "Downloads")


def _mascot_image_source() -> tuple:
    here = Path(__file__).resolve().parent
    gif_local = here / "assets" / "portal_main.gif"
    png_local  = here / "assets" / "icon.png"
    if gif_local.is_file():
        return (str(gif_local.resolve()), True)
    if png_local.is_file():
        return (str(png_local.resolve()), False)
    # Dev run from root
    dev_gif = here.parent / "assets" / "portal_main.gif"
    if dev_gif.is_file():
        return (str(dev_gif.resolve()), True)
    dev_png = here.parent / "assets" / "branding" / "portal_icon.png"
    if dev_png.is_file():
        return (str(dev_png.resolve()), False)
    return (None, False)


def _parse_json_header(data: bytes):
    """Найти первый полный JSON-объект в буфере. Возвращает (dict, end_pos) или (None, 0)."""
    depth = 0
    in_str = False
    esc = False
    for i, b in enumerate(data):
        ch = chr(b)
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(data[: i + 1].decode("utf-8", errors="replace")), i + 1
                    except Exception:
                        return None, 0
    return None, 0


# ── сервер приёма файлов ─────────────────────────────────────────────────────

class ReceiveServer:
    """TCP-сервер на порту 12345 — принимает файлы и текст от десктопного Portal."""

    def __init__(
        self,
        receive_dir: str = "",
        secret: str = "",
        on_event=None,
        saf_tree_uri: str = "",
    ):
        self.receive_dir = receive_dir or _default_receive_dir()
        self.saf_tree_uri = (saf_tree_uri or "").strip()
        self.secret = secret
        self.on_event = on_event   # callback(kind, message) — вызывается через Clock
        self._running  = False
        self._server: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="portal-recv")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        srv = self._server
        if srv:
            try:
                srv.close()
            except Exception:
                pass

    def update_config(
        self, receive_dir: str = "", secret: str = "", saf_tree_uri: str = ""
    ) -> None:
        self.receive_dir = receive_dir or _default_receive_dir()
        self.secret = secret
        self.saf_tree_uri = (saf_tree_uri or "").strip()

    def _emit(self, kind: str, msg: str) -> None:
        if self.on_event:
            Clock.schedule_once(lambda _dt, k=kind, m=msg: self.on_event(k, m), 0)

    def _run(self) -> None:
        while self._running:
            srv = None
            try:
                srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                srv.bind(("0.0.0.0", PORTAL_PORT))
                srv.listen(8)
                srv.settimeout(1.0)
                self._server = srv
                self._emit("info", f"📡 Приём запущен на {PORTAL_PORT}")
                while self._running:
                    try:
                        conn, addr = srv.accept()
                    except socket.timeout:
                        continue
                    except Exception:
                        break
                    threading.Thread(
                        target=self._handle, args=(conn, addr[0]), daemon=True
                    ).start()
            except Exception as e:
                self._emit("error", f"Ошибка сервера: {e} — перезапуск через 5 с")
                time.sleep(5.0)
            finally:
                if srv:
                    try:
                        srv.close()
                    except Exception:
                        pass

    def _handle(self, conn: socket.socket, peer_ip: str) -> None:
        try:
            conn.settimeout(60.0)
            buf = b""
            hdr: Optional[dict] = None
            hdr_end = 0
            # читаем, пока не получим полный JSON-заголовок
            for _ in range(32):
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buf += chunk
                hdr, hdr_end = _parse_json_header(buf)
                if hdr is not None:
                    break

            if hdr is None:
                conn.close()
                return

            secret = (self.secret or "").strip()
            if secret:
                msg_secret = (hdr.get("secret") or "").strip()
                if msg_secret != secret:
                    self._emit("warn", f"⚠️ {peer_ip}: неверный пароль — отклонено")
                    try:
                        conn.sendall(b'{"type":"portal_auth_failed"}')
                    except Exception:
                        pass
                    conn.close()
                    return

            msg_type = str(hdr.get("type", "")).strip()

            if msg_type == "ping":
                try:
                    conn.sendall(json.dumps({"type": "pong"}).encode("utf-8"))
                except Exception:
                    pass
                conn.close()
                return

            if msg_type == "clipboard":
                text = str(hdr.get("text") or "").strip()
                if text:
                    snippet = text[:80] + ("…" if len(text) > 80 else "")
                    self._emit("receive_text", f"📋 Текст от {peer_ip}: «{snippet}»")
                conn.close()
                return

            if msg_type == "file":
                fname    = str(hdr.get("filename", "file")).strip() or "file"
                filesize = int(hdr.get("filesize", 0))
                self._receive_file(conn, peer_ip, fname, filesize, buf[hdr_end:])
                return

            conn.close()
        except Exception as e:
            self._emit("error", f"⚠️ {peer_ip}: {e}")
            try:
                conn.close()
            except Exception:
                pass

    def _receive_file(
        self,
        conn: socket.socket,
        peer_ip: str,
        filename: str,
        filesize: int,
        already: bytes,
    ) -> None:
        safe = _safe_filename(filename)
        ts = int(time.time())
        use_saf = bool(self.saf_tree_uri) and is_android_runtime() and kivy_platform == "android"
        save_dir = self.receive_dir or _default_receive_dir()
        tmp_path: Optional[str] = None
        out_path: Optional[str] = None
        received = len(already)

        try:
            if use_saf:
                cache = android_cache_dir() or save_dir
                try:
                    os.makedirs(cache, exist_ok=True)
                except Exception:
                    pass
                tmp_path = os.path.join(cache, f"_portal_in_{ts}_{safe}")
                with open(tmp_path, "wb") as f:
                    if already:
                        f.write(already)
                    while received < filesize:
                        to_read = min(65536, filesize - received)
                        chunk = conn.recv(to_read)
                        if not chunk:
                            break
                        f.write(chunk)
                        received += len(chunk)
                if received < filesize:
                    self._emit("error", f"⚠️ Файл {safe}: получено {received}/{filesize} байт")
                    return
                out_java, _uri = create_document_output_stream(
                    self.saf_tree_uri, f"{ts}_{safe}"
                )
                if out_java is None:
                    self._emit(
                        "error",
                        f"⚠️ Не удалось создать файл в выбранной папке (проводник): {safe}",
                    )
                    return
                try:
                    if not copy_path_to_java_stream(tmp_path, out_java):
                        self._emit("error", f"⚠️ Ошибка записи в папку проводника: {safe}")
                        return
                finally:
                    close_java(out_java)
                conn.sendall(b"OK")
                kb = max(1, filesize // 1024)
                self._emit(
                    "receive_file",
                    f"📥 Получен файл от {peer_ip}: {safe} ({kb} КБ) → папка (проводник)",
                )
                if is_android_runtime():
                    toast(f"Файл получен: {safe}", long=False)
                return

            try:
                os.makedirs(save_dir, exist_ok=True)
            except Exception as e:
                self._emit("error", f"Не могу создать папку {save_dir}: {e}")
                return

            out_path = os.path.join(save_dir, f"{ts}_{safe}")
            with open(out_path, "wb") as f:
                if already:
                    f.write(already)
                while received < filesize:
                    to_read = min(65536, filesize - received)
                    chunk = conn.recv(to_read)
                    if not chunk:
                        break
                    f.write(chunk)
                    received += len(chunk)
            if received >= filesize:
                conn.sendall(b"OK")
                kb = max(1, filesize // 1024)
                self._emit(
                    "receive_file",
                    f"📥 Получен файл от {peer_ip}: {safe} ({kb} КБ) → {save_dir}",
                )
                if is_android_runtime():
                    toast(f"Файл получен: {safe}", long=False)
            else:
                self._emit("error", f"⚠️ Файл {safe}: получено {received}/{filesize} байт")
        except Exception as e:
            self._emit("error", f"⚠️ Ошибка записи {safe}: {e}")
        finally:
            if tmp_path and os.path.isfile(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            try:
                conn.close()
            except OSError:
                pass


# ── виджеты UI ──────────────────────────────────────────────────────────────

class Card(BoxLayout):
    """Карточка со скруглённым фоном."""

    def __init__(self, bg_color=None, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "vertical"
        self.padding = dp(14)
        self.spacing = dp(10)
        self.size_hint_y = None
        self.bind(minimum_height=self.setter("height"))
        with self.canvas.before:
            Color(*(bg_color or C_PANEL))
            self._rect = RoundedRectangle(radius=[dp(16)])
        self.bind(pos=self._sync, size=self._sync)

    def _sync(self, *_):
        self._rect.pos  = self.pos
        self._rect.size = self.size


class SectionTitle(Label):
    def __init__(self, text, **kwargs):
        super().__init__(
            text=text,
            font_size=dp(16),
            bold=True,
            color=C_TEXT,
            size_hint_y=None,
            height=dp(30),
            halign="left",
            **kwargs,
        )


class Hint(Label):
    def __init__(self, text, **kwargs):
        kwargs.setdefault("font_size", dp(12))
        kwargs.setdefault("color", C_MUTED)
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("halign", "left")
        kwargs.setdefault("valign", "top")
        super().__init__(text=text, **kwargs)
        self.bind(
            width=lambda inst, w: setattr(inst, "text_size", (max(w - dp(4), dp(100)), None))
        )
        self.bind(
            texture_size=lambda inst, ts: setattr(inst, "height", max(ts[1] + dp(4), dp(20)))
        )


def _input(hint="", password=False, height=dp(48), **kwargs) -> TextInput:
    # use_bubble: вставка из буфера долгим нажатием на Android
    kwargs.setdefault("use_bubble", True)
    kwargs.setdefault("use_handles", True)
    return TextInput(
        hint_text=hint,
        multiline=False,
        write_tab=False,
        size_hint_y=None,
        height=height,
        password=password,
        background_color=C_INPUT,
        foreground_color=C_TEXT,
        hint_text_color=C_MUTED,
        padding=[dp(12), dp(13), dp(8), dp(8)],
        **kwargs,
    )


def _btn(text, bg=C_BLUE, height=dp(48), font_size=dp(14), **kwargs) -> Button:
    b = Button(
        text=text,
        size_hint_y=None,
        height=height,
        background_color=bg,
        color=C_TEXT,
        font_size=font_size,
        **kwargs,
    )
    b.bind(
        size=lambda inst, sz: setattr(
            inst, "text_size", (max(sz[0] - dp(10), dp(40)), max(sz[1] - dp(8), dp(26)))
        )
    )
    b.halign = "center"
    b.valign = "middle"
    return b


class PeerRow(BoxLayout):
    """Строка: галочка · IP · подпись · удалить — компактная, без лишних полей."""

    def __init__(self, ip="", name="", send=True, on_remove=None, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "vertical"
        self.spacing     = dp(4)
        self.size_hint_y = None
        self.padding     = [dp(8), dp(8), dp(8), dp(8)]
        self.bind(minimum_height=self.setter("height"))
        self._on_remove = on_remove

        # Нарисуем тёмный фон строки
        with self.canvas.before:
            Color(*C_CARD)
            self._bg = RoundedRectangle(radius=[dp(10)])
        self.bind(pos=lambda *_: setattr(self._bg, "pos", self.pos),
                  size=lambda *_: setattr(self._bg, "size", self.size))

        # Строка 1: галочка + IP
        row1 = BoxLayout(orientation="horizontal", spacing=dp(8),
                         size_hint_y=None, height=dp(44))

        chk_wrap = AnchorLayout(size_hint=(None, 1), width=dp(40))
        self.chk_send = CheckBox(
            size_hint=(None, None), size=(dp(32), dp(32)), active=send
        )
        self.chk_send.color = C_ACCENT
        chk_wrap.add_widget(self.chk_send)
        row1.add_widget(chk_wrap)

        self.ip_input = TextInput(
            hint_text="IP адрес (напр. 100.65.63.84)",
            text=ip,
            multiline=False,
            write_tab=False,
            use_bubble=True,
            use_handles=True,
            size_hint_x=1,
            background_color=C_INPUT,
            foreground_color=C_TEXT,
            hint_text_color=C_MUTED,
            font_size=dp(13),
            padding=[dp(10), dp(11), dp(8), dp(8)],
        )
        row1.add_widget(self.ip_input)
        self.add_widget(row1)

        # Строка 2: подпись + кнопка удалить
        row2 = BoxLayout(orientation="horizontal", spacing=dp(8),
                         size_hint_y=None, height=dp(38))
        row2.add_widget(BoxLayout(size_hint=(None, 1), width=dp(40)))  # отступ под галочку

        self.name_input = TextInput(
            hint_text="Подпись (необязательно)",
            text=name,
            multiline=False,
            write_tab=False,
            use_bubble=True,
            use_handles=True,
            size_hint_x=1,
            background_color=C_INPUT,
            foreground_color=C_TEXT,
            hint_text_color=C_MUTED,
            font_size=dp(12),
            padding=[dp(10), dp(9), dp(8), dp(8)],
        )
        row2.add_widget(self.name_input)

        rm = Button(
            text="✕ Удалить",
            size_hint=(None, 1),
            width=dp(90),
            background_color=(0.42, 0.12, 0.12, 1),
            color=C_TEXT,
            font_size=dp(12),
        )
        rm.bind(on_press=lambda *_: self._do_remove())
        row2.add_widget(rm)
        self.add_widget(row2)

    def _do_remove(self):
        if self._on_remove:
            self._on_remove(self)


# ── основное приложение ──────────────────────────────────────────────────────

class PortalAndroidApp(App):
    title = "Portal"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._share_boot          = False
        self._share_completed     = False
        self._cold_share_started = False
        self._cold_share_ui_mounted = False
        self._peer_rows: list     = []
        self._peers_box           = None
        self._status_lbl          = None
        self._secret_field        = None
        self._receive_dir_field   = None
        self._test_text           = None
        self._mascot: Optional[AsyncImage] = None
        self._mascot_is_gif       = False
        self._conn_lbl            = None
        self._log_label           = None
        self._log_lines: list     = []
        self._ping_event          = None
        self._recv_server: Optional[ReceiveServer] = None
        self._receive_saf_uri: str = ""
        self._cold_share_container: Optional[BoxLayout] = None

    # ── конфиг ──────────────────────────────────────────────────────────────

    def _effective_secret(self) -> str:
        if self._secret_field is not None:
            u = self._secret_field.text.strip()
            if u:
                return u
        return (load_cfg().get("secret") or "").strip()

    # ── build ────────────────────────────────────────────────────────────────

    def build(self):
        Window.clearcolor = C_BG
        if kivy_platform == "android":
            try:
                Window.softinput_mode = "resize"
            except Exception:
                pass
        if is_android_runtime():
            bind_new_intent(self._android_new_intent)
            try:
                if is_share_intent():
                    self._share_boot = True
                    shell = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(10))
                    shell.add_widget(
                        Label(
                            text="Portal",
                            font_size=dp(22),
                            bold=True,
                            color=C_TEXT,
                            size_hint_y=None,
                            height=dp(36),
                            halign="left",
                        )
                    )
                    shell.add_widget(
                        Label(
                            text="Кому отправить файл или текст?",
                            font_size=dp(13),
                            color=C_MUTED,
                            size_hint_y=None,
                            height=dp(28),
                            halign="left",
                        )
                    )
                    self._cold_share_container = BoxLayout(
                        orientation="vertical",
                        spacing=dp(8),
                        size_hint_y=1,
                    )
                    shell.add_widget(self._cold_share_container)
                    return shell
            except Exception:
                pass
        return self._build_ui()

    def _build_ui(self):
        top_pad = dp(16) + (dp(24) if kivy_platform == "android" else dp(8))
        root = BoxLayout(
            orientation="vertical",
            padding=[dp(14), top_pad, dp(14), dp(10)],
            spacing=dp(10),
        )

        # ── Шапка ───────────────────────────────────────────────────────────
        header = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(72),
            spacing=dp(10),
        )

        masc_src, masc_gif = _mascot_image_source()
        if masc_src:
            # AsyncImage + абсолютный путь: на Android file:// часто даёт пустую текстуру (цветной квадрат)
            kw = dict(
                source=masc_src,
                size_hint=(None, None),
                size=(dp(72), dp(72)),
                allow_stretch=True,
                keep_ratio=True,
                mipmap=False,
                nocache=True,
            )
            if masc_gif:
                kw["anim_delay"] = _GIF_FRAME_DELAY
                kw["anim_loop"] = 0
            self._mascot = AsyncImage(**kw)
            self._mascot_is_gif = masc_gif
            self._mascot.color = (1, 1, 1, 1)
            header.add_widget(self._mascot)

        title_col = BoxLayout(orientation="vertical", size_hint_x=1)
        title_col.add_widget(
            Label(
                text="Portal",
                font_size=dp(24),
                bold=True,
                color=C_TEXT,
                size_hint_y=None,
                height=dp(34),
                halign="left",
                valign="middle",
            )
        )
        self._conn_lbl = Label(
            text="Проверка…",
            font_size=dp(12),
            color=C_MUTED,
            size_hint_y=None,
            height=dp(24),
            halign="left",
            valign="top",
        )
        self._conn_lbl.bind(
            width=lambda inst, w: setattr(inst, "text_size", (w, None))
        )
        title_col.add_widget(self._conn_lbl)
        header.add_widget(title_col)

        menu_btn = _btn("Справка", bg=(0.14, 0.17, 0.25, 1), height=dp(40), font_size=dp(12))
        menu_btn.size_hint   = (None, None)
        menu_btn.size        = (dp(72), dp(40))
        menu_btn.pos_hint    = {"center_y": 0.5}
        menu_btn.bind(on_press=lambda *_: self._help())
        header.add_widget(menu_btn)

        root.add_widget(header)

        # ── Прокручиваемое тело ─────────────────────────────────────────────
        scroll = ScrollView(
            do_scroll_x=False,
            bar_width=dp(5),
            size_hint_y=1,
            scroll_type=["bars", "content"],
        )
        body = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=dp(12),
            padding=(0, 0, 0, dp(8)),
        )
        body.bind(minimum_height=body.setter("height"))

        # ── Адреса ─────────────────────────────────────────────────────────
        peers_card = Card()
        peers_card.add_widget(SectionTitle("Адреса компьютеров"))
        peers_card.add_widget(
            Hint("☑ галочка = разрешить отправку на этот адрес. IP как в настольном Portal.")
        )
        self._peers_box = BoxLayout(
            orientation="vertical",
            spacing=dp(6),
            size_hint_y=None,
        )
        self._peers_box.bind(minimum_height=self._peers_box.setter("height"))
        peers_card.add_widget(self._peers_box)

        add_btn = _btn("+ Добавить адрес", bg=C_BLUE, height=dp(44))
        add_btn.bind(on_press=lambda *_: self._add_peer_row())
        peers_card.add_widget(add_btn)
        body.add_widget(peers_card)

        # ── Пароль ─────────────────────────────────────────────────────────
        sec_card = Card()
        sec_card.add_widget(SectionTitle("Пароль сети"))
        sec_card.add_widget(
            Hint(
                "Должен совпадать с паролем в настольном Portal: Настройки → Пароль. "
                "Обновляется сразу после ввода — сохранять перед тестом не обязательно."
            )
        )
        self._secret_field = _input("Пароль сети", password=False)
        sec_card.add_widget(self._secret_field)
        body.add_widget(sec_card)

        # ── Папка приёма ───────────────────────────────────────────────────
        recv_card = Card()
        recv_card.add_widget(SectionTitle("Папка для входящих файлов"))
        recv_card.add_widget(
            Hint(
                "Файлы с ПК сохраняются сюда. По умолчанию — системная папка «Загрузки». "
                "Кнопка «Выбрать папку» открывает проводник Android (можно создать папку там же)."
            )
        )
        self._receive_dir_field = _input(
            hint=_default_receive_dir(),
        )
        recv_card.add_widget(self._receive_dir_field)
        pick_row = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(44),
            spacing=dp(8),
        )
        pick_btn = _btn("📂 Выбрать папку", bg=C_BLUE, height=dp(44), font_size=dp(13))
        pick_btn.bind(on_press=lambda *_: self._pick_receive_folder())
        reset_btn = _btn("↺ Загрузки", bg=(0.18, 0.2, 0.28, 1), height=dp(44), font_size=dp(12))
        reset_btn.bind(on_press=lambda *_: self._reset_receive_folder_default())
        pick_row.add_widget(pick_btn)
        pick_row.add_widget(reset_btn)
        recv_card.add_widget(pick_row)
        body.add_widget(recv_card)

        # ── Кнопки сохранить/проверить связь ──────────────────────────────
        act_card = Card()
        row1 = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(10))
        save_btn = _btn("💾 Сохранить", bg=C_BLUE, height=dp(50))
        save_btn.bind(on_press=lambda *_: self.save_settings())
        ping_btn = _btn("🔗 Проверить связь", bg=(0.18, 0.38, 0.22, 1), height=dp(50))
        ping_btn.bind(on_press=lambda *_: self._ping_peers_bg())
        row1.add_widget(save_btn)
        row1.add_widget(ping_btn)
        act_card.add_widget(row1)
        body.add_widget(act_card)

        # ── Тест отправки текста ──────────────────────────────────────────
        test_card = Card()
        test_card.add_widget(SectionTitle("Тест: отправить текст на ПК"))
        self._test_text = TextInput(
            hint_text="Текст для проверки",
            multiline=True,
            write_tab=False,
            use_bubble=True,
            use_handles=True,
            size_hint_y=None,
            height=dp(80),
            background_color=C_INPUT,
            foreground_color=C_TEXT,
            hint_text_color=C_MUTED,
            padding=[dp(12), dp(10), dp(8), dp(8)],
        )
        test_card.add_widget(self._test_text)
        send_txt_btn = _btn("Отправить текст →", bg=C_ACCENT, height=dp(48))
        send_txt_btn.bind(on_press=lambda *_: self.send_test_text())
        test_card.add_widget(send_txt_btn)
        body.add_widget(test_card)

        # ── Лог активности ─────────────────────────────────────────────────
        log_card = Card(bg_color=(0.08, 0.09, 0.14, 1))
        log_card.add_widget(SectionTitle("Журнал активности"))
        log_scroll = ScrollView(
            do_scroll_x=False,
            size_hint_y=None,
            height=dp(180),
            bar_width=dp(4),
        )
        self._log_label = Label(
            text="",
            font_size=dp(11),
            color=C_MUTED,
            size_hint_y=None,
            halign="left",
            valign="top",
        )
        self._log_label.bind(
            width=lambda inst, w: setattr(inst, "text_size", (max(w - dp(4), dp(100)), None))
        )
        self._log_label.bind(
            texture_size=lambda inst, ts: setattr(inst, "height", max(ts[1] + dp(4), dp(40)))
        )
        log_scroll.add_widget(self._log_label)
        log_card.add_widget(log_scroll)

        clr_btn = _btn("Очистить журнал", bg=(0.15, 0.17, 0.24, 1), height=dp(36), font_size=dp(12))
        clr_btn.bind(on_press=lambda *_: self._clear_log())
        log_card.add_widget(clr_btn)
        body.add_widget(log_card)

        # ── Статусная строка ───────────────────────────────────────────────
        self._status_lbl = Label(
            text="Сохраните настройки. Для отправки: «Поделиться» → Portal.",
            font_size=dp(12),
            color=C_MUTED,
            size_hint_y=None,
            height=dp(36),
            halign="left",
            valign="top",
        )
        self._status_lbl.bind(
            width=lambda inst, w: setattr(inst, "text_size", (max(w - dp(4), dp(100)), None))
        )
        body.add_widget(self._status_lbl)

        scroll.add_widget(body)
        root.add_widget(scroll)

        # Загрузить конфиг
        cfg = load_cfg()
        if self._secret_field:
            self._secret_field.text = cfg.get("secret", "") or ""
        self._receive_saf_uri = (cfg.get("receive_saf_tree_uri") or "").strip()
        if self._receive_dir_field:
            if self._receive_saf_uri:
                self._receive_dir_field.text = (
                    "📁 Папка выбрана в проводнике — нажми «💾 Сохранить»."
                )
            else:
                rdir = cfg.get("receive_dir", "") or ""
                self._receive_dir_field.text = rdir or _default_receive_dir()
        for pr in normalize_peers(cfg.get("peers")):
            self._add_peer_row(ip=pr["ip"], name=pr.get("name") or pr["ip"], send=pr.get("send", True))
        if not self._peer_rows:
            self._add_peer_row()

        return root

    # ── on_start / on_stop ──────────────────────────────────────────────────

    def on_start(self):
        # ВАЖНО: при старте из Share Sheet раньше не поднимали ReceiveServer — исправлено.
        Clock.schedule_once(lambda _dt: self._start_receive_server(), 0.05)
        if kivy_platform == "android":
            try:
                from android_folder_picker import bind_folder_picker

                bind_folder_picker()
            except Exception:
                pass
        if self._share_boot:
            Clock.schedule_once(lambda _dt: self._mount_cold_share_ui(), 0.2)
        else:
            Clock.schedule_once(lambda _dt: self._start_ping_watch(), 0.5)

    def on_stop(self):
        if self._ping_event:
            try:
                self._ping_event.cancel()
            except Exception:
                pass
        if self._recv_server:
            self._recv_server.stop()

    # ── Сервер приёма ────────────────────────────────────────────────────────

    def _start_receive_server(self):
        if self._recv_server is not None:
            try:
                self._recv_server.stop()
            except Exception:
                pass
            self._recv_server = None
        cfg = load_cfg()
        secret = cfg.get("secret", "") or ""
        saf = (cfg.get("receive_saf_tree_uri") or "").strip()
        recv_dir = cfg.get("receive_dir", "") or _default_receive_dir()
        if not saf:
            recv_dir = recv_dir or _default_receive_dir()
        self._recv_server = ReceiveServer(
            receive_dir=recv_dir,
            secret=secret,
            on_event=self._on_server_event,
            saf_tree_uri=saf,
        )
        self._recv_server.start()

    def _on_server_event(self, kind: str, msg: str) -> None:
        self._log(msg)
        if kind in ("receive_file", "receive_text"):
            if self._status_lbl:
                self._status_lbl.text = msg

    # ── Лог ─────────────────────────────────────────────────────────────────

    def _log(self, msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        self._log_lines.append(line)
        if len(self._log_lines) > _LOG_MAX:
            self._log_lines = self._log_lines[-_LOG_MAX:]
        if self._log_label:
            self._log_label.text = "\n".join(reversed(self._log_lines))

    def _clear_log(self) -> None:
        self._log_lines.clear()
        if self._log_label:
            self._log_label.text = ""

    # ── Ping / статус связи ──────────────────────────────────────────────────

    def _start_ping_watch(self):
        self._ping_peers_bg()
        if self._ping_event:
            try:
                self._ping_event.cancel()
            except Exception:
                pass
        self._ping_event = Clock.schedule_interval(lambda _dt: self._ping_peers_bg(), 25.0)

    def _ping_peers_bg(self):
        if ping_peer is None:
            self._apply_ping_ui(False, 0, 0, reason="noping")
            return
        peers = [
            row.ip_input.text.strip()
            for row in (self._peer_rows or [])
            if row.ip_input.text.strip() and row.chk_send.active
        ]
        secret = self._effective_secret()
        if not peers:
            self._apply_ping_ui(False, 0, 0, reason="nopeers")
            return

        def work():
            ok = sum(
                1 for ip in peers
                if (lambda: (
                    next(iter([ping_peer(ip, secret=secret, timeout=4.0)]), False)
                ))()
            )
            Clock.schedule_once(
                lambda _dt, o=ok, t=len(peers): self._apply_ping_ui(o > 0, o, t), 0
            )

        def work2():
            ok = 0
            for ip in peers:
                try:
                    if ping_peer(ip, secret=secret, timeout=4.0):
                        ok += 1
                except Exception:
                    pass
            Clock.schedule_once(
                lambda _dt, o=ok, t=len(peers): self._apply_ping_ui(o > 0, o, t), 0
            )

        threading.Thread(target=work2, daemon=True).start()

    def _apply_ping_ui(self, any_ok: bool, ok_n: int, total: int, reason="") -> None:
        m = self._mascot
        lbl = self._conn_lbl
        if any_ok:
            if m:
                m.color = (1, 1, 1, 1)
                try:
                    if self._mascot_is_gif:
                        m.anim_delay = _GIF_FRAME_DELAY
                except Exception:
                    pass
            if lbl:
                lbl.color = C_OK
                lbl.text = (
                    f"✅ Связь: все {total} отвечают" if ok_n == total
                    else f"⚡ Связь: {ok_n}/{total}"
                )
        else:
            if m:
                m.color = (0.5, 0.5, 0.5, 0.9)
                try:
                    if self._mascot_is_gif:
                        m.anim_delay = _GIF_FROZEN_DELAY
                except Exception:
                    pass
            if lbl:
                lbl.color = C_MUTED
                if reason == "nopeers":
                    lbl.text = "Укажите адрес и сохраните."
                elif reason == "noping":
                    lbl.text = "Проверка недоступна."
                else:
                    lbl.text = "⚠️ Нет ответа от ПК."

    # ── Peers ───────────────────────────────────────────────────────────────

    def _add_peer_row(self, ip="", name="", send=True):
        if not self._peers_box:
            return

        def on_remove(row):
            if row in self._peer_rows:
                self._peer_rows.remove(row)
            self._peers_box.remove_widget(row)

        row = PeerRow(ip=ip, name=name, send=send, on_remove=on_remove)
        self._peer_rows.append(row)
        self._peers_box.add_widget(row)

    # ── Сохранить ───────────────────────────────────────────────────────────

    def save_settings(self) -> None:
        try:
            peers = [
                {
                    "ip": row.ip_input.text.strip(),
                    "name": row.name_input.text.strip() or row.ip_input.text.strip(),
                    "send": bool(row.chk_send.active),
                }
                for row in self._peer_rows
                if row.ip_input.text.strip()
            ]
            if not peers:
                self._set_status("Добавьте хотя бы один IP-адрес.")
                return

            secret = self._secret_field.text.strip() if self._secret_field else ""
            recv_txt = (self._receive_dir_field.text or "").strip() if self._receive_dir_field else ""
            saf = (self._receive_saf_uri or "").strip()
            if saf:
                recv_dir = _default_receive_dir()
            else:
                if recv_txt.startswith("📁"):
                    recv_dir = _default_receive_dir()
                else:
                    recv_dir = recv_txt or _default_receive_dir()

            cfg = {
                "peers": peers,
                "secret": secret,
                "receive_dir": recv_dir,
                "receive_saf_tree_uri": saf,
            }
            save_cfg(cfg)

            if self._recv_server:
                self._recv_server.update_config(
                    receive_dir=recv_dir or _default_receive_dir(),
                    secret=secret,
                    saf_tree_uri=saf,
                )

            n_send = sum(1 for p in peers if p.get("send"))
            dest_human = "папка из проводника" if saf else (recv_dir or _default_receive_dir())
            self._set_status(
                f"Сохранено: {len(peers)} адрес(ов), отправка на {n_send}. Приём → {dest_human}"
            )
            self._log(f"💾 Настройки сохранены ({len(peers)} адрес(ов), пароль: {'да' if secret else 'нет'})")
            if is_android_runtime():
                toast("Настройки сохранены", long=False)
            Clock.schedule_once(lambda _dt: self._ping_peers_bg(), 0.4)
        except Exception as e:
            self._set_status(f"Ошибка: {e}")

    def _pick_receive_folder(self) -> None:
        if kivy_platform != "android":
            self._set_status("Выбор папки только на Android.")
            return
        try:
            from android_folder_picker import pick_receive_folder
        except Exception as e:
            self._set_status(f"Проводник недоступен: {e}")
            return

        def on_uri(uri: Optional[str]) -> None:
            def apply(*_a):
                if not uri:
                    toast("Папка не выбрана", long=False)
                    return
                self._receive_saf_uri = uri.strip()
                if self._receive_dir_field:
                    self._receive_dir_field.text = (
                        "📁 Папка выбрана в проводнике — нажми «💾 Сохранить»."
                    )
                self._set_status("Папка выбрана. Нажми «💾 Сохранить».")
            Clock.schedule_once(apply, 0)

        pick_receive_folder(on_uri)

    def _reset_receive_folder_default(self) -> None:
        self._receive_saf_uri = ""
        d = _default_receive_dir()
        if self._receive_dir_field:
            self._receive_dir_field.text = d
        self._set_status(f"Сброс на Загрузки: {d}")
        toast("Указана папка Загрузки — сохрани настройки", long=False)

    def _set_status(self, msg: str) -> None:
        if self._status_lbl:
            self._status_lbl.text = msg

    # ── Тест текста ─────────────────────────────────────────────────────────

    def send_test_text(self) -> None:
        if send_text_clipboard is None:
            self._set_status("portal_protocol недоступен.")
            return
        peers = [
            {"ip": r.ip_input.text.strip(), "name": r.name_input.text.strip() or r.ip_input.text.strip(), "send": r.chk_send.active}
            for r in self._peer_rows
            if r.ip_input.text.strip()
        ]
        targets = peers_marked_for_send(peers)
        if not targets:
            self._set_status("Отметьте галочкой хотя бы одного получателя.")
            return
        secret = self._effective_secret()
        txt    = (self._test_text.text if self._test_text else "") or "Привет от Portal!"

        def work():
            oks, errs = 0, []
            for p in targets:
                ok, err = send_text_clipboard(
                    p["ip"], txt, secret=secret, portal_source=PORTAL_SOURCE_ANDROID
                )
                if ok:
                    oks += 1
                else:
                    errs.append(f"{p.get('name') or p['ip']}: {err}")
            def done():
                if oks == len(targets):
                    msg = f"✅ Текст доставлен на {oks} ПК."
                elif oks:
                    msg = f"⚡ Частично: {oks} ок, {'; '.join(errs[:2])}"
                else:
                    msg = f"❌ {'; '.join(errs[:2])}"
                self._set_status(msg)
                self._log(msg)
            Clock.schedule_once(lambda _dt: done(), 0)
        threading.Thread(target=work, daemon=True).start()

    # ── Share Sheet ──────────────────────────────────────────────────────────

    def _mount_cold_share_ui(self) -> None:
        if self._cold_share_ui_mounted:
            return
        self._cold_share_ui_mounted = True
        cont = self._cold_share_container
        if cont is None:
            toast("Portal: внутренняя ошибка Share", long=True)
            finish_activity()
            return
        try:
            payload = read_share_intent()
        except Exception as ex:
            toast(f"Portal: {ex}", long=True)
            finish_activity()
            return
        if not self._payload_ok(payload):
            toast("Portal: пустой «Поделиться»", long=True)
            finish_activity()
            return
        cfg = load_cfg()
        peers = normalize_peers(cfg.get("peers"))
        targets = peers_marked_for_send(peers)
        if not targets:
            toast(
                "Нет адресов ПК. Открой Portal из иконки, добавь IP и «💾 Сохранить», "
                "затем снова «Поделиться» → Portal.",
                long=True,
            )
            finish_activity()
            return
        secret = (cfg.get("secret") or "").strip()
        cont.clear_widgets()
        cont.add_widget(
            self._build_share_destinations_panel(payload, targets, secret, popup=None)
        )

    def _payload_ok(self, payload) -> bool:
        if not payload:
            return False
        return bool(payload.file_paths) or bool((payload.text or "").strip())

    def _build_share_destinations_panel(
        self,
        payload,
        targets: list,
        secret: str,
        *,
        popup: Optional[Popup],
    ):
        """Галочки по ПК + «Подтвердить» / «Отмена». popup=None — холодный Share (полный экран)."""
        cold_cancel = popup is None and self._share_boot
        checks: list = []

        root = BoxLayout(orientation="vertical", spacing=dp(12), padding=dp(6), size_hint_y=1)

        nfiles = len(payload.file_paths)
        if nfiles:
            names = [os.path.basename(p) for p in payload.file_paths[:5]]
            preview = "📎 " + ", ".join(names) + ("…" if nfiles > 5 else "")
        else:
            tx = (payload.text or "").strip()
            preview = (
                (f"📋 {tx[:220]}…" if len(tx) > 220 else f"📋 {tx}") if tx else "—"
            )

        prev_lbl = Label(
            text=f"Отправить:\n{preview}",
            font_size=dp(14),
            color=C_TEXT,
            size_hint_y=None,
            halign="left",
            valign="top",
        )
        prev_lbl.bind(
            width=lambda inst, w: setattr(inst, "text_size", (max(w - dp(4), dp(80)), None))
        )
        prev_lbl.bind(
            texture_size=lambda inst, ts: setattr(
                inst, "height", max(ts[1] + dp(8), dp(44))
            )
        )
        root.add_widget(prev_lbl)

        root.add_widget(
            Label(
                text="Кому отправить (сними галочку, если не нужен):",
                font_size=dp(12),
                color=C_MUTED,
                size_hint_y=None,
                height=dp(30),
                halign="left",
            )
        )

        scroll = ScrollView(do_scroll_x=False, bar_width=dp(4), size_hint_y=1)
        col = BoxLayout(orientation="vertical", spacing=dp(6), size_hint_y=None)
        col.bind(minimum_height=col.setter("height"))
        for p in targets:
            row = BoxLayout(
                orientation="horizontal",
                size_hint_y=None,
                height=dp(48),
                spacing=dp(8),
            )
            cb = CheckBox(size_hint=(None, None), size=(dp(40), dp(40)), active=True)
            cb.color = C_ACCENT
            lbl = Label(
                text=p.get("name") or p["ip"],
                font_size=dp(14),
                color=C_TEXT,
                halign="left",
                valign="middle",
                size_hint_x=1,
            )
            lbl.bind(
                size=lambda inst, sz: setattr(
                    inst, "text_size", (max(sz[0] - 4, dp(60)), None)
                )
            )
            row.add_widget(cb)
            row.add_widget(lbl)
            col.add_widget(row)
            checks.append((cb, p))
        scroll.add_widget(col)
        root.add_widget(scroll)

        btn_row = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(54),
            spacing=dp(10),
        )

        def confirm(*_a):
            sel = [peer for cb, peer in checks if cb.active]
            if not sel:
                toast("Отметь хотя бы один ПК", long=False)
                return
            if popup is not None:
                try:
                    popup.dismiss()
                except Exception:
                    pass
            self._share_completed = True
            self._send_with_progress(payload, sel, secret)

        def cancel(*_a):
            if popup is not None:
                try:
                    popup.dismiss()
                except Exception:
                    pass
            if cold_cancel:
                finish_activity()

        b_ok = _btn("Подтвердить отправку", bg=C_BLUE, height=dp(50), font_size=dp(14))
        b_ok.bind(on_press=confirm)
        b_cancel = _btn("Отмена", bg=(0.28, 0.30, 0.38, 1), height=dp(50), font_size=dp(13))
        b_cancel.bind(on_press=cancel)
        btn_row.add_widget(b_ok)
        btn_row.add_widget(b_cancel)
        root.add_widget(btn_row)
        return root

    def _android_new_intent(self, intent) -> None:
        try:
            if not is_share_intent(intent=intent):
                return
            payload = read_share_intent(intent=intent)
            Clock.schedule_once(lambda _dt: self._run_share(payload), 0.05)
        except Exception as ex:
            toast(f"Portal: {ex}", long=True)
            finish_activity()

    def _run_share(self, payload) -> None:
        if send_file_to_peer is None or send_text_clipboard is None:
            toast("Portal: нет portal_protocol", long=True)
            finish_activity()
            return
        if not self._payload_ok(payload):
            toast("Portal: пустой share", long=True)
            finish_activity()
            return

        cfg = load_cfg()
        peers = normalize_peers(cfg.get("peers"))
        secret = (cfg.get("secret") or "").strip()
        targets = peers_marked_for_send(peers)

        if not targets:
            toast(
                "Добавь IP компьютера в Portal и «💾 Сохранить», затем повтори «Поделиться».",
                long=True,
            )
            finish_activity()
            return

        self._share_completed = False
        popup = Popup(
            title="Отправить через Portal",
            size_hint=(0.92, 0.76),
            auto_dismiss=False,
        )
        panel = self._build_share_destinations_panel(
            payload, targets, secret, popup=popup
        )
        popup.content = panel
        popup.open()

    def _send_with_progress(self, payload, targets: list, secret: str) -> None:
        """Показать попап прогресса, отправить в фоне, закрыть по завершении."""
        n_files = len(payload.file_paths)
        n_text  = 1 if (payload.text or "").strip() else 0
        total   = n_files + n_text
        names   = [os.path.basename(fp) for fp in payload.file_paths]
        if payload.text and not names:
            preview = (payload.text or "")[:40]
        else:
            preview = ", ".join(names[:3]) + ("…" if len(names) > 3 else "")

        layout = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(14))
        prog_lbl = Label(
            text=f"Отправка: {preview}",
            font_size=dp(14),
            color=C_TEXT,
            size_hint_y=None,
            height=dp(56),
            halign="center",
            valign="middle",
        )
        prog_lbl.bind(
            size=lambda inst, sz: setattr(inst, "text_size", (max(sz[0] - dp(8), dp(80)), None))
        )
        dest_lbl = Label(
            text=f"→ {', '.join(p.get('name') or p['ip'] for p in targets[:2])}",
            font_size=dp(12),
            color=C_MUTED,
            size_hint_y=None,
            height=dp(28),
            halign="center",
        )
        layout.add_widget(prog_lbl)
        layout.add_widget(dest_lbl)

        pop = Popup(
            title="Отправка…",
            content=layout,
            size_hint=(0.85, 0.38),
            auto_dismiss=False,
        )
        pop.open()

        src = PORTAL_SOURCE_ANDROID

        def work():
            errs = []
            for peer in targets:
                ip   = peer["ip"]
                name = peer.get("name") or ip
                for fp in payload.file_paths:
                    fn = os.path.basename(fp)
                    Clock.schedule_once(
                        lambda _dt, f=fn, n=name: setattr(prog_lbl, "text", f"📤 {f}\n→ {n}"),
                        0,
                    )
                    ok, err = send_file_to_peer(ip, fp, secret=secret, portal_source=src)
                    if not ok:
                        errs.append(f"{name}: {fn} — {err}")
                if (payload.text or "").strip():
                    Clock.schedule_once(
                        lambda _dt, n=name: setattr(prog_lbl, "text", f"📋 Текст → {n}"),
                        0,
                    )
                    ok, err = send_text_clipboard(
                        ip, payload.text, secret=secret, portal_source=src
                    )
                    if not ok:
                        errs.append(f"{name}: текст — {err}")

            def done():
                pop.dismiss()
                if errs:
                    msg = "; ".join(errs[:3])
                    if len(errs) > 3:
                        msg += "…"
                    toast(f"Portal: {msg}", long=True)
                    self._log(f"❌ Отправка: {msg}")
                else:
                    what = (
                        f"{n_files} файл(ов)" if n_files else ""
                    )
                    to   = ", ".join(p.get("name") or p["ip"] for p in targets[:2])
                    msg  = f"✅ {what or 'Текст'} отправлен → {to}"
                    toast("Portal: отправлено", long=False)
                    self._log(msg)
                finish_activity()

            Clock.schedule_once(lambda _dt: done(), 0)

        threading.Thread(target=work, daemon=True).start()

    # ── Справка ──────────────────────────────────────────────────────────────

    def _help(self) -> None:
        text = (
            "Portal — передача файлов и текста между Android и компьютером в одной сети "
            "(локальная сеть или Tailscale VPN).\n\n"
            "Отправить с телефона на ПК\n"
            "• «Поделиться» → Portal → отметь галочками ПК → «Подтвердить отправку».\n"
            "• Или «Тест: отправить текст» в приложении.\n\n"
            "Получить файл с ПК на телефон\n"
            "• Portal должен быть запущен (приём работает в фоне).\n"
            "• Папка: по умолчанию «Загрузки»; кнопка «Выбрать папку» открывает проводник.\n"
            "• После выбора папки нажми «💾 Сохранить».\n\n"
            "Адреса\n"
            "• IP-адрес ПК отображается в шапке настольного Portal (часто 100.… в Tailscale).\n"
            "• Галочка рядом с адресом = разрешена отправка на этот ПК.\n\n"
            "Пароль\n"
            "• Должен совпадать с настольным Portal: Настройки → Пароль.\n\n"
            "Связь\n"
            "• Зелёный значок → ПК отвечает. Серый → ПК недоступен или не запущен приём.\n\n"
            "Журнал активности\n"
            "• Все события (приём, отправка, ошибки) отображаются в журнале."
        )

        outer = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(10))
        scroll = ScrollView(do_scroll_x=False, bar_width=dp(5))
        lbl = Label(
            text=text,
            font_size=dp(14),
            color=C_TEXT,
            size_hint_y=None,
            halign="left",
            valign="top",
        )
        lbl.bind(
            width=lambda inst, w: setattr(inst, "text_size", (max(w - dp(8), dp(100)), None))
        )
        lbl.bind(
            texture_size=lambda inst, ts: setattr(inst, "height", max(ts[1] + dp(8), dp(80)))
        )
        scroll.add_widget(lbl)
        outer.add_widget(scroll)

        close_btn = _btn("Закрыть", bg=C_BLUE, height=dp(48))
        outer.add_widget(close_btn)

        pop = Popup(title="Справка", content=outer, size_hint=(0.92, 0.88))
        close_btn.bind(on_press=pop.dismiss)
        pop.open()


if __name__ == "__main__":
    PortalAndroidApp().run()
