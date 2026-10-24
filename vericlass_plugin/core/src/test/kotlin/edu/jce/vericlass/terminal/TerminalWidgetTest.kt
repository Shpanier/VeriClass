package edu.jce.vericlass.terminal

import com.intellij.terminal.JBTerminalSystemSettingsProviderBase
import com.intellij.terminal.JBTerminalWidget
import com.intellij.testFramework.fixtures.BasePlatformTestCase
import com.intellij.util.ui.UIUtil
import java.io.File
import java.nio.file.Files
import java.util.concurrent.CopyOnWriteArrayList

/**
 * The connector inside the IDE's real terminal widget (JediTerm), headless:
 * the prompt renders, a typed line runs, its output lands on the screen, and a
 * refused line shows the warning — exactly what the student sees in the tool window.
 */
class TerminalWidgetTest : BasePlatformTestCase() {

    // terminalStarter is deprecated in JediTerm, but it's the widget's own keystroke path.
    @Suppress("DEPRECATION")
    fun testCommandsRunInTheIdeTerminalWidget() {
        if (!File("/bin/bash").canExecute()) return
        val projectDir = Files.createTempDirectory("vericlass-lab").toFile()
        File(projectDir, "access.log").writeText("a 404\nb 500\nc 404\n")
        val records = CopyOnWriteArrayList<TerminalRecord>()
        val connector = VeriClassTtyConnector(
            shell = ShellSpec(listOf("/bin/bash"), "bash (test)"),
            policy = TerminalPolicy(setOf("grep", "tr", "awk", "wc")),
            projectDir = projectDir,
            projectName = "lab01",
            stateDir = Files.createTempDirectory("vericlass-state").toFile(),
        ) { records += it }

        val widget = JBTerminalWidget(project, JBTerminalSystemSettingsProviderBase(), testRootDisposable)
        widget.start(connector)
        waitFor("prompt") { screen(widget).contains("lab01$ ") }
        assertTrue(screen(widget).contains("VeriClass terminal"))

        widget.terminalStarter!!.sendString("grep -c 404 access.log | tr 2 X\r", true)
        waitFor("output") { records.size == 1 && screen(widget).contains("X") }
        assertEquals(0, records[0].exitCode)
        assertEquals(listOf("grep", "tr"), records[0].commands)

        widget.terminalStarter!!.sendString("python3 -c 'print(1)'\r", true)
        waitFor("refusal") { records.size == 2 && screen(widget).contains("reported to your instructor") }
        assertFalse(records[1].allowed)

        connector.close()
        projectDir.deleteRecursively()
    }

    private fun screen(widget: JBTerminalWidget): String = widget.terminalTextBuffer.screenLines

    private fun waitFor(what: String, condition: () -> Boolean) {
        val deadline = System.currentTimeMillis() + 15_000
        while (!condition()) {
            if (System.currentTimeMillis() > deadline) fail("timed out waiting for $what")
            UIUtil.dispatchAllInvocationEvents()
            Thread.sleep(50)
        }
    }
}
