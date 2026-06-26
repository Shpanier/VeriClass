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
    """The three teacher-reviewable answer levels, each bilingual."""
    nudge: LevelText
    normal: LevelText
    more: LevelText


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
