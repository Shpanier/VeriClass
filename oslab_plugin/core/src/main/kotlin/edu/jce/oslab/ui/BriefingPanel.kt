package edu.jce.oslab.ui

import com.intellij.util.ui.JBUI
import com.intellij.util.ui.UIUtil
import edu.jce.oslab.api.Exercise
import edu.jce.oslab.util.Format
import edu.jce.oslab.util.MarkdownLite
import java.awt.Dimension
import javax.swing.JEditorPane

/**
 * The exercise briefing bubble — the equivalent of Chainlit's opening message:
 * title, the exercise brief (markdown), the student's variant parameters, the
 * test inputs they must pass, and the current mode.
 */
class BriefingPanel(exercise: Exercise, variantId: String, mode: String) :
    JEditorPane("text/html", "") {

    init {
        isEditable = false
        isOpaque = false
        border = JBUI.Borders.empty(8)
        text = buildHtml(exercise, variantId, mode)
        caretPosition = 0
    }

    // Let the panel report its full height so it lays out nicely in a BoxLayout.
    override fun getMaximumSize(): Dimension =
        Dimension(Int.MAX_VALUE, super.getPreferredSize().height)

    private fun buildHtml(ex: Exercise, variantId: String, mode: String): String {
        val v = ex.variant
        val sb = StringBuilder()
        sb.append("<html><body style=\"font-family:")
            .append(UIUtil.getLabelFont().family)
            .append(";font-size:").append(UIUtil.getLabelFont().size).append("pt;\">")

        sb.append("<h2>📘 ").append(Format.html(ex.title_en))
            .append(" <span style=\"color:gray;\">(variant ").append(Format.html(variantId))
            .append(")</span></h2>")

        sb.append(MarkdownLite.toHtml(ex.brief_md))

        if (v != null) {
            sb.append("<h3>Your variant</h3><ul>")
            val covered = HashSet<String>()
            // Authored labels first (in order); they connect each param to the exercise.
            for (pl in ex.param_labels) {
                if (pl.key.isBlank() || !v.params.containsKey(pl.key)) continue
                covered.add(pl.key)
                val label = if (pl.label.isNullOrBlank()) Format.prettifyKey(pl.key) else pl.label
                sb.append("<li><b>").append(Format.html(label)).append(":</b> ")
                    .append(Format.html(Format.paramValue(v.params[pl.key])))
                if (!pl.note.isNullOrBlank()) {
                    sb.append(" <span style=\"color:gray;\">&mdash; ").append(Format.html(pl.note)).append("</span>")
                }
                sb.append("</li>")
            }
            // Any remaining params fall back to a prettified key.
            for ((k, value) in v.params) {
                if (covered.contains(k)) continue
                sb.append("<li><b>").append(Format.html(Format.prettifyKey(k))).append(":</b> ")
                    .append(Format.html(Format.paramValue(value))).append("</li>")
            }
            sb.append("</ul>")

            if (v.test_inputs.isNotEmpty()) {
                sb.append("<h3>Test inputs you must pass</h3><ul>")
                for (t in v.test_inputs) {
                    sb.append("<li><code>mcalc \"").append(Format.html(t.input))
                        .append("\"</code> &rarr; <code>").append(Format.html(t.expected_output))
                        .append("</code></li>")
                }
                sb.append("</ul>")
            }
        }

        sb.append("<p><b>Mode:</b> <code>").append(Format.html(mode)).append("</code></p>")
        sb.append("</body></html>")
        return sb.toString()
    }
}
