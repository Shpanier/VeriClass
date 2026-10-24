package edu.jce.vericlass.terminal

/** The prompt as drawn ([ansi], with colors) and how many columns it takes on screen. */
data class Prompt(val ansi: String, val width: Int)

/** What the editor needs from the terminal around it. */
interface LineEditorHost {
    /** Write to the screen. */
    fun emit(s: String)

    fun prompt(): Prompt

    /** Enter was pressed. The editor has already moved to a fresh line. */
    fun submit(line: String)

    /**
     * Tab completion candidates for [word]. [commandPosition] is true when the
     * word is where a program name goes (start of line, after `|`, `;`, `&&`…).
     * Directories end with `/`.
     */
    fun complete(word: String, commandPosition: Boolean): List<String>
}

/**
 * A small readline: the student's keystrokes are edited here — not in a real
 * shell — so VeriClass sees the exact line before anything runs. Supports the
 * keys people reach for without thinking: arrows, Home/End, Delete, history
 * (↑/↓), Tab completion, Ctrl-A/E/K/U/W/L/C.
 *
 * Rendering redraws prompt + line from its first row on every change, which
 * keeps long lines that wrap past the terminal width correct.
 */
class LineEditor(private val host: LineEditorHost) {

    /** Terminal width in columns; updated on resize. */
    var columns = 80
        set(value) {
            field = value.coerceAtLeast(10)
        }

    /** True while waiting at the prompt (false while a command runs). */
    var active = false
        private set

    private val buf = StringBuilder()
    private var cursor = 0
    private val history = mutableListOf<String>()
    private var historyIndex = 0
    private var stash = ""
    private val esc = StringBuilder()
    private var lastWasTab = false
    private var skipLf = false

    // Row (counted from the prompt's first row) the terminal cursor is on now.
    private var cursorRow = 0

    val historyEntries: List<String> get() = history

    fun showPrompt() {
        buf.setLength(0)
        cursor = 0
        cursorRow = 0
        historyIndex = history.size
        stash = ""
        lastWasTab = false
        active = true
        val p = host.prompt()
        host.emit(p.ansi)
    }

    /**
     * Feed keystrokes / pasted text. Returns whatever came AFTER an Enter that
     * submitted the line — the caller replays it at the next prompt, so a pasted
     * block of several commands runs one line at a time.
     */
    fun feed(input: String): String {
        var i = 0
        while (i < input.length) {
            val c = input[i]
            if (skipLf) {
                // The \n of a \r\n pair belongs to the line just submitted.
                skipLf = false
                if (c == '\n') {
                    i++
                    continue
                }
            }
            if (!active) return input.substring(i)
            i++
            if (esc.isNotEmpty()) {
                esc.append(c)
                if (escapeComplete()) {
                    handleEscape(esc.toString())
                    esc.setLength(0)
                }
                continue
            }
            val wasTab = lastWasTab
            lastWasTab = false
            when (c) {
                '\u001b' -> esc.append(c)
                '\r' -> { skipLf = true; enter() }
                '\n' -> enter()
                '\u0001' -> moveTo(0)                 // Ctrl-A
                '\u0002' -> moveTo(cursor - 1)        // Ctrl-B
                '\u0003' -> cancelLine()              // Ctrl-C
                '\u0004' -> deleteForward()           // Ctrl-D (no logout here)
                '\u0005' -> moveTo(buf.length)        // Ctrl-E
                '\u0006' -> moveTo(cursor + 1)        // Ctrl-F
                '\u0008', '\u007f' -> backspace()
                '\t' -> complete(wasTab)
                '\u000b' -> { buf.setLength(cursor); redraw() }               // Ctrl-K
                '\u000c' -> clearScreen()                                      // Ctrl-L
                '\u000e' -> historyNext()                                      // Ctrl-N
                '\u0010' -> historyPrev()                                      // Ctrl-P
                '\u0015' -> { buf.delete(0, cursor); cursor = 0; redraw() }   // Ctrl-U
                '\u0017' -> deleteWordBack()                                   // Ctrl-W
                else -> if (c >= ' ') insert(c)
            }
        }
        return ""
    }

    /** Clear the screen and redraw the prompt with the current line. */
    fun clearScreen() {
        host.emit("\u001b[H\u001b[2J")
        cursorRow = 0
        redraw(fromTop = true)
    }

    // --- editing --------------------------------------------------------------

    private fun insert(c: Char) {
        buf.insert(cursor, c)
        cursor++
        if (cursor == buf.length && !wrapsAt(cursor)) {
            // Typing at the end of the line: just echo the character, no redraw.
            host.emit(c.toString())
            cursorRow = (host.prompt().width + cursor) / columns
        } else {
            redraw()
        }
    }

    private fun wrapsAt(pos: Int): Boolean = (host.prompt().width + pos) % columns == 0

    private fun backspace() {
        if (cursor == 0) return
        buf.deleteCharAt(cursor - 1)
        cursor--
        redraw()
    }

    private fun deleteForward() {
        if (cursor >= buf.length) return
        buf.deleteCharAt(cursor)
        redraw()
    }

    private fun deleteWordBack() {
        var start = cursor
        while (start > 0 && buf[start - 1] == ' ') start--
        while (start > 0 && buf[start - 1] != ' ') start--
        buf.delete(start, cursor)
        cursor = start
        redraw()
    }

    private fun moveTo(pos: Int) {
        val p = pos.coerceIn(0, buf.length)
        if (p == cursor) return
        cursor = p
        redraw()
    }

    private fun wordLeft() {
        var p = cursor
        while (p > 0 && !buf[p - 1].isLetterOrDigit()) p--
        while (p > 0 && buf[p - 1].isLetterOrDigit()) p--
        moveTo(p)
    }

