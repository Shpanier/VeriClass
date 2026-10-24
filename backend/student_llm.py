"""Student-facing chat — Gemini (default) or Claude, chosen by LLM_PROVIDER.

The direct (non-review) student chat streams token-by-token, which CrewAI is not
suited for, so it uses a lightweight httpx client (`gemini_student` or
`claude_student`). The review-mode answer drafts and probe suggestions/grading go
through the CrewAI agent layer (see backend/agents/).

"Ask again": when a reply isn't detailed enough, the student can send the same
question to a stronger Claude model (CLAUDE_STRONG_MODEL, default Sonnet 5.5;
empty turns the button off). It needs ANTHROPIC_API_KEY whatever LLM_PROVIDER is.
"""
import os
from typing import AsyncIterator

from backend import claude_student, gemini_student

PROVIDER = os.environ.get("LLM_PROVIDER", "gemini").strip().lower()
NAME = "claude" if PROVIDER == "anthropic" else "gemini"
KEY_ENV = claude_student.API_KEY_ENV if PROVIDER == "anthropic" else gemini_student.API_KEY_ENV
MODEL = claude_student.MODEL if PROVIDER == "anthropic" else gemini_student.MODEL

STRONG_MODEL = os.environ.get("CLAUDE_STRONG_MODEL", "claude-sonnet-5-5").strip()
# The smartest model, for the teacher's "regenerate with Opus" button in the
# review queue (empty turns that button off).
BEST_MODEL = os.environ.get("CLAUDE_BEST_MODEL", "claude-opus-5-5").strip()


def strong_available() -> bool:
    """The "ask again" model is configured, has a key, and isn't the model that
    already answered."""
    return bool(STRONG_MODEL and os.environ.get(claude_student.API_KEY_ENV)
                and STRONG_MODEL != MODEL)


def regen_models() -> list[dict]:
    """The models the teacher can have a question's four answers drafted again
    with: [{key: 'strong'|'best', model, label}], only those configured with a key."""
    if not os.environ.get(claude_student.API_KEY_ENV):
        return []
    out = []
    for key, model in (("strong", STRONG_MODEL), ("best", BEST_MODEL)):
        if model and model not in {m["model"] for m in out}:
            out.append({"key": key, "model": model, "label": model_label(model)})
    return out


def model_label(model: str) -> str:
    """'claude-sonnet-5-5' -> 'Sonnet 5.5' (for the student's button)."""
    parts = model.removeprefix("claude-").split("-")
    words = [p for p in parts if not p.isdigit()]
    numbers = [p for p in parts if p.isdigit() and len(p) < 8]  # skip date suffixes
    label = " ".join(w.capitalize() for w in words)
    return f"{label} {'.'.join(numbers)}".strip() if numbers else label


async def stream_chat(
    system_prompt: str, messages: list[dict], timeout: float = 60.0
) -> AsyncIterator[str]:
    client = claude_student if PROVIDER == "anthropic" else gemini_student
    async for tok in client.stream_chat(system_prompt, messages, timeout):
        yield tok


async def stream_strong(
    system_prompt: str, messages: list[dict], timeout: float = 120.0
) -> AsyncIterator[str]:
    async for tok in claude_student.stream_chat(system_prompt, messages, timeout, model=STRONG_MODEL):
        yield tok
