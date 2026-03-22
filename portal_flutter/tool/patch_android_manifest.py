#!/usr/bin/env python3
"""Патч AndroidManifest после `flutter create`: cleartext, FGS, уведомления, Wi-Fi."""
from __future__ import annotations

import re
from pathlib import Path

MANIFEST = Path("android/app/src/main/AndroidManifest.xml")

# Имя сервиса flutter_background_service (может меняться в плагине, поэтому ищем по подстроке).
_FGS_SERVICE_SUBSTR = "flutter_background_service"


def main() -> None:
    if not MANIFEST.is_file():
        raise SystemExit(f"Нет файла {MANIFEST} — сначала flutter create")

    text = MANIFEST.read_text(encoding="utf-8")
    orig = text

    # 1. usesCleartextTraffic — TCP к LAN без TLS.
    if 'usesCleartextTraffic' not in text and "<application" in text:
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


if __name__ == "__main__":
    main()