    private fun wordRight() {
        var p = cursor
        while (p < buf.length && !buf[p].isLetterOrDigit()) p++
        while (p < buf.length && buf[p].isLetterOrDigit()) p++
        moveTo(p)
    }

    private fun cancelLine() {
        cursor = buf.length
        redraw()
        host.emit("^C\r\n")
        showPrompt()
    }

    private fun enter() {
        val line = buf.toString()
        cursor = buf.length
        redraw()
        host.emit("\r\n")
        active = false
        if (line.isNotBlank() && history.lastOrNull() != line) history += line
        host.submit(line)
    }

    // --- history -------------------------------------------------------------------

    private fun historyPrev() {
        if (historyIndex == 0) return
        if (historyIndex == history.size) stash = buf.toString()
        historyIndex--
        replaceLine(history[historyIndex])
    }

    private fun historyNext() {
        if (historyIndex >= history.size) return
        historyIndex++
        replaceLine(if (historyIndex == history.size) stash else history[historyIndex])
    }

    private fun replaceLine(text: String) {
        buf.setLength(0)
        buf.append(text)
        cursor = buf.length
        redraw()
    }

    // --- completion ------------------------------------------------------------------

    private fun complete(secondTab: Boolean) {
        var start = cursor
        while (start > 0 && buf[start - 1] !in " \t|;&<>(") start--
        val word = buf.substring(start, cursor)
        var before = start - 1
        while (before >= 0 && buf[before] == ' ') before--
        val commandPosition = before < 0 || buf[before] in "|;&("
        val candidates = host.complete(word, commandPosition).distinct().sorted()
        if (candidates.isEmpty()) return

        if (candidates.size == 1) {
            val only = candidates[0]
            val suffix = if (only.endsWith("/")) "" else " "
            replaceWord(start, escapeSpaces(only) + suffix)
            return
        }
        val common = candidates.reduce { a, b -> a.commonPrefixWith(b) }
        if (common.length > word.length) {
            replaceWord(start, escapeSpaces(common))
            return
        }
        if (secondTab) {
            // List the choices under the line (like bash's double Tab), then redraw.
            cursor = buf.length
            redraw()
            host.emit("\r\n" + columnize(candidates.map { it.substringAfterLast('/').ifEmpty { it } }) + "\r\n")
            cursorRow = 0
            redraw(fromTop = true)
        } else {
            lastWasTab = true
        }
    }

    private fun replaceWord(start: Int, text: String) {
        buf.replace(start, cursor, text)
        cursor = start + text.length
        redraw()
    }

    private fun escapeSpaces(s: String) = s.replace(" ", "\\ ")

    private fun columnize(items: List<String>): String {
        val width = (items.maxOf { it.length } + 2).coerceAtMost(columns)
        val perRow = (columns / width).coerceAtLeast(1)
        return items.chunked(perRow).joinToString("\r\n") { row -> row.joinToString("") { it.padEnd(width) }.trimEnd() }
    }

    // --- escape sequences ----------------------------------------------------------------

    private fun escapeComplete(): Boolean {
        if (esc.length < 2) return false
        return when (esc[1]) {
            '[' -> esc.length >= 3 && esc.last().code in 0x40..0x7e
            'O' -> esc.length >= 3
            else -> true // Alt+key: ESC followed by one character
        }
    }

    private fun handleEscape(seq: String) {
        when (seq) {
            "\u001b[A", "\u001bOA" -> historyPrev()
            "\u001b[B", "\u001bOB" -> historyNext()
            "\u001b[C", "\u001bOC" -> moveTo(cursor + 1)
            "\u001b[D", "\u001bOD" -> moveTo(cursor - 1)
            "\u001b[H", "\u001bOH", "\u001b[1~", "\u001b[7~" -> moveTo(0)
            "\u001b[F", "\u001bOF", "\u001b[4~", "\u001b[8~" -> moveTo(buf.length)
            "\u001b[3~" -> deleteForward()
            "\u001b[1;5C", "\u001b[1;3C", "\u001bf" -> wordRight()
            "\u001b[1;5D", "\u001b[1;3D", "\u001bb" -> wordLeft()
            "\u001b\u007f", "\u001b\u0008" -> deleteWordBack()
            // Anything else (F-keys, bracketed-paste markers…) is ignored.
        }
    }

    // --- rendering ------------------------------------------------------------------

    /**
     * Repaint prompt + line. Moves up to the prompt's first row, clears to the end
     * of the screen, writes everything, then places the cursor — counting rows
     * so a line that wraps past the terminal width still lands right.
     */
    private fun redraw(fromTop: Boolean = false) {
        val p = host.prompt()
        val sb = StringBuilder()
        if (!fromTop && cursorRow > 0) sb.append("\u001b[").append(cursorRow).append('A')
        sb.append('\r').append("\u001b[J")
        sb.append(p.ansi).append(buf)
        val end = p.width + buf.length
        // At an exact multiple of the width the terminal holds the cursor at the
        // last column ("pending wrap"); force the wrap so the row math below holds.
        if (end > 0 && end % columns == 0) sb.append(" \r\u001b[K")
        val endRow = end / columns
        val target = p.width + cursor
        val targetRow = target / columns
        val targetCol = target % columns
        if (endRow > targetRow) sb.append("\u001b[").append(endRow - targetRow).append('A')
        sb.append('\r')
        if (targetCol > 0) sb.append("\u001b[").append(targetCol).append('C')
        cursorRow = targetRow
        host.emit(sb.toString())
    }
}
