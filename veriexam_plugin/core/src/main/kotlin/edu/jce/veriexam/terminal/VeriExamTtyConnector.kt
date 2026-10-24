package edu.jce.veriexam.terminal

import com.jediterm.core.util.TermSize
import com.jediterm.terminal.TtyConnector
import com.pty4j.PtyProcess
import com.pty4j.WinSize
import java.io.File
import java.io.InputStreamReader
import java.nio.charset.StandardCharsets
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock

/** One line the student entered, as logged for the teacher. */
data class TerminalRecord(
    val line: String,
    /** Working directory, relative to the project when inside it. */
    val cwd: String,
    val allowed: Boolean,
    val reason: String?,
    val commands: List<String>,
    /** Null when the line never ran (refused). */
    val exitCode: Int?,
    val durationMs: Long?,
    /** Last few KB of what the command printed, ANSI codes stripped. */
    val outputTail: String?,
    val syntaxError: Boolean = false,
    /** Everything it printed (stdout and stderr share the pty), ANSI codes stripped, up to ~4 MB. */
    val output: String? = outputTail,
    /** The shell that ran it, e.g. "BusyBox (bundled)"; null when no shell was found. */
    val shell: String? = null,
)

/**
 * The VeriExam terminal's engine, plugged into JediTerm (the terminal UI the
 * IDE uses) in place of a real shell process:
 *
 *   keystrokes → [LineEditor] → Enter → [CommandChecker]
 *        refused → red message, reported (never runs)
 *        allowed → [ShellRunner] runs it under a pseudo-terminal; while it runs,
 *                  keystrokes go straight to the program (Ctrl-C, `read`, `tail -f`)
 *   every line → [onRecord] (sent to the backend by the caller)
 *   a paste (several characters in one write) → [onPaste]
 */
