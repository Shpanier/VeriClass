package edu.jce.vericlass.terminal

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class LineEditorTest {

    private class Host : LineEditorHost {
        val screen = StringBuilder()
        val submitted = mutableListOf<String>()
        var files = listOf("access.log", "access_old.log", "logs/")
        lateinit var editor: LineEditor

        override fun emit(s: String) {
            screen.append(s)
        }

        override fun prompt() = Prompt("$ ", 2)

        override fun submit(line: String) {
            submitted += line
            editor.showPrompt()
        }

        override fun complete(word: String, commandPosition: Boolean): List<String> =
            if (commandPosition) listOf("grep", "git").filter { it.startsWith(word) }
            else files.filter { it.startsWith(word) }
    }

    private fun editor(): Pair<LineEditor, Host> {
        val host = Host()
        val ed = LineEditor(host)
        host.editor = ed
        ed.showPrompt()
        return ed to host
    }

    @Test
    fun `typing and enter submits the line`() {
        val (ed, host) = editor()
        ed.feed("ls -la\r")
        assertEquals(listOf("ls -la"), host.submitted)
    }

    @Test
    fun `backspace, arrows and ctrl keys edit in place`() {
        val (ed, host) = editor()
        ed.feed("lsx\u007f -l")                // backspace
        ed.feed("\u001b[D\u001b[D\u001b[D")   // left ×3 → before " -l"
        ed.feed("a")                            // "lsa -l"
        ed.feed("\u0005 /tmp")                  // Ctrl-E, append
        ed.feed("\u0001\u001b[3~")              // Ctrl-A, Delete → "sa -l /tmp"
        ed.feed("\r")
        assertEquals("sa -l /tmp", host.submitted.single())
    }

    @Test
    fun `ctrl-u, ctrl-w and ctrl-k kill text`() {
        val (ed, host) = editor()
        ed.feed("grep 404 access.log\u0017\u0017x\r")  // Ctrl-W twice
        ed.feed("echo hi\u0015pwd\r")                   // Ctrl-U
        ed.feed("cat file\u0001\u001b[C\u001b[C\u001b[C\u000b\r") // Ctrl-K after "cat"
        assertEquals(listOf("grep x", "pwd", "cat"), host.submitted)
    }

    @Test
    fun `history with up and down`() {
        val (ed, host) = editor()
        ed.feed("one\r")
        ed.feed("two\r")
        ed.feed("draft")
        ed.feed("\u001b[A")          // up → two
        ed.feed("\u001b[A")          // up → one
        ed.feed("\u001b[B")          // down → two
        ed.feed("\u001b[B")          // down → back to the draft
        ed.feed("\r")
        ed.feed("\u001bOA\r")        // application-mode up → draft again
        assertEquals(listOf("one", "two", "draft", "draft"), host.submitted)
    }

    @Test
    fun `ctrl-c abandons the line`() {
        val (ed, host) = editor()
        ed.feed("rm -rf something\u0003")
        ed.feed("ls\r")
        assertEquals(listOf("ls"), host.submitted)
        assertTrue(host.screen.contains("^C"))
    }

    @Test
    fun `pasted lines run one at a time`() {
        val host = Host()
        // A host that doesn't come back to the prompt right away (a command is running).
        val stalled = object : LineEditorHost by host {
            override fun submit(line: String) {
                host.submitted += line
            }
        }
        val ed2 = LineEditor(stalled)
        ed2.showPrompt()
        val leftover = ed2.feed("ls\r\npwd\r\n")
        assertEquals(listOf("ls"), host.submitted)
        assertEquals("pwd\r\n", leftover)
        ed2.showPrompt()
        assertEquals("", ed2.feed(leftover))
        assertEquals(listOf("ls", "pwd"), host.submitted)
    }

    @Test
    fun `tab completes commands and files`() {
        val (ed, host) = editor()
        ed.feed("gr\t")                       // command position → "grep "
        ed.feed("404 acc\t")                  // two matches → common prefix "access"
        ed.feed(".\t")                        // unique → "access.log "
        ed.feed("\r")
        assertEquals("grep 404 access.log ", host.submitted.single())
    }

    @Test
    fun `double tab lists the choices`() {
        val (ed, host) = editor()
        ed.feed("cat access\t\t")
        assertTrue(host.screen.contains("access.log"))
        assertTrue(host.screen.contains("access_old.log"))
    }

    @Test
    fun `long lines wrap and still edit correctly`() {
        val (ed, host) = editor()
        ed.columns = 20
        val long = "echo " + "x".repeat(50)
        ed.feed(long)
        ed.feed("\u0001")                     // jump to start across wrapped rows
        ed.feed("#")
        ed.feed("\r")
        assertEquals("#$long", host.submitted.single())
        // Moving back up to the prompt's first row uses cursor-up sequences.
        assertTrue(host.screen.contains("\u001b[2A"))
    }
}
