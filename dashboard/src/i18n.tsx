/**
 * Tiny i18n for the teacher dashboard: an EN/HE toggle with right-to-left
 * support for Hebrew. Wrap the app in <LanguageProvider> and read the current
 * language + translate strings with useLang().
 *
 *   const { lang, setLang, t, dir } = useLang();
 *   <h1>{t("appTitle")}</h1>
 *   <p>{t("studentsConnected", { n: 3 })}</p>   // {n} placeholders
 */
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import type { Lang } from "./types";

const STRINGS = {
  en: {
    // chrome
    appTitle: "OS Lab — Teacher Dashboard",
    language: "עברית", // label shows the OTHER language you can switch to
    on: "On",
    off: "Off",
    close: "Close",
    cancel: "Cancel",
    loading: "Loading…",
    // exercise header
    activeExercise: "Active exercise",
    variantsCount: "{n} variants",
    noStudents: "No active students yet. Share {url} with students to begin.",
    studentsConnected: "{n} student(s) connected",
    // student card
    mentor: "Mentor",
    codingPartner: "Coding Partner",
    outsideIde: "OUTSIDE IDE",
    leftTimes: "left {n}×",
    lastActive: "last active: {t}",
    viewChat: "View chat",
    askThem: "Ask them",
    proctorLog: "Proctor log",
    alerts: "Alerts ({n})",
    openProctorLogTitle: "Open this student's proctor log",
    // proctor banner
    bannerOutside: "{n} student(s) currently OUTSIDE the IDE",
    bannerViolations: "Possible exam violations recorded",
    bannerSummary: "· {leaves} leave event(s) across {students} student(s) this session",
    // ask-them modal
    askTitle: "Targeted question for {name} · {variant}",
    genSuggestions: "⏳ Generating suggestions from cloud LLM…",
    suggestMore: "Suggest more",
    writeOwn: "Write your own question:",
    sendQuestions: "Send {n} question(s)",
    // chat viewer
    autoScroll: "auto-scroll",
    noMessages: "No messages yet. The student hasn't sent anything.",
    chatFooter: "{m} chat message(s) · {p} probe(s) · refreshing every 2s",
    instructorProbe: "instructor probe",
    answerGrade: "answer · grade {g}/2",
    overridden: "(overridden)",
    // proctor log modal
    outsideIdeCaps: "OUTSIDE THE IDE",
    leaveEventsRecorded: "{n} leave event(s) recorded · refreshing every 2s",
    noProctorEvents:
      "No proctor events yet. This student hasn't left the IDE — or isn't running the exam client.",
    awayFor: "away {d}",
    kind_exam_started: "Exam started",
    kind_focus_lost: "Switched away from the IDE",
    kind_minimized: "Minimized the IDE",
    kind_fullscreen_exited: "Exited full screen",
    kind_focus_regained: "Returned to the IDE",
    kind_window_restored: "Restored the window",
    // review queue
    reviewMode: "Teacher review mode",
    reviewOnHint: "Students' questions are held until you edit & send an answer.",
    reviewOffHint: "Off — students get answers directly from the LLM.",
    noQuestions: "No questions waiting.",
    send: "Send",
    sending: "Sending…",
    edited: "edited",
    nudge: "Nudge",
    normal: "Normal",
    more: "Normal + more",
    answersIn: "Suggested answers in",
  },
  he: {
    // chrome
    appTitle: "מעבדת OS — לוח בקרה למורה",
    language: "English",
    on: "פעיל",
    off: "כבוי",
    close: "סגור",
    cancel: "ביטול",
    loading: "טוען…",
    // exercise header
    activeExercise: "תרגיל פעיל",
    variantsCount: "{n} וריאנטים",
    noStudents: "אין עדיין תלמידים פעילים. שתף את {url} עם התלמידים כדי להתחיל.",
    studentsConnected: "{n} תלמידים מחוברים",
    // student card
    mentor: "מנטור",
    codingPartner: "שותף קוד",
    outsideIde: "מחוץ ל-IDE",
    leftTimes: "יצא {n}×",
    lastActive: "פעילות אחרונה: {t}",
    viewChat: "צפה בצ'אט",
    askThem: "שאל אותם",
    proctorLog: "יומן השגחה",
    alerts: "התראות ({n})",
    openProctorLogTitle: "פתח את יומן ההשגחה של התלמיד",
    // proctor banner
    bannerOutside: "{n} תלמידים נמצאים כעת מחוץ ל-IDE",
    bannerViolations: "נרשמו הפרות אפשריות בבחינה",
    bannerSummary: "· {leaves} אירועי יציאה אצל {students} תלמידים במהלך מפגש זה",
    // ask-them modal
    askTitle: "שאלה ממוקדת עבור {name} · {variant}",
    genSuggestions: "⏳ מייצר הצעות מ-LLM בענן…",
    suggestMore: "הצע עוד",
    writeOwn: "כתוב שאלה משלך:",
    sendQuestions: "שלח {n} שאלות",
    // chat viewer
    autoScroll: "גלילה אוטומטית",
    noMessages: "אין עדיין הודעות. התלמיד לא שלח דבר.",
    chatFooter: "{m} הודעות צ'אט · {p} בדיקות · מתרענן כל 2 שניות",
    instructorProbe: "בדיקת מרצה",
    answerGrade: "תשובה · ציון {g}/2",
    overridden: "(נדרס)",
    // proctor log modal
    outsideIdeCaps: "מחוץ ל-IDE",
    leaveEventsRecorded: "{n} אירועי יציאה נרשמו · מתרענן כל 2 שניות",
    noProctorEvents:
      "אין עדיין אירועי השגחה. התלמיד לא יצא מה-IDE — או שאינו מריץ את לקוח הבחינה.",
    awayFor: "בחוץ {d}",
    kind_exam_started: "הבחינה החלה",
    kind_focus_lost: "עבר מחוץ ל-IDE",
    kind_minimized: "מזער את ה-IDE",
    kind_fullscreen_exited: "יצא ממסך מלא",
    kind_focus_regained: "חזר ל-IDE",
    kind_window_restored: "שחזר את החלון",
    // review queue
    reviewMode: "מצב בדיקת מורה",
    reviewOnHint: "שאלות התלמידים ממתינות עד שתערוך ותשלח תשובה.",
    reviewOffHint: "כבוי — התלמידים מקבלים תשובות ישירות מה-LLM.",
    noQuestions: "אין שאלות ממתינות.",
    send: "שלח",
    sending: "שולח…",
    edited: "נערך",
    nudge: "רמז",
    normal: "רגיל",
    more: "רגיל + הרחבה",
    answersIn: "תשובות מוצעות בשפה",
  },
} as const;

