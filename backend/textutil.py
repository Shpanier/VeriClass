"""Small text helpers shared by the review queue, the step checks and the
question bank. No model calls: plain string rules."""
import re

_HEBREW = re.compile(r"[֐-׿]")
_LATIN_WORD = re.compile(r"\b[A-Za-z]{2,}\b")
_HEBREW_WORD = re.compile(r"[א-ת]{2,}")
# Words that are code, not language: identifiers with _ ( ) = / or digits, and
# dotted names like df.isna (a sentence's closing period doesn't count).
_CODE_TOKEN = re.compile(r"\S*(?:[_()\[\]{}=<>/\\]|\w\.\w|\d)\S*")
_ASKS_ENGLISH = re.compile(r"\b(in english|english only|reply in english|answer in english)\b", re.I)


def detect_lang(text: str) -> str:
    """'en' or 'he': the language a student wrote in, so the teacher's queue can
    preselect the matching answer. Code (identifiers, paths, numbers) is ignored,
    so a Hebrew question with `df.isna()` in it is still Hebrew. An explicit
    "reply in English" wins."""
    if _ASKS_ENGLISH.search(text or ""):
        return "en"
    prose = _CODE_TOKEN.sub(" ", text or "")
    hebrew = len(_HEBREW_WORD.findall(prose))
    latin = len(_LATIN_WORD.findall(prose))
    if hebrew == 0:
        return "en" if latin else "he"
    return "en" if latin >= 3 * hebrew else "he"


def has_hebrew(text: str) -> bool:
    return bool(_HEBREW.search(text or ""))


# A question mark that ends a sentence (not one inside a shell glob like file?.txt).
_QUESTION_MARK = re.compile(r"[?？؟](?=\s|$)")
# How a question or a request for help opens, in Hebrew, English and Arabic.
_ASKS = re.compile(
    r"^\W*(?:מה|מהו|מהי|מזה|למה|מדוע|איך|כיצד|מתי|איפה|היכן|מי|האם|"
    r"לא הבנתי|לא מבין|לא מבינה|לא ברור|לא בטוח|לא בטוחה|תסביר|תסבירי|הסבר|תעזור|תעזרי|עזרה|רמז|"
    r"what|why|how|when|where|who|which|can|could|should|is|are|do|does|did|"
    r"i don'?t (?:understand|get|know)|not sure|explain|help|hint|"
    r"ماذا|لماذا|كيف|متى|أين|اين|هل|لم افهم|مش فاهم|ساعدني)\b",
    re.I,
)


def looks_like_question(text: str) -> bool:
    """Does a message ask something rather than answer? A question mark ending
    a sentence, or a question word / "I don't understand" / "explain" at its
    start. Plain string rules: it errs toward asking the student."""
    t = (text or "").strip()
    return bool(t) and bool(_QUESTION_MARK.search(t) or _ASKS.search(t))
