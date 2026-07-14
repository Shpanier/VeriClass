package edu.jce.oslab.ui

import com.intellij.ui.IdeBorderFactory
import com.intellij.ui.components.JBCheckBox
import com.intellij.util.ui.JBUI
import edu.jce.oslab.api.Variant
import java.awt.Component
import java.awt.Dimension
import javax.swing.BoxLayout
import javax.swing.JPanel

/**
 * IDE-native mode only: the variant's required test inputs as a manual
 * checklist the student ticks off as they get each one passing. Purely
 * client-side state — it's a focus aid, not a grade.
 */
class TestChecklistPanel(variant: Variant) : JPanel() {

    init {
        layout = BoxLayout(this, BoxLayout.Y_AXIS)
        border = IdeBorderFactory.createTitledBorder("Tests to pass", false)
        alignmentX = Component.LEFT_ALIGNMENT

        for (t in variant.test_inputs) {
            val label = "mcalc \"${t.input}\"  →  ${t.expected_output}"
            add(
                JBCheckBox(label).apply {
                    alignmentX = Component.LEFT_ALIGNMENT
                    border = JBUI.Borders.empty(2, 4)
                },
            )
        }
    }

    override fun getMaximumSize(): Dimension =
        Dimension(Int.MAX_VALUE, super.getPreferredSize().height)
}
