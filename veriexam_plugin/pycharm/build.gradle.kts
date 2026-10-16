import org.jetbrains.intellij.platform.gradle.IntelliJPlatformType

plugins {
    id("java")
    id("org.jetbrains.kotlin.jvm") version "1.9.25"
    id("org.jetbrains.intellij.platform") version "2.1.0"
}

group = providers.gradleProperty("pluginGroup").get()
version = providers.gradleProperty("pluginVersion").get()

repositories {
    mavenCentral()
    intellijPlatform {
        defaultRepositories()
    }
}

dependencies {
    intellijPlatform {
        // Target PyCharm Community. Version comes from gradle.properties
        // (-PpycharmVersion to override). The plugin uses only platform + VFS
        // APIs, so a Community build also loads fine in PyCharm Professional.
        create(IntelliJPlatformType.PyCharmCommunity, providers.gradleProperty("pycharmVersion").get())
        instrumentationTools()
        pluginVerifier()
    }
    // Bundled into the plugin distribution; used for all backend JSON.
    implementation("com.google.code.gson:gson:2.11.0")
}

intellijPlatform {
    // Keeps the built artifact + internal top-level folder named
    // `veriexam-pycharm-plugin-<ver>.zip` (the install/publish scripts glob for this).
    projectName = "veriexam-pycharm-plugin"
    pluginConfiguration {
        ideaVersion {
            sinceBuild = providers.gradleProperty("pluginSinceBuild")
            // Open-ended upper bound — see the CLion module for rationale.
            untilBuild = provider { null }
        }
    }
}

kotlin {
    jvmToolchain(21)
    // Compile the shared core sources into this plugin. See ../core.
    sourceSets["main"].kotlin.srcDir("../core/src/main/kotlin")
}

// Shared non-code resources (icons, etc.), if any live under core.
sourceSets["main"].resources.srcDir("../core/src/main/resources")

tasks {
    // PyCharm 2024.2 runs on JBR 21.
    withType<JavaCompile> {
        sourceCompatibility = "21"
        targetCompatibility = "21"
    }
}
