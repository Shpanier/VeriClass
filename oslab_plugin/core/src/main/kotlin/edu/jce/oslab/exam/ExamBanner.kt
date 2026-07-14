package edu.jce.oslab.exam

import com.intellij.ui.components.JBLabel
import com.intellij.util.ui.JBUI
import java.awt.BorderLayout
import java.awt.Color
import java.awt.Component
import java.awt.Font
import javax.swing.JButton
import javax.swing.JPanel

/**
 * Sticky red strip shown at the top of the OS Lab tool window after the student
 * leaves the IDE during an exam. Starts hidden; [show] makes it visible and
 * refreshes the violation count. "Got it" only hides it — it reappears (with an
 * incremented count) on the next violation, so it can't be permanently
 * dismissed mid-exam.
 *
 * Construct and mutate on the EDT only.
 */
class ExamBanner : JPanel(BorderLayout()) {

    private val message = JBLabel()

    // Warning red that reads on both light and dark IDE themes; the strip is a
    // deliberately loud, hardcoded alert rather than a theme-following color.
    private val warningRed = Color(0xB7, 0x1C, 0x1C)

    init {
        isVisible = false
        isOpaque = true
        background = warningRed
        border = JBUI.Borders.empty(8, 12)
        alignmentX = Component.LEFT_ALIGNMENT

        message.foreground = Color.WHITE
        message.font = message.font.deriveFont(Font.BOLD)
        add(message, BorderLayout.CENTER)

        val gotIt = JButton("Got it")
        gotIt.toolTipText = "Hide this warning (it returns if you leave again)"
        // Qualify: hide the banner, not the button (inside the listener the
        // unqualified `this` would be the button).
        gotIt.addActionListener { this@ExamBanner.isVisible = false }
        add(gotIt, BorderLayout.EAST)
    }

    /** Show/refresh the warning. [reason] is a short human sentence. */
    fun show(violationCount: Int, reason: String) {
        message.text =
            "<html>⚠ <b>Exam mode</b> — $reason<br/>" +
                "Reported to your instructor. You have left the exam window " +
                "<b>$violationCount</b> time(s).</html>"
        isVisible = true
        revalidate()
        repaint()
    }
}
