package edu.jce.vericlass.terminal

import org.junit.Assert.assertEquals
import org.junit.Test

class TerminalHistoryTest {

    private fun rec(line: String, output: String?, allowed: Boolean = true, exit: Int? = 0) =
        TerminalRecord(line, "lab", allowed, null, listOf(line), exit, 5, output, output = output)

    @Test
    fun `what ran after a mark, each command with its output`() {
        val h = TerminalHistory()
        h.add(rec("ls", "a.txt\n"))
        val mark = h.mark
        h.add(rec("docker pull alpine", "3.20: Pulling\nALL READY\n"))
        h.add(rec("true", null))
        assertEquals("$ docker pull alpine\n3.20: Pulling\nALL READY\n$ true", h.since(mark))
        assertEquals("", h.since(h.mark))
    }

    @Test
    fun `refused lines and the terminal's own commands are left out`() {
        val h = TerminalHistory()
        h.add(rec("rm -rf /", null, allowed = false, exit = null))
        h.add(rec("help", null))
        h.add(rec("clear", null))
        h.add(rec("uname -r", "6.8.0\n"))
        assertEquals("$ uname -r\n6.8.0", h.since(0))
    }

    @Test
    fun `only the latest output is kept and filled in`() {
        val h = TerminalHistory(keepChars = 20)
        repeat(5) { h.add(rec("echo $it", "line $it")) }
        assertEquals("$ echo 4\nline 4", h.since(0))
        assertEquals("ine 4", h.since(0, maxChars = 5))
    }
}
