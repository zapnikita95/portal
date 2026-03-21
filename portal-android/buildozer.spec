[app]
title = Portal
package.name = portalshare
package.domain = org.portal
source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,json,gif,xml
version = 0.4.3
requirements = python3,kivy==2.3.0,android
orientation = portrait
fullscreen = 0

# Клавиатура сдвигает контент, а не «старое» всплывающее меню Kivy поверх поля
android.window_softinput_mode = adjustResize

source.include_patterns = assets/*

# Иконка лаунчера (положи icon.png через scripts/generate_branding_icons.py)
icon.filename = %(source.dir)s/assets/icon.png

# Share Sheet → PythonActivity
android.manifest.intent_filters = intent_filters.xml
android.permissions = android.permission.INTERNET

android.api = 33
android.minapi = 24
android.ndk = 25b
android.accept_sdk_license = True
android.archs = arm64-v8a,armeabi-v7a

[buildozer]
log_level = 2
warn_on_root = 1
