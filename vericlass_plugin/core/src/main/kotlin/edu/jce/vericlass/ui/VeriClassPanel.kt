package edu.jce.vericlass.ui

import com.intellij.openapi.Disposable
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.project.Project
import com.intellij.openapi.util.Disposer
import com.intellij.ui.JBColor
import com.intellij.ui.components.JBLabel
import com.intellij.util.ui.JBUI
import edu.jce.vericlass.api.ClientConfig
import edu.jce.vericlass.api.Exercise
import edu.jce.vericlass.api.LoginResponse
import edu.jce.vericlass.api.VeriClassApiClient
import edu.jce.vericlass.api.VeriClassApiException
import edu.jce.vericlass.api.SessionResponse
import edu.jce.vericlass.exam.ExamBanner
import edu.jce.vericlass.exam.ExamGuard
import edu.jce.vericlass.ide.CheckRunner
import edu.jce.vericlass.ide.ExerciseScaffolder
import edu.jce.vericlass.ide.RunReporter
import edu.jce.vericlass.ide.SubmissionCollector
import edu.jce.vericlass.probe.ProbePoller
import edu.jce.vericlass.settings.VeriClassSettings
import edu.jce.vericlass.terminal.VeriClassSessionService
import edu.jce.vericlass.trace.SessionTrace
import com.intellij.openapi.fileChooser.FileChooserFactory
import com.intellij.openapi.fileChooser.FileSaverDescriptor
import com.intellij.openapi.vfs.VirtualFile
import java.awt.BorderLayout
import java.awt.FlowLayout
import javax.swing.BorderFactory
import javax.swing.JButton
import javax.swing.JPanel
import javax.swing.Timer

/**
 * Root of the VeriClass tool window. Owns the login → session flow: authenticate,
 * start (or resume) a session, load the variant's exercise, ask the backend
 * which behavior to run (chat vs. ide), then build the session UI and start the
 * probe poller.
 */
