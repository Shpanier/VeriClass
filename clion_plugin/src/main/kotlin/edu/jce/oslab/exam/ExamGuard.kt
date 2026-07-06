package edu.jce.oslab.exam

import com.intellij.notification.NotificationGroupManager
import com.intellij.notification.NotificationType
import com.intellij.openapi.Disposable
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.diagnostic.thisLogger
import com.intellij.openapi.project.Project
import com.intellij.openapi.util.Disposer
import com.intellij.openapi.wm.ToolWindowManager
import com.intellij.openapi.wm.WindowManager
import com.intellij.util.concurrency.AppExecutorUtil
import edu.jce.oslab.api.ClientConfig
import edu.jce.oslab.api.OsLabApiClient
import java.awt.event.WindowAdapter
import java.awt.event.WindowEvent
import java.awt.event.WindowFocusListener
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong
import javax.swing.JFrame

/**
 * The exam "proctor" on the student's side. While an exam session is live it:
 *
 *  - reports `exam_started` and puts CLion in full screen (if configured);
 *  - watches the IDE frame and, the moment the student leaves it — switches to
 *    another app, minimizes, or exits full screen — reports that to the backend
 *    (which surfaces it on the teacher dashboard), warns the student, and
 *    re-asserts full screen / brings CLion back to the front when they return;
 *  - sends a periodic heartbeat so a quiet student stays on the live grid.
 *
 * Key correctness detail: a [WindowEvent] whose `oppositeWindow` is non-null
 * means focus moved to *another window of our own IDE* (a probe dialog, the
 * settings dialog, a completion popup) — NOT the student leaving. Only
 * `oppositeWindow == null` means focus left the Java app entirely, which is the
 * real "left the IDE" signal. Filtering on that is what keeps the plugin's own
 * dialogs from raising false alarms.
 *
 * Stops cleanly when its parent [Disposable] (the tool window) is disposed.
 */
