package edu.jce.vericlass.trace

import com.google.gson.Gson
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import java.io.File
import java.io.Writer
import java.nio.charset.StandardCharsets
import java.time.Instant
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * The student's own copy of everything this session sent (or tried to send):
 * terminal lines with their full output, proctor events, pastes, and the chat.
 * One JSON object per line in [file], so it survives an IDE restart and keeps
 * growing for the same session.
 *
 * Every row is signed in a chain with the session's trace key — the exact
 * scheme backend/trace.py checks:
 *
 *     mac_n = HMAC-SHA256(key, mac_{n-1} \n seq \n client_id \n at_utc \n session_id \n kind \n payload)
 *
 * [exportCsv] writes the CSV the student hands in when something didn't reach
 * the teacher; the dashboard verifies it and can import the missing rows.
 * Delivery acks are separate lines and are not signed (the server knows what
 * it received).
 */
class TraceJournal(
    private val file: File,
    private val key: String,
    private val sessionId: String,
) {
    data class Row(
        val seq: Long,
        val clientId: String,
        val atUtc: String,
        val atLocal: String,
        val kind: String,
        val payload: String,
        val mac: String,
    )

    private val gson = Gson()
    private val rows = mutableListOf<Row>()
    /** client_id → "yes" | "rejected"; missing means not delivered (yet). */
    private val delivery = mutableMapOf<String, String>()
    private var lastSeq = 0L
    private var lastMac = ""

    init {
        file.parentFile?.mkdirs()
        if (file.isFile) load()
    }

    private fun load() {
        file.forEachLine(StandardCharsets.UTF_8) { line ->
            if (line.isBlank()) return@forEachLine
            val o = runCatching { JsonParser.parseString(line).asJsonObject }.getOrNull() ?: return@forEachLine
            when (o.str("t")) {
                "row" -> {
                    val r = Row(
                        o.get("seq")?.asLong ?: 0L, o.str("client_id"), o.str("at_utc"), o.str("at_local"),
                        o.str("kind"), o.str("payload"), o.str("mac"),
                    )
                    rows += r
                    lastSeq = r.seq
                    lastMac = r.mac
                }
                "ack" -> delivery[o.str("client_id")] = o.str("status")
            }
        }
    }

    @Synchronized
    fun append(kind: String, clientId: String, payload: String, at: Instant = Instant.now()): Row {
        val seq = lastSeq + 1
        val atUtc = UTC.format(at)
        val mac = mac(key, lastMac, seq.toString(), clientId, atUtc, sessionId, kind, payload)
        val row = Row(seq, clientId, atUtc, LOCAL.format(at), kind, payload, mac)
        write(
            mapOf(
                "t" to "row", "seq" to seq, "client_id" to clientId, "at_utc" to atUtc,
                "at_local" to row.atLocal, "kind" to kind, "payload" to payload, "mac" to mac,
            ),
        )
        rows += row
        lastSeq = seq
        lastMac = mac
        return row
    }

    @Synchronized
    fun ack(clientId: String, status: String) {
        if (delivery[clientId] == status) return
        delivery[clientId] = status
        write(mapOf("t" to "ack", "client_id" to clientId, "status" to status))
    }

    @Synchronized
    fun rowCount(): Int = rows.size

    /**
     * Write every row of this session as CSV (UTF-8 with a BOM so Excel shows
     * Hebrew correctly), ending with a signed `export_end` row. [student] only
     * fills a readable column.
     */
    @Synchronized
    fun exportCsv(out: Writer, student: String) {
        append("export_end", "end-${lastSeq + 1}", gson.toJson(mapOf("rows" to rows.size)))
        out.write("﻿")
        out.write(csvLine(COLUMNS))
        for (r in rows) {
            val p = runCatching { JsonParser.parseString(r.payload).asJsonObject }.getOrNull() ?: JsonObject()
            val readable = readable(r.kind, p)
            val delivered = if (r.kind == "export_end") "" else delivery[r.clientId] ?: "no"
            out.write(
                csvLine(
                    listOf(
                        r.seq.toString(), r.atUtc, r.atLocal, sessionId, student, r.kind,
                        readable.where, readable.text, readable.output, readable.exitCode,
                        delivered, r.clientId, r.payload, r.mac,
                    ),
                ),
            )
        }
        out.flush()
    }

    private data class Readable(val where: String = "", val text: String = "", val output: String = "", val exitCode: String = "")

    private fun readable(kind: String, p: JsonObject): Readable = when (kind) {
        "terminal" -> Readable(
            where = p.str("cwd"),
            text = p.str("line") + if (p.get("allowed")?.asBoolean == false) "   [refused: ${p.str("reason")}]" else "",
            output = p.str("output"),
            exitCode = p.get("exit_code")?.takeIf { !it.isJsonNull }?.asString ?: "",
        )
        "proctor" -> Readable(where = "exam", text = listOf(p.str("kind"), p.str("detail")).filter { it.isNotEmpty() }.joinToString(": "))
        "paste" -> Readable(
            where = listOf(p.str("target"), p.str("file")).filter { it.isNotEmpty() }.joinToString(" · ") +
                " · from " + p.str("source"),
            text = p.str("text"),
        )
        "chat_user" -> Readable(where = "chat (student)", text = p.str("text"))
        "chat_tutor" -> Readable(where = "chat (tutor)", text = p.str("text"))
        "export_end" -> Readable(text = "end of export · ${p.get("rows")?.asInt ?: 0} rows")
        else -> Readable()
    }

    private fun write(obj: Map<String, Any?>) {
        file.appendText(gson.toJson(obj) + "\n", StandardCharsets.UTF_8)
    }

    companion object {
        /** Must match backend/trace.py COLUMNS. */
        val COLUMNS = listOf(
            "seq", "at_utc", "at_local", "session_id", "student", "kind", "where",
            "text", "output", "exit_code", "delivered", "client_id", "payload", "mac",
        )

        /** Same format as the backend's CURRENT_TIMESTAMP, so client_at sorts with created_at. */
        val UTC: DateTimeFormatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss").withZone(ZoneOffset.UTC)
        private val LOCAL: DateTimeFormatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss").withZone(ZoneId.systemDefault())

        fun mac(key: String, prev: String, seq: String, clientId: String, atUtc: String, sessionId: String, kind: String, payload: String): String {
            val h = Mac.getInstance("HmacSHA256")
            h.init(SecretKeySpec(key.toByteArray(StandardCharsets.UTF_8), "HmacSHA256"))
            val msg = listOf(prev, seq, clientId, atUtc, sessionId, kind, payload).joinToString("\n")
            return h.doFinal(msg.toByteArray(StandardCharsets.UTF_8)).joinToString("") { "%02x".format(it) }
        }

        /** RFC 4180: every field quoted, quotes doubled, CRLF line ends. */
        fun csvLine(fields: List<String>): String =
            fields.joinToString(",") { "\"" + it.replace("\"", "\"\"") + "\"" } + "\r\n"

        private fun JsonObject.str(name: String): String =
            get(name)?.takeIf { !it.isJsonNull }?.let { if (it.isJsonPrimitive) it.asString else it.toString() } ?: ""
    }
}
