#!/usr/bin/env python3
"""
После `flutter create`: compileSdk 35 и JVM 17 для app + всех Android-модулей (плагины).
Устраняет: lifecycle SDK 35; receive_sharing_intent Kotlin 17 vs Java 1.8.
"""
from __future__ import annotations

import re
from pathlib import Path

APP = Path("android/app/build.gradle")
ROOT = Path("android/build.gradle")

MARK_BEGIN = "// PORTAL_GRADLE_PATCH_BEGIN"
MARK_END = "// PORTAL_GRADLE_PATCH_END"

ROOT_SNIPPET = f"""
{MARK_BEGIN}
subprojects {{ subproject ->
    subproject.afterEvaluate {{
        if (subproject.plugins.hasPlugin("com.android.application") ||
                subproject.plugins.hasPlugin("com.android.library")) {{
            subproject.android {{
                compileSdkVersion 35
                compileOptions {{
                    sourceCompatibility JavaVersion.VERSION_17
                    targetCompatibility JavaVersion.VERSION_17
                }}
            }}
        }}
        subproject.tasks.withType(org.jetbrains.kotlin.gradle.tasks.KotlinCompile).configureEach {{
            kotlinOptions {{
                jvmTarget = "17"
            }}
        }}
        subproject.tasks.withType(JavaCompile).configureEach {{
            sourceCompatibility = JavaVersion.VERSION_17
            targetCompatibility = JavaVersion.VERSION_17
        }}
    }}
}}
{MARK_END}
"""


def _patch_app_gradle(text: str) -> str:
    # compileSdk
    text = re.sub(
        r"compileSdk\s*=\s*flutter\.compileSdkVersion",
        "compileSdk = 35",
        text,
    )
    text = re.sub(
        r"compileSdkVersion\s+flutter\.compileSdkVersion",
        "compileSdkVersion 35",
        text,
    )
    # Java / Kotlin в app
    text = text.replace("JavaVersion.VERSION_1_8", "JavaVersion.VERSION_17")
    text = re.sub(
        r"jvmTarget\s*=\s*JavaVersion\.VERSION_1_8\.toString\(\)",
        'jvmTarget = "17"',
        text,
    )
    text = re.sub(r"jvmTarget\s*=\s*['\"]1\.8['\"]", 'jvmTarget = "17"', text)
    return text


def _patch_root_gradle(text: str) -> str:
    if MARK_BEGIN in text:
        a = text.index(MARK_BEGIN)
        b = text.index(MARK_END) + len(MARK_END)
        text = text[:a] + ROOT_SNIPPET.strip() + text[b:]
        return text
    return text.rstrip() + "\n" + ROOT_SNIPPET


def main() -> None:
    if not APP.is_file():
        raise SystemExit(f"Нет {APP} — сначала flutter create --platforms=android")
    raw = APP.read_text(encoding="utf-8")
    new = _patch_app_gradle(raw)
    if new != raw:
        APP.write_text(new, encoding="utf-8")
        print(f"Обновлён {APP}")
    else:
        print(f"{APP}: без изменений (проверь шаблон Flutter)")

    if ROOT.is_file():
        r = ROOT.read_text(encoding="utf-8")
        nr = _patch_root_gradle(r)
        if nr != r:
            ROOT.write_text(nr, encoding="utf-8")
            print(f"Обновлён {ROOT}")
        else:
            print(f"{ROOT}: без изменений")


if __name__ == "__main__":
    main()
