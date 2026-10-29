package edu.jce.vericlass.lab

import com.intellij.openapi.diagnostic.Logger
import edu.jce.vericlass.api.ClassifyResponse
import edu.jce.vericlass.api.DetectResponse
import edu.jce.vericlass.api.FinishResponse
import edu.jce.vericlass.api.OpenReview
import edu.jce.vericlass.api.Probe
import edu.jce.vericlass.api.ProbeAnswerResponse
import edu.jce.vericlass.api.StepStateResponse
import edu.jce.vericlass.api.TranscriptResponse
import edu.jce.vericlass.api.VeriClassApiClient

/**
 * The server, as [LabFlow] uses it, for one session. Every call blocks. A call
 * that fails returns null (or nothing), so a server without some feature
 * behaves as before it; only [answerProbe] throws, so the student is told.
 */
interface LabBackend {
    fun stepState(): StepStateResponse?
    fun finishStep(step: Int, output: String): FinishResponse?
    fun detectOutput(text: String): DetectResponse?
    fun pendingProbes(): List<Probe>
    fun classify(text: String): ClassifyResponse?

    /** Throws [edu.jce.vericlass.api.ProbeClosedException] when the question is no longer open. */
    fun answerProbe(probeId: Int, answer: String): ProbeAnswerResponse

    /** [othersOnly]: leave out what this chat wrote. */
    fun transcript(after: Int, othersOnly: Boolean): TranscriptResponse?
    fun record(entries: List<Map<String, Any?>>)
    fun openReviews(): List<OpenReview>
}

/** [LabBackend] over the HTTP client. [client]: this chat's id in the transcript. */
class ApiLabBackend(
    private val api: VeriClassApiClient,
    private val token: String,
    private val sessionId: String,
    private val client: String,
) : LabBackend {

    override fun stepState() = quiet { api.stepState(sessionId, token) }
    override fun finishStep(step: Int, output: String) = quiet { api.finishStep(sessionId, step, output, token) }
    override fun detectOutput(text: String) = quiet { api.detectOutput(sessionId, text, token) }
    override fun pendingProbes() = quiet { api.pendingProbes(sessionId, token) } ?: emptyList()
    override fun classify(text: String) = quiet { api.classifyAnswer(sessionId, text, token) }
    override fun answerProbe(probeId: Int, answer: String) = api.answerProbe(probeId, answer, token)
    override fun transcript(after: Int, othersOnly: Boolean) =
        quiet { api.transcript(sessionId, token, after, client.takeIf { othersOnly }) }
    override fun record(entries: List<Map<String, Any?>>) {
        api.recordTranscript(sessionId, token, client, entries)
    }
    override fun openReviews() = quiet { api.openReviews(sessionId, token) } ?: emptyList()

    private fun <T> quiet(call: () -> T): T? = try {
        call()
    } catch (e: Exception) {
        LOG.debug("lab call failed", e)
        null
    }

    companion object {
        private val LOG = Logger.getInstance(ApiLabBackend::class.java)
    }
}
