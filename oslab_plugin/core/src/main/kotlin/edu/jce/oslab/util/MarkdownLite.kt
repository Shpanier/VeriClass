package edu.jce.oslab.util

/**
 * Tiny, dependency-free Markdown→HTML for the briefing bubble. Handles the
 * subset the exercise YAML actually uses: headings, fenced & indented code,
 * bullet lists, bold, and inline code. Not a general Markdown engine.
 */
object MarkdownLite {

    fun toHtml(md: String): String {
        val out = StringBuilder()
        val lines = md.replace("\r\n", "\n").split("\n")
        var i = 0
        var inList = false
        var inPara = false

        fun closeList() {
            if (inList) { out.append("</ul>"); inList = false }
        }
        fun closePara() {
            if (inPara) { out.append("</p>"); inPara = false }
        }

        while (i < lines.size) {
            val line = lines[i]

            // Fenced code block.
            if (line.trimStart().startsWith("```")) {
                closeList(); closePara()
                out.append("<pre><code>")
                i++
                while (i < lines.size && !lines[i].trimStart().startsWith("```")) {
                    out.append(Format.html(lines[i])).append("\n")
                    i++
                }
                out.append("</code></pre>")
                i++
                continue
            }

            // Indented code block (>= 4 leading spaces).
            if (line.startsWith("    ") && line.isNotBlank()) {
                closeList(); closePara()
                out.append("<pre><code>")
                while (i < lines.size && (lines[i].startsWith("    ") || lines[i].isBlank())) {
                    if (lines[i].isBlank() &&
                        (i + 1 >= lines.size || !lines[i + 1].startsWith("    "))
                    ) break
                    out.append(Format.html(lines[i].removePrefix("    "))).append("\n")
                    i++
                }
                out.append("</code></pre>")
                continue
            }

            val trimmed = line.trim()
            when {
                trimmed.isEmpty() -> { closeList(); closePara() }

                trimmed.startsWith("### ") -> {
                    closeList(); closePara(); out.append("<h4>").append(inline(trimmed.removePrefix("### "))).append("</h4>")
                }
                trimmed.startsWith("## ") -> {
                    closeList(); closePara(); out.append("<h3>").append(inline(trimmed.removePrefix("## "))).append("</h3>")
                }
                trimmed.startsWith("# ") -> {
                    closeList(); closePara(); out.append("<h2>").append(inline(trimmed.removePrefix("# "))).append("</h2>")
                }
                trimmed.startsWith("- ") || trimmed.startsWith("* ") -> {
                    closePara()
                    if (!inList) { out.append("<ul>"); inList = true }
                    out.append("<li>").append(inline(trimmed.substring(2))).append("</li>")
                }
                else -> {
                    closeList()
                    if (!inPara) { out.append("<p>"); inPara = true } else out.append(" ")
                    out.append(inline(trimmed))
                }
            }
            i++
        }
        closeList(); closePara()
        return out.toString()
    }

    /** Inline: escape, then **bold** and `code`. */
    private fun inline(raw: String): String {
        var s = Format.html(raw)
        s = Regex("\\*\\*(.+?)\\*\\*").replace(s) { "<b>${it.groupValues[1]}</b>" }
        s = Regex("`([^`]+?)`").replace(s) { "<code>${it.groupValues[1]}</code>" }
        return s
    }
}
