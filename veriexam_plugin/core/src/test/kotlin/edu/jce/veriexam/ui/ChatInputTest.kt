package edu.jce.veriexam.ui

import org.junit.Assert.assertEquals
import org.junit.Test
import java.awt.event.InputEvent
import java.awt.event.KeyEvent
import javax.swing.JTextArea
import javax.swing.KeyStroke
import javax.swing.SwingUtilities

class ChatInputTest {

    /**
     * Enter with [modifiers], resolved the way Swing does for the focused text
     * box: its input map (and the look-and-feel's), then its action map.
     */
    private fun press(area: JTextArea, modifiers: Int) {
        val ks = KeyStroke.getKeyStroke(KeyEvent.VK_ENTER, modifiers)
        val action = area.actionMap[area.inputMap[ks]]
        val event = KeyEvent(area, KeyEvent.KEY_PRESSED, System.currentTimeMillis(), modifiers, KeyEvent.VK_ENTER, '\n')
        SwingUtilities.notifyAction(action, ks, event, area, modifiers)
    }

    // On the EDT, as in the IDE: off it, the caret doesn't follow inserted text.
    @Test
    fun `Shift+Enter starts a new line and Enter sends`() = SwingUtilities.invokeAndWait {
        var sent = 0
        val area = JTextArea("first")
        ChatPanel.installSendKeys(area) { sent++ }
        area.caretPosition = area.text.length

        press(area, InputEvent.SHIFT_DOWN_MASK)
        area.replaceSelection("second")
        assertEquals("first\nsecond", area.text)
        assertEquals(0, sent)

        press(area, 0)
        assertEquals(1, sent)
        assertEquals("first\nsecond", area.text)
    }

    @Test
    fun `no new line while the box is disabled (a reply is streaming)`() = SwingUtilities.invokeAndWait {
        val area = JTextArea("hi")
        ChatPanel.installSendKeys(area) {}
        area.isEnabled = false
        press(area, InputEvent.SHIFT_DOWN_MASK)
        assertEquals("hi", area.text)
    }
}
