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
            sb.append("<h3>Your variant parameters</h3><ul>")
            for ((k, value) in v.params) {
                sb.append("<li><code>").append(Format.html(k)).append("</code> = <code>")
                    .append(Format.html(Format.value(value))).append("</code></li>")
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
