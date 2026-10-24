import org.jetbrains.intellij.platform.gradle.IntelliJPlatformType
import org.jetbrains.intellij.platform.gradle.TestFrameworkType

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
        // Headless IDE for the terminal-widget test (core/src/test).
        testFramework(TestFrameworkType.Platform)
    }
    // Bundled into the plugin distribution; used for all backend JSON.
    implementation("com.google.code.gson:gson:2.11.0")
    // Plain unit tests for the IDE-free parts (terminal command checker, line editor).
    testImplementation("junit:junit:4.13.2")
    // The IntelliJ test framework's assertions extend opentest4j's.
    testImplementation("org.opentest4j:opentest4j:1.3.0")
}

intellijPlatform {
    // Keeps the built artifact + internal top-level folder named
    // `vericlass-pycharm-plugin-<ver>.zip` (the install/publish scripts glob for this).
    projectName = "vericlass-pycharm-plugin"
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
    sourceSets["test"].kotlin.srcDir("../core/src/test/kotlin")
}

// Shared non-code resources (icons, etc.), if any live under core.
sourceSets["main"].resources.srcDir("../core/src/main/resources")

tasks {
    // Ship BusyBox for the VeriClass terminal (bin/<os>-<arch>/busybox[.exe]) when
    // packaging/fetch_busybox.sh has downloaded it; without it the terminal falls
    // back to Git Bash / the system bash.
    prepareSandbox {
        from(rootProject.layout.projectDirectory.dir("busybox")) {
            into(pluginName.map { "$it/bin" })
        }
    }

    // PyCharm 2024.2 runs on JBR 21.
    withType<JavaCompile> {
        sourceCompatibility = "21"
        targetCompatibility = "21"
    }
}
