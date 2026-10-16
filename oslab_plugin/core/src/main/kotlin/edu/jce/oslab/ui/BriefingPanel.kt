package edu.jce.oslab.ui

import edu.jce.oslab.api.Exercise
import edu.jce.oslab.util.Format

/**
 * The exercise briefing, as the first message of the chat: title, the brief
 * (Markdown, ending with the step the students are on), the student's variant
 * parameters and the test inputs they must pass, if the exercise has any.
 */
object Briefing {

    fun markdown(ex: Exercise, variantId: String): String {
        val sb = StringBuilder()
        sb.append("## ").append(ex.title_en).append("\n\n")
        sb.append(ex.brief_md.trim()).append("\n")

        val v = ex.variant ?: return sb.toString()
        if (v.params.isNotEmpty()) {
            sb.append("\n### Your variant (").append(variantId).append(")\n\n")
            val covered = HashSet<String>()
            for (pl in ex.param_labels) {
                if (pl.key.isBlank() || !v.params.containsKey(pl.key)) continue
                covered.add(pl.key)
                val label = if (pl.label.isNullOrBlank()) Format.prettifyKey(pl.key) else pl.label
                sb.append("- **").append(label).append(":** ")
                    .append(Format.paramValue(v.params[pl.key]))
                if (!pl.note.isNullOrBlank()) sb.append(" (").append(pl.note).append(")")
                sb.append("\n")
            }
            for ((k, value) in v.params) {
                if (covered.contains(k)) continue
                sb.append("- **").append(Format.prettifyKey(k)).append(":** ")
                    .append(Format.paramValue(value)).append("\n")
            }
        }
        if (v.test_inputs.isNotEmpty()) {
            sb.append("\n### Test inputs you must pass\n\n")
            for (t in v.test_inputs) {
                sb.append("- `mcalc \"").append(t.input).append("\"` → `")
                    .append(t.expected_output).append("`\n")
            }
        }
        return sb.toString()
    }
}
