"""Student-facing chat — Gemini only.

The direct (non-review) student chat streams token-by-token, which CrewAI is not
suited for, so it keeps using the lightweight httpx Gemini client in
`gemini_student`. The review-mode answer drafts and probe suggestions/grading go
through the CrewAI agent layer (see backend/agents/).
"""
from typing import AsyncIterator

from backend import gemini_student


async def stream_chat(
    system_prompt: str, messages: list[dict], timeout: float = 60.0
) -> AsyncIterator[str]:
    async for tok in gemini_student.stream_chat(system_prompt, messages, timeout):
        yield tok
