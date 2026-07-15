package edu.jce.oslab.util

import com.intellij.openapi.util.text.StringUtil

/** Small formatting helpers shared by the briefing, checklist, and scaffolder. */
object Format {

    /**
     * Render a JSON-parsed value for humans. Gson decodes every JSON number as
     * a Double, so integral values like 100.0 are shown as "100", and lists as
     * "[+, -, *]".
     */
    fun value(v: Any?): String = when (v) {
        null -> "null"
        is Double -> if (v == v.toLong().toDouble()) v.toLong().toString() else v.toString()
        is List<*> -> v.joinToString(", ", "[", "]") { value(it) }
        is Map<*, *> -> v.entries.joinToString(", ", "{", "}") { "${it.key}: ${value(it.value)}" }
        else -> v.toString()
    }

    /**
     * Human-friendly rendering of a variant param value for the briefing's
     * labeled list: booleans as yes/no, lists comma-joined without brackets.
     */
    fun paramValue(v: Any?): String = when (v) {
        is Boolean -> if (v) "yes" else "no"
        is List<*> -> v.joinToString(", ") { value(it) }
        else -> value(v)
    }

    /** "max_number" -> "Max number" — the fallback label when none is authored. */
    fun prettifyKey(key: String): String =
        key.replace('_', ' ').replace('-', ' ').trim()
            .replaceFirstChar { if (it.isLowerCase()) it.titlecase() else it.toString() }

    /** Escape text for safe inclusion in the HTML we feed to Swing JLabels/JTextPanes. */
    fun html(s: String): String = StringUtil.escapeXmlEntities(s)
}
