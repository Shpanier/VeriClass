package edu.jce.veriexam.ui

import com.intellij.openapi.Disposable
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.ide.CopyPasteManager
import com.intellij.openapi.util.Disposer
import com.intellij.ui.JBColor
import com.intellij.ui.components.JBScrollPane
import com.intellij.ui.components.JBTextArea
import com.intellij.util.ui.JBUI
import com.intellij.util.ui.UIUtil
import edu.jce.veriexam.api.VeriExamApiClient
import edu.jce.veriexam.api.VeriExamApiException
import edu.jce.veriexam.util.MarkdownLite
import java.awt.BorderLayout
import java.awt.Color
import java.awt.Component
import java.awt.Dimension
import java.awt.FlowLayout
import java.awt.Font
import java.awt.datatransfer.StringSelection
import java.awt.event.ActionEvent
import java.awt.event.KeyEvent
import java.util.concurrent.atomic.AtomicBoolean
import javax.swing.AbstractAction
import javax.swing.BorderFactory
import javax.swing.BoxLayout
import javax.swing.JButton
import javax.swing.JComponent
import javax.swing.JEditorPane
import javax.swing.JLabel
import javax.swing.JPanel
import javax.swing.KeyStroke
import javax.swing.ScrollPaneConstants
import javax.swing.SwingUtilities
import javax.swing.Timer

/**
 * The whole session is one scrolling conversation: the exercise brief is the
 * first message, then the students' turns and the tutor's replies as bubbles.
 * Messages render Markdown (bold, lists, inline code), and every fenced code
 * block gets its own Copy button so students never retype code. Tutor replies
 * stream in live from /api/ask.
 */
