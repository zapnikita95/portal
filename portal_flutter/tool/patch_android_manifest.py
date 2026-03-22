#!/usr/bin/env python3
"""Патч AndroidManifest после `flutter create`: cleartext, FGS, уведомления, Wi-Fi."""
from __future__ import annotations

import re
from pathlib import Path

MANIFEST = Path("android/app/src/main/AndroidManifest.xml")

# Полное имя класса из пакета id.flutter.flutter_background_service (library manifest: .BackgroundService).
_FGS_SERVICE_CLASS = "id.flutter.flutter_background_service.BackgroundService"

# Имя сервиса flutter_background_service (может меняться в плагине, поэтому ищем по подстроке).
_FGS_SERVICE_SUBSTR = "flutter_background_service"


def main() -> None:
    if not MANIFEST.is_file():
        raise SystemExit(f"Нет файла {MANIFEST} — сначала flutter create")

    text = MANIFEST.read_text(encoding="utf-8")
    orig = text

    # 0. xmlns:tools для merge/replace атрибутов сервиса из зависимости.
    if "xmlns:tools=" not in text and "<manifest" in text:
        text = text.replace(
            "<manifest xmlns:android=\"http://schemas.android.com/apk/res/android\"",
            "<manifest xmlns:android=\"http://schemas.android.com/apk/res/android\"\n"
            '    xmlns:tools="http://schemas.android.com/tools"',
            1,
        )

    # 1. Имя в лаунчере + cleartext для TCP в LAN.
    text = re.sub(
        r'android:label="portal_flutter"',
        'android:label="Portal"',
        text,
    )
    if "usesCleartextTraffic" not in text and "<application" in text:
        text = text.replace("<application", '<application android:usesCleartextTraffic="true"', 1)

    # 2. Разрешения.
    perms = [
        "android.permission.POST_NOTIFICATIONS",
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_DATA_SYNC",
        "android.permission.WAKE_LOCK",
        "android.permission.ACCESS_NETWORK_STATE",
        "android.permission.ACCESS_WIFI_STATE",
        "android.permission.INTERNET",
    ]
    insert = ""
    for full in perms:
        if full not in text:
            insert += f'    <uses-permission android:name="{full}"/>\n'

    if insert and "<manifest" in text:
        idx = text.find(">")
        if idx != -1:
            text = text[: idx + 1] + "\n" + insert + text[idx + 1 :]

    # 3. Добавить foregroundServiceType="dataSync" к сервису flutter_background_service.
    # Android 14+ (API 34) требует явного типа — без него FGS crash.
    def _patch_fgs_service_type(src: str) -> str:
        if "foregroundServiceType" in src:
            return src  # уже есть
        # Найти <service ... > с подстрокой плагина.
        pattern = r'(<service\b[^>]*?' + re.escape(_FGS_SERVICE_SUBSTR) + r'[^>]*?)(/)?(>)'
        def replacer(m: re.Match) -> str:
            tag_body = m.group(1)
            selfclose = m.group(2) or ""
            close = m.group(3)
            if "foregroundServiceType" not in tag_body:
                tag_body += '\n            android:foregroundServiceType="dataSync"'
            return tag_body + selfclose + close
        return re.sub(pattern, replacer, src, flags=re.DOTALL)

    text = _patch_fgs_service_type(text)

    # 3b. Library не задаёт foregroundServiceType → Android 14+ краш при startForeground(dataSync).
    text = _inject_background_service_fgs_merge(text)

    # 4. Share sheet (receive_sharing_intent): без intent-filter Portal не в списке «Поделиться».
    text = _inject_portal_share_intent_filters(text)

    if text != orig:
        MANIFEST.write_text(text, encoding="utf-8")
        print("AndroidManifest.xml обновлён.")
    else:
        print("AndroidManifest.xml без изменений (уже ок).")


def _inject_portal_share_intent_filters(src: str) -> str:
    marker = "<!-- PortalShareIntentFilters -->"
    if marker in src or "android.intent.action.SEND_MULTIPLE" in src:
        return src
    m = re.search(
        r'<activity\b[^>]*android:name\s*=\s*"[^"]*MainActivity"[^>]*>',
        src,
        re.IGNORECASE | re.DOTALL,
    )
    if not m:
        print("WARN: MainActivity не найден в манифесте — share intent не добавлен.")
        return src
    start = m.end()
    end = src.find("</activity>", start)
    if end < 0:
        return src
    inner = src[start:end]
    if "android.intent.action.SEND" in inner:
        return src
    snippet = f"""
            {marker}
            <intent-filter>
                <action android:name="android.intent.action.SEND" />
                <category android:name="android.intent.category.DEFAULT" />
                <data android:mimeType="*/*" />
            </intent-filter>
            <intent-filter>
                <action android:name="android.intent.action.SEND_MULTIPLE" />
                <category android:name="android.intent.category.DEFAULT" />
                <data android:mimeType="*/*" />
            </intent-filter>
"""
    return src[:end] + snippet + src[end:]


def _inject_background_service_fgs_merge(src: str) -> str:
    if _FGS_SERVICE_CLASS in src and "foregroundServiceType" in src:
        return src
    marker = "<!-- PortalBackgroundServiceFgs -->"
    if marker in src:
        return src
    snippet = f"""
        {marker}
        <service
            android:name="{_FGS_SERVICE_CLASS}"
            android:exported="true"
            android:foregroundServiceType="dataSync"
            tools:node="merge" />
"""
    # Вставить сразу после открывающего <application ...>.
    m = re.search(r"<application\b[^>]*>", src)
    if not m:
        print("WARN: <application> не найден — FGS merge для BackgroundService не добавлен.")
        return src
    return src[: m.end()] + "\n" + snippet + src[m.end() :]


if __name__ == "__main__":
    main()
