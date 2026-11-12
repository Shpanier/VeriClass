package edu.jce.vericlass.ui

import com.intellij.openapi.Disposable
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.ide.CopyPasteManager
import com.intellij.openapi.util.Disposer
import com.intellij.ui.DocumentAdapter
import com.intellij.ui.JBColor
import com.intellij.ui.components.JBScrollPane
import com.intellij.ui.components.JBTextArea
import com.intellij.util.ui.JBUI
import com.intellij.util.ui.UIUtil
import edu.jce.vericlass.api.VeriClassApiClient
import edu.jce.vericlass.api.VeriClassApiException
import edu.jce.vericlass.exam.PasteSources
import edu.jce.vericlass.lab.Interrupt
import edu.jce.vericlass.lab.LabButton
import edu.jce.vericlass.lab.LabFlow
import edu.jce.vericlass.lab.LabTexts
import edu.jce.vericlass.lab.LabView
import edu.jce.vericlass.lab.Route
import edu.jce.vericlass.lab.Shown
import edu.jce.vericlass.trace.SessionTrace
import edu.jce.vericlass.util.MarkdownLite
import java.awt.BorderLayout
import java.awt.Color
import java.awt.Component
import java.awt.ComponentOrientation
import java.awt.Dimension
import java.awt.FlowLayout
import java.awt.Font
import java.awt.datatransfer.DataFlavor
import java.awt.datatransfer.StringSelection
import java.awt.event.ActionEvent
import java.awt.event.InputEvent
import java.awt.event.KeyEvent
import java.awt.font.TextAttribute
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
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
import javax.swing.event.DocumentEvent
import javax.swing.text.JTextComponent

/**
 * The whole session is one scrolling conversation: the exercise brief is the
 * first message, then the students' turns and the tutor's replies as bubbles.
 * Messages render Markdown (bold, lists, inline code), and every fenced code
 * block gets its own Copy button so students never retype code. Tutor replies
 * stream in live from /api/ask. A reply the server marks as "can be asked again"
 * gets a button that sends the same question to its stronger model.
 *
 * With a [LabFlow] attached ([attach]), every message first goes to the flow,
 * which says what it is: the answer to a question the chat asked, a class-paced
 * lab step's output, or an ordinary question (see [Route]). The flow shows its
 * own messages here through [labView]. A reply that waits for the teacher's
 * review doesn't keep the box busy: the student can go on meanwhile.
 */
