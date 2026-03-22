#!/usr/bin/env python3
"""
После `flutter create`: compileSdk 36 и JVM 17 для app + Android-модулей (плагины).
Поддерживает шаблон Flutter 3.41+: android/app/build.gradle.kts и android/build.gradle.kts.
"""
from __future__ import annotations

import re
from pathlib import Path

MARK_BEGIN = "// PORTAL_GRADLE_PATCH_BEGIN"
MARK_END = "// PORTAL_GRADLE_PATCH_END"

# Groovy (старые проекты)
ROOT_SNIPPET_GROOVY = f"""
{MARK_BEGIN}
subprojects {{ subproject ->
    subproject.afterEvaluate {{
        if (subproject.name == "app") return
        def ext = subproject.extensions.findByType(com.android.build.gradle.BaseExtension)
        if (ext != null) {{
            ext.compileSdk = 36
            ext.compileOptions {{
                sourceCompatibility JavaVersion.VERSION_17
                targetCompatibility JavaVersion.VERSION_17
            }}
        }}
    }}
}}
gradle.projectsEvaluated {{
    rootProject.subprojects.each {{ p ->
        p.tasks.withType(JavaCompile).configureEach {{ jc ->
            jc.sourceCompatibility = JavaVersion.VERSION_17
            jc.targetCompatibility = JavaVersion.VERSION_17
            jc.options.release = 17
        }}
        p.tasks.withType(org.jetbrains.kotlin.gradle.tasks.KotlinCompile).configureEach {{
            compilerOptions {{
                jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
            }}
        }}
    }}
}}
{MARK_END}
"""

# Kotlin DSL (Flutter 3.35+); Kotlin 2.2+ forbids kotlinOptions on KotlinCompile — use compilerOptions.
# compileSdk для модулей плагинов: afterEvaluate (withId на корне часто не цепляет Flutter-плагины → пустой android.jar).
ROOT_SNIPPET_KTS = f"""
{MARK_BEGIN}
subprojects {{
    afterEvaluate {{
        if (project.name == "app") return@afterEvaluate
        extensions.findByType(com.android.build.gradle.BaseExtension::class.java)?.apply {{
            compileSdk = 36
            compileOptions {{
                sourceCompatibility = JavaVersion.VERSION_17
                targetCompatibility = JavaVersion.VERSION_17
            }}
        }}
    }}
}}
gradle.projectsEvaluated {{
    rootProject.subprojects.forEach {{ sub ->
        sub.tasks.withType(org.gradle.api.tasks.compile.JavaCompile::class.java).configureEach {{
            sourceCompatibility = JavaVersion.VERSION_17.toString()
            targetCompatibility = JavaVersion.VERSION_17.toString()
            options.release.set(17)
        }}
        sub.tasks.withType(KotlinCompile::class.java).configureEach {{
            compilerOptions {{
                jvmTarget.set(JvmTarget.JVM_17)
            }}
        }}
    }}
}}
{MARK_END}
"""

KTS_KOTLIN_COMPILE_IMPORTS = """import org.jetbrains.kotlin.gradle.dsl.JvmTarget
import org.jetbrains.kotlin.gradle.tasks.KotlinCompile

"""


def _ensure_kts_kotlin_imports(text: str) -> str:
    if "import org.jetbrains.kotlin.gradle.tasks.KotlinCompile" in text:
        return text
    return KTS_KOTLIN_COMPILE_IMPORTS + text.lstrip("\n")


def _pick_app_gradle() -> Path:
    for p in (Path("android/app/build.gradle.kts"), Path("android/app/build.gradle")):
        if p.is_file():
            return p
    raise SystemExit(
        "Нет android/app/build.gradle.kts ни build.gradle — сначала "
        "flutter create . --project-name portal_flutter --org org.portal --platforms=android"
    )


def _pick_root_gradle() -> Path | None:
    for p in (Path("android/build.gradle.kts"), Path("android/build.gradle")):
        if p.is_file():
            return p
    return None


def _patch_app_gradle(text: str) -> str:
    text = re.sub(
        r"compileSdk\s*=\s*flutter\.compileSdkVersion",
        "compileSdk = 36",
        text,
    )
    text = re.sub(
        r"compileSdkVersion\s+flutter\.compileSdkVersion",
        "compileSdkVersion 36",
        text,
    )
    text = text.replace("compileSdk = 35", "compileSdk = 36")
    text = text.replace("compileSdkVersion 35", "compileSdkVersion 36")
    text = text.replace("JavaVersion.VERSION_1_8", "JavaVersion.VERSION_17")
    text = text.replace("JavaVersion.VERSION_11", "JavaVersion.VERSION_17")
    text = text.replace("JavaVersion.VERSION_1_11", "JavaVersion.VERSION_17")
    text = re.sub(
        r"jvmTarget\s*=\s*JavaVersion\.VERSION_1_8\.toString\(\)",
        'jvmTarget = "17"',
        text,
    )
    text = re.sub(r"jvmTarget\s*=\s*['\"]1\.8['\"]", 'jvmTarget = "17"', text)
    return text


def _patch_root_groovy(text: str) -> str:
    if MARK_BEGIN in text:
        a = text.index(MARK_BEGIN)
        b = text.index(MARK_END) + len(MARK_END)
        return text[:a] + ROOT_SNIPPET_GROOVY.strip() + text[b:]
    return text.rstrip() + "\n" + ROOT_SNIPPET_GROOVY


def _patch_root_kts(text: str) -> str:
    if MARK_BEGIN in text:
        a = text.index(MARK_BEGIN)
        b = text.index(MARK_END) + len(MARK_END)
        out = text[:a] + ROOT_SNIPPET_KTS.strip() + text[b:]
    else:
        out = text.rstrip() + "\n" + ROOT_SNIPPET_KTS
    return _ensure_kts_kotlin_imports(out)


def main() -> None:
    app = _pick_app_gradle()
    raw = app.read_text(encoding="utf-8")
    new = _patch_app_gradle(raw)
    if new != raw:
        app.write_text(new, encoding="utf-8")
        print(f"Обновлён {app}")
    else:
        print(f"{app}: без изменений (проверь шаблон Flutter)")

    root = _pick_root_gradle()
    if root is None:
        print("Нет android/build.gradle(.kts) — пропуск root patch")
        return
    r = root.read_text(encoding="utf-8")
    if root.suffix == ".kts":
        nr = _patch_root_kts(r)
    else:
        nr = _patch_root_groovy(r)
    if nr != r:
        root.write_text(nr, encoding="utf-8")
        print(f"Обновлён {root}")
    else:
        print(f"{root}: без изменений")


if __name__ == "__main__":
    main()
