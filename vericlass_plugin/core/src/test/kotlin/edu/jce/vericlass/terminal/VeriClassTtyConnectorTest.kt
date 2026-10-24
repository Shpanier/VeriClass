package edu.jce.vericlass.terminal

import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

/**
 * End to end through a real pseudo-terminal: keystrokes in, a shell runs the
 * line, output and a log record come back. Uses the system bash, so it runs on
 * macOS/Linux (on Windows the same path is exercised with BusyBox by hand).
 */
class VeriClassTtyConnectorTest {

    @get:Rule
    val tmp = TemporaryFolder()

    private lateinit var connector: VeriClassTtyConnector
    private val records = LinkedBlockingQueue<TerminalRecord>()
    private val pastes = LinkedBlockingQueue<String>()
    private val screen = StringBuffer()

    @Before
    fun setUp() {
        assumeTrue("needs /bin/bash", File("/bin/bash").canExecute())
        val project = tmp.newFolder("lab01")
        File(project, "logs").mkdirs()
        File(project, "logs/access.log").writeText("1.1.1.1 GET /a 404\n2.2.2.2 GET /b 500\n3.3.3.3 GET /c 404\n")
        connector = VeriClassTtyConnector(
            shell = ShellSpec(listOf("/bin/bash"), "bash (test)"),
            policy = TerminalPolicy(setOf("ls", "cat", "grep", "awk", "sort", "uniq", "wc", "tr", "sleep")),
            projectDir = project,
            projectName = "lab01",
            stateDir = tmp.newFolder("state"),
            onPaste = { pastes += it },
        ) { records += it }
        Thread {
            val buf = CharArray(1024)
            while (true) {
                val n = connector.read(buf, 0, buf.size)
                if (n < 0) break
                screen.append(buf, 0, n)
            }
        }.apply { isDaemon = true; start() }
    }

    @After
    fun tearDown() {
        if (::connector.isInitialized) connector.close()
    }

    private fun run(line: String): TerminalRecord {
        connector.write(line + "\r")
        return records.poll(15, TimeUnit.SECONDS) ?: error("no record for: $line\n--- screen ---\n$screen")
    }

    @Test
    fun `a pipeline runs and is logged with its output`() {
        val r = run("awk '\$4==404' logs/access.log | wc -l | tr -d ' '")
        assertTrue(r.allowed)
        assertEquals(0, r.exitCode)
        assertEquals("2", r.outputTail!!.trim())
        assertEquals(listOf("awk", "wc", "tr"), r.commands)
        assertEquals("lab01", r.cwd)
    }

    @Test
    fun `cd and variables carry over to the next line`() {
        assertEquals("lab01", run("cd logs").cwd) // logged where it was typed
        run("N=404")
        val r = run("grep -c \$N access.log")
        assertEquals("2", r.outputTail!!.trim())
        assertEquals("lab01/logs", r.cwd)
        assertTrue(VeriClassTtyConnector.stripAnsi(screen.toString()).contains("lab01/logs$ "))
    }

    @Test
    fun `a refused line never runs and is reported`() {
        val r = run("ls && bash -c 'touch pwned'")
        assertFalse(r.allowed)
        assertNull(r.exitCode)
        assertTrue(r.reason!!.contains("another shell"))
        assertTrue(screen.contains("reported to your instructor"))
        assertFalse(File(tmp.root, "lab01/pwned").exists())
    }

    @Test
    fun `backslashes reach the shell unchanged and the record names the shell`() {
        // The line goes through a file, not an environment variable: busybox-w32
        // turned every \ in VE_CMD into / (awk "\n", sed "\." broke on Windows).
        val r = run("printf '%s' 'a\\.b\\\"c\\n'")
        assertEquals("a\\.b\\\"c\\n", r.outputTail!!.trim())
        assertEquals("bash (test)", r.shell)
    }

    @Test
    fun `exit codes come back`() {
        assertEquals(1, run("grep -q nothing logs/access.log").exitCode)
    }

    @Test
    fun `ctrl-c stops a running command`() {
        connector.write("sleep 30\r")
        Thread.sleep(500)
        connector.write("\u0003")
        val r = records.poll(10, TimeUnit.SECONDS) ?: error("sleep was not interrupted\n$screen")
        assertTrue("exit ${r.exitCode}", r.exitCode != 0)
        assertTrue(r.durationMs!! < 10_000)
    }

    @Test
    fun `keys typed while a command runs go to that command`() {
        connector.write("read name; echo \"hi \$name\"\r")
        Thread.sleep(500)
        connector.write("dana\r")
        val r = records.poll(10, TimeUnit.SECONDS) ?: error("read never finished\n$screen")
        assertTrue(r.outputTail!!.contains("hi dana"))
    }

    @Test
    fun `a pasted block runs line by line`() {
        connector.write("cd logs\recho second\r")
        assertEquals("cd logs", records.poll(10, TimeUnit.SECONDS)!!.line)
        val second = records.poll(10, TimeUnit.SECONDS)!!
        assertEquals("echo second", second.line)
        assertEquals("lab01/logs", second.cwd)
        assertEquals("cd logs\recho second\r", pastes.poll(1, TimeUnit.SECONDS))
    }

    @Test
    fun `typing one key at a time is not a paste`() {
        "echo hi\r".forEach { connector.write(it.toString()) }
        assertEquals("echo hi", records.poll(10, TimeUnit.SECONDS)!!.line)
        connector.write("\u001b[A") // arrow up: an escape sequence, not a paste
        assertNull(pastes.poll(300, TimeUnit.MILLISECONDS))
        assertEquals("ls", VeriClassTtyConnector.pastedText("\u001b[200~ls\u001b[201~"))
    }

    @Test
    fun `the full output is kept, not just the tail`() {
        val r = run("awk 'BEGIN { for (i = 0; i < 20000; i++) print \"row \" i }'")
        val full = r.output!!
        assertTrue(full.startsWith("row 0\n"))
        assertTrue(full.trimEnd().endsWith("row 19999"))
        assertEquals(20000, full.trimEnd().lines().size)
        assertTrue(r.outputTail!!.length <= 4000)
    }
}
