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
subprojects {
    project.evaluationDependsOn(":app")
}

tasks.register<Delete>("clean") {
    delete(rootProject.layout.buildDirectory)
}

// PORTAL_GRADLE_PATCH_BEGIN
gradle.projectsEvaluated {
    rootProject.subprojects.forEach { sub ->
        sub.plugins.withId("com.android.library") {
            sub.extensions.findByType(com.android.build.gradle.LibraryExtension::class.java)?.apply {
                compileSdk = 35
                compileOptions {
                    sourceCompatibility = JavaVersion.VERSION_17
                    targetCompatibility = JavaVersion.VERSION_17
                }
            }
        }
        sub.tasks.withType(org.gradle.api.tasks.compile.JavaCompile::class.java).configureEach {
            sourceCompatibility = JavaVersion.VERSION_17.toString()
            targetCompatibility = JavaVersion.VERSION_17.toString()
            options.release.set(17)
        }
        sub.tasks.withType(org.jetbrains.kotlin.gradle.tasks.KotlinCompile::class.java).configureEach {
            kotlinOptions.jvmTarget = "17"
        }
    }
}
// PORTAL_GRADLE_PATCH_END
