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
        // Target CLion. Version comes from gradle.properties (-PclionVersion to override).
        create(IntelliJPlatformType.CLion, providers.gradleProperty("clionVersion").get())
        instrumentationTools()
        pluginVerifier()
    }
    // Bundled into the plugin distribution; used for all backend JSON.
    implementation("com.google.code.gson:gson:2.11.0")
}

intellijPlatform {
    // Keeps the built artifact + internal top-level folder named
    // `oslab-clion-plugin-<ver>.zip` (the install/publish scripts glob for this).
    projectName = "oslab-clion-plugin"
    pluginConfiguration {
        ideaVersion {
            sinceBuild = providers.gradleProperty("pluginSinceBuild")
            // Open-ended upper bound: a CLion upgrade (build 261, 271, …) must not
            // reject the plugin. Fine for a self-distributed course plugin;
            // JetBrains Marketplace would require a bounded range instead.
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
    // CLion 2024.2 runs on JBR 21.
    withType<JavaCompile> {
        sourceCompatibility = "21"
        targetCompatibility = "21"
    }
}
