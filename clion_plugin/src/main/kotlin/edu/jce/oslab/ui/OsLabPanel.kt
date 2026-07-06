package edu.jce.oslab.ui

import com.intellij.openapi.Disposable
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.project.Project
import com.intellij.ui.JBSplitter
import com.intellij.openapi.util.Disposer
import com.intellij.ui.JBColor
import com.intellij.ui.ScrollPaneFactory
import com.intellij.ui.components.JBLabel
import com.intellij.util.ui.JBUI
import edu.jce.oslab.api.ClientConfig
import edu.jce.oslab.api.Exercise
import edu.jce.oslab.api.LoginResponse
import edu.jce.oslab.api.OsLabApiClient
import edu.jce.oslab.api.OsLabApiException
import edu.jce.oslab.api.SessionResponse
import edu.jce.oslab.exam.ExamBanner
import edu.jce.oslab.exam.ExamGuard
import edu.jce.oslab.ide.ExerciseScaffolder
import edu.jce.oslab.probe.ProbePoller
import edu.jce.oslab.settings.OsLabSettings
import java.awt.BorderLayout
import java.awt.Component
import java.awt.FlowLayout
import javax.swing.BorderFactory
import javax.swing.Box
import javax.swing.JButton
import javax.swing.JPanel
import javax.swing.ScrollPaneConstants

/**
 * Root of the OS Lab tool window. Owns the login → session flow: authenticate,
 * start (or resume) a session, load the variant's exercise, ask the backend
 * which behavior to run (chat vs. ide), then build the session UI and start the
 * probe poller.
 */
class OsLabPanel(
    private val project: Project,
    private val parent: Disposable,
) : JPanel(BorderLayout()) {

    private val api = OsLabApiClient()
    private val loginPanel = LoginPanel(::doLogin)
    // Everything tied to one logged-in session (chat, probe poller, exam guard)
    // is registered to this child disposable so a re-login tears the previous
    // session down completely — otherwise a second login stacks a second
    // forever-running ProbePoller and re-attaches exam window listeners.
    private var sessionDisposable: Disposable? = null

    init {
        add(loginPanel, BorderLayout.CENTER)

        val devCode = OsLabSettings.instance.devLoginCode
        if (devCode.isNotEmpty()) {
            loginPanel.setBusy(true)
            doLogin(devCode)
        }
    }

    // --- login flow -------------------------------------------------------

    private fun doLogin(code: String) {
        ApplicationManager.getApplication().executeOnPooledThread {
            try {
                val login = api.login(code)
                val session = api.startSession(login.token)
                val exercise = api.activeExercise(session.variant, login.token)
                val config = api.clientConfig()
                ApplicationManager.getApplication().invokeLater {
                    if (project.isDisposed) return@invokeLater
                    buildSession(login, session, exercise, config)
                }
            } catch (e: OsLabApiException) {
                ApplicationManager.getApplication().invokeLater { loginPanel.setError(e.message ?: "Login failed.") }
            } catch (e: Exception) {
                ApplicationManager.getApplication().invokeLater {
                    loginPanel.setError("Can't reach the backend at ${OsLabSettings.instance.backendUrl}. (${e.message})")
                }
            }
        }
    }

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
        val sessionScope = Disposer.newDisposable("oslab-session")
        Disposer.register(parent, sessionScope)
        sessionDisposable = sessionScope

        // North stack: an (initially hidden) exam warning banner above the header.
        // BorderLayout stretches both to the full tool-window width.
        val banner = ExamBanner()
        val north = JPanel(BorderLayout()).apply {
            add(banner, BorderLayout.NORTH)
            add(header(login, session, config), BorderLayout.CENTER)
        }
        add(north, BorderLayout.NORTH)

        val chat = ChatPanel(api, login.token, session.session_id, sessionScope)

        val column = ScrollableColumn().apply {
            add(BriefingPanel(exercise, session.variant, session.mode).apply {
                alignmentX = Component.LEFT_ALIGNMENT
            })
            if (config.isIdeMode && exercise.variant != null) {
                add(TestChecklistPanel(exercise.variant).apply { alignmentX = Component.LEFT_ALIGNMENT })
            }
            if (exercise.welcome_suggestions.isNotEmpty()) {
                add(suggestionChips(exercise.welcome_suggestions, chat))
            }
            add(Box.createVerticalGlue())
        }
        val topScroll = ScrollPaneFactory.createScrollPane(
            column,
            ScrollPaneConstants.VERTICAL_SCROLLBAR_AS_NEEDED,
            ScrollPaneConstants.HORIZONTAL_SCROLLBAR_NEVER,
        )

        val splitter = JBSplitter(true, "oslab.split.proportion", 0.45f).apply {
            firstComponent = topScroll
            secondComponent = chat
        }
        add(splitter, BorderLayout.CENTER)

        if (config.isIdeMode) {
            ExerciseScaffolder.scaffold(project, config.scaffold_filename, exercise)
        }

        ProbePoller(api, session.session_id, login.token, config.poll_interval_ms.toLong(), sessionScope)

        // Exam mode: arm the proctor (full screen + leave-the-IDE detection).
        // Scoped to sessionScope, so a re-login disposes it before re-arming —
        // no double-attached window listeners or duplicate full-screen watchdogs.
        if (config.isExamMode) {
            ExamGuard(
                project, api, session.session_id, login.token, config,
                onViolation = { count, reason -> banner.show(count, reason) },
                parent = sessionScope,
            )
        }

        revalidate()
        repaint()
    }

    private fun header(login: LoginResponse, session: SessionResponse, config: ClientConfig): JPanel {
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
        }
    }

    private fun suggestionChips(suggestions: List<String>, chat: ChatPanel): JPanel {
        val panel = JPanel(FlowLayout(FlowLayout.LEFT, JBUI.scale(6), JBUI.scale(4))).apply {
            alignmentX = Component.LEFT_ALIGNMENT
            border = JBUI.Borders.empty(0, 6, 8, 6)
        }
        for (s in suggestions) {
            panel.add(
                JButton(s).apply {
                    toolTipText = "Ask: $s"
                    addActionListener { chat.submit(s) }
                },
            )
        }
        return panel
    }

    private fun esc(s: String): String =
        com.intellij.openapi.util.text.StringUtil.escapeXmlEntities(s)
}
