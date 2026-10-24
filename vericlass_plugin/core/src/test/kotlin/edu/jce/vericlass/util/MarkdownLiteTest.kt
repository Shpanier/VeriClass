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
}
