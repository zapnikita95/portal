import com.android.build.gradle.LibraryExtension
import org.jetbrains.kotlin.gradle.dsl.JvmTarget
import org.jetbrains.kotlin.gradle.tasks.KotlinCompile

allprojects {
    repositories {
        google()
        mavenCentral()
    }
}

val newBuildDir: Directory =
    rootProject.layout.buildDirectory
        .dir("../../build")
        .get()
rootProject.layout.buildDirectory.value(newBuildDir)

subprojects {
    val newSubprojectBuildDir: Directory = newBuildDir.dir(project.name)
    project.layout.buildDirectory.value(newSubprojectBuildDir)
}
// Не вешать evaluationDependsOn(":app") на все subprojects: ломает порядок конфигурации
// Android-модулей плагинов (пустой android.jar → «package android.content does not exist»).

tasks.register<Delete>("clean") {
    delete(rootProject.layout.buildDirectory)
}

// PORTAL_GRADLE_PATCH_BEGIN
// compileSdk для модулей плагинов: afterEvaluate (не projectsEvaluated — «too late»; withId на корне часто не цепляет Flutter-плагины).
subprojects {
    afterEvaluate {
        if (project.name == "app") return@afterEvaluate
        // BaseExtension в KTS не даёт compileSdk — только LibraryExtension / ApplicationExtension.
        extensions.findByType(LibraryExtension::class.java)?.apply {
            compileSdk = 36
            // Java 21: sqflite_android и др. используют Locale.of / Thread.threadId (не входят в --release 17).
            compileOptions {
                sourceCompatibility = JavaVersion.VERSION_21
                targetCompatibility = JavaVersion.VERSION_21
            }
        }
    }
}
gradle.projectsEvaluated {
    rootProject.subprojects.forEach { sub ->
        sub.tasks.withType(org.gradle.api.tasks.compile.JavaCompile::class.java).configureEach {
            sourceCompatibility = JavaVersion.VERSION_21.toString()
            targetCompatibility = JavaVersion.VERSION_21.toString()
            options.release.set(21)
        }
        sub.tasks.withType(KotlinCompile::class.java).configureEach {
            compilerOptions {
                jvmTarget.set(JvmTarget.JVM_21)
            }
        }
    }
}
// PORTAL_GRADLE_PATCH_END
