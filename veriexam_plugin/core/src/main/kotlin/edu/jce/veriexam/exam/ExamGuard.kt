package edu.jce.veriexam.exam

import com.intellij.ide.AppLifecycleListener
import com.intellij.ide.IdeEventQueue
import com.intellij.notification.NotificationGroupManager
import com.intellij.notification.NotificationType
import com.intellij.openapi.Disposable
import com.intellij.openapi.actionSystem.ActionManager
import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.actionSystem.AnActionResult
import com.intellij.openapi.actionSystem.CommonDataKeys
import com.intellij.openapi.actionSystem.ex.AnActionListener
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.application.ApplicationNamesInfo
import com.intellij.openapi.diagnostic.thisLogger
import com.intellij.openapi.editor.Editor
import com.intellij.openapi.editor.EditorFactory
import com.intellij.openapi.editor.EditorKind
import com.intellij.openapi.editor.event.DocumentEvent
import com.intellij.openapi.editor.event.DocumentListener
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.fileEditor.FileEditorManager
import com.intellij.openapi.fileEditor.FileEditorManagerEvent
import com.intellij.openapi.fileEditor.FileEditorManagerListener
import com.intellij.openapi.ide.CopyPasteManager
import com.intellij.openapi.keymap.KeymapUtil
import com.intellij.openapi.project.Project
import com.intellij.openapi.project.ProjectCloseListener
import com.intellij.openapi.project.ProjectManager
import com.intellij.openapi.ui.DialogWrapperDialog
import com.intellij.openapi.util.Disposer
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.openapi.wm.ToolWindow
import com.intellij.openapi.wm.ToolWindowManager
import com.intellij.openapi.wm.WindowManager
import com.intellij.util.concurrency.AppExecutorUtil
import edu.jce.veriexam.api.ClientConfig
import edu.jce.veriexam.api.VeriExamApiClient
import edu.jce.veriexam.terminal.VeriExamTerminalToolWindowFactory
import edu.jce.veriexam.trace.SessionTrace
import java.awt.AWTEvent
import java.awt.Dialog
import java.awt.Frame
import java.awt.KeyboardFocusManager
import java.awt.Toolkit
import java.awt.Window
import java.awt.datatransfer.DataFlavor
import java.awt.event.AWTEventListener
import java.awt.event.InputEvent
import java.awt.event.KeyEvent
import java.awt.event.MouseEvent
import java.awt.event.WindowAdapter
import java.awt.event.WindowEvent
import java.awt.event.WindowFocusListener
import java.io.File
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong
import javax.swing.JFrame
import javax.swing.KeyStroke
import javax.swing.Timer

/**
 * The exam "proctor" on the student's side. While an exam session is live it:
 *
 *  - reports `exam_started` and puts the IDE in full screen (if configured);
 *  - watches the IDE frame and, the moment the student leaves it — switches to
 *    another app, minimizes, or exits full screen — reports that to the backend
 *    (which surfaces it on the teacher dashboard), warns the student, and
 *    re-asserts full screen / brings the IDE back to the front when they return;
 *  - keeps the window maximized: a smaller window ("restore down") is reported
 *    and undone, and on Windows the OS is asked which app is in front, so a
 *    switch is caught even without a focus event ([ExamWindowLock]);
 *  - allows only the editor, the VeriExam chat and the VeriExam Terminal: any
 *    other panel is closed and reported ([ExamPanelLock]), and so is any other
 *    window — a dialog, another project, a search popup — with how it was
 *    opened (the shortcut or click);
 *  - reports every editor tab opened, and every paste into the editor, the
 *    terminal or the chat with where its text came from ([PasteSources]);
 *  - sends a live status (focused, full screen, open panels / windows / tabs)
 *    with every heartbeat and on every change, for the dashboard's live grid;
 *  - reports `ide_closed` the moment the student closes the IDE or the exam
 *    project, instead of the teacher seeing "no signal" 45 s later.
 *
 * Reports go through [SessionTrace]: journaled locally, queued and retried.
 *
 * Key correctness detail: a [WindowEvent] whose `oppositeWindow` is non-null
 * means focus moved to *another window of our own IDE* (a probe dialog, the
 * settings dialog, a completion popup) — NOT the student leaving. Only
 * `oppositeWindow == null` means focus left the Java app entirely, which is the
 * real "left the IDE" signal. Filtering on that is what keeps the plugin's own
 * dialogs from raising false alarms. Other IDE windows are the window watcher's job.
 *
 * Stops cleanly when its parent [Disposable] (the session) is disposed.
 */
