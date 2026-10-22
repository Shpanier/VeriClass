package edu.jce.veriexam.ui

import edu.jce.veriexam.api.CourseDto
import edu.jce.veriexam.api.CourseExerciseDto
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ChoosePanelTest {

    private fun ex(id: String) = CourseExerciseDto(exercise_id = id, title_en = id)

    @Test
    fun `one course with one exercise opens it without asking`() {
        val courses = listOf(CourseDto("devops", "DevOps", "lab1", listOf(ex("lab1"))))
        assertEquals("devops" to "lab1", ChoosePanel.autoChoice(courses))
    }

    @Test
    fun `several exercises or several courses need a choice`() {
        val many = CourseDto("dl", "Deep Learning", "ex6", listOf(ex("ex5"), ex("ex6")))
        assertNull(ChoosePanel.autoChoice(listOf(many)))
        val one = CourseDto("devops", "DevOps", "lab1", listOf(ex("lab1")))
        assertNull(ChoosePanel.autoChoice(listOf(one, many)))
        assertNull(ChoosePanel.autoChoice(emptyList()))
    }

    @Test
    fun `the Hebrew title follows the English one`() {
        assertEquals("Lab 1 · מעבדה 1", ChoosePanel.label(CourseExerciseDto("lab1", "Lab 1", "מעבדה 1")))
        assertEquals("Lab 1", ChoosePanel.label(CourseExerciseDto("lab1", "Lab 1", null)))
    }
}
