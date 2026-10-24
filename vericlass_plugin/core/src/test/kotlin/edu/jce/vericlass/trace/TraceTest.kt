package edu.jce.vericlass.trace

import edu.jce.vericlass.exam.PasteSources
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.StringWriter
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

class TraceTest {

    @get:Rule
    val tmp = TemporaryFolder()

    @Test
    fun `signature matches the backend's`() {
        // backend.trace.row_mac('k3y', '', '1', 'cid-1', '2026-10-22 09:00:00', 'sess-1', 'chat_user', '{"text":"שלום, world"}')
        assertEquals(
            "29652f5b2f898c7b7b3087e526142df5041fa615e91fd5a83d70ebae8d5c6fcd",
            TraceJournal.mac("k3y", "", "1", "cid-1", "2026-10-22 09:00:00", "sess-1", "chat_user", "{\"text\":\"שלום, world\"}"),
        )
    }

    @Test
    fun `journal survives a restart and keeps the chain`() {
        val file = tmp.newFile("s.jsonl")
        val a = TraceJournal(file, "key", "sess")
        val first = a.append("chat_user", "c1", "{\"text\":\"hi\"}")
        a.ack("c1", "yes")
        val b = TraceJournal(file, "key", "sess")
        val second = b.append("proctor", "p1", "{\"kind\":\"focus_lost\"}")
        assertEquals(2L, second.seq)
        assertEquals(
            TraceJournal.mac("key", first.mac, "2", "p1", second.atUtc, "sess", "proctor", "{\"kind\":\"focus_lost\"}"),
            second.mac,
        )
        val out = StringWriter()
        b.exportCsv(out, "Noa")
        val lines = out.toString().removePrefix("﻿").trimEnd().split("\r\n")
        assertEquals(TraceJournal.COLUMNS.joinToString(",") { "\"$it\"" }, lines[0])
        assertEquals(4, lines.size) // header, 2 rows, export_end
        assertTrue(lines[1].contains("\"yes\"")) // the chat line was delivered
        assertTrue(lines[2].contains("\"no\"")) // the proctor event never was
        assertTrue(lines[3].contains("\"export_end\""))
    }

    @Test
    fun `csv quotes commas, quotes and newlines`() {
        assertEquals("\"a,b\",\"say \"\"hi\"\"\",\"x\ny\"\r\n", TraceJournal.csvLine(listOf("a,b", "say \"hi\"", "x\ny")))
    }

    @Test
    fun `outbox retries until the server is back, in order`() {
        val calls = AtomicInteger()
        val delivered = CopyOnWriteArrayList<String>()
        val done = CountDownLatch(2)
        val box = ReportOutbox(
            post = { _, body ->
                // Network down for the first two tries, then the server answers.
                if (calls.incrementAndGet() <= 2) throw java.io.IOException("connection refused")
                200
            },
            onDone = { item, ok -> if (ok) delivered += item.ackId; done.countDown() },
        )
        box.send(ReportOutbox.Item("/a", emptyMap(), "first"))
        box.send(ReportOutbox.Item("/a", emptyMap(), "second"))
        assertTrue(done.await(15, TimeUnit.SECONDS))
        assertEquals(listOf("first", "second"), delivered)
        assertEquals(0, box.pending)
        box.stop()
    }

    @Test
    fun `outbox drops what the server refuses`() {
        val done = CountDownLatch(1)
        var ok = true
        val box = ReportOutbox(post = { _, _ -> 422 }, onDone = { _, d -> ok = d; done.countDown() })
        box.send(ReportOutbox.Item("/a", emptyMap(), "x"))
        assertTrue(done.await(5, TimeUnit.SECONDS))
        assertFalse(ok)
        box.stop()
    }

    @Test
    fun `paste sources`() {
        PasteSources.noteCopy("def f():\n    return 1", "tutor")
        PasteSources.noteCopy("def f():\n    return 1", "ide") // the IDE clipboard echo keeps "tutor"
        assertEquals("tutor", PasteSources.classify("def f():\n        return 1")) // re-indented
        PasteSources.noteCopy("x = 2", "ide")
        assertEquals("ide", PasteSources.classify("x = 2"))
        PasteSources.noteOutside("import os")
        PasteSources.noteCopy("import os", "ide")
        assertEquals("outside", PasteSources.classify("import os"))
        assertEquals("outside", PasteSources.classify("never seen before"))
    }
}
