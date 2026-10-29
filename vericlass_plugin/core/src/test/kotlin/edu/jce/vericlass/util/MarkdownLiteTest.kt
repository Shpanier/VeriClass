package edu.jce.vericlass.util

import org.junit.Assert.assertEquals
import org.junit.Test

class MarkdownLiteTest {

    @Test
    fun `chat messages keep the lines the student typed`() {
        assertEquals("<p>line one<br>line two</p><p>new paragraph</p>",
            MarkdownLite.toHtml("line one\nline two\n\nnew paragraph", hardBreaks = true))
    }

    @Test
    fun `the brief joins wrapped lines as Markdown does`() {
        assertEquals("<p>line one line two</p>", MarkdownLite.toHtml("line one\nline two"))
    }

    @Test
    fun `the server's italic notes are italic, snake_case names are not`() {
        assertEquals("<p>🧑‍🏫 <i>המרצה בודק את השאלה שלכם — רגע…</i></p>",
            MarkdownLite.toHtml("🧑‍🏫 _המרצה בודק את השאלה שלכם — רגע…_"))
        assertEquals("<p>set resume_minutes and chat_history, or <code>_private_</code> and __init__</p>",
            MarkdownLite.toHtml("set resume_minutes and chat_history, or `_private_` and __init__"))
    }
}