class ExamGuard(
    private val project: Project,
    private val api: VeriExamApiClient,
    private val trace: SessionTrace,
    private val token: String,
    private val config: ClientConfig,
    /** Updates the in-tool-window warning banner. Always invoked on the EDT. */
    private val onViolation: (count: Int, reason: String) -> Unit,
    parent: Disposable,
) : Disposable {

    // The running IDE's display name ("CLion" / "PyCharm") — so the same core
    // serves both plugins and the student sees the product they're actually in.
    private val ide = ApplicationNamesInfo.getInstance().productName
    private val sessionId = trace.sessionId
    private val allowedPanels = ExamPanelLock.allowedIds(config)

    private val stopped = AtomicBoolean(false)
    private val disposed = AtomicBoolean(false)
    // The IDE or project is closing: `ide_closed` was sent, and nothing more is.
    private val closing = AtomicBoolean(false)
    private val away = AtomicBoolean(false)
    private val awaySinceMs = AtomicLong(0L)
    private val violations = AtomicInteger(0)
    // So the full-screen watchdog reports an exit once, not every 2s tick.
    private val fullscreenExitReported = AtomicBoolean(false)
    // Only flag a full-screen *exit* once we've actually seen full screen engage.
    // Guards against the startup transition racing the first tick, and against
    // platforms where full screen never engages (we'd otherwise false-alarm).
    private val sawFullscreen = AtomicBoolean(false)
    /** Until when a full-screen animation may be running (no focus judgments before). */
    @Volatile private var transitionUntilMs = 0L
    // So "made the window smaller" is reported once until it's maximized again.
    private val unmaximizedReported = AtomicBoolean(false)
    // Watchdog ticks in a row with no IDE window focused: a leave whose focus event was lost.
    private var nowhereTicks = 0

    private val scheduler = AppExecutorUtil.getAppScheduledExecutorService()
    private var heartbeatFuture: ScheduledFuture<*>? = null
    private var watchdogFuture: ScheduledFuture<*>? = null
    @Volatile private var statusFuture: ScheduledFuture<*>? = null
    private var frame: JFrame? = null
    private var panelLock: ExamPanelLock? = null

    /** Other windows open right now (dialogs, other projects) → how they're shown on the dashboard. EDT only. */
    private val otherWindows = LinkedHashMap<Window, String>()

    /** The last action the student ran, to say how a panel or window was opened. */
    private class LastAction(val text: String, val input: InputEvent?, val atMs: Long)
    @Volatile private var lastAction: LastAction? = null

    // Paste into the editor: armed by the paste action, filled by the document listener.
    private var pasteEditor: Editor? = null
    private val pasted = StringBuilder()
    // "Paste from history" pastes after its popup closes, so wait for that editor's next change.
    private var historyPaste: Pair<Editor, Long>? = null

    /** The clipboard when the student left, to see whether it changed in another app. */
    private var clipboardAtLeave: String? = null

    private val focusListener = object : WindowFocusListener {
        override fun windowLostFocus(e: WindowEvent) {
            if (e.oppositeWindow != null) return // focus went to another IDE window — ignore
            // On macOS (full screen especially) a dialog of our own can take focus
            // with no opposite window. Look again once focus has settled: if one of
            // the IDE's windows has it, the student didn't leave (the window watcher
            // reports that window).
            checkLeftAfter(LEAVE_SETTLE_MS)
        }

        override fun windowGainedFocus(e: WindowEvent) {
            // Back from another app, or (after a leave we reported) from anywhere.
            if (e.oppositeWindow != null && !away.get()) return
            onReturned("focus_regained")
        }
    }

    private val stateListener = object : WindowAdapter() {
        override fun windowIconified(e: WindowEvent) = onLeft("minimized", "You minimized $ide.")
        override fun windowDeiconified(e: WindowEvent) = onReturned("window_restored")

        // "Restore down" keeps the IDE focused, so no focus event fires: watch the state.
        override fun windowStateChanged(e: WindowEvent) {
            if (config.isMaximizedMode && ExamWindowLock.isUnmaximize(e.oldState, e.newState)) {
                checkUnmaximizedAfter(LEAVE_SETTLE_MS)
            }
        }
    }

    private val windowWatcher = AWTEventListener { e ->
        if (e !is WindowEvent || stopped.get()) return@AWTEventListener
        when (e.id) {
            WindowEvent.WINDOW_OPENED -> onWindowOpened(e.window)
            WindowEvent.WINDOW_CLOSED -> onWindowClosed(e.window)
        }
    }

    init {
        Disposer.register(parent, this)
        if (config.isExamMode) start() else thisLogger().info("exam mode off — ExamGuard idle")
    }

    private fun start() {
        report("exam_started", detail = "exam client armed", awayMs = null)

        ApplicationManager.getApplication().messageBus.connect(this).apply {
            subscribe(AppLifecycleListener.TOPIC, object : AppLifecycleListener {
                override fun appClosing() = onClosing("closed $ide")
            })
            subscribe(ProjectCloseListener.TOPIC, object : ProjectCloseListener {
                override fun projectClosing(project: Project) {
                    if (project == this@ExamGuard.project) onClosing("closed the exam project")
                }
            })
        }

        ApplicationManager.getApplication().invokeLater {
            if (stopped.get() || project.isDisposed) return@invokeLater
            // Land the student in the tutor tool window, full screen, listening.
            toolWindow()?.activate(null)
            if (config.isMaximizedMode) WindowManager.getInstance().getFrame(project)?.let(ExamWindowLock::maximize)
            if (config.force_fullscreen) enterFullScreen()
            attachListeners()
            // Only the editor, the VeriExam chat and the VeriExam Terminal (checked + logged).
            panelLock = ExamPanelLock(project, allowedPanels, ::how, ::onPanelBlocked, parent = this)
            ToolWindowManager.getInstance(project).getToolWindow(VeriExamTerminalToolWindowFactory.ID)?.show()
            // Whatever is on the clipboard now was copied before the exam.
            PasteSources.noteOutside(clipboardText())
            sendStatusSoon()
        }

        val hb = config.heartbeat_ms.toLong().coerceAtLeast(5_000L)
        heartbeatFuture = scheduler.scheduleWithFixedDelay(::sendStatus, hb, hb, TimeUnit.MILLISECONDS)

        watchdogFuture = scheduler.scheduleWithFixedDelay(::watchdog, WATCHDOG_MS, WATCHDOG_MS, TimeUnit.MILLISECONDS)
    }

    /** EDT. */
    private fun attachListeners() {
        WindowManager.getInstance().getFrame(project)?.let { f ->
            frame = f
            f.addWindowFocusListener(focusListener)
            f.addWindowListener(stateListener)
            f.addWindowStateListener(stateListener)
        }
        Toolkit.getDefaultToolkit().addAWTEventListener(windowWatcher, AWTEvent.WINDOW_EVENT_MASK)

        ApplicationManager.getApplication().messageBus.connect(this)
            .subscribe(AnActionListener.TOPIC, actionListener)

        project.messageBus.connect(this).subscribe(
            FileEditorManagerListener.FILE_EDITOR_MANAGER,
            object : FileEditorManagerListener {
                override fun fileOpened(source: FileEditorManager, file: VirtualFile) {
                    val outside = !isInProject(file)
                    report("file_opened", displayPath(file) + if (outside) " (outside the project)" else "", null)
                    sendStatusSoon()
                }

                override fun fileClosed(source: FileEditorManager, file: VirtualFile) = sendStatusSoon()
                override fun selectionChanged(event: FileEditorManagerEvent) = sendStatusSoon()
            },
        )

        EditorFactory.getInstance().eventMulticaster.addDocumentListener(
            object : DocumentListener {
                override fun documentChanged(event: DocumentEvent) {
                    val text = event.newFragment
                    if (text.isEmpty()) return
                    if (pasteEditor?.document == event.document) {
                        pasted.append(text)
                        return
                    }
                    val (editor, until) = historyPaste ?: return
                    if (editor.document != event.document) return
                    historyPaste = null
                    if (System.currentTimeMillis() <= until) onEditorPaste(editor, text.toString())
                }
            },
            this,
        )

        CopyPasteManager.getInstance().addContentChangedListener(
            { _, newContents ->
                // Anything the IDE itself put on the clipboard (copy, cut, Copy buttons).
                val text = runCatching { newContents?.getTransferData(DataFlavor.stringFlavor) as? String }.getOrNull()
                if (!stopped.get()) PasteSources.noteCopy(text, "ide")
            },
            this,
        )
    }

    // --- actions: how things were opened, pastes, copies, popups -----------

    private val actionListener = object : AnActionListener {
        override fun beforeActionPerformed(action: AnAction, event: AnActionEvent) {
            if (stopped.get() || event.project != project) return
            val id = ActionManager.getInstance().getId(action) ?: action.javaClass.simpleName
            lastAction = LastAction(event.presentation.text?.takeIf { it.isNotBlank() } ?: id, event.inputEvent, System.currentTimeMillis())
            val editor = event.getData(CommonDataKeys.EDITOR)?.takeIf { it.editorKind == EditorKind.MAIN_EDITOR }
            when {
                id in PASTE_ACTIONS && editor != null -> {
                    pasteEditor = editor
                    pasted.setLength(0)
                }
                id in HISTORY_PASTE_ACTIONS && editor != null ->
                    historyPaste = editor to System.currentTimeMillis() + 60_000
                id in POPUP_ACTIONS -> evenWhenModal {
                    violation("other_window_opened", "${lastAction?.text ?: id} popup — ${how()}",
                        "Only the editor, the VeriExam chat and the VeriExam Terminal are allowed during the exam.")
                }
            }
        }

        override fun afterActionPerformed(action: AnAction, event: AnActionEvent, result: AnActionResult) {
            val editor = pasteEditor ?: return
            pasteEditor = null
            val text = pasted.toString()
            pasted.setLength(0)
            if (text.isNotEmpty()) onEditorPaste(editor, text)
        }
    }

    /** EDT. */
    private fun onEditorPaste(editor: Editor, text: String) {
        val file = FileDocumentManager.getInstance().getFile(editor.document)?.let(::displayPath)
        onPaste("editor", text, file)
    }

    /** Any thread. A paste into the editor, the VeriExam terminal or the chat box. */
    fun onPaste(target: String, text: String, file: String?) {
        if (stopped.get() || text.isBlank()) return
        val source = PasteSources.classify(text)
        ApplicationManager.getApplication().executeOnPooledThread { trace.paste(target, source, text, file) }
        if (source == "outside") {
            evenWhenModal {
                val count = violations.incrementAndGet()
                warnStudent(count, "You pasted text from outside $ide.")
            }
        }
    }

    /** EDT, from inside the key press or click that opened something. */
    private fun how(fallback: String = "opened by $ide itself (for example by running code)"): String {
        val action = lastAction?.takeIf { System.currentTimeMillis() - it.atMs < 1_500 }
        val input = describeInput(action?.input ?: IdeEventQueue.getInstance().trueCurrentEvent)
        return when {
            action != null && input != null -> "“${action.text}”, $input"
            action != null -> "“${action.text}”"
            input != null -> input
            else -> fallback
        }
    }

    private fun describeInput(e: AWTEvent?): String? = when (e) {
        is KeyEvent -> "keyboard " + KeymapUtil.getKeystrokeText(KeyStroke.getKeyStrokeForEvent(e))
        is MouseEvent -> when {
            e.component?.javaClass?.name?.contains("Stripe") == true -> "mouse click on its side-bar button"
            e.component?.javaClass?.name?.contains("Menu") == true -> "mouse, from a menu"
            else -> "mouse click"
        }
        else -> null
    }

    // --- panels and windows -------------------------------------------------

    /** EDT. A panel outside the allowlist was opened; [ExamPanelLock] already closed it. */
    private fun onPanelBlocked(tw: ToolWindow, how: String) {
        if (stopped.get()) return
        val name = tw.stripeTitle.takeIf { it.isNotBlank() } ?: tw.id
        if (tw.id == ExamPanelLock.STOCK_TERMINAL_ID) {
            violation("stock_terminal_opened", "tried to open the IDE's own Terminal — $how",
                "Use the VeriExam Terminal at the bottom; the IDE's own Terminal is off during the exam.")
            ToolWindowManager.getInstance(project).getToolWindow(VeriExamTerminalToolWindowFactory.ID)?.show()
        } else {
            violation("tool_window_opened", "$name — $how",
                "The $name panel is closed during the exam. Use only the editor, the VeriExam chat and the VeriExam Terminal.")
        }
        sendStatusSoon()
    }

    /** EDT (AWT event). */
    private fun onWindowOpened(w: Window) {
        val name = describeWindow(w) ?: return
        if (otherWindows.containsKey(w)) return
        otherWindows[w] = name
        violation("other_window_opened", "$name — ${how()}",
            "Close “$name”. Only the editor, the VeriExam chat and the VeriExam Terminal are allowed during the exam.")
        sendStatusSoon()
    }

    /** EDT (AWT event). */
    private fun onWindowClosed(w: Window) {
        val name = otherWindows.remove(w) ?: return
        report("other_window_closed", name, null)
        sendStatusSoon()
    }

    /** What to call [w] on the dashboard, or null when it isn't a window to report. */
    private fun describeWindow(w: Window): String? {
        if (w === frame) return null
        if (w is Frame) {
            val other = ProjectManager.getInstance().openProjects
                .firstOrNull { WindowManager.getInstance().getFrame(it) === w }
            if (other == project) return null
            return if (other != null) "another project window: ${other.name}"
            else "another window: ${w.title.orEmpty().ifBlank { w.javaClass.simpleName }}"
        }
        if (w !is Dialog) return null // popups, tooltips, completion lists
        val title = w.title.orEmpty().trim()
        if (title.startsWith("VeriExam")) return null // the plugin's own dialogs
        val wrapper = (w as? DialogWrapperDialog)?.dialogWrapper
        if (wrapper?.javaClass?.name?.startsWith("edu.jce.veriexam") == true) return null
        // The IDE's own progress dialogs (indexing, installing, loading) aren't the student's doing.
        if (wrapper?.javaClass?.name?.contains("Progress") == true) return null
        return when {
            title.isNotEmpty() -> "“$title” window"
            wrapper != null -> "a dialog (${wrapper.javaClass.simpleName})"
            else -> null // untitled heavyweight popups
        }
    }

    // --- leave / return ---------------------------------------------------

    /**
     * EDT. Decide whether focus really left the IDE, [delayMs] from now. While
     * macOS animates into or out of full screen the window has no focus for a
     * moment, so wait until the transition is over before judging.
     */
    private fun checkLeftAfter(delayMs: Int) {
        Timer(delayMs) {
            val transition = transitionUntilMs - System.currentTimeMillis()
            when {
                stopped.get() -> {}
                transition > 0 -> checkLeftAfter(transition.toInt() + LEAVE_SETTLE_MS)
                // Just dropped out of full screen (the green button): that animation
                // too; the watchdog reports the exit and restores full screen.
                config.force_fullscreen && sawFullscreen.get() && !fullscreenExitReported.get() &&
                    !ExamFullScreen.isFullScreen(project) -> {
                    transitionUntilMs = System.currentTimeMillis() + FULLSCREEN_TRANSITION_MS
                    checkLeftAfter(FULLSCREEN_TRANSITION_MS.toInt() + LEAVE_SETTLE_MS)
                }
                KeyboardFocusManager.getCurrentKeyboardFocusManager().activeWindow == null ->
                    onLeft("focus_lost", "You switched away from $ide.")
            }
        }.apply { isRepeats = false; start() }
    }

    /**
     * EDT. Marked away, but one of the IDE's windows has focus (and, on Windows,
     * no other app is in front): a return we didn't get an event for.
     */
    private fun reconcileFocus() {
        if (away.get() && KeyboardFocusManager.getCurrentKeyboardFocusManager().activeWindow != null &&
            ExamWindowLock.otherAppInFront() == null
        ) {
            onReturned("focus_regained")
        }
    }

    /**
     * EDT. Did the student leave without a focus event telling us? On Windows,
     * ask the OS which app is in front. Everywhere, two watchdog ticks in a row
     * with no IDE window focused count as leaving too.
     */
    private fun checkForeground() {
        if (System.currentTimeMillis() < transitionUntilMs) return
        val other = ExamWindowLock.otherAppInFront()
        if (other != null) {
            nowhereTicks = 0
            if (!away.get()) onLeft("other_app_in_front", "Another app is in front of $ide: ${other.describe()}")
            return
        }
        val nowhere = KeyboardFocusManager.getCurrentKeyboardFocusManager().activeWindow == null
        nowhereTicks = if (nowhere && !away.get()) nowhereTicks + 1 else 0
        if (nowhereTicks >= 2) {
            nowhereTicks = 0
            onLeft("focus_lost", "You switched away from $ide.")
        }
    }

    /** EDT. Look again once a state change (or the full-screen animation) has settled. */
    private fun checkUnmaximizedAfter(delayMs: Int) {
        Timer(delayMs) {
            val transition = transitionUntilMs - System.currentTimeMillis()
            when {
                stopped.get() || away.get() -> {}
                transition > 0 -> checkUnmaximizedAfter(transition.toInt() + LEAVE_SETTLE_MS)
                else -> checkMaximized()
            }
        }.apply { isRepeats = false; start() }
    }

    /** EDT. The window must fill the screen (maximized or full screen); re-maximize it if not. */
    private fun checkMaximized() {
        val f = frame ?: return
        if (System.currentTimeMillis() < transitionUntilMs) return
        if (ExamWindowLock.isLocked(f, ExamFullScreen.isFullScreen(project))) {
            if (unmaximizedReported.compareAndSet(true, false)) {
                report("window_maximized", detail = "maximized again", awayMs = null)
                sendStatusSoon()
            }
            return
        }
        if (unmaximizedReported.compareAndSet(false, true)) {
            violation("window_unmaximized",
                "made the window smaller (not maximized) — ${how("not through $ide (the window's restore button, a drag, or a system shortcut)")}",
                "You made $ide smaller. It has to stay maximized.")
            sendStatusSoon()
        }
        ExamWindowLock.maximize(f)
    }

    /** EDT. Full screen on, and no "left the IDE" while macOS animates it. */
    private fun enterFullScreen() {
        transitionUntilMs = System.currentTimeMillis() + FULLSCREEN_TRANSITION_MS
        ExamFullScreen.enter(project)
    }

    /** EDT (called from AWT window listeners). */
    private fun onLeft(kind: String, reason: String) {
        if (stopped.get()) return
        if (!away.compareAndSet(false, true)) return // already away — dedupe (e.g. minimize fires both events)
        awaySinceMs.set(System.currentTimeMillis())
        clipboardAtLeave = clipboardText()
        val count = violations.incrementAndGet()
        report(kind, detail = reason, awayMs = null)
        warnStudent(count, reason)
        sendStatusSoon()
    }

    /** EDT. */
    private fun onReturned(kind: String) {
        if (stopped.get()) return
        if (!away.compareAndSet(true, false)) return // wasn't away — ignore the matching second event
        val ms = (System.currentTimeMillis() - awaySinceMs.get()).coerceAtLeast(0)
        report(kind, detail = "returned to the IDE", awayMs = ms)
        // Copied something in another app while away: a paste of it is "from outside".
        clipboardText()?.let { if (it != clipboardAtLeave) PasteSources.noteOutside(it) }
        // Re-assert exam constraints now that they're back.
        toolWindow()?.activate(null)
        // The watchdog reports fullscreen_restored / window_maximized once it's back.
        if (config.isMaximizedMode) frame?.let(ExamWindowLock::maximize)
        if (config.force_fullscreen) enterFullScreen()
        frame?.toFront()
        sendStatusSoon()
    }

    /** EDT. Count, report and warn. */
    private fun violation(kind: String, detail: String, warning: String) {
        if (stopped.get()) return
        val count = violations.incrementAndGet()
        report(kind, detail = detail, awayMs = null)
        warnStudent(count, warning)
    }

    /** EDT. Updates the banner and pops a sticky balloon. */
    private fun warnStudent(count: Int, reason: String) {
        onViolation(count, reason)
        toolWindow()?.activate(null)
        val group = NotificationGroupManager.getInstance().getNotificationGroup("VeriExam Exam") ?: return
        group.createNotification(
            "Exam mode — stay in $ide",
            "$reason This was reported to your instructor (×$count).",
            NotificationType.WARNING,
        ).notify(project)
    }

    // --- live status ---------------------------------------------------------

    /** EDT. What the dashboard's live grid shows for this student. */
    private fun snapshot(): Map<String, Any?> {
        reconcileFocus()
        otherWindows.keys.filter { !it.isShowing }.forEach(::onWindowClosed)
        val twm = ToolWindowManager.getInstance(project)
        val fem = FileEditorManager.getInstance(project)
        val fullscreen = ExamFullScreen.isFullScreen(project)
        if (fullscreen) sawFullscreen.set(true)
        return mapOf(
            "focused" to !away.get(),
            "fullscreen" to fullscreen,
            // Maximized or full screen. Null when exam mode doesn't ask for it.
            "maximized" to frame?.takeIf { config.isMaximizedMode }?.let { ExamWindowLock.isLocked(it, fullscreen) },
            // Windows: the app the OS has in front, when it isn't the IDE.
            "app_in_front" to ExamWindowLock.otherAppInFront()?.describe(),
            // Don't flag "not full screen" where it was never asked for or never engaged.
            "fullscreen_supported" to (config.force_fullscreen && sawFullscreen.get()),
            "tool_windows" to twm.toolWindowIds.filter { twm.getToolWindow(it)?.isVisible == true },
            "forbidden_tool_windows" to (panelLock?.visibleForbidden() ?: emptyList()),
            "other_windows" to otherWindows.values.toList(),
            "open_files" to fem.openFiles.map(::displayPath),
            "active_file" to fem.selectedFiles.firstOrNull()?.let(::displayPath),
            "violations" to violations.get(),
            "unsent_reports" to trace.pending,
        )
    }

    /** Any thread: collect the status on the EDT, send it off it. */
    private fun sendStatus() {
        if (stopped.get()) return
        evenWhenModal {
            if (stopped.get() || project.isDisposed) return@evenWhenModal
            val status = snapshot()
            ApplicationManager.getApplication().executeOnPooledThread {
                api.proctorHeartbeat(sessionId, token, status)
            }
        }
    }

    /** A change worth showing at once; coalesces bursts (a dialog opening = several events). */
    private fun sendStatusSoon() {
        if (stopped.get()) return
        statusFuture?.cancel(false)
        statusFuture = scheduler.schedule(::sendStatus, 300, TimeUnit.MILLISECONDS)
    }

    /**
     * Every [WATCHDOG_MS] during the exam: another app in front (Windows) or a
     * lost focus event, a window that is no longer maximized, and a full-screen
     * exit that doesn't move focus (the macOS green button, Esc). The window is
     * put back each time. Skipped while the student is away in another app —
     * that's handled on their return, so we don't fight the OS.
     */
    private fun watchdog() {
        if (stopped.get()) return
        evenWhenModal {
            if (stopped.get() || project.isDisposed) return@evenWhenModal
            checkForeground()
            reconcileFocus()
            if (away.get()) return@evenWhenModal
            if (config.isMaximizedMode) checkMaximized()
            if (config.force_fullscreen) checkFullScreen()
        }
    }

    /** EDT. Report a full-screen exit once, and go back to full screen. */
    private fun checkFullScreen() {
        if (ExamFullScreen.isFullScreen(project)) {
            sawFullscreen.set(true)
            if (fullscreenExitReported.compareAndSet(true, false)) {
                report("fullscreen_restored", detail = "back in full screen", awayMs = null)
                sendStatusSoon()
            }
            return
        }
        // Not full screen. Only a violation if we'd previously gone full
        // screen — otherwise the platform just doesn't support it, or the
        // initial transition hasn't completed yet; keep trying quietly.
        if (sawFullscreen.get() && fullscreenExitReported.compareAndSet(false, true)) {
            violation("fullscreen_exited",
                "left full screen — ${how("not through $ide (the window's green button, or a system shortcut)")}",
                "You left full screen.")
            sendStatusSoon()
        }
        enterFullScreen()
    }

    /**
     * The IDE or the exam project is closing. Sent directly with a short timeout,
     * because the outbox stops with the IDE (it is in the student's journal
     * either way). Then quiet, so the closing windows don't report as "left the
     * IDE". If the IDE is still open a little later (the student cancelled a
     * "terminate the running process?" question), the exam goes on.
     */
    private fun onClosing(detail: String) {
        if (stopped.get() || !closing.compareAndSet(false, true)) return
        stopped.set(true)
        trace.proctorNow("ide_closed", detail, CLOSE_REPORT_MS)
        scheduler.schedule({
            if (!disposed.get() && !project.isDisposed && closing.compareAndSet(true, false)) {
                stopped.set(false)
                report("focus_regained", "$ide did not close after all", awayMs = null)
                sendStatusSoon()
            }
        }, CLOSE_CANCELLED_AFTER_S, TimeUnit.SECONDS)
    }

    // --- helpers ----------------------------------------------------------

    private fun report(kind: String, detail: String?, awayMs: Long?) {
        if (stopped.get()) return
        ApplicationManager.getApplication().executeOnPooledThread { trace.proctor(kind, detail, awayMs) }
    }

    private fun clipboardText(): String? =
        runCatching { CopyPasteManager.getInstance().getContents<String>(DataFlavor.stringFlavor) }.getOrNull()

    private fun isInProject(file: VirtualFile): Boolean {
        if (!file.isInLocalFileSystem) return true // IDE pages such as "What's New"
        val base = project.basePath ?: return true
        return File(file.path).canonicalPath.startsWith(File(base).canonicalPath)
    }

    private fun displayPath(file: VirtualFile): String {
        if (!file.isInLocalFileSystem) return file.presentableName
        val base = project.basePath ?: return file.name
        val rel = runCatching { File(file.path).canonicalFile.relativeTo(File(base).canonicalFile).path }.getOrNull()
        return if (rel == null || rel.startsWith("..")) file.path else rel.replace('\\', '/')
    }

    private fun toolWindow() = ToolWindowManager.getInstance(project).getToolWindow("VeriExam")

    override fun dispose() {
        disposed.set(true)
        stopped.set(true)
        heartbeatFuture?.cancel(false)
        watchdogFuture?.cancel(false)
        statusFuture?.cancel(false)
        Toolkit.getDefaultToolkit().removeAWTEventListener(windowWatcher)
        // AWT listener removal is thread-safe; do it directly so it always runs
        // even when the EDT is shutting down with the project.
        frame?.let {
            it.removeWindowFocusListener(focusListener)
            it.removeWindowListener(stateListener)
            it.removeWindowStateListener(stateListener)
        }
        frame = null
    }

    companion object {
        /** How long focus may sit nowhere before "left the IDE" (it passes through nowhere between our own windows). */
        private const val LEAVE_SETTLE_MS = 400
        private const val FULLSCREEN_TRANSITION_MS = 3_000L
        private const val WATCHDOG_MS = 2_000L
        /** How long closing the IDE may wait for `ide_closed` to reach the server. */
        private const val CLOSE_REPORT_MS = 2_000L
        private const val CLOSE_CANCELLED_AFTER_S = 15L

        private val PASTE_ACTIONS = setOf("\$Paste", "EditorPaste", "EditorPasteSimple", "\$PasteSimple", "EditorPasteFromX11")
        private val HISTORY_PASTE_ACTIONS = setOf("PasteMultiple")

        /** Popups that open something other than the editor, chat or terminal. */
        private val POPUP_ACTIONS = setOf(
            "SearchEverywhere", "GotoFile", "GotoClass", "GotoSymbol", "GotoAction",
            "FindInPath", "ReplaceInPath", "RecentFiles", "RecentLocations", "Switcher",
        )
    }
}
