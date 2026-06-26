"""Dispatcher that picks an LLM provider for student- and teacher-facing calls.

  STUDENT_LLM — provider for student chat + grading
  TEACHER_LLM — provider for the teacher's review answer suggestions
                (the nudge/normal/more drafts); falls back to STUDENT_LLM

Each is one of:
  ollama   (default — local, privacy-preserving, slower, weaker Hebrew)
  gemini   (cloud — fast, strong multilingual; messages leave the machine)
"""
import os
from typing import AsyncIterator, Optional

BACKEND = os.environ.get("STUDENT_LLM", "ollama").lower()
# Teacher-side generation (review answer suggestions). Defaults to STUDENT_LLM
# when TEACHER_LLM is unset/blank, so existing setups are unchanged.
TEACHER_BACKEND = (os.environ.get("TEACHER_LLM", "").strip().lower() or BACKEND)


def _resolve(backend: Optional[str]) -> str:
    return (backend or BACKEND).lower()


async def stream_chat(
    system_prompt: str, messages: list[dict], timeout: float = 60.0,
    backend: Optional[str] = None,
) -> AsyncIterator[str]:
    if _resolve(backend) == "gemini":
        from backend import gemini_student
        async for tok in gemini_student.stream_chat(system_prompt, messages, timeout):
            yield tok
    else:
        from backend import ollama_client
        async for tok in ollama_client.stream_chat(system_prompt, messages, timeout):
            yield tok


async def grade_answer(
    question: str, answer: str, variant_params: dict, backend: Optional[str] = None
) -> tuple[int, str]:
    if _resolve(backend) == "gemini":
        from backend import gemini_student
        return await gemini_student.grade_answer(question, answer, variant_params)
    from backend import ollama_client
    return await ollama_client.grade_answer(question, answer, variant_params)
