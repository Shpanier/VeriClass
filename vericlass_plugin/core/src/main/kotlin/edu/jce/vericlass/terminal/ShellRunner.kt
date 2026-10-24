package edu.jce.vericlass.terminal

import com.pty4j.PtyProcess
import com.pty4j.PtyProcessBuilder
import java.io.File
import java.nio.file.Path
import java.util.TreeMap
import java.util.concurrent.TimeUnit

/** How to start the shell that runs each accepted line. */
data class ShellSpec(
    /** Program + leading args; the runner script's path is appended. */
    val command: List<String>,
    /** Shown in the terminal banner, e.g. "BusyBox (bundled)". */
    val label: String,
    /** Prepended to PATH (the BusyBox applet links on Linux), or null. */
    val pathPrefix: String? = null,
)

/**
 * Picks the shell. Preference order:
 *
 *  1. `VERICLASS_TERMINAL_SHELL` (a path to busybox or to an sh-compatible shell) —
 *     lets a teacher test a specific build.
 *  2. BusyBox bundled in the plugin under `bin/<os>-<arch>/` (Windows + Linux).
 *     Same tools and versions on both, so students are tested equally.
 *  3. Fallbacks: Git Bash on Windows, `/bin/bash` (or `/bin/sh`) elsewhere —
 *     macOS always lands here, since BusyBox doesn't target it.
 */
object ShellLocator {

    private val os = System.getProperty("os.name").lowercase()
    val isWindows = os.startsWith("windows")
    private val isLinux = os.startsWith("linux")

    fun locate(pluginDir: Path?): ShellSpec? {
        System.getenv("VERICLASS_TERMINAL_SHELL")?.takeIf { it.isNotBlank() }?.let { File(it) }?.takeIf { it.isFile }?.let {
            return specFor(it, "custom")
        }
        bundledBusybox(pluginDir)?.let { return specFor(it, "bundled") }
        return if (isWindows) gitBash()?.let { ShellSpec(listOf(it.path), "Git Bash") } else unixShell()
    }

    private fun specFor(file: File, origin: String): ShellSpec {
        if (!file.name.lowercase().startsWith("busybox")) return ShellSpec(listOf(file.path), "${file.name} ($origin)")
        if (!isWindows && !file.canExecute()) file.setExecutable(true)
        // busybox-w32 prefers its own applets by itself; on Linux we put links to
        // every applet first on PATH so `ls`, `awk`, … are BusyBox's, not the distro's.
        val links = if (isLinux) appletLinks(file) else null
        return ShellSpec(listOf(file.path, "sh"), "BusyBox ($origin)", links)
    }

    private fun bundledBusybox(pluginDir: Path?): File? {
        if (pluginDir == null) return null
        val osName = when {
            isWindows -> "windows"
            isLinux -> "linux"
            else -> return null
        }
        val arch = when (System.getProperty("os.arch").lowercase()) {
            "amd64", "x86_64", "x64" -> "x86_64"
            "aarch64", "arm64" -> "aarch64"
            else -> return null
        }
        val exe = if (isWindows) "busybox.exe" else "busybox"
        return pluginDir.resolve("bin").resolve("$osName-$arch").resolve(exe).toFile().takeIf { it.isFile }
    }

    /** `busybox --install -s <dir>` once, into a per-user cache dir; null if that fails. */
    private fun appletLinks(busybox: File): String? {
        val dir = File(System.getProperty("user.home"), ".cache/vericlass/busybox-applets")
        val marker = File(dir, ".installed-from")
        if (marker.isFile && marker.readText() == busybox.path && File(dir, "ls").exists()) return dir.path
        return try {
            dir.deleteRecursively()
            dir.mkdirs()
            val p = ProcessBuilder(busybox.path, "--install", "-s", dir.path).redirectErrorStream(true).start()
            p.inputStream.readBytes()
            if (!p.waitFor(10, TimeUnit.SECONDS) || !File(dir, "ls").exists()) return null
            marker.writeText(busybox.path)
            dir.path
        } catch (e: Exception) {
            null
        }
    }

    private fun gitBash(): File? {
        val roots = listOfNotNull(
            System.getenv("ProgramFiles"),
            System.getenv("ProgramFiles(x86)"),
            System.getenv("LOCALAPPDATA")?.let { "$it\\Programs" },
        )
        roots.map { File(it, "Git\\bin\\bash.exe") }.firstOrNull { it.isFile }?.let { return it }
        // On PATH — but never System32\bash.exe, which is the WSL launcher.
        return System.getenv("PATH").orEmpty().split(File.pathSeparator)
            .map { File(it, "bash.exe") }
            .firstOrNull { it.isFile && !it.path.lowercase().contains("system32") }
    }

