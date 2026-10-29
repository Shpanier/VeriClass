package edu.jce.vericlass.lab

/**
 * What the chat itself says in a lab (steps, notes, questions), in the lab's
 * language: Hebrew when the exercise brief is Hebrew, as in the web chat
 * (student_app), whose Hebrew lines these are.
 */
class LabTexts(val hebrew: Boolean) {

    private fun t(he: String, en: String) = if (hebrew) he else en

    // --- coming back ----------------------------------------------------------------
    fun olderHidden() = t("_…הודעות ישנות יותר לא מוצגות._", "_…older messages aren't shown._")
    fun resumed() = t(
        "↩️ **חזרתם למפגש.** כל מה שהיה עד עכשיו מופיע למעלה, וממשיכים מאותו מקום.",
        "↩️ **Welcome back.** Everything so far is above, and you carry on from the same place.")
    fun stillWithTeacher(lines: String) = t(
        "⏳ **עדיין אצל המרצה:**\n$lines\n\nהתשובה תופיע כאן כשהמרצה יענה.",
        "⏳ **Still with your teacher:**\n$lines\n\nThe answer will appear here when they reply.")
    fun placeholder() = t(
        "כתבו כאן שאלה, את התשובה לשאלה שנשאלתם, או «סיימתי»",
        "Ask here, answer the question you were asked, or write \"done\"")

    // --- the steps -------------------------------------------------------------------
    fun movedBack(label: String) = t("↩️ המרצה החזיר אתכם לשלב $label.", "↩️ Your teacher moved you back to step $label.")
    fun returned(label: String) = t(
        "↩️ המרצה בדק את הפלט ששלחתם לשלב $label, והוא עוד לא תקין. הריצו שוב ושלחו את הפלט החדש.",
        "↩️ Your teacher checked the output you sent for step $label: it isn't right yet. Run it again and send the new output.")
    fun approved(label: String) = t("✅ המרצה אישר את שלב $label. אפשר להמשיך.", "✅ Your teacher approved step $label. You can go on.")
    fun firstNotOpen() = t(
        "⏸️ המרצה עוד לא פתח את השלב הראשון. הוא יופיע כאן ברגע שייפתח.",
        "⏸️ Your teacher hasn't opened the first step yet. It will appear here as soon as it opens.")
    fun waitingTeacher(label: String) = t(
        "⏸️ סיימתם את כל השלבים שפתוחים כרגע. שלב $label יופיע כאן כשהמרצה יפתח אותו לכל הכיתה. " +
            "בינתיים אפשר לשאול כאן שאלות על מה שעשיתם.",
        "⏸️ You finished every step that is open now. Step $label will appear here when your teacher opens it " +
            "for the class. Meanwhile you can ask questions here about what you did.")
    fun allDone() = t("🎉 סיימתם את כל השלבים של המעבדה. כל הכבוד!", "🎉 You finished every step of the lab. Well done!")
    fun opened(label: String) = t("🔓 **המרצה פתח את שלב $label.**\n\n", "🔓 **Your teacher opened step $label.**\n\n")
    fun howToFinish(needsOutput: Boolean) = if (needsOutput) t(
        "כשסיימתם: לחצו **סיימתי**. הפלט מהטרמינל של VeriClass ימולא בשבילכם: בדקו אותו ושלחו.",
        "When you're done: click **Done**. The output of your VeriClass Terminal is filled in for you: check it and send it.")
    else t("כשסיימתם: לחצו **סיימתי**.", "When you're done: click **Done**.")
    fun youAreAt(label: String, needsOutput: Boolean) =
        t("📍 אתם בשלב **$label** (למעלה). ", "📍 You are on step **$label** (above). ") + howToFinish(needsOutput)
    fun doneButton(label: String) = t("✅ סיימתי את שלב $label", "✅ Done with step $label")
    fun sendAgain() = t("📋 לשלוח שוב", "📋 Send the output again")

    // --- the "Done" box --------------------------------------------------------------
    fun outputBoxTitle(label: String, prefilled: Boolean) = if (prefilled) t(
        "📋 הפלט של שלב $label, מהטרמינל של VeriClass. בדקו שזה כל מה שהופיע (אפשר לערוך, או להדביק במקומו פלט אחר), ושלחו.",
        "📋 The output of step $label, from your VeriClass Terminal. Check it is everything that appeared " +
            "(you can edit it, or paste other output instead), then send it.")
    else t(
        "📋 הדביקו כאן את הפלט של שלב $label: כל מה שהופיע בטרמינל אחרי הפקודות (אפשר גם עם הפקודות עצמן). ואז שלחו.",
        "📋 Paste the output of step $label here: everything the terminal printed after the commands " +
            "(the commands themselves may stay). Then send it.")
    fun send() = t("שליחה", "Send")
    fun cancel() = t("ביטול", "Cancel")
    fun pasteFirst() = t("הדביקו קודם את הפלט.", "Paste the output first.")

