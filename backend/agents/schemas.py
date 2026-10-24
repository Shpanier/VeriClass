"""Structured-output models for the agent tasks.

Using these as CrewAI Task `output_pydantic` replaces the old brittle regex/JSON
scraping (variants_gen._parse, cloud_llm._parse_suggestions) — CrewAI validates
the model output against these shapes and retries on mismatch.
"""
from pydantic import BaseModel, Field


class LevelText(BaseModel):
    """One help level, written in both languages (same meaning)."""
    en: str = Field(description="English text")
    he: str = Field(description="Hebrew text (keep code identifiers in Latin letters)")


class VariantSet(BaseModel):
    """The four teacher-reviewable answers, each bilingual: three Socratic levels
    and one direct (non-Socratic) answer."""
    nudge: LevelText
    normal: LevelText
    more: LevelText
    direct: LevelText


class ProbeItem(BaseModel):
    kind: str = Field(
        description="One of: Trace, Why, Counterfactual, Failure-mode, Bug-localization"
    )
    body: str = Field(description="The question to ask the student (1-3 sentences)")
    rationale: str = Field(description="One short line: what this question tests")


class ProbeList(BaseModel):
    items: list[ProbeItem]


class Grade(BaseModel):
    score: int = Field(description="0 = wrong/missing, 1 = partial, 2 = correct", ge=0, le=2)
    why: str = Field(description="One short line explaining the score")


class GradeRecommendation(BaseModel):
    """The LLM's judgment of how *wisely* the student used the tutor.

    Correctness is measured deterministically from the real run, so the judge
    only scores the process (goal #2, the main part) and explains it. The final
    blended grade + band are computed in Python from wise_use + correctness.
    """
    wise_use: int = Field(
        description=(
            "0-100. How well the student used the LLM to LEARN vs plug-and-play. "
            "High = specific questions about their own code/errors, gradual hints, "
            "real understanding shown in probes. Low = 'just give me the code', "
            "instant copy-paste, failed comprehension probes."
        ),
        ge=0, le=100,
    )
    rationale: str = Field(description="2-3 sentences justifying the wise_use score")
    signals: list[str] = Field(
        description="Concrete green/red flags observed, each prefixed '+ ' or '- '"
    )
