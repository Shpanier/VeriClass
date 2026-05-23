"""Dispatcher that picks the student-facing LLM at startup.

  STUDENT_LLM=ollama   (default — privacy-preserving, slower)
  STUDENT_LLM=gemini   (dev only — fast, but messages leave the local machine)
"""
import os
from typing import AsyncIterator

BACKEND = os.environ.get("STUDENT_LLM", "ollama").lower()


async def stream_chat(
    system_prompt: str, messages: list[dict], timeout: float = 60.0
) -> AsyncIterator[str]:
    if BACKEND == "gemini":
        from backend import gemini_student
        async for tok in gemini_student.stream_chat(system_prompt, messages, timeout):
            yield tok
    else:
        from backend import ollama_client
        async for tok in ollama_client.stream_chat(system_prompt, messages, timeout):
            yield tok


async def grade_answer(question: str, answer: str, variant_params: dict) -> tuple[int, str]:
    if BACKEND == "gemini":
        from backend import gemini_student
        return await gemini_student.grade_answer(question, answer, variant_params)
    from backend import ollama_client
    return await ollama_client.grade_answer(question, answer, variant_params)
