[app]
title = Portal
package.name = portalshare
package.domain = org.portal
source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,json,gif,xml
version = 0.5.2
requirements = python3,kivy==2.3.0,android
orientation = portrait
fullscreen = 0

# Foreground service: приём TCP :12345 в отдельном процессе (см. portal_receive_service.py).
services = receive:portal_receive_service.py:foreground

# Меньше «прыжков» шапки при вводе: пан/сдвиг окна вместо полного resize
android.window_softinput_mode = adjustPan

source.include_patterns = assets/*

# Иконка лаунчера (положи icon.png через scripts/generate_branding_icons.py)
icon.filename = %(source.dir)s/assets/icon.png

# Share Sheet → PythonActivity
android.manifest.intent_filters = intent_filters.xml
android.permissions = android.permission.INTERNET,android.permission.WRITE_EXTERNAL_STORAGE,android.permission.READ_EXTERNAL_STORAGE,android.permission.FOREGROUND_SERVICE,android.permission.FOREGROUND_SERVICE_DATA_SYNC,android.permission.POST_NOTIFICATIONS,android.permission.WAKE_LOCK

android.api = 33
android.minapi = 24
android.ndk = 25b
android.accept_sdk_license = True
android.archs = arm64-v8a,armeabi-v7a

[buildozer]
log_level = 2
warn_on_root = 1