    // --- finishing a step --------------------------------------------------------------
    fun noConnection() = t("⚠️ אין חיבור לשרת. נסו שוב בעוד רגע.", "⚠️ No connection to the server. Try again in a moment.")
    fun saveFailed() = t("⚠️ לא הצלחנו לשמור את השלב. נסו שוב בעוד רגע.", "⚠️ The step couldn't be saved. Try again in a moment.")
    fun missing(label: String) = t(
        "🔍 הפלט של שלב $label לא נראה כמו מה שציפינו לו.\n\n" +
            "בדקו את «שימו לב» בשלב, הריצו שוב, ושלחו את הפלט החדש. " +
            "המרצה רואה את הפלט ששלחתם, ואם הכול בסדר הוא יאשר לכם להמשיך: השלב הבא יופיע כאן לבד.",
        "🔍 The output of step $label doesn't look like what we expected.\n\n" +
            "Check the step's notes, run it again, and send the new output. Your teacher sees the output you sent, " +
            "and if it's fine they'll let you go on: the next step will appear here by itself.")
    fun stepDone(label: String, outputOk: Boolean, quiz: Boolean) =
        t("✅ שלב $label הושלם.", "✅ Step $label is done.") +
            (if (outputOk) t(" הפלט נראה תקין.", " The output looks right.") else "") +
            (if (quiz) t(" לפני השלב הבא, שאלה קצרה.", " Before the next step, a short question.") else "")
    fun alreadyFinishedAll() = t("כבר סיימתם את כל השלבים. 🎉", "You already finished every step. 🎉")
    fun answerQuizFirst() = t("קודם ענו על השאלה שלמעלה, ואז השלב הבא יופיע.", "First answer the question above; then the next step appears.")
    fun notOpenYet(label: String) = t(
        "שלב $label עוד לא נפתח. הוא יופיע כאן כשהמרצה יפתח אותו.",
        "Step $label isn't open yet. It will appear here when your teacher opens it.")
    fun alreadyDone(label: String, current: String) = t(
        "שלב $label כבר הושלם. אתם עכשיו בשלב $current.", "Step $label is already done. You are now on step $current.")

    // --- a message that may be a step's answer ---------------------------------------
    fun outputOrQuestion(label: String) = t("🤔 שלחתם שאלה, או את התשובה לשלב $label?", "🤔 Is this a question, or your answer for step $label?")
    fun itsTheOutput(label: String, needsOutput: Boolean) =
        if (needsOutput) t("📋 זה הפלט של שלב $label", "📋 It's the output of step $label")
        else t("✅ סיימתי את שלב $label", "✅ I finished step $label")
    fun itsAQuestion() = t("❓ זו שאלה", "❓ It's a question")
    fun detected(label: String) = t("📋 זיהיתי שזה הפלט של שלב $label.", "📋 That's the output of step $label.")

    // --- questions the chat asks (backend/open_questions.py) --------------------------
    fun question(body: String, quizStep: String?) =
        (if (quizStep != null) t("❓ **שאלת הבנה על שלב $quizStep:**", "❓ **A question about step $quizStep:**")
        else t("🎓 **המרצה שואל/ת:**", "🎓 **Your teacher asks:**")) +
            "\n\n> $body\n\n" +
            t("כתבו כאן את התשובה שלכם. יש לכם שאלה לפני שאתם עונים? אפשר לשאול אותה כאן.",
                "Write your answer here. Have a question before you answer? You can ask it here.")
    fun answerOrQuestion() = t("🤔 זו התשובה שלכם לשאלה, או שאלה שלכם?", "🤔 Is this your answer to the question, or a question of yours?")
    fun myAnswer() = t("✍️ זו התשובה שלי", "✍️ It's my answer")
    fun myQuestion() = t("❓ זו שאלה שלי", "❓ It's my question")
    fun remind(body: String) = t(
        "✍️ כשתהיו מוכנים, כתבו כאן את התשובה לשאלה:\n\n> $body",
        "✍️ When you're ready, write your answer to the question here:\n\n> $body")
    fun answerSaved(grade: Int?, why: String?) =
        t("✅ התשובה נשמרה.", "✅ Your answer was saved.") +
            (grade?.let { t(" ציון: **$it/2**", " Grade: **$it/2**") } ?: "") +
            (why?.takeIf { it.isNotBlank() }?.let { " — $it" } ?: "")
    fun questionClosed() = t(
        "השאלה הזו כבר לא פתוחה (כבר עניתם עליה, או שהמרצה ביטל אותה).",
        "This question is no longer open (you already answered it, or your teacher withdrew it).")
    fun answerNotSent() = t("⚠️ התשובה לא נשלחה. נסו שוב.", "⚠️ Your answer wasn't sent. Try again.")

    companion object {
        private val HEBREW = Regex("[֐-׿]")

        /** The lab's language, by the rule the server uses for its own notes: is the brief Hebrew? */
        fun forBrief(brief: String) = LabTexts(HEBREW.containsMatchIn(brief))
    }
}
