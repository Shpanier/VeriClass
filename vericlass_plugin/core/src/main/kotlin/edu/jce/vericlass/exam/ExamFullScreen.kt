package edu.jce.vericlass.exam

import com.intellij.openapi.diagnostic.thisLogger
import com.intellij.openapi.project.Project
import com.intellij.openapi.wm.WindowManager

/**
 * Best-effort full-screen control for the IDE frame.
 *
 * Implemented with reflection on purpose. The platform full-screen API
 * (`IdeFrameEx.isInFullScreen` / `toggleFullScreen`) is the one piece most
 * likely to differ between IDE SDK versions, and a wrong compile-time
 * reference would break the whole plugin build. Going through reflection means
 * the plugin compiles against any SDK; if the methods aren't present at runtime
 * we simply don't full-screen, and the rest of exam mode — the leave-the-IDE
 * detection and reporting, which the instructor actually relies on — is
 * completely independent of this and keeps working.
 *
 * All methods must be called on the EDT.
 */
object ExamFullScreen {

    private fun ideFrame(project: Project): Any? =
        WindowManager.getInstance().getIdeFrame(project)

    fun isFullScreen(project: Project): Boolean {
        val frame = ideFrame(project) ?: return false
        return try {
            frame.javaClass.getMethod("isInFullScreen").invoke(frame) as? Boolean ?: false
        } catch (t: Throwable) {
            thisLogger().info("full-screen state unavailable on this platform", t)
            false
        }
    }

    /** Enter full screen if supported and not already there. */
    fun enter(project: Project) {
        val frame = ideFrame(project) ?: return
        try {
            val already = try {
                frame.javaClass.getMethod("isInFullScreen").invoke(frame) as? Boolean ?: false
            } catch (t: Throwable) {
                false
            }
            if (already) return
            frame.javaClass
                .getMethod("toggleFullScreen", Boolean::class.javaPrimitiveType)
                .invoke(frame, true)
        } catch (t: Throwable) {
            thisLogger().info("could not enter full screen on this platform", t)
        }
    }
}
