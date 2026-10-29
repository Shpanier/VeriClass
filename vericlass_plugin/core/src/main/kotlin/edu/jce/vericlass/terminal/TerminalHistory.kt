package edu.jce.vericlass.terminal

/**
 * The commands the VeriClass terminal ran in this session, with what they
 * printed, kept in memory. A class-paced lab fills its "Done" box from here:
 * everything run since the step appeared ([mark] then, [since] now), which the
 * student checks before sending. Thread-safe.
 */
class TerminalHistory(private val keepChars: Int = KEEP_CHARS) {

    private val lines = ArrayDeque<Pair<Long, String>>()
    private var count = 0L
    private var chars = 0

    /** A point in the history; [since] returns what ran after it. */
    val mark: Long get() = synchronized(this) { count }

    fun add(rec: TerminalRecord) {
        // A refused line never ran, and the terminal's own commands (help, clear) aren't the step's.
        if (!rec.allowed || rec.exitCode == null || rec.line.trim() in OWN_COMMANDS) return
        val output = rec.output.orEmpty().trimEnd('\n')
        val text = "$ ${rec.line.trim()}" + if (output.isEmpty()) "" else "\n$output"
        synchronized(this) {
            count++
            lines.addLast(count to text)
            chars += text.length
            while (chars > keepChars && lines.size > 1) chars -= lines.removeFirst().second.length
        }
    }

    /** The commands run after [mark], each with its output; empty when none. At most the last [maxChars]. */
    fun since(mark: Long, maxChars: Int = MAX_PREFILL): String {
        val text = synchronized(this) { lines.filter { it.first > mark }.joinToString("\n") { it.second } }
        return if (text.length <= maxChars) text else text.takeLast(maxChars)
    }

    companion object {
        private val OWN_COMMANDS = setOf("clear", "history", "help", "exit", "logout")
        private const val KEEP_CHARS = 400_000
        // The server keeps the last 50,000 characters of a step's output.
        const val MAX_PREFILL = 50_000
    }
}