class ChatPanel(
    private val api: VeriExamApiClient,
    private val token: String,
    private val sessionId: String,
    parent: Disposable,
) : JPanel(BorderLayout()), Disposable {

    enum class Role(val label: String) { EXERCISE("📘 Exercise"), USER("You"), TUTOR("Tutor") }

    private val column = ScrollableColumn().apply { border = JBUI.Borders.empty(6, 6, 12, 6) }
    private val scroll = JBScrollPane(
        column,
        ScrollPaneConstants.VERTICAL_SCROLLBAR_AS_NEEDED,
        ScrollPaneConstants.HORIZONTAL_SCROLLBAR_NEVER,
    ).apply { border = JBUI.Borders.empty() }
    private val chipsRow = JPanel(FlowLayout(FlowLayout.LEFT, JBUI.scale(6), JBUI.scale(2))).apply {
        isOpaque = false
        isVisible = false
    }
    private val input = JBTextArea(3, 0).apply {
        lineWrap = true
        wrapStyleWord = true
        border = JBUI.Borders.empty(4)
        emptyText.text = "Ask the tutor, or write \"Done with step N\" and your answers"
    }
    private val sendButton = JButton("Send")
    private val cancelled = AtomicBoolean(false)

    init {
        Disposer.register(parent, this)
        add(scroll, BorderLayout.CENTER)

        val inputRow = JPanel(BorderLayout(JBUI.scale(6), 0)).apply {
            isOpaque = false
            add(JBScrollPane(input), BorderLayout.CENTER)
            add(sendButton, BorderLayout.EAST)
        }
        val south = JPanel(BorderLayout(0, JBUI.scale(4))).apply {
            border = BorderFactory.createCompoundBorder(
                JBUI.Borders.customLine(JBColor.border(), 1, 0, 0, 0),
                JBUI.Borders.empty(6),
            )
            add(chipsRow, BorderLayout.NORTH)
            add(inputRow, BorderLayout.CENTER)
        }
        add(south, BorderLayout.SOUTH)

        sendButton.addActionListener { onSend() }
        // Enter sends; Shift+Enter inserts a newline.
        input.inputMap.put(KeyStroke.getKeyStroke(KeyEvent.VK_ENTER, 0), "veriexam-send")
        input.actionMap.put("veriexam-send", object : AbstractAction() {
            override fun actionPerformed(e: ActionEvent) = onSend()
        })
    }

    // --- public API -----------------------------------------------------------

    /** EDT only. Add a finished message (used for the exercise brief). */
    fun addMessage(role: Role, markdown: String): MessageBubble {
        val bubble = MessageBubble(role)
        bubble.setMarkdown(markdown)
        addRow(bubble)
        return bubble
    }

    /** EDT only. Add any extra component to the conversation (e.g. a checklist). */
    fun addComponent(c: JComponent) {
        c.alignmentX = Component.LEFT_ALIGNMENT
        column.add(c)
        column.revalidate()
    }

    /** Quick-reply buttons above the input box (welcome suggestions). */
    fun setSuggestions(suggestions: List<String>) {
        chipsRow.removeAll()
        for (s in suggestions) {
            chipsRow.add(JButton(s).apply {
                toolTipText = "Put this in the message box"
                // Chips that end with ':' expect the students to add their answers,
                // so they fill the box instead of sending right away.
                addActionListener {
                    if (s.trimEnd().endsWith(":")) {
                        input.text = "$s "
                        input.requestFocusInWindow()
                        input.caretPosition = input.text.length
                    } else {
                        submit(s)
                    }
                }
            })
        }
        chipsRow.isVisible = suggestions.isNotEmpty()
        chipsRow.revalidate()
    }

    /** Public entry point for the welcome-suggestion chips. */
    fun submit(text: String) {
        if (!sendButton.isEnabled) return
        input.text = text
        onSend()
    }

    /** Scroll to the very top (the exercise brief). */
    fun scrollToTop() = SwingUtilities.invokeLater { scroll.verticalScrollBar.value = 0 }

    // --- sending ----------------------------------------------------------------

    private fun onSend() {
        val text = input.text.trim()
        if (text.isEmpty() || !sendButton.isEnabled) return
        input.text = ""
        addMessage(Role.USER, text)
        val reply = MessageBubble(Role.TUTOR).apply { setMarkdown("…") }
        addRow(reply)
        scrollToBottom()
        setBusy(true)

        val buffer = StringBuilder()
        // Re-render at most every 80 ms while tokens stream in.
        val render = Timer(80) { reply.setMarkdown(buffer.toString().ifBlank { "…" }); scrollToBottom() }
            .apply { isRepeats = false }

        ApplicationManager.getApplication().executeOnPooledThread {
            try {
                api.ask(token, sessionId, text, cancelled) { chunk ->
                    ApplicationManager.getApplication().invokeLater {
                        buffer.append(chunk)
                        render.restart()
                    }
                }
            } catch (e: VeriExamApiException) {
                ApplicationManager.getApplication().invokeLater { buffer.append("\n\n⚠️ ${e.message}") }
            } catch (e: Exception) {
                ApplicationManager.getApplication().invokeLater {
                    buffer.append("\n\n⚠️ Could not reach the tutor. Is the backend running? (${e.message})")
                }
            } finally {
                ApplicationManager.getApplication().invokeLater {
                    render.stop()
                    reply.setMarkdown(buffer.toString().ifBlank { "⚠️ No reply." })
                    scrollToBottom()
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

    private fun addRow(bubble: MessageBubble) {
        // Students' messages sit to the right, the tutor's and the brief to the left.
        val row = JPanel(BorderLayout()).apply {
            isOpaque = false
            alignmentX = Component.LEFT_ALIGNMENT
            border = when (bubble.role) {
                Role.USER -> JBUI.Borders.empty(4, 48, 4, 0)
                Role.TUTOR -> JBUI.Borders.empty(4, 0, 4, 32)
                Role.EXERCISE -> JBUI.Borders.empty(4, 0, 8, 0)
            }
            add(bubble, BorderLayout.CENTER)
        }
        column.add(row)
        column.revalidate()
        column.repaint()
    }

    private fun scrollToBottom() = SwingUtilities.invokeLater {
        column.revalidate()
        SwingUtilities.invokeLater {
            val bar = scroll.verticalScrollBar
            bar.value = bar.maximum
        }
    }

    override fun dispose() {
        cancelled.set(true)
    }

    // --- message bubble ---------------------------------------------------------

    /** One message: a role label and Markdown content, with copyable code blocks. */
    class MessageBubble(val role: Role) : JPanel(BorderLayout()) {
        private val body = JPanel().apply {
            layout = BoxLayout(this, BoxLayout.Y_AXIS)
            isOpaque = false
        }

        init {
            background = when (role) {
                Role.USER -> JBColor(Color(0xE3EEFC), Color(0x2B3A4F))
                Role.TUTOR -> JBColor(Color(0xF4F5F7), Color(0x30333A))
                Role.EXERCISE -> JBColor(Color(0xFFF8E1), Color(0x3A3524))
            }
            isOpaque = true
            border = BorderFactory.createCompoundBorder(
                JBUI.Borders.customLine(JBColor(Color(0xD9DEE6), Color(0x454A52)), 1),
                JBUI.Borders.empty(6, 10, 8, 10),
            )
            add(JLabel(role.label).apply {
                font = font.deriveFont(Font.BOLD, font.size2D - 1f)
                foreground = JBColor.GRAY
                border = JBUI.Borders.emptyBottom(2)
            }, BorderLayout.NORTH)
            add(body, BorderLayout.CENTER)
        }

        override fun getMaximumSize(): Dimension = Dimension(Int.MAX_VALUE, preferredSize.height)

        /** EDT only. Re-render the whole message (cheap enough for streaming). */
        fun setMarkdown(md: String) {
            body.removeAll()
            for (seg in segments(md)) {
                body.add(if (seg.isCode) CodeBlock(seg.text) else htmlPane(seg.text))
            }
            body.revalidate()
            body.repaint()
            revalidate()
        }

        private fun htmlPane(md: String): JEditorPane = object : JEditorPane("text/html", "") {
            override fun getMaximumSize(): Dimension = Dimension(Int.MAX_VALUE, preferredSize.height)
        }.apply {
            isEditable = false
            isOpaque = false
            border = JBUI.Borders.empty()
            alignmentX = Component.LEFT_ALIGNMENT
            putClientProperty(JEditorPane.HONOR_DISPLAY_PROPERTIES, true)
            font = UIUtil.getLabelFont()
            val f = UIUtil.getLabelFont()
            text = "<html><body style=\"font-family:${f.family};font-size:${f.size}pt;margin:0;\">" +
                MarkdownLite.toHtml(md) + "</body></html>"
        }
    }

    /** A code block with a Copy button; the text is also selectable. */
    class CodeBlock(code: String) : JPanel(BorderLayout()) {
        init {
            alignmentX = Component.LEFT_ALIGNMENT
            isOpaque = true
            background = JBColor(Color(0x1E2430), Color(0x1A1D23))
            border = JBUI.Borders.empty(4, 8, 6, 6)
            val area = JBTextArea(code).apply {
                isEditable = false
                isOpaque = false
                lineWrap = false
                font = Font(Font.MONOSPACED, Font.PLAIN, UIUtil.getLabelFont().size)
                foreground = Color(0xE4E8F0)
                caretColor = Color(0xE4E8F0)
                border = JBUI.Borders.empty(2, 0)
            }
            val copy = JButton("Copy").apply {
                toolTipText = "Copy this code"
                addActionListener {
                    CopyPasteManager.getInstance().setContents(StringSelection(code))
                    text = "Copied ✓"
                    Timer(1500) { text = "Copy" }.apply { isRepeats = false }.start()
                }
            }
            val top = JPanel(BorderLayout()).apply {
                isOpaque = false
                add(JLabel("code").apply { foreground = Color(0x8E9AB0) }, BorderLayout.WEST)
                add(copy, BorderLayout.EAST)
            }
            add(top, BorderLayout.NORTH)
            add(JBScrollPane(area).apply {
                isOpaque = false
                viewport.isOpaque = false
                border = JBUI.Borders.empty()
                verticalScrollBarPolicy = ScrollPaneConstants.VERTICAL_SCROLLBAR_NEVER
                horizontalScrollBarPolicy = ScrollPaneConstants.HORIZONTAL_SCROLLBAR_AS_NEEDED
            }, BorderLayout.CENTER)
        }

        override fun getMaximumSize(): Dimension = Dimension(Int.MAX_VALUE, preferredSize.height)
    }

    private data class Segment(val text: String, val isCode: Boolean)

    companion object {
        // Older servers send plain text with these markers instead of ``` fences.
        private const val PLAIN_START = "▼▼▼"
        private const val PLAIN_END = "▲▲▲"

        /** Split Markdown into prose and fenced code blocks (``` or the plain markers). */
        private fun segments(md: String): List<Segment> {
            val out = mutableListOf<Segment>()
            val prose = StringBuilder()
            val code = StringBuilder()
            var inCode = false
            var fence = ""
            fun flushProse() {
                if (prose.isNotBlank()) out.add(Segment(prose.toString().trim('\n'), false))
                prose.setLength(0)
            }
            for (line in md.replace("\r\n", "\n").split("\n")) {
                val t = line.trim()
                if (!inCode && (t.startsWith("```") || t.startsWith(PLAIN_START))) {
                    flushProse()
                    inCode = true
                    fence = if (t.startsWith("```")) "```" else PLAIN_END
                    continue
                }
                if (inCode && t.startsWith(fence)) {
                    out.add(Segment(code.toString().trimEnd('\n'), true))
                    code.setLength(0)
                    inCode = false
                    continue
                }
                if (inCode) code.append(line).append('\n') else prose.append(line).append('\n')
            }
            // A fence still open while streaming: show what has arrived as code.
            if (inCode && code.isNotEmpty()) out.add(Segment(code.toString().trimEnd('\n'), true))
            flushProse()
            return out
        }
    }
}
