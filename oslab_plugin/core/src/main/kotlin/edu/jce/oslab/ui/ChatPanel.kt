package edu.jce.oslab.ui

import com.intellij.openapi.Disposable
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.util.Disposer
import com.intellij.ui.JBColor
import com.intellij.ui.components.JBScrollPane
import com.intellij.ui.components.JBTextArea
import com.intellij.util.ui.JBUI
import edu.jce.oslab.api.OsLabApiClient
import edu.jce.oslab.api.OsLabApiException
import java.awt.BorderLayout
import java.awt.Color
import java.awt.event.ActionEvent
import java.awt.event.KeyEvent
import java.util.concurrent.atomic.AtomicBoolean
import javax.swing.AbstractAction
import javax.swing.BorderFactory
import javax.swing.JButton
import javax.swing.JPanel
import javax.swing.JTextPane
import javax.swing.KeyStroke
import javax.swing.text.SimpleAttributeSet
import javax.swing.text.StyleConstants

/**
 * The chat transcript + input box. The transcript is a single styled JTextPane
 * (wraps automatically, streams reliably). User turns get a bold label;
 * assistant tokens are appended live as they arrive from /api/ask.
 */
class ChatPanel(
    private val api: OsLabApiClient,
    private val token: String,
    private val sessionId: String,
    parent: Disposable,
) : JPanel(BorderLayout()), Disposable {

    private val transcript = JTextPane().apply {
        isEditable = false
        border = JBUI.Borders.empty(8)
    }
    private val input = JBTextArea(3, 0).apply {
        lineWrap = true
        wrapStyleWord = true
        border = JBUI.Borders.empty(4)
    }
    private val sendButton = JButton("Send")
    private val cancelled = AtomicBoolean(false)

    private val userStyle = SimpleAttributeSet().apply {
        StyleConstants.setBold(this, true)
        StyleConstants.setForeground(this, JBColor(Color(0x1A66C2), Color(0x589DF6)))
    }
    private val assistantStyle = SimpleAttributeSet()
    private val roleStyle = SimpleAttributeSet().apply {
        StyleConstants.setBold(this, true)
        StyleConstants.setForeground(this, JBColor.GRAY)
    }
    private val systemStyle = SimpleAttributeSet().apply {
        StyleConstants.setItalic(this, true)
        StyleConstants.setForeground(this, JBColor.GRAY)
    }
    private val errorStyle = SimpleAttributeSet().apply {
        StyleConstants.setItalic(this, true)
        StyleConstants.setForeground(this, JBColor.RED)
    }

    init {
        Disposer.register(parent, this)

        add(JBScrollPane(transcript), BorderLayout.CENTER)

        val south = JPanel(BorderLayout(JBUI.scale(6), 0)).apply {
            border = BorderFactory.createCompoundBorder(
                JBUI.Borders.customLine(JBColor.border(), 1, 0, 0, 0),
                JBUI.Borders.empty(6),
            )
        }
        south.add(JBScrollPane(input), BorderLayout.CENTER)
        south.add(sendButton, BorderLayout.EAST)
        add(south, BorderLayout.SOUTH)

        sendButton.addActionListener { onSend() }

        // Enter sends; Shift+Enter inserts a newline.
        val sendKey = KeyStroke.getKeyStroke(KeyEvent.VK_ENTER, 0)
        input.inputMap.put(sendKey, "oslab-send")
        input.actionMap.put("oslab-send", object : AbstractAction() {
            override fun actionPerformed(e: ActionEvent) = onSend()
        })
    }

    /** Public entry point for the welcome-suggestion chips. */
    fun submit(text: String) {
        if (!sendButton.isEnabled) return
        input.text = text
        onSend()
    }

    private fun onSend() {
        val text = input.text.trim()
        if (text.isEmpty() || !sendButton.isEnabled) return
        input.text = ""
        appendRole("You")
        append(text + "\n\n", userStyle)
        setBusy(true)

        appendRole("Tutor")
        ApplicationManager.getApplication().executeOnPooledThread {
            try {
                api.ask(token, sessionId, text, cancelled) { chunk ->
                    ApplicationManager.getApplication().invokeLater {
                        append(chunk, assistantStyle)
                    }
                }
            } catch (e: OsLabApiException) {
                ApplicationManager.getApplication().invokeLater { append("\n${e.message}\n", errorStyle) }
            } catch (e: Exception) {
                ApplicationManager.getApplication().invokeLater {
                    append("\n⚠️ Could not reach the tutor. Is the backend running? (${e.message})\n", errorStyle)
                }
            } finally {
                ApplicationManager.getApplication().invokeLater {
                    append("\n\n", assistantStyle)
                    setBusy(false)
                }
            }
        }
    }

    private fun setBusy(busy: Boolean) {
        sendButton.isEnabled = !busy
        sendButton.text = if (busy) "…" else "Send"
        input.isEnabled = !busy
        if (!busy) input.requestFocusInWindow()
    }

    private fun appendRole(role: String) = append("$role\n", roleStyle)

    /** EDT only. */
    private fun append(text: String, style: SimpleAttributeSet) {
        val doc = transcript.styledDocument
        doc.insertString(doc.length, text, style)
        transcript.caretPosition = doc.length
    }

    /** EDT only. Shown once at the top of the transcript as a system line. */
    fun showSystemLine(text: String) = append("$text\n\n", systemStyle)

    override fun dispose() {
        cancelled.set(true)
    }
}
