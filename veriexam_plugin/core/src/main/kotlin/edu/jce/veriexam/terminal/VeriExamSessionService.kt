package edu.jce.veriexam.terminal

import com.intellij.openapi.Disposable
import com.intellij.openapi.components.Service
import com.intellij.openapi.components.service
import com.intellij.openapi.project.Project
import com.intellij.openapi.util.Disposer
import edu.jce.veriexam.api.ClientConfig
import edu.jce.veriexam.api.Exercise
import edu.jce.veriexam.api.VeriExamApiClient
import edu.jce.veriexam.trace.SessionTrace
import java.util.concurrent.CopyOnWriteArrayList

/**
 * Hands the logged-in session from the VeriExam tool window (right) to the
 * VeriExam Terminal tool window (bottom). The login panel publishes on login and
 * publishes null when the session is torn down (re-login, project close); the
 * terminal starts and stops with it. All calls on the EDT.
 */
@Service(Service.Level.PROJECT)
class VeriExamSessionService {

    data class Active(
        val api: VeriExamApiClient,
        val token: String,
        val sessionId: String,
        val exercise: Exercise,
        val config: ClientConfig,
        /** Journal + outbox: everything this session reports goes through it. */
        val trace: SessionTrace,
        /** Exam mode: a paste into a VeriExam component ("terminal" | "chat") and its text. */
        val onPaste: (target: String, text: String) -> Unit = { _, _ -> },
    )

    var active: Active? = null
        private set

    private val listeners = CopyOnWriteArrayList<(Active?) -> Unit>()

    fun publish(session: Active?) {
        active = session
        listeners.forEach { it(session) }
    }

    /** Calls [listener] now with the current session, then on every change until [parent] is disposed. */
    fun subscribe(parent: Disposable, listener: (Active?) -> Unit) {
        listeners += listener
        Disposer.register(parent) { listeners -= listener }
        listener(active)
    }

    companion object {
        fun getInstance(project: Project): VeriExamSessionService = project.service()
    }
}
