---
name: portal-desktop-release
description: Сборка Portal (.app / .exe) через PyInstaller и GitHub Actions; релизы с тегом v*. Используй, когда нужно собрать десктоп, обновить CI или выложить бинарники на GitHub Releases.
---

# Portal: десктоп-сборки и релизы

## Локально (Mac / Windows)

Из корня репозитория `portal/`:

```bash
pip install -r requirements.txt pyinstaller pillow
python3 scripts/generate_branding_icons.py
pyinstaller pyinstaller_portal.spec
```

- **macOS:** `dist/Portal.app` (перед запуском при необходимости: `xattr -dr com.apple.quarantine dist/Portal.app`)
- **Windows:** `dist/Portal/Portal.exe` + вся папка `Portal`

Подробности: **BUILD_DESKTOP.md**.

## GitHub Actions (без своей машины)

Шаблон в корне репо: **`github-workflow-portal-desktop.yml`** → скопируй в **`.github/workflows/portal-desktop-release.yml`** (см. **BUILD_DESKTOP.md**). Push workflow-файла с GitHub PAT требует scope **`workflow`**.

1. **Артефакты без релиза:** **Actions** → **Portal Desktop Build** → **Run workflow** → скачай **Portal-macOS** / **Portal-Windows**.
2. **Релиз с вложениями:** запушь тег `v1.0.0`:
   ```bash
   git tag v1.0.0
   git push origin v1.0.0
   ```
   Workflow соберёт обе платформы и прикрепит **Portal-macOS.zip** и **Portal-Windows.zip** к GitHub Release.

## Что не забыть

- Иконки: `scripts/generate_branding_icons.py` (исходник `assets/branding/portal_icon.png`).
- Агент в Cursor **не заменяет** CI: при запросе «собери exe/app» по возможности опирайся на этот workflow или локальную команду выше, затем пуш тега для релиза.
