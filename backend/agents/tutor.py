"""Tutor agent — drafts the teacher-reviewable answer variants.

Replaces backend/variants_gen.py. Produces three Socratic help levels
(nudge/normal/more) and one direct answer, each in English AND Hebrew, grounded
in the student's actual conversation (threaded in as memory). The teacher
reviews/edits one before it reaches the student, and can have the four drafted
again by a stronger model (`model=`).
"""
import asyncio
import os

from crewai import Agent, Crew, Process, Task

from backend.agents.llm import claude_llm, default_model_name, gemini_llm
from backend.agents.memory import session_transcript
from backend.agents.schemas import VariantSet

LEVELS = ("nudge", "normal", "more", "direct")

# Eight texts (four answers, two languages) take longer than one reply: Haiku
# needed up to ~30 s for six in class, so the agent default (30 s) is too short.
TIMEOUT_SEC = float(os.environ.get("TUTOR_TIMEOUT_SEC", "120"))
MAX_TOKENS = int(os.environ.get("TUTOR_MAX_TOKENS", "8192"))

# Proven instruction text, carried over from the old variants_gen so the
# drafting behaviour (concrete, grounded, no full solutions) is unchanged; the
# direct answer was added after the October 2026 classes.
_RULES = """\
Produce FOUR answers, and write EACH one in BOTH English and Hebrew
(same meaning in both languages):

Make every reply CONCRETE and grounded in *this* student's situation:
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

The first three are Socratic levels, each strictly more helpful than the previous:
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

The fourth is NOT Socratic:
  direct  — answer the question plainly and completely, the way a teaching
            assistant would at office hours. No counter-questions and no
            "think about…". Name the exact function / command / concept, say
            how to use it here, and add a short example (≤ 6 lines) when it
            helps. It may fully answer what was asked, but it must not write the
            student's whole exercise or a whole step for them.
"""


def _build_crew(system_prompt: str, transcript: str, student_question: str,
                course: str = "Operating Systems", model: str | None = None) -> Crew:
    llm = (claude_llm(model, timeout=TIMEOUT_SEC, max_tokens=MAX_TOKENS) if model
           else gemini_llm(timeout=TIMEOUT_SEC, max_tokens=MAX_TOKENS))
    agent = Agent(
        role="VeriExam teaching assistant",
        goal="Draft graded, bilingual help a teacher will review before it reaches the student.",
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
            f"{_RULES}"
        ),
        expected_output=(
            "A VariantSet: nudge/normal/more/direct, each with en and he text, "
            "grounded in this student's conversation."
        ),
        agent=agent,
        output_pydantic=VariantSet,
    )
    return Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)


async def generate_variants(
    system_prompt: str, session_id: str, student_question: str,
    course: str = "Operating Systems", model: str | None = None,
) -> dict:
    """Return {level: {'en': str, 'he': str}} for level in nudge/normal/more/direct,
    plus 'model': the model that wrote them. [model] names a Claude model to use
    instead of the default (the teacher's regenerate buttons)."""
    transcript = session_transcript(session_id)
    crew = _build_crew(system_prompt, transcript, student_question, course, model)
    # CrewAI is synchronous; run it off the event loop so /ask stays async.
    result = await asyncio.to_thread(crew.kickoff)
    vs: VariantSet = result.pydantic
    out: dict = {lvl: {"en": getattr(vs, lvl).en, "he": getattr(vs, lvl).he} for lvl in LEVELS}
    out["model"] = model or default_model_name()
    return out