class ExamGuard(
    private val project: Project,
    private val api: OsLabApiClient,
    private val sessionId: String,
    private val token: String,
    private val config: ClientConfig,
    /** Updates the in-tool-window warning banner. Always invoked on the EDT. */
    private val onViolation: (count: Int, reason: String) -> Unit,
    parent: Disposable,
) : Disposable {

    private val stopped = AtomicBoolean(false)
    private val away = AtomicBoolean(false)
    private val awaySinceMs = AtomicLong(0L)
    private val violations = AtomicInteger(0)
    // So the full-screen watchdog reports an exit once, not every 2s tick.
    private val fullscreenExitReported = AtomicBoolean(false)
    // Only flag a full-screen *exit* once we've actually seen full screen engage.
    // Guards against the startup transition racing the first tick, and against
    // platforms where full screen never engages (we'd otherwise false-alarm).
    private val sawFullscreen = AtomicBoolean(false)

    private val scheduler = AppExecutorUtil.getAppScheduledExecutorService()
    private var heartbeatFuture: ScheduledFuture<*>? = null
    private var watchdogFuture: ScheduledFuture<*>? = null
    private var frame: JFrame? = null

    private val focusListener = object : WindowFocusListener {
        override fun windowLostFocus(e: WindowEvent) {
            if (e.oppositeWindow != null) return // focus went to another IDE window — ignore
            onLeft("focus_lost", "You switched away from CLion.")
        }

        override fun windowGainedFocus(e: WindowEvent) {
            if (e.oppositeWindow != null) return
            onReturned("focus_regained")
        }
    }

    private val stateListener = object : WindowAdapter() {
        override fun windowIconified(e: WindowEvent) = onLeft("minimized", "You minimized CLion.")
        override fun windowDeiconified(e: WindowEvent) = onReturned("window_restored")
    }

    init {
        Disposer.register(parent, this)
        if (config.isExamMode) start() else thisLogger().info("exam mode off — ExamGuard idle")
    }

    private fun start() {
        report("exam_started", detail = "exam client armed", awayMs = null)

        ApplicationManager.getApplication().invokeLater {
            if (stopped.get() || project.isDisposed) return@invokeLater
            // Land the student in the tutor tool window, full screen, listening.
            toolWindow()?.activate(null)
            if (config.force_fullscreen) ExamFullScreen.enter(project)
            attachListeners()
        }

        val hb = config.heartbeat_ms.toLong().coerceAtLeast(5_000L)
        heartbeatFuture = scheduler.scheduleWithFixedDelay(::safeHeartbeat, hb, hb, TimeUnit.MILLISECONDS)

        if (config.force_fullscreen) {
            watchdogFuture =
                scheduler.scheduleWithFixedDelay(::fullscreenWatchdog, 2_000L, 2_000L, TimeUnit.MILLISECONDS)
        }
    }

    /** EDT. */
    private fun attachListeners() {
        val f = WindowManager.getInstance().getFrame(project) ?: return
        frame = f
        f.addWindowFocusListener(focusListener)
        f.addWindowListener(stateListener)
    }

    // --- leave / return ---------------------------------------------------

    /** EDT (called from AWT window listeners). */
    private fun onLeft(kind: String, reason: String) {
        if (stopped.get()) return
        if (!away.compareAndSet(false, true)) return // already away — dedupe (e.g. minimize fires both events)
        awaySinceMs.set(System.currentTimeMillis())
        val count = violations.incrementAndGet()
        report(kind, detail = reason, awayMs = null)
        warnStudent(count, reason)
    }

    /** EDT. */
    private fun onReturned(kind: String) {
        if (stopped.get()) return
        if (!away.compareAndSet(true, false)) return // wasn't away — ignore the matching second event
        val ms = (System.currentTimeMillis() - awaySinceMs.get()).coerceAtLeast(0)
        report(kind, detail = "returned to the IDE", awayMs = ms)
        // Re-assert exam constraints now that they're back.
        toolWindow()?.activate(null)
        if (config.force_fullscreen) {
            fullscreenExitReported.set(false)
            ExamFullScreen.enter(project)
        }
        frame?.toFront()
    }

    /** EDT. Updates the banner and pops a sticky balloon. */
    private fun warnStudent(count: Int, reason: String) {
        onViolation(count, reason)
        toolWindow()?.activate(null)
        val group = NotificationGroupManager.getInstance().getNotificationGroup("OS Lab Exam") ?: return
        group.createNotification(
            "Exam mode — stay in CLion",
            "$reason This was reported to your instructor (×$count).",
            NotificationType.WARNING,
        ).notify(project)
    }

    // --- background ticks -------------------------------------------------

    private fun safeHeartbeat() {
        if (stopped.get()) return
        api.proctorHeartbeat(sessionId, token)
    }

    /**
     * Catches a full-screen exit that doesn't move focus (e.g. the macOS green
     * button or Esc) and restores it. Skipped while the student is away in
     * another app — that's handled on their return, so we don't fight the OS.
     */
    private fun fullscreenWatchdog() {
        if (stopped.get() || !config.force_fullscreen) return
        ApplicationManager.getApplication().invokeLater {
            if (stopped.get() || project.isDisposed || away.get()) return@invokeLater
            if (ExamFullScreen.isFullScreen(project)) {
                sawFullscreen.set(true)
                fullscreenExitReported.set(false)
                return@invokeLater
            }
            // Not full screen. Only a violation if we'd previously gone full
            // screen — otherwise the platform just doesn't support it, or the
            // initial transition hasn't completed yet; keep trying quietly.
            if (sawFullscreen.get() && fullscreenExitReported.compareAndSet(false, true)) {
                val count = violations.incrementAndGet()
                report("fullscreen_exited", detail = "left full screen", awayMs = null)
                warnStudent(count, "You left full screen.")
            }
            ExamFullScreen.enter(project)
        }
    }

    // --- helpers ----------------------------------------------------------

    private fun report(kind: String, detail: String?, awayMs: Long?) {
        if (stopped.get()) return
        ApplicationManager.getApplication().executeOnPooledThread {
            api.reportProctorEvent(sessionId, kind, token, detail, awayMs)
        }
    }

    private fun toolWindow() = ToolWindowManager.getInstance(project).getToolWindow("OS Lab")

    override fun dispose() {
        stopped.set(true)
        heartbeatFuture?.cancel(false)
        watchdogFuture?.cancel(false)
        // AWT listener removal is thread-safe; do it directly so it always runs
        // even when the EDT is shutting down with the project.
        frame?.let {
            it.removeWindowFocusListener(focusListener)
            it.removeWindowListener(stateListener)
        }
        frame = null
    }
}
