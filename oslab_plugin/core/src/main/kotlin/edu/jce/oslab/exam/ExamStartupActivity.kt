package edu.jce.oslab.exam

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.project.Project
import com.intellij.openapi.startup.ProjectActivity
import com.intellij.openapi.wm.ToolWindowManager
import edu.jce.oslab.api.OsLabApiClient

/**
 * On project open, ask the backend whether exam mode is active. If so, bring the
 * VeriExam tutor tool window to the front and (when configured) put the IDE in full
 * screen straight away — so the student lands in the exam with the tutor chat
 * visible and nothing else inviting a click. The actual leave-the-IDE
 * monitoring arms once the student logs in inside that tool window (see
 * [ExamGuard]).
 *
 * No-op in plain chat/ide mode, and silently tolerant if the backend is
 * unreachable, so normal course use and offline launches are unaffected.
 */
class ExamStartupActivity : ProjectActivity {

    override suspend fun execute(project: Project) {
        // Runs on a background coroutine; the blocking HTTP call is fine here.
        val config = OsLabApiClient().clientConfig() // tolerant: chat default on any failure
        if (!config.isExamMode) return

        ApplicationManager.getApplication().invokeLater {
            if (project.isDisposed) return@invokeLater
            ToolWindowManager.getInstance(project).getToolWindow("VeriExam")?.activate(null)
            if (config.force_fullscreen) ExamFullScreen.enter(project)
        }
    }
}
