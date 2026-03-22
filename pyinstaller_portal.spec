# PyInstaller — из корня репозитория portal/
#
#   pip install -r requirements.txt pyinstaller
#   python3 scripts/generate_branding_icons.py
#   pyinstaller -y pyinstaller_portal.spec
#
# Windows → dist/Portal/Portal.exe
# macOS   → dist/Portal.app
#
# См. BUILD_DESKTOP.md (карантин Mac, иконки, отладка).

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

block_cipher = None
root = Path(SPECPATH).resolve()
assets = root / "assets"
brand = root / "assets" / "branding"

datas = []
if assets.is_dir():
    datas.append((str(assets), "assets"))
# Отдельный процесс глобальных хоткеев на macOS (Python 3.13+)
datas.append((str(root / "portal_mac_hotkey_helper.py"), "."))

# CustomTkinter — темы и ресурсы
try:
    datas += collect_data_files("customtkinter")
except Exception:
    pass

# certifi — CA для GitHub / APK
try:
    datas += collect_data_files("certifi")
except Exception:
    pass

binaries = []
if sys.platform == "win32":
    try:
        binaries += collect_dynamic_libs("pywin32")
    except Exception:
        pass

hiddenimports = [
    "customtkinter",
    "PIL",
    "PIL.Image",
    "PIL.ImageTk",
    "PIL.ImageSequence",
    "pyperclip",
    "portal_config",
    "portal_json_framing",
    "portal_i18n",
    "portal_clipboard_rich",
    "portal_widget",
    "portal_tk_compat",
    "portal_github",
    "portal_update_check",
    "certifi",
    "urllib",
    "ssl",
    "pynput",
    "pynput.keyboard",
    "tkinterdnd2",
    "portal_mac_hotkey_helper",
    "portal_mac_permissions",
]

if sys.platform == "win32":
    hiddenimports.extend(["windnd", "win32clipboard", "win32con", "win32gui"])

if sys.platform == "darwin":
    hiddenimports.extend(
        [
            "AppKit",
            "ApplicationServices",
            "Foundation",
            "objc",
            "PyObjCTools",
            "Quartz",
        ]
    )

ico_path = brand / "portal.ico"
icns_path = brand / "portal.icns"
win_icon = str(ico_path) if ico_path.is_file() and sys.platform == "win32" else None
mac_icon = str(icns_path) if icns_path.is_file() and sys.platform == "darwin" else None

a = Analysis(
    [str(root / "portal.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "numpy", "pandas"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Без консоли — как обычное GUI-приложение
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Portal",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=sys.platform == "darwin",
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=win_icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Portal",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Portal.app",
        icon=mac_icon,
        bundle_identifier="org.portal.desktop",
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleName": "Portal",
            "CFBundleDisplayName": "Portal",
            "CFBundleShortVersionString": "1.0.0",
            "NSHumanReadableCopyright": "MIT",
        },
    )
