"""Student-facing chat — Gemini (default) or Claude, chosen by LLM_PROVIDER.

The direct (non-review) student chat streams token-by-token, which CrewAI is not
suited for, so it uses a lightweight httpx client (`gemini_student` or
`claude_student`). The review-mode answer drafts and probe suggestions/grading go
through the CrewAI agent layer (see backend/agents/).
"""
import os
from typing import AsyncIterator

from backend import claude_student, gemini_student

PROVIDER = os.environ.get("LLM_PROVIDER", "gemini").strip().lower()
NAME = "claude" if PROVIDER == "anthropic" else "gemini"
KEY_ENV = claude_student.API_KEY_ENV if PROVIDER == "anthropic" else gemini_student.API_KEY_ENV


async def stream_chat(
    system_prompt: str, messages: list[dict], timeout: float = 60.0
) -> AsyncIterator[str]:
    client = claude_student if PROVIDER == "anthropic" else gemini_student
    async for tok in client.stream_chat(system_prompt, messages, timeout):
        yield tok
