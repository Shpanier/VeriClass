"""Probe agent — drafts targeted comprehension questions ("Ask Them").

Replaces backend/cloud_llm.suggest_probes. Two fixes over the old one-shot call:
  • Memory: the real session transcript is threaded in (the old code stubbed
    latest_code/action_log as "(not yet wired)").
  • No repeats: prior probes are listed with an explicit "ask something DIFFERENT"
    instruction, so "Suggest more" stops returning the same questions.
The teacher can request the questions in English or Hebrew.
"""
import asyncio
import json

from crewai import Agent, Crew, Process, Task

from backend.agents.llm import gemini_llm
from backend.agents.memory import prior_probes, session_transcript
from backend.agents.schemas import ProbeItem, ProbeList

_LANG_NAME = {"en": "English", "he": "Hebrew"}

# Good/bad guidance carried over from prompts.probe_meta_prompt.
_GUIDANCE = """\
You help an instructor write targeted questions to verify a student actually
understands what they just had an LLM help them with.

Each question must be SPECIFIC to this student's conversation and variant — not
generic. GOOD vs BAD:
  BAD (generic): 'Explain how recursive descent works.'
  GOOD (targeted): 'Your variant allows %, and you asked the LLM how to add
  modulo to your parser. In your current parseTerm, which line would change to
  add %, and why would adding it after * break operator precedence?'

Return 3 questions. Each has:
  - kind: one of [Trace, Why, Counterfactual, Failure-mode, Bug-localization]
  - body: the question (1-3 sentences)
  - rationale: one short line on what it tests
"""


def _build_crew(variant_id, variant_params, transcript, prior, lang) -> Crew:
    avoid = (
        "Do NOT repeat or lightly reword any of these already-sent questions — "
        "ask about DIFFERENT aspects:\n" + "\n".join(f"  - {p}" for p in prior)
        if prior
        else "No questions have been sent yet."
    )
    agent = Agent(
        role="comprehension-probe author",
        goal="Write pointed questions that reveal whether the student truly understands their own code.",
        backstory=(
            "You are an experienced OS instructor who can tell rote LLM-assisted "
            "work from real understanding, and you probe exactly the gap."
        ),
        llm=gemini_llm(),
        verbose=False,
        allow_delegation=False,
    )
    task = Task(
        description=(
            f"{_GUIDANCE}\n\n"
            f"Context (already sanitized):\n"
            f"- Variant: {variant_id} with params {json.dumps(variant_params)}\n"
            f"- Conversation so far (oldest first), use it as memory:\n{transcript}\n\n"
            f"{avoid}\n\n"
            f"Write every question in {_LANG_NAME.get(lang, 'English')}."
        ),
        expected_output="A ProbeList with exactly 3 targeted, non-repeating questions.",
        agent=agent,
        output_pydantic=ProbeList,
    )
    return Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)


async def suggest_probes(
    session_id: str, variant_id: str, variant_params: dict, lang: str = "en"
) -> list[ProbeItem]:
    transcript = session_transcript(session_id)
    prior = prior_probes(session_id)
    crew = _build_crew(variant_id, variant_params, transcript, prior, lang)
    result = await asyncio.to_thread(crew.kickoff)
    pl: ProbeList = result.pydantic
    return pl.items[:3]
