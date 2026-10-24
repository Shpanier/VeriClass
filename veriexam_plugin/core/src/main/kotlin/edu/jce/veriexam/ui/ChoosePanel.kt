package edu.jce.veriexam.ui

import com.intellij.openapi.ui.ComboBox
import com.intellij.ui.JBColor
import com.intellij.ui.SimpleListCellRenderer
import com.intellij.ui.components.JBLabel
import com.intellij.ui.components.JBList
import com.intellij.ui.components.JBScrollPane
import com.intellij.util.ui.JBUI
import edu.jce.veriexam.api.CourseDto
import edu.jce.veriexam.api.CourseExerciseDto
import java.awt.FlowLayout
import java.awt.GridBagConstraints
import java.awt.GridBagLayout
import java.awt.Insets
import javax.swing.DefaultListModel
import javax.swing.JButton
import javax.swing.JPanel
import javax.swing.ListSelectionModel
import javax.swing.SwingConstants

/**
 * Second screen, after login, when there is something to choose: one of the
 * student's courses, then one of the exercises that course offers. The course's
 * default exercise is preselected. (With one course and one exercise the panel
 * is skipped: see [autoChoice].)
 */
class ChoosePanel(
    username: String,
    private val courses: List<CourseDto>,
    private val onChoose: (courseId: String, exerciseId: String) -> Unit,
    private val onBack: () -> Unit,
) : JPanel(GridBagLayout()) {

    private val courseBox = ComboBox(courses.toTypedArray()).apply {
        renderer = SimpleListCellRenderer.create("") { it.name }
    }
    private val exerciseModel = DefaultListModel<CourseExerciseDto>()
    private val exerciseList = JBList(exerciseModel).apply {
        selectionMode = ListSelectionModel.SINGLE_SELECTION
        cellRenderer = SimpleListCellRenderer.create("") { label(it) }
        visibleRowCount = 6
    }
    private val startButton = JButton("Start")
    private val backButton = JButton("Log out")
    private val status = JBLabel(" ").apply {
        foreground = JBColor.RED
        horizontalAlignment = SwingConstants.CENTER
    }

    init {
        border = JBUI.Borders.empty(24)
        val c = GridBagConstraints().apply {
            gridx = 0
            gridy = 0
            insets = Insets(JBUI.scale(6), 0, JBUI.scale(6), 0)
            fill = GridBagConstraints.HORIZONTAL
            weightx = 1.0
        }
        add(JBLabel("Hello, $username").apply { horizontalAlignment = SwingConstants.CENTER }, c)
        c.gridy++
        if (courses.size > 1) {
            add(JBLabel("Course:"), c)
            c.gridy++
            add(courseBox, c)
        } else {
            add(JBLabel("Course: ${courses.first().name}"), c)
        }
        c.gridy++
        add(JBLabel("Exercise:"), c)
        c.gridy++
        c.fill = GridBagConstraints.BOTH
        add(JBScrollPane(exerciseList), c)
        c.fill = GridBagConstraints.HORIZONTAL
        c.gridy++
        add(JPanel(FlowLayout(FlowLayout.CENTER, JBUI.scale(8), 0)).apply {
            add(startButton)
            add(backButton)
        }, c)
        c.gridy++
        add(status, c)

        courseBox.addActionListener { showExercises() }
        startButton.addActionListener { fire() }
        backButton.addActionListener { onBack() }
        exerciseList.addListSelectionListener { startButton.isEnabled = exerciseList.selectedValue != null }
        showExercises()
    }

    /** Lists the selected course's exercises, with its default selected. */
    private fun showExercises() {
        val course = selectedCourse() ?: return
        exerciseModel.clear()
        course.exercises.forEach { exerciseModel.addElement(it) }
        val default = course.exercises.indexOfFirst { it.exercise_id == course.default_exercise }
        exerciseList.selectedIndex = if (default >= 0) default else 0
    }

    private fun selectedCourse(): CourseDto? =
        if (courses.size > 1) courseBox.selectedItem as? CourseDto else courses.firstOrNull()

    private fun fire() {
        val course = selectedCourse() ?: return
        val exercise = exerciseList.selectedValue ?: return setError("Choose an exercise.")
        setBusy(true)
        onChoose(course.course_id, exercise.exercise_id)
    }

    fun setBusy(busy: Boolean) {
        startButton.isEnabled = !busy
        backButton.isEnabled = !busy
        courseBox.isEnabled = !busy
        exerciseList.isEnabled = !busy
        startButton.text = if (busy) "Opening…" else "Start"
        if (busy) status.text = " "
    }

    fun setError(message: String) {
        setBusy(false)
        status.text = message
    }

    companion object {
        /** Exercise title, with the Hebrew title after it when there is one. */
        fun label(e: CourseExerciseDto): String =
            if (e.title_he.isNullOrBlank() || e.title_he == e.title_en) e.title_en else "${e.title_en} · ${e.title_he}"

        /**
         * (course, exercise) when there is nothing to choose: one course that
         * offers one exercise. Null when the student must pick, or has no course.
         */
        fun autoChoice(courses: List<CourseDto>): Pair<String, String>? {
            val course = courses.singleOrNull() ?: return null
            // A meeting today in the student's only course: open its exercise.
            course.today_exercise?.takeIf { id -> course.exercises.any { it.exercise_id == id } }
                ?.let { return course.course_id to it }
            val exercise = course.exercises.singleOrNull() ?: return null
            return course.course_id to exercise.exercise_id
        }
    }
}
