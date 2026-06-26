"""Generate teacher-reviewable answer variants for a student question.

Each of three levels is produced in BOTH English and Hebrew so the teacher can
review/edit/send in either language from the dashboard:
  nudge  — a one-line Socratic hint, no answer
  normal — guidance and partial reasoning, no full solution
  more   — normal + extra explanation/examples, still no full solution

Used by /api/ask when review mode is on. The teacher picks one variant (in one
language, possibly edited) in the dashboard; it is sent to the student and
`answer_level` / `chosen_lang` are logged.

generate() returns: {level: {"en": str, "he": str}} for level in nudge/normal/more.
"""
import json
import re

from backend import student_llm

_LEVELS = ("nudge", "normal", "more")
_LANGS = ("en", "he")

_INSTRUCTION = """\
You are drafting candidate replies a teacher will review (and may edit) before
ONE is sent to a student working on this OS lab exercise. The student's full
question and their latest code are in the conversation above — USE THEM.

Produce THREE levels of help, and write EACH level in BOTH English and Hebrew
(same meaning in both languages):

Make every reply CONCRETE and grounded in *this* student's situation:
  • Refer to the actual identifiers the student wrote (their function names,
    structs, enums, variables) — not generic placeholders.
  • Point at the specific NEXT step in THEIR code, or the exact place a bug or
    gap is, given the exercise's test inputs and required error strings.
  • Prefer "in your <their_function>, the <X> case isn't handled yet — …" over
    vague advice like "think about how to tokenize the input".
  • Keep code identifiers (function/struct names, C keywords) in Latin letters
    even inside the Hebrew text.

NEVER include the full working solution or a complete function body.

Tailor each level — each strictly more helpful than the previous:
  nudge   — ONE precise, pointed hint naming the exact spot in their code to
            look at, or the single next decision to make (≤ 2 sentences). A
            question is fine, but it must be specific to their code, not generic.
            No code blocks.
  normal  — the nudge PLUS the concrete next step and WHY it matters, naming the
            relevant function / syscall / concept by name. At most a ≤ 3-line
            illustrative fragment if essential — never the answer itself.
  more    — normal PLUS a short worked micro-example that builds understanding,
            e.g. trace ONE token/character of ONE of the given test inputs by
            hand, or a tight analogy. Still NO full solution, NO complete
            function body.

Reply with STRICT JSON only, no prose, no markdown fences. Shape:
{"nudge": {"en": "...", "he": "..."},
 "normal": {"en": "...", "he": "..."},
 "more": {"en": "...", "he": "..."}}
"""


async def generate(system_prompt: str, history: list[dict], student_question: str) -> dict:
    """Return {level: {'en': str, 'he': str}} for level in nudge/normal/more."""
    msgs = list(history) + [
        {"role": "user", "content": student_question},
        {"role": "user", "content": _INSTRUCTION},
    ]
    chunks: list[str] = []
    # Teacher-side generation: use TEACHER_LLM (falls back to STUDENT_LLM).
    async for tok in student_llm.stream_chat(
        system_prompt, msgs, backend=student_llm.TEACHER_BACKEND
    ):
        chunks.append(tok)
    raw = "".join(chunks).strip()
    return _parse(raw)


def _parse(raw: str) -> dict:
    text = raw.strip()
    # Strip ```json ... ``` fences if the model added them anyway.
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    # Pluck the outermost JSON object if there's extra prose.
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        text = m.group(0)
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, AttributeError):
        # Fall back so the teacher still sees *something* and can pick.
        return {lvl: dict(_placeholder(lvl, raw=raw)) for lvl in _LEVELS}

    out: dict = {}
    for lvl in _LEVELS:
        node = obj.get(lvl)
        if isinstance(node, dict):
            en = str(node.get("en", "")).strip()
            he = str(node.get("he", "")).strip()
        else:
            # Model collapsed to a single string — use it for both, better than
            # nothing; teacher can translate/edit in the box.
            en = he = str(node or "").strip()
        ph = _placeholder(lvl)
        out[lvl] = {"en": en or ph["en"], "he": he or ph["he"]}
    return out


_PLACEHOLDERS = {
    "nudge": {
        "en": "What part of the input are you having trouble parsing?",
        "he": "איזה חלק של הקלט קשה לך לפענח?",
    },
    "normal": {
        "en": "Think about how each token in the input maps to an operation. "
              "Try printing them in order first.",
        "he": "חשוב כיצד כל טוקן בקלט ממופה לפעולה. נסה קודם להדפיס אותם לפי הסדר.",
    },
    "more": {
        "en": "Walk through one test input by hand on paper. Which token is the "
              "operator? Which are the operands?",
        "he": "עבור על קלט בדיקה אחד ביד על נייר. איזה טוקן הוא האופרטור? "
              "אילו הם האופרנדים?",
    },
}


def _placeholder(level: str, raw: str = "") -> dict:
    base = _PLACEHOLDERS[level]
    if not raw:
        return dict(base)
    note = f"\n\n(model output was not valid JSON; raw: {raw[:200]})"
    return {"en": base["en"] + note, "he": base["he"] + note}
