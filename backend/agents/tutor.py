"""Tutor agent — drafts the teacher-reviewable answer variants.

Replaces backend/variants_gen.py. Produces three help levels (nudge/normal/more),
each in English AND Hebrew, grounded in the student's actual conversation
(threaded in as memory). The teacher reviews/edits one before it reaches the
student.
"""
import asyncio

from crewai import Agent, Crew, Process, Task

from backend.agents.llm import gemini_llm
from backend.agents.memory import session_transcript
from backend.agents.schemas import VariantSet

# Proven instruction text, carried over verbatim from the old variants_gen so the
# drafting behaviour (concrete, grounded, no full solutions) is unchanged.
_RULES = """\
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
"""


def _build_crew(system_prompt: str, transcript: str, student_question: str) -> Crew:
    agent = Agent(
        role="OS-lab teaching assistant",
        goal="Draft graded, bilingual help a teacher will review before it reaches the student.",
        backstory=(
            "You assist an instructor in an Operating Systems lab. You never hand "
            "students full solutions; you meet them exactly where their code is."
        ),
        llm=gemini_llm(),
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
            "A VariantSet: nudge/normal/more, each with en and he text, grounded "
            "in this student's conversation."
        ),
        agent=agent,
        output_pydantic=VariantSet,
    )
    return Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)


async def generate_variants(
    system_prompt: str, session_id: str, student_question: str
) -> dict:
    """Return {level: {'en': str, 'he': str}} for level in nudge/normal/more.

    Same shape the old variants_gen.generate returned, so routes/ask.py only
    needs to swap the call.
    """
    transcript = session_transcript(session_id)
    crew = _build_crew(system_prompt, transcript, student_question)
    # CrewAI is synchronous; run it off the event loop so /ask stays async.
    result = await asyncio.to_thread(crew.kickoff)
    vs: VariantSet = result.pydantic
    return {
        "nudge": {"en": vs.nudge.en, "he": vs.nudge.he},
        "normal": {"en": vs.normal.en, "he": vs.normal.he},
        "more": {"en": vs.more.en, "he": vs.more.he},
    }
