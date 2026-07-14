package edu.jce.oslab.ide

import com.intellij.openapi.diagnostic.thisLogger
import edu.jce.oslab.api.TestInput
import java.io.File
import java.util.concurrent.TimeUnit

/** One test case executed against the student's real build. */
data class RunCase(
    val input: String,
    val expected: String,
    val actual: String,
    val passed: Boolean,
)

/**
 * The actual compile + run result the plugin reports alongside a submission, so
 * the teacher's recommended-grade correctness score is grounded in real
 * execution instead of an LLM guess.
 */
data class RunResult(
    val language: String,               // c | cpp | python | other
    val compileOk: Boolean?,            // null when not applicable (Python / unknown)
    val compileOutput: String,
    val cases: List<RunCase>,
)

/**
 * Compiles (C/C++) or interprets (Python) the student's active file and runs it
 * against the variant's test inputs, driving the built-in the way the brief
 * shows it invoked — `mcalc "3 + 4 * 2"` — over stdin, and capturing stdout.
 *
 * Everything here is best-effort and runs OFF the EDT (compilation blocks): any
 * failure yields a RunResult with nulls/empties so the submission still goes
 * through with just source + console.
 *
 * ASSUMPTION (verify against a real submission): the mini-shell reads a line
 * like `mcalc "<expr>"` from stdin and prints the result on its own line. The
 * command name is taken from the source file stem (mcalc.c -> `mcalc`). If a
 * cohort structures their program differently, adjust `commandLine` below.
 */
object RunReporter {

    private const val COMPILE_TIMEOUT_SEC = 30L
    private const val RUN_TIMEOUT_SEC = 5L

    fun run(source: String, filename: String, testInputs: List<TestInput>): RunResult {
        val language = languageOf(filename)
        if (language == "other" || source.isBlank()) {
            return RunResult(language, null, "", emptyList())
        }
        val stem = filename.substringBeforeLast('.').ifBlank { "prog" }
        val tmp = try {
            File.createTempFile("oslab-$stem", ".${filename.substringAfterLast('.', "txt")}")
        } catch (e: Exception) {
            thisLogger().debug("temp file creation failed", e)
            return RunResult(language, null, "", emptyList())
        }
        return try {
            tmp.writeText(source)
            when (language) {
                "c", "cpp" -> compiledRun(language, tmp, stem, testInputs)
                "python" -> pythonRun(tmp, stem, testInputs)
                else -> RunResult(language, null, "", emptyList())
            }
        } catch (e: Exception) {
            thisLogger().debug("run reporting failed", e)
            RunResult(language, null, "", emptyList())
        } finally {
            tmp.delete()
        }
    }

    private fun languageOf(filename: String): String = when (filename.substringAfterLast('.', "").lowercase()) {
        "c" -> "c"
        "cpp", "cc", "cxx", "hpp" -> "cpp"
        "py" -> "python"
        else -> "other"
    }

    private fun compiledRun(language: String, src: File, stem: String, tests: List<TestInput>): RunResult {
        val bin = File.createTempFile("oslab-bin-$stem", "")
        bin.delete() // compiler creates it
        val compiler = if (language == "cpp") "g++" else "gcc"
        val (code, out) = exec(listOf(compiler, "-O0", "-o", bin.absolutePath, src.absolutePath),
            input = null, timeoutSec = COMPILE_TIMEOUT_SEC)
        val compileOk = code == 0
        val cases = if (!compileOk) emptyList() else try {
            tests.map { runCase(listOf(bin.absolutePath), stem, it) }
        } finally {
            bin.delete()
        }
        return RunResult(language, compileOk, out.take(8000), cases)
    }

    private fun pythonRun(src: File, stem: String, tests: List<TestInput>): RunResult {
        val cases = tests.map { runCase(listOf("python3", src.absolutePath), stem, it) }
        return RunResult("python", null, "", cases)
    }

    /** Feed one `<cmd> "<expr>"` line to the program and compare its last output line. */
    private fun runCase(command: List<String>, stem: String, test: TestInput): RunCase {
        val line = "$stem \"${test.input}\"\n"
        val (_, out) = exec(command, input = line, timeoutSec = RUN_TIMEOUT_SEC)
        val actual = out.lines().lastOrNull { it.isNotBlank() }?.trim() ?: ""
        val expected = test.expected_output.trim()
        return RunCase(test.input, expected, actual, actual == expected)
    }

    /** Run a process with an optional stdin, returning (exitCode, merged stdout+stderr). */
    private fun exec(command: List<String>, input: String?, timeoutSec: Long): Pair<Int, String> {
        return try {
            val proc = ProcessBuilder(command).redirectErrorStream(true).start()
            if (input != null) {
                proc.outputStream.use { it.write(input.toByteArray()); it.flush() }
            } else {
                proc.outputStream.close()
            }
            val finished = proc.waitFor(timeoutSec, TimeUnit.SECONDS)
            if (!finished) {
                proc.destroyForcibly()
                return -1 to "(timed out after ${timeoutSec}s)"
            }
            proc.exitValue() to proc.inputStream.readBytes().toString(Charsets.UTF_8)
        } catch (e: Exception) {
            thisLogger().debug("exec failed: ${command.firstOrNull()}", e)
            -1 to "(could not run ${command.firstOrNull()}: ${e.message})"
        }
    }
}
