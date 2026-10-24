package edu.jce.vericlass.ui

import com.intellij.ui.JBColor
import com.intellij.ui.components.JBLabel
import com.intellij.ui.components.JBPasswordField
import com.intellij.ui.components.JBTextField
import com.intellij.util.ui.JBUI
import java.awt.GridBagConstraints
import java.awt.GridBagLayout
import java.awt.Insets
import javax.swing.JButton
import javax.swing.JComponent
import javax.swing.JPanel
import javax.swing.SwingConstants

/** First screen: username (the login code) and password. Until the teacher sets
 *  a password, it is the username. */
class LoginPanel(private val onSubmit: (code: String, password: String) -> Unit) : JPanel(GridBagLayout()) {

    private val codeField = JBTextField(16)
    private val passwordField = JBPasswordField().apply { columns = 16 }
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

        add(JBLabel("🎓 Welcome to VeriClass").apply { horizontalAlignment = SwingConstants.CENTER }, c)
        c.gridy++
        add(JBLabel("Username:"), c)
        c.gridy++
        add(codeField, c)
        c.gridy++
        add(JBLabel("Password (at first, your username):"), c)
        c.gridy++
        add(passwordField, c)
        c.gridy++
        add(button, c)
        c.gridy++
        add(status, c)

        button.addActionListener { fire() }
        codeField.addActionListener { passwordField.requestFocusInWindow() }
        passwordField.addActionListener { fire() }
    }

    private fun fire() {
        val code = codeField.text.trim()
        val password = String(passwordField.password)
        if (code.isEmpty()) {
            setError("Please type your username.")
            return
        }
        if (password.isEmpty()) {
            setError("Please type your password.")
            return
        }
        setBusy(true)
        onSubmit(code, password)
    }

    fun setBusy(busy: Boolean) {
        button.isEnabled = !busy
        codeField.isEnabled = !busy
        passwordField.isEnabled = !busy
        button.text = if (busy) "Logging in…" else "Log in"
        if (busy) status.text = " "
    }

    fun setError(message: String) {
        setBusy(false)
        status.text = message
    }

    fun preferredFocus(): JComponent = codeField
}
