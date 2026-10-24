package edu.jce.vericlass.ide

import com.intellij.execution.impl.ConsoleViewImpl
import com.intellij.execution.ui.RunContentManager
import com.intellij.openapi.diagnostic.thisLogger
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.fileEditor.FileEditorManager
import com.intellij.openapi.project.Project

/** What the student is sending to the teacher. */
data class Submission(
    val filename: String,
    val source: String,
    val console: String,
) {
    val isEmpty: Boolean get() = source.isBlank() && console.isBlank()
}

/**
 * Gathers the student's current work for a "Send to teacher" submission: the
 * source of the active editor plus the text of the selected Run console.
 *
 * MUST be called on the EDT — it touches the editor manager and console editor,
 * and the EDT holds implicit read access so document reads need no read action.
 * Console capture is best-effort: if nothing has been run (or the console API
 * shifts), it returns an empty string rather than failing the whole submission.
 */
object SubmissionCollector {

    fun collect(project: Project): Submission {
        val editor = FileEditorManager.getInstance(project).selectedTextEditor
        val source = editor?.document?.text ?: ""
        val filename = editor?.document
            ?.let { FileDocumentManager.getInstance().getFile(it)?.name }
            ?: ""
        return Submission(filename = filename, source = source, console = readConsole(project))
    }

    private fun readConsole(project: Project): String {
        return try {
            val console = RunContentManager.getInstance(project).selectedContent?.executionConsole
            if (console is ConsoleViewImpl) {
                console.flushDeferredText() // move buffered output into the console's editor
                console.editor?.document?.text ?: ""
            } else {
                ""
            }
        } catch (e: Exception) {
            thisLogger().debug("console capture failed", e)
            ""
        }
    }
}