export type StringKey = keyof typeof STRINGS["en"];
type Vars = Record<string, string | number>;

function format(s: string, vars?: Vars): string {
  if (!vars) return s;
  return s.replace(/\{(\w+)\}/g, (_, k) => (k in vars ? String(vars[k]) : `{${k}}`));
}

interface LangCtx {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: StringKey, vars?: Vars) => string;
  dir: "ltr" | "rtl";
}

const Ctx = createContext<LangCtx | null>(null);

const STORAGE_KEY = "oslab.lang";

function initialLang(): Lang {
  const saved = typeof localStorage !== "undefined" ? localStorage.getItem(STORAGE_KEY) : null;
  return saved === "he" || saved === "en" ? saved : "en";
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(initialLang);
  const dir = lang === "he" ? "rtl" : "ltr";

  // Drive the whole document direction/lang so layout flips for Hebrew.
  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = dir;
  }, [lang, dir]);

  const setLang = (l: Lang) => {
    setLangState(l);
    try { localStorage.setItem(STORAGE_KEY, l); } catch { /* ignore */ }
  };

  const t = (key: StringKey, vars?: Vars) =>
    format(STRINGS[lang][key] ?? STRINGS.en[key] ?? key, vars);

  return <Ctx.Provider value={{ lang, setLang, t, dir }}>{children}</Ctx.Provider>;
}

export function useLang(): LangCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useLang must be used within <LanguageProvider>");
  return v;
}

/** A small EN/HE toggle button. */
export function LanguageToggle() {
  const { lang, setLang, t } = useLang();
  return (
    <button
      onClick={() => setLang(lang === "en" ? "he" : "en")}
      title="Switch language / החלף שפה"
      style={{
        padding: "6px 12px", border: "1px solid #d1d5db", borderRadius: 6,
        background: "white", cursor: "pointer", fontSize: 14, fontWeight: 600,
      }}
    >
      🌐 {t("language")}
    </button>
  );
}