    private fun unixShell(): ShellSpec? = when {
        File("/bin/bash").canExecute() -> ShellSpec(listOf("/bin/bash"), "bash (system)")
        File("/bin/sh").canExecute() -> ShellSpec(listOf("/bin/sh"), "sh (system)")
        else -> null
    }
}

/**
 * Runs one accepted command line at a time, each in a fresh shell under its own
 * pseudo-terminal (so colors, Ctrl-C, `tail -f` and prompts like `read` behave
 * as in a normal terminal). The shell state that matters between lines — the
 * working directory and variables — is saved by the runner script after every
 * line and restored before the next (see `terminal-runner.sh`).
 */
class ShellRunner(private val shell: ShellSpec, private val stateDir: File) {

    private val runner = File(stateDir, "runner.sh")
    private val stateFile = File(stateDir, "state.sh")
    private val cwdFile = File(stateDir, "cwd.txt")
    // The line goes to the shell in a file, not in an environment variable:
    // busybox-w32 turns every \ in imported variables into /, which broke
    // awk "\n", "\"" and sed "\." on Windows (TERMINAL.md, "Same results on every OS").
    private val cmdFile = File(stateDir, "cmd.txt")

    init {
        stateDir.mkdirs()
        val script = ShellRunner::class.java.getResourceAsStream("/vericlass/terminal-runner.sh")
            ?: error("terminal-runner.sh missing from the plugin")
        script.use { s -> runner.outputStream().use { s.copyTo(it) } }
    }

    fun start(line: String, cwd: File, columns: Int, rows: Int): PtyProcess {
        cwdFile.delete()
        cmdFile.writeText(line + "\n", Charsets.UTF_8)
        val command = (shell.command + slash(runner)).toTypedArray()
        return PtyProcessBuilder(command)
            .setEnvironment(environment(line, cwd))
            .setDirectory(cwd.path)
            .setInitialColumns(columns)
            .setInitialRows(rows)
            .setConsole(false)
            .setUseWinConPty(true)
            .setUnixOpenTtyToPreserveOutputAfterTermination(true)
            .start()
    }

    /** Where the line left the shell (after a `cd`), if it still exists. */
    fun endDirectory(): File? {
        val text = runCatching { cwdFile.readText().trim() }.getOrNull()?.takeIf { it.isNotEmpty() } ?: return null
        return File(text).takeIf { it.isDirectory }
    }

    fun dispose() {
        stateDir.deleteRecursively()
    }

    private fun environment(line: String, cwd: File): Map<String, String> {
        // Windows variable names are case-insensitive (Path vs PATH).
        val env: MutableMap<String, String> =
            if (ShellLocator.isWindows) TreeMap(String.CASE_INSENSITIVE_ORDER) else HashMap()
        env.putAll(System.getenv())
        env["TERM"] = "xterm-256color"
        env["VERICLASS_TERMINAL"] = "1"
        // Pagers and editors would take over the terminal (and an editor can open a shell).
        env["PAGER"] = "cat"
        env["GIT_PAGER"] = "cat"
        env["GIT_EDITOR"] = "echo 'VeriClass: use git commit -m \"message\"' >&2; false"
        // Same `sort` order on every machine, so expected outputs match.
        env["LC_COLLATE"] = "C"
        if (!ShellLocator.isWindows && env["LANG"].isNullOrBlank()) env["LANG"] = "en_US.UTF-8"
        shell.pathPrefix?.let { env["PATH"] = it + File.pathSeparator + env["PATH"].orEmpty() }
        env["VE_CMD_FILE"] = slash(cmdFile)
        env["VE_STATE"] = slash(stateFile)
        env["VE_CWD"] = slash(cwd)
        env["VE_CWD_OUT"] = slash(cwdFile)
        return env
    }

    /** Forward slashes work for BusyBox-w32, Git Bash and Unix alike. */
    private fun slash(f: File) = f.path.replace('\\', '/')

    companion object {
        /** Kill a command and everything it started (second Ctrl-C, or closing the terminal). */
        fun killTree(p: Process) {
            runCatching { ProcessHandle.of(p.pid()).ifPresent { h -> h.descendants().forEach { it.destroyForcibly() } } }
            p.destroyForcibly()
        }
    }
}
