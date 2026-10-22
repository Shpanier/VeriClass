package edu.jce.veriexam.trace

import com.google.gson.GsonBuilder
import com.intellij.openapi.Disposable
import com.intellij.openapi.diagnostic.thisLogger
import com.intellij.openapi.util.Disposer
import edu.jce.veriexam.api.VeriExamApiClient
import edu.jce.veriexam.terminal.TerminalRecord
import java.io.File
import java.io.Writer
import java.time.Instant
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger

/**
 * Everything one session reports goes through here: it is written to the
 * student's local [TraceJournal] first, then queued in the [ReportOutbox] for
 * the backend. So nothing is lost when the network drops — it arrives late, or
 * it is in the student's export.
 *
 * Terminal output is sent in full, in pieces of [CHUNK_CHARS] (the command row
 * keeps only the tail, as before). Thread-safe; call from any thread.
 */
class SessionTrace(
    private val api: VeriExamApiClient,
    private val token: String,
    val sessionId: String,
    val student: String,
    traceKey: String,
    parent: Disposable,
) : Disposable {

    private val gson = GsonBuilder().disableHtmlEscaping().create()
    val journal = TraceJournal(File(TRACE_DIR, "$sessionId.jsonl"), traceKey, sessionId)
    // A terminal line is several outbox items (the line + its output pieces);
    // it counts as delivered once all of them are.
    private val remaining = ConcurrentHashMap<String, AtomicInteger>()
    private val rejected = ConcurrentHashMap.newKeySet<String>()
    private val outbox = ReportOutbox(
        post = { path, body -> api.postReport(path, body, token) },
        onDone = ::done,
    )

    init {
        Disposer.register(parent, this)
        if (traceKey.isEmpty()) thisLogger().warn("backend sent no trace key; the export can't be verified")
    }

    /** Reports not yet accepted by the backend. */
    val pending: Int get() = outbox.pending

    fun terminal(rec: TerminalRecord) {
        val id = newId()
        val at = Instant.now()
        val output = rec.output.orEmpty()
        val pieces = output.chunked(CHUNK_CHARS).take(MAX_CHUNKS)
        val body = linkedMapOf<String, Any?>(
            "session_id" to sessionId,
            "line" to rec.line,
            "cwd" to rec.cwd,
            "allowed" to rec.allowed,
            "reason" to rec.reason,
            "commands" to rec.commands,
            "syntax_error" to rec.syntaxError,
            "exit_code" to rec.exitCode,
            "duration_ms" to rec.durationMs,
            "output_tail" to rec.outputTail,
            "output_chars" to output.length.takeIf { it > 0 },
            "output_chunks" to pieces.size.takeIf { it > 0 },
            "client_id" to id,
            "client_at" to TraceJournal.UTC.format(at),
            // Which OS and shell ran it: the same line can behave differently on each.
            "client_os" to CLIENT_OS,
            "shell" to rec.shell,
        )
        journal.append("terminal", id, gson.toJson(body + ("output" to output)), at)
        remaining[id] = AtomicInteger(1 + pieces.size)
        outbox.send(ReportOutbox.Item("/api/terminal/command", body, id))
        pieces.forEachIndexed { i, text ->
            outbox.send(
                ReportOutbox.Item(
                    "/api/terminal/output",
                    mapOf("session_id" to sessionId, "client_id" to id, "seq" to i, "text" to text),
                    id,
                ),
            )
        }
    }

    fun proctor(kind: String, detail: String?, awayMs: Long?) {
        val id = newId()
        val at = Instant.now()
        val body = linkedMapOf<String, Any?>(
            "session_id" to sessionId,
            "kind" to kind,
            "detail" to detail?.takeIf { it.isNotBlank() },
            "away_ms" to awayMs,
            "client_id" to id,
            "client_at" to TraceJournal.UTC.format(at),
        )
        journal.append("proctor", id, gson.toJson(body), at)
        outbox.send(ReportOutbox.Item("/api/proctor/event", body, id))
    }

    /** [target]: editor | terminal | chat. [source]: outside | ide | tutor (see PasteSources). */
    fun paste(target: String, source: String, text: String, file: String?) {
        val id = newId()
        val at = Instant.now()
        val body = linkedMapOf<String, Any?>(
            "session_id" to sessionId,
            "target" to target,
            "source" to source,
            "text" to text.take(MAX_PASTE_CHARS),
            "file" to file,
            "client_id" to id,
            "client_at" to TraceJournal.UTC.format(at),
        )
        journal.append("paste", id, gson.toJson(body), at)
        outbox.send(ReportOutbox.Item("/api/proctor/paste", body, id))
    }

    /**
     * Journal only — the chat itself goes to the backend through /api/ask.
     * [delivered]: the server stored it (a reply that streamed back always was).
     */
    fun chat(fromStudent: Boolean, text: String, delivered: Boolean) {
        val id = newId()
        journal.append(if (fromStudent) "chat_user" else "chat_tutor", id, gson.toJson(mapOf("text" to text)))
        journal.ack(id, if (delivered) "yes" else "no")
    }

    fun exportCsv(out: Writer) = journal.exportCsv(out, student)

    private fun done(item: ReportOutbox.Item, delivered: Boolean) {
        if (!delivered) {
            rejected += item.ackId
            remaining.remove(item.ackId)
            journal.ack(item.ackId, "rejected")
            return
        }
        if (item.ackId in rejected) return
        val left = remaining[item.ackId]
        if (left == null || left.decrementAndGet() <= 0) {
            remaining.remove(item.ackId)
            journal.ack(item.ackId, "yes")
        }
    }

    override fun dispose() = outbox.stop()

    companion object {
        /** Must match backend routes/terminal.py _CHUNK_MAX / _CHUNKS_MAX. */
        const val CHUNK_CHARS = 16_000
        const val MAX_CHUNKS = 256
        private const val MAX_PASTE_CHARS = 20_000

        /** ~/.veriexam/trace — one journal per session. */
        val TRACE_DIR = File(System.getProperty("user.home"), ".veriexam/trace")

        /** e.g. "Windows 11 amd64", "Mac OS X aarch64". */
        val CLIENT_OS = "${System.getProperty("os.name")} ${System.getProperty("os.arch")}"

        private fun newId() = UUID.randomUUID().toString()
    }
}
