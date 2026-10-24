package edu.jce.veriexam.ui

/**
 * Plain text rules (no model) for the chat box of a step-by-step lab. In
 * October 2026, 9 messages with answers were sent without "Done with step N"
 * and went to the tutor instead of the teacher, and 8 of 15 submissions in
 * another class were only the suggestion button's text, with no answers.
 */
object AnswerDetector {

    // The server's rules (backend/steps.py): "Done with step 2", "סיימנו שלב 2".
    private val DONE_EN = Regex("""\b(?:done|finished|completed)\b[^\n]{0,25}?\bstep\b\s*(\d+)?""", RegexOption.IGNORE_CASE)
    private val DONE_HE = Regex("""סיימ\S*\s+(?:את\s+)?שלב\s*(\d+)?""")
    private val ANSWER_WORDS = Regex(
        """התשובות שלי|התשובה שלי|התשובות שלנו|תשובות\s*:|my answers|our answers|answers\s*:""",
        RegexOption.IGNORE_CASE,
    )
    // "1. …", "2) …", "q3 - …" at the start of a line.
    private val NUMBERED_LINE = Regex("""^\s*(?:[qQ]\s*)?\d{1,2}\s*[.):\-–]""")
    // "q1 … q2 …", "סעיף 1 … סעיף 2", "שאלה 1 …" inside a line.
    private val INLINE_MARK = Regex("""(?:^|\s)(?:[qQ]\s*|סעיף\s*|שאלה\s*)(\d{1,2})\b""")
    private val HEBREW = Regex("[֐-׿]")

    fun isDone(text: String): Boolean = DONE_EN.containsMatchIn(text) || DONE_HE.containsMatchIn(text)

    /** A "Done with step N" message with nothing after it (just the button's text). */
    fun doneWithoutAnswers(text: String): Boolean {
        val m = DONE_EN.find(text) ?: DONE_HE.find(text) ?: return false
        var rest = text.substring(m.range.last + 1)
        val colon = rest.indexOf(':')
        // The rest of the first line up to a colon is the button's text ("Our answers:").
        val firstLineEnd = rest.indexOf('\n').let { if (it < 0) rest.length else it }
        rest = if (colon in 0 until firstLineEnd) rest.substring(colon + 1) else rest.substring(firstLineEnd)
        rest = rest.replace(ANSWER_WORDS, "")
        return rest.count { it.isLetterOrDigit() } < 3
    }

    /** Looks like answers to a step's questions, sent without "Done with step N". */
    fun looksLikeAnswers(text: String): Boolean {
        val t = text.trim()
        if (t.length < 12 || isDone(t)) return false
        if (ANSWER_WORDS.containsMatchIn(t)) return true
        val lines = t.lines().filter { it.isNotBlank() }
        val numbered = lines.count { NUMBERED_LINE.containsMatchIn(it) }
        if (numbered >= 2) return true
        if (INLINE_MARK.findAll(t).map { it.groupValues[1] }.toSet().size >= 2) return true
        // "1. One row is one apartment" — a numbered statement, not a question.
        return numbered == 1 && NUMBERED_LINE.containsMatchIn(lines.first()) && !t.endsWith("?")
    }

    /** The message as a step submission, in the language the student wrote in. */
    fun asSubmission(text: String, step: Int?): String {
        val n = step?.let { " $it" } ?: ""
        val prefix = if (HEBREW.containsMatchIn(text)) "סיימתי שלב$n. התשובות שלי:" else "Done with step$n. Our answers:"
        return prefix + "\n" + text.trim()
    }
}