class VeriExamTtyConnector(
    private val shell: ShellSpec?,
    private val policy: TerminalPolicy,
    private val projectDir: File,
    private val projectName: String,
    private val stateDir: File,
    private val onPaste: (String) -> Unit = {},
    private val onRecord: (TerminalRecord) -> Unit,
) : TtyConnector, LineEditorHost {

    private val screen = ScreenPipe()
    private val editor = LineEditor(this)
    private val runner = shell?.let { ShellRunner(it, stateDir) }
    private val lock = Any()

    @Volatile private var running: Running? = null
    @Volatile private var closed = false
    private var cwd: File = projectDir
    private var columns = 80
    private var rows = 24
    private val typeahead = StringBuilder()

    init {
        greet()
        editor.showPrompt()
    }

    // --- TtyConnector: JediTerm reads the screen from us and sends keys to us ---

    override fun read(buf: CharArray, offset: Int, length: Int): Int = screen.read(buf, offset, length)

    override fun write(bytes: ByteArray) = write(String(bytes, StandardCharsets.UTF_8))

    override fun write(string: String) {
        pastedText(string)?.let { runCatching { onPaste(it) } }
        running?.let { if (it.input(string)) return }
        synchronized(lock) {
            if (running != null) {
                // The command finished between the check above and the lock: replay later.
                typeahead.append(string)
                return
            }
            val leftover = editor.feed(string)
            if (leftover.isNotEmpty()) typeahead.append(leftover)
        }
    }

    override fun resize(termSize: TermSize) {
        columns = termSize.columns.coerceAtLeast(10)
        rows = termSize.rows.coerceAtLeast(2)
        synchronized(lock) { editor.columns = columns }
        running?.resize(columns, rows)
    }

    override fun isConnected(): Boolean = !closed

    override fun waitFor(): Int {
        screen.awaitClosed()
        return 0
    }

    override fun ready(): Boolean = screen.ready()

    override fun getName(): String = "VeriExam"

    override fun close() {
        if (closed) return
        closed = true
        running?.kill()
        runner?.dispose()
        stateDir.deleteRecursively()
        screen.close()
    }

    // --- LineEditorHost --------------------------------------------------------

    override fun emit(s: String) = screen.write(s)

    override fun prompt(): Prompt {
        val where = displayDir()
        return Prompt("$BLUE$where$RESET$ ", where.length + 2)
    }

    override fun complete(word: String, commandPosition: Boolean): List<String> {
        if (commandPosition && '/' !in word) {
            return (policy.allow + BUILTINS).filter { it.startsWith(word) }
        }
        val slash = word.lastIndexOf('/')
        val dirPart = if (slash >= 0) word.substring(0, slash + 1) else ""
        val prefix = word.substring(slash + 1)
        val dir = when {
            dirPart.startsWith("~/") -> File(System.getProperty("user.home"), dirPart.drop(2))
            dirPart.startsWith("/") -> File(dirPart)
            else -> File(cwd, dirPart)
        }
        val entries = dir.listFiles() ?: return emptyList()
        return entries
            .filter { it.name.startsWith(prefix) && (prefix.startsWith(".") || !it.name.startsWith(".")) }
            .map { dirPart + it.name + if (it.isDirectory) "/" else "" }
    }

    /** Called by the editor (under [lock]) when the student presses Enter. */
    override fun submit(line: String) {
        val trimmed = line.trim()
        if (trimmed.isEmpty()) return editor.showPrompt()
        if (builtin(trimmed)) return

        if (runner == null) {
            emit("${RED}veriexam: no shell was found on this computer — tell your instructor.$RESET\r\n")
            return editor.showPrompt()
        }
        val verdict = CommandChecker.check(line, policy, cwd)
        if (!verdict.allowed) {
            if (verdict.syntaxError) {
                emit("${YELLOW}veriexam: ${verdict.reason}$RESET\r\n")
            } else {
                emit("${RED}veriexam: ${verdict.reason}.$RESET\r\n")
                policy.blockedHint?.let { emit("$YELLOW${wrap(it)}$RESET\r\n") }
                emit("${DIM}This attempt was reported to your instructor.$RESET\r\n")
            }
            record(line, verdict, exitCode = null, durationMs = null, output = null)
            return editor.showPrompt()
        }
        start(line, verdict)
    }

    // --- running a command ---------------------------------------------------------

    private fun start(line: String, verdict: CommandVerdict) {
        val startedAt = System.currentTimeMillis()
        val typedIn = displayDir() // logged as where the line was typed, even after a `cd`
        val process = try {
            runner!!.start(line, cwd, columns, rows)
        } catch (e: Exception) {
            emit("${RED}veriexam: couldn't start the shell (${e.message})$RESET\r\n")
            record(line, verdict, exitCode = -1, durationMs = 0, output = e.message, full = e.message)
            return editor.showPrompt()
        }
        val r = Running(process)
        running = r
        val pump = Thread({ r.pumpOutput() }, "veriexam-terminal-output").apply { isDaemon = true; start() }
        Thread({
            val exit = runCatching { process.waitFor() }.getOrDefault(-1)
            pump.join(2_000) // let the last output reach the screen
            finished(line, verdict, r, exit, System.currentTimeMillis() - startedAt, typedIn)
        }, "veriexam-terminal-wait").apply { isDaemon = true; start() }
    }

    private fun finished(line: String, verdict: CommandVerdict, r: Running, exit: Int, durationMs: Long, typedIn: String) {
        if (closed) return
        synchronized(lock) {
            running = null
            runner?.endDirectory()?.let { cwd = it }
            // Programs that don't end with a newline would leave the prompt mid-line.
            if (!r.endedWithNewline) emit("$DIM⏎$RESET\r\n")
            record(line, verdict, exit, durationMs, r.tail(), typedIn, r.full())
            editor.showPrompt()
            if (typeahead.isNotEmpty()) {
                val pending = typeahead.toString()
                typeahead.setLength(0)
                val leftover = editor.feed(pending)
                typeahead.append(leftover)
            }
        }
    }

    /** One command in flight: its process, its output pump and Ctrl-C handling. */
    private inner class Running(val process: PtyProcess) {
        private val tail = StringBuilder()
        private val all = StringBuilder()
        private var dropped = 0L
        private var interrupts = 0
        @Volatile var endedWithNewline = true

        /** Forward keystrokes to the program. Returns false if it has already exited. */
        fun input(s: String): Boolean {
            if (!process.isAlive) return false
            if ('\u0003' in s && ++interrupts >= 2) {
                // The program ignored the first Ctrl-C: stop it and everything it started.
                emit("^C\r\n")
                ShellRunner.killTree(process)
                return true
            }
            runCatching {
                process.outputStream.write(s.toByteArray(StandardCharsets.UTF_8))
                process.outputStream.flush()
            }
            return true
        }

        fun resize(cols: Int, rows: Int) {
            runCatching { if (process.isAlive) process.setWinSize(WinSize(cols, rows)) }
        }

        fun pumpOutput() {
            val reader = InputStreamReader(process.inputStream, StandardCharsets.UTF_8)
            val buf = CharArray(4096)
            try {
                while (true) {
                    val n = reader.read(buf)
                    if (n < 0) break
                    if (n == 0) continue
                    val chunk = String(buf, 0, n)
                    emit(chunk)
                    synchronized(tail) {
                        tail.append(chunk)
                        if (tail.length > TAIL_KEEP * 2) tail.delete(0, tail.length - TAIL_KEEP)
                        val room = FULL_KEEP - all.length
                        if (room >= chunk.length) all.append(chunk) else {
                            if (room > 0) all.append(chunk, 0, room)
                            dropped += chunk.length - room.coerceAtLeast(0)
                        }
                    }
                    endedWithNewline = chunk.last() == '\n'
                }
            } catch (e: Exception) {
                // The pty closes when the program exits; on some platforms that's an IOException.
            }
        }

        fun tail(): String = synchronized(tail) { stripAnsi(tail.toString()).takeLast(TAIL_KEEP) }

        /** The whole output; past [FULL_KEEP] only the tail is known, so say how much is missing. */
        fun full(): String = synchronized(tail) {
            if (dropped == 0L) stripAnsi(all.toString())
            else stripAnsi(all.toString()) + "\n[… $dropped more characters not kept; the end was: …]\n" + tail()
        }

        fun kill() = ShellRunner.killTree(process)
    }

    // --- builtins --------------------------------------------------------------

    /** `clear`, `history`, `help`, `exit` are handled here, not by the shell. */
    private fun builtin(trimmed: String): Boolean {
        when (trimmed) {
            "clear" -> {
                emit("\u001b[H\u001b[2J")
            }
            "history" -> {
                editor.historyEntries.forEachIndexed { i, h -> emit("%5d  %s\r\n".format(i + 1, h)) }
            }
            "help" -> {
                emit("Commands you can use in this exercise:\r\n")
                emit(wrap((policy.allow + BUILTINS).sorted().joinToString(" ")) + "\r\n")
                emit("Pipes (|), redirection (> >> <), && || ; and \$(...) all work.\r\n")
                if (policy.scripts) emit("You can run your own scripts (./script.sh); they are checked too.\r\n")
            }
            "exit", "logout" -> {
                emit("${DIM}This terminal stays open for the whole session.$RESET\r\n")
            }
            else -> return false
        }
        record(trimmed, CommandVerdict(true, listOf(trimmed)), exitCode = 0, durationMs = 0, output = null)
        editor.showPrompt()
        return true
    }

    private fun greet() {
        emit("${BOLD}VeriExam terminal$RESET ${DIM}· ${shell?.label ?: "no shell found"}$RESET\r\n")
        emit("${DIM}Every command is checked against this exercise's rules and logged for your instructor.$RESET\r\n")
        emit("${DIM}Type 'help' to see the commands you can use.$RESET\r\n\r\n")
    }

    // --- helpers ---------------------------------------------------------------

    private fun record(
        line: String,
        verdict: CommandVerdict,
        exitCode: Int?,
        durationMs: Long?,
        output: String?,
        typedIn: String = displayDir(),
        full: String? = output,
    ) {
        val rec = TerminalRecord(
            line = line,
            cwd = typedIn,
            allowed = verdict.allowed,
            reason = verdict.reason,
            commands = verdict.commands,
            exitCode = exitCode,
            durationMs = durationMs,
            outputTail = output?.takeIf { it.isNotBlank() },
            syntaxError = verdict.syntaxError,
            output = full?.takeIf { it.isNotBlank() },
            shell = shell?.label,
        )
        runCatching { onRecord(rec) }
    }

    /** `lab01/logs` inside the project (named after it), an absolute path outside it. */
    private fun displayDir(): String {
        val rel = runCatching { cwd.canonicalFile.relativeTo(projectDir.canonicalFile).path }.getOrNull()
        return when {
            rel == null || rel.startsWith("..") -> cwd.path.replace('\\', '/')
            rel.isEmpty() -> projectName
            else -> projectName + "/" + rel.replace('\\', '/')
        }
    }

    private fun wrap(text: String): String {
        val out = StringBuilder()
        var col = 0
        for (word in text.split(' ')) {
            if (col > 0 && col + word.length + 1 > columns) { out.append("\r\n"); col = 0 }
            if (col > 0) { out.append(' '); col++ }
            out.append(word)
            col += word.length
        }
        return out.toString()
    }

    /** A blocking character pipe: we write screen output, JediTerm reads it. */
    private class ScreenPipe {
        private val lock = ReentrantLock()
        private val changed = lock.newCondition()
        private val buf = StringBuilder()
        private var closed = false

        fun write(s: String) = lock.withLock {
            if (closed) return
            buf.append(s)
            changed.signalAll()
        }

        fun read(dst: CharArray, off: Int, len: Int): Int = lock.withLock {
            while (buf.isEmpty() && !closed) changed.await()
            if (buf.isEmpty()) return -1
            val n = minOf(len, buf.length)
            buf.getChars(0, n, dst, off)
            buf.delete(0, n)
            n
        }

        fun ready(): Boolean = lock.withLock { buf.isNotEmpty() }

        fun close() = lock.withLock {
            closed = true
            changed.signalAll()
        }

        fun awaitClosed() = lock.withLock {
            while (!closed) changed.await()
        }
    }

    companion object {
        private const val TAIL_KEEP = 4000
        private const val FULL_KEEP = 4_000_000

        private const val PASTE_START = "\u001b[200~"
        private const val PASTE_END = "\u001b[201~"

        /**
         * The text when this write is a paste, else null. Typing sends one
         * character per write and special keys send escape sequences; a paste
         * arrives as one multi-character write (bracketed when a running program
         * turned that mode on).
         */
        fun pastedText(s: String): String? = when {
            s.startsWith(PASTE_START) -> s.removePrefix(PASTE_START).removeSuffix(PASTE_END)
            s.length >= 2 && s[0] != '\u001b' && s.any { it >= ' ' } -> s
            else -> null
        }
        private val BUILTINS = listOf("cd", "pwd", "echo", "printf", "export", "clear", "history", "help")

        private const val RESET = "\u001b[0m"
        private const val BOLD = "\u001b[1m"
        private const val DIM = "\u001b[2m"
        private const val RED = "\u001b[31m"
        private const val YELLOW = "\u001b[33m"
        private const val BLUE = "\u001b[1;34m"

        private val ANSI = Regex("\u001b\\[[0-?]*[ -/]*[@-~]|\u001b\\][^\u0007\u001b]*(\u0007|\u001b\\\\)|\u001b[@-Z\\\\-_]")

        fun stripAnsi(s: String): String = ANSI.replace(s, "").replace("\r\n", "\n").replace("\r", "")
    }
}
