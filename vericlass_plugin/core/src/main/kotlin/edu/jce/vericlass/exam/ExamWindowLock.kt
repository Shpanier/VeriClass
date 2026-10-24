package edu.jce.vericlass.exam

import com.intellij.openapi.util.SystemInfo
import com.sun.jna.platform.win32.User32
import com.sun.jna.ptr.IntByReference
import java.awt.Frame
import java.io.File

/**
 * The exam window: kept maximized, and (on Windows) checked against the
 * application the operating system has in front.
 *
 * Why not only full screen and focus events: full screen doesn't engage on
 * every IDE version and OS, and the "restore down" button on Windows leaves
 * the IDE focused, so no focus event fires at all. Java focus events can also
 * be missed while a full-screen window changes state. Asking Windows which
 * window is in the foreground (GetForegroundWindow) answers "is the student in
 * another app?" directly, every time the exam watchdog ticks.
 *
 * Everything here is EDT-safe and cheap. The decisions ([isUnmaximize],
 * [isOtherApp]) take plain values, so they are unit-tested without a window.
 */
object ExamWindowLock {

    fun isMaximizedState(state: Int): Boolean = state and Frame.MAXIMIZED_BOTH == Frame.MAXIMIZED_BOTH

    /**
     * The student made the window smaller ("restore down", or a drag off the
     * maximized size). A minimize is reported on its own (`minimized`), so it
     * doesn't count here.
     */
    fun isUnmaximize(oldState: Int, newState: Int): Boolean =
        isMaximizedState(oldState) && !isMaximizedState(newState) && newState and Frame.ICONIFIED == 0

    /** Maximized, or in full screen: the window fills the screen. */
    fun isLocked(frame: Frame, fullScreen: Boolean): Boolean = fullScreen || isMaximizedState(frame.extendedState)

    fun maximize(frame: Frame) {
        if (!isMaximizedState(frame.extendedState)) {
            frame.extendedState = (frame.extendedState and Frame.ICONIFIED.inv()) or Frame.MAXIMIZED_BOTH
        }
    }

    /** The window the OS has in front: its process, title, and program name. */
    data class Foreground(val pid: Long, val title: String, val program: String?) {
        /** For the teacher, e.g. `chrome.exe — "ChatGPT - Google Chrome"`. */
        fun describe(): String {
            val name = program ?: "pid $pid"
            return if (title.isBlank()) name else "$name — \"${title.take(TITLE_MAX)}\""
        }
    }

    /**
     * Another application is in front, or null: ours (the IDE, or a program the
     * student started from it), unknown, or not on Windows.
     */
    fun otherAppInFront(): Foreground? {
        if (!SystemInfo.isWindows) return null
        val fg = runCatching { windowsForeground() }.getOrNull() ?: return null
        val me = ProcessHandle.current()
        val ours = runCatching { me.descendants().map { it.pid() }.toList() }.getOrDefault(emptyList())
        return fg.takeIf { isOtherApp(it.pid, me.pid(), ours) }
    }

    /** A foreground process that is neither the IDE nor one it started (a run, the terminal). */
    fun isOtherApp(foregroundPid: Long, ownPid: Long, ownDescendants: Collection<Long>): Boolean =
        foregroundPid > 0 && foregroundPid != ownPid && foregroundPid !in ownDescendants

    private fun windowsForeground(): Foreground? {
        val user32 = User32.INSTANCE
        val hwnd = user32.GetForegroundWindow() ?: return null
        val pid = IntByReference()
        user32.GetWindowThreadProcessId(hwnd, pid)
        val buf = CharArray(512)
        val n = user32.GetWindowText(hwnd, buf, buf.size)
        val title = String(buf, 0, n.coerceIn(0, buf.size))
        val program = ProcessHandle.of(pid.value.toLong())
            .flatMap { it.info().command() }
            .map { File(it).name }
            .orElse(null)
        return Foreground(pid.value.toLong(), title, program)
    }

    private const val TITLE_MAX = 80
}
