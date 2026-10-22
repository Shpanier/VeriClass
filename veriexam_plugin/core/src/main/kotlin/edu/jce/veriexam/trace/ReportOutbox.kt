package edu.jce.veriexam.trace

import com.intellij.openapi.diagnostic.thisLogger
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

/**
 * Sends reports to the backend in order on one background thread, and keeps
 * retrying the one at the head while the server can't be reached (network or
 * tunnel down, backend restarting) — so a dropped connection delays reports
 * instead of losing them. A report the server refuses outright (4xx other than
 * 408/429: a bug, an unknown session) is dropped after one try.
 *
 * Retries are safe: every report carries a client_id the backend stores once.
 * What is still queued when the session ends is in the [TraceJournal], which
 * the student can export.
 *
 * [post] returns the HTTP status or throws on a network error;
 * [onDone] gets (item, delivered) for each finished item, on the worker thread.
 */
class ReportOutbox(
    private val post: (path: String, body: Map<String, Any?>) -> Int,
    private val onDone: (Item, Boolean) -> Unit,
) {
    data class Item(val path: String, val body: Map<String, Any?>, val ackId: String)

    private val queue = LinkedBlockingQueue<Item>()
    private val stopped = AtomicBoolean(false)
    private val inFlight = AtomicInteger(0)
    private val worker = Thread(::run, "veriexam-outbox").apply { isDaemon = true; start() }

    /** Reports waiting to go out, including the one being retried. */
    val pending: Int get() = queue.size + inFlight.get()

    fun send(item: Item) {
        if (!stopped.get()) queue.put(item)
    }

    /** Stop sending. Whatever is left stays in the journal. */
    fun stop() {
        stopped.set(true)
        worker.interrupt()
    }

    private fun run() {
        try {
            while (!stopped.get()) {
                val item = queue.poll(1, TimeUnit.SECONDS) ?: continue
                inFlight.set(1)
                deliver(item)
                inFlight.set(0)
            }
        } catch (_: InterruptedException) {
            // stop()
        }
    }

    private fun deliver(item: Item) {
        var backoffMs = FIRST_BACKOFF_MS
        while (!stopped.get()) {
            val status = try {
                post(item.path, item.body)
            } catch (e: Exception) {
                thisLogger().debug("report to ${item.path} failed; will retry", e)
                -1
            }
            when {
                status in 200..299 -> return onDone(item, true)
                status in 400..499 && status != 408 && status != 429 -> {
                    thisLogger().warn("report to ${item.path} refused (HTTP $status); not retrying")
                    return onDone(item, false)
                }
            }
            Thread.sleep(backoffMs)
            backoffMs = (backoffMs * 2).coerceAtMost(MAX_BACKOFF_MS)
        }
    }

    companion object {
        private const val FIRST_BACKOFF_MS = 1_000L
        private const val MAX_BACKOFF_MS = 30_000L
    }
}
