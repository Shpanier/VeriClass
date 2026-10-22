package edu.jce.veriexam.exam

import java.security.MessageDigest

/**
 * Where pasted text came from, as far as the IDE can tell:
 *
 *   tutor    copied with a code block's Copy button in the VeriExam chat
 *   ide      copied or cut inside the IDE during the exam
 *   outside  anything else: changed while the student was in another app,
 *            already on the clipboard when the exam started, or put there by
 *            something the IDE didn't see
 *
 * Text is compared with all whitespace removed, because the editor re-indents
 * what is pasted. Only hashes are kept. A best-effort signal for the teacher,
 * not proof: the pasted text itself is logged alongside it.
 */
object PasteSources {

    private const val KEEP = 500
    private val seen = object : LinkedHashMap<String, String>(64, 0.75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, String>) = size > KEEP
    }

    @Synchronized
    fun noteCopy(text: String?, source: String) {
        if (text.isNullOrBlank()) return
        val h = hash(text)
        // The IDE also reports text it merely picked up from the system clipboard
        // (copied in another app), and the tutor's Copy button goes through it
        // too: an "ide" copy never replaces what we already know about a text.
        if (source == "ide" && seen.containsKey(h)) return
        seen[h] = source
    }

    /** The clipboard changed outside the IDE (seen when the student came back). */
    @Synchronized
    fun noteOutside(text: String?) {
        if (text.isNullOrBlank()) return
        seen[hash(text)] = "outside"
    }

    @Synchronized
    fun classify(text: String): String = seen[hash(text)] ?: "outside"

    private fun hash(text: String): String {
        val norm = text.filterNot { it.isWhitespace() }
        val d = MessageDigest.getInstance("SHA-256").digest(norm.toByteArray(Charsets.UTF_8))
        return d.joinToString("") { "%02x".format(it) }
    }
}
