package edu.jce.veriexam.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Messages from the October 2026 classes, as the students typed them. */
class AnswerDetectorTest {

    @Test
    fun `answers sent without "done with step" are recognized`() {
        assertTrue(AnswerDetector.looksLikeAnswers("1. שורה אחת נותנת מידע על דירה מסויימת"))
        assertTrue(AnswerDetector.looksLikeAnswers(
            "סעיף 1 הנתונים מייצגים מידע לגבי דירות סעיף 2 יש נתונים שמוגדרים כמחרוזת ומספרים"))
        assertTrue(AnswerDetector.looksLikeAnswers("1) שורה 0 - הפיצרים\n2) הסוג של כל עמודה: int64\n3) floor 120"))
        assertTrue(AnswerDetector.looksLikeAnswers("התשובות שלי: כל שורה היא מכירה"))
        assertTrue(AnswerDetector.looksLikeAnswers("q1 - shape q2 - dtypes q3 - floor 120"))
    }

    @Test
    fun `questions and done messages are left alone`() {
        assertFalse(AnswerDetector.looksLikeAnswers("איך מדפיסים שורה אחת מלאה של נתונים ?"))
        assertFalse(AnswerDetector.looksLikeAnswers("How do i change the data into a pandas data frame"))
        assertFalse(AnswerDetector.looksLikeAnswers("מה הכוונה מה מייצגת שורה אחת? אתה מתכוון לlisting_id?"))
        assertFalse(AnswerDetector.looksLikeAnswers("סיימתי שלב 1. התשובות שלי: 1. דירה"))
        assertFalse(AnswerDetector.looksLikeAnswers("hi"))
    }

    @Test
    fun `a done message with only the button's text has no answers`() {
        assertTrue(AnswerDetector.doneWithoutAnswers("Done with step 1. Our commands and answers:"))
        assertTrue(AnswerDetector.doneWithoutAnswers("סיימתי שלב 1. התשובות שלי:"))
        assertTrue(AnswerDetector.doneWithoutAnswers("סיימתי שלב 1. התשובות שלי: "))
        assertFalse(AnswerDetector.doneWithoutAnswers("סיימתי שלב 1. התשובות שלי: כל שורה היא מכירה"))
        assertFalse(AnswerDetector.doneWithoutAnswers("Done with step 2. Our answers:\n1. 25\n2. 82"))
        assertFalse(AnswerDetector.doneWithoutAnswers("Done with step 2\nwc -l -> 2000"))
    }

    @Test
    fun `a submission keeps the student's language`() {
        assertEquals("סיימתי שלב 2. התשובות שלי:\n1. דירה", AnswerDetector.asSubmission("1. דירה", 2))
        assertEquals("Done with step 1. Our answers:\n1. 25", AnswerDetector.asSubmission(" 1. 25 ", 1))
        assertTrue(AnswerDetector.isDone(AnswerDetector.asSubmission("1. x", null)))
    }
}
