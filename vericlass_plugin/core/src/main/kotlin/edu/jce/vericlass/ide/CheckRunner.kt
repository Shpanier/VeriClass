package edu.jce.vericlass.ide

import com.intellij.openapi.diagnostic.thisLogger
import com.intellij.openapi.project.Project
import com.intellij.openapi.roots.ProjectRootManager
import java.io.File
import java.nio.charset.StandardCharsets
import java.util.concurrent.TimeUnit

/**
 * Runs an exercise's `check_command` (e.g. "python checks.py") when the student
 * submits a step, so the teacher sees its output next to the answer.
 *
 * Only a Python interpreter running files inside the project is allowed: the
 * command comes from the teacher's server, and this keeps a bad or hostile one
 * from running anything else on the student's computer. The project's own
 * interpreter (where pandas is installed) is preferred over the one on PATH.
 */
object CheckRunner {

    private val PYTHON_NAMES = setOf("python", "python3", "py")
    private const val TIMEOUT_SECONDS = 30L
    private const val OUTPUT_MAX = 20_000

    /** Runs on the calling thread (not the EDT). Null when there is nothing to run or it is refused. */
    fun run(project: Project, command: String?): String? {
        val parts = command?.trim()?.split(Regex("\\s+"))?.filter { it.isNotEmpty() } ?: return null
        if (parts.isEmpty() || parts[0].lowercase() !in PYTHON_NAMES) return null
        val base = project.basePath?.let { File(it) }?.takeIf { it.isDirectory } ?: return null
        val args = parts.drop(1)
        if (args.any { !safeArg(base, it) }) return "VeriClass: the check command was refused (only files inside the project may run)."

        for (python in interpreters(project, base)) {
            try {
                val process = ProcessBuilder(listOf(python) + args)
                    .directory(base)
                    .redirectErrorStream(true)
                    .apply { environment()["PYTHONIOENCODING"] = "utf-8" }
                    .start()
                val out = StringBuilder()
                val reader = Thread {
                    process.inputStream.bufferedReader(StandardCharsets.UTF_8).use { r ->
                        val buf = CharArray(4096)
                        while (true) {
                            val n = r.read(buf)
                            if (n < 0) break
                            synchronized(out) { if (out.length < OUTPUT_MAX * 2) out.append(buf, 0, n) }
                        }
                    }
                }.apply { isDaemon = true; start() }
                if (!process.waitFor(TIMEOUT_SECONDS, TimeUnit.SECONDS)) {
                    process.destroyForcibly()
                    reader.join(1_000)
                    return synchronized(out) { out.toString().takeLast(OUTPUT_MAX) } +
                        "\n[stopped after $TIMEOUT_SECONDS s]"
                }
                reader.join(2_000)
                val text = synchronized(out) { out.toString() }.takeLast(OUTPUT_MAX)
                return "$ ${parts.joinToString(" ")}  (exit ${process.exitValue()})\n$text"
            } catch (e: java.io.IOException) {
                thisLogger().debug("check command: $python not runnable", e)
                continue // try the next interpreter
            }
        }
        return "VeriClass: no Python interpreter was found to run the check."
    }

    /** A plain file name or relative path inside the project, or an option like -u. */
    private fun safeArg(base: File, arg: String): Boolean {
        if (arg.startsWith("-")) return arg.length <= 4 && arg.drop(1).all { it.isLetter() }
        if (File(arg).isAbsolute || arg.contains("..")) return false
        val f = File(base, arg).canonicalFile
        return f.path.startsWith(base.canonicalFile.path) && f.isFile
    }

    /** The project's interpreter, a .venv/venv in the project, then the names on PATH. */
    private fun interpreters(project: Project, base: File): List<String> {
        val out = mutableListOf<String>()
        runCatching { ProjectRootManager.getInstance(project).projectSdk?.homePath }.getOrNull()
            ?.takeIf { File(it).canExecute() }?.let(out::add)
        for (dir in listOf(".venv", "venv")) {
            for (rel in listOf("bin/python", "Scripts/python.exe")) {
                File(base, "$dir/$rel").takeIf { it.canExecute() }?.let { out.add(it.path) }
            }
        }
        val windows = System.getProperty("os.name").lowercase().startsWith("windows")
        // On Windows "python3" may be the Store's stub; "py" is the official launcher.
        out += if (windows) listOf("python", "py", "python3") else listOf("python3", "python")
        return out.distinct()
    }
}
