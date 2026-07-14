"""Reviewer agent — judges how *wisely* a student used the tutor.

This is the "main part" of the recommended grade. Correctness (did the code
run correctly) is measured deterministically elsewhere; this agent looks at the
whole session — the questions the student asked, how many hints they leaned on
and at what level, their timing/cadence, and how they did on comprehension
probes — and scores whether they used the LLM to genuinely LEARN or just as a
plug-and-play answer machine.

Mirrors backend/agents/grader.py: a single-agent CrewAI crew with structured
output (schemas.GradeRecommendation), Gemini-only, deterministic temperature.
The "instructor who can tell rote LLM-assisted work from real understanding"
framing is borrowed from backend/agents/probe.py so both agents judge the same
gap the same way.
"""
import asyncio
import json

from crewai import Agent, Crew, Process, Task

from backend.agents.llm import gemini_llm
from backend.agents.memory import session_transcript
from backend.agents.schemas import GradeRecommendation

_LANG_NAME = {"en": "English", "he": "Hebrew"}

_RUBRIC = """\
You are an experienced OS instructor grading HOW WISELY a student used an AI
tutor while solving a mini-shell exercise. You can tell rote, plug-and-play
LLM use from genuine learning, and you score exactly that gap.

Score `wise_use` on 0-100. Weigh these, in order:
  1. Question quality — are the student's questions SPECIFIC to their own code,
     variant, and errors (good), or generic "just write the whole thing for me"
     / "give me the full solution" (bad)?
  2. Hint reliance — few, well-targeted hints and gradual escalation (nudge
     before more) is good; leaning on many top-level 'more' hints is bad.
  3. Understanding shown — strong comprehension-probe answers mean they
     understood what they submitted; failed probes on a correct submission is
     the classic plug-and-play tell.
  4. Timing / effort — reasonable thinking time between turns is good; a
     near-zero gap from the tutor's last hint to a correct submission, or long
     time spent outside the IDE, suggests copy-paste rather than learning.

Calibration:
  85-100 excellent: sharp specific questions, minimal/gradual hints, understood it.
  60-84  good: engaged and mostly independent, some reliance.
  40-59  mixed: leaned heavily on the tutor but showed some engagement.
  0-39   plug-and-play: asked for the answer, copy-pasted, little understanding.

IMPORTANT: a fully correct submission does NOT earn a high wise_use score by
itself — a student can paste correct code they don't understand. Judge the
PROCESS, not the result. Return concrete signals, each prefixed '+ ' (good) or
'- ' (concern).
"""


def _build_crew(context: str, lang: str) -> Crew:
    agent = Agent(
        role="learning-process reviewer",
        goal="Score how wisely the student used the AI tutor to learn, not just to get the answer.",
        backstory=(
            "You are an experienced OS instructor who can tell rote LLM-assisted "
            "work from real understanding, and you grade exactly that gap."
        ),
        llm=gemini_llm(temperature=0.0),
        verbose=False,
        allow_delegation=False,
    )
    language = _LANG_NAME.get(lang, "English")
    task = Task(
        description=(
            f"{_RUBRIC}\n\n{context}\n\n"
            f"Write the `rationale` and every `signals` entry in {language} "
            f"(keep code identifiers, hint-level names, and the leading '+ '/'- ' "
            f"markers as-is). The `wise_use` number is language-independent."
        ),
        expected_output=(
            f"A GradeRecommendation: wise_use (0-100), a 2-3 sentence rationale in "
            f"{language}, and a list of concrete + / - signals in {language}."
        ),
        agent=agent,
        output_pydantic=GradeRecommendation,
    )
    return Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)


def _context(exercise_id, variant_id, variant_params, feature_summary,
             source_code, transcript) -> str:
    src = (source_code or "").strip()
    if len(src) > 6000:
        src = src[:6000] + "\n… (truncated)"
    return (
        f"Exercise: {exercise_id}, variant {variant_id} "
        f"with params {json.dumps(variant_params)}\n\n"
        f"MEASURED SIGNALS (deterministic — trust these numbers):\n{feature_summary}\n\n"
        f"CONVERSATION (oldest first, sanitized):\n{transcript}\n\n"
        f"SUBMITTED SOURCE:\n{src or '(no source submitted)'}"
    )


async def recommend(
    session_id: str,
    exercise_id: str,
    variant_id: str,
    variant_params: dict,
    feature_summary: str,
    source_code: str,
    lang: str = "en",
) -> GradeRecommendation:
    """Run the wise-use judgment for one session. Blocking CrewAI call is pushed
    to a thread so the FastAPI event loop stays free (same pattern as grader).
    `lang` sets the language of the rationale + signals (en | he)."""
    transcript = session_transcript(session_id)
    crew = _build_crew(
        _context(exercise_id, variant_id, variant_params, feature_summary,
                 source_code, transcript),
        lang,
    )
    # One retry: the cloud model occasionally returns a transient error, and a
    # single retry turns most of those into a clean structured result rather
    # than falling back to "wise-use unavailable".
    last_exc: Exception | None = None
    for _ in range(2):
        try:
            result = await asyncio.to_thread(crew.kickoff)
            return result.pydantic
        except Exception as exc:  # noqa: BLE001 — retry then re-raise
            last_exc = exc
    raise last_exc
