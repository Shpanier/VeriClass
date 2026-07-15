package edu.jce.oslab.ui

import java.awt.Rectangle
import javax.swing.BoxLayout
import javax.swing.JPanel
import javax.swing.Scrollable

/**
 * A vertical (BoxLayout) column that tracks the viewport width, so HTML and
 * wrapping children inside a scroll pane wrap to the available width instead of
 * forcing a horizontal scrollbar.
 */
class ScrollableColumn : JPanel(), Scrollable {

    init {
        layout = BoxLayout(this, BoxLayout.Y_AXIS)
    }

    override fun getPreferredScrollableViewportSize() = preferredSize
    override fun getScrollableUnitIncrement(r: Rectangle, orientation: Int, direction: Int) = 16
    override fun getScrollableBlockIncrement(r: Rectangle, orientation: Int, direction: Int) = 100
    override fun getScrollableTracksViewportWidth() = true
    override fun getScrollableTracksViewportHeight() = false
}
