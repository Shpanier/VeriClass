"""Grader agent — scores a student's answer to a comprehension probe.

Replaces gemini_student.grade_answer for the probe flow. Returns (score, why)
so routes/probes.py keeps its existing tuple-based handling.
"""
import asyncio
import json

from crewai import Agent, Crew, Process, Task

from backend.agents.llm import gemini_llm
from backend.agents.schemas import Grade


def _build_crew(question: str, answer: str, variant_params: dict) -> Crew:
    agent = Agent(
        role="answer grader",
        goal="Fairly score whether the student's answer shows real understanding.",
        backstory="You grade concisely and consistently on a 0-2 scale.",
        llm=gemini_llm(temperature=0.0),
        verbose=False,
        allow_delegation=False,
    )
    task = Task(
        description=(
            "Grade the student's answer to a targeted comprehension question.\n"
            "Score: 0 = wrong/missing, 1 = partially correct, 2 = correct.\n"
            f"Variant params: {json.dumps(variant_params)}\n\n"
            f"Question: {question}\n"
            f"Student answer: {answer}"
        ),
        expected_output="A Grade with score (0|1|2) and a one-line why.",
        agent=agent,
        output_pydantic=Grade,
    )
    return Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)


async def grade(question: str, answer: str, variant_params: dict) -> tuple[int, str]:
    crew = _build_crew(question, answer, variant_params)
    result = await asyncio.to_thread(crew.kickoff)
    g: Grade = result.pydantic
    return int(g.score), str(g.why)
