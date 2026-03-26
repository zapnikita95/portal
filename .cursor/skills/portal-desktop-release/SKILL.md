---
name: portal-desktop-release
description: Сборка Portal (.app / .exe) через PyInstaller и GitHub Actions; релизы с тегом v*. Используй, когда нужно собрать десктоп, обновить CI или выложить бинарники на GitHub Releases.
---

# Portal: десктоп-сборки и релизы

## Один скрипт: версия → commit → тег → GitHub CI

Из корня репозитория:

- **Windows (PowerShell):**  
  `.\scripts\release_desktop.ps1 -Version 1.2.0 -BumpConfig`  
  Опции: `-LocalBuild` (проверочная сборка перед push), `-SkipPush`, `-DryRun`.

- **macOS / Linux:**  
  `bash scripts/release_desktop.sh --version 1.2.0 --bump`

После `git push` тега `v*` workflow **Portal Desktop Build** прикрепляет **PortalSetup.exe** (Inno), **Portal-Windows.zip** и macOS-артефакты. На Windows проверка обновлений открывает загрузку **PortalSetup.exe** (см. `installer/PortalSetup.iss`, `portal_github.pick_desktop_download_url`).

---

## Локально (Mac / Windows)

Из корня репозитория `portal/`:

```bash
pip install -r requirements.txt pyinstaller pillow
python3 scripts/generate_branding_icons.py
pyinstaller -y pyinstaller_portal.spec
```

- **macOS:** `dist/Portal.app` (перед запуском при необходимости: `xattr -dr com.apple.quarantine dist/Portal.app`)
- **Windows:** `dist/Portal/Portal.exe` + вся папка `Portal`

Подробности: **BUILD_DESKTOP.md**.

## GitHub Actions (без своей машины)

Шаблон: **`github-workflow-portal-desktop.yml`**. Добавить в репо безопаснее **через веб GitHub** (Create new file → `.github/workflows/portal-desktop-release.yml` → вставить содержимое шаблона) — см. **BUILD_DESKTOP.md** («ошибка workflow scope»). Push этого файла по **HTTPS + PAT** требует scope **`workflow`**; иначе используй веб, **SSH** или новый PAT.

1. **Артефакты без релиза:** **Actions** → **Portal Desktop Build** → **Run workflow** → скачай **Portal-macOS** / **Portal-Windows**.
2. **Релиз с вложениями:** запушь тег `v1.0.0`:
   ```bash
   git tag v1.0.0
   git push origin v1.0.0
   ```
   Workflow соберёт обе платформы и прикрепит **Portal-macOS.zip** и **Portal-Windows.zip** к GitHub Release.

## Что не забыть

- Иконки: `scripts/generate_branding_icons.py` (исходник **`assets/portal_main.gif`** → `portal_icon.png`, `.ico`, `.icns`, Android `icon.png`).
- Агент в Cursor **не заменяет** CI: при запросе «собери exe/app» по возможности опирайся на этот workflow или локальную команду выше, затем пуш тега для релиза.