class ChatPanel(
    private val api: VeriClassApiClient,
    private val token: String,
    private val sessionId: String,
    parent: Disposable,
    /** The local journal (student export) gets every turn. */
    private val trace: SessionTrace? = null,
    /** Exam mode: called with the text of every paste into the input box. */
    private val onPaste: ((String) -> Unit)? = null,
    /** Step-by-step labs: how many steps, and the one the student is on (kept up to date from replies). */
    private val steps: StepState = StepState(0, 0),
    /** On a step submission, on the EDT: what to attach for the teacher (the open file, the check's output). */
    private val attachments: (() -> PendingAttachment?)? = null,
    /** The lab's own lines (prompts, buttons), in its language. */
    private val texts: LabTexts = LabTexts(false),
) : JPanel(BorderLayout()), Disposable {

    enum class Role(val label: String) {
        EXERCISE("📘 Exercise"), USER("You"), TUTOR("Tutor"), NOTICE("⚠️ VeriClass"),
        /** A class-paced lab's step. */
        STEP("📋 Step"),
        /** The lab's own notes, results and questions. */
        LAB("VeriClass"),
    }

    /** The lab's steps as far as this chat knows. */
    class StepState(var total: Int, var current: Int) {
        val active: Boolean get() = total > 0 && current in 1..total
    }

    /** An attachment collected on the EDT, finished off it (running the check command can take seconds). */
    fun interface PendingAttachment {
        fun complete(): Map<String, String?>
    }

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
    private val input = object : JBTextArea(3, 0) {
        override fun paste() {
            onPaste?.let { report ->
                runCatching { CopyPasteManager.getInstance().getContents<String>(DataFlavor.stringFlavor) }
                    .getOrNull()?.takeIf { it.isNotEmpty() }?.let(report)
            }
            super.paste()
        }
    }.apply {
        lineWrap = true
        wrapStyleWord = true
        border = JBUI.Borders.empty(4)
        emptyText.text = "Ask the tutor, or write \"Done with step N\" and your answers"
    }
    private val south: JPanel
    private val sendButton = JButton("Send")
    private val cancelled = AtomicBoolean(false)
    /** This chat's id in the session's transcript (a second window has its own). */
    val clientId: String = java.util.UUID.randomUUID().toString().replace("-", "")
    private var flow: LabFlow? = null
    /** After the brief (or the replayed conversation): what VeriClassPanel adds below it. */
    private var afterIntro: ((replayed: Boolean) -> Unit)? = null
    /** Replies streaming that keep the box busy (not those waiting for the teacher's review). */
    private var foreground = 0
    /** The flow is deciding what the message being sent is. */
    private var routing = false
    /** The "ask again" button under the latest reply; removed once anything new is sent. */
    private var reaskRow: JComponent? = null
    /** "Send these as your step answers?" / "No answers yet" above the box; removed on the next send. */
    private var promptRow: JComponent? = null
    /** What the prompt above the box is about, so a teacher's change can take it away ([LabView.interrupt]). */
    private var promptAbout: Interrupt? = null
    /** Called when the prompt goes away without being answered (the "Done" box: [LabView.outputBox]'s onClose). */
    private var promptOnClose: (() -> Unit)? = null

    init {
        Disposer.register(parent, this)
        add(scroll, BorderLayout.CENTER)

        val inputRow = JPanel(BorderLayout(JBUI.scale(6), 0)).apply {
            isOpaque = false
            add(JBScrollPane(input), BorderLayout.CENTER)
            add(sendButton, BorderLayout.EAST)
        }
        south = JPanel(BorderLayout(0, JBUI.scale(4))).apply {
            border = BorderFactory.createCompoundBorder(
                JBUI.Borders.customLine(JBColor.border(), 1, 0, 0, 0),
                JBUI.Borders.empty(6),
            )
            add(chipsRow, BorderLayout.NORTH)
            add(inputRow, BorderLayout.CENTER)
        }
        add(south, BorderLayout.SOUTH)

        sendButton.addActionListener { onSend() }
        installSendKeys(input, ::onSend)
        // The box grows with the student's lines, up to MAX_INPUT_ROWS, then scrolls.
        input.document.addDocumentListener(object : DocumentAdapter() {
            override fun textChanged(e: DocumentEvent) {
                val rows = input.lineCount.coerceIn(MIN_INPUT_ROWS, MAX_INPUT_ROWS)
                if (rows != input.rows) {
                    input.rows = rows
                    south.revalidate()
                }
            }
        })
    }

    // --- public API -----------------------------------------------------------

    /** Messages go through [flow] from now on; [afterIntro] runs once the brief or the replay is shown. */
    fun attach(flow: LabFlow, afterIntro: (replayed: Boolean) -> Unit) {
        this.flow = flow
        this.afterIntro = afterIntro
    }

    /** The hint in the empty message box. */
    fun setPlaceholder(text: String) {
        input.emptyText.text = text
    }

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

    /** Scroll to the very top (the exercise brief), after any scroll to the bottom already asked for. */
    fun scrollToTop() = SwingUtilities.invokeLater {
        SwingUtilities.invokeLater { scroll.verticalScrollBar.value = 0 }
    }

    // --- sending ----------------------------------------------------------------

    private fun onSend() {
        val text = input.text.trim()
        if (text.isEmpty() || !sendButton.isEnabled) return
        removePrompt()
        val f = flow ?: return askPath(text)
        routing = true
        updateBusy()
        f.route(text) { route ->
            ApplicationManager.getApplication().invokeLater {
                routing = false
                updateBusy()
                apply(f, route, text)
            }
        }
    }

    /** EDT. Act on what the flow says [text] is. A choice applies to the box's text then. */
    private fun apply(f: LabFlow, route: Route, text: String) {
        fun current() = input.text.trim().ifEmpty { text }
        when (route) {
            is Route.Ask -> askPath(text)
            is Route.Finish -> {
                echo(text)
                f.finish(route.step)
            }
            is Route.Answer -> {
                echo(text)
                f.answer(route.probe, text)
            }
            is Route.AnswerOrQuestion -> showPrompt(
                texts.answerOrQuestion(),
                texts.myAnswer() to { current().let { echo(it); f.answer(route.probe, it) } },
                // Their own question: answered, then the chat reminds them of its own.
                texts.myQuestion() to { send(current(), remind = true) },
                about = Interrupt.PROBE,
            )
            is Route.Output -> sendOutput(f, route.step, route.label, text, route.needsOutput, detected = true)
            is Route.OutputOrQuestion -> showPrompt(
                texts.outputOrQuestion(route.label),
                texts.itsTheOutput(route.label, route.needsOutput) to {
                    sendOutput(f, route.step, route.label, current(), route.needsOutput, detected = false)
                },
                texts.itsAQuestion() to { send(current()) },
                about = Interrupt.STEP,
            )
        }
    }

    /** EDT. A step's answer typed or pasted into the box: it finishes the step (or, if the step closed meanwhile, goes to the tutor). */
    private fun sendOutput(f: LabFlow, step: Int, label: String, text: String, needsOutput: Boolean, detected: Boolean) {
        echo(text)
        f.output(step, label, text, needsOutput, detected) {
            ApplicationManager.getApplication().invokeLater { streamReply(text, reaskModel = null, traceQuestion = false) }
        }
    }

    /** EDT. Show what the student sent (not to the tutor) and record it. */
    private fun echo(text: String) {
        removePrompt()
        input.text = ""
        addMessage(Role.USER, text)
        scrollToBottom()
        trace?.let { t -> ApplicationManager.getApplication().executeOnPooledThread { t.chat(fromStudent = true, text = text, delivered = true) } }
        flow?.recordStudent(text)
    }

    /** EDT. An ordinary message: a step-by-step lab may first ask whether it holds the step's answers. */
    private fun askPath(text: String) {
        if (steps.active) {
            if (AnswerDetector.isDone(text) && AnswerDetector.doneWithoutAnswers(text)) {
                showPrompt(
                    "Your message has no answers yet. Write them after the colon, then send. " +
                        "· ההודעה עוד בלי תשובות. כתבו אותן אחרי הנקודתיים ושלחו.",
                    "Edit · לערוך" to { input.requestFocusInWindow(); input.caretPosition = input.text.length },
                    "Send anyway · לשלוח בכל זאת" to { send(text) },
                )
                return
            }
            if (!AnswerDetector.isDone(text) && AnswerDetector.looksLikeAnswers(text)) {
                val n = steps.current
                showPrompt(
                    "This looks like your answers to step $n. Send them to your teacher? " +
                        "· נראה כמו תשובות לשלב $n. לשלוח אותן למורה?",
                    "Send as step $n · לשלוח כהגשה" to { send(AnswerDetector.asSubmission(text, n)) },
                    "Ask the tutor · לשאול את הטוטור" to { send(text) },
                )
                return
            }
        }
        send(text)
    }

    /** [remind]: afterwards, remind the student of the question the chat asked them. */
    private fun send(text: String, remind: Boolean = false) {
        removePrompt()
        input.text = ""
        addMessage(Role.USER, text)
        flow?.recordStudent(text)
        val attachment = if (steps.active && AnswerDetector.isDone(text)) {
            runCatching { attachments?.invoke() }.getOrNull()
        } else null
        streamReply(text, reaskModel = null, attachment = attachment,
            onDone = if (remind) ({ flow?.remindQuestion() }) else null)
    }

    /** EDT. A short question above the input box with one button per choice; [about]: see [promptAbout]. */
    private fun showPrompt(message: String, vararg choices: Pair<String, () -> Unit>, about: Interrupt? = null) {
        removePrompt()
        val panel = JPanel(BorderLayout(0, JBUI.scale(4))).apply {
            isOpaque = true
            background = JBColor(Color(0xFFF4D6), Color(0x4A3F22))
            border = JBUI.Borders.empty(6, 8)
            add(JLabel("<html>${com.intellij.openapi.util.text.StringUtil.escapeXmlEntities(message)}</html>"),
                BorderLayout.CENTER)
            add(JPanel(FlowLayout(FlowLayout.LEFT, JBUI.scale(6), 0)).apply {
                isOpaque = false
                for ((label, action) in choices) add(JButton(label).apply { addActionListener { action() } })
            }, BorderLayout.SOUTH)
        }
        promptRow = panel
        promptAbout = about
        south.add(panel, BorderLayout.SOUTH)
        south.revalidate()
        south.repaint()
    }

    /** EDT. Take the prompt (or the "Done" box) above the message box away; the box's text stays. */
    private fun removePrompt() {
        promptRow?.let { south.remove(it); south.revalidate(); south.repaint() }
        promptRow = null
        promptAbout = null
        promptOnClose?.let { close -> promptOnClose = null; close() }
    }

    /** EDT. A notice from VeriClass itself (not the tutor), e.g. a project folder that will cause trouble. */
    fun addNotice(markdown: String) = addMessage(Role.NOTICE, markdown)

    /** Follow the lab's progress from the replies the server sends (decisions, "you are on step N"). */
    private fun trackStep(reply: String) {
        Regex("""approved step (\d+)""").find(reply)?.let { steps.current = it.groupValues[1].toInt() + 1 }
        Regex("""You are now on step (\d+)""").find(reply)?.let { steps.current = it.groupValues[1].toInt() }
        if (reply.contains("finished all the steps")) steps.current = steps.total + 1
    }

    /**
     * Stream the tutor's reply to [question]. [reaskModel]: the student asked
     * this question again with that (stronger) model; the server answers it
     * from the same point in the conversation and stores no second question.
     */
    private fun streamReply(
        question: String,
        reaskModel: String?,
        attachment: PendingAttachment? = null,
        /** False when the question is already in the student's journal. */
        traceQuestion: Boolean = true,
        /** EDT, when the reply is complete. */
        onDone: (() -> Unit)? = null,
    ) {
        removeReaskButton()
        val label = reaskModel?.let { "Tutor · $it" } ?: Role.TUTOR.label
        val reply = MessageBubble(Role.TUTOR, label).apply { setMarkdown("…") }
        addRow(reply)
        scrollToBottom()
        foreground++
        updateBusy()
        // EDT only. A reply waiting for the teacher frees the box early; then once only.
        var released = false
        val release = {
            if (!released) {
                released = true
                foreground--
                updateBusy()
            }
        }

        val buffer = StringBuilder()
        var failed = false
        var canReaskWith: String? = null
        // Re-render at most every 80 ms while tokens stream in.
        val render = Timer(80) { reply.setMarkdown(buffer.toString().ifBlank { "…" }); scrollToBottom() }
            .apply { isRepeats = false }

        ApplicationManager.getApplication().executeOnPooledThread {
            try {
                val attached = attachment?.let { runCatching { it.complete() }.getOrNull() }
                canReaskWith = api.ask(token, sessionId, question, cancelled, reask = reaskModel != null,
                    attachment = attached,
                    // The flow shows the transcript, so a late answer from the teacher still arrives.
                    transcript = flow?.history == true,
                    onReviewWait = { ApplicationManager.getApplication().invokeLater { release() } }) { chunk ->
                    ApplicationManager.getApplication().invokeLater {
                        buffer.append(chunk)
                        render.restart()
                    }
                }
            } catch (e: VeriClassApiException) {
                failed = true
                ApplicationManager.getApplication().invokeLater { buffer.append("\n\n⚠️ ${e.message}") }
            } catch (e: Exception) {
                failed = true
                ApplicationManager.getApplication().invokeLater {
                    buffer.append("\n\n⚠️ Could not reach the tutor. Is the backend running? (${e.message})")
                }
            } finally {
                ApplicationManager.getApplication().invokeLater {
                    render.stop()
                    reply.setMarkdown(buffer.toString().ifBlank { "⚠️ No reply." })
                    trackStep(buffer.toString())
                    canReaskWith?.takeIf { !failed && buffer.isNotBlank() }?.let { addReaskButton(question, it) }
                    scrollToBottom()
                    release()
                    val answer = buffer.toString()
                    if (!failed && answer.isNotBlank()) flow?.recordTutor(answer)
                    trace?.let { t ->
                        ApplicationManager.getApplication().executeOnPooledThread {
                            // Asking again stores no new question on the server, so none here either.
                            if (reaskModel == null && traceQuestion) t.chat(fromStudent = true, text = question, delivered = !failed)
                            if (answer.isNotBlank()) t.chat(fromStudent = false, text = answer, delivered = !failed)
                        }
                    }
                    onDone?.invoke()
                }
            }
        }
    }

    /** EDT. "Not detailed enough? Ask Sonnet 5.5" under the reply just finished. */
    private fun addReaskButton(question: String, model: String) {
        val button = JButton("Not detailed enough? Ask $model").apply {
            toolTipText = "Send the same question to $model for a more detailed answer"
            addActionListener {
                if (sendButton.isEnabled) streamReply(question, reaskModel = model)
            }
        }
        val row = JPanel(FlowLayout(FlowLayout.LEFT, 0, 0)).apply {
            isOpaque = false
            alignmentX = Component.LEFT_ALIGNMENT
            border = JBUI.Borders.empty(0, 0, 4, 32)
            add(button)
        }
        reaskRow = row
        column.add(row)
        column.revalidate()
    }

    private fun removeReaskButton() {
        reaskRow?.let { column.remove(it); column.revalidate(); column.repaint() }
        reaskRow = null
    }

    private fun updateBusy() {
        val busy = foreground > 0 || routing
        reaskRow?.components?.forEach { it.isEnabled = !busy }
        sendButton.isEnabled = !busy
        sendButton.text = if (busy) "…" else "Send"
        input.isEnabled = !busy
        if (!busy) input.requestFocusInWindow()
    }

    // --- the lab flow's view -------------------------------------------------------

    /** How [LabFlow] shows things here (any thread; it all happens on the EDT, in order). */
    val labView: LabView = object : LabView {
        override fun show(author: String, kind: String, markdown: String, buttons: List<LabButton>): Shown {
            val row = AtomicReference<JComponent?>()
            onEdt { row.set(addLabMessage(author, kind, markdown, buttons)) }
            return Shown {
                onEdt {
                    row.getAndSet(null)?.let { column.remove(it); column.revalidate(); column.repaint() }
                }
            }
        }

        override fun outputBox(title: String, prefill: String, onSend: (String) -> Unit, onClose: () -> Unit) =
            onEdt { showOutputBox(title, prefill, onSend, onClose) }

        override fun interrupt(what: Set<Interrupt>) = onEdt {
            if (promptAbout in what) removePrompt()
        }

        override fun introDone(replayed: Boolean) = onEdt {
            afterIntro?.invoke(replayed)
            if (replayed) scrollToBottom() else scrollToTop()
        }
    }

    private fun onEdt(task: () -> Unit) = ApplicationManager.getApplication().invokeLater {
        if (!disposed) task()
    }

    /** EDT. A message the flow shows; returns the row of [buttons] under it (null: none). */
    private fun addLabMessage(author: String, kind: String, markdown: String, buttons: List<LabButton>): JComponent? {
        val role = when {
            author == "student" -> Role.USER
            kind == "brief" -> Role.EXERCISE
            kind == "step" -> Role.STEP
            kind == "text" && author == "tutor" -> Role.TUTOR
            else -> Role.LAB
        }
        addMessage(role, if (author == "student" && kind == "output") fenced(markdown) else markdown)
        if (buttons.isEmpty()) {
            scrollToBottom()
            return null
        }
        val row = JPanel(FlowLayout(FlowLayout.LEFT, JBUI.scale(6), 0)).apply {
            isOpaque = false
            alignmentX = Component.LEFT_ALIGNMENT
            border = JBUI.Borders.empty(0, 0, 6, 32)
            for (b in buttons) add(JButton(b.label).apply { addActionListener { b.onClick() } })
        }
        column.add(row)
        column.revalidate()
        scrollToBottom()
        return row
    }

    /**
     * EDT. A class-paced step's "Done" box above the message box: [prefill] (what
     * the terminal printed) to check, edit or replace, then send to [onSend].
     */
    private fun showOutputBox(title: String, prefill: String, onSend: (String) -> Unit, onClose: () -> Unit) {
        removePrompt()
        val area = object : JBTextArea(prefill, 10, 0) {
            override fun paste() {
                onPaste?.let { report ->
                    runCatching { CopyPasteManager.getInstance().getContents<String>(DataFlavor.stringFlavor) }
                        .getOrNull()?.takeIf { it.isNotEmpty() }?.let(report)
                }
                super.paste()
            }
        }.apply {
            font = Font(Font.MONOSPACED, Font.PLAIN, UIUtil.getLabelFont().size)
            border = JBUI.Borders.empty(4)
            caretPosition = 0
        }
        val error = JLabel(" ").apply { foreground = JBColor.RED }
        val send = JButton(texts.send()).apply {
            addActionListener {
                val output = area.text.trim('\n', '\r')
                if (output.isBlank()) {
                    error.text = texts.pasteFirst()
                    return@addActionListener
                }
                promptOnClose = null // sent, not closed
                removePrompt()
                addMessage(Role.USER, fenced(output))
                scrollToBottom()
                trace?.let { t -> ApplicationManager.getApplication().executeOnPooledThread { t.chat(fromStudent = true, text = output, delivered = true) } }
                onSend(output)
            }
        }
        val panel = JPanel(BorderLayout(0, JBUI.scale(4))).apply {
            isOpaque = true
            background = JBColor(Color(0xFFF4D6), Color(0x4A3F22))
            border = JBUI.Borders.empty(6, 8)
            add(JLabel("<html>${com.intellij.openapi.util.text.StringUtil.escapeXmlEntities(title)}</html>"), BorderLayout.NORTH)
            add(JBScrollPane(area).apply { preferredSize = Dimension(0, JBUI.scale(170)) }, BorderLayout.CENTER)
            add(JPanel(FlowLayout(FlowLayout.LEFT, JBUI.scale(6), 0)).apply {
                isOpaque = false
                add(send)
                add(JButton(texts.cancel()).apply { addActionListener { removePrompt() } })
                add(error)
            }, BorderLayout.SOUTH)
        }
        promptRow = panel
        promptAbout = Interrupt.STEP
        promptOnClose = onClose
        south.add(panel, BorderLayout.SOUTH)
        south.revalidate()
        south.repaint()
        area.requestFocusInWindow()
    }

    private fun fenced(text: String) = "```\n${text.trimEnd()}\n```"

    private fun addRow(bubble: MessageBubble) {
        // Students' messages sit to the right, the tutor's and the brief to the left.
        val row = JPanel(BorderLayout()).apply {
            isOpaque = false
            alignmentX = Component.LEFT_ALIGNMENT
            border = when (bubble.role) {
                Role.USER -> JBUI.Borders.empty(4, 48, 4, 0)
                Role.TUTOR, Role.LAB -> JBUI.Borders.empty(4, 0, 4, 32)
                Role.EXERCISE, Role.STEP, Role.NOTICE -> JBUI.Borders.empty(4, 0, 8, 0)
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

    @Volatile private var disposed = false

    override fun dispose() {
        disposed = true
        cancelled.set(true)
        flow?.dispose()
    }

    // --- message bubble ---------------------------------------------------------

    /** One message: a role label and Markdown content, with copyable code blocks. */
    class MessageBubble(val role: Role, label: String = role.label) : JPanel(BorderLayout()) {
        private val body = JPanel().apply {
            layout = BoxLayout(this, BoxLayout.Y_AXIS)
            isOpaque = false
        }

        init {
            background = when (role) {
                Role.USER -> JBColor(Color(0xE3EEFC), Color(0x2B3A4F))
                Role.TUTOR -> JBColor(Color(0xF4F5F7), Color(0x30333A))
                Role.EXERCISE, Role.STEP -> JBColor(Color(0xFFF8E1), Color(0x3A3524))
                Role.NOTICE -> JBColor(Color(0xFFE9D6), Color(0x4A3322))
                Role.LAB -> JBColor(Color(0xEAF4EC), Color(0x2D3B33))
            }
            isOpaque = true
            border = BorderFactory.createCompoundBorder(
                JBUI.Borders.customLine(JBColor(Color(0xD9DEE6), Color(0x454A52)), 1),
                JBUI.Borders.empty(6, 10, 8, 10),
            )
            add(JLabel(label).apply {
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
            // Hebrew replies need a right-to-left base direction; otherwise the
            // embedded English terms (df.shape, AttributeError) start each line
            // and the Hebrew words around them come out in the wrong order.
            val rtl = isMostlyHebrew(md)
            if (rtl) {
                componentOrientation = ComponentOrientation.RIGHT_TO_LEFT
                document.putProperty(TextAttribute.RUN_DIRECTION, TextAttribute.RUN_DIRECTION_RTL)
            }
            val align = if (rtl) "text-align:right;" else ""
            text = "<html><body style=\"font-family:${f.family};font-size:${f.size}pt;margin:0;$align\">" +
                MarkdownLite.toHtml(md, hardBreaks = role != Role.EXERCISE && role != Role.STEP) + "</body></html>"
        }

        /** True when Hebrew letters dominate, ignoring `inline code` (identifiers are Latin). */
        private fun isMostlyHebrew(md: String): Boolean {
            val prose = md.replace(Regex("`[^`]*`"), "")
            val hebrew = prose.count { it in '\u0590'..'\u05FF' }
            val latin = prose.count { it in 'A'..'Z' || it in 'a'..'z' }
            return hebrew > 0 && hebrew * 2 >= latin
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
                    PasteSources.noteCopy(code, "tutor")
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
        private const val MIN_INPUT_ROWS = 3
        private const val MAX_INPUT_ROWS = 8

        /** Enter sends; Shift+Enter starts a new line (a text area has no binding for it). */
        internal fun installSendKeys(area: JTextComponent, onSend: () -> Unit) {
            area.inputMap.put(KeyStroke.getKeyStroke(KeyEvent.VK_ENTER, 0), "vericlass-send")
            area.actionMap.put("vericlass-send", object : AbstractAction() {
                override fun actionPerformed(e: ActionEvent) = onSend()
            })
            area.inputMap.put(KeyStroke.getKeyStroke(KeyEvent.VK_ENTER, InputEvent.SHIFT_DOWN_MASK), "vericlass-newline")
            area.actionMap.put("vericlass-newline", object : AbstractAction() {
                override fun actionPerformed(e: ActionEvent) {
                    if (area.isEditable && area.isEnabled) area.replaceSelection("\n")
                }
            })
        }

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
