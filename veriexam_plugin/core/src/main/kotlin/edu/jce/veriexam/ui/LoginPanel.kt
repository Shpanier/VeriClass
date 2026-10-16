package edu.jce.veriexam.ui

import com.intellij.ui.JBColor
import com.intellij.ui.components.JBLabel
import com.intellij.ui.components.JBTextField
import com.intellij.util.ui.JBUI
import java.awt.GridBagConstraints
import java.awt.GridBagLayout
import java.awt.Insets
import javax.swing.JButton
import javax.swing.JComponent
import javax.swing.JPanel
import javax.swing.SwingConstants

/** First screen: enter the course login code. */
class LoginPanel(private val onSubmit: (String) -> Unit) : JPanel(GridBagLayout()) {

    private val codeField = JBTextField(16)
    private val button = JButton("Log in")
    private val status = JBLabel("").apply {
        foreground = JBColor.RED
        horizontalAlignment = SwingConstants.CENTER
    }

    init {
        border = JBUI.Borders.empty(24)
        val c = GridBagConstraints().apply {
            gridx = 0
            gridy = 0
            insets = Insets(JBUI.scale(6), 0, JBUI.scale(6), 0)
            fill = GridBagConstraints.HORIZONTAL
            weightx = 1.0
        }

        add(JBLabel("🎓 Welcome to VeriExam").apply { horizontalAlignment = SwingConstants.CENTER }, c)
        c.gridy++
        add(JBLabel("Enter your login code to begin:").apply { horizontalAlignment = SwingConstants.CENTER }, c)
        c.gridy++
        add(codeField, c)
        c.gridy++
        add(button, c)
        c.gridy++
        add(status, c)

        button.addActionListener { fire() }
        codeField.addActionListener { fire() }
    }

    private fun fire() {
        val code = codeField.text.trim()
        if (code.isEmpty()) {
            setError("Please type your login code.")
            return
        }
        setBusy(true)
        onSubmit(code)
    }

    fun setBusy(busy: Boolean) {
        button.isEnabled = !busy
        codeField.isEnabled = !busy
        button.text = if (busy) "Logging in…" else "Log in"
        if (busy) status.text = " "
    }

    fun setError(message: String) {
        setBusy(false)
        status.text = message
    }

    fun preferredFocus(): JComponent = codeField
}
