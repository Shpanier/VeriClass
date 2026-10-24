package edu.jce.vericlass.exam

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.awt.Frame

class ExamWindowLockTest {

    @Test
    fun `restore down from maximized is a violation`() {
        assertTrue(ExamWindowLock.isUnmaximize(Frame.MAXIMIZED_BOTH, Frame.NORMAL))
        // Maximized only horizontally is still not maximized.
        assertTrue(ExamWindowLock.isUnmaximize(Frame.MAXIMIZED_BOTH, Frame.MAXIMIZED_HORIZ))
    }

    @Test
    fun `minimize and maximize are not a restore down`() {
        // Minimizing is reported on its own ("minimized").
        assertFalse(ExamWindowLock.isUnmaximize(Frame.MAXIMIZED_BOTH, Frame.ICONIFIED))
        assertFalse(ExamWindowLock.isUnmaximize(Frame.NORMAL, Frame.MAXIMIZED_BOTH))
        assertFalse(ExamWindowLock.isUnmaximize(Frame.NORMAL, Frame.NORMAL))
    }

    @Test
    fun `another process in front is another app, our own children are not`() {
        assertTrue(ExamWindowLock.isOtherApp(foregroundPid = 4242, ownPid = 100, ownDescendants = listOf(101)))
        assertFalse(ExamWindowLock.isOtherApp(foregroundPid = 100, ownPid = 100, ownDescendants = emptyList()))
        // A program the student ran from the IDE (its window) is not "another app".
        assertFalse(ExamWindowLock.isOtherApp(foregroundPid = 101, ownPid = 100, ownDescendants = listOf(101)))
        // Unknown (0): don't raise an alarm on a failed query.
        assertFalse(ExamWindowLock.isOtherApp(foregroundPid = 0, ownPid = 100, ownDescendants = emptyList()))
    }

    @Test
    fun `the teacher sees the program and the window title`() {
        assertEquals("chrome.exe — \"ChatGPT - Google Chrome\"",
            ExamWindowLock.Foreground(4242, "ChatGPT - Google Chrome", "chrome.exe").describe())
        assertEquals("pid 4242", ExamWindowLock.Foreground(4242, "", null).describe())
    }

    @Test
    fun `not on Windows there is nothing to ask`() {
        // The test machine is macOS or Linux: the OS query is skipped, never an alarm.
        if (!System.getProperty("os.name").startsWith("Windows")) {
            assertEquals(null, ExamWindowLock.otherAppInFront())
        }
    }
}
