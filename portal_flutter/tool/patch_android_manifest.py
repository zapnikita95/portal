#!/usr/bin/env python3
"""Патч AndroidManifest после `flutter create`: cleartext, FGS, уведомления."""
from __future__ import annotations

from pathlib import Path

MANIFEST = Path("android/app/src/main/AndroidManifest.xml")


def main() -> None:
    if not MANIFEST.is_file():
        raise SystemExit(f"Нет файла {MANIFEST} — сначала flutter create")

    text = MANIFEST.read_text(encoding="utf-8")
    orig = text

    if 'usesCleartextTraffic' not in text and "<application" in text:
        text = text.replace("<application", '<application android:usesCleartextTraffic="true"', 1)

    perms = [
        "android.permission.POST_NOTIFICATIONS",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_DATA_SYNC",
        "android.permission.WAKE_LOCK",
        "android.permission.ACCESS_NETWORK_STATE",
        "android.permission.ACCESS_WIFI_STATE",
    ]
    insert = ""
    for full in perms:
        if full not in text:
            insert += f'    <uses-permission android:name="{full}"/>\n'

    if insert and "<manifest" in text:
        # сразу после открывающего <manifest ...>
        idx = text.find(">")
        if idx != -1:
            text = text[: idx + 1] + "\n" + insert + text[idx + 1 :]

    if text != orig:
        MANIFEST.write_text(text, encoding="utf-8")
        print("AndroidManifest.xml обновлён.")
    else:
        print("AndroidManifest.xml без изменений (уже ок).")


if __name__ == "__main__":
    main()
