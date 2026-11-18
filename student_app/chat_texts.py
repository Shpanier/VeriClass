"""Everything the student chat itself says, in Hebrew and in English.

The chat picks one language per student (student_app/app.py, `_lang`): the
lecturer's setting (CHAT_LANGUAGE=he|en), or, on "auto", Hebrew for a lab
written in Hebrew and English otherwise; before the lab is known (signing in,
choosing a course) it follows the browser's language. The lab's own text, the
tutor's answers and the server's notes are not here: they come as written.

Each entry is (Hebrew, English). {name} is filled by text(key, lang, name=...).
"""

TEXTS: dict[str, tuple[str, str]] = {
    # --- signing in (only when the chat asks; the sign-in page has its own labels) ---
    "ask_username": ("🎓 ברוכים הבאים ל־VeriClass. הקלידו את שם המשתמש שלכם.",
                     "🎓 Welcome to VeriClass. Type your username."),
    "no_username": ("לא התקבל שם משתמש. רעננו את הדף כדי לנסות שוב.",
                    "No username was received. Reload the page to try again."),
    "ask_password": ("עכשיו את הסיסמה. (עד שהמרצה משנה אותה, היא זהה לשם המשתמש.)",
                     "Now your password. (Until your lecturer changes it, it is the same as your username.)"),
    "no_password": ("לא התקבלה סיסמה. רעננו את הדף כדי לנסות שוב.",
                    "No password was received. Reload the page to try again."),
    "no_server": ("⚠️ אין חיבור לשרת המעבדה. ספרו למרצה.",
                  "⚠️ The lab server can't be reached. Tell your lecturer."),
    "wrong_login": ("❌ שם המשתמש או הסיסמה שגויים. רעננו את הדף כדי לנסות שוב.",
                    "❌ Wrong username or password. Reload the page to try again."),
    "too_many_logins": ("❌ יותר מדי ניסיונות כניסה. המתינו 5 דקות ונסו שוב.",
                        "❌ Too many failed sign-ins. Wait 5 minutes and try again."),
    "login_failed": ("⚠️ הכניסה נכשלה. נסו שוב בעוד רגע.",
                     "⚠️ Signing in failed. Try again in a moment."),

    # --- choosing a course and an exercise ---
    "choose_course": ("בחרו קורס:", "Choose a course:"),
    "choose_exercise": ("**{course}**: בחרו תרגיל (⭐ = הבחירה של המרצה):",
                        "**{course}**: choose an exercise (⭐ = your lecturer's pick):"),
    "no_choice": ("לא התקבלה בחירה. רעננו את הדף כדי לנסות שוב.",
                  "Nothing was chosen. Reload the page to try again."),
    "session_failed": ("⚠️ לא הצלחנו לפתוח את המפגש שלכם.", "⚠️ Your session couldn't be opened."),
    "exercise_gone": ("⚠️ התרגיל הזה כבר לא פתוח בשבילכם. בחרו תרגיל אחר בתפריט שבראש הדף.",
                      "⚠️ This exercise isn't open for you any more. Choose another one in the menu at the top of "
                      "the page."),
    "hint_relogin": (" צאו והיכנסו שוב.", " Sign out and sign in again."),
    "hint_reload": (" רעננו את הדף כדי לנסות שוב.", " Reload the page to try again."),
    "stopped": ("_⏸️ הופסק._", "_⏸️ Stopped._"),
    "nothing_chosen": ("_לא נבחרה תשובה._", "_Nothing was chosen._"),

    # --- coming back to a lab ---
    "older_hidden": ("_…הודעות ישנות יותר לא מוצגות._", "_…older messages aren't shown._"),
    "resumed": ("↩️ **חזרתם לתרגיל {title}.** כל מה שהיה בו עד עכשיו מופיע למעלה, וממשיכים מאותו מקום.",
                "↩️ **Welcome back to {title}.** Everything you did in it is shown above, and you continue "
                "from the same place."),

    # --- the exercise menu at the top of the page (one entry per exercise) ---
    "switch_hint": ("🔀 **לעבור לתרגיל אחר:** בחרו אותו בתפריט שבראש הדף. העבודה שלכם בכל תרגיל נשמרת, "
                    "וכשחוזרים אליו ממשיכים מאותו מקום. כדי להתחבר כמשתמש אחר: העיגול עם האות "
                    "בפינה הימנית העליונה ← **יציאה**.",
                    "🔀 **To switch to another exercise,** choose it in the menu at the top of the page. Your "
                    "work in each exercise is kept, and going back to one continues from the same place. To "
                    "sign in as someone else: the circle with your initial at the top right → **Sign out**."),
    "menu_course": ("קורס: **{course}**", "Course: **{course}**"),
    "menu_pick": ("⭐ הבחירה של המרצה", "⭐ Your lecturer's pick"),
    "menu_last": ("עבדתם עליו לאחרונה: {when}", "You last worked on it: {when}"),
    "menu_new": ("עוד לא התחלתם אותו.", "You haven't started it yet."),
    "still_with_lecturer": ("⏳ **עדיין אצל המרצה:**\n{lines}\n\nהתשובה תופיע כאן כשהמרצה יענה.",
                            "⏳ **Still with your lecturer:**\n{lines}\n\nThe answer will appear here when your lecturer replies."),

    # --- the briefing ---
    "yes": ("כן", "yes"),
    "no": ("לא", "no"),
    "variant_head": ("**הגרסה שלכם לתרגיל ({variant}):**", "**Your version of the exercise ({variant}):**"),
    "tests_head": ("**קלטי הבדיקה שהתוכנית צריכה לעבור:**", "**The test inputs your program has to pass:**"),
    "test_line": ("- קלט `{input}` ← פלט `{output}`", "- input `{input}` → output `{output}`"),
    "mode_mentor": ("**מצב העוזר:** מנחה (עוזר בשאלות מכוונות, לא נותן את הפתרון)",
                    "**Tutor mode:** mentor (guides you with questions, doesn't hand over the solution)"),
    "mode_coding_partner": ("**מצב העוזר:** שותף לקוד (עזרה ישירה יותר)",
                            "**Tutor mode:** coding partner (more direct help)"),
    "mode_other": ("**מצב העוזר:** {mode}", "**Tutor mode:** {mode}"),

    # --- asking the tutor ---
    "expired": ("המפגש הסתיים. רעננו את הדף.", "Your session has ended. Reload the page."),
    "expired_login": ("⚠️ המפגש הסתיים. רעננו את הדף והיכנסו שוב.",
                      "⚠️ Your session has ended. Reload the page and sign in again."),
    "unavailable": ("⚠️ הצ'אט לא זמין כרגע. נסו שוב בעוד רגע.",
                    "⚠️ The chat isn't available right now. Try again in a moment."),
    "cut": ("⚠️ החיבור נקטע. נסו שוב.", "⚠️ The connection was interrupted. Try again."),

    # --- a class-paced lab: steps ---
    "step_opened": ("🔓 **המרצה פתח את שלב {label}.**\n\n", "🔓 **Your lecturer opened step {label}.**\n\n"),
    "how_output": ("כשסיימתם: לחצו **סיימתי**, והדביקו את כל הפלט שקיבלתם בטרמינל.",
                   "When you finish: click **Done**, and paste all the output you got in the terminal."),
    "how_done": ("כשסיימתם: לחצו **סיימתי**.", "When you finish: click **Done**."),
    "btn_done": ("✅ סיימתי את שלב {label}", "✅ Done with step {label}"),
    "btn_paste_again": ("📋 להדביק שוב", "📋 Paste again"),
    "where_you_are": ("📍 אתם בשלב **{label}** (למעלה). כשסיימתם: {how}",
                      "📍 You are on step **{label}** (above). When you finish: {how}"),
    "resume_how_output": ("לחצו **סיימתי** והדביקו את הפלט.", "click **Done** and paste the output."),
    "resume_how_done": ("לחצו **סיימתי**.", "click **Done**."),
    "no_server_retry": ("⚠️ אין חיבור לשרת. נסו שוב בעוד רגע.",
                        "⚠️ The server can't be reached. Try again in a moment."),
    "paste_here": ("📋 הדביקו כאן את הפלט של שלב {label}: כל מה שהופיע בטרמינל אחרי הפקודות "
                   "(אפשר גם עם הפקודות עצמן). ואז שלחו.",
                   "📋 Paste the output of step {label} here: everything the terminal showed after the "
                   "commands (the commands themselves can stay in). Then send."),
    "save_failed": ("⚠️ לא הצלחנו לשמור את השלב. נסו שוב בעוד רגע.",
                    "⚠️ The step couldn't be saved. Try again in a moment."),
    "output_mismatch": ("🔍 הפלט של שלב {label} לא נראה כמו מה שציפינו לו.\n\n"
                        "בדקו את «שימו לב» בשלב, הריצו שוב, והדביקו את הפלט החדש. "
                        "המרצה רואה את הפלט ששלחתם, ואם הכול בסדר הוא יאשר לכם להמשיך: "
                        "השלב הבא יופיע כאן לבד.",
                        "🔍 The output of step {label} doesn't look like what was expected.\n\n"
                        "Check the step's notes, run it again, and paste the new output. "
                        "Your lecturer sees the output you sent; if it is fine, they will let you continue "
                        "and the next step will appear here by itself."),
    "output_ok": (" הפלט נראה תקין.", " The output looks right."),
    "quiz_next": (" לפני השלב הבא, שאלה קצרה.", " Before the next step, a short question."),
    "step_done": ("✅ שלב {label} הושלם.{note}", "✅ Step {label} is done.{note}"),
    "all_done": ("כבר סיימתם את כל השלבים. 🎉", "You already finished every step. 🎉"),
    "answer_first": ("קודם ענו על השאלה שלמעלה, ואז השלב הבא יופיע.",
                     "First answer the question above; then the next step will appear."),
    "answer_waiting": ("התשובה שלכם לשאלה ממתינה למרצה. השלב הבא יופיע כשהמרצה יאשר לכם להמשיך.",
                       "Your answer is waiting for your lecturer. The next step will appear when they let you continue."),
    "not_open_yet": ("שלב {label} עוד לא נפתח. הוא יופיע כאן כשהמרצה יפתח אותו.",
                     "Step {label} isn't open yet. It will appear here when your lecturer opens it."),
    "already_done": ("שלב {label} כבר הושלם. אתם עכשיו בשלב {current}.",
                     "Step {label} is already done. You are now on step {current}."),
    "why_question": ("נוספה שאלה (היא כאן בצ'אט). ענו עליה, ואז לחצו שוב «סיימתי».",
                     "A question was added (it is here in the chat). Answer it, then click \"Done\" again."),
    "why_changed": ("השלב השתנה.", "The step changed."),
    "paste_stopped": ("⏸️ **המרצה עצר אתכם:** ההדבקה לשלב {label} הופסקה. {why}",
                      "⏸️ **Your lecturer paused you:** pasting for step {label} was stopped. {why}"),
    "sent_back": ("↩️ המרצה החזיר אתכם לשלב {label}.", "↩️ Your lecturer moved you back to step {label}."),
    "output_returned": ("↩️ המרצה בדק את הפלט ששלחתם לשלב {label}, והוא עוד לא תקין. "
                        "הריצו שוב והדביקו את הפלט החדש.",
                        "↩️ Your lecturer looked at the output you sent for step {label}, and it isn't right yet. "
                        "Run it again and paste the new output."),
    "step_approved": ("✅ המרצה אישר את שלב {label}. אפשר להמשיך.",
                      "✅ Your lecturer approved step {label}. You can go on."),
    "answer_read": ("📬 המרצה קרא את התשובה שלכם לשאלה.", "📬 Your lecturer read your answer."),
    "first_not_open": ("⏸️ המרצה עוד לא פתח את השלב הראשון. הוא יופיע כאן ברגע שייפתח.",
                       "⏸️ Your lecturer hasn't opened the first step yet. It will appear here as soon as it opens."),
    "wait_next": ("⏸️ סיימתם את כל השלבים שפתוחים כרגע. שלב {label} יופיע כאן "
                  "כשהמרצה יפתח אותו לכל הכיתה. בינתיים אפשר לשאול כאן שאלות על מה שעשיתם.",
                  "⏸️ You finished every step that is open. Step {label} will appear here when your lecturer "
                  "opens it for the whole class. Meanwhile you can ask questions here about what you did."),
    "lab_done": ("🎉 סיימתם את כל השלבים של המעבדה. כל הכבוד!",
                 "🎉 You finished every step of the lab. Well done!"),

    # --- a message that may be a step's answer ---
    "maybe_step_q": ("🤔 שלחתם שאלה, או את התשובה לשלב {label}?",
                     "🤔 Was that a question, or your answer for step {label}?"),
    "opt_output": ("📋 זה הפלט של שלב {label}", "📋 It's the output of step {label}"),
    "opt_done": ("✅ סיימתי את שלב {label}", "✅ I finished step {label}"),
    "opt_question": ("❓ זו שאלה", "❓ It's a question"),
    "detected_output": ("📋 זיהיתי שזה הפלט של שלב {label}.", "📋 That looks like the output of step {label}."),

    # --- questions the chat asks the student ---
    "quiz_head": ("❓ **שאלת הבנה על שלב {step}:**", "❓ **A question about step {step}:**"),
    "lecturer_asks": ("🎓 **המרצה שואל/ת:**", "🎓 **Your lecturer asks:**"),
    "answer_here": ("כתבו כאן את התשובה שלכם. יש לכם שאלה לפני שאתם עונים? אפשר לשאול אותה כאן.",
                    "Write your answer here. Have a question before you answer? You can ask it here."),
    "maybe_answer_q": ("🤔 זו התשובה שלכם לשאלה, או שאלה שלכם?",
                       "🤔 Is that your answer to the question, or a question of your own?"),
    "opt_my_answer": ("✍️ זו התשובה שלי", "✍️ It's my answer"),
    "opt_my_question": ("❓ זו שאלה שלי", "❓ It's my question"),
    "remind": ("✍️ כשתהיו מוכנים, כתבו כאן את התשובה לשאלה:\n\n> {body}",
               "✍️ When you're ready, write your answer to the question here:\n\n> {body}"),
    "answer_not_sent": ("⚠️ התשובה לא נשלחה. נסו שוב.", "⚠️ Your answer wasn't sent. Try again."),
    "grade": (" ציון: **{grade}/2**", " Grade: **{grade}/2**"),
    "answer_saved_review": ("📝 התשובה נשמרה.{grade}{why}\n\n"
                            "⏳ **התשובה ממתינה למרצה.** הוא יקרא אותה, ואז יאשר לכם להמשיך או יבקש שתענו "
                            "שוב; ההמשך יופיע כאן לבד. בינתיים אפשר לשאול כאן שאלות.",
                            "📝 Your answer was saved.{grade}{why}\n\n"
                            "⏳ **It is waiting for your lecturer.** They will read it, then let you continue or "
                            "ask you to answer again; what comes next will appear here by itself. Meanwhile you "
                            "can ask questions here."),
    "answer_saved": ("✅ התשובה נשמרה.{grade}{why}", "✅ Your answer was saved.{grade}{why}"),
    "question_closed": ("השאלה הזו כבר לא פתוחה (כבר עניתם עליה, או שהמרצה ביטל אותה).",
                        "This question is no longer open (you already answered it, or your lecturer withdrew it)."),
}


def text(key: str, lang: str, **values) -> str:
    """The chat's line `key` in `lang` ('he', else English)."""
    he, en = TEXTS[key]
    s = he if lang == "he" else en
    return s.format(**values) if values else s
