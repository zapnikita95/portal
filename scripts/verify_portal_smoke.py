#!/usr/bin/env python3
"""
Быстрая проверка после merge: импорт, парс JSON, PortalApp() без mainloop.
Запуск: python scripts/verify_portal_smoke.py
Из корня репо: python -m scripts.verify_portal_smoke
"""
from __future__ import annotations

import json
import os
import sys

# корень репозитория в sys.path
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def main() -> int:
    errors: list[str] = []

    # 1) Импорт модулей
    try:
        import portal_config  # noqa: F401

        need = [
            "load_auto_clipboard_enabled",
            "load_remote_ips",
            "load_receive_dir",
            "receive_dir_path",
            "load_peer_ips",
            "load_shared_secret",
            "save_shared_secret",
            "generate_shared_secret",
            "load_widget_media_path",
            "load_widget_media_mode",
            "WIDGET_MEDIA_MODE_LABELS_RU",
        ]
        for name in need:
            if not hasattr(portal_config, name):
                errors.append(f"portal_config: нет атрибута {name!r}")
    except Exception as e:
        errors.append(f"portal_config: {e}")

    try:
        import portal  # noqa: F401

        for name in ("merge_outgoing_shared_secret", "incoming_peer_secret_ok"):
            if not hasattr(portal, name):
                errors.append(f"portal: нет функции {name!r}")
    except Exception as e:
        errors.append(f"portal: {e}")
        _print_errors(errors)
        return 1

    # 2) parse_first_json_object_bytes (не должен ссылаться на несуществующие имена)
    try:
        from portal import parse_first_json_object_bytes

        buf = (
            json.dumps(
                {"type": "file", "filename": "x}.txt", "filesize": 2},
                ensure_ascii=False,
            ).encode()
            + b"ab"
        )
        tail = b"ab"
        obj, n = parse_first_json_object_bytes(buf)
        if not obj or obj.get("filename") != "x}.txt" or buf[n:] != tail:
            errors.append("parse_first_json_object_bytes: неверный результат")
    except Exception as e:
        errors.append(f"parse_first_json_object_bytes: {e}")

    # 3) PortalApp: методы UI, очередь
    try:
        from portal import PortalApp

        required_methods = (
            "choose_receive_dir",
            "handle_client",
            "_receive_clipboard_file_payload",
        )
        for m in required_methods:
            if not hasattr(PortalApp, m):
                errors.append(f"PortalApp: нет метода {m!r}")

        app = PortalApp()
        if not hasattr(app, "_ui_signal_queue") or app._ui_signal_queue is None:
            errors.append("PortalApp: нет _ui_signal_queue")
        app.destroy()
    except Exception as e:
        errors.append(f"PortalApp(): {e}")

    if errors:
        _print_errors(errors)
        return 1

    print("OK: verify_portal_smoke (config + parse + PortalApp init)")
    return 0


def _print_errors(errors: list[str]) -> None:
    print("FAIL verify_portal_smoke:", file=sys.stderr)
    for line in errors:
        print(f"  - {line}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
