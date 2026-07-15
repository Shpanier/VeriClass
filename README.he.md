<div dir="rtl" align="right">

# VeriExam — מודל שפה בשליטת המרצה

> 🇮🇱 גרסה עברית · [English version](README.md)

פלטפורמת מעבדה מבוססת מודל שפה (LLM) מקומי, שנבנתה עבור קורס *מבוא למערכות הפעלה* במכללת JCE. הסטודנטים משוחחים עם מודל שפה קטן שרץ מקומית בזמן שהם עובדים על תרגיל תכנות; המרצה צופה בכל שיחה בזמן אמת ויכול להתערב — באמצעות שאלות הבנה ממוקדות, החלפת אישיות המודל, או (במצב הקפדני ביותר) סקירה ועריכה של כל תשובה לפני שהיא מגיעה לסטודנט.

המאגר כולל תרגיל הדגמה מוכן (`ex3-mcalc`, עם 8 וריאנטים), כך שהמערכת עובדת מהרגע שהיא מותקנת — ללא צורך בהגדרות נוספות.

הסטודנטים ניגשים לחונך דרך אחד משני קליינטים מתחלפים מול אותו צד שרת: אפליקציית וויב של **Chainlit** (לשונית בדפדפן) או **תוסף ל־CLion** שמטמיע את אותו זרם של כניסה ← תדריך ← צ׳אט ← שאלות הבנה בתוך חלון כלים לצד הקוד. ראו [קליינט סטודנט חלופי: תוסף ה־CLion](#קליינט-סטודנט-חלופי-תוסף-ה־clion).

---

## למה זה קיים — הבעיה החינוכית

שימוש במודלי שפה בקורסי תכנות בסיסיים אינו עוד שאלה של "אם" אלא של "איך". הסטודנטים *משתמשים* ב־ChatGPT / Copilot / Gemini בין אם נרצה ובין אם לא. השאלה האמיתית היא **איך לשלב אותם בצורה שמשמרת למידה**.

שילוב נאיבי ("בואו ניתן לכל סטודנט חלון צ׳אט") מוביל לשתי בעיות מוכרות:

1. **מכונת התשובות.** המודל מייצר פתרון שלם ומלוטש בקליק הראשון. הסטודנט מעתיק־מדביק, הטסט עובר, והסטודנט לא למד דבר.
2. **השיחה הסמויה.** למרצה אין מושג *איך* הסטודנט השתמש במודל — האם נתקע? האם המודל הטעה אותו? האם פתר הכל בקליק אחד או נאבק בצורה פורייה?

המערכת הזו מטפלת בשתי הבעיות, ומוסיפה יכולת שלישית שפלטפורמות LLM מסחריות לא מציעות: **התאמה אישית לכל סטודנט** באמצעות וריאנטים של התרגיל, כך ששני סטודנטים לא יכולים פשוט לחלוק תשובה.

העיצוב נשען על ארבעה רעיונות:

- **המרצה בלולאה.** כל שכבת התערבות — מצפייה פסיבית ועד פיקוח מלא על כל תשובה — זמינה. המרצה בוחר כמה לשלוט, בהתאם לשלב הפדגוגי של המעבדה.
- **הקצאת וריאנטים.** כל סטודנט מקבל אחד מתוך N וריאנטים פרמטריים של התרגיל, באופן דטרמיניסטי. הטסטים שלו שונים. תמליל שיחה של חבר לא יעבור את הטסטים שלו.
- **שאלות הבנה (probes).** באמצע המעבדה, המרצה יכול לירות שאלה ממוקדת לסטודנט אחד או לכמה. הסטודנט חייב לענות לפני שהשיחה ממשיכה. התשובות נבדקות אוטומטית ונשמרות לצד התמליל — מקור הערכה שלא תלוי במודל.
- **מקומיות (Local-first).** התעבורה של הסטודנט לא יוצאת מהרשת המקומית. הקריאה היחידה לשירות חיצוני היא הצעות השאלות שהמרצה מבקש מהמודל הענני, גם זה אחרי ניקוי PII ועם תיעוד מלא של מטריקות.

זוהי פלטפורמת מחקר פעילה לשאלה הרחבה של המחלקה שלנו: *איך נראית הוראת מדעי המחשב אחראית, מתווכת־LLM, בפועל?*

---

## שלושת מצבי ההוראה

המצבים בלתי תלויים — אפשר לשלב ביניהם לפי סטודנט, לפי שיחה, או באופן גלובלי במהלך מעבדה.

### 1. מצב אישיות — `mentor` (חונך) מול `coding_partner` (שותף לקוד)
נקבע לפי שיחה, מתוך הכרטיס של הסטודנט בלוח הבקרה.

- **mentor (חונך)** — סוקרטי. המודל מחזיר שאלות, מסרב לכתוב קוד שלם, מצביע על מושגים רלוונטיים. ברירת מחדל לתרגילים בתחילת הקורס.
- **coding_partner (שותף לקוד)** — שיתופי. המודל יכול לכתוב קטעי קוד קטנים אך עדיין נמנע מפתרון מוכן. ברירת מחדל לתרגילים מתקדמים, אחרי שהסטודנטים הוכיחו הבנה.

האישיות ממומשת כמתג בפרומפט המערכת (`backend/prompts.py`) וזוהי ההתערבות הרכה ביותר: המודל עונה ישירות לסטודנט, את/ה רק מעצב/ת את הסגנון.

### 2. מצב שאלות הבנה (Probe) — שאלות יזומות על־ידי המרצה
בכל רגע, המרצה פותח *Ask Them* בכרטיס של סטודנט וגם:
- כותב שאלה ידנית, או
- לוחץ **Suggest** — המודל הענני קורא את התמליל האחרון של הסטודנט ומציע 2–3 שאלות הבנה ממוקדות לפי הפערים שזיהה.

הצ׳אט של הסטודנט נקטע על־ידי השאלה. התשובה שלו מקבלת ציון אוטומטי (0–2) ונשמרת. ניתן לדרוס את הציון האוטומטי בהמשך.

זהו עמוד התווך של ההערכה: שאלות ההבנה בודקות אם הסטודנט *מבין* את מה שהמודל עזר לו לייצר.

### 3. מצב סקירה (Teacher-review) — פיקוח מלא
מתג גלובלי בלוח הבקרה. כשהוא דלוק:

1. הסטודנט שואל שאלה.
2. צד השרת מייצר **שלוש גרסאות תשובה** בקריאת LLM אחת:
   - **Nudge (רמיזה)** — שורת רמז סוקרטית אחת, ללא תשובה.
   - **Normal (רגיל)** — הכוונה ועוד הצבעה קטנה, ללא פתרון מלא.
   - **Normal + more (רגיל + הסבר)** — כמו רגיל, עם הסבר נוסף או אנלוגיה.
3. השאלה ושלוש הגרסאות מופיעות בתור הסקירה של המרצה. הסטודנט רואה *"המורה סוקר/ת את השאלה שלך…"*.
4. המרצה בוחר אחת. הטקסט הזה נשלח אל הסטודנט בזרימה.
5. הרמה הנבחרת מתועדת בעמודה `messages.answer_level` לצורך מתאם עתידי עם הציון של הסטודנט.

מומלץ להפעיל מצב זה במעבדות עם משקל הערכה גבוה, בבחנים, או כאשר סטודנט מסוים זקוק לתמיכה ממוקדת. המודל **לעולם** לא מחזיר פתרון מלא בשום רמה — האילוץ הזה אכוף בסוכן ה־tutor (`backend/agents/tutor.py`). הטיוטות מבוססות על השיחה האמיתית של הסטודנט (מוזרמת כזיכרון), כך שהן עונות ל*סטודנט הזה* ולא חוזרות על תשובות גנריות.

---

## רכיבים

<div dir="ltr">

| # | Component        | Stack                        | Port  |
|---|------------------|------------------------------|-------|
| 1 | Agents           | CrewAI on Gemini (review drafts, probes, grading) | — |
| 2 | Student chat     | Gemini (streaming)           | —     |
| 3 | Backend          | FastAPI + SQLite (WAL)       | 8010  |
| 4 | Student app      | Chainlit                     | 8011  |
| 4b| Student app (alt)| CLion plugin (Kotlin)        | בתוך ה־IDE |
| 5 | Instructor dash  | React + Vite + TypeScript    | 5173  |

</div>

לסטודנט יש **שני קליינטים מתחלפים** מול אותו צד שרת: אפליקציית הוויב של Chainlit (רכיב 4) ו**תוסף ל־CLion** (רכיב 4b) שמכניס את אותו זרם של כניסה ← תדריך ← צ׳אט ← שאלות הבנה אל תוך ה־IDE. ראו [*קליינט סטודנט חלופי: תוסף ה־CLion*](#קליינט-סטודנט-חלופי-תוסף-ה־clion) ואת [`oslab_plugin/README.md`](oslab_plugin/README.md).

המודל המקומי הוא הנתיב היחיד שרואה הודעות של סטודנטים. המודל הענני משמש **אך ורק** להצעות שאלות הבנה למרצה (`/api/probe/suggest`), ורק אחרי ש־`backend/sanitize.py` הסיר שמות, קודים ומידע מזהה אחר.

---

## התקנה מהירה

<div dir="ltr">

```bash
# 1. תלויות Python
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. הגדרות
cp .env.example .env
# ערוך את .env — קבע GEMINI_API_KEY (המפתח היחיד שצריך)

# 4. זריעת סטודנטים — וגם לפחות מרצה אחד (ראו "כניסת מרצה" למטה)
python scripts/add_students.py \
  --names "Yossi Cohen,Shira Levi,Ahmed Alyan" \
  --teachers "Dr. Cohen"
```

</div>

חשבונות הדגמה לאחר זריעה:

<div dir="ltr">

| Name         | Login code | Role    |
|--------------|------------|---------|
| Instructor   | TEACH-XXXX   | teacher |
| Yossi Cohen  | STU1-XXXX   | student |
| Shira Levi   | STU2-XXXX   | student |
| Ahmed Alyan  | STU3-XXXX   | student |

</div>

> היכנסו ללוח הבקרה (`http://localhost:5173`) עם קוד ה**מרצה** **`TEACH-XXXX`**.
> הקודים אצלכם יהיו שונים — סקריפט הזריעה מייצר אותם באקראי; הריצו את שאילתת
> ה־`sqlite3` בסעיף "כניסת מרצה" כדי לראות את שלכם.

הסטודנטים פותחים את `http://localhost:8011`, המרצה את `http://localhost:5173`.
מעדיפים את ה־IDE? דלגו על הדפדפן והשתמשו בקליינט תוסף ה־CLion במקום — ראו [קליינט סטודנט חלופי: תוסף ה־CLion](#קליינט-סטודנט-חלופי-תוסף-ה־clion).

### כניסת מרצה

לוח הבקרה (`http://localhost:5173`) מוגן מאחורי כניסת מרצה — מסך הכניסה שלו מציג
**"כניסת מרצה — enter your instructor code"**. מרצה נכנס עם **קוד כניסה**, בדיוק
כמו סטודנט, רק שהחשבון שלו נושא `role=teacher`. קוד של סטודנט נדחה כאן
(*"That code isn't an instructor account."*).

צרו קודי מרצה עם אותו סקריפט זריעה, בעזרת `--teachers`:

<div dir="ltr">

```bash
python scripts/add_students.py --teachers "Dr. Cohen,TA Levi"
```

</div>

הסקריפט מדפיס טבלת `name → code` (בקטע נפרד **"teachers (dashboard login)"**).
מסרו את הקוד למרצה; הוא מקליד אותו במסך הכניסה (הקודים אינם תלויי אותיות
גדולות/קטנות). כדי להוסיף מרצה לבסיס נתונים קיים ישירות:

<div dir="ltr">

```bash
sqlite3 oslab.db \
  "INSERT INTO users(username, login_code, role) VALUES('Dr. Cohen','TEACH-01','teacher');"
```

</div>

לרשימת קודי המרצה שכבר קיימים בבסיס הנתונים בכל רגע:

<div dir="ltr">

```bash
sqlite3 oslab.db "SELECT username, login_code FROM users WHERE role='teacher';"
```

</div>

רק חשבון עם `role=teacher` יכול לפתוח את לשונית **התרגילים** וליצור תרגילים
חדשים, להחליף את אישיות המודל של סטודנט, או להפעיל מצב סקירה.

---

## הרצה ב־קליק אחד — `scripts/dev_up.sh`

הרצת שלושה שירותים בשלושה טרמינלים נפרדים זה מעצבן. סקריפט ההפעלה עושה את זה בפקודה אחת:

<div dir="ltr">

```bash
./scripts/dev_up.sh
```

</div>

מה הוא עושה:

1. **הורג** כל מה שמאזין על הפורטים `8010`, `8011`, `5173` (וגם הישנים `8000`/`8001`), וגם תהליכי `uvicorn backend.main` / `chainlit run student_app` שנשארו לבד. שימושי אחרי קריסה שבה התהליך הקודם עדיין מחזיק את הפורט.
2. **פותח חלון Terminal חדש עם שלוש לשוניות:**
   - לשונית 1: `uvicorn backend.main:app --reload --port 8010`
   - לשונית 2: `chainlit run student_app/app.py --port 8011`
   - לשונית 3: `cd dashboard && npm run dev`
3. שתי הלשוניות של פייתון מבצעות `source .venv/bin/activate` אוטומטית לפני ההפעלה.

**בקשת הרשאה בהפעלה הראשונה.** macOS יבקש מ־Terminal לשלוט ב־*System Events* (נדרש עבור הקלדת ⌘T שיוצרת לשוניות חדשות). אשרו פעם אחת ב־*System Settings → Privacy & Security → Accessibility*.

**כניסה אוטומטית במצב פיתוח.** הגדירו את `DEV_AUTO_LOGIN_CODE` בקובץ `.env` עם קוד של סטודנט (לדוגמה: `STU1-XXXX`). אפליקציית הסטודנט תדלג על מסך הכניסה ותתחבר אוטומטית — נוח כשעושים רענון לדף עשרות פעמים בזמן פיתוח. השאירו את המשתנה ריק בייצור.

---

## תהליך מומלץ למרצה

מעבדה של 90 דקות, מקצה לקצה:

**לפני השיעור (5 דקות)**
- `./scripts/dev_up.sh` — ודאו ששלוש הלשוניות עולות תקין.
- פתחו את לוח הבקרה. ודאו שהתרגיל הפעיל הוא הנכון (`config/exercises/*.yaml`).
- החליטו על פרופיל המצבים שלכם לשיעור הזה. בחירות נפוצות:
  - *תרגול פתוח:* אישיות=`coding_partner`, מצב סקירה כבוי, שאלות הבנה מדי פעם.
  - *מעבדה מודרכת:* אישיות=`mentor`, מצב סקירה כבוי, שאלות הבנה תכופות.
  - *מעבדת הערכה:* אישיות=`mentor`, **מצב סקירה דלוק**, שאלות הבנה לכל סטודנט.

**במהלך השיעור**
- הסטודנטים מתחברים עם הקודים שלהם (מודפסים/מוקרנים). כל אחד מקבל וריאנט שהוקצה לו דטרמיניסטית.
- צפו ברשת הסטודנטים. כל כרטיס מציג: שם, וריאנט, מצב, פעילות אחרונה, מספר שאלות הבנה.
- לחצו *View chat* בכל כרטיס כדי לראות את התמליל בזמן אמת.
- לחצו *Ask them* כדי לפתוח את מודאל שאלת ההבנה:
  - כתבו שאלה, או
  - *Suggest* — המודל הענני מציע שאלות ממוקדות לפי הפעילות האחרונה של הסטודנט.
- אם סטודנט רץ מהר מדי / נשען על המודל יותר מדי, הפעילו את מצב הסקירה. השאלה הבאה שלו תגיע לתור שלכם.

**אחרי השיעור**
- כל התמלילים ותוצאות שאלות ההבנה נמצאים ב־`oslab.db`. שאילתות שימושיות:

<div dir="ltr">

```sql
-- ציוני שאלות הבנה לפי סטודנט
SELECT u.username, COUNT(p.id) AS probes,
       AVG(COALESCE(p.override_grade, p.auto_grade)) AS avg_score
FROM users u
JOIN sessions s ON s.user_id = u.id
JOIN probes p ON p.session_id = s.id
WHERE p.status = 'answered'
GROUP BY u.username;

-- התפלגות רמות התשובה שנבחרו במצב סקירה
SELECT s.user_id, answer_level, COUNT(*)
FROM messages m JOIN sessions s ON s.id = m.session_id
WHERE answer_level IS NOT NULL
GROUP BY s.user_id, answer_level;
```

</div>

---

## חוויית הסטודנט

מה הסטודנט רואה:

1. מזין/ה קוד כניסה ← מקבל/ת וריאנט של התרגיל הפעיל.
2. מקבל/ת בועת תדריך: כותרת התרגיל, הפרמטרים האישיים, קלטי הטסטים, המצב הנוכחי.
3. הצעות פתיחה מופיעות כשבבים לחיצים (ניתן להגדיר ב־YAML של התרגיל).
4. משוחח/ת עם המודל עד שמרוצה מהפתרון.
5. בכל רגע עשויה להגיע שאלת הבנה: *"המרצה שואל אותך…"*. חייב/ת לענות לפני שהצ׳אט ממשיך; הציון האוטומטי מופיע מיד.

סטודנטים לא יכולים לראות עבודה של אחרים, להחליף וריאנטים, או לדלג על שאלות הבנה. הצ׳אט מוגן באמצעות רשימת ביטויים אסורים נגד prompt injection ב־`backend/routes/ask.py`.

החוויה הזו זהה בין אם הסטודנט משתמש באפליקציית הוויב של Chainlit ובין אם בתוסף ה־CLion. במצב `ide` של התוסף (ראו בהמשך), שלבים 1–5 זהים, והתוסף בנוסף יוצר קובץ `mcalc.c` התחלתי בתוך הפרויקט ומציג את קלטי הטסט כרשימת סימון.

---

## קליינט סטודנט חלופי: תוסף ה־CLion

הסטודנטים בקורס הזה ממילא כותבים את קוד ה־C שלהם ב־CLion. הספרייה
[`oslab_plugin/`](oslab_plugin/) היא תוסף JetBrains שמטמיע את *כל* קליינט הסטודנט
בתוך חלון כלים (tool window) ב־CLion, כך שלא צריך לצאת מה־IDE כדי לדבר עם החונך.
הוא משתמש באותם שישה endpoints של צד השרת כמו Chainlit — צד השרת ללא שינוי, פרט
ל־endpoint קטן אחד לקריאה בלבד (`GET /api/client-config`) שחושף את מתג ההתנהגות.

התוסף כולל **שתי התנהגויות בתוסף אחד**, והמרצה בוחר איזו פעילה דרך **משתנה `.env`
יחיד בצד השרת** (כך שכל הסטודנטים נשלטים ממקום אחד — זו *אינה* הגדרה לכל סטודנט):

<div dir="ltr">

| `.env`                       | התנהגות התוסף |
|------------------------------|-----------------|
| `STUDENT_CLIENT_MODE=chat`   | פורט צ׳אט נאמן — כניסה, תדריך, צ׳אט בזרימה, שבבי הצעות, שאלות הבנה. זהה ל־Chainlit, בתוך חלון כלים. |
| `STUDENT_CLIENT_MODE=ide`    | כל מה שב־`chat`, **ובנוסף** יוצר קובץ C התחלתי (`mcalc.c`) לוריאנט שהוקצה לסטודנט בתוך הפרויקט הפתוח, ומציג את קלטי הטסט הנדרשים כרשימת סימון. |

</div>

בנייה והרצה (פירוט מלא ב־[`oslab_plugin/README.md`](oslab_plugin/README.md)):

<div dir="ltr">

```bash
cd oslab_plugin
gradle wrapper --gradle-version 8.10.2   # פעם אחת, יוצר את ה-wrapper jar
./gradlew :clion:runIde                  # מריץ CLion ארגז-חול עם התוסף טעון
./gradlew :pycharm:runIde                # מריץ PyCharm ארגז-חול עם התוסף טעון
```

</div>

בארגז־החול, הגדירו את כתובת צד השרת תחת **Settings → Tools → VeriExam**, פתחו את
חלון הכלים **VeriExam**, והתחברו עם קוד קורס. אפשר להשתמש ב־Chainlit ובתוסף בו־זמנית
מול אותו צד שרת.

---

## עיצוב תרגילים חדשים

תרגילים מוגדרים בקבצי YAML בספרייה `config/exercises/`. מבנה מינימלי:

<div dir="ltr">

```yaml
exercise_id: ex4-myexercise
title_en: My Exercise
default_mode: mentor       # mentor | coding_partner
brief_md: |
  Markdown shown to the student in the briefing bubble.
welcome_suggestions:
  - "How should I start?"
  - "What does the test input look like?"
variants:
  - id: A
    params: { N: 5, operator: "+" }
    test_inputs:
      - { input: "1+1", expected_output: "2" }
  - id: B
    ...
```

</div>

המערכת בוחרת את התרגיל *הפעיל* (ראשון לפי סדר אלפביתי בספרייה כברירת מחדל). וריאנטים מוקצים לסטודנטים על־פי hash של ה־user id — כך שאותו סטודנט תמיד מקבל את אותו וריאנט בכל השיחות שלו.

מטרות עיצוב לסט וריאנטים טוב:
- אותה רמת קושי קונספטואלית בכל הוריאנטים.
- שונים מספיק כדי שתמליל של חבר לא יעבור את הטסטים שלך.
- קלטי טסט שמכסים מקרי קצה הקשורים לפרמטרים של הוריאנט.

---

## פרטיות וריבונות נתונים

זהו כלי הוראה המשמש סטודנטים (חלקם מתחת לגיל 18) במוסד ציבורי, ולכן עמדת ברירת המחדל בנושא פרטיות שמרנית:

- **Gemini הוא ספק ה־LLM היחיד.** צ׳אט הסטודנט וסוכני CrewAI (טיוטות תשובה, שאלות הבנה, ניקוד) רצים כולם על Gemini של Google — אין נתיב Ollama מקומי ואין מנגנון גיבוי רב־ספקי. הודעות הסטודנטים מעובדות אצל Google; התאימו את ההסכמה/ההודעה בהתאם.
- **כל מה שנשלח לסוכנים מנוקה תחילה.** `backend/sanitize.py` מסיר שמות, מספרי ת״ז, אימיילים, מספרי טלפון ונתיבי בית מהתמליל לפני שהוא מוזרם לסוכן.
- **יומן ביקורת.** כל קריאה ענית נכתבת ל־`api_audit_log` עם הספק, המודל, ספירת טוקנים, latency, הקלט המנוקה, ועותק מוצפן AES של הקלט הגולמי. הגדירו `AUDIT_AES_KEY` ב־`.env`.
- **שום חשבון סטודנט לא יוצא מבסיס הנתונים.** קודי הכניסה נוצרים מקומית על־ידי `scripts/add_students.py`; אין SSO, אין איסוף אימיילים, אין אימות צד שלישי.

---

## מבנה המאגר

<div dir="ltr">

```
config/
  exercises/ex3-mcalc.yaml   # the demo exercise + 8 variants
  cloud_llm.yaml             # Gemini model + timeout for the agent layer
  instructors.yaml.example   # copy to instructors.yaml and edit

backend/                     # FastAPI app
  main.py                    # entrypoint, loads .env early
  db.py                      # SQLite schema + tiny migration runner
  auth.py                    # login codes, bearer tokens, rate-limit
  student_llm.py             # Gemini-only streaming for the direct student chat
  gemini_student.py          # httpx streaming + grader against Gemini
  agents/                    # CrewAI agent layer (Gemini only)
    llm.py                   #   single Gemini LLM factory
    memory.py                #   conversation memory (transcript + prior probes)
    schemas.py               #   structured-output models
    tutor.py                 #   review-mode answer drafts (replaces variants_gen)
    probe.py                 #   "Ask Them" probe suggestions (replaces cloud_llm)
    grader.py                #   probe answer grading
  sanitize.py                # PII scrub before anything leaves for Gemini
  variants.py                # deterministic student → variant assignment
  prompts.py                 # system prompts per (exercise, mode)
  exercises.py               # YAML loader and accessor
  routes/
    login.py, sessions.py, exercises.py, ask.py,
    probes.py, students.py, mode.py, review.py

student_app/
  app.py                     # Chainlit student UI (login + chat + probes)

oslab_plugin/                # alternative student client: a CLion/JetBrains plugin
  build.gradle.kts           # IntelliJ Platform Gradle build (targets CLion)
  src/main/kotlin/edu/jce/oslab/
    api/                     # DTOs + HTTP/streaming client over the 6 endpoints
    ui/                      # tool window, login, briefing, chat, checklist
    probe/                   # 2s probe poller + answer dialog
    ide/                     # `ide` mode: scaffold mcalc.c into the project
    settings/, util/

dashboard/
  src/App.tsx                # student grid + modals + review queue
  src/components/            # StudentGrid, ChatViewModal, AskThemModal,
                             #   ReviewQueue, ExerciseHeader

scripts/
  add_students.py            # seed users + login codes
  dev_up.sh                  # kill old + launch all three services
```

</div>

---

## עיון בהגדרות

`.env` (העתק מ־`.env.example`):

<div dir="ltr">

| Variable              | Purpose                                                       |
|-----------------------|---------------------------------------------------------------|
| `GEMINI_API_KEY`      | The only LLM key. Powers the CrewAI agents and the student chat. |
| `AGENT_MODEL`         | Gemini model for the agents (review drafts, probes, grading). Default `gemini-2.5-pro`. |
| `STUDENT_CHAT_MODEL`  | Gemini model for the direct student chat. Default `gemini-2.5-flash-lite`. |
| `DB_PATH`             | `./oslab.db` by default.                                      |
| `AUDIT_AES_KEY`       | 32-byte base64 key for encrypting raw cloud-LLM payloads.     |
| `DEV_AUTO_LOGIN_CODE` | If set, student app auto-logs in with this code (dev only).   |
| `STUDENT_CLIENT_MODE` | CLion plugin behavior: `chat` (default) or `ide`. Ignored by Chainlit. |
| `SCAFFOLD_FILENAME`   | File the plugin's `ide` mode scaffolds into the project. Default `mcalc.c`. |

</div>

`config/cloud_llm.yaml` מגדיר את מודל ה־Gemini והזמן הקצוב לשכבת הסוכנים. הכול רץ על מפתח `GEMINI_API_KEY` היחיד.

---

## מחקר וכיוונים עתידיים

זוהי פלטפורמת מחקר, לא מוצר מוגמר. כיוונים פתוחים שאנו חוקרים:

- **תמיכה מסתגלת (Adaptive scaffolding).** בחירה אוטומטית של רמת התשובה (nudge / normal / more) לפי היסטוריית שאלות ההבנה של הסטודנט, במקום קליק של המרצה.
- **מספר תרגילים פעילים בו־זמנית.** כרגע יש תרגיל פעיל יחיד. אנו רוצים תרגילים מקבילים עם הקצאה לפי קבוצה.
- **זיכרון בין־שיחות עבור המרצה.** תצוגה ארוכת־טווח לכל סטודנט, שמצרפת שאלות הבנה, שימוש במצבים, ורמות תשובה שנבחרו.
- **שחזריות (Replicability).** אריזה כסטאק Docker יחיד למחלקות שלא רוצות להריץ Python ו־Node בעצמן.

תרומות ודיווחי באגים יתקבלו בברכה — פתחו issue או PR.

---

## רישיון וייחוס

נבנה בסמינר *הנדסת תוכנה*, המכללה האקדמית להנדסה ירושלים ע״ש עזריאלי (JCE).
שימוש למטרות חינוך ומחקר.

</div>
