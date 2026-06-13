package edu.jce.oslab.probe

import com.intellij.openapi.Disposable
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.diagnostic.thisLogger
import com.intellij.openapi.ui.Messages
import com.intellij.openapi.util.Disposer
import com.intellij.util.concurrency.AppExecutorUtil
import edu.jce.oslab.api.OsLabApiClient
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Polls GET /api/probes/pending/{session} on a background scheduler. When a new
 * probe appears it pops a modal input on the EDT (the IDE equivalent of
 * Chainlit's AskUserMessage), submits the answer, and shows the auto-grade.
 *
 * Mirrors the Chainlit poll loop: every [pollIntervalMs], dedupe by probe id.
 * Stops when its parent [Disposable] is disposed (tool window closed).
 */
class ProbePoller(
    private val api: OsLabApiClient,
    private val sessionId: String,
    private val pollIntervalMs: Long,
    parent: Disposable,
) : Disposable {

    private val handled = java.util.Collections.synchronizedSet(HashSet<Int>())
    private val stopped = AtomicBoolean(false)
    private val scheduler = AppExecutorUtil.getAppScheduledExecutorService()
    private var future: ScheduledFuture<*>? = null

    init {
        Disposer.register(parent, this)
        future = scheduler.scheduleWithFixedDelay(
            ::pollOnce,
            pollIntervalMs,
            pollIntervalMs.coerceAtLeast(500),
            TimeUnit.MILLISECONDS,
        )
    }

    private fun pollOnce() {
        if (stopped.get()) return
        val probes = try {
            api.pendingProbes(sessionId)
        } catch (e: Exception) {
            thisLogger().debug("probe poll failed", e)
            return
        }
        for (probe in probes) {
            if (!handled.add(probe.id)) continue
            ApplicationManager.getApplication().invokeLater { presentProbe(probe.id, probe.body) }
        }
    }

    /** EDT. */
    private fun presentProbe(probeId: Int, body: String) {
        if (stopped.get()) return
        val answer = Messages.showInputDialog(
            "Your instructor is asking you:\n\n$body\n\nType your answer:",
            "OS Lab — Comprehension Check",
            Messages.getQuestionIcon(),
        )?.trim()
        if (answer.isNullOrEmpty()) {
            // Re-arm so an unanswered probe is offered again on the next poll.
            handled.remove(probeId)
            return
        }
        ApplicationManager.getApplication().executeOnPooledThread {
            val result = try {
                api.answerProbe(probeId, answer)
            } catch (e: Exception) {
                ApplicationManager.getApplication().invokeLater {
                    Messages.showErrorDialog(
                        "Could not submit your answer: ${e.message}",
                        "OS Lab",
                    )
                }
                return@executeOnPooledThread
            }
            ApplicationManager.getApplication().invokeLater {
                Messages.showInfoMessage(
                    "Answer submitted. Auto-grade: ${result.auto_grade}/2\n\n${result.why}",
                    "OS Lab — Comprehension Check",
                )
            }
        }
    }

    override fun dispose() {
        // Order matters: flag first so an in-flight pollOnce/presentProbe bails,
        // then cancel the recurring task so it's reclaimed from the shared
        // application-lifetime scheduler (cancel(false) lets any running tick
        // finish). Without this the periodic task would linger for the IDE's life.
        stopped.set(true)
        future?.cancel(false)
    }
}
