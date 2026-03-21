"""
Portal для Android (Kivy): настройки пиров + Share Sheet (ACTION_SEND) без фонового сервиса.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from kivy.app import App
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView

try:
    from portal_protocol import send_file_to_peer, send_text_clipboard
except ImportError:
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
    out = []
    for p in raw or []:
        if not isinstance(p, dict):
            continue
        ip = str(p.get("ip", "")).strip()
        if not ip:
            continue
        name = str(p.get("name", "") or ip).strip()
        out.append({"ip": ip, "name": name})
    return out


KV_SETTINGS = """
<SettingsRoot>:
    orientation: "vertical"
    padding: dp(12)
    spacing: dp(8)
    Label:
        text: "Portal · настройки"
        size_hint_y: None
        height: dp(36)
    Label:
        text: "Пиры: JSON [{\\"ip\\":\\"100.x\\",\\"name\\":\\"ПК\\"}]"
        text_size: self.width, None
        halign: "left"
        size_hint_y: None
        height: self.texture_size[1]
    TextInput:
        id: peers_json
        multiline: True
        size_hint_y: 0.28
    TextInput:
        id: secret_field
        hint_text: "shared secret (как на ПК)"
        multiline: False
        size_hint_y: None
        height: dp(40)
    TextInput:
        id: text_send
        hint_text: "Тест: текст на первый IP"
        multiline: True
        size_hint_y: 0.18
    BoxLayout:
        size_hint_y: None
        height: dp(44)
        spacing: dp(8)
        Button:
            text: "Сохранить"
            on_press: app.save_settings()
        Button:
            text: "Тест текста"
            on_press: app.send_test_text()
    Label:
        id: status
        text: "Один раз сохрани IP и пароль. Share: Поделиться → Portal."
        text_size: self.width, None
        halign: "left"
        size_hint_y: None
        height: dp(100)
"""


class SettingsRoot(BoxLayout):
    pass


class PortalAndroidApp(App):
    title = "Portal"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._share_boot = False
        self._share_completed = False
        self._settings_root = None
        self._cold_share_started = False

    def build(self):
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
        Builder.load_string(KV_SETTINGS)
        root = SettingsRoot()
        self._settings_root = root
        cfg = load_cfg()
        root.ids.peers_json.text = json.dumps(
            cfg.get("peers", []), ensure_ascii=False, indent=2
        )
        root.ids.secret_field.text = cfg.get("secret", "")
        return root

    def on_start(self):
        if self._share_boot:
            Clock.schedule_once(lambda _dt: self._begin_share_from_cold_start(), 0.05)

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
            toast("Сначала открой Portal и сохрани IP компов (JSON).", long=True)
            finish_activity()
            return

        if len(peers) == 1:
            self._share_completed = True
            self._send_payload_thread(payload, peers, secret)
            return

        self._open_peer_picker(payload, peers, secret)

    def _open_peer_picker(self, payload: SharePayload, peers: list, secret: str):
        self._share_completed = False
        layout = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(10))
        layout.add_widget(
            Label(
                text="Куда отправить?",
                size_hint_y=None,
                height=dp(36),
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
            b = Button(text=label, size_hint_y=None, height=dp(48))
            b.bind(on_press=make_choose(peer))
            btn_col.add_widget(b)

        b_all = Button(text="Все компы", size_hint_y=None, height=dp(48))

        def on_all(_w):
            self._share_completed = True
            pop[0].dismiss()
            self._send_payload_thread(payload, peers, secret)

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

    def save_settings(self) -> None:
        root = self._settings_root
        if not root:
            return
        try:
            peers = json.loads(root.ids.peers_json.text or "[]")
            if not isinstance(peers, list):
                raise ValueError("peers должен быть списком")
            cfg = {
                "peers": peers,
                "secret": root.ids.secret_field.text.strip(),
            }
            save_cfg(cfg)
            root.ids.status.text = "Сохранено. Можно закрыть приложение — Share работает без фона."
        except Exception as e:
            root.ids.status.text = f"Ошибка: {e}"

    def send_test_text(self) -> None:
        root = self._settings_root
        if not root or send_text_clipboard is None:
            return
        cfg = load_cfg()
        peers = normalize_peers(cfg.get("peers"))
        if not peers:
            root.ids.status.text = "Нет пиров"
            return
        ip = peers[0]["ip"]
        txt = root.ids.text_send.text or ""
        ok, err = send_text_clipboard(
            ip,
            txt,
            secret=(cfg.get("secret") or ""),
            portal_source=PORTAL_SOURCE_ANDROID,
        )
        root.ids.status.text = "Отправлено." if ok else f"Ошибка: {err}"


if __name__ == "__main__":
    PortalAndroidApp().run()
