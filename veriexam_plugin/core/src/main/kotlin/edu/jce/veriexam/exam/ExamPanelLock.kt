package edu.jce.veriexam.exam

import com.intellij.openapi.Disposable
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.application.ModalityState
import com.intellij.openapi.project.Project
import com.intellij.openapi.util.Disposer
import com.intellij.openapi.wm.ToolWindow
import com.intellij.openapi.wm.ToolWindowManager
import com.intellij.openapi.wm.ex.ToolWindowManagerListener
import edu.jce.veriexam.api.ClientConfig
import edu.jce.veriexam.terminal.VeriExamTerminalToolWindowFactory

/**
 * Exam mode: the only panels (tool windows) are the VeriExam chat, the VeriExam
 * Terminal and whatever the teacher added (EXAM_ALLOWED_TOOL_WINDOWS). Every
 * other one — Project, Git, Python Console, Run, the IDE's own Terminal, other
 * plugins — is hidden and its side-bar button removed. If something opens one
 * anyway (a shortcut, the View menu, running code) it is hidden again and
 * [onBlocked] gets it plus [how], which is read at that moment, while the
 * key press or click that opened it is still the current event.
 *
 * Disposing the lock gives the panels back, so a normal session afterwards has them.
 */
class ExamPanelLock(
    private val project: Project,
    private val allowed: Set<String>,
    private val how: () -> String,
    private val onBlocked: (toolWindow: ToolWindow, how: String) -> Unit,
    parent: Disposable,
) : Disposable {

    private val madeUnavailable = mutableSetOf<String>()

    init {
        Disposer.register(parent, this)
        madeUnavailable += hideAll(project, allowed)
        project.messageBus.connect(this).subscribe(
            ToolWindowManagerListener.TOPIC,
            object : ToolWindowManagerListener {
                override fun toolWindowShown(toolWindow: ToolWindow) {
                    if (toolWindow.id in allowed) return
                    val how = runCatching(how).getOrDefault("")
                    evenWhenModal {
                        if (project.isDisposed) return@evenWhenModal
                        hide(toolWindow)
                        madeUnavailable += toolWindow.id
                        onBlocked(toolWindow, how)
                    }
                }

                override fun toolWindowsRegistered(ids: List<String>, toolWindowManager: ToolWindowManager) {
                    val extra = ids.filter { it !in allowed }
                    if (extra.isEmpty()) return
                    evenWhenModal {
                        if (project.isDisposed) return@evenWhenModal
                        val twm = ToolWindowManager.getInstance(project)
                        extra.forEach { id -> twm.getToolWindow(id)?.let { hide(it); madeUnavailable += id } }
                    }
                }
            },
        )
    }

    /** EDT. Panels that are open right now but aren't allowed (normally none: they're closed at once). */
    fun visibleForbidden(): List<String> {
        val twm = ToolWindowManager.getInstance(project)
        return twm.toolWindowIds.filter { it !in allowed && twm.getToolWindow(it)?.isVisible == true }
    }

    override fun dispose() {
        val ids = madeUnavailable.toList()
        ApplicationManager.getApplication().invokeLater {
            if (project.isDisposed) return@invokeLater
            val twm = ToolWindowManager.getInstance(project)
            ids.forEach { twm.getToolWindow(it)?.isAvailable = true }
        }
    }

    companion object {
        /** The id the IDE's bundled terminal plugin registers its tool window under. */
        const val STOCK_TERMINAL_ID = "Terminal"

        fun allowedIds(config: ClientConfig): Set<String> =
            setOf("VeriExam", VeriExamTerminalToolWindowFactory.ID) + config.exam_allowed_tool_windows

        private fun hide(tw: ToolWindow) {
            tw.hide()
            tw.isAvailable = false
        }

        /** EDT. Hide every panel that isn't allowed, without reporting (also before the student logs in). */
        fun hideAll(project: Project, allowed: Set<String>): List<String> {
            val twm = ToolWindowManager.getInstance(project)
            return twm.toolWindowIds.filter { it !in allowed }.onEach { id -> twm.getToolWindow(id)?.let(::hide) }
        }
    }
}

/**
 * Run on the EDT even while a modal dialog (Settings, a probe) is open; the
 * default would wait until it closes, and the dashboard would miss that time.
 */
internal fun evenWhenModal(block: () -> Unit) =
    ApplicationManager.getApplication().invokeLater(block, ModalityState.any())
