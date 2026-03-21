"""
Portal для Android (Kivy): адреса в вашей сети, пароль, отправка через Share Sheet (ACTION_SEND).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.checkbox import CheckBox
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.popup import Popup
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
        pass

    def finish_activity():
        pass

    def bind_new_intent(_cb):
        pass


PORTAL_SOURCE_ANDROID = "android"
CONFIG_NAME = "portal_android_config.json"

# Тёмная тема в духе «портала»: тёмно-синий + оранжевый акцент
C_BG = (0.06, 0.07, 0.11, 1)
C_PANEL = (0.11, 0.13, 0.2, 1)
C_ACCENT = (0.95, 0.45, 0.12, 1)
C_ACCENT_2 = (0.2, 0.45, 0.95, 1)
C_TEXT = (0.92, 0.93, 0.96, 1)
C_MUTED = (0.55, 0.58, 0.68, 1)


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
    return {"peers": [], "secret": ""}


def save_cfg(data: dict) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def normalize_peers(raw) -> list:
    """Как peer_ips + алиасы на ПК; send = «отмечен в списке кому слать» (аналог галочек на главном экране)."""
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
    """Только те IP, куда разрешена отправка (галочка)."""
    return [p for p in peers if p.get("send", True)]


def _asset_icon_path() -> Path:
    return Path(__file__).resolve().parent / "assets" / "icon.png"


_GIF_FRAME_DELAY = 0.06
_GIF_FROZEN_DELAY = 86400.0

HELP_TEXT = (
    "Portal для Android пересылает файлы и текст на компьютеры в вашей сети (локальная сеть или VPN), "
    "где запущен настольный Portal и активна кнопка «Запустить портал».\n\n"
    "Адреса\n"
    "Введите те же IP, что указаны в настольном приложении: ⚙ Настройки → «Пиры» "
    "(один адрес на строку, при необходимости с подписью).\n\n"
    "Откуда взять адрес\n"
    "В верхней части окна настольного Portal показан текущий адрес "
    "(часто это Tailscale 100.… или локальный адрес в LAN).\n\n"
    "Галочка\n"
    "Отметка слева означает разрешение отправки на этот адрес — по смыслу совпадает с выбором получателей "
    "в настольном Portal.\n\n"
    "Пароль сети\n"
    "Должен совпадать с полем «Пароль» в настройках настольного Portal на всех участвующих компьютерах.\n\n"
    "Поделиться\n"
    "После сохранения настроек в любом приложении можно выбрать «Поделиться» → Portal — "
    "данные отправятся на отмеченные адреса."
)


def _portal_gif_path() -> str | None:
    """GIF в APK (portal-android/assets) или при запуске из корня репозитория."""
    here = Path(__file__).resolve().parent
    for candidate in (
        here / "assets" / "portal_main.gif",
        here.parent / "assets" / "portal_main.gif",
    ):
        if candidate.is_file():
            return str(candidate)
    return None


class Panel(BoxLayout):
    """Карточка с скруглённым фоном."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "vertical"
        self.padding = dp(14)
        self.spacing = dp(10)
        # Внутри ScrollView дочерние BoxLayout с size_hint_y=1 «растягиваются» и ломают minimum_height —
        # кнопки и подписи наезжают друг на друга. Фиксируем высоту по содержимому.
        self.size_hint_y = None
        self.bind(minimum_height=self.setter("height"))
        with self.canvas.before:
            Color(*C_PANEL)
            self._rect = RoundedRectangle(radius=[dp(16)])
        self.bind(pos=self._sync_rect, size=self._sync_rect)

    def _sync_rect(self, *_args):
        self._rect.pos = self.pos
        self._rect.size = self.size