class VeriClassPanel(
    private val project: Project,
    private val parent: Disposable,
) : JPanel(BorderLayout()) {

    private val api = VeriClassApiClient()
    private val loginPanel = LoginPanel(::doLogin)
    // Everything tied to one logged-in session (chat, probe poller, exam guard)
    // is registered to this child disposable so a re-login tears the previous
    // session down completely — otherwise a second login stacks a second
    // forever-running ProbePoller and re-attaches exam window listeners.
    private var sessionDisposable: Disposable? = null

    init {
        add(loginPanel, BorderLayout.CENTER)

        // Auto-login precedence: an explicit per-machine setting wins; otherwise
        // ask the backend for a dev code (DEV_AUTO_LOGIN_CODE) so no per-student
        // setup is needed — same convenience as the Chainlit student app.
        // Dev logins use the default password, the code itself.
        val localCode = VeriClassSettings.instance.devLoginCode
        if (localCode.isNotEmpty()) {
            loginPanel.setBusy(true)
            doLogin(localCode, localCode)
        } else {
            maybeBackendAutoLogin()
        }
    }

    /** Off the EDT: fetch the (dev-only) auto-login code from the backend and, if
     *  present, log in with it. No-op in exam/production where it's empty. */
    private fun maybeBackendAutoLogin() {
        ApplicationManager.getApplication().executeOnPooledThread {
            val code = try {
                api.clientConfig().dev_auto_login_code
            } catch (e: Exception) {
                ""
            }
            if (code.isNotBlank()) {
                ApplicationManager.getApplication().invokeLater {
                    if (project.isDisposed) return@invokeLater
                    loginPanel.setBusy(true)
                    doLogin(code, code)
                }
            }
        }
    }

    // --- login flow -------------------------------------------------------

    // The course/exercise picker while it is on screen, so errors show there.
    private var chooser: ChoosePanel? = null

    private fun doLogin(code: String, password: String) {
        ApplicationManager.getApplication().executeOnPooledThread {
            try {
                val login = api.login(code, password)
                ApplicationManager.getApplication().invokeLater {
                    if (project.isDisposed) return@invokeLater
                    afterLogin(login)
                }
            } catch (e: Exception) {
                ApplicationManager.getApplication().invokeLater { loginPanel.setError(errorText(e, "Login failed.")) }
            }
        }
    }

    /** No course, or one course with one exercise: open it. Otherwise let the student pick. */
    private fun afterLogin(login: LoginResponse) {
        val auto = ChoosePanel.autoChoice(login.courses)
        if (login.courses.isEmpty() || auto != null) {
            openExercise(login, auto?.first, auto?.second)
            return
        }
        val panel = ChoosePanel(
            login.username,
            login.courses,
            onChoose = { courseId, exerciseId -> openExercise(login, courseId, exerciseId) },
            onBack = ::showLogin,
        )
        chooser = panel
        removeAll()
        add(panel, BorderLayout.CENTER)
        revalidate()
        repaint()
    }

    private fun showLogin() {
        chooser = null
        removeAll()
        loginPanel.setBusy(false)
        add(loginPanel, BorderLayout.CENTER)
        revalidate()
        repaint()
    }

    private fun openExercise(login: LoginResponse, courseId: String?, exerciseId: String?) {
        ApplicationManager.getApplication().executeOnPooledThread {
            try {
                val session = api.startSession(login.token, courseId, exerciseId)
                val exercise = api.sessionExercise(session, login.token)
                val config = api.clientConfig(session.exercise_id)
                ApplicationManager.getApplication().invokeLater {
                    if (project.isDisposed) return@invokeLater
                    chooser = null
                    buildSession(login, session, exercise, config)
                }
            } catch (e: Exception) {
                ApplicationManager.getApplication().invokeLater {
                    val message = errorText(e, "Could not open the exercise.")
                    chooser?.setError(message) ?: loginPanel.setError(message)
                }
            }
        }
    }

    private fun errorText(e: Exception, fallback: String): String =
        if (e is VeriClassApiException) e.message ?: fallback
        else "Can't reach the backend at ${VeriClassSettings.instance.backendUrl}. (${e.message})"

    // --- session UI -------------------------------------------------------

    private fun buildSession(
        login: LoginResponse,
        session: SessionResponse,
        exercise: Exercise,
        config: ClientConfig,
    ) {
        removeAll()

        // Tear down the previous session's background work (poller/chat/guard)
        // before building the new one, then scope everything to a fresh child.
        sessionDisposable?.let { Disposer.dispose(it) }
        val sessionScope = Disposer.newDisposable("vericlass-session")
        Disposer.register(parent, sessionScope)
        sessionDisposable = sessionScope

        // Journal + outbox for everything this session reports (terminal, exam
        // events, pastes, chat), so the student can export it if it didn't arrive.
        val trace = SessionTrace(api, login.token, session.session_id, login.username, session.trace_key, sessionScope)

        // North stack: an (initially hidden) exam warning banner above the header.
        // BorderLayout stretches both to the full tool-window width.
        val banner = ExamBanner()
        val north = JPanel(BorderLayout()).apply {
            add(banner, BorderLayout.NORTH)
            add(header(login, session, config, exercise, trace, sessionScope), BorderLayout.CENTER)
        }
        add(north, BorderLayout.NORTH)

        // Pastes into the chat / terminal go to the exam guard, which exists only in exam mode.
        var guard: ExamGuard? = null
        val onPaste: (String, String) -> Unit = { target, text -> guard?.onPaste(target, text, null) }

        // One scrolling conversation: the exercise brief is the first message;
        // students scroll up to read it again.
        val steps = ChatPanel.StepState(exercise.steps_total, exercise.step_current)
        val chat = ChatPanel(
            api, login.token, session.session_id, sessionScope, trace,
            onPaste = { onPaste("chat", it) },
            steps = steps,
            attachments = { stepAttachment(exercise) },
        )
        chat.addMessage(ChatPanel.Role.EXERCISE, Briefing.markdown(exercise, session.variant))
        nonEnglishPathNotice()?.let(chat::addNotice)
        if (config.isIdeMode && exercise.variant != null) {
            chat.addComponent(TestChecklistPanel(exercise.variant))
        }
        chat.setSuggestions(exercise.welcome_suggestions)
        chat.scrollToTop()
        add(chat, BorderLayout.CENTER)

        if (config.isIdeMode) {
            ExerciseScaffolder.scaffold(project, config.scaffold_filename, exercise)
        }

        ProbePoller(api, session.session_id, login.token, config.poll_interval_ms.toLong(), sessionScope)

        // Start the VeriClass Terminal (bottom tool window) for this session; it
        // shuts down with the session (re-login, project close).
        val sessions = VeriClassSessionService.getInstance(project)
        sessions.publish(VeriClassSessionService.Active(api, login.token, session.session_id, exercise, config, trace, onPaste))
        Disposer.register(sessionScope) { if (!project.isDisposed) sessions.publish(null) }

        // Exam mode: arm the proctor (full screen + leave-the-IDE detection).
        // Scoped to sessionScope, so a re-login disposes it before re-arming —
        // no double-attached window listeners or duplicate full-screen watchdogs.
        if (config.isExamMode) {
            guard = ExamGuard(
                project, api, trace, login.token, config,
                onViolation = { count, reason -> banner.show(count, reason) },
                parent = sessionScope,
            )
        }

        revalidate()
        repaint()
    }

    /**
     * EDT. What a step submission carries for the teacher: the open file and the
     * Run console now, and the exercise's check command's output (run off the EDT).
     */
    private fun stepAttachment(exercise: Exercise): ChatPanel.PendingAttachment {
        val work = SubmissionCollector.collect(project)
        val command = exercise.check_command
        return ChatPanel.PendingAttachment {
            mapOf(
                "filename" to work.filename,
                "source" to work.source,
                "console" to work.console,
                "check_output" to CheckRunner.run(project, command),
            )
        }
    }

    /**
     * A project folder whose path has non-English letters makes the terminal's
     * `cd` fail (seen in class in October 2026), so say so up front.
     */
    private fun nonEnglishPathNotice(): String? {
        val path = project.basePath ?: return null
        if (path.all { it.code < 128 }) return null
        return "Your project folder's path has letters that aren't English:\n\n`$path`\n\n" +
            "Some terminal commands (like `cd`) will fail there. Move the project to a folder with an " +
            "English name, for example `C:/VeriClass/lab` or `~/VeriClass/lab`, and open it again.\n\n" +
            "בנתיב של תיקיית הפרויקט יש אותיות שאינן באנגלית, ולכן חלק מהפקודות בטרמינל (כמו `cd`) ייכשלו. " +
            "העבירו את הפרויקט לתיקייה עם שם באנגלית ופתחו אותו מחדש."
    }

    private fun header(
        login: LoginResponse,
        session: SessionResponse,
        config: ClientConfig,
        exercise: Exercise,
        trace: SessionTrace,
        scope: Disposable,
    ): JPanel {
        val modeTag = if (config.isIdeMode) "ide" else "chat"
        val label = JBLabel(
            "<html>👤 <b>${esc(login.username)}</b> &middot; variant <b>${esc(session.variant)}</b>" +
                " &middot; mode <b>${esc(session.mode)}</b> &middot; client <b>$modeTag</b></html>",
        )
        return JPanel(BorderLayout()).apply {
            border = BorderFactory.createCompoundBorder(
                JBUI.Borders.customLine(JBColor.border(), 0, 0, 1, 0),
                JBUI.Borders.empty(6, 10),
            )
            add(label, BorderLayout.WEST)
            add(submitControls(login, session, exercise, trace, scope), BorderLayout.EAST)
        }
    }

    /** "Send to teacher" and "Export my log" buttons + a small status label, right-aligned in the header. */
    private fun submitControls(
        login: LoginResponse,
        session: SessionResponse,
        exercise: Exercise,
        trace: SessionTrace,
        scope: Disposable,
    ): JPanel {
        val status = JBLabel("").apply {
            border = JBUI.Borders.emptyRight(8)
            foreground = JBColor.GRAY
        }
        val button = JButton("📤 Send to teacher").apply {
            toolTipText = "Send your current file and console output to the instructor"
        }
        val testInputs = exercise.variant?.test_inputs ?: emptyList()
        button.addActionListener {
            sendToTeacher(login.token, session.session_id, testInputs, button, status)
        }
        val export = JButton("💾 Export my log").apply {
            toolTipText = "Save your terminal, chat and exam log as a CSV file to hand in if something didn't reach the teacher"
            addActionListener { exportLog(trace, login.username, status) }
        }
        // Reports waiting for the server (network or tunnel down): tell the student, so they export.
        val unsent = JBLabel("").apply { foreground = JBColor.ORANGE }
        val timer = Timer(3_000) {
            val n = trace.pending
            unsent.text = if (n > 0) "⏳ $n not sent yet" else ""
            unsent.toolTipText = if (n > 0) "No connection to the teacher's server. Keep working; it is retried. " +
                "If it stays, use “Export my log” and hand in the file." else null
        }.apply { start() }
        Disposer.register(scope) { timer.stop() }
        return JPanel(FlowLayout(FlowLayout.RIGHT, JBUI.scale(4), 0)).apply {
            isOpaque = false
            add(unsent)
            add(status)
            add(export)
            add(button)
        }
    }

    /** Save this session's journal as CSV wherever the student chooses. */
    private fun exportLog(trace: SessionTrace, username: String, status: JBLabel) {
        val day = java.time.LocalDate.now()
        val name = "vericlass-log-${username.replace(Regex("[^\\p{L}\\p{N}_-]+"), "_")}-$day.csv"
        val descriptor = FileSaverDescriptor("VeriClass — Export My Log", "Save your log as a CSV file to hand in", "csv")
        val target = FileChooserFactory.getInstance().createSaveFileDialog(descriptor, project)
            .save(null as VirtualFile?, name)?.file ?: return
        ApplicationManager.getApplication().executeOnPooledThread {
            val result = try {
                target.outputStream().bufferedWriter(Charsets.UTF_8).use { trace.exportCsv(it) }
                true to "✓ Saved ${target.name} (${trace.journal.rowCount()} rows)"
            } catch (e: Exception) {
                false to "⚠ Couldn't save: ${e.message}"
            }
            ApplicationManager.getApplication().invokeLater {
                if (project.isDisposed) return@invokeLater
                status.foreground = if (result.first) JBColor.namedColor("Label.successForeground", JBColor.GREEN) else JBColor.RED
                status.text = result.second
                status.toolTipText = target.absolutePath
            }
        }
    }

    /**
     * Collect the student's source + console (on the EDT, where this runs) and
     * POST it to the backend on a pooled thread. The button is disabled and a
     * status label narrates progress so nothing blocks the UI.
     */
    private fun sendToTeacher(
        token: String,
        sessionId: String,
        testInputs: List<edu.jce.vericlass.api.TestInput>,
        button: JButton,
        status: JBLabel,
    ) {
        val submission = SubmissionCollector.collect(project)
        if (submission.isEmpty) {
            status.foreground = JBColor.RED
            status.text = "Open your code file first"
            return
        }
        button.isEnabled = false
        status.foreground = JBColor.GRAY
        status.text = "Compiling & running…"
        ApplicationManager.getApplication().executeOnPooledThread {
            // Compile + run against the variant's test cases OFF the EDT. Best
            // effort: a null result just means we submit source + console only.
            val run = try {
                RunReporter.run(submission.source, submission.filename, testInputs)
            } catch (e: Exception) {
                null
            }
            val (ok, message) = try {
                api.submitWork(token, sessionId, submission.filename, submission.source, submission.console, run)
                true to "✓ Sent to teacher"
            } catch (e: VeriClassApiException) {
                false to "⚠ ${e.message}"
            } catch (e: Exception) {
                false to "⚠ Couldn't reach the server"
            }
            ApplicationManager.getApplication().invokeLater {
                if (project.isDisposed) return@invokeLater
                status.foreground = if (ok) JBColor.namedColor("Label.successForeground", JBColor.GREEN) else JBColor.RED
                status.text = message
                button.isEnabled = true
            }
        }
    }

    private fun esc(s: String): String =
        com.intellij.openapi.util.text.StringUtil.escapeXmlEntities(s)
}
