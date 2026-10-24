package edu.jce.vericlass.terminal

import com.intellij.ide.plugins.PluginManager
import com.intellij.openapi.Disposable
import com.intellij.openapi.diagnostic.thisLogger
import com.intellij.openapi.project.DumbAware
import com.intellij.openapi.project.Project
import com.intellij.openapi.util.Disposer
import com.intellij.openapi.wm.ToolWindow
import com.intellij.openapi.wm.ToolWindowFactory
import com.intellij.terminal.JBTerminalSystemSettingsProviderBase
import com.intellij.terminal.JBTerminalWidget
import com.intellij.ui.components.JBLabel
import com.intellij.ui.content.ContentFactory
import com.intellij.util.ui.JBUI
import edu.jce.vericlass.api.TerminalPolicyDto
import java.awt.BorderLayout
import java.io.File
import java.nio.file.Files
import javax.swing.JPanel
import javax.swing.SwingConstants

/** Registers the "VeriClass Terminal" tool window (bottom), next to where Terminal and Run live. */
class VeriClassTerminalToolWindowFactory : ToolWindowFactory, DumbAware {

    override fun createToolWindowContent(project: Project, toolWindow: ToolWindow) {
        val panel = TerminalHostPanel(project, toolWindow.disposable)
        val content = ContentFactory.getInstance().createContent(panel, "", false)
        toolWindow.contentManager.addContent(content)
    }

    companion object {
        const val ID = "VeriClass Terminal"
    }
}

/**
 * Shows a placeholder until the student logs in on the right, then a JediTerm
 * terminal wired to [VeriClassTtyConnector]. A new login replaces the terminal;
 * logging out (or a torn-down session) puts the placeholder back.
 */
private class TerminalHostPanel(private val project: Project, parent: Disposable) : JPanel(BorderLayout()), Disposable {

    private var terminalScope: Disposable? = null

    init {
        Disposer.register(parent, this)
        VeriClassSessionService.getInstance(project).subscribe(this, ::onSession)
    }

    private fun onSession(session: VeriClassSessionService.Active?) {
        if (project.isDisposed) return
        terminalScope?.let { Disposer.dispose(it) }
        terminalScope = null
        removeAll()
        when {
            session == null -> message("Log in to VeriClass (the panel on the right) to open your terminal.")
            session.exercise.terminal == null ->
                message("This VeriClass server doesn't offer a terminal yet. Ask your instructor to update it.")
            else -> openTerminal(session, session.exercise.terminal)
        }
        revalidate()
        repaint()
    }

    private fun openTerminal(session: VeriClassSessionService.Active, dto: TerminalPolicyDto) {
        val scope = Disposer.newDisposable(this, "vericlass-terminal")
        terminalScope = scope
        try {
            val projectDir = project.basePath?.let { File(it) }?.takeIf { it.isDirectory }
                ?: File(System.getProperty("user.home"))
            val pluginDir = PluginManager.getPluginByClass(VeriClassTtyConnector::class.java)?.pluginPath
            val connector = VeriClassTtyConnector(
                shell = ShellLocator.locate(pluginDir),
                policy = TerminalPolicy(
                    dto.allow.map { it.lowercase() }.toSet(), dto.scripts, dto.blocked_hint?.takeIf { it.isNotBlank() },
                ),
                projectDir = projectDir,
                projectName = project.name,
                stateDir = Files.createTempDirectory("vericlass-terminal").toFile(),
                onPaste = { text -> session.onPaste("terminal", text) },
                onRecord = session.trace::terminal,
            )
            Disposer.register(scope) { connector.close() }
            val widget = JBTerminalWidget(project, JBTerminalSystemSettingsProviderBase(), scope)
            widget.start(connector)
            add(widget, BorderLayout.CENTER)
        } catch (e: Exception) {
            thisLogger().warn("VeriClass terminal failed to start", e)
            message("The VeriClass terminal couldn't start: ${e.message}")
        }
    }

    private fun message(text: String) {
        add(
            JBLabel(text, SwingConstants.CENTER).apply { border = JBUI.Borders.empty(16) },
            BorderLayout.CENTER,
        )
    }

    override fun dispose() {
        terminalScope = null
    }
}