class PeerRow(BoxLayout):
    """Строка как на ПК: галочка «кому слать» + IP + подпись + удалить."""

    def __init__(
        self,
        ip: str = "",
        name: str = "",
        send: bool = True,
        on_remove=None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.orientation = "horizontal"
        self.spacing = dp(6)
        self.size_hint_y = None
        self.height = dp(54)
        self._on_remove = on_remove

        # Галочка — как на главном экране Portal на ПК («Кому отправлять»)
        self.chk_send = CheckBox(
            size_hint=(None, None), size=(dp(36), dp(36)), active=send
        )
        self.chk_send.color = C_ACCENT
        wrap_chk = AnchorLayout(size_hint=(None, 1), width=dp(44))
        wrap_chk.add_widget(self.chk_send)
        self.add_widget(wrap_chk)

        self.ip_input = TextInput(
            hint_text="IP узла в сети (например 100.…)",
            text=ip,
            multiline=False,
            size_hint_x=0.44,
            background_color=(0.16, 0.18, 0.26, 1),
            foreground_color=C_TEXT,
            hint_text_color=C_MUTED,
            padding=[dp(10), dp(12), dp(8), dp(8)],
        )
        self.name_input = TextInput(
            hint_text="Подпись (необязательно)",
            text=name,
            multiline=False,
            size_hint_x=0.36,
            background_color=(0.16, 0.18, 0.26, 1),
            foreground_color=C_TEXT,
            hint_text_color=C_MUTED,
            padding=[dp(10), dp(12), dp(8), dp(8)],
        )
        rm = Button(
            text="✕",
            size_hint_x=0.12,
            background_color=(0.35, 0.18, 0.18, 1),
            color=C_TEXT,
        )
        rm.bind(on_press=lambda *_a: self._do_remove())
        self.add_widget(self.ip_input)
        self.add_widget(self.name_input)
        self.add_widget(rm)

    def _do_remove(self):
        if self._on_remove:
            self._on_remove(self)


class PortalAndroidApp(App):
    title = "Portal"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._share_boot = False
        self._share_completed = False
        self._settings_root = None
        self._cold_share_started = False
        self._peer_rows: list = []
        self._peers_box: BoxLayout | None = None
        self._status_label: Label | None = None
        self._secret_field: TextInput | None = None
        self._test_text: TextInput | None = None
        self._portal_mascot: Image | None = None
        self._conn_status_lbl: Label | None = None
        self._ping_event = None

    def build(self):
        Window.clearcolor = C_BG
        if is_android_runtime():
            bind_new_intent(self._android_on_new_intent)
            try:
                if is_share_intent():
                    self._share_boot = True
                    return FloatLayout()
            except Exception:
                pass

        return self._build_settings_ui()

    def _build_settings_ui(self):
        top_pad = dp(12) + (dp(8) if kivy_platform == "android" else 0)
        root = BoxLayout(
            orientation="vertical",
            padding=[dp(16), top_pad, dp(16), dp(16)],
            spacing=dp(12),
        )
        self._settings_root = root

        # Шапка: меню · GIF Portal (серый = нет связи, цветной = ответ узла) · заголовок и статус
        header = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            spacing=dp(10),
            padding=[0, 0, 0, dp(2)],
        )
        menu_btn = Button(
            text="☰",
            size_hint=(None, None),
            size=(dp(44), dp(44)),
            font_size=dp(22),
            bold=True,
            background_color=(0.14, 0.16, 0.23, 1),
            color=C_TEXT,
        )
        menu_btn.bind(on_press=lambda *_a: self._open_help_menu())
        header.add_widget(menu_btn)

        gif_src = _portal_gif_path()
        if gif_src:
            self._portal_mascot = Image(
                source=gif_src,
                size_hint=(None, None),
                size=(dp(58), dp(58)),
                allow_stretch=True,
                keep_ratio=True,
                anim_delay=_GIF_FRAME_DELAY,
            )
            self._portal_mascot.color = (0.4, 0.41, 0.44, 1)
            header.add_widget(self._portal_mascot)
        elif _asset_icon_path().is_file():
            self._portal_mascot = Image(
                source=str(_asset_icon_path()),
                size_hint=(None, None),
                size=(dp(58), dp(58)),
                allow_stretch=True,
                keep_ratio=True,
            )
            self._portal_mascot.color = (0.4, 0.41, 0.44, 1)
            header.add_widget(self._portal_mascot)
        else:
            self._portal_mascot = None

        ht = BoxLayout(
            orientation="vertical",
            spacing=dp(4),
            size_hint_x=1,
            size_hint_y=None,
        )
        ht.bind(minimum_height=ht.setter("height"))
        tw = max(Window.width - dp(130), dp(160))
        title_lbl = Label(
            text="Portal",
            font_size=dp(22),
            bold=True,
            color=C_TEXT,
            size_hint_y=None,
            height=dp(28),
            halign="left",
            valign="middle",
            text_size=(tw, None),
        )
        self._conn_status_lbl = Label(
            text="Проверка подключения…",
            font_size=dp(12),
            color=C_MUTED,
            size_hint_y=None,
            text_size=(tw, None),
            halign="left",
            valign="top",
        )

        def _status_h(inst, ts):
            inst.height = max(ts[1] + dp(4), dp(22))

        self._conn_status_lbl.bind(texture_size=_status_h)
        ht.add_widget(title_lbl)
        ht.add_widget(self._conn_status_lbl)
        header.add_widget(ht)

        def _sync_header_height(*_a):
            try:
                row_min = dp(58) if self._portal_mascot else dp(44)
                header.height = max(row_min + dp(6), ht.height + dp(8))
            except Exception:
                header.height = dp(76)

        ht.fbind("height", _sync_header_height)
        _sync_header_height()
        root.add_widget(header)

        def _defer_header_layout(_dt):
            _sync_header_height()

        Clock.schedule_once(_defer_header_layout, 0)

        scroll = ScrollView(
            do_scroll_x=False,
            bar_width=dp(6),
            size_hint_y=1,
            scroll_type=["bars", "content"],
        )
        body = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=dp(14),
            padding=(0, 0, 0, dp(8)),
        )
        body.bind(minimum_height=body.setter("height"))

        def _h_from_tex(inst, sz):
            inst.height = max(sz[1] + dp(4), dp(24))

        # Список IP — как «Пиры» + галочки «Кому отправлять» на ПК
        peers_panel = Panel()
        peers_panel.add_widget(
            Label(
                text="Адреса в вашей сети",
                font_size=dp(17),
                bold=True,
                color=C_TEXT,
                size_hint_y=None,
                height=dp(28),
                halign="left",
            )
        )
        peers_sub = Label(
            text=(
                "Галочка — разрешить отправку на этот адрес. Поле IP — узел с настольным Portal. "
                "Подпись видна только здесь."
            ),
            font_size=dp(12),
            color=C_MUTED,
            size_hint_y=None,
            text_size=(max(Window.width - dp(56), dp(200)), None),
            halign="left",
        )
        peers_sub.bind(texture_size=_h_from_tex)
        peers_panel.add_widget(peers_sub)
        self._peers_box = BoxLayout(
            orientation="vertical",
            spacing=dp(8),
            size_hint_y=None,
        )
        self._peers_box.bind(minimum_height=self._peers_box.setter("height"))
        peers_panel.add_widget(self._peers_box)

        add_btn = Button(
            text="+ Добавить адрес",
            size_hint_y=None,
            height=dp(48),
            background_color=C_ACCENT_2,
            color=C_TEXT,
            font_size=dp(15),
        )
        add_btn.bind(on_press=lambda *_a: self._add_peer_row())
        peers_panel.add_widget(add_btn)
        body.add_widget(peers_panel)

        # Пароль
        sec_panel = Panel()
        sec_panel.add_widget(
            Label(
                text="Пароль сети",
                font_size=dp(16),
                bold=True,
                color=C_TEXT,
                size_hint_y=None,
                height=dp(26),
                halign="left",
            )
        )
        sec_hint = Label(
            text="Тот же пароль, что в настольном Portal: ⚙ Настройки → «Пароль». "
            "Должен совпадать на телефоне и на компьютерах в вашей сети.",
            font_size=dp(12),
            color=C_MUTED,
            size_hint_y=None,
            text_size=(max(Window.width - dp(56), dp(200)), None),
            halign="left",
        )
        sec_hint.bind(texture_size=_h_from_tex)
        sec_panel.add_widget(sec_hint)
        self._secret_field = TextInput(
            hint_text="Пароль из настроек настольного Portal",
            multiline=False,
            size_hint_y=None,
            height=dp(48),
            password=True,
            background_color=(0.16, 0.18, 0.26, 1),
            foreground_color=C_TEXT,
            hint_text_color=C_MUTED,
            padding=[dp(10), dp(14), dp(8), dp(8)],
        )
        sec_panel.add_widget(self._secret_field)
        body.add_widget(sec_panel)

        # Тест
        test_panel = Panel()
        test_panel.add_widget(
            Label(
                text="Проверка отправки текста",
                font_size=dp(16),
                bold=True,
                color=C_TEXT,
                size_hint_y=None,
                height=dp(26),
                halign="left",
            )
        )
        test_hint = Label(
            text=(
                "Отправляет текст в буфер обмена на все отмеченные адреса "
                "(на компьютере должен быть запущен приём в настольном Portal)."
            ),
            font_size=dp(12),
            color=C_MUTED,
            size_hint_y=None,
            text_size=(max(Window.width - dp(56), dp(200)), None),
            halign="left",
        )
        test_hint.bind(texture_size=_h_from_tex)
        test_panel.add_widget(test_hint)
        self._test_text = TextInput(
            hint_text="Произвольный текст для проверки",
            multiline=True,
            size_hint_y=None,
            height=dp(88),
            background_color=(0.16, 0.18, 0.26, 1),
            foreground_color=C_TEXT,
            hint_text_color=C_MUTED,
            padding=[dp(10), dp(10), dp(8), dp(8)],
        )
        test_panel.add_widget(self._test_text)

        row = BoxLayout(
            size_hint_y=None,
            height=dp(56),
            spacing=dp(10),
        )

        def _btn_text_fit(btn, *_a):
            btn.text_size = (max(btn.width - dp(8), dp(40)), max(btn.height - dp(10), dp(28)))
            btn.halign = "center"
            btn.valign = "middle"

        save_btn = Button(
            text="Сохранить настройки",
            size_hint_x=0.5,
            background_color=C_ACCENT_2,
            color=C_TEXT,
            font_size=dp(13),
        )
        save_btn.bind(on_press=lambda *_a: self.save_settings())
        save_btn.bind(size=_btn_text_fit)
        test_btn = Button(
            text="Отправить тест",
            size_hint_x=0.5,
            background_color=C_ACCENT,
            color=C_TEXT,
            font_size=dp(13),
        )
        test_btn.bind(on_press=lambda *_a: self.send_test_text())
        test_btn.bind(size=_btn_text_fit)
        row.add_widget(save_btn)
        row.add_widget(test_btn)
        test_panel.add_widget(row)
        body.add_widget(test_panel)

        self._status_label = Label(
            text="Сохраните адреса и пароль. Далее: «Поделиться» в любом приложении → Portal.",
            font_size=dp(12),
            color=C_MUTED,
            size_hint_y=None,
            text_size=(max(Window.width - dp(32), dp(200)), None),
            halign="left",
        )
        self._status_label.bind(texture_size=_h_from_tex)
        body.add_widget(self._status_label)

        scroll.add_widget(body)
        root.add_widget(scroll)

        Clock.schedule_once(_defer_header_layout, 0.05)

        # Загрузить конфиг
        cfg = load_cfg()
        if self._secret_field:
            self._secret_field.text = cfg.get("secret", "") or ""
        for pr in normalize_peers(cfg.get("peers")):
            self._add_peer_row(
                ip=pr["ip"],
                name=pr.get("name") or pr["ip"],
                send=pr.get("send", True),
            )
        if not self._peer_rows:
            self._add_peer_row()

        return root

    def _open_help_menu(self) -> None:
        outer = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(10))
        scroll = ScrollView(do_scroll_x=False, bar_width=dp(5))
        tw = max(Window.width * 0.82 - dp(24), dp(200))
        lbl = Label(
            text=HELP_TEXT,
            font_size=dp(14),
            color=C_TEXT,
            size_hint_y=None,
            text_size=(tw, None),
            halign="left",
            valign="top",
        )
        lbl.bind(
            texture_size=lambda inst, ts: setattr(
                inst, "height", max(ts[1] + dp(8), dp(48))
            )
        )
        scroll.add_widget(lbl)
        outer.add_widget(scroll)
        close_row = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(8))
        close_btn = Button(
            text="Закрыть",
            size_hint_x=1,
            background_color=C_ACCENT_2,
            color=C_TEXT,
            font_size=dp(15),
        )
        close_row.add_widget(close_btn)
        outer.add_widget(close_row)
        pop = Popup(
            title="Справка и настройка",
            content=outer,
            size_hint=(0.9, 0.86),
        )
        close_btn.bind(on_press=pop.dismiss)
        pop.open()

    def _apply_ping_ui(
        self,
        any_ok: bool,
        ok_n: int,
        total: int,
        *,
        reason: str = "",
    ) -> None:
        if self._conn_status_lbl is None:
            return
        masc = self._portal_mascot
        if any_ok:
            if masc:
                masc.color = (1.0, 0.78, 0.42, 1)
                try:
                    masc.anim_delay = _GIF_FRAME_DELAY
                except Exception:
                    pass
            self._conn_status_lbl.color = C_ACCENT
            if ok_n == total:
                self._conn_status_lbl.text = (
                    f"Связь есть: отвечают все отмеченные узлы ({total})."
                )
            else:
                self._conn_status_lbl.text = (
                    f"Связь частично: отвечают {ok_n} из {total} отмеченных узлов."
                )
        else:
            if masc:
                masc.color = (0.38, 0.39, 0.42, 1)
                try:
                    masc.anim_delay = _GIF_FROZEN_DELAY
                except Exception:
                    pass
            self._conn_status_lbl.color = C_MUTED
            if reason == "nopeers":
                self._conn_status_lbl.text = (
                    "Укажите адрес и отметьте получателя, затем сохраните настройки."
                )
            elif reason == "noping":
                self._conn_status_lbl.text = "Проверка сети недоступна в этой сборке."
            else:
                self._conn_status_lbl.text = (
                    "Нет ответа от отмеченных узлов. Запущен ли приём в настольном Portal?"
                )

    def _ping_peers_bg(self) -> None:
        if ping_peer is None:
            Clock.schedule_once(
                lambda *_a: self._apply_ping_ui(False, 0, 0, reason="noping"),
                0,
            )
            return
        peers: list[str] = []
        secret = ""
        try:
            for row in self._peer_rows or []:
                ip = row.ip_input.text.strip()
                if not ip:
                    continue
                if not row.chk_send.active:
                    continue
                peers.append(ip)
            if self._secret_field:
                secret = self._secret_field.text.strip()
        except Exception:
            pass
        if not peers:
            Clock.schedule_once(
                lambda *_a: self._apply_ping_ui(False, 0, 0, reason="nopeers"),
                0,
            )
            return

        def work():
            ok = 0
            for ip in peers:
                try:
                    if ping_peer(ip, secret=secret, timeout=4.0):
                        ok += 1
                except Exception:
                    pass
            tot = len(peers)
            any_ok = ok > 0
            Clock.schedule_once(
                lambda _dt, o=ok, t=tot, a=any_ok: self._apply_ping_ui(a, o, t),
                0,
            )

        threading.Thread(target=work, daemon=True).start()

    def _start_connectivity_watch(self) -> None:
        self._ping_peers_bg()
        if self._ping_event is not None:
            try:
                self._ping_event.cancel()
            except Exception:
                pass
        self._ping_event = Clock.schedule_interval(
            lambda _dt: self._ping_peers_bg(),
            22.0,
        )

    def _add_peer_row(self, ip: str = "", name: str = "", send: bool = True):
        if not self._peers_box:
            return

        def on_remove(row: PeerRow):
            if row in self._peer_rows:
                self._peer_rows.remove(row)
            self._peers_box.remove_widget(row)

        row = PeerRow(ip=ip, name=name, send=send, on_remove=on_remove)
        self._peer_rows.append(row)
        self._peers_box.add_widget(row)

    def on_start(self):
        if self._share_boot:
            Clock.schedule_once(lambda _dt: self._begin_share_from_cold_start(), 0.05)
            return
        Clock.schedule_once(lambda _dt: self._start_connectivity_watch(), 0.35)

    def on_stop(self):
        if self._ping_event is not None:
            try:
                self._ping_event.cancel()
            except Exception:
                pass
            self._ping_event = None

    def _android_on_new_intent(self, intent):
        try:
            if not is_share_intent(intent=intent):
                return
            payload = read_share_intent(intent=intent)
            Clock.schedule_once(lambda _dt: self._run_share_flow(payload), 0.05)
        except Exception as ex:
            toast(f"Portal: intent {ex}", long=True)
            finish_activity()

    def _begin_share_from_cold_start(self):
        if self._cold_share_started:
            return
        self._cold_share_started = True
        try:
            payload = read_share_intent()
            self._run_share_flow(payload)
        except Exception as ex:
            toast(f"Portal: {ex}", long=True)
            finish_activity()

    def _run_share_flow(self, payload: SharePayload | None):
        if send_file_to_peer is None or send_text_clipboard is None:
            toast("Portal: нет portal_protocol", long=True)
            finish_activity()
            return
        if not payload:
            toast("Portal: пустой share", long=True)
            finish_activity()
            return
        has_files = bool(payload.file_paths)
        has_text = bool((payload.text or "").strip())
        if not has_files and not has_text:
            toast("Portal: нечего отправить", long=True)
            finish_activity()
            return

        cfg = load_cfg()
        peers = normalize_peers(cfg.get("peers"))
        secret = (cfg.get("secret") or "").strip()
        if not peers:
            toast(
                "Откройте Portal: добавьте адрес компьютера и сохраните настройки.",
                long=True,
            )
            finish_activity()
            return

        targets = peers_marked_for_send(peers)
        if not targets:
            toast(
                "Ни у одного адреса не отмечена отправка. Откройте приложение и отметьте получателей.",
                long=True,
            )
            finish_activity()
            return

        if len(targets) == 1:
            self._share_completed = True
            self._send_payload_thread(payload, targets, secret)
            return

        self._open_peer_picker(payload, targets, secret)

    def _open_peer_picker(self, payload: SharePayload, peers: list, secret: str):
        self._share_completed = False
        layout = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(10))
        layout.add_widget(
            Label(
                text="Выберите получателя (из отмеченных в настройках)",
                size_hint_y=None,
                height=dp(36),
                color=C_TEXT,
                text_size=(Window.width * 0.82, None),
                halign="center",
            )
        )
        btn_col = BoxLayout(
            orientation="vertical",
            spacing=dp(6),
            size_hint_y=None,
        )
        btn_col.bind(minimum_height=btn_col.setter("height"))

        pop = [None]

        def make_choose(peer):
            def on_press(_w):
                self._share_completed = True
                pop[0].dismiss()
                self._send_payload_thread(payload, [peer], secret)

            return on_press

        for peer in peers:
            label = peer.get("name") or peer["ip"]
            b = Button(
                text=label,
                size_hint_y=None,
                height=dp(48),
                background_color=C_ACCENT_2,
                color=C_TEXT,
            )
            b.bind(on_press=make_choose(peer))
            btn_col.add_widget(b)

        b_all = Button(
            text="На все отмеченные адреса",
            size_hint_y=None,
            height=dp(48),
            background_color=C_ACCENT,
            color=C_TEXT,
        )

        def on_all(_w):
            self._share_completed = True
            pop[0].dismiss()
            self._send_payload_thread(payload, list(peers), secret)

        b_all.bind(on_press=on_all)
        btn_col.add_widget(b_all)

        scroll = ScrollView(
            size_hint=(1, 1),
            do_scroll_x=False,
        )
        scroll.add_widget(btn_col)
        layout.add_widget(scroll)

        pop[0] = Popup(
            title="Portal",
            content=layout,
            size_hint=(0.88, 0.55),
            auto_dismiss=True,
        )

        def on_dismiss(_inst):
            if not self._share_completed:
                finish_activity()

        pop[0].bind(on_dismiss=on_dismiss)
        pop[0].open()

    def _send_payload_thread(self, payload: SharePayload, targets: list, secret: str):
        src = PORTAL_SOURCE_ANDROID

        def work():
            errs: list[str] = []
            for peer in targets:
                ip = peer["ip"]
                name = peer.get("name") or ip
                for fp in payload.file_paths:
                    ok, err = send_file_to_peer(
                        ip, fp, secret=secret, portal_source=src
                    )
                    if not ok:
                        errs.append(f"{name}: файл — {err}")
                if (payload.text or "").strip():
                    ok, err = send_text_clipboard(
                        ip, payload.text, secret=secret, portal_source=src
                    )
                    if not ok:
                        errs.append(f"{name}: текст — {err}")

            def done():
                if errs:
                    msg = "; ".join(errs[:4])
                    if len(errs) > 4:
                        msg += "…"
                    toast(f"Portal: {msg}", long=True)
                else:
                    toast("Portal: отправлено")
                finish_activity()

            try:
                from android.runnable import run_on_ui_thread  # type: ignore

                run_on_ui_thread(done)
            except Exception:
                done()

        threading.Thread(target=work, daemon=True).start()

    def _collect_peers(self) -> list:
        peers = []
        for row in self._peer_rows:
            ip = row.ip_input.text.strip()
            if not ip:
                continue
            nm = row.name_input.text.strip() or ip
            peers.append(
                {
                    "ip": ip,
                    "name": nm,
                    "send": bool(row.chk_send.active),
                }
            )
        return peers

    def save_settings(self) -> None:
        if not self._settings_root or not self._secret_field:
            return
        try:
            peers = self._collect_peers()
            if not peers:
                if self._status_label:
                    self._status_label.text = (
                        "Добавьте хотя бы один адрес узла с настольным Portal."
                    )
                return
            if not any(p.get("send") for p in peers):
                if self._status_label:
                    self._status_label.text = (
                        "Отметьте галочкой хотя бы одного получателя — иначе отправка некуда направлена."
                    )
                return
            cfg = {
                "peers": peers,
                "secret": self._secret_field.text.strip(),
            }
            save_cfg(cfg)
            if self._status_label:
                n = sum(1 for p in peers if p.get("send"))
                self._status_label.text = (
                    f"Сохранено: {len(peers)} адрес(ов), отправка на {n} отмеченных. "
                    "Далее: «Поделиться» → Portal."
                )
            Clock.schedule_once(lambda _dt: self._ping_peers_bg(), 0.5)
        except Exception as e:
            if self._status_label:
                self._status_label.text = f"Ошибка: {e}"

    def send_test_text(self) -> None:
        if not self._test_text:
            return
        if send_text_clipboard is None:
            return
        peers = self._collect_peers()
        if not peers:
            if self._status_label:
                self._status_label.text = (
                    "Сначала укажите адреса и нажмите «Сохранить настройки»."
                )
            return
        targets = peers_marked_for_send(peers)
        if not targets:
            if self._status_label:
                self._status_label.text = (
                    "Отметьте галочкой хотя бы одного получателя."
                )
            return
        cfg = load_cfg()
        secret = (cfg.get("secret") or "").strip()
        txt = self._test_text.text or ""
        errs: list[str] = []
        oks = 0
        for p in targets:
            ip = p["ip"]
            ok, err = send_text_clipboard(
                ip,
                txt,
                secret=secret,
                portal_source=PORTAL_SOURCE_ANDROID,
            )
            if ok:
                oks += 1
            else:
                lbl = p.get("name") or ip
                errs.append(f"{lbl}: {err}")
        if self._status_label:
            if oks == len(targets):
                self._status_label.text = (
                    f"Текст доставлен на {oks} узел(ов) — вставьте его на компьютере (Ctrl+V / Cmd+V)."
                )
            elif oks:
                self._status_label.text = (
                    f"Частично: успешно {oks}, ошибки: {'; '.join(errs[:2])}"
                )
            else:
                self._status_label.text = (
                    f"Не удалось: {'; '.join(errs[:2])}. Проверьте адрес, пароль и приём в настольном Portal."
                )
        Clock.schedule_once(lambda _dt: self._ping_peers_bg(), 0.3)


if __name__ == "__main__":
    PortalAndroidApp().run()
