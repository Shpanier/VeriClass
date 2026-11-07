"""Tutor agent — drafts the teacher-reviewable answers.

One call drafts ONE answer at a given help level (nudge, normal, more or
direct), in English AND Hebrew, grounded in the student's actual conversation
(threaded in as memory). The review queue (backend/routes/review.py) runs one
call per answer at the same time, so the teacher sees each answer as soon as
its model is done with it, the shortest first, instead of waiting for all of
them. The teacher reviews/edits one before it reaches the student.
"""
import asyncio
import os

from crewai import Agent, Crew, Process, Task

from backend.agents.llm import claude_llm, default_model_name, gemini_llm
from backend.agents.memory import session_transcript
from backend.agents.schemas import Answer

LEVELS = ("nudge", "normal", "more", "direct")

# One answer in two languages is quick, but a slow model under load took ~30 s
# for several texts in class, so the agent default (30 s) is too short.
TIMEOUT_SEC = float(os.environ.get("TUTOR_TIMEOUT_SEC", "120"))
MAX_TOKENS = int(os.environ.get("TUTOR_MAX_TOKENS", "4096"))

# Proven instruction text, carried over from the old variants_gen so the
# drafting behaviour (concrete, grounded, no full solutions) is unchanged; the
# direct answer was added after the October 2026 classes.
_RULES = """\
Write ONE answer, in BOTH English and Hebrew (same meaning in both languages).

Make the reply CONCRETE and grounded in *this* student's situation:
  • Refer to the actual identifiers the student wrote (their function names,
    structs, enums, variables, DataFrame columns) — not generic placeholders.
  • Point at the specific NEXT step in THEIR code, or the exact place a bug or
    gap is, given the exercise's test inputs and required error strings.
  • Prefer "in your <their_function>, the <X> case isn't handled yet — …" over
    vague advice like "think about how to tokenize the input".
  • Keep code identifiers (function/struct names, language keywords) in Latin letters
    even inside the Hebrew text.

NEVER include the full working solution of the exercise, or of a whole step,
or a complete function body. Always follow the INSTRUCTOR NOTES (for example,
never state numbers the notes say not to reveal).
"""

# What each level is. The three Socratic levels are each strictly more helpful
# than the previous; "direct" is not Socratic.
_LEVEL_RULES = {
    "nudge": """\
The answer's level is NUDGE (Socratic): ONE precise, pointed hint naming the
exact spot in their code to look at, or the single next decision to make
(≤ 2 sentences). A question is fine, but it must be specific to their code,
not generic. No code blocks.""",
    "normal": """\
The answer's level is NORMAL (Socratic): a pointed hint naming the exact spot
in their code, PLUS the concrete next step and WHY it matters, naming the
relevant function / syscall / concept by name. At most a ≤ 3-line illustrative
fragment if essential — never the answer itself.""",
    "more": """\
The answer's level is MORE (Socratic, the most helpful Socratic level): the
hint and the concrete next step with why it matters, PLUS a short worked
micro-example that builds understanding, e.g. trace ONE token/character of ONE
of the given test inputs by hand, or a tight analogy. Still NO full solution,
NO complete function body.""",
    "direct": """\
The answer's level is DIRECT (NOT Socratic): answer the question plainly and
completely, the way a teaching assistant would at office hours. No
counter-questions and no "think about…". Name the exact function / command /
concept, say how to use it here, and add a short example (≤ 6 lines) when it
helps. It may fully answer what was asked, but it must not write the
student's whole exercise or a whole step for them.""",
}


_LANG_NAMES = {"he": "Hebrew", "en": "English"}


def _translate_rule(translate_to: str | None) -> str:
    """The instruction for question_lang / question_translation: translate a
    question the teacher can't read (neither Hebrew nor English) into
    `translate_to`; no translation when it's None."""
    if not translate_to:
        return "\nSet question_lang to the question's language code; leave question_translation empty.\n"
    return (
        "\nAlso set question_lang to the ISO 639-1 code of the language the student's latest\n"
        "question is written in (ignore code identifiers, commands and paths). If that language\n"
        "is NEITHER Hebrew NOR English, set question_translation to a faithful "
        f"{_LANG_NAMES[translate_to]} translation\n"
        "of the question, for the teacher (keep code identifiers, commands and paths as they\n"
        "are). If the question is in Hebrew or English, leave question_translation empty.\n"
    )


def _build_crew(system_prompt: str, transcript: str, student_question: str, level: str,
                course: str = "Operating Systems", model: str | None = None,
                translate_to: str | None = None) -> Crew:
    if level not in _LEVEL_RULES:
        raise ValueError(f"unknown answer level {level!r} (use {', '.join(LEVELS)})")
    llm = (claude_llm(model, timeout=TIMEOUT_SEC, max_tokens=MAX_TOKENS) if model
           else gemini_llm(timeout=TIMEOUT_SEC, max_tokens=MAX_TOKENS))
    agent = Agent(
        role="VeriClass teaching assistant",
        goal="Draft bilingual help a teacher will review before it reaches the student.",
        backstory=(
            f"You assist an instructor in a {course} lab. You never hand "
            "students full solutions; you meet them exactly where their code is."
        ),
        llm=llm,
        verbose=False,
        allow_delegation=False,
    )
    task = Task(
        description=(
            f"{system_prompt}\n\n"
            "CONVERSATION SO FAR (oldest first) — use it as memory; refer back to "
            f"what the student already tried and asked:\n{transcript}\n\n"
            f"The student's latest question is:\n{student_question}\n\n"
            f"{_RULES}\n{_LEVEL_RULES[level]}\n"
            f"{_translate_rule(translate_to)}"
        ),
        expected_output=(
            f"An Answer at the {level} level, with en and he text, grounded in this "
            "student's conversation."
        ),
        agent=agent,
        output_pydantic=Answer,
    )
    return Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)


async def draft(
    system_prompt: str, session_id: str, student_question: str, level: str,
    course: str = "Operating Systems", model: str | None = None,
    translate_to: str | None = None,
) -> dict:
    """One answer at `level` (nudge/normal/more/direct): {'en', 'he', 'model',
    'question_lang', 'question_translation'}. [model] names a Claude model to
    use instead of the default; [translate_to] ('he' or 'en') asks for the
    question's language and a translation when it is in neither (None: don't)."""
    transcript = session_transcript(session_id)
    crew = _build_crew(system_prompt, transcript, student_question, level, course, model, translate_to)
    # CrewAI is synchronous; run it off the event loop so /ask stays async.
    result = await asyncio.to_thread(crew.kickoff)
    a: Answer = result.pydantic
    return {
        "en": a.en, "he": a.he,
        "model": model or default_model_name(),
        "question_lang": (a.question_lang or "").strip().lower()[:8],
        "question_translation": (a.question_translation or "").strip() if translate_to else "",
    }
